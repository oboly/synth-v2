# Fib Exit Ladder V1 — Phase A artifact provenance (Issue #270 Phase A)

Immutable provenance for the six frozen artifact files that
`docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md` is
computed from. The three JSON files (`all_rows` — the complete 105-row
sweep each window needs for deterministic reproduction) are committed
verbatim under `data/research/fib_exit_ladder_v1_phase_a/`; the three CSV
files are the same sweeps serialized in a second format and are not
committed (redundant with the JSON for reproduction purposes). This
document is the verifiable fingerprint for all six, plus the fields needed
to confirm any disposition claim was actually computed from real output of
the frozen, unmodified runners, without re-running the backtests.

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

The three JSON files are committed verbatim (identical bytes, verified
sha256 match against the row above) at:

```text
data/research/fib_exit_ladder_v1_phase_a/baseline_2020_2022.json
data/research/fib_exit_ladder_v1_phase_a/validation_2022_2024.json
data/research/fib_exit_ladder_v1_phase_a/validation_2024_2026.json
```

produced by an unmodified invocation of
`python -m src.research.run_fib_exit_ladder_scoreboard_v1` against
`obs_market_candle` for the window/venue/interval/symbol universe listed
above. Per this repository's DB and data rules, this is a research-namespace
artifact, not an operational runtime table — it is frozen, immutable
evidence, not a scratch or backfilled operational table. The three CSV
files (same 105 rows per window, second serialization format, redundant
with the committed JSON for reproduction) are not committed; their sha256
fingerprints above remain the provenance record for them.

`docs/research/fib_exit_ladder_v1_phase_a_evidence_summary_v1.json` and
`tests/test_fib_exit_ladder_v1_phase_a_evidence_summary_v1.py` are derived,
self-consistency evidence over the summary alone.
`tests/test_fib_exit_ladder_v1_phase_a_raw_evidence_reproduction_v1.py`
additionally re-derives the frozen-config rows directly from these
committed raw JSON files (never `best_rows`) and cross-checks both the
sha256 hashes above and the tracked evidence summary against them, so the
disposition in
`docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md` is
independently reproducible from a hash-verifiable, tracked source without
re-running the backtest.
