# Public Market-Data Runtime Owners v1

## Status

`public_price_snapshot` completed exact-commit gurkDB preflight, controlled
acceptance, and inactive host preparation on 2026-07-21.
`public_candle_freshness` passed strict gurkDB preflight on 2026-07-23 but
stopped before acceptance writes because the enabled database universe did not
match the current Bitvavo EUR market universe. The other capabilities are
unchanged.

The authoritative machine-readable ownership source is
`deploy/ownership/writer_capability_ownership_v1.json`.

## Current Canonical Ownership

```text
public_price_snapshot.production_runtime_owner=gurkdb
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
  selected_host=gurkdb
  acceptance_host=gurkdb
  acceptance_status=ACCEPTED
  production_runtime_owner=gurkdb
  production_authorization_status=AUTHORIZED
  runtime_lifecycle=AUTHORIZED_INACTIVE
  observed_runtime_state=gurkdb timer installed/disabled/inactive,
                         production authorization file absent

public_candle_freshness:
  candidate_host=gurkdb
  selected_host=gurkdb
  acceptance_host=gurkdb
  acceptance_status=PENDING
  production_runtime_owner=UNASSIGNED
  production_authorization_status=PREFLIGHT_PASSED
  runtime_lifecycle=PREFLIGHT_PASSED
  observed_runtime_state=[]

market_rotation_pressure:
  candidate_host=gurkdb
  selected_host=gurkdb
  acceptance_host=devlap
  acceptance_status=ACCEPTED
  runtime_lifecycle=SELECTED_PENDING_PREFLIGHT
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

## gurkDB Public-Price Authorization and Remaining Selections

`public_price_snapshot` is accepted and separately authorized to gurkDB in
`AUTHORIZED_INACTIVE`. `public_candle_freshness` has passed strict preflight
but remains blocked before controlled acceptance; `market_rotation_pressure`
remains selected for preflight only.

For the two remaining selected lanes, selection still means only strict host
preflight; it is not production authorization. Specifically:

```text
public_price_snapshot production_runtime_owner=gurkdb
public_price_snapshot production_authorization_status=AUTHORIZED
public_price_snapshot runtime_lifecycle=AUTHORIZED_INACTIVE
public_price_snapshot production authorization file absent
public_price_snapshot timer disabled/inactive
public_candle_freshness production_runtime_owner=UNASSIGNED
public_candle_freshness runtime_lifecycle=PREFLIGHT_PASSED
market_rotation_pressure production_runtime_owner=UNASSIGNED
```

The public-price unit and the fail-closed candle candidate unit are bound to
gurkDB. Remaining devlap-bound committed units are candidate/historical
artifacts. The devlap
Rotation Pressure historical assignment remains
`SUPERSEDED`, while canonical
`observed_runtime_state.current_state=UNVERIFIED`; this PR does not assert or
record current host containment. Odroid remains a consumer/publisher host with
zero writer capabilities. The public-price acceptance and rollback evidence is
in `docs/ops/public_price_snapshot_gurkdb_host_acceptance_20260721.md`.

`native_short_4h_chain` is not selected and remains independently unresolved
(`selected_host=UNASSIGNED`, `runtime_lifecycle=UNASSIGNED`).

## Stage-Aware Preflight Evidence

Strict gurkDB preflight distinguishes evidence stages. Only `PREFLIGHT_LOCAL`
and `PREFLIGHT_EXTERNAL` checks gate `--strict`; `ACCEPTANCE` and `CUTOVER`
checks stay visible but deferred and non-blocking, and are never silently marked
`PASS`.

```text
PREFLIGHT_LOCAL     measured locally by the read-only runner; always authoritative
PREFLIGHT_EXTERNAL  DB/exchange/network/host-policy probes; UNVERIFIED unless proven
ACCEPTANCE          runtime_per_writer, resource_usage_per_writer (deferred)
CUTOVER             rollback_capability (deferred)
```

Separately authorized external probes may be recorded in a matching
external-evidence manifest and merged with `--external-evidence-file`. The
manifest binds `schema_version`, `capability`, `hostname`, `checkout_commit`,
and `observed_at_utc`, may fill only permitted `PREFLIGHT_EXTERNAL` checks, and
never overrides a local check. Capability-specific external requirements are
proven from code. All three writers reach MariaDB through `src.common.db`, so
`mariadb_connectivity` and `runtime_configuration` are required for each. The
public price/candle writers additionally require public-exchange connectivity
but no private exchange credentials (`private_exchange_credentials` not
required); `market_rotation_pressure` requires MariaDB but no exchange API (it
reads persisted candles and uses only optional public CoinGecko context).
`runtime_configuration` verifies only safe DB/runtime configuration metadata
(env names resolvable, config file present/owned/permissioned, required values
non-empty) and never reads secret values.

External evidence is time-bounded: `--max-external-evidence-age-seconds`
(default 900) rejects stale or future evidence, and every required check must
belong to one bounded evidence run. The manifest also carries strict safety
markers proving no mutation occurred while producing the evidence
(`host_mutations=0`, `database_writes=0`, `writer_invocations=0`,
`systemctl_mutations=0`, `order_submission=0`, `broker_writes=0`,
`authorization_created=false`, `deployment_performed=false`); read-only probe
counters may be nonzero.

A strict preflight `PASS` proves host readiness only. It is non-authorizing: it
does not grant production ownership and does not change any lifecycle here. No
external-evidence file may contain secrets or credentials, and acceptance or
cutover evidence must not be presented as preflight evidence. Evidence files are
local operational artifacts and are not committed by default. See
`docs/ops/writer_capability_host_ownership_contract_v1.md` and
`deploy/ownership/host_preflight_external_evidence_v1.schema.json`.

## Executable Artifacts

The public-price service and fail-closed candle candidate service are explicitly
gurkDB-bound:

```text
ConditionHost=gurkdb
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
ExecStartPre=src.operations.verify_writer_capability_authorization_v1
```

The remaining committed services are devlap-bound candidate or historical
artifacts; none are authorized by the public-price decision.

The mandatory `ExecStartPre` guard fails closed while a capability is
`UNASSIGNED`, while the authorization file is absent, on the wrong hostname, on
the wrong checkout commit, or for a lifecycle outside `AUTHORIZED_INACTIVE` and
`ACTIVE`.

Do not copy these units to another host with different users or paths. The
gurkDB public-price timer must not be enabled before this ownership change is
independently reviewed and merged and the exact-merge production authorization
file is installed.

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
