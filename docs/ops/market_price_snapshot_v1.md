# Market Price Snapshot v1

`market_price_snapshot` stores latest public prices for persisted-state
consumers. The writer uses only Bitvavo public `GET /ticker/price`.

## Ownership State

```text
capability_id=public_price_snapshot
candidate_host=gurkdb
selected_host=UNASSIGNED
acceptance_host=UNASSIGNED
acceptance_status=UNASSIGNED
production_runtime_owner=UNASSIGNED
production_authorization_status=UNASSIGNED
runtime_lifecycle=UNASSIGNED
observed_runtime_state=[]
```

The committed service and timer below are devlap-bound candidate artifacts, not
host-neutral production configuration:

```text
timer=deploy/systemd/synth-market-price-snapshot-writer.timer
service=deploy/systemd/synth-market-price-snapshot-writer.service
wrapper=scripts/run_market_price_snapshot_once.sh
module=src.market_data.run_market_price_snapshot_v1 --write-db
lock=/tmp/synth-market-price-snapshot-writer-v1.lock
ConditionHost=devlap
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
```

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

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
