# Native SHORT writer provenance operational acceptance — 2026-07-17

## Status

PASS — host acceptance evidence captured on devlap for the merged PR #114
writer-provenance contract.

This reviewed record closes `WRITER_PROVENANCE_UNATTRIBUTED` only. It does
not authorize a new Native SHORT scope, promotion/removal, bootstrap,
failure-isolation, writer commit-time fencing, or SOL canary work.

## Boundary

Accepted scope:

    bitvavo / BTC / EUR / SHORT / 4h / 1h

BTC remained the sole SUPPORTED canonical scope. SOL, ETH, XRP, and every
other market remained review-only and unseeded. The acceptance used public
market data and Native SHORT market-data ledgers only.

No selection_engine, decision_gate, execution_planner, executor, account,
wallet, private broker, order, or Profit Plan path was read or mutated.

## Installed checkout reconciliation

    preserved_branch=fix/profit-plan-safe-render-owner-v1
    preserved_branch_sha_before=2349deafd2d682a2dfa10f6e1923d6b5a39d8076
    preserved_branch_sha_after=2349deafd2d682a2dfa10f6e1923d6b5a39d8076
    installed_branch_before=fix/profit-plan-safe-render-owner-v1
    installed_head_before=2349deafd2d682a2dfa10f6e1923d6b5a39d8076
    installed_branch_after=main
    installed_head_after=38346fc1460453469ca5bd3bc2f45159f0dc303e
    origin_main=38346fc1460453469ca5bd3bc2f45159f0dc303e
    working_tree_clean=yes
    other_worktree_conflict=no
    branch_work_preserved=yes

PR #114 was merged as
38346fc1460453469ca5bd3bc2f45159f0dc303e, and fetched origin/main remained
exactly that commit before and after acceptance. The installed checkout
remained clean.

## Host preflight

    host_name=devlap
    expected_repository_owner=synth-chain-4h
    outer_lock=/tmp/synth_chain_4h.lock
    native_short_lock=/tmp/synth-native-short-scope-status-chain-v1.lock
    active_4h_chain=0
    active_native_short_writer=0
    outer_lock_held=0
    native_short_lock_held=0

No installed system or user service, timer, or cron entry for the 4h chain was
present. Live systemd state for synth-chain-4h.service and
synth-chain-4h.timer was LoadState=not-found, ActiveState=inactive; the timer
had no last or next trigger. Therefore no scheduled cycle was imminent. No
unit or timer was installed, stopped, enabled, disabled, restarted, reloaded,
or edited.

## Migration

    file=db/migrations/20260716_native_short_writer_provenance_v1.sql
    sha256=09f3652efc4ec936d6907090c185f7c805aee3db621219f95e1dfb46b1f71963
    database=synth
    database_host=gurkdb
    mariadb_version=11.8.6-MariaDB-5ubuntu0.1 from Ubuntu
    started_utc=2026-07-17T13:54:09Z
    finished_utc=2026-07-17T13:54:09Z
    result=PASS

Only this migration was applied through the established direct MariaDB SQL
file procedure.

Post-DDL verification found all five nullable run-provenance columns, all
seven nullable writer_invocation_uuid columns, all eight expected indexes,
all seven foreign keys to native_short_materializer_run_v1.run_uuid, and both
expected run-provenance check constraints.

Every pre-migration row count, maximum primary key, and semantic SHA-256
fingerprint remained unchanged immediately after DDL. All new provenance
fields on historical rows remained NULL. All 51 historical writer runs
classified LEGACY_UNATTRIBUTED; attributable and invalid counts were zero.

## Pre-write baseline

    writer_runs=51 max_run_id=51
    maps=9 max_map_id=9
    generation_events=18 max_generation_event_id=18
    lifecycle_events=17 max_lifecycle_event_id=17
    scopes=1 max_scope_id=1
    support_events=1 max_scope_support_event_id=1
    observations=51 max_scope_observation_id=51
    scope_status_rows=1 max_scope_status_id=1
    map_level_rows=3 max_map_level_status_id=177
    cadence_config_rows=1 max_cadence_config_id=1

The sole scope row was the exact BTC key and was SUPPORTED. The current ledger
projected map 9 as MAP_ACTIVE, CURRENT_EVALUATION, SOURCE_CURRENT, and
ACTIONABLE_ACTIVE_MAP, with exactly three active SELL extension level rows.

Integrity checks returned zero duplicate scope keys, duplicate map
definitions, incomplete generation chains, published generation rows without
maps, duplicate terminal lifecycle outcomes, orphan observation/run links,
and non-BTC rows across the inspected Native SHORT ledgers.

Persisted source evidence was:

    BTC 4h max_close_ts_utc=2026-07-17T12:00:00Z
    BTC 1h max_close_ts_utc=2026-07-17T13:00:00Z
    future_candle_rows=0
    accepted_as_of_utc=2026-07-17T12:00:00Z

The accepted as-of is the latest persisted 4h close and latest common closed
boundary, so the controlled writer could not consume the later 1h close.

## No-write readiness

The exact BTC map-materializer dry-run used:

    execution_mode=MANUAL
    repository_commit=38346fc1460453469ca5bd3bc2f45159f0dc303e
    trigger_ref=native-short-writer-provenance-operational-acceptance-readiness-20260717
    symbols=BTC
    write=false

It returned STRUCTURE_HASH_UNCHANGED, published=0, lifecycle_event_ids=[], and
failed=0. All database counts and maximum keys remained unchanged after the
dry-run.

## Controlled writer invocation

Exactly one production-capable invocation was made through:

    bash scripts/run_native_short_scope_status_chain_once.sh --symbols BTC --as-of-utc 2026-07-17T12:00:00Z

scripts/run_chain_4h.sh was not invoked. No writer retry was made.

Persisted run provenance:

    run_id=52
    run_uuid=b07d897d-6574-4380-98c3-8145c5c41b30
    provenance_contract_version=native_short_writer_provenance_v1
    writer_entrypoint=scripts/run_native_short_scope_status_chain_once.sh
    repository_writer_owner=synth-chain-4h
    runner_name=run_native_short_scope_status_chain_v1
    runner_version=0.1
    contract_version=native_short_scope_status_v1
    execution_mode=CHAIN
    repository_commit_sha=38346fc1460453469ca5bd3bc2f45159f0dc303e
    host_name=devlap
    process_id=26030
    trigger_type=REPOSITORY_4H_MARKET_CHAIN
    trigger_ref=scripts/run_native_short_scope_status_chain_once.sh
    started_at_utc=2026-07-17T13:56:30.317146Z
    finished_at_utc=2026-07-17T13:56:30.407854Z
    terminal_status=FINISHED
    requested_scope_count=1
    observed_scope_count=1
    published_map_count=0
    lifecycle_event_count=0
    failed_scope_count=0

The wrapper entrypoint and trigger reference describe the actual manual shell
path. No service, timer, schedule, or parent-process identity was fabricated.

## Exact permitted writes and linkage

    native_short_materializer_run_v1: 51 -> 52; new run_id=52
    native_short_scope_observation_v1: 51 -> 52; new scope_observation_id=52
    native_short_scope_status_v1: 1 -> 1; BTC projection linked to run_id=52/run_uuid
    native_short_map_level_status_v1: 3 -> 3; IDs 175-177 rebuilt as 178-180

Observation 52 contains both run_id=52 and the accepted run UUID. The BTC
scope-status row contains latest_run_id=52, latest_observation_id=52, and the
same writer_invocation_uuid. All three rebuilt level rows contain the same
UUID and remain linked to current map 9 and its unchanged map cycle.

No orphaned non-NULL writer_invocation_uuid existed in any contract table.

## Unchanged ledgers and semantics

    native_short_map_v1: 9 -> 9; max_map_id=9
    native_short_map_generation_event_v1: 18 -> 18; max_generation_event_id=18
    native_short_map_lifecycle_event_v1: 17 -> 17; max_lifecycle_event_id=17
    native_short_map_scope_v1: 1 -> 1; max_scope_id=1
    native_short_scope_support_event_v1: 1 -> 1; max_scope_support_event_id=1
    native_short_scope_cadence_config_v1: 1 -> 1; max_cadence_config_id=1

There was no new scope, support-state change, map, generation event, lifecycle
event, duplicate map, incomplete generation chain, lifecycle transition, or
SOL/ETH/XRP/non-BTC write. All append-only historical-prefix semantic
fingerprints matched their pre-migration values, and all 51 historical runs
remained legacy-unattributed. Persisted classification after acceptance was:

    writer_run_count=52
    legacy_unattributed_writer_run_count=51
    attributable_writer_run_count=1
    invalid_provenance_writer_run_count=0

## Transitional audit

The SELECT-only multi-asset audit at the accepted as-of returned:

    provenance_contract_implemented=true
    attributable_production_run_observed=true
    operational_acceptance_completed=false
    writer_provenance_blocker_active=true
    WRITER_PROVENANCE_UNATTRIBUTED=active

Those values were the deliberately fail-closed audit output before independent
review. Acceptance of this permanent record closes the provenance blocker in
the canonical TODO state; the historical audit output above is not rewritten.

The proposed SOL -> ETH -> XRP queue remains review order only. No queue member
was seeded, supported, or approved.

## Safety markers

    broker_private_calls=0
    broker_writes=0
    order_submission=0
    live_orders=0
    account_reads=0
    decision_gate=none
    execution_planner=none
    executor=none
    deployment_outside_devlap=0
    service_changes=0
    timer_changes=0
    full_4h_chain_invocations=0
    controlled_btc_writer_invocations=1
    writer_retries=0
    new_scope_seeds=0

## Review state

Host acceptance evidence is captured and reviewed.
`WRITER_PROVENANCE_UNATTRIBUTED` is closed by this record.

Scope-administration transactions, writer commit-time fencing,
`NO_CURRENT_MAP` bootstrap semantics, per-symbol failure isolation, and the
SOL canary remain separate blocked work. This evidence must not clear those
blockers or authorize any non-BTC scope.
