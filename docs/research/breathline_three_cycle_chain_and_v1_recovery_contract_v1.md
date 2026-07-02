# Breathline Three-Cycle Chain and Legacy V1 Recovery Contract v1

**Status:** DRAFT_FOR_CONTRACT_REVIEW
**Scope:** Research-only market context
**Decision status:** No promotion, runtime integration, or execution use
**Related work:** Legacy V1 recovery/control audit; V2 remains a separate retrospective calibration experiment

## 1. Purpose

This contract separates two research lanes:

1. **Legacy V1 recovery**
   - Determine exactly what the existing V1 partial-cycle algorithm measured.
   - Preserve V1 source semantics unchanged.
   - Compare its outputs against calendar-matched phase controls.

2. **Phase-relative Breathline chain discovery**
   - Detect repeating historical Breathline structure before making any forward claim.
   - Confirm a chain only after three consecutive base cycles.
   - Validate the fourth cycle forward, without re-fitting the chain during validation.

The system must not start from an arbitrary current timestamp and project a Breathline onto it.

The primary discovery unit is:

    THREE_CYCLE_CHAIN_CANDIDATE

Not:

    single anchor + assumed 21-day map

## 2. Architectural Boundaries


selection_engine
= market-only, account-agnostic

decision_gate
= account-aware permission layer

execution_planner
= execution intent only

executor / agents
= order handling only

Breathline research remains:

market-only
research-only
read-only
no orders
no broker calls
no DB writes from research runners
no account logic
no position sizing
no runtime trading authority

Regime remains independently owned:

market_participation / market_regime
→ independently computes regime snapshots

Breathline
→ may later read frozen as-of regime context
→ may not derive, rewrite, or classify regime
3. Evidence Roles
A+ datasheet
= immutable source seed / hypothesis index

market candles
= observed evidence

three-cycle detector
= confirms, rejects, or leaves a seed unresolved

historical ledger
= append-only record of candidates, evidence, and lifecycle observations

live continuation lane
= appends new evidence to existing lineage

A+ labels must never directly create a confirmed Breathline state.

A+ says phase / offset / stability
→ SOURCE_SEED

market evidence confirms sequence
→ CHAIN_CANDIDATE or CONFIRMED_HISTORICAL_CHAIN

market evidence fails sequence
→ REJECTED_SEED or UNCLEAR

The detector must eventually support both:

A+ seeded discovery
unseeded market-wide discovery

A+ seeding may prioritize research effort. It may not determine results.

4. Core Terms
Term	Meaning
phase_origin_candidate	Proposed asset-specific start coordinate for a Breathline. Never assumed confirmed merely because it exists.
candidate_period_days	Fixed base-cycle duration tested for one chain.
discrete_offset_band_days	Stable discrete phase offset associated with one candidate chain.
cycle_chain_candidate	Three sequential base cycles sharing one period and one offset-band contract.
chain_confirmed_as_of_ts_utc	Latest timestamp needed to observe the third cycle. No fourth-cycle data may contribute to confirmation.
fourth_cycle_validation	Forward-only observation of the next cycle after chain confirmation.
extension_context	Post-1.000 evidence attached to an earlier line; it does not prevent a new base-cycle candidate.
raw_lattice_anchor	Legacy V1/V2 replay coordinate only. Not a confirmed market phase origin.
source_seed_id	Immutable pointer to an A+ source row, ingestion batch, timestamp, and source hash.
5. Phase Sequence Contract

The base sequence is chronologically ordered:

0.236 FIRST_LIFT_HIGH
→ 0.382 FIRST_DIP_LOW
→ 0.500 SECOND_PEAK_RETEST_HIGH
→ 0.618 SECOND_DIP_HIGHER_LOW
→ 0.786 IGNITION_PRE_SPIKE
→ 1.000 MAIN_PULSE_REGION

The following are research-state definitions, not trading instructions:

0.618 FORMING
= 0.236 → 0.382 → 0.500 observed in chronological order

0.618 CONFIRMED
= FORMING
+ observed .618 higher-low structure

0.786 BUILDING
= .618 CONFIRMED
+ no structural failure already observed

0.786 ACTIVE
= BUILDING
+ observed .786 phase event

1.000 REGION OBSERVED
= valid preceding sequence
+ observed high evidence in the scheduled structural region

1.272 EXTENSION REGION OBSERVED
= valid 1.000 context
+ later high evidence in extension region

Volume, liquidity, BTC-relative behavior, and independent regime snapshots qualify an observed sequence as clean, mixed, dirty, strong, weak, or unusable.

They do not create a missing phase sequence.

6. Candidate Periods

21d is a legacy/default research candidate. It is not a universal truth.

Every period must be source-labeled:

A_PLUS_HARMONIC_CANDIDATE
= a period directly asserted or named in a verifiable A+ source batch
= requires all five provenance fields:
    source_seed_id              — immutable identifier for this source item
    source_capture_timestamp    — UTC timestamp when the source was captured
    source_content_sha256       — SHA-256 of the source content at capture time
    verbatim_supporting_text    — the exact A+ text asserting the period
    source_storage_locator      — pointer to the immutable archive or committed artifact
= no entry may be created without all five fields

SYNTH_DERIVED_HARMONIC_HYPOTHESIS
= a period derived by Synth arithmetic from a confirmed period using harmonic
  multipliers or ratios
= not directly asserted in any A+ source
= remains exploratory; may be elevated to A_PLUS_HARMONIC_CANDIDATE only when
  an A+ source explicitly states the harmonic relationship and a source_seed_id
  is filed

SYNTH_EXPLORATORY_CANDIDATE
= a discovery candidate not asserted by A+ source and not derived from an A+
  period by harmonic arithmetic
= requires empirical preregistration before outcome review

REJECTED_PERIOD
= tested and rejected under registered controls

Initial period registry for contract review:

Legacy candidate:
21d

A+ harmonic candidates — source confirmation required before use in chain discovery:
7d
11d
13d
17d
42d
63d

Synth-derived harmonic hypotheses — not A_PLUS_HARMONIC_CANDIDATES unless
an A+ source explicitly asserts the harmonic relationship and a source_seed_id
is filed:
21 × 1.618 ≈ 33.98d
21 × 2.618 ≈ 54.98d
21 ÷ 1.618 ≈ 12.98d
21 ÷ 2.618 ≈ 8.02d

Synth exploratory local-period candidates:
19d
20d
22d
23d

Rules:

one chain uses one fixed period

three cycles must use the same period

no 19d → 21d → 23d reconstruction

no per-cycle period tuning

no continuous drift used to rescue a failed chain

Any expansion of the candidate-period registry must be preregistered before
outcome review.

No A_PLUS_HARMONIC_CANDIDATE entry may be created without all five provenance
fields. A filesystem path alone is not sufficient provenance: the content must
be identified by its source_content_sha256. The source_storage_locator may
point to a local immutable archive or a committed artifact; mutable local files
may not be treated as immutable source evidence without a recorded hash.
source_seed_id must remain valid and resolvable even when the original local
source path is unavailable.

7. Three-Cycle Chain Discovery
7.1 Discovery logic

For each:

symbol
candidate_period_days
candidate_origin_ts_utc
discrete_offset_band_days

the detector searches for:

cycle 1: valid base sequence
cycle 2: valid base sequence
cycle 3: valid base sequence

Required cross-cycle consistency:

same candidate_period_days
same discrete_offset_band_days
chronological phase order preserved
no retroactive origin rewrite
no per-cycle score-weight tuning
no fourth-cycle data used for confirmation

The detector may retrospectively discover a historical chain.

It may not claim predictive validity from those same three cycles.

7.2 Confirmation boundary
cycles 1–3
→ retrospective discovery allowed

chain_confirmed_as_of_ts_utc
= latest evidence timestamp needed for cycle 3

cycle 4
→ forward-only validation

Cycle 4 must not alter:

candidate period
candidate origin
offset band
cycle 1–3 marker assignments
chain confirmation timestamp

before its forward assessment is archived.

7.3 Extension handling

Extensions do not block a new base-cycle candidate.

1.000
→ base-cycle transition region

1.272+
→ historical extension context

new .236
→ new origin candidate may coexist with old extension context

A previous chain remains historical context after a new candidate appears.

8. Lifecycle and Rollover Contract

The following are provisional Synth research states. They are not all original A+ source rules.

ORIGIN_CANDIDATE
FORMING
RECOGNITION_CONFIRMED
OVERFLOW_BUILDING
OVERFLOW_ACTIVE
TRANSITION_REGION_OBSERVED
EXTENSION_REGION_OBSERVED
NEW_ORIGIN_CANDIDATE
ROLLOVER_CONFIRMED
CHAIN_CONFIRMED_HISTORICAL
FOURTH_CYCLE_VALIDATING
EXTENDING
SUPEROVERFLOW_OR_RUPTURE_CANDIDATE
STRUCTURAL_INVALIDATION_CANDIDATE
UNCLEAR
RETIRED
REJECTED
8.1 Rollover

Provisional source-informed rule:

NEW_0236_OBSERVED
→ NEW_ORIGIN_CANDIDATE

NEW_ORIGIN_CANDIDATE
+ NEW_0382_OBSERVED_IN_CHRONOLOGICAL_SEQUENCE
→ ROLLOVER_CONFIRMED
→ NEW_LINE_ACTIVE_RESEARCH_CONTEXT

Constraints:

ROLLOVER_CONFIRMED
≠ three-cycle stability confirmation

NEW_LINE_ACTIVE_RESEARCH_CONTEXT
≠ runtime trade authority

bare .236
≠ automatic replacement of an old line

The old line remains:

historical context
extension context
superseded lineage candidate

The most recent active line means:

most recent ROLLOVER_CONFIRMED lineage

not:
most recent isolated .236 event
8.2 Deferred lifecycle states

The following lifecycle states are named but not yet operationalized.

No implementation transition may target these states until a separate
lifecycle operationalization contract is approved. No entry condition,
exit condition, or triggering evidence is defined for them here.

EXTENDING
SUPEROVERFLOW_OR_RUPTURE_CANDIDATE
STRUCTURAL_INVALIDATION_CANDIDATE
COMPLETED
EXHAUSTED
PHASE_DRIFTED
STRUCTURAL_INTEGRITY
PHASE_STABILITY
CLEAN_OR_DIRTY

They remain evidence labels or research hypothesis names until:

measurable entry and exit conditions are defined; and
a separate lifecycle operationalization contract is approved.

8.3 Fourth-cycle validation transitions

The following transitions are provisionally defined. They are the minimum
required to support the fourth-cycle forward validation design in §7.2.

CHAIN_CONFIRMED_HISTORICAL
+ fourth-cycle candle data available beyond chain_confirmed_as_of_ts_utc
→ FOURTH_CYCLE_VALIDATING

FOURTH_CYCLE_VALIDATING
+ valid base sequence observed in cycle 4
→ CHAIN_CONFIRMED_VALIDATED

FOURTH_CYCLE_VALIDATING
+ structural failure in cycle 4
→ FOURTH_CYCLE_REJECTED

A FOURTH_CYCLE_REJECTED outcome does not modify or erase the
CHAIN_CONFIRMED_HISTORICAL state for cycles 1–3. Historical confirmation
is based solely on evidence available at chain_confirmed_as_of_ts_utc
and is not retroactively invalidated by cycle 4 outcomes.

CHAIN_CONFIRMED_VALIDATED and FOURTH_CYCLE_REJECTED are terminal states
in this contract. No further transitions from either state are defined
until separately operationalized.

9. Historical Breathline Ledger

Storage and format

The historical ledger is append-only research data.

Storage location:
    data/research/breathline_historical_ledger/

Allowed artifact formats:
    JSONL, CSV, manifests, hashes, provenance records.

No new operational DB tables are created for the historical ledger.
No operational DB writes from research runners.
A future DB-backed research ledger requires a separate contract and a
dedicated research schema outside operational runtime tables.

A+ seed ingestion rules

Non-numeric A+ PHASE_OFFSET_BAND values, including drift, are ingested as:
    discrete_offset_band_days = null
    offset_band_status = INDETERMINATE

INDETERMINATE seeds are excluded from the primary THREE_CYCLE_CHAIN_CANDIDATE
discovery path until market-based retrospective discovery establishes a discrete
candidate band for that symbol. A seed with offset_band_status = INDETERMINATE
may coexist with a separately discovered chain for the same symbol.

For every A+ source-linked record, all five provenance fields must be populated:

    source_seed_id              — immutable identifier; remains valid when
                                  the original local path is unavailable
    source_capture_timestamp    — UTC timestamp of source capture
    source_content_sha256       — SHA-256 of the source content
    verbatim_supporting_text    — the exact A+ text
    source_storage_locator      — pointer to a local immutable archive or
                                  committed artifact whose contents are
                                  identified by source_content_sha256

Rules:
- source_storage_locator may point to a local immutable archive or committed artifact
- its contents are identified by source_content_sha256
- mutable local files may not be treated as immutable source evidence without
  a recorded hash
- source_seed_id must remain valid even when the original local source path
  is unavailable

Record schema

Historical records must be append-only.

breathline_chain
├── chain_id
├── symbol
├── model_version
├── source_seed_id
├── candidate_period_days
├── discrete_offset_band_days
├── offset_band_status
├── candidate_origin_ts_utc
├── cycle_1_evidence_id
├── cycle_2_evidence_id
├── cycle_3_evidence_id
├── chain_confirmed_as_of_ts_utc
├── chain_status
├── parent_chain_id
├── superseded_by_chain_id
├── lifecycle_state
├── source_provenance
└── created_at_utc
breathline_cycle_evidence
├── evidence_id
├── chain_id
├── cycle_index
├── phase_ratio
├── expected_ts_utc
├── observed_ts_utc
├── observed_price
├── marker_kind
├── sequence_status
├── timing_evidence
├── evidence_timeframe
├── source_candle_hash
├── observed_as_of_ts_utc
└── provenance

Rules:

new live evidence
→ may append new observations and status transitions

new live evidence
→ may not overwrite historical marker evidence

new origin
→ creates a new candidate lineage

old lineage
→ remains queryable after rollover or retirement
10. Legacy V1 Recovery Lane

V1 is a legacy algorithm audit.

It is not the definition of the future phase-relative Breathline model.

Frozen files:

src/research/backtest_breath_curve_partial_to_full_v1.py
src/market_context/breath_curve_core_v1.py
src/research/breath_curve_template_matcher_v1.py

No changes are allowed in the first recovery implementation.

Recovery taxonomy:

SOURCE_CODE_RECOVERY
= committed V1 source is executable without modification

SOURCE_DATA_RECOVERY
= exact original candle snapshot and hashes are available

RESULT_RECOVERY
= historical result reproduces row-for-row from exact code plus exact source data

A mutable live candle database may establish source-code recovery.

It cannot establish source-data or result recovery without the original hashed candle export.

10.1 Arm A: V1 partial exact recovery

Execute frozen V1 unchanged.

Preserve:

original offsets
original raw-checkpoint as-of rule
original positive-offset exclusion
original 36h tolerance
original scoring
original ranking
original selected winner behavior
original output CSV
original output JSONL
original scheduled-window high outcomes

The existing V1 JSONL already includes every partial offset in all_partial_offsets.

The recovery lane must preserve that raw JSONL unchanged.

10.2 Arm B: calendar-matched phase-null controls

Controls preserve:

same symbols
same calendar exposure
same V1 semantics
same candle source
same offset grid
same as-of rule
same outcome calculation
Arm B control metadata (required for all sub-arms)

Every Arm B control run must record two distinct fields per shift in the
control metadata CSV:

phase_class_mod_21_days
= the canonical representative of the phase class modulo 21d
= uniquely identifies which phase is being tested
= two displacements that are modulo-21 aliases of each other share the
  same phase_class_mod_21_days value
= example: both +10.5d and -10.5d → phase_class_mod_21_days = 10.5

anchor_displacement_days
= the actual signed day-count added to canonical anchor timestamps
= determines the finite calendar cohort for this control run
= two runs with the same phase_class_mod_21_days but different
  anchor_displacement_days produce different finite calendar cohorts;
  they must not be treated as independent evidence
= must be identical within a single control population

These fields must be preregistered for all shifts before any run.

B.1 HALF_CYCLE_PHASE_CONTROL
one deterministic +10.5d physical anchor displacement

phase_class_mod_21_days = 10.5
anchor_displacement_days = +10.5d (predeclared)

+10.5d and -10.5d are the same phase class modulo 21d but produce different
finite calendar cohorts separated by 21d at their boundaries. They must not
be counted as independent control populations.

B.2a INTEGER_DAY_PHASE_NULL_CONTROL

Phase displacements:
{-10d, -9d, -8d, -7d, -6d, -5d, -4d, -3d, -2d, -1d,
 +1d, +2d, +3d, +4d, +5d, +6d, +7d, +8d, +9d, +10d}

These are 20 distinct non-zero integer-day phase classes modulo 21d. No two
values in this set are modulo-21 aliases of each other. Together with the
canonical phase (0d) and the half-cycle class (±10.5d), they cover all
non-half-integer phase classes of the 21d cycle at 1d resolution.

Rules:

zero shift = canonical phase (Arm A)

same canonical anchor-date cohort retained for all shifts

all 20 shifts preregistered before any run

no result-driven shift changes or exclusions after inspection

no random historical date ranges

per-anchor data availability verified before running; anchors where the full
query window falls outside available candle history are recorded as
DATA_UNAVAILABLE in the manifest and excluded from that shift's population

Phase 2 implementation must begin with B.2a.

B.2a implementation status:

External orchestration runner:
    src/research/run_breathline_v1_recovery_orchestration_b2a_v1.py
Deterministic tests:
    tests/test_run_breathline_v1_recovery_orchestration_b2a_v1.py

The runner invokes frozen V1 unchanged once per (symbol, canonical anchor, shift)
combination across the fixed 20-shift registry, preserves raw V1 CSV/JSONL per
combination, and writes flattened analysis, sidecar metrics, control metadata,
manifest, per-symbol summary, and anchor-cluster uncertainty artifacts separately.
Availability is verified per combination from the frozen V1 run's own row status;
DATA_UNAVAILABLE combinations are recorded in control metadata and the manifest and
excluded from the flattened/sidecar analysis population, never substituted.

B.2a is matched phase-control research. It is not independent samples and not
trading authority. See the statistical note in section 10.3.

B.2b HALF_DAY_PHASE_NULL_CONTROL (deferred)

Candidate lattice: half-day increments over the half-open interval
[-10.5d, +10.5d) in 0.5d steps, excluding 0d.

Negative side: {-10.5d, -10.0d, -9.5d, ..., -0.5d} — 21 values
Positive side: {+0.5d, +1.0d, +1.5d, ..., +10.0d} — 20 values
Total: 41 non-zero, non-canonical control phase classes

+10.5d is excluded: it is an alias of -10.5d modulo 21d.
0d is excluded: it is the canonical phase (Arm A).
The 41 controls are all distinct modulo 21d.

Required precondition before B.2b may be run:
A smoke test must demonstrate that the frozen V1 runner accepts 12:00 UTC
anchor timestamps and produces valid daily-candle semantics when a half-day
offset is applied to a canonical anchor. B.2b is deferred until this smoke
test passes and is separately approved. It is not part of the Phase 2
implementation slice.

Anchor displacement and cohort identity

B.1 predeclares anchor_displacement_days = +10.5d.
B.2b must use the same physical displacement (+10.5d) for the half-cycle class
(phase_class_mod_21_days = 10.5).
The alias displacement (-10.5d) is excluded from B.2b.

Cohort boundary analysis:

+10.5d cohort:   {A_0 + 10.5,  A_1 + 10.5,  ...,  A_N + 10.5}
-10.5d cohort:   {A_0 - 10.5,  A_1 - 10.5,  ...,  A_N - 10.5}
               = {A_{-1} + 10.5, A_0 + 10.5, ..., A_{N-1} + 10.5}

These two cohorts share N of (N+1) anchor timestamps. They differ at one
boundary in each direction: +10.5d includes A_N+10.5 that the alias does not;
the alias includes A_{-1}+10.5 that +10.5d does not. They may not be treated
as independent evidence for the same phase class.

B.1 and B.2b literal subset condition:

B.1 is a literal subset of B.2b if and only if B.2b uses
anchor_displacement_days = +10.5d for the half-cycle class.
Under that condition the anchor timestamps are identical and B.2b may
inherit B.1 results rather than re-running for that class.
This condition must be verified from the control metadata
(anchor_displacement_days field) before any such inheritance is claimed.

Statistical note (applies to B.1, B.2a, and B.2b):

None of these control populations are statistically independent from the
canonical cohort. All share the same calendar period with a shifted phase.
They are matched phase controls, not independent samples.

The two alias displacements for the half-cycle class (+10.5d and -10.5d)
produce cohorts that share N of (N+1) anchor timestamps and must not be
counted as two independent control populations for the same phase class.
Only one physical displacement is evaluated per phase_class_mod_21_days.

10.3 Analysis outputs

Required artifacts:

raw V1 CSV
raw V1 JSONL
flattened all_partial_offsets analysis CSV
derived sidecar metrics CSV
control metadata CSV
manifest
per-symbol summaries
anchor-cluster uncertainty outputs

The raw V1 CSV and JSONL must be preserved exactly as written by the frozen
V1 runner. No post-processing modifies or replaces these files.

Flattened all_partial_offsets CSV derivation

The external orchestration runner reads each JSONL row's all_partial_offsets
array and writes one output row per (symbol, anchor_ts_utc, checkpoint_ratio,
phase_offset_days). It derives the following analysis fields from the existing
JSONL content. It does not re-implement or recompute partial matching, scoring,
or selection logic.

target_is_future
= direct copy of future_target_is_future from the all_partial_offsets item

required_marker_due
= false   when "REQUIRED_RATIO_NOT_DUE" is in result.notes
             (the required checkpoint marker's expected_ts is beyond as_of under
             the V1 raw-checkpoint rule; applies to positive offsets at both
             checkpoints)
= null    when "UNKNOWN_REQUIRED_RATIO" is in result.notes
             (the required ratio is not present in the markers list)
= true    otherwise
             (the required marker's expected_ts is at or before as_of; does
             not imply the marker was matched)

required_marker_matched

Primary derivation from result.markers:
  Step 1: find M in result.markers where
          abs(float(M.ratio) - required_ratio) < 1e-9
  Step 2: if no such M is found:
              required_marker_matched = null
  Step 3: if M is found:
              required_marker_matched = bool(M.matched)

Cross-check against result.notes (diagnostic):
  If required_marker_matched == True
  and "REQUIRED_RATIO_NOT_MATCHED" in result.notes:
      append DERIVATION_CONFLICT to score_zero_reason
      and preserve both the marker-derived value and the notes entry

  If required_marker_matched == False
  and "REQUIRED_RATIO_NOT_MATCHED" not in result.notes
  and "UNKNOWN_REQUIRED_RATIO" not in result.notes:
      append DERIVATION_CONFLICT to score_zero_reason
      and preserve both

  REQUIRED_RATIO_NOT_DUE does not create a conflict with required_marker_matched.
  When "REQUIRED_RATIO_NOT_DUE" is in result.notes, M exists with M.status == FUTURE.
  M.matched may be True or False without contradiction; the V1 code checks status
  before matched, so M.matched is unreliable for the FUTURE case.
  In that case required_marker_due = false already gates structurally_eligible;
  the value of required_marker_matched is preserved but carries reduced diagnostic
  weight and must not be used independently to set structurally_eligible.

  result.notes must be retained in score_zero_reason in full regardless of
  whether a conflict was detected.

min_due_markers_met
= false   when "INSUFFICIENT_DUE_MARKERS" is in result.notes
= true    otherwise

structurally_eligible
= true    when all of the following hold:
             target_is_future is true
             AND required_marker_due is true
             AND required_marker_matched is true
             AND min_due_markers_met is true
= false   otherwise

partial_match_score
= raw V1 field from result.partial_match_score

ranking_score
= raw V1 field from the all_partial_offsets item

selected_by_v1
= true    only for the offset whose phase_offset_days matches
             selected_partial_offset_days in the parent JSONL row
= false   for all other offsets

score_zero_reason
= ordered list preserving all applicable entries from result.notes that
  explain a zero or suppressed score; all distinct reasons retained without
  collapsing into an invented label; empty list when no zero-score reason
  applies; append DERIVATION_CONFLICT here when a note/marker conflict is
  detected (see above)

Explicit statements about the relationship between structural eligibility
and ranking_score:

structurally_eligible does not imply ranking_score > 0. A structurally
eligible offset may still receive partial_match_score = 0 due to absent or
weak marker evidence. When structurally eligible, ranking_score equals
partial_match_score.

ranking_score == 0 does not prove structural ineligibility. A zero ranking
score may result from a zero partial_match_score on a structurally eligible
offset.

A zero-ranking candidate may still be selected_by_v1 when all candidates
share the same (ranking_score, partial_match_score). The frozen V1 sort is
stable; when all candidates tie, the first offset in iteration order is
selected. Iteration order follows the --offsets argument, which defaults to
-10.5,-7,-5,-3,0,3,5,7,10.5.

Derived sidecar metrics

These are computed by the orchestration runner from the V1 JSONL and bounded
candle queries. They are written to a separate sidecar CSV and are never
merged into the V1 primary output or JSONL.

Derived metrics remain separate from raw V1 outcomes:

mfe_from_high_pct
mae_from_low_pct
close_to_close_1000_pct
time_to_window_high_bars

The legacy V1 return_to_1000_pct remains:

SCHEDULED_WINDOW_FAVOURABLE_EXCURSION

not:
realized trade return
target fill
execution result

Inference rules:

per-symbol results first

0.618 and 0.786 rows from one anchor-cycle are correlated

repeated 21d anchors are serially dependent

cross-asset returns are correlated

do not report row count as independent sample size

use anchor-date cluster-aware bootstrap or permutation

pooled aggregate is descriptive unless dependence is handled explicitly

No promotion threshold is set before Arm A/B outputs exist.

10.4 Arm-A vs Arm-B.2a Matched-Control Comparison Implementation Status

External comparison/report runner:
    src/research/run_breathline_v1_arm_a_b2a_comparison_v1.py
Deterministic tests:
    tests/test_run_breathline_v1_arm_a_b2a_comparison_v1.py

The runner never modifies either evidence archive. It verifies each archive's
tar.gz against its .sha256 file, extracts to an isolated scratch directory,
verifies the archive-internal SHA256SUMS against the extracted files, and only
then discovers and parses artifacts. It rejects (fails closed, no partial
output written) on any checksum mismatch, provenance mismatch, cohort/count
mismatch, missing or duplicate shift, incorrect canonical/shifted-anchor
mapping, or schema mismatch, for the preregistered exact cohort: 8 symbols x
28 anchors x 2 checkpoints x 9 offsets = 4,032 Arm-A rows, joined against
4,032 x 20 shifts = 80,640 B.2a rows with phase_class_mod_21_days ==
anchor_displacement_days enforced on every B.2a row.

Outputs: a matched-cell CSV (one canonical Arm-A row plus its 20 B.2a control
rows per join key), a per-cell contrast CSV for ranking_score,
partial_match_score, and structurally_eligible (canonical value, control mean/
median/min/max, tie-aware mid-rank percentile, canonical-minus-control-mean),
a per-symbol summary, a per-symbol canonical-anchor cluster bootstrap
uncertainty CSV, a pooled cross-asset descriptive-only summary, and a
manifest with input archive hashes, source run IDs/commits, registry, counts,
and output hashes.

Sidecar-outcome comparison is deferred: Arm-A's recovery orchestration
produces no sidecar metrics artifact, so Arm-A and B.2a sidecar schemas are
not directly equivalent without adaptation, which is out of scope here.

This comparison is matched phase-control descriptive research only. It is
not independent hypothesis confirmation and not trading authority: no
independent-row p-values, no promotion threshold, and no validated,
predictive, trade, execution, or ranking conclusion may be drawn from it.

11. Implementation Sequence
Phase 1
→ Claude High contract review
→ no code

Phase 2
→ standard implementation model
→ external V1 recovery/orchestration runner
→ raw V1 artifact preservation
→ JSONL flattening
→ sidecar metrics
→ manifests and provenance
→ half-cycle and exhaustive phase-null control support

Phase 3
→ execute Arm A and Arm B
→ archive outputs
→ assess source-code/data/result recovery status

Phase 4
→ approve separate three-cycle discovery implementation contract

Phase 5
→ A+ seed ingestion
→ historical chain discovery
→ fourth-cycle forward validation

Phase 6
→ append-only live continuation lane

Phase 7
→ independent regime/context stratification only after chain evidence exists
12. Explicit Non-Goals
no runtime trade logic
no account-aware logic
no selection_engine integration
no decision_gate integration
no execution_planner integration
no executor or broker calls
no dashboard or UI change
no V1 source mutation
no V2 source mutation
no merge decision for PR #39
no automatic phase-origin truth
no automatic completed/exhausted/phase-drifted labels
no A+ label used as hidden score or ground truth
no 1h research before daily/4h evidence passes controls
13. Claude 4.6 High Contract Review Prompt

MODEL ROUTING

Planning / architecture / research design:
→ Start with Claude 4.6 High.

Implementation after contract approval:
→ Switch to standard model.

Do not let the implementation model redefine architecture.

TASK

Review this document as a read-only architecture and research-contract audit:

docs/research/breathline_three_cycle_chain_and_v1_recovery_contract_v1.md

Do not implement code.
Do not edit files.
Do not create commits, branches, PRs, or artifacts.
Do not merge PR #39.

The task is to determine whether the contract is internally coherent, falsifiable, and compatible with the current repository.

Repository:

oboly/synth-v2

Required review areas:

Legacy V1 recovery lane
verify frozen V1 runner boundaries;
verify the existing JSONL already contains all partial offsets;
verify that an external orchestration runner can preserve raw V1 output;
review the calendar-matched half-cycle and exhaustive phase-null control design;
identify any modulo-21 aliasing or daily-resolution ambiguity.
Three-cycle chain discovery lane
verify that retrospective chain discovery and fourth-cycle forward validation are cleanly separated;
identify every potential look-ahead leak;
identify where marker detection, period discovery, origin discovery, and offset selection could accidentally be re-fit using cycle 4;
confirm that extension overlap does not invalidate a next-cycle candidate by default.
Period registry
distinguish A+ source-supported period hypotheses from Synth exploratory periods;
evaluate whether 19, 20, 22, and 23 days belong in an exploratory discovery registry;
propose a deterministic preregistered candidate-period protocol;
do not declare 21d universal.
Lifecycle and rollover
verify the separation between:
new origin candidate;
rollover confirmed;
active research context;
three-cycle historical confirmation;
identify any lifecycle state that is currently unsupported or circular;
preserve old and new lineages concurrently until an explicit confirmation rule resolves them.
A+ source boundary
A+ datasheets are immutable hypothesis seeds only;
distinguish raw A+ source wording from later Synth interpretation;
identify which fields must remain non-operational until measurable definitions exist;
do not convert A+ labels into truth, scoring, trade rules, or regime classification.
Architecture boundary
confirm no selection, decision, account, execution, broker, DB-write, UI, or dashboard responsibility leaks into either research lane;
regime remains independent and read-only when later used.

DELIVERABLE

Return one evidence-backed review with:

Contract elements that are ready to approve
Contradictions or ambiguous definitions
Required corrections before implementation
Exact external orchestration-runner responsibility boundary
Exact three-cycle discovery responsibility boundary
Look-ahead and control-design risks
Required source-recovery artifacts
Recommended smallest implementation slice
Explicit non-goals
Final status

Do not invent numeric promotion thresholds.
Do not recommend trading logic.
Do not add a third matcher.

End with exactly one line:

READY_FOR_CONTRACT_APPROVAL

or:

REQUIRES_CONTRACT_CORRECTIONS
