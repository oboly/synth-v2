# A+ Raw Backlog Inventory V1

## Purpose
Before any old A+ raw file is normalized or backfilled, produce a deterministic manifest of what exists, classify each file by schema family, detect duplicates, and separate parse-ready snapshots from legacy / incompatible formats. The output is descriptive only — it does not move, modify, or commit raw backlog files.

## Research-only boundary
- Research-only.
- Market-only.
- Account-agnostic.
- No trading advice.
- No buy/sell advice.
- No DB writes.
- No broker / API calls.
- No paper / live branching.
- No `selection_engine`, `advice_engine`, `decision_gate`, `execution_planner`, `executor` changes.
- Does not touch `run_chain_4h.sh`, policy_router files, or `paper_advice_policy_v1`.
- Does not normalize, parse, ingest, move, or delete backlog files.

## Source roots
Defaults (configurable via `--roots`):
- `data/aplus_raw/`
- `data/research/aplus_table1_table2_normalized_v1/`
- `data/research/aplus_table2_harmonic_overlay_v1/`

All files (recursive) under each root are walked.

## Manifest schema
One JSON line per file in `aplus_raw_backlog_manifest_v1.jsonl`:

- `file_path`
- `file_name`
- `root`
- `file_size_bytes`
- `mtime_utc`
- `sha256`
- `suffix`
- `source_format` — one of `raw_text`, `markdown_table`, `jsonl`, `unknown`
- `guessed_table_type` — one of
  - `TABLE1_BREATHLINE_VECTOR`
  - `TABLE2_HARMONIC_PHASE`
  - `CONSISTENCY_RUN`
  - `CLUSTER_EXTENSION`
  - `NORMALIZED_JOINED_JSONL`
  - `UNKNOWN`
- `guessed_snapshot_ts_utc` — inferred from inline `YYYY-MM-DDTHH:MM:SSZ` text or filename pattern; `null` if not inferable
- `contains_table1_headers` — `bool`
- `contains_table2_headers` — `bool`
- `line_count` — text/jsonl line count, or `null`
- `token_count_guess` — heuristic count of unique token rows
- `parse_candidate` — `bool` (true only for parse-ready raw snapshots)
- `ingestion_status` — one of `READY_FOR_PARSE`, `NEEDS_REVIEW`, `DUPLICATE_CANDIDATE`, `OLD_FORMAT`, `UNKNOWN`
- `reason` — short text explaining classification
- `duplicate_kind` (when applicable) — `EXACT_SHA256` or `SAME_TS_AND_TYPE`
- `duplicate_peers` (when applicable) — list of peer file paths

## Classification rules
1. **Path-based shortcuts** for derived outputs:
   - `.jsonl` under any root with normalized markers (`schema_version aplus_table1_table2_normalized_v1`, `table1_phase`, or `harmonic_phase` + `table_type`) → `NORMALIZED_JOINED_JSONL` → `NEEDS_REVIEW`.
   - `.json` summary files under the current canonical lane → `UNKNOWN` type, `NEEDS_REVIEW` status with explanatory reason.
   - `.csv` under `data/research/` → treated as derived → `NORMALIZED_JOINED_JSONL` → `NEEDS_REVIEW`.
2. **Header signature detection** on `.txt` files:
   - All ten Table 1 v1 column names present in one line → `TABLE1_BREATHLINE_VECTOR`.
   - All eight Table 2 v1 column names present in one line → `TABLE2_HARMONIC_PHASE`.
3. **Legacy / incompatible schemas**:
   - `TOKEN MOMENTUM STABILITY ALIGNMENT VOLATILITY ...` → `CONSISTENCY_RUN` → `OLD_FORMAT`.
   - `CLUSTER_GROUP`, `CLUSTER_STRENGTH`, `DIVERGENCE_FLAG` → `CLUSTER_EXTENSION` → `OLD_FORMAT`.
   - Early prose signatures (`Codex Breathline Resonance`, `Emotional Load`, `Distortion Level`) → `OLD_FORMAT`.
4. **Already-handled snapshots** (the 2026-05-15 12:44 lane) are kept in the manifest for completeness but flagged `NEEDS_REVIEW` with reason "already normalized via aplus_table1_table2_normalized_v1 lane".
5. **Files with a v1 header but suspiciously empty body** (file <500 bytes or `token_count_guess < 5`) → `NEEDS_REVIEW` instead of `READY_FOR_PARSE`.

## Duplicate rules
- **Exact duplicate**: same `sha256` across files. Each peer record is annotated with `duplicate_kind = EXACT_SHA256` and `duplicate_peers`. If a file was otherwise `READY_FOR_PARSE` or `UNKNOWN`, it is downgraded to `DUPLICATE_CANDIDATE`. Files already classified as `OLD_FORMAT` keep that stronger status but still get the duplicate annotation.
- **Semantic duplicate candidate**: same `guessed_snapshot_ts_utc` and same `guessed_table_type`, but different `sha256`. Recorded with `duplicate_kind = SAME_TS_AND_TYPE`.

## Summary counts (run on 2026-05-15)
- Total files inventoried: **26**
- By `guessed_table_type`:
  - `TABLE1_BREATHLINE_VECTOR`: 3
  - `TABLE2_HARMONIC_PHASE`: 4
  - `CONSISTENCY_RUN`: 11
  - `CLUSTER_EXTENSION`: 1
  - `NORMALIZED_JOINED_JSONL`: 5
  - `UNKNOWN`: 2
- By `ingestion_status`:
  - `READY_FOR_PARSE`: 3
  - `NEEDS_REVIEW`: 10
  - `OLD_FORMAT`: 13
  - `DUPLICATE_CANDIDATE`: 0 (all exact duplicates are inside `OLD_FORMAT`; the duplicate fact is captured by `duplicate_peers` and `duplicate_groups_by_sha256`)
- By `source_format`:
  - `raw_text`: 16
  - `markdown_table`: 4
  - `jsonl`: 6

Exact `sha256` duplicate groups detected: **3** groups (8 files total)
- `2026-04-23_run_02_consistency.txt` ≡ `2026-04-23_run_03_consistency.txt` (legacy CONSISTENCY_RUN)
- `2026-05-04_0055_vector_snapshot_01.txt` ≡ `2026-05-04_1755_vector_snapshot_01.txt` (CONSISTENCY_RUN under misleading filename)
- `2026-05-06_1800`, `2026-05-07_1550`, `2026-05-08_1619`, `2026-05-09_1455` — four byte-identical files (CONSISTENCY_RUN under misleading filenames)

## READY_FOR_PARSE files
v1-compatible raw snapshots that have not yet been normalized:
- `data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt`
- `data/aplus_raw/2026-05-14_1256_table2_harmonic_phase_overlay.txt`
- `data/aplus_raw/2026-05-14_1315_table1_canonical_breathline.txt`

The Table 1 files use the space-separated v1 schema (compatible with the existing `parse_aplus_canonical_table1_v1` parser and tolerable to the new `aplus_table1_table2_normalized_v1` parser given an extended header-row detector). The Table 2 file uses the pipe-separated v1 schema and is directly compatible with `aplus_table1_table2_normalized_v1`'s Table 2 path.

## NEEDS_REVIEW files
- `data/aplus_raw/2026-05-14_table2_harmonic_overlay.txt` — 130 bytes; Table 2 header present but body empty.
- `data/aplus_raw/2026-05-15_1244_table1_breathline_vector_snapshot.txt` — already normalized via the 2026-05-15 lane.
- `data/aplus_raw/2026-05-15_1244_table2_harmonic_phase_overlay.txt` — already normalized via the 2026-05-15 lane.
- `data/research/aplus_table1_table2_normalized_v1/2026-05-14_table1_table2_normalized.jsonl` — prior-lane joined output; review whether it is reproducible from the raw 2026-05-14 files.
- `data/research/aplus_table1_table2_normalized_v1/table1_normalized_20260515_1244.jsonl` — current canonical lane output.
- `data/research/aplus_table1_table2_normalized_v1/table2_normalized_20260515_1244.jsonl` — current canonical lane output.
- `data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260515_1244.jsonl` — current canonical lane output.
- `data/research/aplus_table1_table2_normalized_v1/validation_summary_20260515_1244.json` — current canonical lane summary.
- `data/research/aplus_table2_harmonic_overlay_v1/aplus_table2_harmonic_overlay_20260514T125600Z.csv` — prior-lane derived CSV.
- `data/research/aplus_table2_harmonic_overlay_v1/aplus_table2_harmonic_overlay_20260514T125600Z.jsonl` — prior-lane derived JSONL.

## OLD_FORMAT files
13 files — all incompatible with the v1 Table 1 / Table 2 schema. They include the legacy CONSISTENCY_RUN format (10 raw `.txt`s plus the misnamed `vector_snapshot_01` files), the CLUSTER_EXTENSION schema, and the 2026-03-25 early prose snapshot.

## Next recommended steps
1. **Review `READY_FOR_PARSE` files first**. For each, decide whether the snapshot's `prediction_ts_utc` is worth re-normalizing into the v1 lane.
2. **Design a backfill parser/runner only for compatible snapshots**, reusing the tolerant header detection from `aplus_table1_table2_normalized_v1`. Do not merge into the current normalized output dataset until both Table 1 and Table 2 for the same snapshot have passed validation.
3. **Keep all labels research-only**. Backfilled snapshots feed only:
   - normalized labels (research dataset)
   - outcome validation
   - multi-snapshot validation
   No direct selection / advice / decision_gate / execution_planner / executor use.
4. **Do not parse `OLD_FORMAT` files into the v1 dataset**. If they have research value, build a separate legacy-schema lane for them; do not coerce them into the v1 column set.
5. **Resolve `NEEDS_REVIEW` items** by deciding which prior-lane outputs to keep, archive, or reproduce from raw. The duplicate groups under `OLD_FORMAT` can be deduplicated before any future legacy-lane work.

## Outputs
Output dir: `data/research/aplus_raw_backlog_inventory_v1/`
- `aplus_raw_backlog_manifest_v1.jsonl` — one record per file.
- `aplus_raw_backlog_summary_v1.json` — counts, lists per status, duplicate groups, safety markers.

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
`src/research/run_aplus_raw_backlog_inventory_v1.py`

CLI:
- `--roots PATH [PATH ...]` (default: the three roots above)
- `--output-dir` (default `data/research/aplus_raw_backlog_inventory_v1`)
- `--output {table,json}` (default `table`)
- `--write-files` (writes the two output files when set)
