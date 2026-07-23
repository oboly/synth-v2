# Market Candle Freshness v1

The public candle writer keeps `obs_market_candle` fresh for:

- `15m` with a 72-hour refresh window;
- `1h` with a 168-hour window;
- `4h` with a 720-hour window;
- `1d` with a 2160-hour window;
- `1w` with a 2016-hour window.

## Ownership State

```text
capability_id=public_candle_freshness
candidate_host=gurkdb
selected_host=gurkdb
acceptance_host=gurkdb
acceptance_status=PENDING
production_runtime_owner=UNASSIGNED
production_authorization_status=PREFLIGHT_PASSED
runtime_lifecycle=PREFLIGHT_PASSED
observed_runtime_state=[]
```

Strict gurkDB preflight passed at exact commit
`6031a94a2f6e9a0576dd73b0d3babe5d6e228bb6` on 2026-07-23. Acceptance
remains pending and production ownership remains `UNASSIGNED`: the required
full enabled-universe check found 429 enabled assets but only 421 current
Bitvavo EUR trading markets. No manual writer cycle ran, no candle row was
written, and no timer or production authorization was installed. See
`docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md`.

The committed service and timer below are gurkDB-bound candidate artifacts, not
host-neutral production configuration:

```text
timer=deploy/systemd/synth-market-candle-freshness-writer.timer
service=deploy/systemd/synth-market-candle-freshness-writer.service
wrapper=scripts/run_market_candle_freshness_once.sh
module=src.etl.bitvavo.run_candles_etl
lock=/tmp/synth-market-candle-freshness-writer-v1.lock
ConditionHost=gurkdb
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
authorization_file=/etc/synth/writer-capability-public-candle-freshness-authorization-v1.json
```

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

The wrapper reuses the existing ETL and canonical `obs_market_candle` upserts;
it does not duplicate ETL logic. The retained
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

See `docs/ops/writer_capability_host_ownership_contract_v1.md` and
`docs/ops/public_market_data_runtime_owners_v1.md` for selection, cutover, and
rollback order.
