# Execution Plan Leg V1

Status: design only  
Scope: future execution planner persistence  
Live trading permission: NOT_GRANTED  

## Purpose

`execution_plan_leg` is the future child table for multi-leg execution plans.

It supports:

- passive buy ladders
- passive exit ladders
- per-leg repricing controls
- per-leg wait limits
- per-leg fill monitoring
- clean separation between planner intent and executor order handling

This document is design-only.  
No migration is created here.

## Boundary

The execution planner may create plan legs only after `decision_gate` has approved an execution intent.

The executor may read plan legs and place / monitor orders.

The executor must not decide:

- target ladders
- fib/pro profile interpretation
- sleeve allocation
- strategy timing
- account permission
- duplicate exposure rules

## Proposed table

Table name:

    execution_plan_leg

Suggested columns:

| Column | Type | Meaning |
|---|---|---|
| `execution_plan_leg_id` | BIGINT PK | Surrogate leg id |
| `execution_plan_id` | BIGINT | Parent execution plan |
| `leg_index` | INT | Stable leg order inside plan |
| `side` | VARCHAR | BUY or SELL |
| `leg_type` | VARCHAR | PASSIVE_LIMIT, URGENT_LIMIT, PREPARE_ONLY |
| `target_price_eur` | DECIMAL | Planned limit/target price |
| `target_fraction` | DECIMAL | Fraction of plan target allocated to leg |
| `target_notional_eur` | DECIMAL | EUR notional allocated to this leg |
| `quantity_base` | DECIMAL | Base asset quantity for this leg |
| `post_only` | BOOLEAN | Whether order must be post-only |
| `time_in_force` | VARCHAR | GTC, IOC, etc. |
| `max_reprices` | INT | Per-leg reprice cap |
| `max_wait_seconds` | INT | Per-leg max wait |
| `max_chase_bps` | DECIMAL | Maximum permitted chase from original target |
| `min_spread_bps_for_capture` | DECIMAL | Minimum spread needed for passive capture |
| `escalation_to_urgent_limit` | BOOLEAN | Whether this leg may escalate |
| `abort_if_signal_invalidates` | BOOLEAN | Whether leg aborts on signal invalidation |
| `leg_state` | VARCHAR | IDLE, ACTIVE, FILLED, CANCELLED, ABORTED, etc. |
| `created_ts_utc` | DATETIME | Creation timestamp |
| `updated_ts_utc` | DATETIME | Update timestamp |

## State model

Initial proposed leg states:

    IDLE
    ACTIVE
    PLACED
    PARTIALLY_FILLED
    FILLED
    CANCEL_REQUESTED
    CANCELLED
    REPRICE_PENDING
    ESCALATED
    ABORTED
    EXPIRED

Planner-created preview legs currently use:

    IDLE

## Parent-child relationship

One `execution_plan` can have one or many `execution_plan_leg` rows.

Single-leg plans are still represented as one leg.

Examples:

    PASSIVE_ENTRY
      -> 1 BUY leg

    PASSIVE_EXIT
      -> 1 SELL leg

    PASSIVE_ENTRY_LADDER
      -> multiple BUY legs

    PASSIVE_EXIT_LADDER
      -> multiple SELL legs

## Quantity logic

BUY ladder:

    max_notional_eur
    -> target_fraction
    -> target_notional_eur
    -> quantity_base = target_notional_eur / target_price_eur

SELL ladder:

    quantity_base
    -> target_fraction
    -> leg quantity_base
    -> target_notional_eur = leg quantity_base * target_price_eur

## Execution philosophy

Default execution remains passive-first:

    BUY  = best_bid + 1 tick, post-only
    SELL = best_ask - 1 tick, post-only

Preview caveat:

    If the spread is exactly one tick, BUY = best_bid + 1 tick can equal best_ask.
    A real post-only executor must avoid crossing the spread and must handle this with
    venue-aware post-only validation or one-tick retreat logic.

Ladder legs use explicit target prices supplied by planner logic and then quantized to tick size.

## Required rule

Fib/pro/asset-exit-profile research can only influence execution after:

    asset_exit_profile candidate
    -> decision_gate validates position / sleeve / permission / duplicate safety
    -> execution_planner creates plan + legs
    -> executor places and monitors orders

Research profiles must not create plan legs directly.

## Not implemented yet

This document does not add:

- SQL migration
- repository writes
- executor support
- lifecycle support
- broker calls
- live/paper runtime integration

Next implementation step should be a schema/migration proposal only after this contract stays stable.
