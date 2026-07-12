# TODO — Momentum Flow Scanner Matrix V1

## Status

```text
open P3 research / read-only scanner
non-blocking for Synth v2.23 P1 lanes
```

## Purpose

Build a compact multi-asset, multi-timeframe research scanner that finds candidates worthy of human review without promoting them to trading decisions.

Question owned by this lane:

```text
Which markets have enough target room, acceptable risk context, and supportive reset/momentum/flow evidence to justify research review?
```

Question not owned by this lane:

```text
What should the bot buy or execute now?
```

## Sources

- Existing `feat_candle` RSI, volume-ratio, dollar-volume, OBV, and slope features.
- Native map/target/invalidation context.
- Market price snapshots.
- FFG-style overview as external presentation inspiration only.
- `docs/research/market_rotation_pressure_v1.md` for Synth-native inferred rotation-pressure research.

External labels or curated lists are inputs to research provenance, not execution authority.

## Research contract

Working output:

```text
momentum_flow_scanner_snapshot_v1
```

Candidate fields:

```text
symbol / market / venue
observed timestamps and freshness
price
RSI: 1d / 4h / 1h / 15m
MFI: 1d / 4h / 1h / 15m
volume_ratio_20
dollar_volume_ratio_20
native map status
nearest valid target upside %
invalidation downside %
entry/reset research state
scanner bucket
reason codes
```

No server-baked relative age may be the sole freshness evidence.

## Minimum target-room gate

User-selected research threshold:

```text
nearest_valid_target_upside_pct >= 4.0
```

This is a minimum upside-to-target gate, not reward/risk.
Risk and invalidation remain separate and can reject a candidate that passes 4% target room.

## Allowed research states

```text
NO_EDGE
WATCH
RESET_READY
ENTRY_CANDIDATE_RESEARCH
OVERHEATED
ACCUMULATION_FLOW
DISTRIBUTION_RISK
DATA_UNAVAILABLE
```

Forbidden states:

```text
BUY_READY
AUTO_BUY
EXECUTE
FIX_LADDER
```

## P3-A — Deterministic MFI feature

Add `mfi_14` only as a market-data feature when this lane is selected for implementation.

Owner split:

```text
feature ETL       = deterministic candle calculation
feat_candle       = persisted feature value
scanner/read-model = read-only aggregation and presentation
```

Minimum tests:

- deterministic fixed fixture;
- zero-volume/flat-window handling;
- warmup nulls;
- bounded 0..100 values when calculable;
- no regression to existing RSI/ATR/volume features.

## P3-B — Read-only scanner builder

Build rows from canonical feature, price, and native-map sources.
Fail closed to `DATA_UNAVAILABLE` or `NO_EDGE` for stale/missing inputs.
Do not reconstruct candle features in reporting when a canonical feature source exists.

## P3-C — Replay/backtest validation

Before any promotion toward `selection_engine`, measure:

- bucket counts;
- forward returns;
- MFE/MAE;
- target-before-invalidation rate;
- time to target;
- false-positive rate;
- symbol/timeframe breakdown;
- random/control comparison;
- incremental value of MFI beyond RSI + volume features + map context;
- effect of the 4% target-room gate.

Any later feature promotion requires a separate explicit proposal and must remain market-only.

## P3-D — Read-only dashboard

Only after the read model and validation exist, add a compact matrix with filters/sorts for bucket, target room, reset readiness, flow, map freshness, and data availability.

## Relationship to FFG / rotation research

FFG-curated universes, external inflow/outflow narratives, and Synth-native rotation pressure may provide research context.
They do not directly set scanner states or trading actions.
Avoid duplicating a separate FFG execution lane; normalize external evidence into this research path or its canonical rotation-pressure source.

## Boundary

```text
research-only
market-only
account-agnostic
selection_engine unchanged unless a later validated promotion is approved
decision_gate unchanged
execution_planner unchanged
executor/agents unchanged
```

Forbidden:

- live trading;
- broker calls or writes;
- order submission;
- account-specific sizing;
- `BUY_READY` or execution language;
- automatic entry promotion;
- research-to-decision or research-to-execution shortcuts.

## Definition of done

- required RSI/MFI fields exist where data supports them;
- rows expose absolute timestamps and availability;
- target room and risk remain distinct;
- buckets have replay evidence;
- no promotion to selection or execution is implied.
