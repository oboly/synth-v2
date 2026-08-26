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

1. opens `START TRANSACTION READ ONLY`;
2. resolves exactly one canonical `asset` row for RENDER and TAO;
3. streams complete matching candle history with `fetchmany(1000)` in
   `open_ts_utc` order;
4. validates identity, timestamps, 4h candle span, OHLC and optional volume;
5. records every spacing deviation as a gap without interpolation;
6. serializes `open_ts_utc` as tracker CSV column `ts` and `volume_base` as
   tracker CSV column `volume`;
7. hashes the deterministic source CSV;
8. closes the DB read-only snapshot before tracker computation;
9. invokes `run_bullish_breathline_tracker_v1.run()` unchanged;
10. hashes generated tracker artifacts and writes `run_manifest.json`.

Each run uses a new run directory. Existing run directories are never
silently overwritten.

## Host acceptance

Run only after the implementation PR is reviewed and merged.

From the repository root on the DB-capable research host:

```text
python -m src.research.run_bullish_breathline_canonical_4h_v1 \
  --run-id empirical-RENDER-TAO-4h-<UTC_TIMESTAMP>
```

Before the broad empirical run, inspect the fixed candle query with `EXPLAIN`
on the configured MariaDB host and confirm it uses the expected indexed
asset/venue/interval/timestamp access path. Do not change query scope based on
observed Breathline outcomes.

Expected root output:

```text
data/research/bullish_breathline_canonical_4h_v1/<run-id>/
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
