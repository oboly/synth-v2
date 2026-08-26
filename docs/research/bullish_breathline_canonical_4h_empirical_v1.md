# Bullish Breathline canonical 4h empirical acceptance v1

Status: research-only acceptance lane for GitHub Issue #534.

## Purpose

Produce the first real historical RENDER/TAO evidence for the already-merged
bullish Breathline tracker v1 without changing tracker behavior or frozen grids.

## Frozen scope

- source table: `synth.obs_market_candle`
- venue: `bitvavo`
- symbols: `RENDER`, `TAO`
- input interval: `4h`
- tracker candle timestamp: canonical `open_ts_utc`
- tracker volume: canonical `volume_base` when present
- expected consecutive open spacing: 14,400 seconds

The 4h input interval is not a Breathline lifecycle duration. Observed lifecycle
duration remains data-derived by the #417 tracker.

## Runner

```text
src/research/run_bullish_breathline_canonical_4h_v1.py
```

The runner:

1. prints an immediate flushed `STARTED` line with mode, frozen scope and `workers=1`;
2. sets the next transaction to `REPEATABLE READ`, then starts
   `START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY` before any source query;
3. resolves exactly one canonical `asset` row for RENDER and TAO;
4. streams complete matching candle history with a PyMySQL server-side
   `SSDictCursor` and `fetchmany(1000)` in `open_ts_utc` order;
5. reports query row counts, elapsed times, phases and progress heartbeats;
6. validates identity, timestamps, 4h candle span, OHLC and optional volume;
7. records every spacing deviation as a gap without interpolation;
8. serializes `open_ts_utc` as tracker CSV column `ts` and `volume_base` as
   tracker CSV column `volume`;
9. hashes the deterministic source CSVs and, after both exports finish under the
   same consistent DB snapshot, writes `source_checkpoint.json`;
10. closes the DB read-only snapshot before tracker computation;
11. invokes `run_bullish_breathline_tracker_v1.run()` unchanged, with periodic
    heartbeat output around tracker phases;
12. hashes generated tracker artifacts and writes `run_manifest.json`;
13. finishes with exactly one flushed `FINISHED`, `INTERRUPTED`, or `FAILED`
    terminal summary.

Each run uses a new run directory. Existing completed run directories are never
silently overwritten. The generated run root is ignored by Git so canonical
candle evidence cannot be accidentally committed as source code.

`SIGINT` and `SIGTERM` are converted into a clean interruption request. Candle
streaming stops between bounded batches. If interruption happens after the
complete source checkpoint exists, those exact gehashte source CSVs are retained
for provenance-strict resume. Tracker phases may finish their current #417 call
before the interruption is finalized so the existing tracker is not modified to
add interruption hooks.

## Host acceptance

Run only after the implementation PR is reviewed and merged.

From the repository root on the DB-capable research host:

```text
python -m src.research.run_bullish_breathline_canonical_4h_v1 \
  --run-id empirical-RENDER-TAO-4h-<UTC_TIMESTAMP>
```

If that exact run is interrupted after `source_checkpoint.json` was written,
resume only with the same checked-out code provenance:

```text
python -m src.research.run_bullish_breathline_canonical_4h_v1 \
  --run-id empirical-RENDER-TAO-4h-<UTC_TIMESTAMP> \
  --resume
```

Resume verifies runner version, frozen scope, analysis commit, tracker source
commit, tracker source hashes and both source CSV hashes before reusing data. A
completed run containing `run_manifest.json` cannot be resumed or overwritten.
If interruption occurred before the source checkpoint completed, `--resume`
restarts the incomplete source phase instead of mixing partial DB snapshots.

The DB host acceptance on 2026-08-26 confirmed that gurkdb accepts
`START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY`. The runner additionally
sets the transaction-specific isolation level to `REPEATABLE READ` immediately
before that statement so both asset exports are bound to one stable read view.

Before the broad empirical run, inspect the fixed candle query with `EXPLAIN`
on the configured MariaDB host and confirm it uses the expected indexed
asset/venue/interval/timestamp access path. Do not change query scope based on
observed Breathline outcomes.

Expected root output:

```text
data/research/bullish_breathline_canonical_4h_v1/<run-id>/
  source_checkpoint.json
  run_manifest.json
  RENDER/
    source/canonical_candles.csv
    tracker/latest_cycles.json
    tracker/summary.json
    tracker/cycle_ledger.jsonl   # present when cycle_count > 0
  TAO/
    source/canonical_candles.csv
    tracker/latest_cycles.json
    tracker/summary.json
    tracker/cycle_ledger.jsonl   # present when cycle_count > 0
```

The existing #417 `append_cycle_ledger()` does not create a ledger file when
`cycle_count == 0`. The wrapper records that absence explicitly in the manifest
rather than fabricating an empty tracker artifact. A zero-cycle result remains a
valid negative/insufficient empirical result.

## Review output after host run

For each asset review:

- source candle count and first/last source timestamp;
- exact gap count and gap records;
- source SHA256;
- cycle count and cycle-status counts;
- observed lifecycle duration distribution where sample size permits;
- phase offset and phase drift distributions;
- recognition, ignition, main-pulse and extension confirmations;
- reset, phase-shift and failure counts;
- selected discovery ratios and holdout evidence where sample size permits;
- walk-forward sample count;
- explicit sufficiency or insufficiency for downstream #533.

Do not tune #417 from these RENDER/TAO outcomes. Do not add 1d sensitivity,
BTC-alt relationship analysis, account state, selection, permission, execution,
broker or live-trading behavior to this lane.