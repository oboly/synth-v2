# Issue #399 Phase 5 BUY DRY_RUN/PAPER acceptance v1

Status: repository acceptance seam only. No runtime activation, executor submission, broker write, order submission, credentials, kill-switch mutation, or LIVE authority.

Canonical verified path:

```text
persisted Phase 4 runtime input
-> automatic_buy_candidate_v1
-> automatic_buy_gate_v1
-> automatic_buy_planner_v1
-> automatic_buy_evaluation_audit_v1
-> Phase 5 PAPER_DRY_RUN handoff preview
```

The Phase 5 wrapper calls the existing Phase 4 orchestrator. It does not reproduce candidate, decision_gate, planner, sizing, rounding, protection, or bucket logic.

A handoff preview exists only when the canonical runtime returns `planner_state=STAGED` with an in-memory `AutomaticBuyPlanV1`. The preview carries that exact typed object. Persisted `immutable_plan_json` is used only to verify that the audit row matches the typed plan; it is never deserialized or reconstructed into execution intent.

Non-staged outcomes produce no preview. A non-paper account fails closed before acceptance. Duplicate replay reuses the Phase 4 idempotency key and audit semantics and cannot create a second execution intent inside Phase 5.

Phase 5 ends before the executor boundary. Phase 6 remains the separately reviewed shared #206 handoff integration. Phase 7 remains separately authorized LIVE activation.

Safety markers:

```text
executor_calls=0
credential_calls=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority=0
production_migration_apply=0
production_data_seed=0
service_timer_activation=0
```
