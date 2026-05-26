# Paper Advice Manual Trading Cockpit V1

## Status

Canonical direction note.

No code change.
No runtime permission change.
No paper execution.
No live execution.

## Purpose

Define the near-term role of paper advice as a:

- manual trading co-pilot
- strategy candidate inbox
- read-only decision-support cockpit

The goal is to make paper advice useful enough for practical manual trading
review before any paper execution, simulated fills, or live execution work is
considered.

This cockpit is the human-readable review layer for:

- entries
- reloads
- trims
- holds
- wait/avoid states
- invalidated/stale map states

## Canonical Role

Paper advice should currently be read as:

```text
market/setup/context interpretation
-> candidate inbox
-> manual human review
-> manual trade outside Synth execution
```

Not:

```text
paper advice
-> paper execution
-> fills
-> broker order path
```

Paper advice is the practical bridge between market-only candidate generation
and later account-aware decision/execution design, but it is not itself that
later layer.

## Non-Goals

This cockpit is not:

- paper execution
- simulated fills
- a fake broker
- an order queue
- an account allocator
- a decision-gate replacement
- a live execution surface

Specifically out of scope:

- order creation
- paper order submission
- fill simulation
- position sizing
- capital reservation
- account exposure resolution
- automated trim/reload execution
- live trading enablement

## Architecture Boundary

Correct flow:

```text
market observation
-> feature
-> signal
-> market-only candidate/ranking
-> paper advice cockpit / candidate inbox
-> future decision_gate permission
-> future execution_planner intent
-> future executor order handling
```

Boundary rules:

- `selection_engine` remains market-only and account-agnostic.
- paper advice may show review actions and context.
- paper advice may read existing read-only market/context snapshots.
- paper advice may not submit orders.
- paper advice may not allocate capital.
- paper advice may not create fills.
- paper advice may not bypass `decision_gate`.
- `decision_gate` remains the future account-aware permission layer.
- `execution_planner` and `executor` remain untouched.

## Candidate Inbox Model

The cockpit should be treated as a strategy candidate inbox, not a raw symbol
watchlist.

Core rule:

```text
asset != strategy
```

Correct inbox unit:

```text
candidate = (
    symbol,
    strategy_family,
    horizon_bucket,
    setup_context,
    validation_state,
)
```

The dashboard/inbox row shape should be able to show:

- `symbol`
- `strategy_family`
- `horizon_bucket`
- `paper_action`
- `direction_label`
- `confidence_score` or comparable score if available
- `reasons`
- `risk/invalidation`
- `target/reaction_zone`
- `freshness`
- `source_modules`
- missing inputs explicitly marked as missing

This means one asset may later surface multiple independent paper-review rows
for different strategy families or horizons without forcing them into one
blended asset verdict.

## Manual Action Labels

Canonical manual paper-review actions:

- `BUY_REVIEW`
- `RELOAD_REVIEW`
- `TRIM_REVIEW`
- `HOLD`
- `WAIT`
- `AVOID`
- `INVALIDATED`

Interpretation:

- `BUY_REVIEW`: current market/setup context is constructive enough for manual entry review
- `RELOAD_REVIEW`: retest/reclaim/support context favors manual add/reload review
- `TRIM_REVIEW`: target/extension/harvest context favors manual trim review
- `HOLD`: no stronger manual action is surfaced from current inputs
- `WAIT`: context is incomplete, neutral, early, or not actionable yet
- `AVOID`: current context blocks new exposure review
- `INVALIDATED`: the displayed map is stale or invalidated and requires upstream recompute

These are review labels only.

They are not:

- order instructions
- execution permission
- sizing permission
- account approval

## Direction Labels

Direction-first display labels may be used so the cockpit reads quickly:

- `bullish short-term`
- `bullish medium-term`
- `neutral / wait`
- `bearish risk`
- `trim candidate`
- `reload candidate`

These are display semantics for human scanning, not new strategy logic.

## Context / Reason Fields

The cockpit should surface the strongest currently available reasons without
inventing unavailable signals.

Preferred reason/context fields:

- fibo / zone context
- reclaim / retest context
- regime context
- Market Breath or breathline context when explicitly available
- setup-fail reason
- lifecycle / recompute state
- target / reaction zone
- invalidation / risk reason
- freshness / timestamp

Important interpretation rule:

```text
missing != neutral
```

If a required field is unavailable, the cockpit should show:

- missing zone map
- missing invalidation
- missing current price
- missing breath/context overlay
- missing freshness input

It must not silently downgrade missing inputs into a neutral view.

## Strategy Families That May Later Feed The Inbox

Examples of valid strategy-family labels for future inbox rows:

- `FIBO_ZONE_RECLAIM_V1`
- `SPIKE_HARVEST_V1`
- `BREATHLINE_CONTEXT_V1`
- `REGIME_CONTEXT_V1`
- `ROTATION_REVIEW_V1`

Interpretation guidance:

- `FIBO_ZONE_RECLAIM_V1`: zone/reclaim/retest context
- `SPIKE_HARVEST_V1`: extension/harvest/trim context
- `BREATHLINE_CONTEXT_V1`: compass/context only unless separately validated
- `REGIME_CONTEXT_V1`: regime/readiness context only
- `ROTATION_REVIEW_V1`: existing-position or relative-strength review context

These labels belong in the candidate inbox only after they are explicitly
defined and validated. Naming a family does not promote it to execution.

## What Belongs Later In Paper Execution / Simulated Fills

The following work belongs in a later lane and not in this cockpit:

- paper order objects
- paper execution intent
- simulated entry/exit fills
- fill price rules
- slippage rules
- partial fill behavior
- cash / position state transitions
- PnL ledger updates
- account exposure tracking
- cooldown and duplicate-order prevention
- order lifecycle state machines

That future path, when allowed, is:

```text
candidate inbox
-> decision_gate paper permission
-> execution_planner paper intent
-> isolated simulated-fill engine
-> paper ledger / reporting
```

Until that lane is explicitly opened, paper advice remains upstream of it.

## Safety Guarantees

Paper advice manual cockpit must preserve:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
live_trading=false
paper/manual only
```

Operational guarantees:

- no broker writes
- no order submission
- no executor activation
- no timer changes required for this document
- no account mutation
- no hidden paper-trading enablement

## Relation To Existing Docs

This direction is consistent with:

- `paper_candidate_contract_v1`: research/paper boundary only
- `strategy_candidate_horizon_buckets_v1`: asset is not strategy
- `current_strategy_audit_v1`: current runtime is a paper-navigation stack
- Odroid runtime docs: read-only cockpit first
- zone / Market Breath / Breath Curve TODOs: context before execution

## Recommended Next Step

Before any paper execution or simulated-fill work:

```text
finish the manual paper advice cockpit
-> make strategy candidate inbox rows explicit
-> improve human-readable reasons / missing markers / freshness
-> validate one strategy-family readout path at a time
```

That is the correct next implementation direction.
