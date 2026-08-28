# Entry Quality forward validation v1

Issue: #568
Parent: #542
Status: research-only, market-only

## Purpose

Create deterministic forward market labels for immutable CQ shadow observations before adding or evaluating CQ v1 cross-market features.

This phase answers a narrower question first:

> Given the exact evidence identity scored by CQ v0, what happened to the asset later?

It does not alter selection, ranking, permissions or execution.

## Frozen registry

The preregistered contract lives at:

```text
config/research/entry_quality_forward_validation_v1.yaml
```

Version `1.0.0` freezes before outcome inspection:

```text
candle source = obs_market_candle
candle interval = 15m
horizons = 1h, 4h, 24h
base price = latest canonical candle close at or before observation as-of
future labels = canonical candles strictly after observation as-of
horizon end = inclusive
complete horizon = available canonical candle stream has advanced to or beyond horizon end
```

## Observation identity

Input observations come from:

```text
research_entry_quality_shadow
```

The existing `evidence_key` remains the immutable feature/evidence identity. The evaluator does not recreate Selection Engine features and does not replace the CQ v0 identity.

## Forward outcomes

For each observation and horizon:

```text
forward_return_pct = ((last future close / base close) - 1) * 100
mfe_pct            = ((max future high / base close) - 1) * 100
mae_pct            = ((min future low / base close) - 1) * 100
```

Future candles satisfy:

```text
observation_asof < candle.close_ts_utc <= horizon_end
```

A candle exactly at observation as-of may supply the base price, but may never be a future label.

A horizon may be marked `COMPLETE` only when the available canonical candle stream has demonstrably reached or passed that horizon end. A later candle timestamp may prove coverage for a shorter horizon, but the later candle's prices/highs/lows are never used in that shorter horizon's return, MFE or MAE.

Missing base, incomplete horizon coverage, or missing in-horizon future candles remains explicit:

```text
INSUFFICIENT_BASE_PRICE
INSUFFICIENT_HORIZON_COVERAGE
INSUFFICIENT_FUTURE_CANDLES
```

This prevents recent observations from receiving truncated labels that would change merely because more of the originally requested horizon elapsed later. No interpolation or fabricated candles are allowed.

## Target outcomes

Phase 1 shadow persistence currently carries PPP percentage + PPP provenance but not a canonical target price/reference-price pair sufficient to reconstruct the actual target touch from market candles.

Therefore v1 deliberately emits:

```text
target_outcome_status = UNAVAILABLE_NO_CANONICAL_TARGET_PRICE
```

It is forbidden to infer a target as:

```text
current_market_price * (1 + PPP)
```

because the PPP reference/entry basis may not equal the observation market close. Target-hit and time-to-target can be added only after a canonical target-price contract is available.

## Baseline columns retained

The forward dataset carries the Phase-1 comparison inputs unchanged:

```text
ppp_pct
trade_quality_score
selection_score
cq_v0
entry_strength_v0
```

Reserved Phase-2 fields remain unavailable initially:

```text
cq_v1 = null
entry_strength_v1 = null
```

This PR does not claim to implement CQ v1 itself.

## Outputs

Default research output directory:

```text
data/research/entry_quality_forward_validation_v1/
```

Files:

```text
forward_outcomes_v1.jsonl
summary_v1.json
```

The runner is read-only with respect to the database.

## Anti-leakage boundary

Hard rules:

- all CQ features/evidence exist at or before observation as-of;
- every outcome candle is strictly later than observation as-of;
- no later regime, breadth, BTC state, lifecycle or target result may be used as CQ input;
- a later candle timestamp may prove horizon coverage but its values cannot enter an earlier horizon's outcome;
- the evaluator computes labels only, never market features;
- target touch is unavailable until canonical target-price provenance exists.

## Next step

After this outcome lane is reviewed, #568 can audit candidate canonical cross-market producers for CQ v1. Only replayable, versioned upstream observations may enter the next frozen CQ v1 feature registry.

## Safety

```text
research_only=1
market_only=1
db_writes=0
production_ranking_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```
