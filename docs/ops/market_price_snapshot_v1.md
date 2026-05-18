# Market Price Snapshot v1

`market_price_snapshot` centralizes latest public market prices for dashboards and
read-only reports. The v1 writer uses only Bitvavo public `GET /ticker/price`.

Safety boundary:

- no Bitvavo private broker read
- no broker writes
- no order submission
- no account awareness
- executor is not invoked

Migration:

```bash
mysql "$DB_NAME" < db/migrations/20260518_market_price_snapshot_v1.sql
```

Writer:

```bash
python -m src.market_data.run_market_price_snapshot_v1 \
  --venue bitvavo \
  --quote EUR \
  --write-db \
  --output table
```

The writer stores one row per public ticker price observed in the requested quote
currency. `source_ts_utc` is `NULL` because Bitvavo `/ticker/price` does not
include a source timestamp; `observed_ts_utc` is the local UTC observation time
for the public response.

Dashboard use:

- `src.reporting.run_position_rotation_static_dashboard_v1` reads latest rows
  through `fetch_latest_prices_by_symbol`.
- Renderers do not call Bitvavo directly.
- The Odroid dashboard render script writes a fresh public snapshot before
  rendering `rotation-preview.html`.

Smoke:

```bash
python -m src.market_data.run_market_price_snapshot_v1 --venue bitvavo --quote EUR --write-db --output table
python -m src.reporting.run_position_rotation_static_dashboard_v1 --venue bitvavo --quote EUR --interval 4h --trading-account-id 2 --output summary
grep -n "HYPE" /var/www/html/synth/rotation-preview.html
```

Expected safety markers include:

```text
broker_writes=0 order_submission=0 executor=none
```
