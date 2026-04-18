# SYNTH v2 — Sleeves + PREPARE + Paper PnL Bundle

## Goal
Add:
- PREPARE state between WATCH and ENTER_LONG
- portfolio sleeves
- default sleeve agents
- lot-based paper accounting
- strategy attribution and daily metrics
- clean flow through:
  selection -> sleeve agents -> decision -> risk -> portfolio -> execution_intent

## Canonical sleeves
- CORE         = 0.30
- SWING        = 0.35
- TACTICAL     = 0.25
- EXPERIMENTAL = 0.10

## Canonical agent defaults
- CORE         -> core_trend
- SWING        -> swing_rotation
- TACTICAL     -> tactical_momentum
- EXPERIMENTAL -> experimental_misc

## Canonical state ladders
CORE / SWING:
- WATCH -> PREPARE -> ENTER_LONG -> HOLD -> REDUCE -> EXIT

TACTICAL:
- WATCH -> SCALP_ONLY -> HOLD -> EXIT

## Key design rules
1. Sleeves own capital budgets.
2. Agents propose; allocator approves.
3. PREPARE belongs to structural sleeves, not tactical.
4. Lots are the accounting unit.
5. Paper execution updates lots using target deltas.
6. Market response can be fast; strategy review stays slow/versioned.

## Fast loop
Recommended every market refresh / minute:
- read latest signals
- run sleeve agents
- allocate targets
- write decision / risk / portfolio targets
- generate execution intents
- update paper positions and snapshots

## Slow loop
Recommended daily aggregation:
- realized PnL
- unrealized PnL
- per-sleeve metrics
- per-strategy metrics
- PREPARE transition success / failure

## Important v1 simplification
This bundle does not assume live exchange fills.
Paper execution uses:
- latest price
- target fraction delta
- wallet equity in EUR

That is enough to build the accounting backbone now.
