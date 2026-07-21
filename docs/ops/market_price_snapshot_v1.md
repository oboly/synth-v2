# Market Price Snapshot v1

`market_price_snapshot` stores latest public prices for persisted-state
consumers. The writer uses only Bitvavo public `GET /ticker/price`.

## Ownership State

```text
capability_id=public_price_snapshot
candidate_host=gurkdb
selected_host=gurkdb
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
observed_runtime_state=gurkdb timer installed/disabled/inactive
```

gurkDB strict preflight, two controlled acceptance writes, lock behavior, and
rollback readiness passed at the exact release commit. The timer remains
disabled/inactive and the production authorization file remains absent pending
independent review and merge.

The committed service and timer below are canonical gurkDB-bound artifacts:

```text
timer=deploy/systemd/synth-market-price-snapshot-writer.timer
service=deploy/systemd/synth-market-price-snapshot-writer.service
wrapper=scripts/run_market_price_snapshot_once.sh
module=src.market_data.run_market_price_snapshot_v1 --write-db
lock=/tmp/synth-market-price-snapshot-writer-v1.lock
ConditionHost=gurkdb
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
```

Acceptance evidence is recorded in
`docs/ops/public_price_snapshot_gurkdb_host_acceptance_20260721.md`. The unit
still fails closed without the exact production authorization file.

Odroid render/account runners must not call this writer. They validate and
consume persisted rows through the SELECT-only
`src.operations.run_persisted_market_price_freshness_v1` boundary. Missing,
malformed, future-dated, or stale rows block dependent stages; consumers never
repair freshness.

Safety boundary:

- public endpoint only;
- no private broker read or broker write;
- no account, reporting, decision, planning, execution, or order authority;
- no SSH or remote-host command.

Repository smoke commands, not host activation:

```bash
bash -n scripts/run_market_price_snapshot_once.sh
python -m src.market_data.run_market_price_snapshot_v1 --help
python -m src.operations.run_persisted_market_price_freshness_v1 --help
systemd-analyze verify deploy/systemd/synth-market-price-snapshot-writer.service
systemd-analyze verify deploy/systemd/synth-market-price-snapshot-writer.timer
```

See `docs/ops/writer_capability_host_ownership_contract_v1.md` and
`docs/ops/public_market_data_runtime_owners_v1.md` for selection, cutover, and
rollback order.
