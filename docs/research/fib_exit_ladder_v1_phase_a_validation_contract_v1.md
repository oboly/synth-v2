# Fib Exit Ladder V1 — Phase A validation contract (Issue #270 Phase A)

Status: frozen contract, pre-execution
Layer: research only
Live trading permission: not granted
Evidence-gate role: upstream validation input for `docs/architecture/automatic_exit_profile_promotion_v1.md` (#657 Phase B). This document does not itself validate, revise, or reject anything; it fixes the method before any new outcome is read, per the #270 comment requiring exactly one of `VALIDATED` / `REVISED` / `REJECTED` / `INSUFFICIENT_DATA`.

This contract is frozen **before** any Phase A query beyond schema/connectivity checks was run. It must not be edited after validation results are inspected. Any change to bucket definitions, thresholds, or eligibility rules after results are seen invalidates the run and requires a new contract version.

## Provenance of the frozen original logic

Original methodology and code, unchanged, reconstructed from:

```text
src/research/run_fib_exit_ladder_backtest_v1.py     sha256:ffd3b4477f426e2c1bcbb93b59df06d12b5451b0f991344f190319f8efab760d
src/research/run_fib_exit_ladder_scoreboard_v1.py   sha256:07af7776f50716ee3654c61455452ba5de535ce91f3d0d835b35b38138b70ad5
docs/research/fib_exit_ladder_v1_findings.md        sha256:4dcab868ac8a6197cff5dfd1c94bb7c4b9f0fb0fa3ee502f6435141ff3c17b0e
```

Last commit touching the runners before this contract: `93a3d73` (help-text formatting only; the last logic-bearing commit is `a36350b`, "Add fib exit ladder research runners"). Base SHA for this Phase A branch: `c98f2a49e990cf79e9f4477f5241070b215ecd2c` (`origin/main`).

Phase A must call the existing functions in `run_fib_exit_ladder_backtest_v1.py` and `run_fib_exit_ladder_scoreboard_v1.py` unmodified. If a bug is found, it is reported as a finding, not silently patched, and the original (unpatched) run is still the one whose numbers back the disposition.

## 1. Source dataset(s)

- Table: `obs_market_candle` (read-only), columns resolved dynamically via `detect_candle_columns` (`open_price`/`open`, `high_price`/`high`, `low_price`/`low`, `close_price`/`close`).
- Join key: `asset.symbol -> asset.asset_id` (`fetch_asset_id`).
- `venue = "bitvavo"`, `interval_code = "1d"` (original defaults, unchanged).
- Connection: read-only session (`SET SESSION TRANSACTION READ ONLY`, `START TRANSACTION READ ONLY`, explicit `rollback()` on close) as already implemented in `run_fib_exit_ladder_scoreboard_v1.connect_read_only`. No write-capable connection may be opened for Phase A.
- DB credentials are sourced only from `SYNTH_DB_*` / `DB_*` / `MYSQL_*` / `MARIADB_*` environment variables or an explicit `--env-file`; no credential may be hardcoded or committed.

## 2. Eligibility rules (deterministic anchor detector, unchanged)

`find_anchor_set` in `run_fib_exit_ladder_backtest_v1.py`, run with its documented defaults:

```text
pivot_threshold_pct        = 0.25
min_wave1_gain_pct         = 1.00   (wave1 high >= 2x anchor low)
min_wave1_days             = 14
min_wave2_days_after_high  = 3
wave2_min_retrace          = 0.236
wave2_max_retrace          = 0.886
```

An asset is eligible for a window only if this detector returns a non-`None` `AnchorSet` for that window's candle series (`anchor_low -> wave1_high -> wave2_low`, `method="deterministic_low_high_retrace_expansion"`). No alternate anchor-detection method may be substituted. `min(candles) >= 20` remains a hard precondition (`evaluate_symbol`).

## 3. Original training/discovery window

```text
interval: 1d
from:     2020-01-01 00:00:00
to:       2022-01-01 00:00:00
venue:    bitvavo
```

This window is re-run unchanged as the reproduction baseline (§ Validation requirements: "reproduce original logic unchanged"), before any new window is evaluated.

## 4. New validation window(s)

Two out-of-sample windows, chosen to be disjoint from and entirely after the original window, extending evidence to the present:

```text
VALIDATION_WINDOW_1 (extension):     2022-01-01 00:00:00  ->  2024-01-01 00:00:00
VALIDATION_WINDOW_2 (recent/live):   2024-01-01 00:00:00  ->  2026-09-01 00:00:00   (today)
```

Each window is run independently (its own anchor search over only that window's candles — no anchor may be detected using candles outside the window it is scored in). This bounds which *window* a result is attributed to; it is a separate concern from whether the detector is point-in-time-safe *within* a window, which it is not — see "Look-ahead / promotion-grade classification" below. A combined `2020-01-01 -> 2026-09-01` run is permitted only as a descriptive cross-check, never as a substitute for the disjoint per-window runs the disposition is based on.

## 5. Asset universe handling

```text
Original usable (2021):     LINK, SOL, XRP, HOT, XLM
Original excluded (2021):   HBAR, SUI   (insufficient historical candles at that time)
```

Phase A re-attempts all seven original symbols (`LINK,SOL,XRP,HBAR,HOT,SUI,XLM`) in every window, including `HBAR`/`SUI`, since more candle history may now exist. No symbol may be silently dropped: every symbol/window pair must resolve to exactly one of the outcome statuses in § Missing-data handling. No symbol outside this original seven-symbol universe may be added — this validates the existing buckets, it does not discover new ones.

## 6. Setup/anchor logic

Unchanged from § Eligibility rules. Bucket assignment (asset -> exit-profile family) is **not** re-derived per window; it stays pinned to the original mapping so validation measures whether the *original* assignment still holds, not whether some other assignment would score better:

```text
EXIT_PROFILE_CONTROLLED_3X4X      (target_family=PRO_3X4X)              LINK, XLM
EXIT_PROFILE_SUPERCYCLE_BALANCED  (target_family=SUPERCYCLE)            SOL, XRP
EXIT_PROFILE_EXPLOSIVE_MOONBAG    (target_family=EXPLOSIVE_SUPERCYCLE)  HOT
```

`HBAR` and `SUI` have no original bucket assignment; if they now produce a usable anchor, they are reported as unassigned/descriptive only (§ Missing-data handling: `INSUFFICIENT_DATA` at the per-symbol-original-window level, since no 2021 bucket exists for them to validate).

Ladder parameters held at original defaults for every run: `max_ladder_sell_fraction=0.80`, `rungs_per_target=5`, `distribution=front_loaded`, `target_zone_low_pct=0.04`, `target_zone_high_pct=0.04`, `front_run_pct=0.08`, `end_pct_of_zone_high=0.98`. `TARGET_FAMILIES` multiplier/fraction tuples are used exactly as defined in the module (no retuning — see § Non-negotiable constraints).

## Look-ahead / promotion-grade classification

Code audit of `find_anchor_set` in `run_fib_exit_ladder_backtest_v1.py`
(unchanged, per § Provenance): for each candidate `(anchor_low, wave1_high,
wave2_low)` triple, the detector computes

```python
future_high = max(candle.high_price for candle in candles[wave2_idx + 1 :])
if future_high <= wave1_high:
    continue
expansion = (future_high - wave2_low) / wave1_range
score = expansion
```

and selects the candidate triple with the highest `score`. `wave2_low`
becomes `entry_ts`/`entry_price` in `evaluate_symbol`. `future_high` is the
maximum high of every candle **strictly after** the candidate entry point,
and a candidate is not even eligible (`continue`) unless that future data
exceeds `wave1_high`. The entry decision is therefore not confirmable, let
alone selectable among competitors, using only data available at the entry
point itself.

**This methodology is `FUTURE_AWARE_RESEARCH`, not point-in-time-safe.**
Any earlier or later document in this repository (including this contract's
own § New validation window(s), before this revision) that describes the
detector or its window-scoping as "no-look-ahead" is describing only the
separate, weaker property that a *window boundary* is respected (§ New
validation window(s)) — it is not a point-in-time-safety claim about
entry selection within a window, and must not be read as one.

Consequences, binding on this contract and any findings report built on it:

```text
methodology_promotion_grade = 0
reason                      = FUTURE_AWARE_RESEARCH
```

- A result from this methodology alone — `VALIDATED`, `REVISED`, or
  otherwise — is retrospective bucket-stability evidence only. It answers
  "did the originally-published buckets remain the best-scoring choice when
  the same in-hindsight selection rule is re-applied to later data", not
  "would this bucket have been selectable in real time".
- Per `docs/architecture/automatic_exit_profile_promotion_v1.md` § 2
  (evidence eligibility), promotion requires "point-in-time replay
  validation with no look-ahead leakage". This methodology's output
  therefore **must not**, by itself, satisfy `#657` Phase B's promotion
  evidence requirement, regardless of the disposition reached in
  § Acceptance thresholds.
- A true point-in-time replay (entry confirmed only from data available at
  or before `entry_ts`, with a separate, no-look-ahead re-detection or
  confirmation rule) is a distinct research slice, not implemented by this
  contract or by the frozen runners it wraps. It is out of scope for Phase A
  per this task's "do not invent replacement bucket values merely to obtain
  a usable result" and "do not retune after holdout inspection" constraints
  — building it would be a new methodology, not a re-run of the frozen one.
  It is recorded here as a dependency for whichever future Issue seeks
  promotion-grade evidence for `#657`, not fabricated in this document.
- Retrospective bucket-stability research remains legitimate under
  `AGENTS.md` Research Rules (future-aware data is permitted inside
  `src/research/`) and is exactly what § Acceptance thresholds evaluates.
  The distinction is only about what the *output* may be used for
  downstream: bucket-stability review, yes; `#657` production promotion
  evidence, no.

## 7. Metrics

Per symbol per window, taken directly from `SymbolResult` / scoreboard row, no re-derivation:

```text
status                                         (OK / ASSET_NOT_FOUND / INSUFFICIENT_CANDLES / NO_ANCHOR_SET_FOUND / NO_FUTURE_CANDLES)
sample count                                    = 1 candidate structure per symbol per window (this methodology is single-anchor,
                                                   not a multi-trade sample; § Acceptance thresholds treats cross-window/cross-asset
                                                   agreement, not within-window trade count, as the sample axis)
fill_count / filled_fraction                    (how much of the ladder actually filled)
remaining_fraction
avg_exit_price
realized_return_pct_on_full_position
remaining_return_pct_on_full_position
total_return_pct_with_remaining                 (primary return metric)
hold_return_pct                                 (baseline)
peak_oracle_return_pct                          (upper bound)
top_capture_ratio                               (total_return / peak_oracle_return)
alpha_vs_hold_pct = total_return_pct_with_remaining - hold_return_pct
```

Cross-window stability metrics (computed in the findings report, not new runner code):

```text
bucket_sign_agreement     = alpha_vs_hold_pct has the same sign in >=2 of the 3 windows (original + both validation windows)
bucket_rank_agreement     = the asset's originally-assigned family remains the highest-total_return family among the 3
                             defined families for that asset in each window where an anchor was found
top_capture_stability     = |top_capture_ratio(window) - top_capture_ratio(original)| reported per window, no pass/fail threshold
                             by itself (informational)
```

## 8. Acceptance thresholds

Applied per originally-bucketed asset (`LINK`, `SOL`, `XRP`, `HOT`, `XLM`), across the two validation windows plus the reproduced original window. The rules below are evaluated in the fixed order given (first match wins), so every reachable combination of baseline/validation outcomes maps to exactly one disposition — no combination is left undefined. A reference implementation of this exact ordering is `classify_asset_disposition` in `src/research/fib_exit_ladder_v1_phase_a_disposition_v1.py`; a findings report must use it (or reproduce its logic verbatim) rather than deriving the disposition ad hoc.

```text
0. BASELINE NOT EVALUABLE
   If the original (2020-01-01 -> 2022-01-01) window does not reach status=OK with a detected
   anchor for this asset under the frozen methodology (contrary to the published 2021 findings,
   which recorded a result for every one of LINK/SOL/XRP/HOT/XLM): INSUFFICIENT_DATA. There is no
   baseline to validate against.

1. BASELINE REPRODUCTION FAILURE  (fail-closed; must precede every other rule below)
   If the original window IS evaluable (status=OK, anchor detected) but its
   total_return_pct_with_remaining / hold_return_pct / anchor timestamps do not match the
   historical findings doc within rounding tolerance under the unmodified, frozen methodology:
   REJECTED, reason=BASELINE_REPRODUCTION_FAILED.
   This never resolves to VALIDATED or REVISED regardless of how the validation windows score,
   because Phase A cannot state confidently that the frozen methodology was actually reproduced,
   and an unreproducible baseline must not be presented as promotion evidence in either direction.
   This is distinct from a REJECTED verdict reached by successfully reproducing the baseline and
   then finding the ladder does not beat holding (rule 4 below) — a findings report must state
   which of the two applies.

2. VALIDATION WINDOWS ALL NON-OK
   If baseline reproduction succeeded (rule 1 did not fire) but both validation windows return a
   non-OK status: INSUFFICIENT_DATA. The original claim reproduces, but cannot be re-tested outside
   the original window at all.

3. VALIDATED  requires ALL:
  - rule 1 did not fire (baseline reproduced).
  - at least 1 of the 2 validation windows yields status=OK with a detected anchor.
  - in every validation window with status=OK: alpha_vs_hold_pct > 0 (ladder beats hold) AND
    the originally-assigned target family remains the best-total_return family among the 3 families
    for that asset in that window (bucket_rank_agreement holds, i.e. is explicitly `True` — an
    unevaluated/unknown rank-agreement input is not "holds").

4. REVISED  requires:
  - rules 0-2 did not fire (baseline reproduced, >=1 validation window OK), AND
  - rule 3 (VALIDATED) did not match, i.e. either >=1 OK validation window has alpha_vs_hold_pct <= 0
    while >=1 other OK validation window has alpha_vs_hold_pct > 0 (a MIXED positive/negative
    OK-window set — this must never be reported as VALIDATED even if bucket_rank_agreement holds
    in the positive window(s)), or every OK validation window has alpha_vs_hold_pct > 0 but
    bucket_rank_agreement fails in >=1 of them (a different family scores better), AND
  - bucket_sign_agreement holds (ladder beats hold in at least 2 of the 3 windows including
    original), so the asset->family mapping itself is not defensible unchanged, though "use a
    ladder over holding" still is.

5. REJECTED (reproduction succeeded)  requires:
  - rules 0-2 did not fire (baseline reproduced, >=1 validation window OK), AND
  - EITHER alpha_vs_hold_pct <= 0 in every validation window with status=OK (ladder never beats
    hold out of the original window), OR the mixed/rank-disagreement condition in rule 4 holds but
    bucket_sign_agreement does not (majority sign disagreement across the 3 windows).
  This is a negative result from successfully reproducing the methodology, and must be reported
  with a different (or absent) reason string than rule 1's `BASELINE_REPRODUCTION_FAILED` so the
  two REJECTED causes are never conflated.
```

Rules 0-5 are exhaustive and mutually exclusive over every reachable combination of baseline/validation outcomes: rule 0 covers a non-evaluable baseline, rule 1 covers an evaluable-but-unreproduced baseline (fail-closed, always REJECTED), rule 2 covers a reproduced baseline with no usable validation window, and rules 3-5 partition every remaining case (>=1 OK validation window with a reproduced baseline) by sign/rank agreement. No combination of baseline/validation outcomes is left without a defined disposition.

`bucket_rank_agreement_all_ok_windows` and `bucket_sign_agreement` are each tri-state (`True` / `False` / unknown). An unknown value at the point rule 3 or rule 4/5 needs it is missing/unevaluable evidence, not a known disagreement — it must never be inferred as satisfying rule 3 or rule 4 (i.e. never silently treated as `True`), and must not be silently treated as `False` either (which would produce a REJECTED that overstates confidence in a negative finding). Both cases fail closed to `INSUFFICIENT_DATA` instead: preferred over `REJECTED` because the defect is missing evidence, not a contradictory result.

The overall Phase A disposition is the least favorable outcome across the complete, exact frozen five-asset universe (`LINK`, `XLM`, `SOL`, `XRP`, `HOT` — see § 5 Asset universe handling), using the ordering `REJECTED < REVISED < VALIDATED` for defensibility. `overall_disposition` may only be computed once every one of these five assets is represented exactly once:

- A duplicate entry for the same asset, or an asset outside this five-asset universe (including `HBAR`/`SUI`, which have no original bucket per § 5/§ 9), is a malformed input and must not be silently included or excluded — a findings report or its tooling must fail closed (reject the input) rather than compute an overall result from it.
- A missing required asset is treated exactly as if that asset had independently returned `INSUFFICIENT_DATA`: an incomplete universe can never yield an overall result more favorable than `INSUFFICIENT_DATA`, regardless of how favorably the present assets scored. This is the same principle already stated for an explicit per-asset `INSUFFICIENT_DATA`, extended to an asset that was never evaluated at all — omission must not be a way to obtain a better overall result than actually running the missing asset would.
- Any asset reaching rule 1 (`BASELINE_REPRODUCTION_FAILED`) forces the overall disposition to at least `REJECTED`, with the reason carried through explicitly, regardless of how other assets score.

`overall_disposition` in `src/research/fib_exit_ladder_v1_phase_a_disposition_v1.py` is the reference implementation of this exact universe check.

If Phase A cannot execute the runners against real data at all (no DB access, no equivalent dataset), the disposition is `BLOCKED`, a distinct state from `INSUFFICIENT_DATA` (inability to run vs. the detector legitimately finding nothing).

## 9. Missing-data handling

- A symbol/window pair that raises `ASSET_NOT_FOUND` is reported as such, not treated as `0` return.
- A symbol/window pair with `INSUFFICIENT_CANDLES` (`< 20` candles) or `NO_ANCHOR_SET_FOUND` or `NO_FUTURE_CANDLES` is reported with that exact status string; it never falls back to a synthesized anchor or interpolated candle.
- `HBAR`/`SUI` (no 2021 bucket) are reported descriptively only; they cannot produce `VALIDATED`/`REVISED`/`REJECTED` under this contract because there is no original assignment to validate — at most `INSUFFICIENT_DATA` (no baseline) or a note that new bucket discovery is out of scope (§ Non-negotiable constraints).
- Fail-closed: if the DB is unreachable, or `obs_market_candle` lacks coverage for a required venue/interval/window, Phase A stops and reports `BLOCKED`, never a partial run presented as a full one.

## 10. Deterministic outcome categories

Exactly one of the following is the Phase A conclusion, stated explicitly in the findings report:

```text
VALIDATED           all five originally-bucketed assets meet the VALIDATED bar in § Acceptance thresholds
REVISED              at least one asset meets REVISED and none meet REJECTED or force-level INSUFFICIENT_DATA
REJECTED             at least one asset meets REJECTED
INSUFFICIENT_DATA    the runners execute against real data but the detector/coverage cannot produce
                     an evaluable result for enough of the universe to judge the original claim
BLOCKED              Phase A cannot execute the runners against real historical data at all in this
                     environment (e.g. no DB access, no substitute dataset) — distinct from INSUFFICIENT_DATA
```

A `REJECTED` outcome additionally carries a `reason` when it was reached via
Acceptance-thresholds rule 1: `reason=BASELINE_REPRODUCTION_FAILED`. This
reason is informational metadata on a `REJECTED` disposition, not a sixth
outcome category — the five-way enum above stays exhaustive and unchanged;
see § Acceptance thresholds rule 1 for when it applies and why it is
fail-closed (never `VALIDATED`/`REVISED`).

Independently of which of the five outcomes above is reached, § Look-ahead /
promotion-grade classification fixes `methodology_promotion_grade=0`,
`reason=FUTURE_AWARE_RESEARCH` for every disposition produced under this
contract's frozen anchor detector. A `VALIDATED` outcome answers "do the
original buckets remain the best in-hindsight choice", not "is this
promotion-grade evidence for `#657`" — the two questions are orthogonal and
both must be reported.

## Non-negotiable constraints

- No bucket definition, multiplier, fraction, or threshold in `TARGET_FAMILIES` or the anchor detector may change after any query result is seen. A finding that the current buckets look wrong is reported as `REVISED`/`REJECTED`, not silently retuned.
- No new bucket, family, or asset assignment may be invented to force a usable result.
- No production write path (`automatic_exit_profile_v1`, `selection_engine`, `decision_gate`, `execution_planner`, `executor`) is touched by Phase A.
- No account-aware, balance-aware, or order-aware data may enter this evaluation.
- Phase A produces research artifacts under `docs/research/` and, if a run executes, `data/research/` only.
- No result produced under this contract's frozen anchor detector may be cited as satisfying `#657` Phase B's point-in-time promotion evidence requirement; see § Look-ahead / promotion-grade classification.
