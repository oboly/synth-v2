# A+ → Breathline V1 Alignment Study Contract v1

**Status:** DRAFT — Phase 1 (inventory) implemented; Phase 2 (snapshot-alignment comparison) preregistered here as a design only, not implemented, not executed
**Scope:** Research-only market/context alignment study
**Decision status:** No promotion, runtime integration, or execution use

## 1. Purpose

A+ Table 1 and Table 2 records are **point-in-time snapshots**, not forward
predictions. Determine whether, at the exact A+ snapshot timestamp `T`, using
only market candles fully closed at or before `T`, frozen Breathline V1
describes a compatible phase/state for the same asset, compared with
matched shifted-time controls.

This is a **snapshot-alignment** study. It is not a trading feature. It is
not connected to `selection_engine`, `decision_gate`, `execution_planner`,
`executor`, UI, DB writes, accounts, broker, or strategy promotion. A+
remains an external symbolic/narrative research label, not market-data
truth. It is not observation of a future event, not prospective validation,
not predictive proof, not trade evidence, and not trading authority.

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

The inventory recursively scans `data/aplus_raw/` (or an explicit `--root`).
Content identity is canonical by **sha256**: identical bytes discovered at
multiple paths are one canonical source with multiple `alias_paths`, never
one ledger population per alias. Per canonical source, the inventory
produces:

- `canonical_source_hash`, `canonical_source_path` (the lexicographically
  first of the discovered aliases), `alias_paths` (sorted, every discovered
  path with this content), `alias_count`;
- `file_size_bytes`;
- `detected_table_type`: `TABLE1_CANONICAL_BREATHLINE`,
  `TABLE2_HARMONIC_OVERLAY`, or `UNSUPPORTED_SCHEMA`;
- `header_tokens` / `delimiter_style` (space, pipe, or markdown-pipe-with-
  separator-row — all three are observed in the current local corpus);
- `declared_metadata`: any `key = value` preamble lines present in the file
  — this is provenance metadata, not a table value;
- `token_count`: number of parsed asset rows (only for TABLE1/TABLE2 files;
  never includes a footer line or trailing prose — see 3.3);
- `explicit_timestamps`: every distinct explicit timestamp found in the
  source text, each tagged with its field name (if any) and resolved role;
- `filename_inferred_timestamp`, `timestamp_provenance`, `primary_timestamp_iso`,
  `primary_timestamp_role`, `timestamp_lane`: which named field (if any)
  established the primary timestamp;
- `source_capture_ts_utc`, `source_capture_time_provenance`,
  `source_capture_time_eligible`: filename-derived **diagnostics only** —
  never required for eligibility, never compared to `snapshot_ts_utc` (see
  3.2);
- **the primary snapshot-alignment fields (section 3.5)**: `snapshot_ts_utc`,
  `snapshot_ts_utc_provenance`, `snapshot_source_field_name`,
  `snapshot_alignment_eligible`, `snapshot_exclusion_reason`,
  `analysis_lane`;
- `status` and `status_notes`.

Per-row records (only for `TABLE1_CANONICAL_BREATHLINE` /
`TABLE2_HARMONIC_OVERLAY` canonical sources) preserve every raw Table 1 /
Table 2 field (`phase`, `coherence`, `field`, `geometry`, `structural_role`,
`expansion_quality`, `anchor_strength`, `strategic_bias`, `notes` for Table 1;
`harmonic_phase`, `phase_state`, `offset_band`, `drift_direction`, `quality`,
`extension_risk`, `notes` for Table 2), tagged with `canonical_source_hash`,
`canonical_source_path`, `detected_table_type`, `snapshot_ts_utc`,
`snapshot_source_field_name`, `timestamp_provenance`, `timestamp_lane`,
`analysis_lane`, `raw_source_token`, `canonical_market_symbol`,
`asset_resolution_status`, and `row_parse_status`. A row's own
`analysis_lane` is `PRIMARY_SNAPSHOT_ALIGNMENT` only when the file-level
preconditions hold **and** its own token resolves — see 3.5. Lines that
never became an asset row (a footer line, a malformed row, trailing prose)
appear in the same stream tagged
`row_parse_status = MALFORMED_TABLE_BODY` or `UNPARSED_NON_TABLE_LINE`, with
no asset/field values fabricated for them — see 3.3.

Generated artifacts are written under:

```text
data/research/aplus_breathline_alignment_v1/<run_id>/
    evidence/aplus_evidence_canonical_source_manifest_<run_id>.jsonl
    evidence/aplus_evidence_rows_<run_id>.jsonl
    manifest/aplus_evidence_inventory_manifest_<run_id>.json
```

These are generated evidence, not committed to git.

### 3.1 Timestamp provenance, role, and (descriptive) lane

Provenance (per canonical source, how confident we are that a timestamp is
real source evidence rather than a filename guess):

```text
EXPLICIT_SOURCE_TIMESTAMP     found literally in the source text
FILENAME_INFERRED_TIMESTAMP   parsed only from the filename
UNKNOWN                       no usable timestamp found, or found but ambiguous
```

Role (what a specific timestamp field means):

```text
SNAPSHOT_TIME           named field prediction_ts_utc. Treated in this
                        research lane as an A+ point-in-time
                        snapshot/evaluation timestamp -- never a future
                        target time, never described as observation of a
                        future event, prospective validation, predictive
                        proof, trade evidence, or trading authority.
OBSERVATION_TIME        named field observation_ts_utc. A separate future
                        as-of lane; detected structurally but not
                        implemented in this PR.
FILENAME_INFERRED       exploratory only; excluded from primary analysis.
UNLABELED_EXPLICIT      an explicit timestamp with no named field to
                        establish its semantic role -- never coerced into
                        OBSERVATION_TIME or SNAPSHOT_TIME without a named
                        field as evidence.
```

Descriptive lane (`timestamp_lane`, records which named field established
the primary timestamp — `analysis_lane` in 3.5 is the authoritative Phase 2
eligibility gate):

```text
PRIMARY_SNAPSHOT_ALIGNMENT  primary_timestamp_role == SNAPSHOT_TIME.
FUTURE_OBSERVATION_ASOF     primary_timestamp_role == OBSERVATION_TIME.
EXPLORATORY_ONLY            everything else.
```

### 3.2 Fail-closed rules

- **Duplicate source identity** (identical sha256 content discovered at two
  or more paths) never aborts the inventory. Each sha256 is one canonical
  source identity; every discovered path is preserved as a sorted
  `alias_paths` list with `alias_count`. The event ledger produces one
  source event population per content hash, never one per alias path.
- **Impossible/internal inconsistency** is the only fail-closed condition
  tied to duplicate content: if the same sha256 ever produced non-identical
  parsed source identity, timestamp metadata, or row payload across its
  alias paths, the run raises and writes nothing. This can never happen for
  byte-identical bytes in a correctly functioning parser; it exists purely
  as a defensive invariant (tested directly, not via real files — see the
  test suite).
- **Ambiguous timestamp parsing** (multiple distinct explicit timestamp
  values found in one file with no way to prefer one) never selects a
  winner: `timestamp_provenance` is set to `UNKNOWN`, `status` is
  `AMBIGUOUS_TIMESTAMP`, and `analysis_lane` resolves to `EXPLORATORY_ONLY`.
- **Unsupported table schema** (header does not match the Table 1 or Table
  2 token set) is recorded per source as `UNSUPPORTED_SCHEMA` — never
  coerced into a Table 1 or Table 2 shape. The source is still listed in
  the inventory; it simply contributes no row-level records.
- **Conflicting asset alias** (the same raw token appears more than once
  inside one source's table body) is recorded as
  `DUPLICATE_ASSET_ALIAS_WITHIN_FILE`. Every raw row is preserved (never
  silently collapsed or best-of-picked); the source is excluded from
  primary-lane eligibility until a human resolves which row is authoritative.
- **Filename timestamps are diagnostic only.** `source_capture_ts_utc` is
  never required for `snapshot_alignment_eligible`, and it is never compared
  to `snapshot_ts_utc`. A filename timestamp equal to, before, or after
  `snapshot_ts_utc` is never treated as a failure of any kind — there is no
  ordering requirement between them in this model.
- Console/log summary output prints only provenance, counts, and schema
  findings. It never prints PHASE, COHERENCE, HARMONIC_PHASE, or any other
  table-body field value.

### 3.3 Parser correction: no arbitrary prose line becomes an asset row

Two anomalies were found in the real local corpus during initial
implementation: a trailing `Note: This snapshot is symbolic...` footer line,
and a stray `This snapshot reflects the current harmonic phase alignment...`
paragraph. Both happened to split into exactly the expected column count for
a Table 1 row under naive whitespace splitting, and were incorrectly counted
as asset rows (tokens `NOTE:` and `THIS`).

Fix: table rows in this corpus are contiguous. Once at least one row has
been parsed, the first blank line ends the table body. Everything after that
boundary — a footer note, stray prose, a second unsupported table — is never
a candidate asset row. It is recorded only as an `UNPARSED_NON_TABLE_LINE`
row-diagnostic (bounded to 50 trailing lines per source). A non-blank line
inside the contiguous body that fails to match the expected column shape is
recorded as `MALFORMED_TABLE_BODY`. Neither diagnostic ever becomes an asset
event, and both are covered by regression fixtures matching the two observed
anomalies exactly.

### 3.4 Source-token resolution

Each parsed asset row preserves its `raw_source_token` (exactly as written,
uppercased) separately from a `canonical_market_symbol`, resolved only
against an explicit, documented registry
(`MARKET_SYMBOL_ALIAS_REGISTRY` / `CANONICAL_MARKET_SYMBOLS` in the runner).
Aliases are never inferred from source text. A raw token not in the registry
is `asset_resolution_status = UNRESOLVED`: it is preserved as a diagnostic
row, not dropped, and excluded from primary-lane eligibility until a human
adds a reviewed registry entry.

One alias was found and documented from the real corpus:
`data/aplus_raw/2026-05-27_2149_june_reflection_subset_8_note.txt` writes the
CC token as `Canton (CC)` in the TOKEN column; the registry maps
`"CANTON (CC)" -> "CC"`.

### 3.5 The primary model: point-in-time snapshot alignment

Two prior drafts of this contract mis-modeled the named `prediction_ts_utc`
field, first as a retrospective target-alignment time and then as a forward
forecast target requiring a source-capture time strictly before it.
**Both have been corrected.** A+ Table 1 and Table 2 are point-in-time
snapshots. `prediction_ts_utc` is treated in this research lane as:

```text
snapshot_ts_utc = an A+ snapshot/evaluation timestamp,
                  parsed only from the named source field prediction_ts_utc.
                  The original raw field name is preserved for provenance
                  as snapshot_source_field_name = "prediction_ts_utc".
```

It is never treated as a future target time. There is no source-capture
time requirement, no ordering requirement, and no "S < T" condition of any
kind. Filename timestamps remain retained purely as source-capture
diagnostics (`source_capture_ts_utc` etc.) — never required for eligibility,
never compared to `snapshot_ts_utc`, and an equal (or later, or missing)
filename timestamp is never a failure.

One canonical event per:

```text
(canonical_source_hash, table_type, asset, snapshot_ts_utc)
```

A row is eligible for `analysis_lane = PRIMARY_SNAPSHOT_ALIGNMENT` only when
**all** of the following hold:

1. its canonical source is a supported, non-empty `TABLE1_CANONICAL_BREATHLINE`
   or `TABLE2_HARMONIC_OVERLAY` source;
2. source `status == OK` (this already excludes
   `DUPLICATE_ASSET_ALIAS_WITHIN_FILE` — i.e. no duplicate-asset ambiguity);
3. a named `prediction_ts_utc` value exists and parses as `snapshot_ts_utc`;
4. its own `raw_source_token` resolves to a `canonical_market_symbol`
   (`asset_resolution_status == RESOLVED`).

Criteria 1-3 are file-level (`snapshot_alignment_eligible`,
`snapshot_exclusion_reason` — one of `NOT_SUPPORTED_TABLE`,
`STATUS_NOT_OK`, `SNAPSHOT_TIME_MISSING`, checked in that priority order);
criterion 4 is row-level. Everything else is `EXPLORATORY_ONLY`.
`OBSERVATION_TIME` (`observation_ts_utc`) remains a separate, unimplemented,
future as-of lane, not required for this study.

## 4. Phase 2 — Preregistered Snapshot-Alignment Design (not implemented)

This section fixes the design before any code exists for it. No runner
implements this section yet. It must not be implemented or executed until
the Phase 1 ledger inventory (section 3) has been regenerated under the
snapshot-alignment model and reviewed.

### 4.1 Event ledger

One canonical event ledger row per:

```text
(canonical_source_hash, table_type, asset, snapshot_ts_utc)
```

The ledger is immutable and append-only, carries `canonical_source_hash` and
full timestamp provenance for every row, and produces exactly one event
population per canonical source hash — never one per alias path (section
3.2). Only `analysis_lane == PRIMARY_SNAPSHOT_ALIGNMENT` rows are in scope
for Phase 2.

### 4.2 Frozen-V1 adapter geometry: evaluate at `T`, using only candles closed by `T`

For every eligible event with snapshot timestamp `T`, for each checkpoint
`c` in `{0.618, 0.786}` and each offset `o` in
`{-10.5, -7, -5, -3, 0, 3, 5, 7, 10.5}` (the frozen V1 module's own default
2-checkpoint x 9-offset grid):

```text
derived_anchor_ts_utc = T - timedelta(days=(21.0 * c) + o)
```

The frozen V1 computation is invoked with `derived_anchor_ts_utc` as its
anchor such that its resulting `as_of` timestamp is exactly `T`. Frozen V1
must only receive candles whose close timestamp is `<=` the last fully
completed UTC daily candle before `T`; no candle spanning or ending after
`T` may enter the V1 adapter.

The complete 2-checkpoint x 9-offset grid (18 derived anchors) is emitted in
full for every event and asset; every raw score/state is preserved. The
adapter must not select a best anchor, best offset, or best checkpoint, and
must not perform any post-hoc selection, exactly as the existing Arm-A/B.2a
lanes never select a "best-looking" row ahead of the rest.

### 4.3 Matched shifted-time controls

For every `PRIMARY_SNAPSHOT_ALIGNMENT` event, for each `k` in the fixed,
preregistered integer-day shift registry (no `0d`):

```text
-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,+1,+2,+3,+4,+5,+6,+7,+8,+9,+10
```

apply the shift to the snapshot timestamp only:

```text
T_control = T + k calendar days
```

Same asset, same snapshot source/event, same clock time of day. Derived
anchors are recomputed from `T_control` using the identical section 4.2
formula (`derived_anchor_ts_utc = T_control - timedelta(days=(21.0 * c) + o)`)
for every checkpoint/offset pair. The anchor/offset is never selected after
results are known, for either the canonical event or any control. No
missing control may be silently dropped: a control that cannot be computed
(e.g. candle history unavailable) is recorded as `DATA_UNAVAILABLE` and
excluded from that control's population, never substituted.

These are **descriptive matched-time nulls, not forecast controls** — they
mirror the B.2a integer-day phase-null control design in
`docs/research/breathline_three_cycle_chain_and_v1_recovery_contract_v1.md`
section 10.2, applied to the A+ snapshot timestamp instead of the P0.3
canonical anchor cohort.

### 4.4 Daily-candle semantics at `T`

A+ snapshot timestamps are frequently intraday (e.g. `19:15:00Z`), while the
frozen V1 module operates on daily candles. At `T` (or `T_control`), V1 uses
the **last completed UTC daily candle at or before `T`** — the same
"raw-checkpoint as-of rule" already frozen in
`src/research/backtest_breath_curve_partial_to_full_v1.py` and preserved
unchanged by the Arm-A/B.2a lanes. No candle spanning or ending after `T`,
no interpolation, and no partial-day candle is ever used.

### 4.5 Side-by-side output, not a forced label conversion

Future Phase 2 output must present A+ evidence and V1 evidence side by side,
never as a single forced/scored comparison:

```text
token
snapshot_ts_utc
A+ source table type
A+ raw fields          (PHASE/COHERENCE/FIELD/... or HARMONIC_PHASE/PHASE_STATE/...,
                         verbatim, per section 3.4's resolved token)
Breathline V1 raw grid/state fields   (per section 4.2, the full 2x9 grid)
crosswalk_status
crosswalk_note
```

`crosswalk_status` is one of:

```text
EXACT_DEFINED     an explicit, preregistered mapping exists between a
                  specific A+ field/value and a specific V1 field/value.
PARTIAL_DEFINED   a documented, preregistered partial correspondence exists
                  (e.g. only some values map, or the mapping is directional
                  only), explicitly noted as partial.
UNMAPPED          no mapping is defined. The two fields are shown side by
                  side with no implied relationship.
```

**No semantic mapping between A+ labels (`PHASE`, `COHERENCE`, `FIELD`,
`HARMONIC_PHASE`, `PHASE_STATE`, etc.) and V1 outputs may be invented.** Any
mapping used to set `crosswalk_status` to `EXACT_DEFINED` or
`PARTIAL_DEFINED` must be explicitly documented and preregistered in a
future revision of this contract *before* any comparison score is
calculated from it. Until such a mapping is preregistered and reviewed,
every A+-label-to-V1-output pairing defaults to `UNMAPPED`.

### 4.6 Primary outputs (preregistered)

1. Immutable A+ event ledger with canonical source hashes and timestamp
   provenance/lane, keyed by `(canonical_source_hash, table_type, asset,
   snapshot_ts_utc)`.
2. Fixed-grid Breathline state vector evaluated at `T`, per section 4.2.
3. Matched shifted-time (descriptive, not forecast) control vectors (20 per
   event, per section 4.3).
4. The side-by-side crosswalk output of section 4.5 (A+ raw fields, V1 raw
   grid/state fields, `crosswalk_status`, `crosswalk_note`) — descriptive
   only until an explicit mapping is preregistered.
5. Asset-level cluster-aware uncertainty, clustering by source
   snapshot/event timestamp (not by row), matching the anchor-date
   cluster-bootstrap convention used throughout this research lane.
6. A pooled descriptive-only output, explicitly labelled cross-asset
   correlated / non-independent.
7. A provenance manifest with input hashes, source run IDs/commits, the
   fixed shift registry, counts, and complete output hashes.

### 4.7 Statistical and wording boundary

- No independent-row p-values.
- No "validated", "predictive", "confirmed", "trade", "signal", or
  promotion claims anywhere in outputs, code, or documentation for this
  study.
- No post-hoc field selection: the fixed 2x9 grid is preregistered here, not
  chosen after inspecting results.
- No invented semantic mapping between A+ labels and V1 outputs (section
  4.5) — every pairing defaults to `UNMAPPED` until explicitly preregistered
  and reviewed.
- Unsupported or ambiguous A+ fields (unresolved tokens, unsupported
  schemas, ambiguous timestamps) are reported as unavailable, never coerced
  into a supported shape.
- A+ remains an external symbolic/narrative research label, not market-data
  truth, throughout every output of this study. Snapshot alignment at `T` is
  not observation of a future event, not prospective validation, not
  predictive proof, not trade evidence, and not trading authority.

## 5. Implementation Sequence

```text
Phase 1  -> inventory + this contract (implemented; snapshot-alignment model
            corrected in this amendment, replacing the rejected two-time
            forecast-overlap model)
Phase 2  -> preregistered design only (this document, section 4); not
            implemented, not executed
Stop     -> do not implement or execute Phase 2 until the regenerated Phase 1
            ledger inventory has been reviewed
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
no execution of the Phase 2 snapshot-alignment comparison in this implementation round
no treating prediction_ts_utc as a future target/forecast time
no source-capture-time-before-snapshot-time (S<T) requirement of any kind
no invented semantic mapping between A+ labels and V1 outputs before a mapping
is explicitly preregistered and reviewed
no observation-of-a-future-event, prospective-validation, predictive-proof,
trade-evidence, or trading-authority claims for PRIMARY_SNAPSHOT_ALIGNMENT
```
