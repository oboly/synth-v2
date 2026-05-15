# A+ Table 1-Only Normalized V1

## Purpose
Normalize A+ Table 1 (Breathline Vector Snapshot) files into a deterministic per-token-per-snapshot research staging dataset when no validated matching Table 2 (Harmonic Phase Overlay) is available.

This lane holds Table 1-only snapshots in a separate staging area. They are not included in the Table 1/Table 2 joined dataset until a matching Table 2 snapshot is found and validated.

## Why this is Table 1-only, not joined Table 1/Table 2

The existing joined normalization lane (`aplus_table1_table2_normalized_v1`) requires both a Table 1 and a Table 2 file for the same snapshot period. The 2026-05-13 snapshot has only a Table 1 file — no corresponding Table 2 (Harmonic Phase Overlay) file for 2026-05-13T19:15:00Z has been found.

Adding a Table 1-only snapshot to the joined lane would:
- introduce incomplete rows (no harmonic phase, no phase_state, no extension_risk, etc.)
- break the semantic contract of the joined schema
- make aggregations across the joined dataset unreliable

This staging lane preserves the Table 1 labels in their correct normalized form without forcing a premature join.

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
- Does not modify the Table 1/Table 2 joined normalization runner or its outputs.

## Source file
`data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt`

Format: space-separated (no pipes). Header: `TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES`. The parser handles both space-separated and pipe-separated Table 1 formats.

## Schema

### Staging row (one per token)
- `snapshot_id` — `{YYYYMMDD}_{HHMM}_table1_only`
- `table1_prediction_ts_utc` — per-table timestamp from the raw file
- `prediction_ts_utc` — equals `table1_prediction_ts_utc` (no pair alignment needed)
- `table2_present` — always `false` in this lane
- `joined_pair_available` — always `false` in this lane
- `token`
- `table1_phase`, `table1_coherence`, `table1_field`, `table1_geometry`
- `table1_structural_role`, `table1_expansion_quality`, `table1_anchor_strength`, `table1_strategic_bias`
- `table1_notes`
- `source_table1_path`
- `parser_version`
- `validation_status`

### Allowed Table 1 values
- `PHASE`: early / forming / confirmed / late / exhaustion / reset / neutral
- `COHERENCE`: high / moderate / low
- `FIELD`: expansion / compression / transition / neutral
- `GEOMETRY`: clean / mixed / distorted / unknown
- `STRUCTURAL_ROLE`: leader / confirmer / laggard / speculative / defensive / unknown
- `EXPANSION_QUALITY`: strong / moderate / weak / none
- `ANCHOR_STRENGTH`: strong / moderate / weak / none
- `STRATEGIC_BIAS`: accumulation / continuation / caution / avoid / neutral

## Validation rules
`validation_status = VALID` requires:
- `table1_rows > 0`
- `duplicate_tokens = 0`
- `invalid_controlled_values = 0`
- every row has `validation_status = VALID`

Missing expected tokens (e.g. LINK absent from this snapshot) are informational and do not invalidate. The `EXPECTED_TOKENS` list of 41 (BTC … LINK) is a reference; snapshots may contain a subset.

## Validation summary — 2026-05-13 snapshot

- `snapshot_id = 20260513_1915_table1_only`
- `table1_prediction_ts_utc = 2026-05-13T19:15:00Z`
- `table2_present = false`
- `joined_pair_available = false`
- `table1_rows = 40`
- `duplicate_tokens = 0`
- `invalid_controlled_values = 0`
- `missing_expected_tokens = LINK` (informational)
- `extra_tokens = none`
- `validation_status = VALID`

## Known limitation: no Table 2 pair yet
This snapshot cannot be used in the multi-snapshot outcome validation runner (`aplus_multi_snapshot_outcome_validation_v1`) until a matching Table 2 file for 2026-05-13 is found, validated, and joined. The Table 1-only staging row carries `joined_pair_available = false` to make this explicit.

## Downstream path
1. Raw A+ Table 1 snapshot
2. **Table 1-only normalized staging (this lane)**
3. Optional: Table 1-only outcome validation (separate lane, future)
4. Later join with Table 2 only if a validated matching Table 2 snapshot is found — joined output must go through `aplus_table1_table2_normalized_v1` with both files present
5. After joining: eligible for multi-snapshot outcome validation
6. Optional feature candidate only after multi-snapshot validation
7. No direct runtime use at any stage

Any future use must:
- enter through its own preview table
- be evaluated against real market outcomes
- never bypass decision_gate
- never produce order intent
- never imply account permission

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

## Script
`src/research/run_aplus_table1_only_normalized_v1.py`

CLI:
- `--table1-path` (default: `data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt`)
- `--output-dir` (default: `data/research/aplus_table1_only_normalized_v1`)
- `--output {table,json}` (default: `table`)
- `--write-files` (writes output files when set)

Exit code is `0` only when `validation_status = VALID`.

## Output files
- `data/research/aplus_table1_only_normalized_v1/table1_normalized_20260513_1915.jsonl` — 40 staging rows
- `data/research/aplus_table1_only_normalized_v1/validation_summary_20260513_1915.json`

## No trading advice
Nothing in this dataset is a trade signal, account permission, execution intent, or order.
The labels are symbolic A+ snapshot tags being captured for later research validation.
