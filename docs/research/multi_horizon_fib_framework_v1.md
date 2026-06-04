# Multi Horizon Fib Framework V1

## Purpose

This defines the canonical research-only fib trading-horizon contract for Synth v2.
It is separate from strategy candidate `horizon_bucket` enums and must not be
reused as runtime strategy intent.

## Canonical Horizon Matrix

`fib_trading_horizon`:

- `SHORT`
  - `primary_interval=4h`
  - `supporting_intervals=[1h]`
  - `parent_horizon=MEDIUM`
  - `child_horizon=none`
  - live discovery/reconstruction window: about 60 days
- `MEDIUM`
  - `primary_interval=1d`
  - `supporting_intervals=[4h]`
  - `parent_horizon=LONG`
  - `child_horizon=SHORT`
  - live discovery/reconstruction window: about 365 days
- `LONG`
  - `primary_interval=1w`
  - `supporting_intervals=[1d]`
  - `parent_horizon=none`
  - `child_horizon=MEDIUM`
  - live discovery/reconstruction window: about 4 years

## Terminology Rules

- Trading horizon and candle interval are separate concepts.
- `parent_horizon` / `child_horizon` are canonical relationships.
- `HTF` / `LTF` may remain human-facing aliases only.
- Do not hardcode `HTF=1d`.

## Canonical Fib Levels

Retracement:

- `0.382`
- `0.500`
- `0.618`
- `0.786`

Extension:

- `1.272`
- `1.618`
- `2.000`
- `2.618`
- `3.618`
- `4.236`

## Output Contract

Every event/outcome row must carry:

- `fib_trading_horizon`
- `interval_code`
- `interval_role=PRIMARY|SUPPORT`
- `parent_horizon`
- `child_horizon`

## Boundaries

- research-only
- market-only
- account-agnostic
- raw candles are source of truth
- checkpoints are acceleration/cache only
- no dashboard wiring
- no selection, decision, planning, or execution writes

## Safety Markers

```text
db_writes=0
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
research_only=true
```
