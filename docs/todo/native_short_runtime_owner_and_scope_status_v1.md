# TODO — Native SHORT Runtime Owner And Scope Status V1

## Authoritative ownership (current truth)

The single source of truth for writer-capability host ownership is the registry:

```text
deploy/ownership/writer_capability_ownership_v1.json
```

Current canonical lifecycle for this capability:

```text
native_short_4h_chain.production_runtime_owner = UNASSIGNED
native_short_4h_chain.production_authorization_status = UNASSIGNED
native_short_4h_chain.runtime_lifecycle = UNASSIGNED
```

There is **no** current production "canonical synth-chain-4h owner". The historical
implementation wiring below is preserved as **historical / superseded** evidence
only; it does not grant production authorization. Any wording in this document
that reads as a present-tense "canonical owner" refers to the historical
implementation line, not to current operational authority. Active operational
truth is the ownership registry and the current runtime lifecycle above.

## Status

```text
implementation line: done / accepted (historical)
production runtime owner: UNASSIGNED (see registry)
installed-host activation: separate P2 operational action, not performed by this lane closure
```

The native SHORT map-level runtime implementation line is closed. Host selection,
production authorization, and activation remain open and are UNASSIGNED.

## Sources and completion evidence

Canonical sources:

```text
docs/architecture/native_short_scope_status_contract_v1.md
docs/architecture/native_short_map_level_status_contract_v1.md
docs/ops/native_short_map_materializer_canary_v1.md
docs/ops/native_short_map_ledger_health_report_v1.md
```

Merged implementation chain:

```text
PR #74 cadence profile seed
PR #71 map-level persistence
PR #76 map-level materializer
PR #77 map-level runner
PR #81 runner interruption and observability
PR #79 scope-status chain integration
PR #87 historical 4h runtime wiring (superseded as production authority; see registry)
```

Earlier scope-status persistence, materializer, and health-report work is also merged and is no longer an open prerequisite.

## Accepted implementation state (historical)

The historical repository wiring line was:

```text
synth-chain-4h runtime wrapper (historical implementation; production owner now UNASSIGNED)
-> SELECT-only expected 4h candle boundary validation
-> native SHORT scope-status chain
-> current map-level status rebuild
-> remaining market chain
```

This describes the implemented chain shape, not current production ownership.
Production ownership is UNASSIGNED in the registry.

Accepted facts (historical implementation evidence):

- cadence/grace configuration is persisted and seeded for supported scopes;
- `native_short_scope_status_v1` is the sole current scope/map authority;
- `native_short_map_level_status_v1` is the rebuildable current per-level authority for V1 SELL extension roles;
- unchanged geometry does not publish duplicate maps;
- lifecycle transitions and operational evaluation evidence remain separate;
- the historical runtime wrapper reused the existing 4h chain shape and added no second scheduler (production owner is now UNASSIGNED);
- host acceptance on the PR branch passed;
- post-merge `origin/main` acceptance passed;
- repeated BTC execution remained idempotent;
- current `origin/main` is `38ce625` or newer;
- local cleanup is complete.

Safety remained:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Closed work

The following former TODOs are complete and must not remain open:

- persistent cadence/grace contract;
- materializer run and per-scope observation evidence;
- scope-status projection;
- health-report consumption of the projection;
- map-level persistence;
- map-level materializer;
- standalone runner;
- interruption and bounded observability;
- scope-status-chain integration;
- historical 4h runtime wiring (production owner now UNASSIGNED; see registry);
- PR-branch and post-merge acceptance.

## Remaining operational action — P2 owner only

Installed-host activation was deliberately not part of PR #87 acceptance.

Any later installed-host action must be handled as a separate operational change and must:

1. verify the installed checkout and exact `origin/main` ancestry;
2. inspect the existing `synth-chain-4h` service/timer state;
3. reuse that owner rather than create another timer;
4. run a manual one-shot before enabling or restarting anything;
5. verify bounded logs, lock behavior, idempotency, and terminal summaries;
6. preserve rollback by reverting repository deployment or runtime owner wiring without mutating ledger history;
7. perform no broker, account, order, decision, planning, or execution action.

This remaining host action is tracked under:

```text
docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md
```

Do not reopen this implementation lane solely because installed systemd state is still separate.

## Downstream ownership

Profit Plan consumption of the canonical projection, map-cycle identity, and level rows belongs only in:

```text
docs/todo/profit_plan_live_ladder.md
```

Target history/lifecycle correctness belongs only in:

```text
docs/todo/profit_plan_target_lifecycle_history_truth_v1.md
```

## Boundary

- market-only
- account-agnostic
- persisted public candle inputs only
- no broker/private account calls
- no broker writes
- no reporting-side reconstruction of projection truth
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no executor changes
- no live trading enablement

## Reopen criteria

Reopen this lane only for a concrete native runtime defect such as:

- duplicate publication on unchanged geometry;
- scope identity leakage;
- non-idempotent current-level rebuild;
- broken projection precedence;
- lifecycle ledger mutation or heartbeat pollution;
- authorized owner bypass or a second scheduler being introduced once a production owner is assigned in the registry.
