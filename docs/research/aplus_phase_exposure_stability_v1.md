# A+ Phase Exposure Stability V1

## Purpose
Measure whether A+ Table 1 and Table 2 labels remain in the same phase/offset/exposure buckets across normalized paired snapshots, or drift between buckets. This is a label-stability lane, separate from outcome validation. It does not require forward candle data and has no DB dependency.

## Research-only boundary
- Research-only.
- Market-only.
- Account-agnostic.
- No trading advice, no buy/sell advice.
- No DB writes, no broker/API calls.
- No paper/live branching.
- No `selection_engine`, `advice_engine`, `decision_gate`, `execution_planner`, `executor` changes.
- Does not touch `run_chain_4h.sh`, policy_router files, or `paper_advice_policy_v1`.
- Does not modify outcome validation runners.

## Input snapshots (run 2026-05-16)
| Snapshot pair | pair_reference_ts_utc | Tokens | same_snapshot_ts | mismatch_min |
|---|---|---|---|---|
| `20260514_1315_1256` | 2026-05-14T13:15:00Z | 40 | false | 19 |
| `20260515_1244` | 2026-05-15T12:44:48Z | 41 | true | 0 |
| `20260516_0115_0117` | 2026-05-16T01:17:00Z | 41 | true | 2 |

Snapshots are sorted and processed in `pair_reference_ts_utc` order. LINK is absent from the 2026-05-14 snapshot and present in both 2026-05-15 and 2026-05-16.

## Derived exposure keys

For each joined row the runner computes:

| Key | Definition |
|---|---|
| `table1_phase_key` | `table1_phase` |
| `table1_bias_key` | `table1_strategic_bias` |
| `table1_structure_key` | `table1_phase\|table1_coherence\|table1_field\|table1_geometry\|table1_strategic_bias` |
| `table2_offset_key` | `table2_offset_band` |
| `table2_harmonic_key` | `table2_harmonic_phase` |
| `table2_exposure_key` | `table2_harmonic_phase\|table2_offset_band\|table2_quality\|table2_extension_risk` |
| `combined_exposure_key` | `table1_phase\|table1_strategic_bias\|table2_harmonic_phase\|table2_offset_band\|table2_quality\|table2_extension_risk` |

All `offset_band` values present in the raw data are handled generically (`-10.5`, `-9`, `-7`, `-5`, `-3`, `0`, `+3`, `+5`, `+7`, `+9`, `+10.5`, `unknown`). No bucket is synthesized. `-8` has not appeared in any snapshot to date and is not present in any output.

## Trajectory method
For each token:
1. Collect all snapshots where the token is present, sorted by `pair_reference_ts_utc`.
2. Record the per-snapshot label sequences for all tracked fields.
3. Compute a `stability_class` based on whether Table 1 key fields and Table 2 key fields are stable across all present snapshots.

**Stability class rules:**
| Class | Condition |
|---|---|
| `FULLY_STABLE` | Both table1 (phase + bias) and table2 (harmonic_phase + offset_band + quality + extension_risk) unchanged |
| `TABLE1_STABLE_TABLE2_DRIFT` | Table1 key fields stable; any Table 2 key field drifted |
| `TABLE1_DRIFT_TABLE2_STABLE` | Table2 key fields stable; any Table 1 key field drifted |
| `DRIFTING` | Both Table 1 and Table 2 key fields drifted |
| `INSUFFICIENT_SNAPSHOTS` | Token present in only 1 snapshot — no transitions possible |

## Transition method
For each pair of adjacent snapshots (by `pair_reference_ts_utc` order):
- Compute one transition row per token present in both snapshots.
- Record the per-field from/to values, change flags, and a `transition_signature`.
- `hours_between_snapshots` is the wall-clock difference between the two `pair_reference_ts_utc` values.

Adjacent snapshot intervals:
- 2026-05-14 → 2026-05-15: ~23.5 h
- 2026-05-15 → 2026-05-16: ~12.5 h

Transition row count per adjacent pair:
- 2026-05-14 → 2026-05-15: 40 tokens (LINK absent in 2026-05-14)
- 2026-05-15 → 2026-05-16: 41 tokens
- Total: 81 transition rows

## Current results (3 snapshots, run 2026-05-16)

### Input / output counts
- Input snapshots: 3
- Input token rows: 122
- Unique tokens: 41
- Transition rows: 81
- LINK: present in 2 of 3 snapshots (absent 2026-05-14)

### Stability class counts
| Class | Count |
|---|---|
| FULLY_STABLE | 0 |
| TABLE1_STABLE_TABLE2_DRIFT | 14 |
| TABLE1_DRIFT_TABLE2_STABLE | 0 |
| DRIFTING | 27 |
| INSUFFICIENT_SNAPSHOTS | 0 |

No token is FULLY_STABLE across all 3 snapshots. 14 tokens are TABLE1_STABLE_TABLE2_DRIFT — their Table 1 phase and bias labels held, but Table 2 harmonic/offset shifted. The majority (27) are DRIFTING in both dimensions.

### Stability rates (tokens with ≥ 2 snapshots, all 41 tokens qualify)
| Field | Stability rate |
|---|---|
| `table1_phase` | 41.5% |
| `table1_strategic_bias` | 51.2% |
| `table2_harmonic_phase` | 4.9% |
| `table2_offset_band` | 9.8% |
| `table2_quality` | 56.1% |
| `table2_extension_risk` | 29.3% |
| `combined_exposure_key` | 0.0% |

Table 2 harmonic phase and offset band are the most volatile fields. Table 2 quality is the most stable Table 2 field. No token has a stable combined exposure across all 3 snapshots.

### Offset band stability
- Tokens with stable `table2_offset_band` (4): INJ, LDO, NOT, PEPE
- Tokens with offset band drift (37): all others

### Combined exposure stability
- Tokens with stable `combined_exposure_key`: 0
- All 41 tokens drifted in combined exposure across the 3-snapshot window.

### Top offset band transitions
| From | To | Count |
|---|---|---|
| -3 | +3 | 5 |
| +5 | 0 | 4 |
| +9 | -3 | 3 |
| -9 | +9 | 3 |
| +3 | 0 | 2 |

### Top Table 1 phase transitions
| From | To | Count |
|---|---|---|
| confirmed | forming | 6 |
| forming | early | 4 |
| forming | reset | 3 |
| forming | confirmed | 3 |
| forming | neutral | 2 |

### Top combined exposure transitions
1. `confirmed|continuation|confirmed_1000|0|clean|low` → `confirmed|continuation|confirmed_0618|0|clean|low` — 4× (harmonic level shift, all else stable)
2. `late|avoid|reset|-9|dirty|unknown` → `late|avoid|late_extension|+9|dirty|high` — 3× (offset swing + extension risk flip)
3. Single-token transitions (all unique)

## LOW_SAMPLE_THREE_SNAPSHOTS limitation
Only 3 snapshot pairs are currently available. All stability measurements reflect behaviour over a ~62-hour window (2026-05-14 13:15Z → 2026-05-16 01:17Z). This is insufficient to draw conclusions about whether label instability is structural or noise.

No runtime promotion is allowed. No feature candidate promotion is allowed. More snapshot accumulation is required before any stability pattern can be treated as a validated finding.

## Downstream path
1. Raw A+ snapshots
2. Normalized A+ labels — Table 1 / Table 2 joined (existing lane)
3. **Phase/exposure stability (this lane)** — measures label drift across snapshots
4. Multi-snapshot outcome validation (separate lane) — measures label vs forward returns
5. Future: cross-reference stable-label subset vs outcome validation results — only after sufficient snapshot accumulation (target: 10+ pairs)
6. Optional feature candidate only after validation — must enter through its own preview table
7. No direct selection / advice / decision_gate / execution_planner / executor use

Any future use must:
- enter through its own preview table
- be evaluated against real market outcomes
- never bypass decision_gate
- never produce order intent
- never imply account permission

## Script
`src/research/run_aplus_phase_exposure_stability_v1.py`

CLI:
- `--joined-paths PATH [PATH ...]` (default: all three joined files above)
- `--output-dir` (default `data/research/aplus_phase_exposure_stability_v1`)
- `--output {table,json}` (default `table`)
- `--write-files` (writes output files when set)

No DB connection required. No forward candle data required.

## Output files
Output dir: `data/research/aplus_phase_exposure_stability_v1/`

- `token_phase_exposure_trajectories_v1.jsonl` — 41 rows, one per token
- `phase_exposure_transition_rows_v1.jsonl` — 81 rows, one per token per adjacent snapshot transition
- `phase_exposure_stability_summary_v1.json` — aggregated stability metrics and token lists

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
The labels are symbolic A+ snapshot tags; this lane measures whether those tags are stable or drifting across snapshots. No inference about future price behaviour is made or implied.
