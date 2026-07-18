# Market Price Snapshot v1

`market_price_snapshot` stores latest public prices for persisted-state
consumers. The writer uses only Bitvavo public `GET /ticker/price`.

Canonical runtime owner:

```text
host=devlap
timer=deploy/systemd/synth-market-price-snapshot-writer.timer
service=deploy/systemd/synth-market-price-snapshot-writer.service
wrapper=scripts/run_market_price_snapshot_once.sh
module=src.market_data.run_market_price_snapshot_v1 --write-db
lock=/tmp/synth-market-price-snapshot-writer-v1.lock
owner=devlap-public-market-data
```

Odroid render/account runners must not call this writer. They validate and
consume persisted rows through the SELECT-only
`src.operations.run_persisted_market_price_freshness_v1` boundary. Missing,
malformed, future-dated, or stale rows block dependent stages; consumers never
repair freshness.

The batch validator proves writer liveness and timestamp freshness, not full
asset coverage. A current non-empty batch can pass even when an account asset
is absent. Wallet and Profit Plan consumers therefore retain independent
per-asset `MISSING_CURRENT_PRICE` and `STALE_CURRENT_PRICE` fail-closed checks;
the top-level gate must never replace those checks.

Safety boundary:

- public endpoint only;
- no private broker read or broker write;
- no account, reporting, decision, planning, execution, or order authority;
- no SSH or remote-host command.

The writer stores one row per quote-currency ticker. `source_ts_utc` is NULL
because the endpoint has no source timestamp; `observed_ts_utc` is the UTC
observation time.

Repository smoke commands, not host activation:

```bash
bash -n scripts/run_market_price_snapshot_once.sh
python -m src.market_data.run_market_price_snapshot_v1 --help
python -m src.operations.run_persisted_market_price_freshness_v1 --help
systemd-analyze verify deploy/systemd/synth-market-price-snapshot-writer.service
systemd-analyze verify deploy/systemd/synth-market-price-snapshot-writer.timer
```

See `docs/ops/public_market_data_runtime_owners_v1.md` for deployment order and
rollback. Repository merge alone does not deploy or enable the writer.
