# A+ → Breathline V1 Alignment Study Contract v1

**Status:** DRAFT — Phase 1 (inventory) implemented; Phase 2 (alignment comparison) preregistered here as a design only, not implemented, not executed
**Scope:** Research-only market/context alignment study
**Decision status:** No promotion, runtime integration, or execution use

## 1. Purpose

Determine whether frozen Breathline V1 detects a consistent phase/state at the
exact target timestamp of independently recorded A+ Table 1 / Table 2
records, compared with matched shifted-time controls.

This is not a trading feature. It is not connected to `selection_engine`,
`decision_gate`, `execution_planner`, `executor`, UI, DB writes, accounts,
broker, or strategy promotion. A+ remains an external symbolic/narrative
research label, not market-data truth. This is a target-alignment study, not
observation, not prospective validation, not predictive proof, not trade
evidence, and not trading authority.

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
  (e.g. `schema =`, `source_type =`, `status =`) — this is provenance
  metadata, not a table value;
- `token_count`: number of parsed asset rows (only for TABLE1/TABLE2 files;
  never includes a footer line or trailing prose — see 3.3);
- `explicit_timestamps`: every distinct explicit timestamp found in the
  source text, each tagged with its field name (if any) and resolved role;
- `filename_inferred_timestamp`: a timestamp parsed from the canonical
  path's filename only;
- `timestamp_provenance`: one of
  `EXPLICIT_SOURCE_TIMESTAMP` / `FILENAME_INFERRED_TIMESTAMP` / `UNKNOWN`;
- `timestamp_lane`: one of `PRIMARY_TARGET_ALIGNMENT` /
  `FUTURE_OBSERVATION_ASOF` / `EXPLORATORY_ONLY` — see 3.1;
- `status` and `status_notes`.

Per-row records (only for `TABLE1_CANONICAL_BREATHLINE` /
`TABLE2_HARMONIC_OVERLAY` canonical sources) preserve every raw Table 1 /
Table 2 field (`phase`, `coherence`, `field`, `geometry`, `structural_role`,
`expansion_quality`, `anchor_strength`, `strategic_bias`, `notes` for Table 1;
`harmonic_phase`, `phase_state`, `offset_band`, `drift_direction`, `quality`,
`extension_risk`, `notes` for Table 2), tagged with `canonical_source_hash`,
`canonical_source_path`, `detected_table_type`, `primary_timestamp_iso`,
`timestamp_provenance`, `primary_timestamp_role`, `timestamp_lane`,
`raw_source_token`, `canonical_market_symbol`, `asset_resolution_status`, and
`row_parse_status`. Lines that never became an asset row (a footer line, a
malformed row, trailing prose) appear in the same stream tagged
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

### 3.1 Timestamp provenance, role, and lane

Provenance (Phase 1, per canonical source, how confident we are that a
timestamp is real source evidence rather than a filename guess):

```text
EXPLICIT_SOURCE_TIMESTAMP     found literally in the source text
FILENAME_INFERRED_TIMESTAMP   parsed only from the filename
UNKNOWN                       no usable timestamp found, or found but ambiguous
```

Role (what a specific timestamp field means):

```text
PREDICTION_TARGET_TIME  named field prediction_ts_utc. This is the primary
                        A+ TARGET_ALIGNMENT_TIME for this study (approved
                        design decision, see 3.3). Never described as
                        observation-time, prospective validation, predictive
                        proof, trade evidence, or trading authority.
OBSERVATION_TIME        named field observation_ts_utc. A separate future
                        as-of lane; detected structurally but not
                        implemented in this PR (see 3.1 lanes below).
FILENAME_INFERRED       exploratory only; excluded from primary analysis.
UNLABELED_EXPLICIT      an explicit timestamp with no named field to
                        establish its semantic role (e.g. a bare
                        "(2026-05-15T12:44:48Z)" in a title line) — never
                        coerced into OBSERVATION_TIME or
                        PREDICTION_TARGET_TIME without a named field as
                        evidence.
```

Lane (which analysis lane a canonical source's primary timestamp feeds; this
is the field actually used to gate Phase 2 eligibility):

```text
PRIMARY_TARGET_ALIGNMENT  primary_timestamp_role == PREDICTION_TARGET_TIME.
                          Eligible for V1-state alignment at the A+ target
                          timestamp (Phase 2, section 4). This is the
                          primary lane for this study.
FUTURE_OBSERVATION_ASOF   primary_timestamp_role == OBSERVATION_TIME. A
                          separate as-of lane, not required for this
                          target-alignment study and not implemented here.
EXPLORATORY_ONLY          everything else (FILENAME_INFERRED,
                          UNLABELED_EXPLICIT, UNKNOWN). Never eligible for
                          Phase 2.
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
  `AMBIGUOUS_TIMESTAMP`, and `timestamp_lane` resolves to `EXPLORATORY_ONLY`.
- **Unsupported table schema** (header does not match the Table 1 or Table
  2 token set) is recorded per source as `UNSUPPORTED_SCHEMA` — never
  coerced into a Table 1 or Table 2 shape. The source is still listed in
  the inventory; it simply contributes no row-level records.
- **Conflicting asset alias** (the same raw token appears more than once
  inside one source's table body) is recorded as
  `DUPLICATE_ASSET_ALIAS_WITHIN_FILE`. Every raw row is preserved (never
  silently collapsed or best-of-picked); the source is excluded from
  primary-lane eligibility until a human resolves which row is authoritative.
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
row, not dropped, and excluded from Phase 2 eligibility until a human adds a
reviewed registry entry.

One alias was found and documented from the real corpus:
`data/aplus_raw/2026-05-27_2149_june_reflection_subset_8_note.txt` writes the
CC token as `Canton (CC)` in the TOKEN column; the registry maps
`"CANTON (CC)" -> "CC"`.

### 3.5 Approved design decision: `prediction_ts_utc` is the primary target-alignment time

Prior draft of this contract treated every explicit timestamp in the local
corpus as `prediction_ts_utc` / `PREDICTION_TARGET_TIME` and concluded zero
files were eligible for a primary analysis lane, because that lane required
`OBSERVATION_TIME`. This has been superseded by an approved design decision:

- `prediction_ts_utc` **is** the primary A+ `TARGET_ALIGNMENT_TIME` for this
  study and **is** eligible for the primary `PRIMARY_TARGET_ALIGNMENT` lane
  (section 3.1).
- It must never be described as observation-time, prospective validation,
  predictive proof, trade evidence, or trading authority — the study
  measures whether frozen V1's computed state aligns with what A+ recorded
  *at that named target timestamp*, nothing more.
- `OBSERVATION_TIME` (`observation_ts_utc`) remains a separate, future,
  as-of lane. It is detected structurally (the field pattern exists in the
  runner) but is **not implemented** in this PR and is not required for this
  target-alignment study.

## 4. Phase 2 — Preregistered Alignment Design (not implemented)

This section fixes the design before any code exists for it. No runner
implements this section yet. It must not be implemented or executed until
the Phase 1 ledger inventory (section 3) has been regenerated under the
corrected parser/dedup design and reviewed.

### 4.1 Event ledger

One canonical event ledger row per:

```text
(canonical_source_hash, table_type, asset, event_timestamp, timestamp_role)
```

The ledger is immutable and append-only, carries `canonical_source_hash` and
full timestamp provenance for every row, and produces exactly one event
population per canonical source hash — never one per alias path (section
3.2).

Timestamp roles/lanes remain separate and are never blended (section 3.1):

```text
PRIMARY_TARGET_ALIGNMENT  named prediction_ts_utc; the primary lane for
                          this study.
FUTURE_OBSERVATION_ASOF   named observation_ts_utc; not implemented here.
EXPLORATORY_ONLY          excluded from Phase 2 eligibility entirely.
```

### 4.2 Frozen-V1 adapter geometry (preregistered, not implemented)

For every `PRIMARY_TARGET_ALIGNMENT` event with target timestamp `T`
(`prediction_ts_utc`), for each checkpoint `c` in `{0.618, 0.786}` and each
offset `o` in `{-10.5, -7, -5, -3, 0, 3, 5, 7, 10.5}` (the frozen V1
module's own default 2-checkpoint x 9-offset grid):

```text
derived_anchor_ts_utc = T - timedelta(days=(21.0 * c) + o)
```

The frozen V1 computation is invoked with `derived_anchor_ts_utc` as its
anchor such that its resulting `as_of` timestamp is exactly `T`. This is the
inverse of V1's own forward computation
(`as_of = anchor + timedelta(days=(cycle_days * ratio) + offset_days)`,
`cycle_days = 21.0`, `ratio = c`) — solved for the anchor given a fixed
target `as_of = T`.

The anchor/offset pair is never chosen after seeing results: the full
2-checkpoint x 9-offset grid (18 derived anchors) is computed and every raw
score/state preserved for every event and asset, exactly as the existing
Arm-A/B.2a lanes never select a "best-looking" row ahead of the rest.

### 4.3 Matched shifted-time controls

For every `PRIMARY_TARGET_ALIGNMENT` event:

- same asset, same A+ event, same clock time as the canonical target `T`;
- exact integer-day shifts (fixed, preregistered, no `0d`):

```text
-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,+1,+2,+3,+4,+5,+6,+7,+8,+9,+10
```

- the shift is applied to the target timestamp (`T + shift`), never to the
  source record itself;
- derived anchors are recomputed from the *shifted* target timestamp using
  the identical section 4.2 formula (`derived_anchor_ts_utc = (T + shift) -
  timedelta(days=(21.0 * c) + o)`) for every checkpoint/offset pair;
- the anchor/offset is never selected after results are known, for either
  the canonical event or any control;
- no missing control may be silently dropped: a control that cannot be
  computed (e.g. candle history unavailable) is recorded as
  `DATA_UNAVAILABLE` and excluded from that control's population, never
  substituted.

This mirrors the B.2a integer-day phase-null control design in
`docs/research/breathline_three_cycle_chain_and_v1_recovery_contract_v1.md`
section 10.2, applied to A+ target-alignment timestamps instead of the P0.3
canonical anchor cohort.

### 4.4 Daily-candle semantics at an intraday target timestamp

A+ target timestamps are frequently intraday (e.g. `19:15:00Z`), while the
frozen V1 module operates on daily candles. At any target (or shifted
target) timestamp `T`, V1 uses the **last completed daily candle at or
before `T`** — the same "raw-checkpoint as-of rule" already frozen in
`src/research/backtest_breath_curve_partial_to_full_v1.py` and preserved
unchanged by the Arm-A/B.2a lanes. No interpolation, no partial-day candle,
and no forward-looking candle is ever used.

### 4.5 Primary outputs (preregistered)

1. Immutable A+ event ledger with canonical source hashes and timestamp
   provenance/lane.
2. Fixed-grid Breathline state vector at each eligible
   `PRIMARY_TARGET_ALIGNMENT` event (section 4.2).
3. Matched shifted-time control vectors (20 per event, per section 4.3).
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

### 4.6 Statistical and wording boundary

- No independent-row p-values.
- No "validated", "predictive", "confirmed", "trade", "signal", or
  promotion claims anywhere in outputs, code, or documentation for this
  study.
- No post-hoc field selection: the three contrast metrics and the fixed
  2x9 grid are preregistered here, not chosen after inspecting results.
- Unsupported or ambiguous A+ fields (unresolved tokens, unsupported
  schemas, ambiguous timestamps) are reported as unavailable, never coerced
  into a supported shape.
- A+ remains an external symbolic/narrative research label, not market-data
  truth, throughout every output of this study. Alignment with a named
  target timestamp is not observation, not prospective validation, not
  predictive proof, not trade evidence, and not trading authority.

## 5. Implementation Sequence

```text
Phase 1  -> inventory + this contract (implemented; parser/dedup corrected
            in this amendment)
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
no execution of the Phase 2 alignment comparison in this implementation round
no observation-time, prospective-validation, predictive-proof, trade-evidence,
or trading-authority claims for the PRIMARY_TARGET_ALIGNMENT lane
```
