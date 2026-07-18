# Market Candle Freshness v1

The canonical host-neutral wrapper keeps `obs_market_candle` fresh for:

- `15m` with a 72-hour refresh window;
- `1h` with a 168-hour window;
- `4h` with a 720-hour window;
- `1d` with a 2160-hour window;
- `1w` with a 2016-hour window.

Canonical runtime owner:

```text
host=devlap
timer=deploy/systemd/synth-market-candle-freshness-writer.timer
service=deploy/systemd/synth-market-candle-freshness-writer.service
wrapper=scripts/run_market_candle_freshness_once.sh
module=src.etl.bitvavo.run_candles_etl
lock=/tmp/synth-market-candle-freshness-writer-v1.lock
owner=devlap-public-market-data
```

The wrapper reuses the existing ETL and canonical `obs_market_candle` upserts;
it does not duplicate ETL logic. Refreshes remain idempotent. Weekly semantics
remain Bitvavo-native `1W`, aligned to Monday 00:00 UTC, with no incomplete
current-week close persisted.

The former Odroid user-unit templates are removed. The retained
`scripts/odroid/run_market_candle_freshness_once.sh` path is a fail-closed
retirement stub and cannot invoke ETL. Reporting and account/render runners
must consume persisted candles and expose staleness rather than starting a
writer.

Safety boundary:

- public market data only;
- no account, private broker, reporting, decision, planning, or execution
  imports or calls;
- no broker writes or order submission;
- no cross-host orchestration.

Repository checks, not host activation:

```bash
bash -n scripts/run_market_candle_freshness_once.sh
python -m src.etl.bitvavo.run_candles_etl --help
systemd-analyze verify deploy/systemd/synth-market-candle-freshness-writer.service
systemd-analyze verify deploy/systemd/synth-market-candle-freshness-writer.timer
```

See `docs/ops/public_market_data_runtime_owners_v1.md` for exact host rollout
and rollback order. No timer is activated by this repository change.
