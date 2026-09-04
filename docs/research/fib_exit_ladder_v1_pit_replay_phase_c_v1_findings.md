# Fib Exit Ladder V1 — PIT Replay Phase C findings (Issue #707 Phase C)

Provenance: `docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1/provenance_v1.md`.
Raw evidence: `docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1/raw/`.
Verifier: `src/research/fib_exit_ladder_v1_pit_replay_verifier_v1.py`.

Per contract § 12 rule 5: if the verifier's derived result ever disagrees
with this document, the verifier's derived result is authoritative. This
document was written after and matches the verifier's actual output against
the committed raw evidence (see provenance doc).

This is the real, DB-sourced Phase C run. The frozen Phase A contract
(`docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md`) and merged
Phase B engine (`src/research/fib_exit_ladder_v1_pit_replay_engine_v1.py`)
were **not** changed in response to these results.

## A. Factual PIT replay results

Universe: LINK, XLM, SOL, XRP, HOT (5 assets, `bitvavo`, `1d`).
Windows: `SELECTION_WINDOW` 2020-01-01→2022-01-01,
`OOS_WINDOW_1` 2022-01-01→2024-01-01, `OOS_WINDOW_2` 2024-01-01→2026-09-01.

| Symbol | PIT-selected family | PIT-selected fraction | SELECTION_WINDOW metric (total_return_pct_with_remaining) | OOS_WINDOW_1 status / total_return_pct_with_remaining / alpha_vs_hold_pct | OOS_WINDOW_2 status / total_return_pct_with_remaining / alpha_vs_hold_pct | sample counts |
|---|---|---|---|---|---|---|
| LINK | PRO_3X4X | 0.80 | 33.58 | OK / 11.88 / 0.00 | OK / -21.53 / 17.05 | selection=1, oos1=1, oos2=1 |
| XLM  | PRO_3X4X | 0.80 | 82.98 | OK / -20.03 / 0.00 | OK / -71.25 / 0.00 | selection=1, oos1=1, oos2=1 |
| SOL  | SUPERCYCLE | 0.80 | 126.31 | OK / 221.61 / -72.11 | OK / -49.46 / 0.00 | selection=1, oos1=1, oos2=1 |
| XRP  | PRO_3X4X | 0.80 | 114.69 | OK / -21.40 / 0.00 | OK / 43.31 / 59.12 | selection=1, oos1=1, oos2=1 |
| HOT  | EXPLOSIVE_SUPERCYCLE | 0.40 | 472.86 | OK / 5.86 / 0.00 | OK / -91.99 / 0.00 | selection=1, oos1=1, oos2=1 |

All 5 assets returned `status=OK` for the SELECTION_WINDOW policy and both
OOS windows (75/75 selection-grid rows and 10/10 OOS rows present, none
`INSUFFICIENT_CANDLES` or `NO_ANCHOR_SET_FOUND`). `alpha_vs_hold_pct=0.00`
appears for several OOS rows: this is an exact zero (`Decimal("0E-26")`),
not a rounding artifact of this table, and per contract § 9 an exact-zero
alpha does not count as `alpha_vs_hold_pct > 0`.

## B. Original-vs-PIT policy comparison

Original `#270` future-aware policies (from
`docs/research/fib_exit_ladder_v1_findings.md`) vs. this PIT-only replay's
independently `SELECTION_WINDOW`-selected policy:

| Symbol | #270 policy | PIT-selected policy | Same? |
|---|---|---|---|
| LINK | PRO_3X4X 0.80 | PRO_3X4X 0.80 | Same |
| XLM  | PRO_3X4X 0.80 | PRO_3X4X 0.80 | Same |
| SOL  | SUPERCYCLE 0.80 | SUPERCYCLE 0.80 | Same |
| XRP  | SUPERCYCLE 0.80 | **PRO_3X4X 0.80** | **Different** |
| HOT  | EXPLOSIVE_SUPERCYCLE 0.40 | EXPLOSIVE_SUPERCYCLE 0.40 | Same |

For XRP, the PIT-only (no future-candle) selection process picked a
different family (`PRO_3X4X` instead of `SUPERCYCLE`) at the same
0.80 fraction than the original `#270` future-aware sweep. This shows the
PIT-eligibility constraint (candidates visible only using data available at
each historical decision point) changes at least one asset's selected
policy versus a future-aware selection — the two methodologies are not
interchangeable, which is the reason `#707` exists as a separate,
non-future-aware protocol.

## C. Per-asset dispositions

Per contract § 9 (majority sign agreement across OOS windows with a
PIT-confirmed anchor):

| Symbol | OOS_WINDOW_1 alpha | OOS_WINDOW_2 alpha | Positive / total | Disposition |
|---|---|---|---|---|
| LINK | 0.00 (not positive) | +17.05 | 1/2 (tie) | **REJECTED** |
| XLM  | 0.00 (not positive) | 0.00 (not positive) | 0/2 | **REJECTED** |
| SOL  | -72.11 | 0.00 (not positive) | 0/2 | **REJECTED** |
| XRP  | 0.00 (not positive) | +59.12 | 1/2 (tie) | **REJECTED** |
| HOT  | 0.00 (not positive) | 0.00 (not positive) | 0/2 | **REJECTED** |

LINK and XRP each have exactly one positive-alpha OOS window and one
non-positive OOS window: a 1/2 tie, which per contract § 9 fails majority
sign agreement and classifies `REJECTED` (not `REVISED`) — `REVISED`
requires the positive side to be a strict majority, not a tie.

## D. Overall disposition

```text
overall_disposition = REJECTED
```

All 5 required-universe assets independently classify `REJECTED`; per
contract § 9/§ 12, overall disposition is the least-favorable outcome across
the required universe, so overall is `REJECTED`.

## E. Promotion-grade assessment

All nine contract § 10 criteria, evaluated independently and fail-closed
(any single `False` forces `methodology_promotion_grade=0`):

| # | Criterion | Result | Basis |
|---|---|---|---|
| 1 | `true_pit_eligibility` | **True** | Property of the frozen, unmodified Phase B engine and Phase A contract helper; proven by existing unchanged Phase A/B regression tests, not re-derivable from this run's JSON evidence alone. |
| 2 | `no_look_ahead` | **True** | Same basis as (1). |
| 3 | `disjoint_selection_oos` | **True** | `SELECTION_WINDOW` (→2022-01-01) ends at or before `OOS_WINDOW_1` starts (2022-01-01), which ends at or before `OOS_WINDOW_2` starts (2024-01-01); every OOS row's `(target_family, max_ladder_sell_fraction)` matches that symbol's frozen `SELECTION_WINDOW`-selected policy (no retuning). |
| 4 | `deterministic_replay` | **True** | Verifier's independent re-ranking of all 75 `selection_grid_results_v1.json` rows reproduces the exact reported `selected_policies_v1.json` policy for all 5 assets, with zero mismatches. |
| 5 | `sufficient_sample_count` | **True** | Every asset has `selection_sample_count>=1` on `SELECTION_WINDOW` and at least one `status=OK` OOS row. |
| 6 | `positive_oos_alpha` | **False** | 0 of 5 assets classify `VALIDATED` (all 5 classify `REJECTED` — see § C). |
| 7 | `stable_reproducible` | **True** | Same as (4), checked empirically against the committed data (verifier `mismatches: []`). |
| 8 | `immutable_raw_evidence` | **True** | All 4 raw evidence files' sha256/byte-size match `manifest_v1.json` exactly (see provenance doc). |
| 9 | `verifier_reproduces` | **True** | Deterministic verifier reproduces the exact reported per-asset and overall result directly from committed raw evidence; zero mismatches. |

```text
methodology_promotion_grade = 0
promotion_eligible           = false
```

Criterion 6 alone is sufficient to fail this run closed regardless of how
favorable any individual asset's numbers might look in isolation (e.g. LINK
OOS_WINDOW_2 alpha=+17.05, XRP OOS_WINDOW_2 alpha=+59.12) — the contract
requires **every** asset in the required universe to be `VALIDATED`, and
none are.

## F. Implication for #657

This completed Phase C run is **not** promotion-grade evidence
(`methodology_promotion_grade=0`, `promotion_eligible=false`,
`overall_disposition=REJECTED`). Per contract § 14, `#657` may consume only
a separately validated promotion-grade result that passes every § 10
criterion; this run does not, so it grants no promotion eligibility to the
`fib_exit_ladder_v1` methodology or to any specific asset's exit-ladder
policy.

This finding is **not** binding on `#657` and does not modify, gate, or
otherwise touch `automatic_exit_profile_v1`, `decision_gate`,
`execution_planner`, or `executor` code. It states only that the evidence
generated here — under the frozen, non-future-aware PIT protocol — would
not qualify for later `#657` consumption as-is. Whether `#270`'s original
(future-aware, already `REJECTED`,
`docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md`)
disposition should also be reconsidered, whether a revised PIT protocol
should be attempted, or whether `#657` should be closed/reframed given both
`#270` and `#707` now independently rejecting this exit-ladder methodology
on this asset universe are decisions out of scope for this document.

## Reproduction

```bash
python -m src.research.fib_exit_ladder_v1_pit_replay_verifier_v1 \
  --evidence-dir docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1
python -m pytest tests/test_fib_exit_ladder_v1_pit_replay_verifier_v1.py tests/test_run_fib_exit_ladder_v1_pit_replay_v1.py -q
```
