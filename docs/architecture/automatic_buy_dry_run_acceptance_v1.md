# Automatic BUY DRY_RUN acceptance v1

Issue #471 defines the sole controlled acceptance path that persists an automatic BUY handoff without granting LIVE authority:

```text
canonical source input writer
-> automatic_buy_runtime_input_v1 (immutable contract v2 snapshot)
-> candidate
-> automatic_buy_gate_v1
-> automatic_buy_planner_v1
-> shared ExecutionHandoffRepositoryV1 intake (DRY_RUN only)
```

Run it only as `python -m src.entry_policy.run_automatic_buy_dry_run_acceptance_v1 --input-json <controlled-input.json>`. This source-owned CLI replaces neither the decision gate nor the shared executor handoff with SQL seeding or direct operator-shell intake.

The entrypoint fixes `executor_mode=DRY_RUN`, `runtime_owner=gurkdb`, and `executor_identity=shared-executor-v1`. Shared DRY_RUN intake persists `executor_credential_binding_id=NULL`; it does not resolve credentials, construct broker/private clients, or submit orders.

LIVE input evidence passes unchanged to `automatic_buy_gate_v1`. Thus `account_mode=live` with `live_trading_enabled=0` remains denied before planning and handoff; DRY_RUN is an executor-mode override, never a decision-gate bypass.

Structured output includes runtime input, candidate/gate/planner state, handoff/plan identity where staged, runtime identity, and these safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority=0
```
