# Synth v2.6 Execution Status

Status: active execution/planner status note  
Scope: execution planner preview, execution_plan_leg schema state  
Live trading permission: NOT_GRANTED

---

## Current state

Latest execution-planner lane status:

- execution planner contract preview exists
- single-leg preview exists
- ladder preview exists
- BUY ladder notional allocation exists
- SELL exit ladder quantity allocation exists
- execution_plan_leg design exists
- execution_plan_leg SQL schema proposal exists
- execution_plan_leg table has been manually created in the development DB through DBeaver

---

## Verified execution_plan_leg DB state

Verified after manual DBeaver execution:

- table exists as execution_plan_leg
- parent FK exists:
  - execution_plan_id -> execution_plan.execution_plan_id
- unique leg ordering exists:
  - uq_execution_plan_leg_order (execution_plan_id, leg_index)
- lookup indexes exist:
  - ix_execution_plan_leg_plan_state (execution_plan_id, leg_state)
  - ix_execution_plan_leg_state (leg_state)
  - ix_execution_plan_leg_side_state (side, leg_state)
- charset/collation:
  - utf8mb4
  - utf8mb4_unicode_ci
- no cascade delete is defined

---

## Active boundary

Schema exists.

Runtime integration has not started.

Do not touch without explicit approval:

- src/execution_planner/repository.py
- src/executor/repository.py
- src/plan_lifecycle/repository.py
- src/orchestration/*

Still not implemented:

- repository writes for execution_plan_leg
- executor support for execution_plan_leg
- lifecycle support for execution_plan_leg
- orchestration/runtime wiring
- broker/order integration
- live trading

---

## Correct flow

asset_exit_profile candidate
-> decision_gate validates actual position / sleeve / permission / duplicate safety
-> execution_planner builds passive / urgent / ladder plan
-> executor places / monitors orders only

Research/profile metadata must not create orders or bypass decision_gate.

---

## Next allowed step

Review/design only unless explicitly approved.

Possible next review topic:

- whether execution_plan_leg schema needs additional indexes or constraints before repository integration

Not allowed yet:

- executor implementation
- runtime integration
- orchestration wiring
- live/paper chain activation
