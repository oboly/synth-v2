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
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
observed_runtime_state=[]
```

Exact-head strict preflight and two controlled manual cycles passed at commit
`2e762b58ab9e311f4a8d403d8d97332e5ebb0f16`. The initial enabled-universe
mismatch was corrected by disabling only eight stale historical-import rows;
validation reports 421 enabled assets, 430 current Bitvavo EUR trading markets,
and zero mismatch. Each interval retained 421/421 asset coverage, cycle 1 added
93,457 unique rows, and cycle 2 was idempotent. The separately authorized
production owner is gurkDB in `AUTHORIZED_INACTIVE`; no timer or production
authorization has yet been installed. See
`docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md`.

The committed service and timer below are gurkDB-bound artifacts, not
host-neutral configuration:

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
