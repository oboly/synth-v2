# Market Breath V1.1 Calibration Audit

## Purpose

Market Breath V1.1 is a calibration audit for the existing Market Breath V1 observation logic.

The audit runs the same V1 phase/state logic over many historical as-of timestamps and measures whether the resulting phase distribution is sane before any outcome validation, strategy design, feature promotion, or runtime integration.

The motivating V1 latest-run concern was a highly skewed phase distribution:

```text
COLLAPSE_RESET=23
NEUTRAL_TRANSITION=17
EXHALE_EXPANSION=1
HOLD_COMPRESSION=0
INHALE_ACCUMULATION=0
OVERBREATH_EXTENSION=0
```

V1.1 answers only one question:

> Does Market Breath V1 produce a plausible distribution of phases across historical 4h as-of windows, or are one or more phase thresholds likely unreachable or overly dominant?

## Why calibration comes before outcome validation

Outcome validation should not be run against a classifier whose labels may already be structurally biased.

If V1 almost never emits `INHALE_ACCUMULATION`, `HOLD_COMPRESSION`, `EXHALE_EXPANSION`, or `OVERBREATH_EXTENSION`, then later hit-rate or return validation would mostly measure the dominant labels rather than the intended breath cycle.

The order is therefore:

```text
Market Breath V1
-> V1.1 calibration audit
-> optional threshold calibration patch
-> market_breath_outcome_validation
-> only later possible strategy candidate
```

This lane does not decide whether the labels predict anything. It only checks whether the label distribution is usable enough to justify later validation.

## Market-only boundary

This audit is strictly:

- research-only
- market-only
- account-agnostic
- no A+ input
- no PRO input
- no symbolic labels
- no future outcomes
- no strategy logic
- no selection engine changes
- no advice engine changes
- no decision gate changes
- no execution planner changes
- no executor or order changes
- no broker calls
- no broker writes
- no order submission
- no DB writes
- no `run_chain_4h.sh` changes
- no paper/live branching
- no runtime promotion

The runner imports and reuses the existing Market Breath V1 observation functions. It does not modify V1 thresholds.

## Input data

The audit uses:

- `obs_market_candle`
- `asset` metadata
- existing Market Breath V1 formula and observation logic

Default runtime parameters:

```text
venue=bitvavo
interval=4h
lookback_candles=120
sample_step_hours=24
output_dir=data/research/market_breath_v1_1_calibration_audit
```

No A+ archive tables are queried.
No external research labels are queried.
No future candles beyond each as-of timestamp are queried.

## Sampling method

The runner selects historical as-of timestamps from available `obs_market_candle.close_ts_utc` values for the requested venue and interval.

Default behavior:

- use the latest available candle as `to_ts`
- use `to_ts - 60 days` as `from_ts`
- target one sample per day
- prefer 00:00 UTC when the sample step is 24 hours
- select the nearest available 4h close to each target timestamp
- de-duplicate selected close timestamps

For each selected as-of timestamp:

1. Fetch all eligible enabled/tradeable assets.
2. Fetch candles with `close_ts_utc <= asof_ts_utc` only.
3. Build Market Breath V1 observations for each eligible asset.
4. Count phase and state distributions.
5. Store per-asof phase ratios and average component scores.

## Metrics

Per-asof output file:

```text
data/research/market_breath_v1_1_calibration_audit/phase_distribution_by_asof_v1.jsonl
```

Each row contains:

- venue
- interval_code
- asof_ts_utc
- assets_processed
- phase_counts
- state_counts
- collapse_reset_pct
- neutral_transition_pct
- inhale_accumulation_pct
- hold_compression_pct
- exhale_expansion_pct
- overbreath_extension_pct
- insufficient_data_pct
- avg_compression_score
- avg_expansion_score
- avg_momentum_score
- avg_reversal_pressure_score
- avg_relative_strength_score
- avg_btc_alignment_score
- avg_breadth_alignment_score
- avg_market_breath_confidence
- top_collapse_reset_symbols
- top_neutral_transition_symbols
- top_exhale_expansion_symbols
- top_inhale_accumulation_symbols
- top_hold_compression_symbols
- top_overbreath_extension_symbols

Summary output file:

```text
data/research/market_breath_v1_1_calibration_audit/calibration_summary_v1.json
```

The summary contains:

- sample_count
- assets_per_sample_avg/min/max
- aggregate_phase_counts
- aggregate_phase_percentages
- days_with_zero_inhale
- days_with_zero_hold
- days_with_zero_overbreath
- days_with_zero_exhale
- days_with_collapse_reset_gt_50pct
- most_common_phase_per_day
- suspected_threshold_issues
- calibration_recommendations
- safety markers

## Interpretation rules

The audit reports possible threshold issues only. It does not change thresholds.

Possible reported issues:

- `COLLAPSE_RESET too dominant`
- `HOLD_COMPRESSION unreachable`
- `INHALE_ACCUMULATION unreachable`
- `OVERBREATH_EXTENSION unreachable`
- `EXHALE_EXPANSION too strict`
- `thresholds appear plausible`

Suggested interpretation:

- If `COLLAPSE_RESET` dominates most sampled days, inspect the reset gate before outcome validation.
- If a phase is zero across all sampled days, treat that phase as potentially unreachable under current V1 thresholds.
- If `EXHALE_EXPANSION` appears only rarely, inspect whether its momentum and relative-strength gate is too strict.
- If all phases appear with non-trivial frequency and no phase dominates excessively, thresholds may be plausible enough to proceed to outcome validation.

## Calibration result snapshot

Initial 60-day calibration output:

```text
sample_count=60
assets_per_sample=41
observations=2460

NEUTRAL_TRANSITION=88.333333%
EXHALE_EXPANSION=6.056911%
COLLAPSE_RESET=3.699187%
OVERBREATH_EXTENSION=1.178862%
INHALE_ACCUMULATION=0.650407%
HOLD_COMPRESSION=0.081301%
INSUFFICIENT_DATA=0.0%
```

Interpretation:

```text
Latest collapse-heavy run = likely temporary current 4h market-state skew.
60-day audit = not collapse-biased, but strongly neutral-dominant.
Selective phases = reachable, intentionally conservative, but sparse.
```

## TODO list

All open TODOs for this lane live here.

### Done

- Added Market Breath V1.1 calibration audit runner.
- Added Market Breath V1.1 research documentation.
- Generated and committed the initial 60-day calibration output files.
- Confirmed the lane uses Market Breath V1 logic without changing V1 thresholds.
- Confirmed the latest collapse-heavy V1 run is not representative of the 60-day distribution.

### Open — P0: clean up audit interpretation language

Status: open.

Goal: improve the audit diagnosis so it reports sparse phase behavior more accurately without implying immediate threshold changes.

Tasks:

- Add explicit diagnostic language for `NEUTRAL_TRANSITION` structural dominance.
- Add explicit diagnostic language for sparse-but-reachable phases.
- Distinguish intended selectivity from functional unreachability.
- Avoid treating rare phases as automatically wrong.
- Replace overly broad `thresholds appear plausible` output with a more precise summary when neutral dominance is high.

Suggested future wording:

```text
COLLAPSE_RESET not structurally dominant.
NEUTRAL_TRANSITION structurally dominant.
HOLD_COMPRESSION sparse / near-unreachable.
INHALE_ACCUMULATION sparse but reachable.
OVERBREATH_EXTENSION sparse but reachable.
No Market Breath V1 threshold changes applied.
```

### Open — P1: review whether neutral is intentionally a large rest bucket

Status: open.

Goal: decide whether `NEUTRAL_TRANSITION` should remain the dominant rest bucket or whether V1 should classify more observations into specific breath phases.

Review questions:

- Is `NEUTRAL_TRANSITION` expected to absorb most non-clean market states?
- Does an 88% neutral rate make the later outcome validation too sparse for several phases?
- Should phase-specific validation focus first on `EXHALE_EXPANSION` and `COLLAPSE_RESET`, where sample counts are more meaningful?
- Should `HOLD_COMPRESSION` be reviewed separately because it appears only 2 times in 2460 observations?

### Open — P2: optional separate threshold-calibration patch

Status: blocked until P0 and P1 are reviewed.

Goal: only if calibration review confirms a real measurement problem, open a separate patch for threshold calibration.

Rules:

- Do not change Market Breath V1 thresholds in this audit-output commit.
- Do not mix audit interpretation cleanup with threshold changes.
- Any threshold-calibration patch must remain research-only and market-only.
- Any threshold-calibration patch must rerun the same distribution audit before outcome validation.

### Open — P3: market_breath_outcome_validation

Status: blocked until P0/P1 are reviewed and P2 is either skipped or completed.

Goal: validate whether Market Breath labels have useful future market behavior.

Rules:

- No outcome validation in this V1.1 calibration audit lane.
- No strategy candidate until outcome validation exists.
- No selection, advice, decision, execution, broker, or order integration.

### Not TODO in this lane

These are explicitly out of scope:

- Change Market Breath V1 thresholds now.
- Add strategy logic.
- Add selection engine modifiers.
- Add advice engine behavior.
- Add decision-gate permissions.
- Add execution planner behavior.
- Add executor/order behavior.
- Add broker calls or broker writes.
- Add DB writes.
- Touch `run_chain_4h.sh`.
- Use A+, PRO, symbolic, or external labels.

## Known limitation

No future outcomes are used.

That is intentional. This audit does not measure predictive value, returns, drawdown, continuation, reversal, or strategy profitability.

It only measures whether the Market Breath V1 phase classifier produces a usable historical distribution from past as-of windows.

## CLI

Compile check:

```bash
python -m py_compile src/research/run_market_breath_v1_1_calibration_audit.py
```

Dry run:

```bash
python -m src.research.run_market_breath_v1_1_calibration_audit \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --sample-step-hours 24 \
  --output table
```

Write files:

```bash
python -m src.research.run_market_breath_v1_1_calibration_audit \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --sample-step-hours 24 \
  --write-files \
  --output table
```

Optional bounded window:

```bash
python -m src.research.run_market_breath_v1_1_calibration_audit \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --from-ts "2026-03-16T00:00:00Z" \
  --to-ts "2026-05-16T08:00:00Z" \
  --sample-step-hours 24 \
  --write-files \
  --output table
```

## No runtime promotion

The calibration audit output is not a runtime feature, not a selection modifier, not advice, not a decision permission layer, and not execution intent.

Promotion path remains blocked until the research sequence is complete:

```text
Market Breath V1.1 calibration audit
-> reviewed threshold calibration patch if needed
-> market_breath_outcome_validation
-> feature-candidate review
-> possible strategy candidate only after validation
```

Safety markers expected in output:

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
