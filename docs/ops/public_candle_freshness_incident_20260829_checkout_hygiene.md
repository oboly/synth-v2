# Public Candle Freshness Incident — 2026-08-29/30 (Issue #606)

## Summary

`ICP-EUR` 1h/4h `obs_market_candle` rows were reported stale (no row newer
than `2026-08-29T12:00:00Z` with `current_date=2026-08-30`). Root-cause audit
found the gap was **systemic, not ICP-specific, and not an ETL/aggregation
bug**: every Bitvavo interval (`15m`, `1h`, `4h`, `1d`, `1w`) across the
entire enabled asset universe (442 assets) stopped advancing at the exact
same moment, `2026-08-29T12:52:00Z`.

```text
ICP_1H_LAST_ROW=2026-08-29T12:00:00Z (before fix)
ICP_4H_LAST_ROW=2026-08-29T12:00:00Z (before fix)
CONTROL_MARKETS=all 442 enabled Bitvavo/EUR assets (BTC, ETH, SOL, ... checked as a group)
AFFECTED_MARKET_COUNT=442 (100% -- systemic, not ICP-isolated)
AFFECTED_INTERVALS=15m,1h,4h,1d,1w (all configured intervals, identical stall boundary)
CANONICAL_PRODUCER=src.etl.bitvavo.run_candles_etl (systemd: synth-market-candle-freshness-writer.{service,timer})
OWNER_HOST_SERVICE_TIMER=gurkdb / synth-market-candle-freshness-writer.service+.timer
SOURCE_DATA_CONTINUED=YES (Bitvavo public API unaffected; the writer never reached it)
EARLIEST_DIVERGENCE=2026-08-29T12:52:00Z (last successful writer commit before the guard began failing)
ROOT_CAUSE=canonical gurkDB writer checkout (/home/gurk/projects/synth-v2) was left on a
  feature branch and carried untracked research artifacts under data/research/, which
  correctly and repeatedly tripped the fail-closed checkout-purity guard in
  src/operations/writer_capability_authorization_v1.py (verify_checkout_identity):
  "checkout HEAD is on branch ..., expected 'main'" and
  "untracked file not permitted in checkout: data/research/...".
  This is a recurrence of the exact incident class already documented in
  docs/ops/gurkdb_canonical_runtime_checkout_guard_v1.md (2026-08-22).
FRESHNESS_MONITOR_EXISTING=NO (no scheduled process independently observed obs_market_candle
  staleness; only the writer's own per-run journal FAIL lines existed, and nothing polled
  or alerted on them between runs)
BACKFILL_REQUIRED=NO (writer resumed on its normal cadence and closed the gap without
  any manual backfill; see Recovery Evidence below)
IMPLEMENTATION_READY=YES
PRODUCTION_MUTATION_PERFORMED=0
```

## Timeline

```text
2026-08-29T12:52:00Z  Last clean writer cycle (all intervals FINISHED).
2026-08-29T~12:5X     Canonical checkout /home/gurk/projects/synth-v2 gains untracked
                       research output (data/research/cq_v1_pit_extractor_v1_smoke_*)
                       from research run(s) executed directly in that checkout.
2026-08-29T13:02:23Z  First writer FAIL: "untracked file not permitted in checkout".
                       (repeats on every ~15 min timer tick thereafter)
2026-08-30T~03:17Z    A feature-branch checkout (agent/550-...) is additionally left in
                       the canonical checkout; writer FAIL gains a second reason:
                       "checkout HEAD is on branch 'agent/550-...', expected 'main'".
2026-08-30T~03:3X-03:4X  Canonical checkout restored to clean `main` at `origin/main` HEAD;
                       stray untracked research artifacts relocated into a dedicated
                       issue worktree (/home/gurk/projects/synth-v2-606), not deleted.
2026-08-30T03:47:32Z  Writer tick starts against the now-clean checkout.
2026-08-30T03:50:43Z  Writer FINISHED cleanly for 4h/1d/1w; obs_market_candle advances
                       to the current boundary for every checked interval.
```

## Recovery Evidence

Read-only verification against `obs_market_candle` after the checkout was
restored:

```text
interval  global_latest_close_ts_utc   assets_at_latest
15m       2026-08-30T03:45:00Z         441
1h        2026-08-30T03:00:00Z         442
4h        2026-08-30T00:00:00Z         442
1d        2026-08-30T00:00:00Z         442
1w        2026-08-24T00:00:00Z         441
```

ICP-EUR specifically matches the same current boundary on every interval.
A duplicate-row check on `(asset_id, venue, interval_code, open_ts_utc)` for
ICP-EUR across the incident window returned zero duplicates -- the writer's
`ON DUPLICATE KEY UPDATE` upsert remained idempotent through the stall and
recovery, with no manual backfill performed.

## Root Cause Is Not Market-Data/ETL Code

`src/etl/bitvavo/etl_bitvavo_candles.py`, `run_candles_etl.py`, and the
checkout-purity guard in `writer_capability_authorization_v1.py` all behaved
exactly as designed: the guard is supposed to fail closed the instant the
authorized checkout is impure, and it did, on every single tick, for every
capability sharing that checkout. No ETL/aggregation/dedupe/DB-write defect
was found or is being fixed here. Per
`docs/ops/gurkdb_canonical_runtime_checkout_guard_v1.md`, the canonical
checkout is runtime infrastructure, not an agent worktree; the corrective
action is workflow discipline (use a dedicated issue worktree), not a code
change to the guard.

## What Changed As Part of Issue #606

1. **Host remediation (operational, not a repository change):** restored
   `/home/gurk/projects/synth-v2` to clean `main` at `origin/main` and moved
   the stray untracked research artifacts into a dedicated issue worktree
   (`/home/gurk/projects/synth-v2-606`) instead of deleting them.
2. **New whole-universe freshness/coverage signal** so this incident class
   is visible without a human having to notice repeated `journalctl` FAIL
   lines or diff 442 per-symbol rows by hand:
   - `classify_universe_candle_coverage` in
     `src/operations/persisted_market_candle_freshness_v1.py` classifies one
     (venue, interval) boundary across the whole eligible symbol universe as
     `CURRENT`, `PARTIAL_COVERAGE`, `STALE`, `MISSING`, or `WRITER_FAILED`.
     `WRITER_FAILED` fires only when *no* symbol is current and a dominant
     share (default 90%) of the non-current symbols share one identical
     lagging close boundary -- the exact signature this incident produced
     (100% of symbols, one shared boundary) and which a per-symbol check
     cannot distinguish from ordinary per-market drift.
   - `fetch_universe_latest_close_by_symbol` is the paired one-SELECT,
     read-only data fetch.
   - `src/operations/run_public_candle_coverage_health_check_v1.py` is a
     read-only CLI runner (`--venue`, `--interval`, repeatable) that reports
     this per configured interval and exits non-zero unless every interval
     is `CURRENT`, following the same fail-closed-by-default convention
     already used by `run_held_market_coverage_health_check_v1.py`.
3. Regression coverage in
   `tests/test_persisted_market_candle_freshness_v1.py` proves: an isolated
   single-symbol lag stays `PARTIAL_COVERAGE` (a healthy control set stays
   `CURRENT`), a universe-wide identical stall boundary is classified
   `WRITER_FAILED`, an interval with zero persisted rows anywhere is
   `MISSING` (never silently `CURRENT`), and an empty eligible-symbol input
   is `SOURCE_UNAVAILABLE`.

## Scope and Safety

Market-data-only, read-only. No account, decision, execution, or broker
code touched.

```text
market_data_scope=1
account_awareness=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_live_activation=0
database_writes=0
```

## Verification

```bash
python -m py_compile src/operations/persisted_market_candle_freshness_v1.py \
  src/operations/run_public_candle_coverage_health_check_v1.py
python -m pytest tests/test_persisted_market_candle_freshness_v1.py -q
python -m src.operations.run_public_candle_coverage_health_check_v1 --help
git diff --check
```

`tests/test_run_candles_etl_v1.py`, `tests/test_writer_capability_authorization_v1.py`,
and `tests/test_etl_bitvavo_candles_v1.py` have pre-existing, unrelated
failures in this sandbox caused by host `umask`/temp-directory permission
bits tripping their own group/world-writable-file fixture assertions; the
same failures reproduce identically on unmodified `main` outside a worktree
and are unrelated to this change.

## Not Done Here (Deliberately Out of Scope)

- No new gate was added to any downstream consumer.
- No fabricated candles and no production backfill; the writer closed the
  gap itself on its normal cadence once unblocked.
- The checkout-purity guard itself was not loosened; it worked correctly.
- No systemd unit was installed, restarted, or modified as part of this
  change; the timer that recovered was already installed and running.
