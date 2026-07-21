# Executor Permission Consumption Gate V1

Status: draft prerequisite

## Boundary

Credentials authenticate a broker request. Credentials do not authorize execution.

`decision_gate` owns account-aware permission and risk decisions. It produces explicit permission evidence.

`execution_planner` owns execution intent. It creates `execution_plan` records from allowed decision-gate output.

`executor` consumes both exact records. It may validate evidence and submit or manage broker orders only after all live gates pass. It must not recalculate market selection, risk policy, position sizing policy, permission policy, or decision-gate outcome.

## Evidence Contract

Before any live broker write, executor must require exactly one active, current `execution_permission_evidence` row matching:

- `execution_plan_id`
- `trading_account_id`
- `venue`
- `asset_id`
- `market`
- decision-gate `execution_intent`
- planner/executor `action_type`
- `requested_side` when present
- `decision_state=EXECUTION_ALLOWED`
- `permission_state=EXECUTION_PERMITTED`
- `evidence_state=ACTIVE`
- non-expired `valid_until_ts_utc`
- no `revoked_ts_utc`
- no `superseded_by_evidence_id`

The execution plan must remain actionable and unexpired. The trading account must be enabled and `trading_account.live_trading_enabled=true`.

Production live execution also requires `SYNTH_LIVE_EXECUTION_PERMISSION` to contain the canonical granted value, and broker writes still require `SYNTH_BROKER_WRITE_PERMISSION=I_UNDERSTAND_THIS_PLACES_REAL_ORDERS`.

## Paper Separation

Paper execution remains independent of live broker submission. Paper plans do not require broker credentials, do not consume live permission evidence, and must not call live order placement, cancellation, or authenticated order polling methods.

## Current Violations

The legacy `src/execution/worker.py` path was capable of live `place_order` and `cancel_order` calls when its runtime mode was not paper, using only environment-level broker write permission at the broker adapter. It did not consume exact decision-gate permission evidence, did not validate `trading_account.live_trading_enabled`, and instantiated a broker client before knowing whether a live plan was authorized.

The legacy `src/execution/planner.py` can build execution plans directly from market context without consuming decision-gate output. That remains outside this focused executor gate and must not be used as canonical live planning.

The direct buy/sell ladder placement helpers cannot validate exact decision-gate and execution-plan evidence because they receive only raw broker orders and a client. Direct broker placement through those helpers is disabled; they remain build/preview helpers only.

## Non-Goals

This contract does not implement account-to-trade-credential resolution. Trade credential binding remains a later PR B2.

This contract does not change private-read credential behavior, does not execute production migrations, and does not call an exchange.
