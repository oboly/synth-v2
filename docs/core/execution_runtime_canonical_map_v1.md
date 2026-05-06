# Execution Runtime Canonical Map V1

Status: active architecture note  
Scope: Synth v2.6 execution / planner / executor cleanup  
Live trading permission: NOT_GRANTED

---

## Purpose

This document defines the canonical execution-runtime map for Synth v2.6.

The repository currently contains multiple historical execution paths:

- `src/execution/`
- `src/execution_planner/`
- `src/executor/`
- `src/plan_lifecycle/`

The goal is to prevent accidental cross-layer coupling while the paper runtime and future live runtime are hardened.

---

## Active source of truth

Implementation order is governed by:

- `docs/core/current_implementation_order.md`

Current active flow:

    market data
    -> quality layer
    -> selection_engine
    -> decision_gate
    -> execution_planner
    -> executor / agents
    -> portfolio / account state
    -> reporting

Layer responsibility:

    selection_engine   = market intelligence
    decision_gate      = account permission
    execution_planner  = execution intent / plan construction
    executor / agents  = order handling
    plan_lifecycle     = reservation / lifecycle cleanup

---

## Live trading status

Live trading permission remains:

    NOT_GRANTED

Real Bitvavo execution is not active.

Live execution must be built as a separate live execution layer, not patched onto the paper runtime.

Still required before live execution:

- canonical exchange order layer
- idempotent client order IDs
- fill reconciliation
- retry / rate-limit / error handling
- kill switch
- hard paper/live mode separation
- max notional controls
- max active order controls
- explicit live permission gate

---

## Canonical module map

### decision_gate

Canonical package:

    src/decision_gate/

Responsibility:

- account-aware permission
- sleeve eligibility
- balance check
- duplicate exposure check
- active plan check
- open position check
- open order check

Forbidden:

- no market-regime logic
- no trend/setup re-interpretation
- no order handling
- no execution placement
- no target selection

Current known gap:

    DecisionGateRepository.fetch_open_order_flag()

must be connected to real `open_order_state` or equivalent order-state tracking before any runtime path is considered execution-safe.

---

### execution_planner

Canonical package:

    src/execution_planner/

Canonical current files:

    src/execution_planner/execution_planner_v1.py
    src/execution_planner/models.py
    src/execution_planner/repository.py
    src/execution_planner/run_execution_planner_v1.py

Responsibility:

- convert approved decision output into execution plan
- choose passive vs urgent-limit intent
- set plan controls:
  - max_reprices
  - max_wait_seconds
  - max_chase_bps
  - min_spread_bps_for_capture
  - escalation_to_urgent_limit
  - abort_if_signal_invalidates
- produce plan structure for executor / agents

Forbidden:

- no order placement
- no broker calls
- no strategy selection
- no account permission decisions
- no direct live trading
- no fib/pro chart direct sell orders

Current v1 shortcut:

- `ExecutionPlannerRepository.create_plan_with_reservation()` writes `execution_plan`, writes `capital_reservation`, and mutates `portfolio_sleeve`.

This is acceptable as current paper-runtime v1 behavior, but future clean architecture should separate:

    pure planner builder
    -> plan persistence
    -> reservation / lifecycle service

Current known cleanup:

    src/execution_planner/repository.py

contained duplicate `create_plan_without_reservation()` definitions and must stay clean.

---

### plan_lifecycle

Canonical package:

    src/plan_lifecycle/

Responsibility:

- lifecycle invalidation
- stale plan cleanup
- reservation release
- sleeve state correction
- execution_event lifecycle logging where relevant

Forbidden:

- no strategy logic
- no market-signal logic
- no order placement

---

### executor / agents

Intended canonical package:

    src/executor/

Responsibility:

- read execution plans
- place / simulate / monitor orders
- cancel / replace orders
- write execution events
- update order state
- handle fills
- delegate exchange-specific details downward

Forbidden:

- no strategy logic
- no account allocation logic
- no target selection
- no fib ladder intelligence
- no decision_gate bypass

Current status:

- paper executor / worker behavior exists in older paths
- live executor is not approved
- executor implementation should not be expanded until planner contract and safety gaps are cleaned

---

## Legacy / reference paths

### src/execution/

Status:

    legacy / paper-runtime reference

Contains useful historical paper worker logic, including:

- passive monitoring
- reprice events
- timeout escalation
- timeout aborts
- paper open-order state writes

Do not expand this as the future canonical live execution layer.

Use only as reference unless explicitly promoted.

### src/execution_planner/planner.py

Status:

    legacy skeleton

Do not build on this file.

Use:

    src/execution_planner/execution_planner_v1.py

as the current canonical planner builder.

### src/execution_planner/run_execution_planner_skeleton.py

Status:

    legacy skeleton

Do not use as active runtime.

### src/execution_planner/worker.py

Status:

    misplaced worker stub

Worker/executor logic does not belong inside `execution_planner`.

---

## Research boundary

Research and backtest tools may use future-aware returns or labels only in clearly separated namespaces:

    src/research/
    src/backtest/
    research_*
    bt_*
    docs/research/

Future-aware data must never leak into:

    live selection_engine path
    decision_gate
    execution_planner
    executor
    live inference

Oracle research is a microscope, not a steering wheel.

---

## Fib / pro chart exit ladders

Fib/pro exit ladders are research harvest maps.

Correct future path:

    research fib/target maps
    -> asset_exit_profile candidate
    -> decision_gate checks real position and permission
    -> execution_planner creates passive limit sell ladder
    -> executor places and monitors orders

Forbidden:

- do not turn pro charts into direct sell orders
- do not bypass decision_gate
- do not put ladder intelligence in executor
- do not use research labels as live permission

---

## Current stabilization order

Before adding advanced planner features:

1. Clean `src/execution_planner/repository.py`
   - remove duplicate `create_plan_without_reservation()`

2. Implement real `DecisionGateRepository.fetch_open_order_flag()`
   - use `open_order_state`
   - block active/open orders before allowing new execution

3. Keep operational chains paused until latest context generation is deliberately restored

4. Add planner contract preview
   - no DB writes
   - no executor call
   - no reservation mutation

5. Add execution plan leg model only after the single-plan contract is clean

6. Later:
   - entry ladder
   - exit ladder
   - per-leg repricing
   - sleeve-specific execution profiles
   - separate live executor

---

## Canonical rule

The planner is the brain.

The executor is the hands.

The decision gate is the permission officer.

Research is the microscope.

Live trading remains locked.
