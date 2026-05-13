# Paper Advice Policy v1

## Status

Market-only paper/navigation layer.

This layer produces per-coin advice observations for dashboard and manual navigation.

It does not place orders.

## Scope

Allowed:

- read latest `selection_state`
- read latest `trade_setup_filter_observation`
- read latest `trade_setup_policy_preview_observation`
- read latest `execution_zone_context`
- read latest A+ canonical Table 1 raw snapshot
- write `paper_advice_observation`

Forbidden:

- broker calls
- broker writes
- order submission
- decision_gate writes
- execution_planner writes
- executor calls
- account-aware allocation
- live trading

## Data flow

```text
selection_engine_v2
trade_setup_filter_v1
trade_setup_policy_preview_v1
execution_zone_context
A+ canonical Table 1
        ↓
paper_advice_policy_v1
        ↓
paper_advice_observation
        ↓
dashboard / manual navigation
Advice states
state	meaning
PAPER_READY	paper test allowed by market setup and A+ support
WATCH_CORE	watchlist candidate with A+ canonical support
WATCH	market watchlist candidate without full permission
CORE_CONTEXT	A+ supported but market setup not ready
NO_NEW_BUY	A+ avoid/collapse context blocks adding
BLOCK_24H	trade setup policy blocks 24h entry
AVOID	market and A+ both reject
WAIT	no edge permission
Architecture boundary

This is not selection_engine.

This is not decision_gate.

This is not execution_planner.

This is not executor.

It is a dashboard-facing observation layer.
