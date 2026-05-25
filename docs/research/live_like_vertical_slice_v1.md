## Live-Like Vertical Slice V1

This document defines the first live-like vertical slice for Synth v2.12:

- first configured instance: `near_intraday_retest_reclaim_v1`
- strategy family: `INTRADAY_RETEST_RECLAIM_V1`
- mode: `shadow`

The goal is a narrow but generic path from market-only strategy context to account-aware preview layers and finally to read-only shadow logging/dashboard output.

This is not a trading path.

- no broker writes
- no order submission
- no live executor path
- no decision gate bypass
- no strategy-side account sizing

## Path

The first vertical slice preserves the intended Synth layer boundaries:

`StrategyInstanceConfig -> StrategyCandidate -> DecisionPreview -> ExecutionPlanPreview -> ShadowEvent`

### StrategyInstanceConfig

Static configuration for one enabled strategy instance.

- identifies the strategy family
- binds symbol, venue, quote, and timeframes
- defines shadow/paper/manual/live-disabled mode
- carries generic thresholds and execution profile metadata

The first example is NEAR on Bitvavo, but the contract is generic. Adding `HYPE` or `RENDER` later should require a new instance config, not symbol-specific logic changes.

### StrategyCandidate

Market-only, account-agnostic candidate output.

- built from public market state only
- contains candidate state, entry state, pressure, confidence, risk, freshness, and source context
- does not size positions
- does not know balances, open orders, or broker permissions
- does not create execution instructions

### DecisionPreview

Account-aware permission preview.

- receives a strategy candidate
- evaluates whether the account would permit further action
- may block for capital, policy, risk, or broker-permission reasons
- remains preview-only in this phase

This layer is where account awareness starts. Strategy generation stays account-agnostic.

### ExecutionPlanPreview

Execution intent preview only.

- receives an allowed or reviewable decision preview
- defines side, notional preview, limit-price preview, ladder steps preview, timeout, and cancel conditions
- keeps `executor_enabled=false`
- never submits orders in v1

### ShadowEvent

Read-only lifecycle output.

- records candidate state
- records decision state
- records execution-plan state
- records observed price and timestamp
- must keep `no_order_submitted=true`

This is the object intended for shadow logs or dashboards.

## Instance Example

The first configured instance is:

- `strategy_instance_id=near_intraday_retest_reclaim_v1`
- `strategy_family=INTRADAY_RETEST_RECLAIM_V1`
- `symbol=NEAR`
- `venue=bitvavo`
- `quote=EUR`
- `enabled=true`
- `mode=shadow`
- `capital_bucket=INTRADAY_TEST`
- `primary_tf=1h`
- `entry_tf=15m`
- `context_tf=4h`
- `execution_profile=PASSIVE_LIMIT_RETEST`

NEAR is the first configured instance only. The architecture must remain generic.

## Candidate-State Model

Candidate states for `INTRADAY_RETEST_RECLAIM_V1`:

- `NO_CANDIDATE`
- `WATCH_FOR_RECLAIM`
- `IMPULSE_ACTIVE`
- `WAIT_RETEST`
- `SHALLOW_RETEST_ACTIVE`
- `NORMAL_RETEST_ACTIVE`
- `DEEP_RETEST_ACTIVE`
- `ENTRY_CANDIDATE`
- `INVALIDATED`
- `STALE`

These states describe market/setup readiness only. They are not order instructions.

## Watcher-State Mapping

Existing manual watcher states can map into strategy candidate states as follows:

- `IMPULSE_CONTINUATION -> IMPULSE_ACTIVE` or `WAIT_RETEST`
- `WICK_REJECTION_PULLBACK -> WAIT_RETEST` or `REVIEW_PULLBACK`
- `SHALLOW_PULLBACK_STRONG -> SHALLOW_RETEST_ACTIVE`
- `NORMAL_RETEST_ZONE -> NORMAL_RETEST_ACTIVE`
- `DEEP_RETEST_ZONE -> DEEP_RETEST_ACTIVE`
- `NO_CLEAN_ENTRY -> NO_CANDIDATE`

`REVIEW_PULLBACK` is descriptive watcher language. The canonical candidate-state contract remains the list above unless a later phase promotes an additional explicit candidate state.

## Architecture Boundaries

The point of this slice is to preserve the production separation of concerns while making a real end-to-end preview possible.

- selection or strategy research may emit `StrategyCandidate`
- decision gate remains the account-aware permission layer
- execution planner remains intent-only
- executor remains the only order-handling layer
- shadow outputs remain read-only

No later phase should allow a market-only candidate to jump directly to order behavior.

## Out Of Scope For V1

- live trading
- paper order placement
- broker keys
- broker writes
- account mutations
- auto-sizing capital inside strategy generation
- direct dashboard-to-order flows

## Why This Slice Exists

Synth already sees useful market context. This slice defines the first clean bridge from:

- market-only candidate discovery
- to account-aware decision preview
- to execution intent preview
- to shadow logging/dashboard review

without granting trade permission.
