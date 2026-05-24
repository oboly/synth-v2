# TODO — Position Rotation Preview

## Status

MVP implemented / parked follow-up lane.

## Purpose

Build a read-only, account-aware preview that evaluates whether existing positions should be held, reduced, exited, or considered for rotation into stronger candidates.

This lane exists because market-only paper advice can say a symbol is weak or blocked, but it must not decide what to do with an existing account position. Existing exposure belongs to an account-aware layer.

The MVP cockpit path, Odroid render orchestration, public current-price snapshot
display, and deterministic distance semantics are now implemented. This TODO
remains as the parking place for account-aware review refinements only; strategy
and backtest work belongs in `docs/research/current_strategy_audit_v1.md` and
`docs/todo/regime_research.md` and `docs/todo/strategy_candidates.md`.

## Current trigger

HYPE is currently visible as a useful test case:

```text
selection_state = WATCHLIST
setup_filter_state = FAIL
setup_filter_reason = MARKET_DAMAGE_CAUTION
paper_advice_action = WATCH_ONLY
leg_direction = DOWN
downside target / TP zone exists below the reaction zone
```

A+ Table 1 DB context also indicates weak structural context for HYPE, but A+ data must remain context only until validated.

## Target output

The preview classifies existing positions as:

```text
HOLD
REDUCE_CANDIDATE
EXIT_CANDIDATE
ROTATE_CANDIDATE
NO_POSITION_CONTEXT
```

The implemented/readout output includes:

- symbol
- position source and timestamp
- position size / value if available
- current paper advice state/action
- setup filter state and reason
- current leg direction
- reaction / entry zone
- downside or upside target zone
- invalidation level
- A+ Table 1 bucket when available
- candidate alternatives ranked by market-only strength
- rotation pressure reason codes
- current public market price from `market_price_snapshot`
- price age
- distance to entry, target, and risk/invalidation context

## Inputs

Candidate input sources to inspect and then wire explicitly:

```text
account / position snapshot tables
paper_advice_observation
trade_setup_filter_observation
selection_state
execution_zone_context
aplus_table1_report
aplus_table1_row
```

## Boundary

```text
read-only only
account-aware preview only
no broker writes
no order submission
no executor
no execution_planner changes
no selection_engine shortcut
no setup_filter behavior change
no decision_gate permission change
```

## Non-goals

- No automatic selling.
- No portfolio rebalancing execution.
- No order generation.
- No broker write permissions.
- No direct use of A+ Table 2 / breath rhythm in this lane for now.

## P1 — Schema/source inventory

Status: implemented for MVP cockpit.

Tasks:

- Identify canonical position/account snapshot tables.
- Identify latest usable position timestamp.
- Identify whether values are EUR notional, units, entry cost, and unrealized PnL.
- Confirm whether current private-read snapshots are available on devlap and Odroid.
- Confirm no private broker calls are needed to run preview from stored DB snapshots.

## P1 — Read-only preview runner

Status: implemented for MVP cockpit.

Proposed file:

```text
src/research/run_position_rotation_preview_v1.py
```

Expected behavior:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
db_writes=0
```

## P1 — Current-price and distance semantics

Status: implemented.

Implemented behavior:

- public market prices come from `market_price_snapshot`
- the renderer does not fetch Bitvavo directly
- dashboard columns include current price, price age, entry distance, target
  distance, and risk distance
- distance semantics are display/review context only and do not change scoring
  or better-candidate logic

## P1 — Target/risk-aware rotation classification

Status: implemented.

Implemented behavior:

- target state labels: `TARGET_REACHED`, `TARGET_PENDING`, `TARGET_UNKNOWN`
- risk state labels: `RISK_NEAR`, `RISK_OK`, `RISK_UNKNOWN`
- harvest review labels: `PARTIAL_TP_REVIEW`, `TARGET_REACHED_REVIEW`,
  `REDUCE_REVIEW_TARGET_REACHED`
- candidate lists are split into `review_references` and
  `rotation_destination_candidates`
- destination candidates exclude rows with reached targets, near risk,
  `APLUS_AVOID`, `DO_NOT_ADD`, `AVOID_NO_NEW_BUY`, `MARKET_DAMAGE_RISK`, or
  `setup_filter_state != PASS`

## P2 — Better-candidate comparison

Status: MVP implemented; future refinements only.

Use market-only candidates only. Do not move capital to a symbol purely because it is less bad than the current holding.

## Completed research baseline

Status: completed in separate market-only research lanes.

Completed follow-up baselines:

- `rotation_destination_outcome_audit_v1`
- `rotation_destination_historical_replay_audit_v2`
- v2 extra summary and CLI/docs cleanup work

These runs belong to research validation, not cockpit behavior changes.

## Next Strategy Work

Status: separate research lane.

The next work is not more cockpit plumbing. It is research validation and regime follow-up:

- rerun `rotation_destination_historical_replay_audit_v2` full-ish
- inspect symbol-by-confidence outcomes
- inspect symbol-by-curve-sanity outcomes
- run `market_regime_discovery_v1` full-ish
- compare discovered regimes with existing labels only after clustering

See:

```text
docs/todo/regime_research.md
```

## Parked

A+ Table 2 / breath rhythm module is explicitly parked for now.
