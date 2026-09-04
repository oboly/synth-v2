# Fib Exit Ladder V1 — PIT Replay Phase C provenance (Issue #707 Phase C)

Immutable provenance for the real, DB-sourced Phase C replay run committed
under `docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1/raw/`. This
document is the verifiable fingerprint for the four raw evidence files plus
the manifest that records them, so any disposition or promotion-grade claim
in `docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1_findings.md` can
be confirmed without re-running the replay.

## Run identity

```text
runner                = run_fib_exit_ladder_v1_pit_replay_v1
                        (src/research/run_fib_exit_ladder_v1_pit_replay_v1.py,
                        unmodified since merge)
engine                = fib_exit_ladder_v1_pit_replay_engine_v1
                        (src/research/fib_exit_ladder_v1_pit_replay_engine_v1.py,
                        frozen Phase B engine, unmodified)
contract               = fib_exit_ladder_v1_pit_replay_contract_v1
                        (docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md,
                        frozen Phase A contract, unmodified)
methodology_version    = fib_exit_ladder_v1_pit_replay_contract_v1@v1
code_commit_sha         = 232e0d430a15fe180361a1ec157c2931b2cc1d84
generated_at_utc        = 2026-09-04T07:57:15.423804+00:00
mode                    = read_only_research
venue                   = bitvavo
interval_code           = 1d
symbol_universe         = LINK, XLM, SOL, XRP, HOT  (5 symbols, frozen contract § 3)
candidate_families      = PRO_3X4X, SUPERCYCLE, EXPLOSIVE_SUPERCYCLE
sell_fraction_grid      = 0.40, 0.50, 0.60, 0.70, 0.80
candidate_grid          = 5 symbols x 3 families x 5 fractions = 75 SELECTION_WINDOW rows
```

## DB source and window bounds

```text
source table  = obs_market_candle (read-only session: SET SESSION
                TRANSACTION READ ONLY, START TRANSACTION READ ONLY,
                explicit rollback() on close)
query columns = open_ts_utc, open_price, high_price, low_price, close_price
query filter  = asset_id = <resolved per symbol>, venue = 'bitvavo',
                interval_code = '1d',
                open_ts_utc >= <window from_ts>, open_ts_utc < <window to_ts>
query order   = open_ts_utc ASC (deterministic)
```

Window bounds (frozen contract § 4, unchanged):

```text
SELECTION_WINDOW  2020-01-01 00:00:00 -> 2022-01-01 00:00:00
OOS_WINDOW_1       2022-01-01 00:00:00 -> 2024-01-01 00:00:00
OOS_WINDOW_2       2024-01-01 00:00:00 -> 2026-09-01 00:00:00
```

## Candle row counts (from `raw/input_window_metadata_v1.json`)

| Symbol | SELECTION_WINDOW | OOS_WINDOW_1 | OOS_WINDOW_2 |
|---|---|---|---|
| LINK | 365 | 730 | 974 |
| XLM  | 365 | 730 | 974 |
| SOL  | 151 | 730 | 974 |
| XRP  | 365 | 730 | 974 |
| HOT  | 365 | 730 | 974 |

Every window/asset returned a non-empty candle series (the runner fails
closed on any zero-row window fetch — see
`run_fib_exit_ladder_v1_pit_replay_v1.fetch_window_candles`). SOL's shorter
`SELECTION_WINDOW` row count (151 vs 365 for the other four assets) reflects
SOL's actual `obs_market_candle` history start for `bitvavo`/`1d`, not a
truncated or filtered query — it is a data availability fact of the source
table, not a runner artifact.

## Raw evidence files and sha256

| File | sha256 | byte size |
|---|---|---|
| `input_window_metadata_v1.json` | `0dd3cd0017929ac0caa984bbd62f9bd6fc69edaddaf9374728870733d3a9395e` | 1024 |
| `manifest_v1.json` | `5a6db4bf6071f701856a3e30473a73e3ce5f37dc7ac48eb8ac49dad7b5332b93` | 1486 |
| `oos_evaluation_results_v1.json` | `8ffd6d459d12cf31c97ed27055ede9843ec6f99ff396b28f4280337e5a377b75` | 16462 |
| `selected_policies_v1.json` | `a4d4246ce81608795486b6dfa8b35b5bfbcfe802306c21698b2e6b0e4bbf17f9` | 1223 |
| `selection_grid_results_v1.json` | `6e82fe0d1b0fedbe2f59edec4601c1cee3e302d3f3e09e62d8098da717d90add` | 282151 |

sha256/byte-size values above were independently recomputed against the
committed bytes at
`docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1/raw/` and match
`manifest_v1.json`'s `files` map exactly (also asserted by
`tests/test_fib_exit_ladder_v1_pit_replay_verifier_v1.py::test_real_committed_manifest_hashes_match_actual_files`).

Row counts:

```text
selection_grid_results_v1.json   rows_total=75   (5 symbols x 3 families x 5 fractions)
selected_policies_v1.json        rows_total=5    (one per required asset, all status=OK)
oos_evaluation_results_v1.json   rows_total=10    (5 symbols x 2 OOS windows, all status=OK)
```

## Verifier command and result

```bash
python -m src.research.fib_exit_ladder_v1_pit_replay_verifier_v1 \
  --evidence-dir docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1
```

Result (independently reproduced from raw evidence only, no DB access):

```json
{
  "overall_disposition": "REJECTED",
  "per_asset_disposition": {
    "HOT": "REJECTED", "LINK": "REJECTED", "SOL": "REJECTED",
    "XLM": "REJECTED", "XRP": "REJECTED"
  },
  "criteria": {
    "true_pit_eligibility": true,
    "no_look_ahead": true,
    "disjoint_selection_oos": true,
    "deterministic_replay": true,
    "sufficient_sample_count": true,
    "positive_oos_alpha": false,
    "stable_reproducible": true,
    "immutable_raw_evidence": true,
    "verifier_reproduces": true
  },
  "methodology_promotion_grade": 0,
  "promotion_eligible": false,
  "mismatches": []
}
```

`mismatches: []` confirms the verifier's independent re-derivation of the
SELECTION_WINDOW ranking, the no-retuning check across both OOS windows, and
the manifest hash/size check all agree with the committed evidence exactly.

## Reproduction

```bash
python -m pytest tests/test_fib_exit_ladder_v1_pit_replay_verifier_v1.py -q
python -m pytest tests/test_run_fib_exit_ladder_v1_pit_replay_v1.py -q
```

`tests/test_fib_exit_ladder_v1_pit_replay_verifier_v1.py` includes a
dedicated group of tests run directly against this committed evidence
directory (not synthetic fixtures): manifest hash/size verification,
independent selection-grid re-ranking, OOS policy identity vs. the frozen
selected policy, absence of any alternate OOS ranking, and the exact
reported per-asset/overall disposition and promotion-grade result.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
db_writes=0
```

The replay run used a read-only DB transaction only (`SET SESSION
TRANSACTION READ ONLY`, `START TRANSACTION READ ONLY`, explicit
`rollback()`); no `INSERT`/`UPDATE`/`DELETE`/DDL statement was issued
(`run_fib_exit_ladder_backtest_v1.fetch_all` raises on any non-`SELECT`
statement via `assert_read_only_sql`).
