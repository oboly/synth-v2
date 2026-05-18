# TODO — Position Rotation Preview

## Status

Open / active design lane.

## Purpose

Build a read-only, account-aware preview that evaluates whether existing positions should be held, reduced, exited, or considered for rotation into stronger candidates.

This lane exists because market-only paper advice can say a symbol is weak or blocked, but it must not decide what to do with an existing account position. Existing exposure belongs to an account-aware layer.

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

The preview should classify existing positions as:

```text
HOLD
REDUCE_CANDIDATE
EXIT_CANDIDATE
ROTATE_CANDIDATE
NO_POSITION_CONTEXT
```

The output should include:

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

Status: next.

Tasks:

- Identify canonical position/account snapshot tables.
- Identify latest usable position timestamp.
- Identify whether values are EUR notional, units, entry cost, and unrealized PnL.
- Confirm whether current private-read snapshots are available on devlap and Odroid.
- Confirm no private broker calls are needed to run preview from stored DB snapshots.

## P1 — Read-only preview runner

Status: blocked until schema/source inventory is done.

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

## P2 — Better-candidate comparison

Status: later.

Use market-only candidates only. Do not move capital to a symbol purely because it is less bad than the current holding.

## Parked

A+ Table 2 / breath rhythm module is explicitly parked for now.

