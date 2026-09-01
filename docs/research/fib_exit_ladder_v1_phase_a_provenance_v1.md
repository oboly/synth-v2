# Fib Exit Ladder V1 — Phase A artifact provenance (Issue #270 Phase A)

Immutable provenance for the six frozen artifact files that
`docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md` is
computed from. These files are **not** committed to this repository (they
are large, machine-generated backtest sweeps); this document is the
verifiable pointer to them plus the fields needed to confirm any future
disposition claim was actually computed from real output of the frozen,
unmodified runners, without re-running the backtests.

Runner/module identity (unchanged, read-only, account-agnostic — same for
all six files):

```text
runner  = run_fib_exit_ladder_scoreboard_v1
          (src/research/run_fib_exit_ladder_scoreboard_v1.py, unmodified)
mode    = read_only_research
rank_metric = total_return
methodology_classification  = FUTURE_AWARE_RESEARCH
                               (src/research/fib_exit_ladder_v1_phase_a_disposition_v1.py
                               METHODOLOGY_CLASSIFICATION, unmodified)
venue        = bitvavo
interval     = 1d
symbol_universe = LINK, SOL, XRP, HBAR, HOT, SUI, XLM  (7 symbols)
target_families = PRO_3X4X, SUPERCYCLE, EXPLOSIVE_SUPERCYCLE
max_sell_fractions = 0.40, 0.50, 0.60, 0.70, 0.80
rows_total_per_window = 105  (7 symbols x 3 families x 5 fractions)
```

## Per-artifact provenance

| Field | `baseline_2020_2022.csv` | `baseline_2020_2022.json` |
|---|---|---|
| sha256 | `77445a33b151c42891479acc024019b414ad0ec09c76742ca25bcefaea5f736b` | `b730943a361d680f734eb3e177b12f985790c9afa722476e366c5a0dcae0309e` |
| byte size | 34561 | 170612 |
| row/result count | 105 data rows (106 lines incl. header) | `rows_total`=105, `all_rows`=105, `best_rows`=7 |
| generation window (from_ts -> to_ts) | 2020-01-01 -> 2022-01-01 | 2020-01-01 -> 2022-01-01 |

| Field | `validation_2022_2024.csv` | `validation_2022_2024.json` |
|---|---|---|
| sha256 | `b372a1c04953353c7df081dbcdad832f4fb795f50e770df795ebbe92764d533c` | `3e278f2413635225505e42b9e617910e4b899220cde1268f8ea76648a31aa445` |
| byte size | 34982 | 167755 |
| row/result count | 105 data rows (106 lines incl. header) | `rows_total`=105, `all_rows`=105, `best_rows`=7 |
| generation window (from_ts -> to_ts) | 2022-01-01 -> 2024-01-01 | 2022-01-01 -> 2024-01-01 |

| Field | `validation_2024_2026.csv` | `validation_2024_2026.json` |
|---|---|---|
| sha256 | `a57b4fe5ce72fde10d38bbf91b54e6544ed287f5b5a924d5468dc9bfc9ed96fc` | `6e1db7ce1f41f962a3eaf0ccb0393bb13bb7d966a828a05bd4c3e0b0e37ae453` |
| byte size | 36919 | 177110 |
| row/result count | 105 data rows (106 lines incl. header) | `rows_total`=105, `all_rows`=105, `best_rows`=7 |
| generation window (from_ts -> to_ts) | 2024-01-01 -> 2026-09-01 | 2024-01-01 -> 2026-09-01 |

All six files share: `venue=bitvavo`, `interval=1d`,
`symbol_universe=LINK, SOL, XRP, HBAR, HOT, SUI, XLM`,
`runner=run_fib_exit_ladder_scoreboard_v1`,
`methodology_classification=FUTURE_AWARE_RESEARCH`.

sha256 values above are for the exact bytes as produced by
`run_fib_exit_ladder_scoreboard_v1.py`; the `.csv`/`.json` pair for a given
window is the same sweep serialized in both formats (105 rows each), not two
independent runs.

## Location of the source artifacts

The six files live outside this repository's tracked tree, under a
research working copy at
`data/research/fib_exit_ladder_v1_phase_a/{baseline_2020_2022,validation_2022_2024,validation_2024_2026}.{csv,json}`,
produced by an unmodified invocation of
`python -m src.research.run_fib_exit_ladder_scoreboard_v1` against
`obs_market_candle` for the window/venue/interval/symbol universe listed
above. Per this repository's DB and data rules, this is a research-namespace
artifact, not an operational runtime table; it is not committed here to
avoid checking in a large machine-generated sweep, and the derived,
row-scoped evidence needed to reproduce the disposition is instead captured
in `docs/research/fib_exit_ladder_v1_phase_a_evidence_summary_v1.json`
(next to this file) together with the sha256/size/row-count fingerprints
above, so the disposition in
`docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md` can be
checked against a fixed, hash-verifiable source without re-running the
backtest.
