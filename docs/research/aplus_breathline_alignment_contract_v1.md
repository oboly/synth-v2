# A+ → Breathline V1 Alignment Study Contract v1

**Status:** DRAFT — Phase 1 (inventory) implemented; Phase 2 (alignment comparison) preregistered here as a design only, not implemented, not executed
**Scope:** Research-only market/context alignment study
**Decision status:** No promotion, runtime integration, or execution use

## 1. Purpose

Determine whether frozen Breathline V1 detects a consistent phase/state at the
exact timestamp of independently recorded A+ Table 1 / Table 2 records,
compared with matched shifted-time controls.

This is not a trading feature. It is not connected to `selection_engine`,
`decision_gate`, `execution_planner`, `executor`, UI, DB writes, accounts,
broker, or strategy promotion. A+ remains an external symbolic/narrative
research label, not market-data truth.

## 2. Architectural Boundaries

Research remains:

```text
market-only
research-only
read-only
no orders
no broker calls
no DB writes from research runners
no account logic
no position sizing
no runtime trading authority
```

`data/aplus_raw/` is local external research evidence, not a market-data
source and not committed research output. This study:

- does not commit, move, rename, edit, normalize in place, or copy raw
  contents from `data/aplus_raw/` into git;
- only reads from `data/aplus_raw/`; every script in this lane opens files
  read-only and never writes into the scanned root;
- does not modify frozen V1 files (`src/research/backtest_breath_curve_partial_to_full_v1.py`,
  `src/market_context/breath_curve_core_v1.py`,
  `src/research/breath_curve_template_matcher_v1.py`);
- does not modify the existing Arm-A/B.2a orchestration runners or the
  Arm-A vs B.2a comparison runner;
- does not inspect outcomes (does not analyze or report on the substantive
  content of A+ PHASE/COHERENCE/HARMONIC_PHASE/etc. field values) before the
  event ledger and this comparison contract are reviewed and fixed.

## 3. Phase 1 — Read-Only A+ Evidence Inventory (implemented)

Runner:

```text
src/research/inventory_aplus_raw_evidence_v1.py
```

Tests:

```text
tests/test_inventory_aplus_raw_evidence_v1.py
```

The inventory recursively scans `data/aplus_raw/` (or an explicit `--root`)
and produces, per file:

- `sha256`, `file_name`, `file_size_bytes`;
- `detected_table_type`: `TABLE1_CANONICAL_BREATHLINE`,
  `TABLE2_HARMONIC_OVERLAY`, or `UNSUPPORTED_SCHEMA`;
- `header_tokens` / `delimiter_style` (space, pipe, or markdown-pipe-with-
  separator-row — all three are observed in the current local corpus);
- `declared_metadata`: any `key = value` preamble lines present in the file
  (e.g. `schema =`, `source_type =`, `status =`) — this is provenance
  metadata, not a table value;
- `token_count`: number of parsed asset rows (only for TABLE1/TABLE2 files);
- `explicit_timestamps`: every distinct explicit timestamp found in the
  source text, each tagged with its field name (if any) and resolved role;
- `filename_inferred_timestamp`: a timestamp parsed from the filename only;
- `timestamp_provenance`: one of
  `EXPLICIT_SOURCE_TIMESTAMP` / `FILENAME_INFERRED_TIMESTAMP` / `UNKNOWN`;
- `status` and `status_notes`;
- `eligible_for_primary_analysis`: true only when provenance is
  `EXPLICIT_SOURCE_TIMESTAMP` and the resolved role is `OBSERVATION_TIME`.

Per-asset row records (only for `TABLE1_CANONICAL_BREATHLINE` /
`TABLE2_HARMONIC_OVERLAY` files with parseable rows) preserve every raw Table
1 / Table 2 field (`phase`, `coherence`, `field`, `geometry`,
`structural_role`, `expansion_quality`, `anchor_strength`, `strategic_bias`,
`notes` for Table 1; `harmonic_phase`, `phase_state`, `offset_band`,
`drift_direction`, `quality`, `extension_risk`, `notes` for Table 2), tagged
with `source_file_hash`, `detected_table_type`, `primary_timestamp_iso`,
`timestamp_provenance`, and `primary_timestamp_role`.

Generated artifacts are written under:

```text
data/research/aplus_breathline_alignment_v1/<run_id>/
    evidence/aplus_evidence_file_manifest_<run_id>.jsonl
    evidence/aplus_evidence_rows_<run_id>.jsonl
    manifest/aplus_evidence_inventory_manifest_<run_id>.json
```

These are generated evidence, not committed to git.

### 3.1 Timestamp provenance vs. timestamp role

Provenance (Phase 1, per-file, how confident we are that a timestamp is real
source evidence rather than a filename guess):

```text
EXPLICIT_SOURCE_TIMESTAMP     found literally in the source text
FILENAME_INFERRED_TIMESTAMP   parsed only from the filename
UNKNOWN                       no usable timestamp found, or found but ambiguous
```

Role (what the timestamp means; carried through into Phase 2's event ledger):

```text
OBSERVATION_TIME       eligible for the as-of Breathline detection study
PREDICTION_TARGET_TIME alignment-only; never described as prospective
                       prediction evidence
FILENAME_INFERRED      excluded from primary analysis; exploratory only
UNLABELED_EXPLICIT     an explicit timestamp with no named field to establish
                       its semantic role (e.g. a bare "(2026-05-15T12:44:48Z)"
                       in a title line) — never coerced into OBSERVATION_TIME
                       or PREDICTION_TARGET_TIME without a named field as
                       evidence
```

### 3.2 Fail-closed rules

- **Duplicate source identity** (identical sha256 content discovered at two
  or more paths under the scanned root) is a run-level integrity failure:
  the whole inventory run raises and writes no output artifacts. The event
  ledger's key is `source_file_hash`; a hash collision across "different"
  paths must be resolved by a human, not silently tolerated.
- **Ambiguous timestamp parsing** (multiple distinct explicit timestamp
  values found in one file with no way to prefer one) never selects a
  winner: `timestamp_provenance` is set to `UNKNOWN`, the file's `status` is
  `AMBIGUOUS_TIMESTAMP`, and it is excluded from primary-analysis eligibility.
- **Unsupported table schema** (header does not match the Table 1 or Table
  2 token set) is recorded per file as `UNSUPPORTED_SCHEMA` — never coerced
  into a Table 1 or Table 2 shape. The file is still listed in the
  inventory; it simply contributes no row-level records.
- **Conflicting asset alias** (the same token appears more than once inside
  one file's table body) is recorded as `DUPLICATE_ASSET_ALIAS_WITHIN_FILE`.
  Every raw row is preserved (never silently collapsed or best-of-picked);
  the file is excluded from primary-analysis eligibility until a human
  resolves which row is authoritative.
- Console/log summary output prints only provenance, counts, and schema
  findings (file counts, table-type counts, status counts, timestamp
  provenance/role counts, eligible-file paths). It never prints PHASE,
  COHERENCE, HARMONIC_PHASE, or any other table-body field value.

### 3.3 Open finding for review before Phase 2 proceeds

Every explicit timestamp currently found anywhere in the local
`data/aplus_raw/` corpus uses the field name `prediction_ts_utc`. No file in
the current corpus declares an `observation_ts_utc` (or equivalent) field.
Per the role definitions above, `prediction_ts_utc` resolves to
`PREDICTION_TARGET_TIME`, not `OBSERVATION_TIME`.

Consequence: as implemented, **zero files in the current local corpus are
`eligible_for_primary_analysis`** (the as-of Breathline detection study
requires `OBSERVATION_TIME`). Whether `prediction_ts_utc` should instead be
treated as the observation anchor for this study's purposes (i.e. "the phase
state A+ claims to hold as of this moment") is a substantive research-design
question, not a parsing question, and is explicitly left for human review
rather than silently resolved in code. Phase 2 must not begin until this is
decided and, if needed, this contract is revised accordingly.

## 4. Phase 2 — Preregistered Alignment Design (not implemented)

This section fixes the design before any code exists for it. No runner
implements this section yet. It must not be implemented or executed until
the Phase 1 ledger inventory (section 3) has been reviewed, and in
particular until section 3.3 is resolved.

### 4.1 Event ledger

One canonical event ledger row per:

```text
(source_file_hash, table_type, asset, event_timestamp, timestamp_role)
```

The ledger is immutable and append-only, carries `source_file_hash` and full
timestamp provenance for every row, and never merges two source files into
one row.

Timestamp roles remain separate and are never blended:

```text
OBSERVATION_TIME        eligible for as-of detection study
PREDICTION_TARGET_TIME  alignment-only; never described as prospective
                        prediction evidence
FILENAME_INFERRED       excluded from primary analysis; may appear only in
                        an explicitly labelled exploratory inventory
```

### 4.2 Fixed-grid Breathline state at each eligible observation event

For every `OBSERVATION_TIME` event ledger row:

- the frozen Breathline V1 state is computed at the fixed A+ event
  timestamp — the anchor/offset is never chosen after seeing results;
- the complete predeclared 2-checkpoint x 9-offset state grid (the same
  grid the frozen V1 module already computes: checkpoints `0.618`/`0.786`,
  offsets `-10.5,-7,-5,-3,0,3,5,7,10.5`) is emitted in full for every event
  and asset;
- every raw score/state in that grid is preserved; no "best-looking" row is
  selected or promoted ahead of the others.

### 4.3 Matched shifted-time controls

For every `OBSERVATION_TIME` event:

- same asset, same A+ event, same clock time as the canonical event;
- exact integer-day shifts (fixed, preregistered, no `0d`):

```text
-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,+1,+2,+3,+4,+5,+6,+7,+8,+9,+10
```

- the shift is applied to the A+ evaluation timestamp, never to the source
  record itself;
- the identical fixed V1 2x9 phase-state grid is recomputed at each of the
  20 control timestamps;
- no missing control may be silently dropped: a control that cannot be
  computed (e.g. candle history unavailable) is recorded as
  `DATA_UNAVAILABLE` and excluded from that control's population, never
  substituted.

This mirrors the B.2a integer-day phase-null control design in
`docs/research/breathline_three_cycle_chain_and_v1_recovery_contract_v1.md`
section 10.2, applied to A+-event timestamps instead of the P0.3 canonical
anchor cohort.

### 4.4 Primary outputs (preregistered)

1. Immutable A+ event ledger with source hashes and timestamp provenance.
2. Fixed-grid Breathline state vector at each eligible A+ observation event.
3. Matched shifted-time control vectors (20 per event, per contract 4.3).
4. Per-event and per-asset contrasts for `ranking_score`,
   `partial_match_score`, `structurally_eligible` (canonical value, control
   mean/median/min/max, tie-aware mid-rank percentile,
   canonical-minus-control-mean — the same contrast design used in
   `run_breathline_v1_arm_a_b2a_comparison_v1.py`).
5. An A+-label <-> V1-state contingency/overlap report, produced only when
   the A+ field semantics for that comparison are unambiguous; otherwise the
   field is reported as unavailable.
6. Asset-level cluster-aware uncertainty, clustering by source
   snapshot/event timestamp (not by row), matching the anchor-date
   cluster-bootstrap convention used throughout this research lane.
7. A pooled descriptive-only output, explicitly labelled cross-asset
   correlated / non-independent.
8. A provenance manifest with input hashes, source run IDs/commits, the
   fixed shift registry, counts, and complete output hashes.

### 4.5 Statistical and wording boundary

- No independent-row p-values.
- No "validated", "predictive", "confirmed", "trade", "signal", or
  promotion claims anywhere in outputs, code, or documentation for this
  study.
- No post-hoc field selection: the three contrast metrics and the fixed
  2x9 grid are preregistered here, not chosen after inspecting results.
- Unsupported or ambiguous A+ fields are reported as unavailable, never
  coerced into a supported shape.
- A+ remains an external symbolic/narrative research label, not market-data
  truth, throughout every output of this study.

## 5. Implementation Sequence

```text
Phase 1  -> inventory + this contract (implemented)
Phase 2  -> preregistered design only (this document, section 4); not
            implemented, not executed
Stop     -> do not implement or execute Phase 2 until the Phase 1 ledger
            inventory has been reviewed, including the open finding in
            section 3.3
```

## 6. Explicit Non-Goals

```text
no runtime trade logic
no account-aware logic
no selection_engine integration
no decision_gate integration
no execution_planner integration
no executor or broker calls
no dashboard or UI change
no V1 source mutation
no Arm-A/B.2a/comparison runner mutation
no A+ raw evidence mutation, move, rename, or in-place normalization
no commit of A+ raw evidence or generated inventory artifacts to git
no inspection of A+ table-body values before this contract is reviewed
no automatic promotion of A+ labels into trade rules or regime classification
no execution of the Phase 2 alignment comparison in this implementation round
```
