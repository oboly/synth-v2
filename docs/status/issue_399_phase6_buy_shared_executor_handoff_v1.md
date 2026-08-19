# Issue #399 Phase 6 BUY shared executor handoff v1

Status: repository integration only. No LIVE authorization or broker activity.

Canonical Phase 6 boundary:

```text
Phase 5 AutomaticBuyHandoffPreviewV1
-> exact in-memory AutomaticBuyPlanV1
-> automatic_buy_execution_handoff_adapter_v1
-> shared ApprovedExecutionPlanV1
-> shared ExecutionHandoffRepositoryV1.intake
```

The BUY lane now converges with SELL at the existing #206 side-neutral executor substrate. No BUY-specific executor, credential resolver, submission state machine, reconciliation path, client-order identity, or Bitvavo adapter is introduced.

The adapter derives a deterministic `plan_reference_id` from the full logical BUY-plan identity, including account, venue/market/side, candidate action/evidence, strategy/setup identity, gate approval provenance, planner version and exact leg mechanics. The wall-clock planning timestamp is excluded so retries of the same logical intent remain stable.

Phase 6 accepts only the Phase 5 `PAPER_DRY_RUN` preview and only `paper` account mode. Normal intake maps to executor `PAPER`; the sole explicit override is `DRY_RUN`. `LIVE` cannot be expressed through this Phase 6 API and remains Phase 7.

The existing shared handoff repository owns persistence and `(plan_source, plan_reference_id)` idempotency. Duplicate automatic-BUY replay therefore converges on the same canonical shared handoff identity rather than creating a separate BUY execution path.

Safety:

```text
buy_specific_executor=0
buy_specific_broker_adapter=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
LIVE_authority_activation=0
credential_provisioning=0
kill_switch_mutation=0
production_migration_apply=0
production_data_seed=0
service_timer_activation=0
```
