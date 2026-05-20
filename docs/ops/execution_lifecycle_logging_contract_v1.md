# Execution Lifecycle Logging Contract v1

This document defines the audit/logging contract for Synth's future live execution lifecycle. It prepares the database and naming model for account-scoped execution review without enabling live trading.

Live execution remains disabled. This contract does not submit orders, does not perform broker writes, does not start executor runtime, and does not bypass `decision_gate`.

## Lifecycle Flow

```text
paper_advice / live intent preview
-> decision_gate
-> execution_planner
-> executor
-> broker/order result
```

Layer responsibilities:

- `selection_engine` remains market-only and account-agnostic.
- `paper_advice` and live intent preview are review context, not account permission.
- `decision_gate` is the account-aware permission layer.
- `execution_planner` creates execution intent, sizing, notional constraints, and plan shape only.
- `executor` handles simulated or future order actions after approved plans.
- `broker_adapter` is the broker API boundary and must remain hard-gated before live writes.

## Execution Modes

Use explicit execution modes. Do not use a plain `live=true` flag.

| Mode | Semantics |
| --- | --- |
| `PAPER` | DB logging is allowed. Simulated execution actions are allowed. Broker writes and order submission are always `0`. Broker private reads are allowed only when an existing explicit read permission grants them. |
| `LIVE_DRY_RUN` | DB logging is allowed. Planner/executor may produce live-shaped previews. Broker writes and order submission are always `0`. |
| `LIVE_ARMED` | DB logging is allowed. All preflight checks must pass. It still does not submit orders unless later final `LIVE` permission is present. |
| `LIVE` | Not enabled by this task. Later activation requires explicit live execution permission, broker write permission, decision gate approval, execution plan approval, and executor safety preflight. |

Required safety markers for lifecycle logs:

- `broker_private_calls`
- `broker_calls`
- `broker_writes`
- `order_submission`
- `live_orders`
- `decision_gate_changes`
- `execution_planner_changes`
- `executor`
- `account_awareness`

## Scope Fields

Lifecycle logs are account-aware, so they carry future-ready scope fields:

- `user_id` nullable for now
- `trading_account_id` required for account-specific logs
- `strategy_profile_id` nullable for now
- `strategy_candidate_id` nullable where relevant
- `venue`
- `asset_id`
- `symbol` display-only, nullable
- `interval_code`
- `asof_ts_utc`
- `created_ts_utc`

Do not add `user_id` to market-only tables. In particular, this contract does not alter:

- `asset`
- `obs_market_candle`
- `feat_candle`
- `signal_state`
- `market_breath`
- `execution_zone_context`
- `selection_engine` outputs

Market tables remain global. Account-aware logs may join to market tables only after the account-side query is scoped.

## Required DB Logs

The additive migration `db/migrations/20260520_execution_lifecycle_audit_log_v1.sql` defines append-only lifecycle audit tables.

### `decision_gate_audit_log`

Records account-scoped decision gate outcomes and permission states.

Required content:

- scope fields
- `execution_mode`
- `lifecycle_state`
- `permission_state`
- `decision_state`
- `decision_reason`
- `execution_intent`
- requested side/notional/quantity/limit if present
- `reason_codes_json`
- `safety_markers_json`
- upstream reference to advice or live intent preview

This table records permission decisions. It does not create execution plans and does not place orders.

### `execution_plan_audit_log`

Records planner-produced intent and plan state.

Required content:

- scope fields
- `execution_plan_id` when a persisted plan exists
- `execution_mode`
- `permission_state`
- `plan_state`
- planner name/version
- action type, side, notional, quantity, limit
- `reason_codes_json`
- `safety_markers_json`
- upstream reference to the decision gate result

This table records plan intent. It does not submit orders.

### `executor_action_audit_log`

Records executor actions before simulation or broker-bound work.

Required content:

- scope fields
- `execution_plan_id`
- `execution_mode`
- `permission_state`
- `action_type`
- requested side/notional/quantity/limit
- `submitted`
- broker adapter name and broker request preview where applicable
- `reason_codes_json`
- `safety_markers_json`
- upstream reference to the execution plan

For `PAPER`, `LIVE_DRY_RUN`, and `LIVE_ARMED`, `submitted` must remain `0`.

### `executor_result_audit_log`

Records simulated or future broker result, fill, error, reject, or cancellation outcomes.

Required content:

- scope fields
- `executor_action_audit_log_id`
- `execution_plan_id`
- `execution_mode`
- `permission_state`
- `result_state`
- requested side/notional/quantity/limit
- `submitted`
- filled quantity/notional when applicable
- broker response, error code, and error message when applicable
- `reason_codes_json`
- `safety_markers_json`
- upstream reference to executor action or broker response

This table can log paper results today and future broker results later, but the migration itself does not activate live order handling.

## Existing Tables And Gaps

Current runtime already has plan and paper-advice concepts:

- `paper_advice_observation` is market/paper advice context and remains account-agnostic in the current runtime.
- `execution_plan` is used by existing planner/executor repositories.
- `execution_plan_leg` exists as a child table for multi-leg plan details.
- `execution_event` is used by current executor-style paper flows.

The audit tables in this contract are append-only lifecycle records. They are intentionally separate from operational state tables so future review, replay, and safety audits can answer what each layer decided without mutating market data or relying on current plan state.

## Paper-Run Semantics

In `PAPER` mode:

- `decision_gate` may log account-scoped paper permission results.
- `execution_planner` may log paper plan intent.
- `executor` may log simulated actions and results.
- broker writes must remain `0`.
- order submission must remain `0`.
- no live orders are created.

Paper execution logs must still include `trading_account_id` because they are account-scoped simulations.

## Live-Run Semantics

`LIVE` is not enabled by this task.

Future live activation requires all of the following before any broker write:

- explicit live execution permission
- explicit broker write permission
- explicit order submission permission
- kill switch clear
- decision gate approval
- execution plan approval
- executor safety preflight
- broker adapter safety checks

`LIVE_ARMED` is a preflight state only. It may log readiness and failures, but it must not submit orders unless a later runtime explicitly transitions into hard-gated `LIVE`.

## Query Discipline

Account-aware lifecycle queries must filter by `trading_account_id` and, once user tables exist, by `user_id` where applicable.

Market-only queries must not filter by `user_id` and must not read account state.

Joins from lifecycle logs to market tables must keep scope on the account-side. Never infer account or user identity from `asset_id`, `symbol`, `venue`, or interval.

## Anti-Patterns

Do not:

- use a plain `live=true` flag
- let the executor decide account permissions
- let the planner read balances without scoped account context
- let `selection_engine` see account state
- write broker orders without `decision_gate` approval and execution plan approval
- query account-aware logs without `trading_account_id` or future `user_id` scope
- add `user_id` to market-only tables
- route paper advice, dashboards, or live intent preview directly to broker writes
- treat `LIVE_ARMED` as permission to submit orders

## Migration Notes

The migration is additive and creates only lifecycle audit tables. It does not alter market tables and does not modify executor runtime.

Foreign keys are intentionally deferred in v1 because the current repository has a mix of legacy runtime tables and future multi-user identifiers that are not all represented by migrations yet. Later migrations may tighten references after `user`, `user_strategy_profile`, `strategy_candidate_registry`, and the canonical account schema are finalized.

## Implementation Follow-Ups

- Add repository writers for append-only logs after runtime ownership is agreed.
- Normalize current lowercase `paper` execution mode values into the explicit mode model before writing lifecycle logs.
- Add tests that fail if account-aware lifecycle queries omit account/user scope.
- Add live preflight logging in `LIVE_DRY_RUN` before enabling `LIVE_ARMED`.
- Keep broker adapter write paths disabled until live permission gates are implemented and reviewed.
