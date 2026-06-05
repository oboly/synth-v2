## Market Candle Freshness V1

`market_candle_freshness_v1` is a dedicated Odroid-oriented public market ETL
runner for keeping `obs_market_candle` fresh across:

- `15m`
- `1h`
- `4h`
- `1d`
- `1w`

This lane is ops-only and market-only.

Safety boundary:

- `broker_private_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `db_writes=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
- `account_awareness=0`

It does not:

- change `selection_engine`
- change `decision_gate`
- change `execution_planner`
- change `executor`
- touch account refresh
- create orders

## Why This Exists

The MVP cockpit path is not candle freshness.

Current MVP/read-only timers refresh:

- `market_price_snapshot_v1`
- selected `4h` structural recompute
- selected `15m` lifecycle/recompute support

That is not enough to guarantee broad `obs_market_candle` freshness for:

- research runners
- replay studies
- reporting/dashboard consumers
- multi-timeframe signal inventory work

The broken legacy `synth-runner.service` is not the solution.
It points to legacy `~/synthesizer/run_synth.sh` and currently fails with
`Exec format error`.

That legacy service should be disabled or masked manually on the runtime host.
This repository lane does not change or repair it automatically.

## One-Shot Runner

Script:

```text
scripts/odroid/run_market_candle_freshness_once.sh
```

One-shot command:

```bash
cd /home/theone/projects/synth-v2
bash scripts/odroid/run_market_candle_freshness_once.sh
```

Optional asset filter:

```bash
bash scripts/odroid/run_market_candle_freshness_once.sh --asset BTC --asset ETH
```

The runner:

- changes into the repo
- activates `.venv` or `venv`
- takes a lock to prevent overlap
- runs `src.etl.bitvavo.run_candles_etl` separately for `15m`, `1h`, `4h`, and `1d`
- runs `src.etl.bitvavo.run_candles_etl` separately for `15m`, `1h`, `4h`, `1d`, and `1w`
- uses only supported ETL arguments:
  - `--config`
  - `--asset`
  - `--interval`
  - `--start`
  - `--end` when needed later
  - `--dry-run` when used manually later
- prints latest `obs_market_candle` timestamps per interval after refresh

Current lookback windows are conservative:

- `15m` -> `72h`
- `1h` -> `168h`
- `4h` -> `720h`
- `1d` -> `2160h`
- `1w` -> `2016h`

These are freshness windows, not backfill-history policy.

Weekly semantics are native Bitvavo closed-week candles.

- interval code in Synth remains canonical `1w`
- upstream API request uses Bitvavo-native `1W`
- week alignment is UTC Monday `00:00:00`
- incomplete current week is not written as a closed candle
- writes remain idempotent through canonical `obs_market_candle` upserts

## Systemd User Timer Templates

Templates live under:

```text
scripts/odroid/systemd/synth-market-candle-freshness.service
scripts/odroid/systemd/synth-market-candle-freshness.timer
```

Manual install example:

```bash
mkdir -p ~/.config/systemd/user
cp /home/theone/projects/synth-v2/scripts/odroid/systemd/synth-market-candle-freshness.service ~/.config/systemd/user/
cp /home/theone/projects/synth-v2/scripts/odroid/systemd/synth-market-candle-freshness.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now synth-market-candle-freshness.timer
```

Status commands:

```bash
systemctl --user status synth-market-candle-freshness.service
systemctl --user status synth-market-candle-freshness.timer
journalctl --user -u synth-market-candle-freshness.service -n 100 --no-pager
journalctl --user -u synth-market-candle-freshness.timer -n 50 --no-pager
```

Disable commands:

```bash
systemctl --user disable --now synth-market-candle-freshness.timer
systemctl --user stop synth-market-candle-freshness.service
```

## Relationship To Research And Reporting

This runner feeds `obs_market_candle` freshness for downstream consumers such
as:

- `signal_matrix_single_asset_replay_v1`
- other research replay runners
- static dashboards that inspect multi-timeframe market context

It does not turn freshness into advice.

It does not recompute decision logic.

It does not resolve stale-coverage interpretation by itself.

Signal replay and research consumers must still keep their own coverage and
staleness diagnostics.

## Legacy Runtime Note

If the host still has a legacy user service such as:

```text
synth-runner.service
```

pointing at:

```text
~/synthesizer/run_synth.sh
```

that service is outside Synth v2 canonical runtime and should be reviewed,
disabled, or masked manually.

This doc intentionally separates:

- legacy broken runner cleanup
- public candle freshness
- MVP cockpit rendering
- market-only replay/reporting consumers
