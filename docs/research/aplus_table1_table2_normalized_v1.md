# A+ Table 1 / Table 2 Normalized V1

## Purpose
Normalize the latest A+ Breathline Vector Snapshot (Table 1) and Harmonic Phase Overlay (Table 2) into a deterministic per-token-per-snapshot research dataset.

## Research-only boundary
- Research-only.
- Market-only.
- Account-agnostic.
- Symbolic label dataset, not trading advice.
- Not a buy/sell signal.
- Not an account permission.
- Not an execution intent.
- Not an order.
- Does not feed any live runtime path.

No code in this lane:
- modifies selection_engine, advice_engine, decision_gate, execution_planner, or executor
- calls any broker/API
- writes to live or paper DB
- branches on account or paper/live mode
- touches run_chain_4h.sh, policy_router files, or paper_advice_policy_v1

## Raw files used
- `data/aplus_raw/2026-05-15_1244_table1_breathline_vector_snapshot.txt`
- `data/aplus_raw/2026-05-15_1244_table2_harmonic_phase_overlay.txt`

Both files declare the same prediction timestamp in their title line:
`prediction_ts_utc = 2026-05-15T12:44:48Z`.

## Schema

### Table 1 (Breathline Vector Snapshot)
Columns:
`TOKEN | PHASE | COHERENCE | FIELD | GEOMETRY | STRUCTURAL_ROLE | EXPANSION_QUALITY | ANCHOR_STRENGTH | STRATEGIC_BIAS | NOTES`

### Table 2 (Harmonic Phase Overlay)
Columns:
`TOKEN | HARMONIC_PHASE | PHASE_STATE | OFFSET_BAND | DRIFT_DIRECTION | QUALITY | EXTENSION_RISK | NOTES`

### Joined row grain
One row per `(pair_reference_ts_utc, token)`. The two tables' snapshot timestamps may differ slightly — see "Timestamp pairing rule" below.
Fields:
- `pair_reference_ts_utc` — always the later of `table1_prediction_ts_utc` and `table2_prediction_ts_utc`.
- `table1_prediction_ts_utc`
- `table2_prediction_ts_utc`
- `timestamp_mismatch_minutes` — integer minutes between the two per-table timestamps.
- `same_snapshot_ts` — `true` iff `timestamp_mismatch_minutes <= 5`.
- `timestamp_mismatch_allowed` — `true` when the pair is permitted as a joined research snapshot family.
- `prediction_ts_utc` — retained for downstream compatibility; equals `pair_reference_ts_utc`. **Pair-level reference only**, not a per-table snapshot timestamp.
- `token`
- `table1_phase`, `table1_coherence`, `table1_field`, `table1_geometry`, `table1_structural_role`, `table1_expansion_quality`, `table1_anchor_strength`, `table1_strategic_bias`, `table1_notes`
- `table2_harmonic_phase`, `table2_phase_state`, `table2_offset_band`, `table2_drift_direction`, `table2_quality`, `table2_extension_risk`, `table2_notes`
- `source_table1_path`
- `source_table2_path`
- `parser_version`
- `validation_status`

### Timestamp pairing rule
- If `abs(table1_prediction_ts_utc - table2_prediction_ts_utc) <= 5 minutes`:
  - `same_snapshot_ts = true`
  - `prediction_ts_utc` may collapse to `pair_reference_ts_utc`.
- If `abs(table1_prediction_ts_utc - table2_prediction_ts_utc) > 5 minutes`:
  - `same_snapshot_ts = false`
  - Do not collapse the originals — both per-table timestamps are preserved.
  - `prediction_ts_utc`, if retained for compatibility, equals `pair_reference_ts_utc` and is documented as pair-level reference only.
- `pair_reference_ts_utc` is always the **later** of the two per-table timestamps.
- `timestamp_mismatch_allowed = true` by default — the pair is still joined as a "research snapshot family" with the mismatch surfaced rather than hidden. Setting this `false` would reject the pair.

## Allowed values

### Table 1
- `PHASE`: early / forming / confirmed / late / exhaustion / reset / neutral
- `COHERENCE`: high / moderate / low
- `FIELD`: expansion / compression / transition / neutral
- `GEOMETRY`: clean / mixed / distorted / unknown
- `STRUCTURAL_ROLE`: leader / confirmer / laggard / speculative / defensive / unknown
- `EXPANSION_QUALITY`: strong / moderate / weak / none
- `ANCHOR_STRENGTH`: strong / moderate / weak / none
- `STRATEGIC_BIAS`: accumulation / continuation / caution / avoid / neutral

### Table 2
- `HARMONIC_PHASE`: pre_0618 / forming_0618 / confirmed_0618 / forming_0786 / confirmed_0786 / forming_1000 / confirmed_1000 / extension_1272 / late_extension / reset / unclear
- `PHASE_STATE`: early / forming / confirmed / late / exhausted / unclear
- `OFFSET_BAND`: -10.5 / -9 / -8 / -7 / -5 / -3 / 0 / +3 / +5 / +7 / +9 / +10.5 / unknown
- `DRIFT_DIRECTION`: converging / forward_drift / backward_drift / flat / unstable / unknown
- `QUALITY`: clean / mixed / dirty / unknown
- `EXTENSION_RISK`: low / moderate / high / unknown

## Parser tolerance rules
The parser accepts both flavors of the A+ snapshot prose:
- Markdown table headers with leading/trailing pipes (`| TOKEN | PHASE | ...`)
- Markdown separator rows like `| --- | --- |` or `--- | ---`
- Plain pipe rows without leading/trailing pipes (`BTC | confirmed_1000 | ...`)
- Variable spacing around pipes
- Title lines and prose before/after the table block
- Token cells written without space before the pipe (e.g. `RENDER| confirmed | ...`)
- Notes columns as free short text

Validation rules:
- Header row required; cell count must match expected schema.
- Token-cell must match `^[A-Z][A-Z0-9_+\-]*$` after upper-casing; non-token lines are skipped.
- Each controlled cell must exactly match its allowed value set.
- Notes are kept as free text and are not required to be non-empty. Outer double-quotes around a notes cell are stripped (some raw snapshots quote their notes).

Token expectations:
- The `EXPECTED_TOKENS` list of 41 (BTC … LINK) is informational. Missing tokens (e.g. LINK absent from a snapshot) are reported in the audit but do **not** make `validation_status = INVALID` on their own.
- `validation_status = VALID` requires: no duplicate tokens, all controlled-field values valid in both tables, all joined rows internally valid, `joined_rows == |T1 ∩ T2|`, `joined_rows > 0`, and `timestamp_mismatch_allowed = true`.

Timestamp extraction:
- The first `YYYY-MM-DDTHH:MM:SSZ` substring in each file is taken as that table's per-table prediction timestamp.
- Table 1 and Table 2 timestamps may differ — see "Timestamp pairing rule" above.

## Output files
Output dir: `data/research/aplus_table1_table2_normalized_v1/`

File-naming convention:
- Per-table files use that table's own slug: `tableN_normalized_<YYYYMMDD>_<HHMM>.jsonl`.
- The joined and validation files use a **pair slug**:
  - If `t1_slug == t2_slug` (same snapshot minute), the pair slug is the single slug.
  - Otherwise the pair slug is `<YYYYMMDD>_<t1_HHMM>_<t2_HHMM>`.

For the 2026-05-15 12:44 snapshot (same_snapshot_ts = true):
- `table1_normalized_20260515_1244.jsonl`
- `table2_normalized_20260515_1244.jsonl`
- `table1_table2_joined_20260515_1244.jsonl`
- `validation_summary_20260515_1244.json`

For the 2026-05-14 backfill pair (same_snapshot_ts = false; T1 = 13:15Z, T2 = 12:56Z, mismatch = 19 min):
- `table1_normalized_20260514_1315.jsonl`
- `table2_normalized_20260514_1256.jsonl`
- `table1_table2_joined_20260514_1315_1256.jsonl`
- `validation_summary_20260514_1315_1256.json`

For the 2026-05-16 pair (same_snapshot_ts = true; T1 = 01:15Z, T2 = 01:17Z, mismatch = 2 min):
- `table1_normalized_20260516_0115.jsonl`
- `table2_normalized_20260516_0117.jsonl`
- `table1_table2_joined_20260516_0115_0117.jsonl`
- `validation_summary_20260516_0115_0117.json`

No DB writes. No CSV. No broker calls. No account data.

## Validation summary — snapshot 2026-05-15T12:44:48Z
- `table1_rows = 41`
- `table2_rows = 41`
- `joined_rows = 41`
- `same_snapshot_ts = true` (T1 ts == T2 ts)
- `missing_table1 = none`
- `missing_table2 = none`
- `extra_table1 = none`
- `extra_table2 = none`
- `duplicates_table1 = none`
- `duplicates_table2 = none`
- `invalid_table1_count = 0`
- `invalid_table2_count = 0`
- `all_valid_joined = true`
- `validation_status = VALID`

## Validation summary — 2026-05-16 pair (T1 = 01:15:11Z, T2 = 01:17:00Z)
- `pair_reference_ts_utc = 2026-05-16T01:17:00Z`
- `table1_prediction_ts_utc = 2026-05-16T01:15:11Z`
- `table2_prediction_ts_utc = 2026-05-16T01:17:00Z`
- `timestamp_mismatch_minutes = 2`
- `same_snapshot_ts = true` (mismatch ≤ 5 min)
- `timestamp_mismatch_allowed = true`
- `table1_rows = 41`
- `table2_rows = 41`
- `joined_rows = 41`
- `missing_table1 = none`
- `missing_table2 = none`
- `extra_table1 = none`
- `extra_table2 = none`
- `duplicates_table1 = none`
- `duplicates_table2 = none`
- `invalid_table1_count = 0`
- `invalid_table2_count = 0`
- `all_valid_joined = true`
- `validation_status = VALID`

**Timestamp override note:** The 2026-05-16 Table 2 raw file (`2026-05-16_0117_table2_harmonic_phase_overlay.txt`) contains a stale internal timestamp `2026-05-15T12:44:48Z` — the same value as the 2026-05-15 snapshot. The correct capture timestamp `2026-05-16T01:17:00Z` was applied via `--table2-ts-override`. The stale internal timestamp is recorded in the validation summary as `table2_ts_internal = 2026-05-15T12:44:48Z` and `table2_ts_override_applied = true`. The override takes precedence for all pair metadata, output filenames, and per-row timestamps.

## Validation summary — 2026-05-14 backfill pair (T1 = 13:15:00Z, T2 = 12:56:00Z)
- `pair_reference_ts_utc = 2026-05-14T13:15:00Z`
- `timestamp_mismatch_minutes = 19`
- `same_snapshot_ts = false`
- `timestamp_mismatch_allowed = true`
- `table1_rows = 40`
- `table2_rows = 40`
- `joined_rows = 40` (= |T1 ∩ T2|)
- `missing_table1 = LINK` (informational — not in this snapshot)
- `missing_table2 = LINK` (informational — not in this snapshot)
- `extra_table1 = none`
- `extra_table2 = none`
- `duplicates_table1 = none`
- `duplicates_table2 = none`
- `invalid_table1_count = 0`
- `invalid_table2_count = 0`
- `all_valid_joined = true`
- `validation_status = VALID`

Safety markers:
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
The labels are symbolic A+ snapshot tags being captured for later research validation.

## Downstream path
1. Raw A+ snapshot
2. Normalized labels (this lane)
3. Validation against market/regime outcomes (separate research lane, future)
4. Optional feature candidate only after validation
5. No direct selection / advice / decision / execution use

Any future use must:
- enter through its own preview table
- be evaluated against real market outcomes
- never bypass decision_gate
- never produce order intent
- never imply account permission

## Timestamp override rule

Raw snapshot files occasionally carry stale internal timestamps (e.g. a Table 2 file generated against an older session that retained the prior day's timestamp header). When this occurs:
- Pass the correct capture timestamp via `--table1-ts-override` or `--table2-ts-override`.
- The override takes precedence over the internal timestamp for pair metadata, output slugs, and all per-row `prediction_ts_utc` fields.
- The original internal timestamp is preserved in the validation summary as `table1_ts_internal` / `table2_ts_internal` for audit purposes.
- `table1_ts_override_applied` / `table2_ts_override_applied` flags in the summary confirm the override was active.

Do not silently use a stale internal timestamp. Always surface the mismatch in the validation summary.

## Script
`src/research/run_aplus_table1_table2_normalized_v1.py`

CLI:
- `--table1-path` (required)
- `--table2-path` (required)
- `--output-dir` (default `data/research/aplus_table1_table2_normalized_v1`)
- `--output {table,json}` (default `table`)
- `--write-files` (flag — writes the four output files when set)
- `--table1-ts-override` (optional — override internal Table 1 timestamp, `YYYY-MM-DDTHH:MM:SSZ`)
- `--table2-ts-override` (optional — override internal Table 2 timestamp, `YYYY-MM-DDTHH:MM:SSZ`)

Exit code is `0` only when `validation_status = VALID`.
