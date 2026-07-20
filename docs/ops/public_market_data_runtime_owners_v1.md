# Public Market-Data Runtime Owners v1

## Status

Repository implementation only. No host deployment, timer activation, writer
invocation, database mutation, operational acceptance, or systemctl mutation is
claimed here.

The authoritative machine-readable ownership source is
`deploy/ownership/writer_capability_ownership_v1.json`.

## Current Canonical Ownership

```text
public_price_snapshot.production_runtime_owner=UNASSIGNED
public_candle_freshness.production_runtime_owner=UNASSIGNED
market_rotation_pressure.production_runtime_owner=UNASSIGNED
native_short_4h_chain.production_runtime_owner=UNASSIGNED
```

`UNASSIGNED` means no canonical production authorization. It does not prove
that no host has an installed or running timer.

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

## Capability State

```text
public_price_snapshot:
  candidate_host=gurkdb
  selected_host=UNASSIGNED
  acceptance_host=UNASSIGNED
  acceptance_status=UNASSIGNED
  runtime_lifecycle=UNASSIGNED
  observed_runtime_state=[]

public_candle_freshness:
  candidate_host=gurkdb
  selected_host=UNASSIGNED
  acceptance_host=UNASSIGNED
  acceptance_status=UNASSIGNED
  runtime_lifecycle=UNASSIGNED
  observed_runtime_state=[]

market_rotation_pressure:
  candidate_host=gurkdb
  selected_host=UNASSIGNED
  acceptance_host=devlap
  acceptance_status=ACCEPTED
  runtime_lifecycle=UNASSIGNED
  historical_runtime_assignment.host=devlap
  historical_runtime_assignment.status=SUPERSEDED
  observed_runtime_state=devlap timer last observed installed/enabled/active,
                         current_state=UNVERIFIED,
                         authorization_status=SUPERSEDED

native_short_4h_chain:
  candidate_host=UNASSIGNED
  selected_host=UNASSIGNED
  acceptance_host=UNASSIGNED
  acceptance_status=UNASSIGNED
  runtime_lifecycle=UNASSIGNED
  observed_runtime_state=[]
```

## Executable Artifacts

The committed services under `deploy/systemd/` are devlap-bound candidate or
historical artifacts. They are not host-neutral:

```text
ConditionHost=devlap
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
ExecStartPre=src.operations.verify_writer_capability_authorization_v1
```

The mandatory `ExecStartPre` guard fails closed while a capability is
`UNASSIGNED`, while the authorization file is absent, on the wrong hostname, on
the wrong checkout commit, or for a lifecycle outside `AUTHORIZED_INACTIVE` and
`ACTIVE`.

Do not copy these units to another host with different users or paths. Do not
create a gurkDB unit until gurkDB has been selected, accepted, contained, and
authorized for a specific capability.

Host-local locks still prevent manual/systemd overlap on one host:

```text
public_price_snapshot: /tmp/synth-market-price-snapshot-writer-v1.lock
public_candle_freshness: /tmp/synth-market-candle-freshness-writer-v1.lock
market_rotation_pressure: /tmp/synth-market-rotation-pressure-v1.lock
native_short_4h_chain: /tmp/synth_chain_4h.lock
```

Those locks cannot prevent cross-host overlap. Authorization and cutover guards
are mandatory for that.

## Domain Boundary

Public market-data writer capabilities are separate from:

- account snapshot persistence;
- website registration;
- dashboard and reporting publication;
- decision_gate;
- execution_planner;
- executor and broker clients.

Reporting, dashboards, and account runtimes consume persisted state. They must
not start public market-data writers or run repair paths.

## Native SHORT Inventory

`native_short_4h_chain` is independently evaluated from the light DB writers.
It invokes:

```text
src.market_data.native_short_repository_source_identity_v1
src.operations.run_persisted_market_price_freshness_v1
src.operations.run_persisted_market_candle_freshness_v1
scripts/run_native_short_scope_status_chain_once.sh
src.market_data.run_native_short_scope_status_chain_v1
src.market_data.run_native_short_fib_context_snapshot_v1 --publish
src.features.run_feat_candle
src.signal_engine.run_signal_state_etl
src.advice.run_advice_engine
src.ranking.run_ranking_engine
src.measurement.run_asset_interval_quality_snapshot --write-db
src.selection.run_selection_engine_v2 --write-db
src.zone.run_zone_engine_v1 --write-db
src.trade_setup_filter.run_trade_setup_filter_v1 --write-db
src.research.run_trade_setup_filter_policy_preview_v1 --write-db
src.advice.run_paper_advice_policy_v1 --write-db
src.strategy_runtime.run_strategy_runtime_snapshot
```

It writes or publishes native scope/map state, feature/signal/advice/ranking
state, quality snapshots, selection state, zone context, trade setup filter
observations, policy preview rows, paper advice observations, strategy runtime
snapshots, and native SHORT fib context artifacts/manifests.

## Cutover Order

Use the state machine in
`docs/ops/writer_capability_host_ownership_contract_v1.md`:

1. identify candidate host
2. record candidate/selected state without production authorization
3. complete read-only preflight
4. prepare host without activating timer
5. complete controlled acceptance after separate authorization
6. inventory every installed runtime instance for the capability
7. disable the old timer
8. prove old timer inactive and disabled
9. record new production authorization
10. activate new timer
11. observe natural scheduled cycles
12. verify persisted-state freshness and consumers
13. mark lifecycle `ACTIVE`
14. prove at most one authorized active owner

If an installed legacy timer is discovered while canonical authorization is
`UNASSIGNED`, classify it as
`OBSERVED_LEGACY_RUNTIME_PENDING_CONTAINMENT`. Do not silently treat it as
inactive.

## Repository Checks

These commands are repository-only checks, not host activation:

```bash
python -m src.operations.validate_writer_capability_ownership_v1
bash -n scripts/run_market_price_snapshot_once.sh
bash -n scripts/run_market_candle_freshness_once.sh
bash -n scripts/run_market_rotation_pressure_once.sh
bash -n scripts/run_chain_4h.sh
systemd-analyze verify deploy/systemd/*.service deploy/systemd/*.timer
```

Do not run `systemctl enable`, `systemctl start`, a writer wrapper, or any
`--write-db` command as part of repository correction.
