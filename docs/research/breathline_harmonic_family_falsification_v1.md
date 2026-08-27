# Breathline harmonic-family falsification v1

Status: preregistered research-only protocol for GitHub Issue #533.

This document and `src/research/breathline_harmonic_family_registry_v1.py`
form the frozen preregistration boundary. Outcome analysis must not alter these
choices after seeing #533 results.

## Input boundary

Initial empirical inputs are the immutable #534 RENDER/TAO canonical Bitvavo 4h
Breathline artifacts produced by the unchanged #417 tracker.

Required source objects per asset:

```text
cycle_ledger.jsonl
summary.json
#534 run_manifest.json
source candle SHA256 provenance
```

The #417 tracker and frozen checkpoint grids are inputs only. #533 must not tune
or modify them.

## Frozen duration family

```text
3
6
9
12
21
42
63
105
126
147
days
```

`21d` is one prior/baseline candidate, never a forced cycle duration.

`10.5d` remains a separate HALF_PHASE_SPLIT research concept and is not inserted
into the normal family or the #417 normal phase-offset grid.

## Frozen phase markers

```text
first_high   0.236
first_low    0.382
second_high  0.500
recognition  0.618
ignition     0.786
main_pulse   1.000
extension    1.272
```

## Frozen split and walk-forward contract

- Order cycles chronologically by `start_ts`.
- Preserve per-asset results before any pooled result.
- Discovery fraction: 70% per asset.
- Holdout: final 30% per asset.
- Pooled holdout is the union of the already-defined per-asset holdouts.
- Expanding walk-forward may use only prior cycles whose `outcome_as_of_ts` is
  strictly earlier than the current checkpoint `feature_as_of_ts`.
- Minimum prior completed cycles for asset-history baseline: 8.
- Minimum prior completed cycles for pooled-history baseline: 12.

No holdout result may alter the registry, candidate family, nulls, metrics,
thresholds, split, or correction method.

## Lane A: retrospective structural fit

Lane A is descriptive only. It may use the completed cycle's realized
`observed_cycle_length_days` because it makes no predictive claim.

For every cycle and every duration candidate retain:

```text
observed_cycle_length_days
candidate_duration_days
absolute_duration_error_days
relative_duration_error
nearest_candidate_duration_days
nearest_candidate_absolute_error_days
nearest_candidate_relative_error
fixed_21d_absolute_error_days
fixed_21d_relative_error
```

No binary `close enough` duration threshold is allowed in v1.

For each observed node retain continuous phase fit:

```text
expected_node_ts = start_ts + observed_cycle_length_days * node_ratio
node_timing_residual_days = observed_node_ts - expected_node_ts
observed_phase_position = (observed_node_ts - start_ts) / observed_cycle_length_days
phase_position_residual = observed_phase_position - node_ratio
```

Missing nodes, FAILED cycles, UNCLEAR cycles, reset cycles and phase-shift cycles
remain in the input population. Missing node fields remain missing rather than
being fabricated.

### Lane A phase null

For each completed cycle, shift all observed internal phase positions by one
seeded `U[0,1)` circular offset modulo 1. This preserves relative within-cycle
node spacing while breaking alignment to the fixed marker positions.

The random stream is deterministic from seed `533001` plus population/cycle
identity. Use 2000 null permutations.

## Lane B: point-in-time predictive validation

Lane B may use only information available at or before the current checkpoint.
Realized full-cycle duration and later outcomes are evaluation fields only.

Checkpoints:

```text
recognition 0.618
ignition    0.786
```

For duration candidate `D` at checkpoint `c`:

```text
checkpoint_elapsed_days = checkpoint_ts - start_ts
expected_checkpoint_elapsed_days = D * checkpoint_ratio
checkpoint_alignment_absolute_error_days = abs(
    checkpoint_elapsed_days - expected_checkpoint_elapsed_days
)
alignment_score = -checkpoint_alignment_absolute_error_days
```

Larger alignment score is better.

Recognition/ignition "accuracy" is defined as continuous alignment MAE. There is
no binary close-enough threshold in v1.

The per-cycle family selector is frozen as:

```text
candidate with minimum current checkpoint alignment absolute error
```

Ties resolve by ascending frozen candidate order.

### Frozen baselines

```text
fixed_21d
asset_prior_median_completed_duration
pooled_prior_median_completed_duration
```

Historical medians may include only cycles whose `outcome_as_of_ts` is strictly
earlier than the current checkpoint `feature_as_of_ts`.

If the minimum history requirement is not satisfied, emit
`INSUFFICIENT_HISTORY`; do not backfill with future data or another baseline.

### Later binary outcomes

For each fixed duration candidate, evaluate checkpoint alignment score against:

```text
main_pulse_confirmed
extension_confirmed
```

using tie-aware ROC AUC. AUC uses only future outcome labels for evaluation.

### Later timing outcomes

For family-selected and baseline durations:

```text
predicted_event_ts = start_ts + predicted_duration * event_ratio
```

Evaluate continuous absolute timing error for:

```text
main_pulse 1.000
extension  1.272
```

when those events exist. Missing future events remain missing and are also
represented in continuation/extension/failure-rate outputs.

### Duration prediction

The predicted duration is the point-in-time family-selected duration or one of
the frozen baseline durations. Realized `observed_cycle_length_days` is used only
after prediction is frozen to compute absolute and relative error.

### Market outcome metrics

At recognition and ignition retain/report where defined:

```text
continuation_probability
extension_probability
false_extension_rate
MFE
MAE
time_to_main_pulse
time_to_extension
```

These are evaluation fields, not candidate-selection inputs.

## Frozen null controls

2000 deterministic permutations, seed `533001`.

1. Lane A phase circular-shift null described above.
2. Lane B binary-outcome permutation within asset/checkpoint after predictor
   rows are frozen.
3. Lane B duration-outcome permutation within asset after PIT duration
   predictions are frozen.

Permutation p-value:

```text
(1 + count(null statistic at least as favorable as observed)) / (N + 1)
```

The direction of `favorable` follows the metric: higher AUC is better, lower
absolute error is better.

## Frozen multiple-comparison correction

Method: Holm-Bonferroni, alpha `0.05`.

Duration-family member tests are corrected across the 10 fixed duration
candidates within each:

```text
population x checkpoint x future-outcome x metric family
```

Phase-marker tests are corrected across the 7 fixed phase markers within each
population for Lane A structural phase fit.

Do not pool unrelated hypothesis families into one post-hoc correction bucket and
do not split a preregistered family after seeing results.

## Required outputs

At minimum:

```text
registry.json
lane_a_cycle_residuals.jsonl
lane_a_phase_residuals.jsonl
lane_a_summary.json
lane_b_checkpoint_rows.jsonl
lane_b_candidate_tests.jsonl
lane_b_summary.json
run_manifest.json
```

Reports must remain per asset first, then pooled.

## Provenance

Every run records:

```text
registry version and registry SHA256
#417 tracker model version
#534 run id and analysis commit SHA
input ledger paths and SHA256
input summary paths and SHA256
source candle SHA256
analysis commit SHA
frozen duration/phase/baseline/null registries
split contract
multiple-comparison method
run timestamp
CLI
```

## Safety / architecture boundary

```text
research_only=true
market_only=true
account_awareness=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_calls=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_trading_permission=0
production_db_writes=0
production_schema_changes=0
runtime_activation=0
decision_gate=none
execution_planner=none
executor=none
```

No result from this study creates BUY/SELL intent, sizing, account permission,
execution intent, order handling, production runtime activation, or a production
selection feature.
