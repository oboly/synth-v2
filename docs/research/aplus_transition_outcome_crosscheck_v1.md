# A+ Transition Outcome Crosscheck V1

## Purpose
Cross-check A+ label transitions against already generated forward market outcomes. This is a small-sample research measurement that asks whether a token's transition from one A+ exposure state to the next is followed by different forward return behavior.

This module measures transition/outcome association only. It does not produce trading advice, account permission, execution intent, or orders.

## Research-only boundary
- Research-only.
- Market-only.
- Account-agnostic.
- No trading advice, no buy/sell advice.
- No DB connections and no DB writes.
- No broker/API imports and no broker calls.
- No paper/live branching.
- No order, advice, or planning logic.
- No `selection`, `advice`, `decision_gate`, `execution_planner`, `executor`, `execution`, `live`, broker, or chain-script changes.

## Inputs
- `data/research/aplus_phase_exposure_stability_v1/phase_exposure_transition_rows_v1.jsonl`
- `data/research/aplus_multi_snapshot_outcome_validation_v1/label_outcomes_multi_snapshot_v1.jsonl`

The transition input is produced by the phase exposure stability lane. The outcome input is produced by the multi-snapshot outcome validation lane. This runner reads those local JSONL files only.

## Join rule
For each transition row, outcomes are attached by:

```text
transition.to_snapshot_pair_id = outcome.snapshot_pair_id
transition.token = outcome.token
outcome.horizon_hours = horizon
```

This means the measurement is aligned to the market outcome after the new transition state is visible. It does not use the prior snapshot's outcome as the result for the transition.

If an expected outcome row is absent, the joined row is counted as `MISSING_OUTCOME_ROW`. Rows with `NO_FUTURE_CANDLE` remain visible in coverage counts but are excluded from return metrics.

## Groups evaluated
Boolean change-flag groups:
- `table1_phase_changed`
- `table1_bias_changed`
- `table2_harmonic_phase_changed`
- `table2_offset_band_changed`
- `table2_quality_changed`
- `table2_extension_risk_changed`
- `combined_exposure_changed`

From/to transition-value groups:
- `table1_phase_transition`
- `table1_bias_transition`
- `table2_harmonic_phase_transition`
- `table2_offset_band_transition`
- `table2_quality_transition`
- `table2_extension_risk_transition`
- `combined_exposure_transition`

## Metrics
For each horizon and group value:
- `n_total`
- `n_valid`
- `n_no_future_candle`
- `n_missing_outcome_row`
- `avg_return_pct`
- `median_return_pct`
- `win_rate_pct`
- `avg_mfe_pct`
- `avg_mae_pct`
- `token_count`
- `snapshot_count`
- `snapshots_present`
- `tokens_present`
- `reliability_label`

## Reliability labels
| Label | Condition |
|---|---|
| `TOO_SMALL` | Fewer than 2 valid outcomes |
| `LOW_SAMPLE` | At least 2 valid outcomes but fewer than 2 snapshots |
| `POSITIVE_OBSERVATION` | At least 3 valid outcomes, at least 2 snapshots, positive average return, win rate at least 55% |
| `NEGATIVE_OBSERVATION` | At least 3 valid outcomes, at least 2 snapshots, negative average return, win rate at most 45% |
| `MIXED` | At least 2 valid outcomes and no positive/negative observation label |

These are exploratory research labels only. They are not feature candidates and do not permit runtime promotion.

## Script
`src/research/run_aplus_transition_outcome_crosscheck_v1.py`

CLI:
- `--transitions-path` (default: `data/research/aplus_phase_exposure_stability_v1/phase_exposure_transition_rows_v1.jsonl`)
- `--outcomes-path` (default: `data/research/aplus_multi_snapshot_outcome_validation_v1/label_outcomes_multi_snapshot_v1.jsonl`)
- `--output-dir` (default: `data/research/aplus_transition_outcome_crosscheck_v1`)
- `--min-n INT` (default `2`)
- `--output {table,json}` (default `table`)
- `--write-files` (writes output files when set)

## Output files
Output files are written only when `--write-files` is provided:

- `data/research/aplus_transition_outcome_crosscheck_v1/transition_outcome_crosscheck_rows_v1.jsonl`
- `data/research/aplus_transition_outcome_crosscheck_v1/transition_outcome_crosscheck_summary_v1.json`

No DB writes. No generated files are written without `--write-files`.

## Safety markers
- `db_writes = 0`
- `broker_calls = 0`
- `broker_writes = 0`
- `order_submission = 0`
- `live_orders = 0`
- `selection_engine_changes = 0`
- `advice_engine_changes = 0`
- `decision_gate_changes = 0`
- `execution_planner_changes = 0`
- `executor_changes = 0`
- `paper_live_logic = not_allowed`
- `account_state = not_allowed`
- `research_only = true`
- `market_only = true`
- `account_agnostic = true`

## Limitations
The current dataset has only a few A+ snapshot pairs and partial future-candle coverage. Results are exploratory and may change materially as new snapshots and forward outcomes arrive.

No runtime promotion is allowed. No feature candidate promotion is allowed. Any future use would require a separate preview/evaluation lane and must not bypass the normal account-aware permission and execution layers.
