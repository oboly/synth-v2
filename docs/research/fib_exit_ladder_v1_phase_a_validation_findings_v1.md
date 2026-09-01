# Fib Exit Ladder V1 — Phase A validation findings (Issue #270 Phase A)

## Disposition

```text
REJECTED
```

This supersedes the prior `BLOCKED` version of this document. The DB blocker
recorded there is resolved: frozen validation artifacts now exist (produced
by an unmodified run of `run_fib_exit_ladder_scoreboard_v1.py`) and this
report is computed exclusively from them, per
`docs/research/fib_exit_ladder_v1_phase_a_validation_contract_v1.md`. No
backtest was re-run to produce this document; the contract itself was not
edited.

Independently of this outcome, the frozen methodology is classified
`FUTURE_AWARE_RESEARCH` (unchanged from the prior version of this document —
see below). `methodology_promotion_grade=0` regardless of which of the five
outcome categories is reached.

## Artifacts used

The six raw sweep files below are the direct source of this report. The
three JSON files (`all_rows` — the complete 105-row sweep needed for
deterministic reproduction) are committed verbatim under
`data/research/fib_exit_ladder_v1_phase_a/`; the three CSV files are a
redundant second serialization of the same sweeps and are not committed.
Immutable identity/provenance for each file (sha256, byte size, row count,
generation window, venue, interval, symbol universe, runner, methodology
classification) is tracked in
`docs/research/fib_exit_ladder_v1_phase_a_provenance_v1.md`. The exact rows
this report is derived from — every field needed to reproduce the
per-asset/per-window disposition below without re-running the backtest — are
tracked in `docs/research/fib_exit_ladder_v1_phase_a_evidence_summary_v1.json`,
and independently re-derived straight from the committed raw JSON by
`tests/test_fib_exit_ladder_v1_phase_a_raw_evidence_reproduction_v1.py`.

```text
baseline_2020_2022.csv       baseline_2020_2022.json
validation_2022_2024.csv     validation_2022_2024.json
validation_2024_2026.csv     validation_2024_2026.json
```

Each JSON's `all_rows` is the full 7-symbol x 3-target-family x 5-sell-fraction
sweep (105 rows per window) produced by
`run_fib_exit_ladder_scoreboard_v1.py`. This report selects, per asset per
window, exactly the one row matching that asset's frozen
`ORIGINAL_ASSET_CONFIG` `(target_family, max_ladder_sell_fraction)` pair from
`src/research/fib_exit_ladder_v1_phase_a_disposition_v1.py` — never the
`best_rows` (which is the best row across family *and* fraction, not a
same-fraction family comparison, and not necessarily the published config).

## Frozen asset config used (unchanged from the contract)

```text
LINK  PRO_3X4X              0.80
XLM   PRO_3X4X              0.80
SOL   SUPERCYCLE             0.80
XRP   SUPERCYCLE             0.80
HOT   EXPLOSIVE_SUPERCYCLE   0.40
```

`BEST_BY_SYMBOL` was not used; per-asset config is exactly the published 2021
table (`docs/research/fib_exit_ladder_v1_findings.md`), reproduced by
`ORIGINAL_ASSET_CONFIG`.

## Baseline reproduction (original 2020-01-01 -> 2022-01-01 window)

All five frozen-config rows are `status=OK` and reproduce the published 2021
table within rounding tolerance:

| Symbol | Config | total_return_pct_with_remaining | Published | hold_return_pct | Published | Match |
|---|---|---:|---:|---:|---:|---|
| LINK | PRO_3X4X / 0.80 | 93.6754% | 93.6754% | 21.5124% | 21.5124% | yes |
| XLM  | PRO_3X4X / 0.80 | 128.7534% | 128.7534% | 22.8163% | 22.8163% | yes |
| SOL  | SUPERCYCLE / 0.80 | 178.3058% | 178.3058% | 165.8023% | 165.8023% | yes |
| XRP  | SUPERCYCLE / 0.80 | 207.5549% | 207.5549% | 145.9933% | 145.9933% | yes |
| HOT  | EXPLOSIVE_SUPERCYCLE / 0.40 | 563.1368% | 563.1368% | 591.5183% | 591.5183% | yes |

`baseline_reproduced=True` and `baseline_evaluable=True` for all five assets.
Acceptance-thresholds rule 1 (`BASELINE_REPRODUCTION_FAILED`) does not fire
for any asset.

## Per-asset validation window results

`alpha_vs_hold_pct = total_return_pct_with_remaining - hold_return_pct`, taken
directly from the frozen-config row, no re-derivation.
`bucket_rank_agreement` compares the three target families **at the same
asset-frozen `max_ladder_sell_fraction`** within a window (the only
same-fraction, family-only comparison available in the sweep); a tie (all
three families return an identical value) is treated as the frozen family
still being "the best-scoring" one, since no other family strictly exceeds
it — noted explicitly per asset below where it occurs.

### LINK (PRO_3X4X, 0.80)

```text
baseline_2020_2022     alpha_vs_hold_pct = +72.1631%   (status=OK)
validation_2022_2024   alpha_vs_hold_pct =   0.0000%   (status=OK)  rank: 3-way tie (36.7540% each) -> agreement holds
validation_2024_2026   alpha_vs_hold_pct = +20.6105%   (status=OK)  rank: PRO_3X4X best (-5.1362% vs -25.7467% both others) -> agreement holds
```

`validation_windows_ok=2`, `alpha_positive_ok_window_count=1` (2022-2024's
alpha is exactly `0`, which is not `>0`; 2024-2026 is positive) — a mixed
OK-window set, so acceptance rule 3 (VALIDATED) cannot fire.
`bucket_sign_agreement`: signs across baseline/val1/val2 = `+ / 0 / +` -> 2 of
3 positive -> **True**.

`classify_asset_disposition(...)` -> **REVISED**, reason=None.

### XLM (PRO_3X4X, 0.80)

```text
baseline_2020_2022     alpha_vs_hold_pct = +105.9371%  (status=OK)
validation_2022_2024   alpha_vs_hold_pct =    0.0000%  (status=OK)  rank: 3-way tie (5.5051% each) -> agreement holds
validation_2024_2026   alpha_vs_hold_pct =  +53.0794%  (status=OK)  rank: PRO_3X4X best (37.1018% vs 7.5834% / -15.9775%) -> agreement holds
```

`validation_windows_ok=2`, `alpha_positive_ok_window_count=1` (mixed, same
shape as LINK). `bucket_sign_agreement`: `+ / 0 / +` -> **True**.

`classify_asset_disposition(...)` -> **REVISED**, reason=None.

### SOL (SUPERCYCLE, 0.80)

```text
baseline_2020_2022     alpha_vs_hold_pct =  +12.5035%  (status=OK)
validation_2022_2024   alpha_vs_hold_pct = -257.7731%  (status=OK)  rank: EXPLOSIVE_SUPERCYCLE best (486.2488%) > SUPERCYCLE (355.8889%) -> agreement fails
validation_2024_2026   alpha_vs_hold_pct =  +33.6175%  (status=OK)  rank: PRO_3X4X best (58.4677%) > SUPERCYCLE (23.1974%) -> agreement fails
```

`validation_windows_ok=2`, `alpha_positive_ok_window_count=1` (mixed: 2022-2024
negative, 2024-2026 positive). `bucket_sign_agreement`: `+ / - / +` -> 2 of 3
positive -> **True**.

`classify_asset_disposition(...)` -> **REVISED**, reason=None.

### XRP (SUPERCYCLE, 0.80)

```text
baseline_2020_2022     alpha_vs_hold_pct =  +61.5616%  (status=OK)
validation_2022_2024   alpha_vs_hold_pct =  +13.8073%  (status=OK)  rank: PRO_3X4X best (109.2888%) > SUPERCYCLE (97.4247%) -> agreement fails
validation_2024_2026   alpha_vs_hold_pct =  +43.2924%  (status=OK)  rank: PRO_3X4X best (117.0330%) > SUPERCYCLE (62.0404%) -> agreement fails
```

`validation_windows_ok=2`, `alpha_positive_ok_window_count=2` — every OK
validation window is alpha-positive, so this reaches acceptance rule 3's
alpha condition, but `bucket_rank_agreement_all_ok_windows=False` (known
disagreement, not unevaluated) in both windows: `SUPERCYCLE` is not the
best-total_return family in either — `PRO_3X4X` scores higher in both.
Rule 3 (VALIDATED) therefore does not match; falls through to sign-agreement
routing. `bucket_sign_agreement`: `+ / + / +` -> **True**.

`classify_asset_disposition(...)` -> **REVISED**, reason=None.

### HOT (EXPLOSIVE_SUPERCYCLE, 0.40)

```text
baseline_2020_2022     alpha_vs_hold_pct =  -28.3816%  (status=OK)
validation_2022_2024   alpha_vs_hold_pct =    0.0000%  (status=OK)  rank: 3-way tie (25.4365% each) -> agreement holds
validation_2024_2026   alpha_vs_hold_pct =    0.0000%  (status=OK)  rank: PRO_3X4X best (-23.6656%) > EXPLOSIVE_SUPERCYCLE (-74.2492%) -> agreement fails
```

`validation_windows_ok=2`, `alpha_positive_ok_window_count=0` — neither OK
validation window has `alpha_vs_hold_pct > 0` (both are exactly `0`, HOT's
ladder degenerates to a full-hold outcome at `0.40` in both post-2022
windows). This is acceptance rule 5 ("ladder never beats hold out of the
original window"), independent of rank/sign agreement.

`classify_asset_disposition(...)` -> **REJECTED**, reason=None (this is a
methodology-negative result from a *successfully reproduced* baseline — it
must not be conflated with `BASELINE_REPRODUCTION_FAILED`, which did not
fire for HOT here).

## Overall Phase A disposition

```text
overall_disposition([LINK=REVISED, XLM=REVISED, SOL=REVISED, XRP=REVISED, HOT=REJECTED])
  = REJECTED
```

`REJECTED` is the least-favorable outcome present (`REJECTED < REVISED <
VALIDATED`), driven by HOT. This is computed over the complete, exact
five-asset frozen universe (`LINK`, `XLM`, `SOL`, `XRP`, `HOT`), matching
`disposition.REQUIRED_ASSET_UNIVERSE`.

## HBAR / SUI — descriptive only, not part of the overall disposition

`HBAR` and `SUI` have no original 2021 bucket assignment
(`has_original_bucket=False`), so per contract §5/§9 they cannot be
`VALIDATED`/`REVISED`/`REJECTED` and are excluded from `overall_disposition`
entirely (they are not passed to it; they are not treated as
`INSUFFICIENT_DATA` stand-ins for a required asset either, since they were
never part of the required five). Reported here for descriptive/bucket
-discovery-scoping context only, taken from each window's `best_rows` (best
row across family and fraction, since neither has a frozen config to select
a single row from):

```text
HBAR  baseline_2020_2022     status=INSUFFICIENT_CANDLES  (< 20 candles at that time; matches 2021 exclusion)
HBAR  validation_2022_2024   status=OK  best=PRO_3X4X/0.40  total_return=109.7585%  hold_return=109.7585%  alpha=0.0000%
HBAR  validation_2024_2026   status=OK  best=PRO_3X4X/0.80  total_return=193.9242%  hold_return=-11.3273%  alpha=+205.2515%

SUI   baseline_2020_2022     status=INSUFFICIENT_CANDLES  (< 20 candles at that time; matches 2021 exclusion)
SUI   validation_2022_2024   status=NO_ANCHOR_SET_FOUND
SUI   validation_2024_2026   status=OK  best=SUPERCYCLE/0.80  total_return=212.3769%  hold_return=-6.7090%  alpha=+219.0859%
```

No new bucket, family, or asset assignment is made for HBAR or SUI by this
report (forbidden by the contract's non-negotiable constraints). This is
observational context only.

## Methodology look-ahead classification (unchanged from the prior version of this document)

Established by code audit alone, independent of which artifacts back a given
run (see the contract's "Look-ahead / promotion-grade classification"
section for the full derivation): the frozen anchor detector
(`find_anchor_set` in `run_fib_exit_ladder_backtest_v1.py`) selects an entry
point using `future_high`, the maximum high of every candle strictly *after*
that candidate entry point, and rejects any candidate whose future data does
not exceed `wave1_high`. The entry decision is therefore not confirmable
using only data available at the entry point itself.

```text
methodology_classification    = FUTURE_AWARE_RESEARCH
methodology_promotion_grade   = 0
promotion_eligible            = false
```

This holds regardless of the `REJECTED` disposition above: even a
hypothetical `VALIDATED` result from this methodology would still be
retrospective bucket-stability evidence only, not point-in-time promotion
evidence. Retrospective bucket-stability research under this methodology
remains legitimate per `AGENTS.md` Research Rules; it simply cannot, by
itself, satisfy `#657` Phase B's point-in-time evidence requirement
(`docs/architecture/automatic_exit_profile_promotion_v1.md` § 2).

## Downstream effect

`docs/architecture/automatic_exit_profile_promotion_v1.md` §1 names #270's
validated conclusion as the primary candidate canonical evidence source for
a future `automatic_exit_profile_v1` producer. `#657` Phase B entry
criterion 1 ("#270 ... records a validated conclusion") remains unmet: this
report's conclusion is `REJECTED`, not `VALIDATED`, and even a `VALIDATED`
conclusion reached under this future-aware methodology would still fail
criterion 1's point-in-time requirement (see above). This retrospective
result cannot satisfy `#657` Phase B promotion evidence under either reading.
No promotion, preview, or runtime wiring may proceed on the basis of this
document. `#657` itself is not modified by this report.

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
reason=FUTURE_AWARE_RESEARCH
```
