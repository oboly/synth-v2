# A+ Table 1 / Table 2 Interaction Discovery V1

## Purpose
Discover which combinations of A+ Table 1 and Table 2 labels correlate with forward market outcomes across the normalized paired snapshot dataset. This is a systematic search for candidate predictive interactions — measurement only, not a validation conclusion.

## Table 2 as a dynamic harmonic overlay
Table 2 is not a static token identity profile. Phase exposure stability analysis confirmed that Table 2 fields (especially `harmonic_phase` and `offset_band`) are highly dynamic across snapshots (4.9% and 9.8% stability rates respectively). This is expected and acceptable: Table 2 is a snapshot-level harmonic overlay describing where a token sits in its current wave structure, not a fixed characteristic. Its value for interaction discovery lies precisely in how it conditions or modifies the signal from Table 1 labels at each snapshot moment.

## Research-only boundary
- Research-only.
- Market-only.
- Account-agnostic.
- No trading advice, no buy/sell advice.
- No DB writes, no broker/API calls.
- No paper/live branching.
- No `selection_engine`, `advice_engine`, `decision_gate`, `execution_planner`, `executor` changes.
- Does not touch `run_chain_4h.sh`, policy_router files, or `paper_advice_policy_v1`.

## Input
`data/research/aplus_multi_snapshot_outcome_validation_v1/label_outcomes_multi_snapshot_v1.jsonl`

- Total rows: 366 (122 tokens × 3 horizons)
- Valid rows (outcome_status=VALID): 121
  - 4h: 81 valid rows — snapshots `20260514_1315_1256` (40) + `20260515_1244` (41)
  - 24h: 40 valid rows — snapshot `20260514_1315_1256` only
  - 72h: 0 valid rows — all NO_FUTURE_CANDLE
  - 2026-05-16: no valid rows at any horizon (forward candles not yet in DB)

Only `outcome_status=VALID` rows are used for return metrics. No_future_candle coverage is reported separately in the summary.

## Interaction groups (39 definitions)

### Single-field groups (14)
`table1_phase`, `table1_coherence`, `table1_field`, `table1_geometry`, `table1_structural_role`, `table1_expansion_quality`, `table1_anchor_strength`, `table1_strategic_bias`, `table2_harmonic_phase`, `table2_phase_state`, `table2_offset_band`, `table2_drift_direction`, `table2_quality`, `table2_extension_risk`

### Two-field interactions (19)
Cross-table: `table1_phase × table2_harmonic_phase`, `table1_phase × table2_offset_band`, `table1_phase × table2_quality`, `table1_phase × table2_extension_risk`, `table1_coherence × table2_quality`, `table1_coherence × table2_drift_direction`, `table1_field × table2_harmonic_phase`, `table1_geometry × table2_quality`, `table1_structural_role × table2_harmonic_phase`, `table1_structural_role × table2_offset_band`, `table1_expansion_quality × table2_quality`, `table1_anchor_strength × table2_quality`, `table1_strategic_bias × table2_harmonic_phase`, `table1_strategic_bias × table2_offset_band`, `table1_strategic_bias × table2_extension_risk`

Intra-Table2: `table2_harmonic_phase × table2_offset_band`, `table2_harmonic_phase × table2_drift_direction`, `table2_offset_band × table2_quality`, `table2_quality × table2_extension_risk`

### Three-field interactions (6)
`table1_phase + table1_coherence + table2_harmonic_phase`, `table1_phase + table1_strategic_bias + table2_harmonic_phase`, `table1_strategic_bias + table2_harmonic_phase + table2_offset_band`, `table1_coherence + table2_quality + table2_extension_risk`, `table1_structural_role + table2_quality + table2_extension_risk`, `table1_field + table2_harmonic_phase + table2_drift_direction`

## Metrics per group-value combination
For each horizon × group-definition × unique field-value combination:
- `n_total`, `n_with_return`, `avg_return_pct`, `median_return_pct`, `win_rate_pct`
- `avg_mfe_pct`, `avg_mae_pct`
- `token_count`, `snapshot_count`, `snapshots_present`, `tokens_present`
- `reliability_label`

## Reliability labels
| Label | Condition |
|---|---|
| `TOO_SMALL` | n_with_return < 2 |
| `LOW_SAMPLE` | n_with_return ≥ 2, snapshot_count < 2 |
| `WATCH_CANDIDATE` | n_with_return ≥ 3, snapshot_count ≥ 2, avg_return > 0, win_rate ≥ 55% |
| `NEGATIVE_CANDIDATE` | n_with_return ≥ 3, snapshot_count ≥ 2, avg_return < 0, win_rate ≤ 45% |
| `MIXED` | n_with_return ≥ 2, does not qualify for WATCH or NEGATIVE |

Because the dataset is small, all reliability labels are research labels only. No promotion is allowed at this stage.

## Current findings (run 2026-05-16)

### Output counts
- Group definitions evaluated: 39
- Metric rows written: 757 (groups × unique value combinations × horizons with valid data)
- WATCH_CANDIDATE: 65
- NEGATIVE_CANDIDATE: 86
- MIXED: 100
- LOW_SAMPLE: 506

### Top WATCH_CANDIDATE groups (4h, 2 snapshots — the only horizon with multi-snapshot coverage)
| Group | Values | n | snaps | avg_return | win_rate |
|---|---|---|---|---|---|
| `table1_phase × table2_extension_risk` | forming\|high | 7 | 2 | +3.563% | 85.7% |
| `table1_phase × table2_quality` | forming\|mixed | 15 | 2 | +3.141% | 86.7% |
| `table1_coherence × table2_drift_direction` | moderate\|forward_drift | 14 | 2 | +3.019% | 85.7% |
| `table1_strategic_bias × table2_extension_risk` | accumulation\|high | 7 | 2 | +2.823% | 85.7% |
| `table1_phase + table1_coherence + table2_harmonic_phase` | forming\|moderate\|forming_1000 | 8 | 2 | +2.567% | 75.0% |
| `table2_quality × table2_extension_risk` | mixed\|high | 9 | 2 | +2.394% | 66.7% |
| `table1_structural_role × table2_offset_band` | speculative\|+9 | 4 | 2 | +2.184% | 75.0% |
| `table1_expansion_quality × table2_quality` | moderate\|mixed | 14 | 2 | +2.107% | 78.6% |
| `table1_structural_role + table2_quality + table2_extension_risk` | confirmer\|clean\|low | 6 | 2 | +2.014% | 83.3% |
| `table1_field × table2_harmonic_phase` | transition\|forming_0618 | 3 | 2 | +1.996% | 66.7% |

### Top NEGATIVE_CANDIDATE groups (4h)
| Group | Values | n | snaps | avg_return | win_rate |
|---|---|---|---|---|---|
| `table1_anchor_strength × table2_quality` | moderate\|mixed | 15 | 2 | -0.504% | 40.0% |
| `table1_phase × table2_offset_band` | confirmed\|0 | 9 | 2 | -0.501% | 44.4% |
| `table2_harmonic_phase` | confirmed_1000 | 12 | 2 | -0.451% | 41.7% |
| `table1_structural_role + table2_quality + table2_extension_risk` | speculative\|mixed\|moderate | 7 | 2 | -0.417% | 42.9% |
| `table1_anchor_strength × table2_quality` | strong\|clean | 27 | 2 | -0.399% | 44.4% |

### Strongest single-field signals (24h, 1 snapshot — LOW_SAMPLE)
| Field | Value | n | avg_return | win_rate |
|---|---|---|---|---|
| `table1_strategic_bias` | caution | 3 | +6.712% | 100% |
| `table2_harmonic_phase` | forming_1000 | 6 | +2.987% | 83.3% |
| `table1_expansion_quality` | strong | 14 | +2.678% | 92.9% |

Note: 24h results are from one snapshot (2026-05-14) only — all LOW_SAMPLE. The WATCH_CANDIDATE `table1_strategic_bias=caution` at 4h (n=5, 2 snapshots, +1.959%, 60% win rate) is the only single-field group with multi-snapshot coverage.

### Strongest 2-field interactions (24h, LOW_SAMPLE)
| Group | Values | n | avg_return | win_rate |
|---|---|---|---|---|
| `table1_field × table2_harmonic_phase` | expansion\|forming_1000 | 2 | +10.526% | 100% |
| `table1_phase × table2_offset_band` | forming\|0 | 2 | +9.022% | 100% |
| `table1_expansion_quality × table2_quality` | strong\|mixed | 3 | +6.660% | 100% |

All highest-returning 2-field groups are LOW_SAMPLE (24h, 1 snapshot). The highest 4h WATCH_CANDIDATE two-field is `table1_phase × table2_extension_risk=forming|high` (+3.563%, 86.7% win, 2 snapshots).

### Weakest interactions (4h, LOW_SAMPLE)
The five weakest rows share the same underlying data: tokens in `late_extension` harmonic with `+9` offset:
- `table1_phase=exhaustion × table2_offset_band=+9`: avg -5.927%, 0% win rate (n=2, 1 snapshot)
- `avoid × late_extension × +9` three-field: same -5.927%

All weakest rows are LOW_SAMPLE (1 snapshot). Signal requires replication.

## LOW_SAMPLE_THREE_SNAPSHOTS_PARTIAL_OUTCOME_COVERAGE limitation
- Only 3 snapshot pairs are currently available.
- 72h has zero valid outcomes. 24h has outcomes from one snapshot only (all LOW_SAMPLE).
- 4h is the only horizon with multi-snapshot coverage (2 snapshots). WATCH_CANDIDATE and NEGATIVE_CANDIDATE labels are computed only for 4h groups.
- 2026-05-16 contributes no valid outcome rows yet; it will resolve on the next ETL cycle.
- With n=3–27 per group even at 4h, all apparent signal must be treated as exploratory observation.
- No runtime promotion. No feature-candidate promotion. More snapshot and outcome accumulation required.

## Downstream path
1. Raw A+ snapshots
2. Normalized A+ labels — Table 1 / Table 2 joined
3. Multi-snapshot outcome validation — labels vs forward returns
4. **Interaction discovery (this lane)** — systematic cross-field measurement
5. Repeat as more snapshots and forward candles become available
6. If a group shows consistent WATCH_CANDIDATE signal across 10+ snapshots and multiple horizons — possible feature candidate, requiring its own preview table evaluation
7. No direct selection / advice / decision_gate / execution_planner / executor use

Any future use must:
- enter through its own preview table
- be evaluated against real market outcomes across sufficient sample
- never bypass decision_gate
- never produce order intent
- never imply account permission

## Script
`src/research/run_aplus_table1_table2_interaction_discovery_v1.py`

CLI:
- `--outcomes-path` (default: `label_outcomes_multi_snapshot_v1.jsonl`)
- `--output-dir` (default `data/research/aplus_table1_table2_interaction_discovery_v1`)
- `--min-n INT` (default 2 — minimum n_with_return to include in output)
- `--output {table,json}` (default `table`)
- `--write-files`

No DB connection required.

## Output files
- `data/research/aplus_table1_table2_interaction_discovery_v1/interaction_group_metrics_v1.jsonl` — 757 rows (one per horizon × group × value combination with n ≥ 2)
- `data/research/aplus_table1_table2_interaction_discovery_v1/interaction_discovery_summary_v1.json`

## Safety markers
- `broker_calls = 0`
- `broker_writes = 0`
- `order_submission = 0`
- `live_orders = 0`
- `db_writes = 0`
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

## No trading advice
Nothing in this dataset is a trade signal, account permission, execution intent, or order. The interaction metrics are research measurements of label-vs-outcome correlation in a small sample. All findings are exploratory.
