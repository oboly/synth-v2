# A+ Multi-Snapshot Outcome Validation V1

## Purpose
Measure whether A+ Table 1/Table 2 labels correlate with forward market outcomes across all currently normalized joined snapshots. This is a pooled measurement across three snapshot pairs; it is not a single-snapshot result.

## Research-only boundary
- Research-only.
- Market-only.
- Account-agnostic.
- No trading advice.
- No buy/sell advice.
- No DB writes.
- No broker/API calls.
- No paper/live branching.
- No `selection_engine`, `advice_engine`, `decision_gate`, `execution_planner`, `executor` changes.
- Does not touch `run_chain_4h.sh`, policy_router files, or `paper_advice_policy_v1`.

## Source joined files
- `data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260514_1315_1256.jsonl` — 40 tokens, pair_reference_ts=2026-05-14T13:15:00Z, same_snapshot_ts=false, mismatch=19 min
- `data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260515_1244.jsonl` — 41 tokens, pair_reference_ts=2026-05-15T12:44:48Z, same_snapshot_ts=true, mismatch=0 min
- `data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260516_0115_0117.jsonl` — 41 tokens, pair_reference_ts=2026-05-16T01:17:00Z, same_snapshot_ts=true, mismatch=2 min

## Timestamp alignment rule
`pair_reference_ts_utc` is the outcome alignment timestamp for each snapshot. If `pair_reference_ts_utc` is absent in a row, `prediction_ts_utc` is used as fallback. Per-table timestamps (`table1_prediction_ts_utc`, `table2_prediction_ts_utc`) are carried through for transparency but are not used individually for candle alignment.

## Outcome method
For each joined row × horizon:
1. Find the latest 4h candle with `close_ts_utc <= pair_reference_ts_utc` (base candle).
2. Find the first 4h candle with `close_ts_utc >= base_ts + horizon_hours` (future candle).
3. Compute `forward_return_pct = (future_price / base_price - 1) × 100`.
4. Compute `mfe_pct` and `mae_pct` from MAX(high) and MIN(low) over the hold window.

DB: `obs_market_candle`, venue=bitvavo, interval_code=4h.

## Horizons
- 4h
- 24h
- 72h

## Input summary
- Input snapshots: 3
- Input token rows: 122 (40 + 41 + 41)
- Outcome rows: 366 (122 × 3 horizons)

## Coverage summary (run 2026-05-16)

### 2026-05-14 snapshot (`20260514_1315_1256`)
- 4h: 40/40 VALID
- 24h: 40/40 VALID
- 72h: 0/40 VALID — all NO_FUTURE_CANDLE (candle date not yet in DB)

### 2026-05-15 snapshot (`20260515_1244`)
- 4h: 41/41 VALID
- 24h: 0/41 VALID — all NO_FUTURE_CANDLE (snapshot too fresh)
- 72h: 0/41 VALID — all NO_FUTURE_CANDLE

### 2026-05-16 snapshot (`20260516_0115_0117`)
- 4h: 0/41 VALID — all NO_FUTURE_CANDLE (candles not yet available)
- 24h: 0/41 VALID — all NO_FUTURE_CANDLE
- 72h: 0/41 VALID — all NO_FUTURE_CANDLE

### Overall by horizon
| Horizon | Total | VALID | NO_FUTURE_CANDLE |
|---------|-------|-------|-----------------|
| 4h      | 122   | 81    | 41              |
| 24h     | 122   | 40    | 82              |
| 72h     | 122   | 0     | 122             |

## Per-horizon overall aggregation
| Horizon | n  | snapshots | avg_return | win_rate | avg_mfe  | avg_mae  |
|---------|-----|-----------|------------|----------|----------|----------|
| 4h      | 81  | 2         | -0.097%    | 49.4%    | +1.804%  | -2.301%  |
| 24h     | 40  | 1         | +0.581%    | 67.5%    | +5.305%  | -1.257%  |
| 72h     | 0   | 0         | —          | —        | —        | —        |

Note: 2026-05-16 future candles are not yet available at any horizon. Aggregations are unchanged from the 2-snapshot run — the 2026-05-16 rows are present in the output file with `outcome_status=NO_FUTURE_CANDLE` and will resolve on the next refresh once ETL populates the forward candles.

## Label aggregation groups

### Single-field groups
- `table1_phase`
- `table1_coherence`
- `table1_field`
- `table1_structural_role`
- `table1_strategic_bias`
- `table2_harmonic_phase`
- `table2_phase_state`
- `table2_offset_band`
- `table2_quality`
- `table2_extension_risk`

### Cross-field groups
- `table1_coherence` × `table2_quality`
- `table1_strategic_bias` × `table2_extension_risk`
- `table1_phase` × `table2_harmonic_phase`

## Results

### Top positive groups (min n=2)

**4h horizon:**
| Group | n | snapshots | avg_return | win_rate |
|-------|---|-----------|------------|----------|
| phase×harmonic: forming\|forming_0618 | 4 | 1 | +4.056% | 100% |
| bias×ext_risk: caution\|high | 2 | 2 | +3.598% | 50% |
| bias×ext_risk: accumulation\|high | 7 | 2 | +2.823% | 86% |
| harmonic_phase: confirmed_0618 | 9 | 1 | +2.779% | 100% |
| phase×harmonic: confirmed\|confirmed_0618 | 8 | 1 | +2.779% | 100% |

**24h horizon (2026-05-14 only):**
| Group | n | snapshots | avg_return | win_rate |
|-------|---|-----------|------------|----------|
| strategic_bias: caution | 3 | 1 | +6.712% | 100% |
| harmonic_phase: forming_1000 | 6 | 1 | +2.987% | 83% |
| phase×harmonic: forming\|forming_1000 | 6 | 1 | +2.987% | 83% |
| offset_band: 0 | 7 | 1 | +2.498% | 71% |
| phase×harmonic: confirmed\|confirmed_1000 | 3 | 1 | +2.381% | 100% |

### Weakest groups (min n=2)

**4h horizon:**
| Group | n | snapshots | avg_return | win_rate |
|-------|---|-----------|------------|----------|
| harmonic_phase: confirmed_0786 | 4 | 1 | -3.630% | 0% |
| phase×harmonic: neutral\|unclear | 2 | 1 | -3.543% | 0% |
| bias×ext_risk: neutral\|unknown | 2 | 1 | -3.543% | 0% |
| coherence×quality: moderate\|unknown | 2 | 1 | -3.543% | 0% |
| phase_state: unclear | 2 | 1 | -3.543% | 0% |

**24h horizon:**
| Group | n | snapshots | avg_return | win_rate |
|-------|---|-----------|------------|----------|
| table1_phase: early | 3 | 1 | -3.029% | 0% |
| phase×harmonic: reset\|reset | 2 | 1 | -2.629% | 0% |
| bias×ext_risk: neutral\|moderate | 2 | 1 | -2.629% | 0% |
| harmonic_phase: reset | 2 | 1 | -2.629% | 0% |
| table1_phase: reset | 2 | 1 | -2.629% | 0% |

## LOW_SAMPLE_MULTI_SNAPSHOT limitation
Three snapshot pairs are currently available. The 24h horizon has data from one snapshot only (2026-05-14); the 72h horizon has zero coverage across all three snapshots. The 2026-05-16 snapshot has no future coverage at any horizon — all outcome rows are NO_FUTURE_CANDLE pending ETL. No label group has n ≥ 2 across three snapshots. All apparent signal must be treated as exploratory pattern observation, not a validated finding.

No runtime promotion is allowed. No feature candidate promotion is allowed yet. More snapshot accumulation is required before any conclusion can be drawn.

## Downstream path
1. Raw A+ snapshots
2. Normalized A+ labels (Table 1 / Table 2 joined)
3. **Multi-snapshot outcome validation (this lane)**
4. More snapshot accumulation (target: 10+ pairs, 3+ horizons with >0 NO_FUTURE_CANDLE coverage)
5. Optional feature candidate only after validation — must enter through its own preview table
6. No direct selection / advice / decision_gate / execution_planner / executor use

Any future use must:
- enter through its own preview table
- be evaluated against real market outcomes
- never bypass decision_gate
- never produce order intent
- never imply account permission

## Script
`src/research/run_aplus_multi_snapshot_outcome_validation_v1.py`

CLI:
- `--joined-paths PATH [PATH ...]` (default: both joined files above)
- `--venue` (default `bitvavo`)
- `--interval` (default `4h`)
- `--horizons INT [INT ...]` (default `4 24 72`)
- `--output-dir` (default `data/research/aplus_multi_snapshot_outcome_validation_v1`)
- `--output {table,json}` (default `table`)
- `--write-files` (writes output files when set)

## Output files
- `data/research/aplus_multi_snapshot_outcome_validation_v1/label_outcomes_multi_snapshot_v1.jsonl` — 366 rows (one per snapshot/token/horizon)
- `data/research/aplus_multi_snapshot_outcome_validation_v1/validation_summary_multi_snapshot_v1.json`

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
Nothing in this dataset is a trade signal, account permission, execution intent, or order.
The labels are symbolic A+ snapshot tags; their correlation with outcomes is being measured for research purposes only.
