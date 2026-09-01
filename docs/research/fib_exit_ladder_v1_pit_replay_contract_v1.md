# Fib Exit Ladder V1 — Point-in-Time Replay Contract (Issue #707 Phase A)

Status: frozen contract, pre-execution
Layer: research only
Live trading permission: not granted
Evidence-gate role: this document only *defines* the replay protocol that
would, if executed and if it survives every criterion in
§ 10 (Promotion-grade criteria), become a future candidate promotion-grade
evidence source for `#657` Phase B
(`docs/architecture/automatic_exit_profile_promotion_v1.md`). It does not
itself run the replay, read any new outcome metric, or reach any
`VALIDATED` / `REVISED` / `REJECTED` / `INSUFFICIENT_DATA` disposition. Per
this task's instructions, no PIT outcome data has been inspected while
writing this document.

This contract is frozen **before** any point-in-time replay query is run.
It must not be edited after a replay result is inspected. Any change to
anchor eligibility, windows, candidate grid, selection metric, or
promotion-grade criteria after a result is seen invalidates the run and
requires a new contract version.

## 1. Purpose and non-goals

Purpose:

- Define a true point-in-time (PIT) replay protocol for the Fib Exit Ladder
  research lane that removes the future-aware anchor dependency identified
  in `#270` Phase A
  (`docs/research/fib_exit_ladder_v1_phase_a_validation_contract_v1.md`
  § "Look-ahead / promotion-grade classification").
- Make the PIT eligibility rule explicit and mechanically testable, so a
  test can prove no future candle is accessed at anchor-selection or
  scoring time.
- Freeze training/selection vs. out-of-sample (OOS) windows, the candidate
  policy grid, the selection metric, and the promotion-grade criteria
  *before* any new PIT outcome is computed.

Non-goals (explicitly out of scope for this Phase A):

- No production promotion. This contract does not itself validate,
  revise, or reject anything, and cannot be cited as satisfying `#657`
  Phase B's evidence requirement by itself — only a completed, criteria-
  meeting replay run under this contract could be (§ 10).
- No silent reuse of the `#270` future-aware anchor detector's semantics.
  `find_anchor_set` in `src/research/run_fib_exit_ladder_backtest_v1.py`
  (unchanged) remains `FUTURE_AWARE_RESEARCH` and is not point-in-time-safe
  (`future_high = max(candle.high for candle in candles[wave2_idx+1:])`,
  admitting a candidate only if that strictly-future maximum exceeds
  `wave1_high`). This contract defines a **separate** PIT anchor rule
  (§ 5); it does not patch, retune, or relax the `#270` detector.
- No execution of the replay engine in this Phase A beyond a minimal, pure
  research helper needed to make the contract's eligibility rule
  machine-testable (§ 13, "tiny pure research helper" allowance).
- No `#657` binding or profile writes of any kind.
- No account-aware, balance-aware, or order-aware data anywhere in this
  protocol.

## 2. Data source and timestamp semantics

Frozen, matching `#270`'s reproducible baseline source unless explicitly
noted:

```text
table:            obs_market_candle (read-only)
join key:         asset.symbol -> asset.asset_id (fetch_asset_id)
venue:            bitvavo
interval_code:    1d
column mapping:   detect_candle_columns (open_price/open, high_price/high,
                   low_price/low, close_price/close)
connection:       read-only session (SET SESSION TRANSACTION READ ONLY,
                   START TRANSACTION READ ONLY, explicit rollback() on
                   close), same discipline as
                   run_fib_exit_ladder_scoreboard_v1.connect_read_only.
                   No write-capable connection may be opened.
credentials:      SYNTH_DB_* / DB_* / MYSQL_* / MARIADB_* environment
                   variables or an explicit --env-file only; never hardcoded
                   or committed.
```

Candle timestamp meaning (frozen, this is the section that makes PIT
eligibility testable):

- `open_ts_utc` on a row is the **open** timestamp of that 1d candle. The
  candle's `high_price`/`low_price`/`close_price` are only fully known,
  and therefore only usable as replay input, **at or after that candle's
  close** — i.e. at or after the *next* candle's `open_ts_utc` (or, for the
  final available candle, only once no later candle exists to supersede it
  intraday).
- A candle at index `i` is "closed" and usable as of decision timestamp
  `t` iff `t >= candles[i + 1].open_ts_utc` (or, equivalently in a replay
  that walks candles in order, once processing has moved past index `i`).
  `open_price` on a still-open candle is not usable as replay input either;
  the whole candle is treated as unobserved until it closes, since
  `high_price`/`low_price` (needed for anchor/fill logic) are not known at
  open time.
- **Decision timestamp** = the timestamp at which the PIT replay is
  permitted to act (detect/confirm an anchor, or simulate a rung fill). A
  decision at timestamp `t` may read only candles whose close is `<= t`
  under the rule above — i.e. candles strictly before the candle containing
  `t`, plus the just-closed candle if `t` equals its close/next-open
  boundary exactly.
- **No same-candle information leakage**: the candle whose `open_ts_utc`
  a decision timestamp falls inside must never contribute its own
  `high_price`/`low_price`/`close_price` to that same decision. A decision
  timestamped at candle `i`'s open may use candles `0..i-1` only.
- This is strictly stricter than `#270`'s window-scoping guarantee (§ New
  validation window(s) in the `#270` contract), which only bounds *which
  window* an anchor may be detected in, not what is visible *within* that
  window at decision time. § 5 below defines the anchor/confirmation rule
  that this timestamp semantics is enforced against.

## 3. Universe

Frozen initial universe, matching `#270`'s originally-bucketed five assets:

```text
LINK
XLM
SOL
XRP
HOT
```

`HBAR` and `SUI` remain descriptive/out of scope for this Phase A, exactly
as in `#270` (§ 5 of the `#270` contract): no original bucket exists for
them, and no new bucket/family/asset assignment may be invented here to
force a usable PIT result for them. They may be reported in a future
findings document only as observational context, never contributing to an
overall PIT disposition or promotion-grade claim.

## 4. Training / selection / validation windows

Reuse the `#270` broad chronology, since it is already the frozen,
previously-reasoned window split and no new evidence has been inspected
that would justify moving it:

```text
SELECTION_WINDOW (training):          2020-01-01 00:00:00 -> 2022-01-01 00:00:00
OOS_WINDOW_1 (extension):             2022-01-01 00:00:00 -> 2024-01-01 00:00:00
OOS_WINDOW_2 (recent/live):           2024-01-01 00:00:00 -> 2026-09-01 00:00:00  (today)
venue:                                bitvavo
interval:                             1d
```

Rules:

- `SELECTION_WINDOW` is the only window in which family/fraction selection
  (§ 7) may occur. `OOS_WINDOW_1` and `OOS_WINDOW_2` are evaluated only
  after the policy selected on `SELECTION_WINDOW` is frozen (§ 8).
- The three windows are disjoint and evaluated independently: PIT anchor
  detection/confirmation for a window uses only candles inside that
  window, in addition to (never in place of) the per-decision PIT rule in
  § 5. A combined `2020-01-01 -> 2026-09-01` run is permitted only as a
  descriptive cross-check, never as a substitute for the disjoint windows
  the disposition is based on — identical to the `#270` contract's rule
  for this.
- **No retuning on `OOS_WINDOW_1` or `OOS_WINDOW_2`.** Once a
  family/fraction is selected on `SELECTION_WINDOW` per § 7, that selection
  is frozen before either OOS window's outcome is read. If OOS results
  motivate a different selection, that is reported as a finding (e.g.
  `REVISED`), never silently re-run with new parameters and re-reported as
  the original OOS result.

## 5. Point-in-time anchor eligibility (critical section)

This section defines the PIT-safe replacement for `#270`'s
`find_anchor_set` scoring rule. It is a distinct research object; it does
not modify `find_anchor_set` in `run_fib_exit_ladder_backtest_v1.py`,
which remains frozen and future-aware per `#270`.

### 5.1 Candidate detection (unchanged geometry, PIT-gated scope)

A candidate anchor triple `(anchor_low, wave1_high, wave2_low)` uses the
same geometric definition as `#270`'s detector — `anchor_low` a local low,
`wave1_high` a subsequent high satisfying the wave1 gain/day thresholds,
`wave2_low` a subsequent retracement low satisfying the retrace-ratio
bounds — with the same frozen threshold defaults:

```text
pivot_threshold_pct        = 0.25
min_wave1_gain_pct         = 1.00   (wave1 high >= 2x anchor low)
min_wave1_days             = 14
min_wave2_days_after_high  = 3
wave2_min_retrace          = 0.236
wave2_max_retrace          = 0.886
```

The difference from `#270` is entirely in **what data may be consulted to
detect and score a candidate**, not in the geometric thresholds:

- At the moment a candidate's `wave2_low` candle is being evaluated
  (candle index `wave2_idx`), detection and scoring may use **only**
  candles `0 .. wave2_idx` (inclusive, subject to § 2's closed-candle rule:
  candle `wave2_idx` itself is usable only once it is closed) — i.e. the
  anchor_low, wave1_high, and wave2_low candles themselves, and everything
  strictly before them.
- **Hard rule: no `future_high`.** Unlike `#270`'s
  `future_high = max(candle.high for candle in candles[wave2_idx+1:])`,
  no candle at an index `> wave2_idx` may be read for eligibility or for
  scoring a candidate anchored at `wave2_idx`.
- **Hard rule: no scan of candles after the candidate decision timestamp**
  for eligibility or score, for any candidate under consideration at that
  decision timestamp.
- **Hard rule: no future-return-derived anchor ranking.** Candidates may
  not be ranked or filtered by any quantity computed from candles after
  the candidate's own `wave2_low` index (this rules out `#270`'s
  `expansion = (future_high - wave2_low) / wave1_range` scoring rule
  verbatim, and any equivalent future-return-based score).

### 5.2 Confirmation event and decision timestamp

Because a raw `wave2_low` candidate cannot be scored by future expansion
under § 5.1, a PIT anchor requires an explicit **confirmation event**
defined and observable using only past/current data:

```text
confirmation_event:  the first candle, strictly after wave2_idx, whose
                      close_price closes back above wave1_high (i.e. the
                      retracement has been fully reclaimed and price is
                      making new local highs beyond wave1_high again).
confirmation_idx:     the index of that candle.
confirmation_ts:      candles[confirmation_idx].open_ts_utc (the candle's
                      own open timestamp — the event is observable once
                      this candle CLOSES, per § 2, i.e. at
                      candles[confirmation_idx + 1].open_ts_utc, not at
                      confirmation_idx's own open).
observable_ts:        candles[confirmation_idx + 1].open_ts_utc  (the
                      earliest timestamp at which the confirmation event's
                      close_price is knowable under § 2's closed-candle
                      rule; if confirmation_idx is the last available
                      candle in the window, the event is not yet
                      observable at all and the candidate remains
                      unconfirmed for that run).
```

- A candidate `(anchor_low, wave1_high, wave2_low)` is PIT-eligible only if
  a `confirmation_event` exists, i.e. some later candle's `close_price`
  exceeds `wave1_high`, and only using candles up to and including that
  confirmation candle to determine this — never any candle after it.
- **The simulated entry/decision may occur only at or after
  `observable_ts`.** `entry_ts` for a PIT anchor is `observable_ts`, not
  `wave2_low_ts` as in `#270`. `entry_price` is the `open_price` of the
  candle at `observable_ts` (the first fully tradeable price after
  confirmation is knowable) — not `wave2_low` (`#270`'s `entry_price`,
  which is a same-candle low unavailable at decision time).
- If multiple wave2 candidates for the same `anchor_low -> wave1_high` pair
  would each separately confirm, the PIT anchor is the **first** one whose
  `observable_ts` is reached scanning forward in time (earliest usable
  confirmation), not the one that would score highest by any future-aware
  measure. This keeps selection deterministic and avoids reintroducing a
  future-derived "best" candidate.
- **Downstream evaluation starts after the decision timestamp**: rung
  building, fill simulation, hold-return, and any other outcome metric for
  a PIT anchor use only candles at or after `observable_ts` as input to
  the ladder/hold simulation (the anchor geometry itself, i.e.
  `anchor_low`/`wave1_high`/`wave2_low` values and their timestamps, was
  already fixed using only candles at or before `observable_ts` per the
  rules above).

### 5.3 Machine-testability

This rule is testable directly against the semantics above: truncating a
candle series to end exactly at `observable_ts` (inclusive) must still let
the PIT detector confirm the same anchor and fix the same `entry_ts`,
because by construction nothing after `observable_ts` was used to reach
that confirmation. This is the PIT analogue of the existing `#270` test
`test_anchor_detector_requires_future_data_after_its_own_entry_point`,
which proves the *opposite* property for the frozen future-aware detector
(truncation destroys the anchor there). § 13 requires an equivalent test
for whichever PIT detector helper is added.

## 6. Candidate policy grid

Frozen initial candidate families, unchanged definitions from
`TARGET_FAMILIES` in `src/research/run_fib_exit_ladder_backtest_v1.py`
(research candidate space only — not production policy, and not a claim
that these are the correct or final families):

```text
PRO_3X4X:              multipliers [2.000, 2.618, 3.000, 4.000, 4.236]
                       fractions   [0.20,  0.25,  0.25,  0.20,  0.10]
SUPERCYCLE:            multipliers [2.618, 4.236, 6.854, 11.090]
                       fractions   [0.25,  0.35,  0.25,  0.15]
EXPLOSIVE_SUPERCYCLE:  multipliers [4.236, 6.854, 11.090, 17.944]
                       fractions   [0.20,  0.30,  0.30,  0.20]
```

`FIB_STANDARD` (also present in `TARGET_FAMILIES`) is not part of this
Phase A's frozen candidate grid — it was not part of `#270`'s originally
bucketed families and is not added here without evidence, per the "no new
bucket... invented" non-negotiable constraint carried over from `#270`.

Sell-fraction candidate grid, reused verbatim from
`DEFAULT_MAX_SELL_FRACTIONS` in `run_fib_exit_ladder_scoreboard_v1.py`,
labeled research candidate space only:

```text
max_ladder_sell_fraction candidates: 0.40, 0.50, 0.60, 0.70, 0.80
```

Ladder construction parameters held at the same frozen defaults as `#270`
(unchanged, `build_targets`/`build_rungs` in
`run_fib_exit_ladder_backtest_v1.py`):

```text
rungs_per_target       = 5
distribution           = front_loaded
target_zone_low_pct    = 0.04
target_zone_high_pct   = 0.04
front_run_pct          = 0.08
end_pct_of_zone_high   = 0.98
```

This yields the same 3-family x 5-fraction = 15-row-per-asset-per-window
grid shape as `#270`'s scoreboard sweep (over the 5-asset frozen universe,
105 rows per window before any PIT-specific narrowing from unconfirmed
candidates).

## 7. Selection metric

Selection happens exactly once, on `SELECTION_WINDOW` only, before either
OOS window is evaluated.

```text
primary ranking metric:    total_return_pct_with_remaining, computed under
                           the PIT anchor/entry rule (§ 5), for each
                           (asset, target_family, max_ladder_sell_fraction)
                           combination in the frozen grid (§ 6), on
                           SELECTION_WINDOW only.
selection unit:            per asset, the (target_family,
                           max_ladder_sell_fraction) pair with the highest
                           total_return_pct_with_remaining on
                           SELECTION_WINDOW becomes that asset's frozen
                           policy for both OOS windows.
tie handling:              if two or more (family, fraction) pairs tie
                           exactly on total_return_pct_with_remaining for
                           an asset, the tie is broken by (1) preferring
                           the lower max_ladder_sell_fraction (larger
                           moonbag reserve, the more conservative choice),
                           then (2) if still tied, the family earlier in
                           the fixed order PRO_3X4X, SUPERCYCLE,
                           EXPLOSIVE_SUPERCYCLE. A tie-break must never be
                           silently arbitrary (e.g. dict/iteration order).
minimum sample requirement: an asset contributes a selected policy only if
                           at least one PIT anchor was confirmed
                           (§ 5.2) and observable strictly inside
                           SELECTION_WINDOW for that asset under at least
                           one grid combination. An asset with zero
                           confirmed PIT anchors in SELECTION_WINDOW under
                           every combination cannot be selected on, and is
                           reported INSUFFICIENT_DATA for that asset (it is
                           not silently dropped from the universe; see § 9
                           and the `#270` contract's missing-data handling,
                           which this reuses).
zero-rung case:            a combination whose ladder fills zero rungs
                           (filled_fraction == 0, i.e. price never reaches
                           the lowest target zone before OOS/window end)
                           remains a valid, scoreable candidate — its
                           total_return_pct_with_remaining degenerates to
                           the pure hold-through-window return, which may
                           legitimately be the best-scoring combination and
                           must not be excluded from selection on that
                           basis alone.
missing/insufficient data: ASSET_NOT_FOUND / INSUFFICIENT_CANDLES (<20
                           candles) / no PIT-confirmed anchor are each
                           reported with that exact status; none is
                           silently treated as a 0% return or interpolated.
oracle/peak metrics:       peak_oracle_return_pct and top_capture_ratio
                           (both computed against the window-end/peak
                           candle, which is future-aware relative to the
                           selection point by construction) are diagnostic
                           only. They must never be used as a selection
                           input, ranking criterion, or tie-breaker under
                           this contract.
```

## 8. OOS evaluation

Evaluated only after § 7's selection is frozen, independently for each of
`OOS_WINDOW_1` and `OOS_WINDOW_2`, using each asset's selected
`(target_family, max_ladder_sell_fraction)` from `SELECTION_WINDOW` —
never re-selected per OOS window:

```text
total_return_pct_with_remaining   (primary OOS return metric)
hold_return_pct                   (baseline)
alpha_vs_hold_pct = total_return_pct_with_remaining - hold_return_pct
rung fills                        (fill_count, filled_fraction,
                                    remaining_fraction, avg_exit_price)
sample count                      (number of PIT-confirmed anchors
                                    contributing to the window's result per
                                    asset — see § 7 minimum sample
                                    requirement, evaluated per OOS window
                                    independently)
peak_oracle_return_pct,
top_capture_ratio                 diagnostic only, exactly as in § 7 —
                                    never used to alter, retune, or
                                    override the frozen selection.
```

An asset with no PIT-confirmed anchor observable inside a given OOS window
is reported with the applicable status (`NO_ANCHOR_SET_FOUND` /
`NO_FUTURE_CANDLES` / etc., reusing `#270`'s status vocabulary) for that
window; it does not fall back to `SELECTION_WINDOW`'s anchor or to a
synthesized value.

## 9. Revised bucket semantics

Per-asset conclusions reuse `#270`'s deterministic enum
(`src/research/fib_exit_ladder_v1_phase_a_disposition_v1.py`), since it is
already exhaustive, fail-closed, and reviewed, and this contract
introduces no new evidence that would justify a different enum:

```text
VALIDATED           the asset's SELECTION_WINDOW-frozen policy beats hold
                    (alpha_vs_hold_pct > 0) in every OOS window with a
                    PIT-confirmed anchor, with no reproduction-failure and
                    no ambiguous rank/sign evidence.
REVISED             mixed OOS evidence (see #270 disposition rules 3/4)
                    but majority sign agreement across the evaluated
                    windows still favors the ladder over holding.
REJECTED            the ladder never beats hold in any OOS window with a
                    PIT-confirmed anchor, or majority sign agreement fails.
INSUFFICIENT_DATA   no PIT-confirmed anchor in SELECTION_WINDOW (no policy
                    to select), or both OOS windows have no PIT-confirmed
                    anchor, or rank/sign agreement is unevaluated
                    (ambiguous, not a known disagreement).
```

These conclusions describe whether the PIT-selected policy generalizes
out-of-sample. They are **not** a production promotion decision by
themselves — see § 10.

## 10. Promotion-grade criteria

A completed PIT replay run under this contract is promotion-grade evidence
for `#657` only if **every** criterion below holds. Any single unmet
criterion fails closed to `promotion_grade=0` for the entire run,
regardless of how favorable the disposition (§ 9) is.

```text
1.  true_pit_eligibility     every anchor/entry decision used only candles
                             closed at or before its own decision
                             timestamp (§ 2, § 5) — verified, not assumed.
2.  no_look_ahead            no future_high, no future-candle scan, and no
                             future-return-derived ranking anywhere in
                             detection, confirmation, or selection (§ 5.1,
                             § 7's oracle/peak exclusion).
3.  disjoint_selection_oos   SELECTION_WINDOW and both OOS windows are
                             disjoint (§ 4), and no retuning occurred on
                             either OOS window (§ 4, § 8).
4.  deterministic_replay     identical inputs (candle data, grid, windows)
                             produce identical anchors, selections, and
                             outcome metrics on repeated runs (no
                             nondeterministic tie-breaking, ordering, or
                             floating-point-order-dependent aggregation).
5.  sufficient_sample_count  each asset claimed as promotion evidence has
                             at least one PIT-confirmed anchor in
                             SELECTION_WINDOW and at least one OOS window
                             (§ 7 minimum sample requirement); an asset
                             failing this is INSUFFICIENT_DATA (§ 9) and
                             excluded from a promotion-grade claim, not
                             silently counted as supporting one.
6.  positive_oos_alpha       the disposition reached is VALIDATED per § 9
                             (alpha_vs_hold_pct > 0 in every OOS window
                             with a PIT-confirmed anchor) for every asset
                             the claim covers.
7.  stable_reproducible      re-running the exact same query/window/grid
                             against the same underlying data reproduces
                             the same anchors and metrics (this is
                             criterion 4 checked empirically against the
                             live/replayed data, not only asserted as a
                             code property).
8.  immutable_raw_evidence   the exact raw per-(asset, window, family,
                             fraction) rows backing the claim are committed
                             as raw evidence with provenance (§ 11), not
                             hand-summarized only.
9.  verifier_reproduces      a deterministic verifier (§ 12) reproduces the
                             reported per-asset and overall result directly
                             from the committed raw evidence, independent
                             of the hand-written findings prose.
```

`methodology_promotion_grade = 0` is the default state of any run under
this contract until a specific completed run is checked against all nine
criteria above and passes every one; the mere existence of this frozen
contract does not itself grant promotion-grade status to anything.

## 11. Raw evidence and provenance contract

A future PIT replay run must commit, per run, at minimum:

```text
input_window_metadata:        venue, interval, from_ts, to_ts (exact,
                               per window), symbol universe, candle row
                               counts per (asset, window).
anchor_geometry:               anchor_low/anchor_low_ts, wave1_high/
                               wave1_high_ts, wave2_low/wave2_low_ts, per
                               PIT-confirmed anchor.
confirmation_and_decision_ts:  confirmation_idx/confirmation_ts,
                               observable_ts, entry_ts, entry_price
                               (§ 5.2), per PIT-confirmed anchor.
target_family:                 selected (SELECTION_WINDOW) and evaluated
                               (per OOS window) target_family per asset.
max_ladder_sell_fraction:      selected and evaluated value per asset.
returns:                       total_return_pct_with_remaining,
                               hold_return_pct, realized/remaining return
                               components, per (asset, window).
alpha:                         alpha_vs_hold_pct per (asset, OOS window).
rung_fills:                    fill_count, filled_fraction,
                               remaining_fraction, avg_exit_price per
                               (asset, window).
sample_counts:                 PIT-confirmed-anchor count per (asset,
                               window), and per-grid-combination row count
                               backing the selection in SELECTION_WINDOW.
provenance_hashes:              sha256 of every raw evidence file
                               committed, following the `#270`
                               provenance-doc pattern
                               (docs/research/fib_exit_ladder_v1_phase_a_provenance_v1.md).
methodology_version:           a version tag identifying this contract
                               document's version (this document, v1) that
                               produced the run.
code_commit_sha:                the exact commit SHA of the PIT replay
                               engine code used, where available.
```

Raw evidence is committed under `data/research/` per `#270`'s established
pattern (`data/research/fib_exit_ladder_v1_phase_a/`); a corresponding new
namespace (e.g. `data/research/fib_exit_ladder_v1_pit_replay/`) is used for
PIT-specific raw evidence so it is never conflated with `#270`'s
future-aware raw evidence.

## 12. Deterministic verifier contract

A future verifier (test or script) for a completed PIT replay run must:

```text
1. load the committed raw tracked evidence (§ 11) directly — never a
   hand-written summary document as its source of truth.
2. derive each reported per-asset result (selection, OOS metrics,
   disposition per § 9) purely from the raw evidence, using the same
   selection/disposition logic frozen in this contract (§ 7, § 9) — not
   re-deriving a different logic path.
3. derive the overall result from the per-asset results, over the
   complete frozen five-asset universe (§ 3), using the same fail-closed
   missing-asset/duplicate-asset handling `#270`'s
   `overall_disposition` already implements (extended to PIT if reused,
   or an equivalent PIT-specific implementation with the same guarantees).
4. validate the provenance hashes (§ 11) of every raw evidence file it
   reads match the hashes recorded at commit time, and fail rather than
   silently proceed on a mismatch.
5. must not depend on the accompanying findings prose being correct — if
   the verifier's derived result disagrees with a hand-written findings
   document, the verifier's derived result is authoritative and the
   findings document is wrong.
```

This is the PIT analogue of `#270`'s
`tests/test_fib_exit_ladder_v1_phase_a_raw_evidence_reproduction_v1.py`,
which independently re-derives the `#270` findings from committed raw
JSON.

## 13. Performance constraints

`#270`'s frozen future-aware implementation is CPU-heavy (`find_anchor_set`
is roughly cubic in candle count: nested loops over `low_idx`, `high_idx`,
`wave2_idx`, though the `suffix_max_high` precomputation already makes the
innermost `future_high` lookup O(1) rather than an O(n) scan per
candidate).

For a future PIT replay implementation:

- Detection/confirmation must remain deterministic and must not introduce
  an additional superlinear repeated-suffix-scan or repeated-future-scan
  pattern; confirmation-event lookup (§ 5.2) should be a single forward
  scan per `(anchor_low, wave1_high)` pair, not a re-scan per wave2
  candidate.
- Any performance optimization (precomputation, memoization, vectorization)
  must not alter PIT semantics — in particular, no optimization may
  introduce access to a candle at an index beyond what § 2/§ 5 permits at
  the timestamp being evaluated, even transiently (e.g. a suffix-max array
  computed once over the *entire* series, as `#270`'s detector does for
  `future_high`, is exactly the kind of precomputation that must not be
  reused here, since indexing into it at `wave2_idx` would again expose
  future data).
- This Phase A does not implement the full PIT replay engine (per this
  task's scope); § 15's tiny pure research helper, if added, must still
  respect this constraint at whatever scale it is exercised at (unit-test
  scale), so the constraint is exercised by a later Phase B's runner
  implementation.

## 14. Relationship to #270 and #657

```text
#270   prior findings (docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md,
       disposition REJECTED, methodology_promotion_grade=0,
       reason=FUTURE_AWARE_RESEARCH) remain historical retrospective
       evidence. They are not superseded, retracted, or re-run by this
       document.
#707   supersedes only the *methodology* to be used for any future
       promotion-grade evaluation attempt — i.e. any future attempt to
       satisfy #657 Phase B's point-in-time evidence requirement must use
       this contract's PIT protocol (or a later explicitly-versioned
       revision of it), not #270's future-aware detector.
#657   may consume only a separately validated promotion-grade result: a
       completed PIT replay run under this contract that passes every
       criterion in § 10. This document alone is a frozen protocol, not
       such a result, and grants no promotion eligibility to anything by
       existing.
```

No `automatic_exit_profile_v1` write, `decision_gate` change,
`execution_planner` change, or executor/runtime change is made by this
document or by any Phase A test added alongside it.

## 15. Required tests for Phase A (this document's own compliance)

Focused tests (added under `tests/`) must prove the frozen protocol itself
is coherent and fail-closed, without executing the replay:

```text
- reject any hypothetical detector/config that accesses a future candle
  index (index > the candidate's own confirmation/decision index) for
  eligibility or scoring.
- reject same-candle leakage: a decision at a candle's open timestamp must
  not be able to read that same candle's high/low/close.
- reject a selection routine that evaluates OOS-window data before
  SELECTION_WINDOW's policy is frozen (training/OOS separation).
- reject retuning: selecting a different policy per OOS window rather than
  reusing the SELECTION_WINDOW-frozen one.
- reject a promotion-grade claim when any one of the § 10 criteria is
  unmet (fail-closed enumeration, not merely a happy-path check).
- reject a promotion-grade claim when immutable raw evidence or a
  verifier (§ 11, § 12) is absent.
```

A tiny pure research helper (no DB access, no I/O) may be added if — and
only if — it is needed to make the § 5 PIT eligibility rule mechanically
testable (e.g. a candle-index-visibility helper proving no future index is
reachable from a given decision index). It must not implement rung
building, fill simulation, selection, or disposition logic; those remain
future (Phase B+) work per § 1's non-goals.

## Non-negotiable constraints

- No PIT outcome metric may be inspected before this contract is committed
  (task instruction; also self-consistent with § 10's requirement that the
  contract predates any result it might later evaluate).
- No bucket/family/fraction/threshold in `TARGET_FAMILIES` or this
  contract's PIT eligibility rule may change after any query result is
  seen once a replay is eventually run under this contract.
- No new bucket, family, or asset assignment may be invented to force a
  usable result.
- No production write path (`automatic_exit_profile_v1`, `selection_engine`,
  `decision_gate`, `execution_planner`, `executor`) is touched by this
  document or its accompanying Phase A tests.
- No account-aware, balance-aware, or order-aware data may enter this
  protocol.
- This document produces a research artifact under `docs/research/` only;
  no `data/research/` artifact is produced by this Phase A (no replay is
  run).
- No result may be cited as satisfying `#657` Phase B's promotion evidence
  requirement until a completed run under this contract passes every § 10
  criterion; this document by itself never does.

## Safety markers

```text
account_awareness=0
decision_permission=0
execution_intent=0
order_submission=0
live_orders=0
broker_private_calls=0
broker_writes=0
db_writes=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
automatic_exit_profile_v1_writes=0
production_promotion=0
runtime_activation=0
methodology_promotion_grade=0
pit_outcome_metrics_inspected=0
```
