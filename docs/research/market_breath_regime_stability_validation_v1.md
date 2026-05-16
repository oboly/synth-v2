# Market Breath Regime Stability Validation V1

## Purpose

Market Breath regime stability validation V1 maps how Market Breath V1 outcome behavior changes across rolling historical windows.

The purpose is not to prove that any phase behaves the same across all regimes. The working assumption is the opposite: all Market Breath phase behavior is regime-dependent unless proven otherwise. Universal phase behavior is not required for this research lane.

This pass classifies phase behavior by window/context as:

- regime-dependent context
- reset/bounce context in specific regimes
- late-risk / exhaustion context in specific regimes
- inverted behavior in some regimes
- low-sample / unusable
- characterized and parked

## Why this follows bucketed outcome analysis

The bucketed outcome analysis showed that first-pass results varied by phase and score context:

- `COLLAPSE_RESET` had sufficient outperforming buckets, but only as a candidate for further review.
- `EXHALE_EXPANSION` had sufficient underperforming buckets and no sufficient outperforming buckets in that pass.
- `OVERBREATH_EXTENSION` remained consistent with late-risk / exhaustion.
- `INHALE_ACCUMULATION` and `HOLD_COMPRESSION` remained too sparse for conclusions.

The next question is whether those findings persist across rolling windows or whether they are tied to specific market regimes. This pass therefore maps behavior across windows rather than looking for regime-independent phase rules.

## Input data

The runner reads:

- `obs_market_candle`
- `asset` metadata
- existing Market Breath V1 observation logic

It uses future candles only after each historical as-of timestamp to calculate research outcomes.

It does not read:

- A+ input
- PRO input
- symbolic labels
- account data
- broker data
- selection, advice, decision, execution, or order state

## Rolling window method

Default parameters:

```text
venue=bitvavo
interval=4h
lookback_candles=120
history_days=180
window_days=60
step_days=30
sample_step_hours=24
min_count=20
```

The runner:

1. Finds the latest usable as-of timestamp as the latest available candle minus 24 forward candles.
2. Builds rolling 60-day windows over the last 180 days, stepping by 30 days.
3. Selects one as-of sample per day using the same sampling method as the V1.1 calibration audit.
4. Computes existing Market Breath V1 observations for each as-of and eligible asset.
5. Computes 24-candle forward outcomes from future candles after each as-of.
6. Aggregates phase outcomes and selected key buckets per window.
7. Compares each phase/bucket against the `NEUTRAL_TRANSITION` baseline inside the same window.

Generated outputs:

```text
data/research/market_breath_regime_stability_validation_v1/window_summary_v1.jsonl
data/research/market_breath_regime_stability_validation_v1/stability_summary_v1.json
```

## Phase and bucket interpretation rules

Per-window phase hints:

- `OUTPERFORMS_BASELINE`: sufficient sample, average 24c return at least 1.0 percentage point above neutral, and positive rate at least 5 percentage points above neutral.
- `UNDERPERFORMS_BASELINE`: sufficient sample, average 24c return at least 1.0 percentage point below neutral, and positive rate at least 5 percentage points below neutral.
- `MIXED_OR_FLAT`: sufficient sample without clear outperformance or underperformance.
- `LOW_SAMPLE`: outcome available count below `min_count`.

Across-window hints:

- `CONSISTENT_OUTPERFORMER`: sufficient samples in at least two windows and outperformance in at least 60% of sufficient windows.
- `CONSISTENT_UNDERPERFORMER`: sufficient samples in at least two windows and underperformance in at least 60% of sufficient windows.
- `MIXED`: sufficient windows exist, but behavior is not consistent by the above thresholds.
- `LOW_SAMPLE`: fewer than two sufficient windows.

These hints describe repeated behavior across the sampled rolling windows only. They are not claims of regime-independent behavior.

## Limitations

- Research-only and market-only.
- No strategy edge is declared.
- No buys or sells are recommended.
- No runtime feature is created.
- No Market Breath V1 thresholds are changed.
- Rolling windows are still samples of available history, not proof of universal behavior.
- Phase behavior should be assumed regime-dependent unless later research proves otherwise.
- Low-sample phases and buckets are not usable for conclusions.

## Generated first-pass findings

Generated with:

```text
history_days=180
window_days=60
step_days=30
window_count=5
min_count=20
```

Phase stability summary:

```text
EXHALE_EXPANSION sufficient=5 outperform=0 underperform=3 avg_vs_neutral_24c=-0.799968 avg_vs_neutral_pos_rate=-8.795948 hint=CONSISTENT_UNDERPERFORMER
OVERBREATH_EXTENSION sufficient=3 outperform=0 underperform=3 avg_vs_neutral_24c=-4.125906 avg_vs_neutral_pos_rate=-28.876661 hint=CONSISTENT_UNDERPERFORMER
COLLAPSE_RESET sufficient=5 outperform=2 underperform=0 avg_vs_neutral_24c=0.054214 avg_vs_neutral_pos_rate=10.789553 hint=MIXED
INHALE_ACCUMULATION sufficient=0 hint=LOW_SAMPLE
HOLD_COMPRESSION sufficient=0 hint=LOW_SAMPLE
```

Interpretation:

- `COLLAPSE_RESET` is mixed over longer history. It should be treated as a regime-dependent reset/bounce context, not a failed label and not a signal. Any downstream review should separate context/window behavior before use.
- `EXHALE_EXPANSION` underperformed in 3 of 5 sufficient windows. It is a consistent late-risk / exhaustion candidate in the tested windows, not a universal rule.
- `OVERBREATH_EXTENSION` underperformed in all 3 sufficient windows. It is a late-risk / exhaustion candidate in the tested windows, with sample-size caution.
- `INHALE_ACCUMULATION` and `HOLD_COMPRESSION` remain low-sample / unusable for regime conclusions.

## Threshold calibration decision

Threshold calibration remains blocked.

Do not recalibrate thresholds just because behavior is regime-dependent. Reopen threshold calibration only if review finds a specific reachability or measurement problem, such as a phase that cannot be sampled enough to evaluate or a threshold gate that prevents intended measurement.

## Downstream path

Recommended next step:

```text
manual review of regime/window summaries
-> optionally add explicit regime labels later
-> decide whether Market Breath should be documented as a state/risk-timing classifier
-> keep threshold calibration blocked unless a specific measurement problem is found
-> no runtime promotion
```

## No strategy/runtime promotion

This output is not:

- a trading signal
- a buy or sell recommendation
- a selection modifier
- advice
- a decision permission layer
- execution intent
- an order plan
- a broker instruction
- a runtime feature

Safety markers:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
db_writes=0
selection_engine_changes=0
advice_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

## CLI

Compile check:

```bash
python -m py_compile src/research/run_market_breath_regime_stability_validation_v1.py
```

Dry run:

```bash
python -m src.research.run_market_breath_regime_stability_validation_v1 \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --history-days 180 \
  --window-days 60 \
  --step-days 30 \
  --sample-step-hours 24 \
  --output table
```

Write files:

```bash
python -m src.research.run_market_breath_regime_stability_validation_v1 \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --history-days 180 \
  --window-days 60 \
  --step-days 30 \
  --sample-step-hours 24 \
  --write-files \
  --output table
```
