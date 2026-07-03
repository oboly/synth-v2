# A+ → Breathline V1 Alignment Study Contract v1

**Status:** DRAFT — Phase 1 (inventory) implemented; Phase 2 (forecast-overlap comparison) preregistered here as a design only, not implemented, not executed
**Scope:** Research-only market/context alignment study
**Decision status:** No promotion, runtime integration, or execution use

## 1. Purpose

Determine whether frozen Breathline V1's state, computed strictly from
information available at an A+ source's capture time `S`, aligns with what
A+ separately recorded as its forward prediction target `T`, compared with
matched shifted-time controls that preserve the same `S`-to-`T` horizon.

This is a **forecast-overlap** study, not a retrospective one: the primary
question is whether V1's state as of `S` (using no information from between
`S` and `T`) says something consistent with A+'s own `T`-dated claim. This is
not a trading feature. It is not connected to `selection_engine`,
`decision_gate`, `execution_planner`, `executor`, UI, DB writes, accounts,
broker, or strategy promotion. A+ remains an external symbolic/narrative
research label, not market-data truth. It is not observation, not
prospective validation, not predictive proof, not trade evidence, and not
trading authority.

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
  `primary_timestamp_role`, `timestamp_lane` — legacy/retrospective metadata,
  preserved but demoted (never primary; see 3.5);
- **the two-time forecast-overlap fields (section 3.5, the primary model)**:
  `source_capture_ts_utc`, `source_capture_time_provenance`,
  `source_capture_time_eligible`, `prediction_target_ts_utc`,
  `prediction_target_time_provenance`, `lead_seconds`,
  `forecast_overlap_eligible`, `forecast_exclusion_reason`, `analysis_lane`;
- `status` and `status_notes`.

Per-row records (only for `TABLE1_CANONICAL_BREATHLINE` /
`TABLE2_HARMONIC_OVERLAY` canonical sources) preserve every raw Table 1 /
Table 2 field (`phase`, `coherence`, `field`, `geometry`, `structural_role`,
`expansion_quality`, `anchor_strength`, `strategic_bias`, `notes` for Table 1;
`harmonic_phase`, `phase_state`, `offset_band`, `drift_direction`, `quality`,
`extension_risk`, `notes` for Table 2), tagged with `canonical_source_hash`,
`canonical_source_path`, `detected_table_type`, `primary_timestamp_iso`,
`timestamp_provenance`, `primary_timestamp_role`, `timestamp_lane`,
`analysis_lane`, `forecast_overlap_eligible`, `raw_source_token`,
`canonical_market_symbol`, `asset_resolution_status`, and `row_parse_status`.
Lines that never became an asset row (a footer line, a malformed row,
trailing prose) appear in the same stream tagged
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

### 3.1 Timestamp provenance, role, and (legacy) lane

Provenance (per canonical source, how confident we are that a timestamp is
real source evidence rather than a filename guess):

```text
EXPLICIT_SOURCE_TIMESTAMP     found literally in the source text
FILENAME_INFERRED_TIMESTAMP   parsed only from the filename
UNKNOWN                       no usable timestamp found, or found but ambiguous
```

Role (what a specific timestamp field means):

```text
PREDICTION_TARGET_TIME  named field prediction_ts_utc. This is T in the
                        two-time forecast-overlap model (section 3.5) --
                        never described as observation-time, prospective
                        validation, predictive proof, trade evidence, or
                        trading authority on its own.
OBSERVATION_TIME        named field observation_ts_utc. A separate future
                        as-of lane; detected structurally but not
                        implemented in this PR.
FILENAME_INFERRED       exploratory only; excluded from primary analysis.
UNLABELED_EXPLICIT      an explicit timestamp with no named field to
                        establish its semantic role -- never coerced into
                        OBSERVATION_TIME or PREDICTION_TARGET_TIME without a
                        named field as evidence.
```

Legacy lane (`timestamp_lane`, preserved but no longer the eligibility gate
— see `analysis_lane` in 3.5):

```text
PRIMARY_TARGET_ALIGNMENT  primary_timestamp_role == PREDICTION_TARGET_TIME.
FUTURE_OBSERVATION_ASOF   primary_timestamp_role == OBSERVATION_TIME.
EXPLORATORY_ONLY          everything else.
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
- **Date-only filenames are never assigned a silent midnight default.** A
  filename without an `HH:MM` component cannot produce `S`; the source is
  `source_capture_time_eligible = False`, excluded from
  `PRIMARY_FORECAST_OVERLAP` via `SOURCE_CAPTURE_TIME_INELIGIBLE`, not
  coerced into a fabricated capture time.
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

### 3.5 The primary model: two-time forecast overlap (`S` and `T`)

A prior draft of this contract treated a single named timestamp
(`prediction_ts_utc`) as sufficient for a primary retrospective
target-alignment lane. **This has been corrected.** The desired primary
study is a genuine forward forecast-overlap check using two distinct times:

```text
S = source_capture_ts_utc
    Derived only from a filename containing both a date and an HH:MM time
    (YYYY-MM-DD_HHMM). Provenance label is exactly
    SOURCE_CAPTURE_TIME_FILENAME_UTC_ASSUMED. A date-only filename never
    produces S -- it is excluded, never assigned a silent midnight default.

T = prediction_target_ts_utc
    Parsed only from the named source field prediction_ts_utc. Never from
    an unlabeled bare timestamp, never from observation_ts_utc.
```

A canonical source is `forecast_overlap_eligible` (`analysis_lane =
PRIMARY_FORECAST_OVERLAP`) only when **all** of the following hold:

1. it is a supported, non-empty `TABLE1_CANONICAL_BREATHLINE` or
   `TABLE2_HARMONIC_OVERLAY` canonical source;
2. `status == OK`;
3. its filename contains both a date and an `HH:MM` time
   (`source_capture_time_eligible`);
4. a named `prediction_ts_utc` value exists (`T` resolves);
5. `S < T` (strictly before -- `S == T` is excluded, not treated as
   forward-looking);
6. `lead_seconds = T - S` is recorded.

Rows additionally require a `RESOLVED` `canonical_market_symbol` (section
3.4) to count toward the forecast-overlap event population.

A source that fails only criterion 5 or has no valid `T` at all, but does
have a valid legacy `PRIMARY_TARGET_ALIGNMENT` timestamp lane, is demoted to
`analysis_lane = RETROSPECTIVE_TARGET_ALIGNMENT`: **never primary, never
predictive**, kept only as legacy/retrospective metadata (not deleted).
Everything else is `EXPLORATORY_ONLY`.

`forecast_exclusion_reason` (one of `NOT_SUPPORTED_TABLE`, `STATUS_NOT_OK`,
`SOURCE_CAPTURE_TIME_INELIGIBLE`, `PREDICTION_TARGET_TIME_MISSING`,
`SOURCE_NOT_BEFORE_TARGET`) records exactly why an otherwise-plausible
source did not qualify, in that priority order.

**Observed finding:** in the current local corpus, every source whose
filename encodes a date+time and which also declares a named
`prediction_ts_utc` has `S == T` (the filename timestamp and the declared
prediction target are the same clock instant) or lacks an `HH:MM` filename
component entirely. As implemented, this yields **zero**
`forecast_overlap_eligible` sources today. This is a legitimate finding about
the current corpus, not a code defect: these sources describe same-moment
snapshots, not advance forecasts. New A+ sources whose capture time genuinely
precedes their declared target time will populate this lane going forward.
`OBSERVATION_TIME` (`observation_ts_utc`) remains a separate, unimplemented,
future as-of lane, not required for this study.

## 4. Phase 2 — Preregistered Forecast-Overlap Design (not implemented)

This section fixes the design before any code exists for it. No runner
implements this section yet. It must not be implemented or executed until
the Phase 1 ledger inventory (section 3) has been regenerated under the
forecast-overlap model and reviewed.

### 4.1 Event ledger

One canonical event ledger row per:

```text
(canonical_source_hash, table_type, asset, source_capture_ts_utc,
 prediction_target_ts_utc, analysis_lane)
```

The ledger is immutable and append-only, carries `canonical_source_hash` and
full timestamp provenance for every row, and produces exactly one event
population per canonical source hash — never one per alias path (section
3.2). Only `analysis_lane == PRIMARY_FORECAST_OVERLAP` rows are in scope for
Phase 2; `RETROSPECTIVE_TARGET_ALIGNMENT` rows are retained as demoted
metadata and never used as primary evidence.

### 4.2 Frozen-V1 adapter geometry: a forecast vector at `S`, for `T`

For every eligible `(S, T, asset)` event, for each checkpoint `c` in
`{0.618, 0.786}` and each offset `o` in
`{-10.5, -7, -5, -3, 0, 3, 5, 7, 10.5}` (the frozen V1 module's own default
2-checkpoint x 9-offset grid):

```text
derived_anchor_ts_utc = S - timedelta(days=(21.0 * c) + o)
```

The frozen V1 computation is invoked with `derived_anchor_ts_utc` as its
anchor such that its resulting `as_of` timestamp is exactly `S` — **not**
`T`. Frozen V1 must only receive candles whose close timestamp is `<=` the
last fully completed UTC daily candle before `S`; no candle spanning or
ending after `S` may enter the V1 adapter. This forms a forecast vector *at
`S`*, to be assessed *for `T`* — the adapter must never calculate V1 as-of
`T` in the primary lane, since that would leak information from between `S`
and `T` into the computation.

The complete 2-checkpoint x 9-offset grid (18 derived anchors) is emitted in
full for every event and asset; every raw score/state is preserved. The
adapter must not select a best anchor, best offset, or best checkpoint,
exactly as the existing Arm-A/B.2a lanes never select a "best-looking" row
ahead of the rest.

### 4.3 Matched shifted-time controls

For every `PRIMARY_FORECAST_OVERLAP` event, for each `k` in the fixed,
preregistered integer-day shift registry (no `0d`):

```text
-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,+1,+2,+3,+4,+5,+6,+7,+8,+9,+10
```

define:

```text
S_control = S + k calendar days
T_control = T + k calendar days
```

**Both** `S` and `T` shift by the same `k` — never `T` alone — so the
`S`-to-`T` horizon (`lead_seconds`), the same asset, and the same clock time
of day are preserved exactly. Derived anchors are recomputed from
`S_control` using the identical section 4.2 formula
(`derived_anchor_ts_utc = S_control - timedelta(days=(21.0 * c) + o)`) for
every checkpoint/offset pair. The anchor/offset is never selected after
results are known, for either the canonical event or any control. No missing
control may be silently dropped: a control that cannot be computed (e.g.
candle history unavailable) is recorded as `DATA_UNAVAILABLE` and excluded
from that control's population, never substituted.

This mirrors the B.2a integer-day phase-null control design in
`docs/research/breathline_three_cycle_chain_and_v1_recovery_contract_v1.md`
section 10.2, applied to the A+ `(S, T)` pair instead of the P0.3 canonical
anchor cohort.

### 4.4 Daily-candle semantics at `S`

A+ source capture times are frequently intraday (e.g. `08:00:00Z`), while
the frozen V1 module operates on daily candles. At `S` (or `S_control`), V1
uses the **last fully completed UTC daily candle at or before `S`** — the
same "raw-checkpoint as-of rule" already frozen in
`src/research/backtest_breath_curve_partial_to_full_v1.py` and preserved
unchanged by the Arm-A/B.2a lanes. No candle spanning or ending after `S`,
no interpolation, and no partial-day candle is ever used. This rule is keyed
to `S`, never to `T`.

### 4.5 Primary outputs (preregistered)

1. Immutable A+ event ledger with canonical source hashes and timestamp
   provenance/lane, keyed by `(S, T)`.
2. Fixed-grid Breathline forecast vector at `S`, for `T`, at each eligible
   `PRIMARY_FORECAST_OVERLAP` event (section 4.2).
3. Matched shifted-time control vectors (20 per event, per section 4.3, each
   preserving the `S`-to-`T` horizon).
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
   fixed shift registry, `lead_seconds` distribution, counts, and complete
   output hashes.

### 4.6 Statistical and wording boundary

- No independent-row p-values.
- No "validated", "predictive", "confirmed", "trade", "signal", or
  promotion claims anywhere in outputs, code, or documentation for this
  study.
- No post-hoc field selection: the three contrast metrics and the fixed
  2x9 grid are preregistered here, not chosen after inspecting results.
- Unsupported or ambiguous A+ fields (unresolved tokens, unsupported
  schemas, ambiguous timestamps, date-only filenames) are reported as
  unavailable, never coerced into a supported shape.
- A+ remains an external symbolic/narrative research label, not market-data
  truth, throughout every output of this study. Forecast overlap between `S`
  and `T` is not observation, not prospective validation, not predictive
  proof, not trade evidence, and not trading authority.

## 5. Implementation Sequence

```text
Phase 1  -> inventory + this contract (implemented; forecast-overlap model
            corrected in this amendment)
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
no execution of the Phase 2 forecast-overlap comparison in this implementation round
no observation-time, prospective-validation, predictive-proof, trade-evidence,
or trading-authority claims for PRIMARY_FORECAST_OVERLAP or
RETROSPECTIVE_TARGET_ALIGNMENT
no primary-lane or predictive use of RETROSPECTIVE_TARGET_ALIGNMENT
no silent midnight assumption for a date-only filename
no shifting only T without shifting S by the same amount in controls
```
