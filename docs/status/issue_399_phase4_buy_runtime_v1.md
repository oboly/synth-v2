# Issue #399 Phase 4 automatic BUY runtime v1

Status: repository implementation only. No runtime activation and no LIVE authority.

Canonical path in this phase:

```text
persisted immutable automatic_buy_runtime_input_v1 snapshot
-> automatic_buy_candidate_v1
-> automatic_buy_gate_v1
-> automatic_buy_planner_v1
-> automatic_buy_evaluation_audit_v1
```

The runtime input snapshot carries an immutable `evaluation_ts_utc`. Replays of
the same `source_snapshot_key` therefore evaluate at the same logical instant;
the process wall clock is not an input to candidate/gate/planner decisions.

`decision_gate` remains the sole owner of account permission/allocation. The
runtime loads canonical #279 strategy-bucket configuration history and #318
account-protection evidence, but does not reinterpret either. The planner
remains the sole BUY ladder owner.

The audit table is append-only and unique on the deterministic idempotency key.
The key binds the input snapshot, evaluation instant, strategy/setup identity,
exact #279 config/revocation identities, #318 protection fingerprint, and
canonical venue-constraint identity. Re-evaluation of identical evidence is
idempotent; identical evidence producing a different logical decision fails
closed as an idempotency payload conflict.

Runtime ownership is registered as `AUTOMATIC_BUY_POLICY_RUNTIME` on `gurkdb`
with a canonical home-state flock path. The registry state is `PLANNED` only.
No service/timer is installed or enabled by this change.

Safety:

```text
selection_engine_account_awareness=0
decision_gate_bypass=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_migration_apply=0
production_data_seed=0
service_timer_activation=0
LIVE_authority_activation=0
```

Phase 5 DRY_RUN/PAPER acceptance, Phase 6 shared executor handoff and Phase 7
LIVE authorization remain out of scope.
