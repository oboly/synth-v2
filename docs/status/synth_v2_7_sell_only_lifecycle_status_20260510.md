# Synth v2.7 Sell-Only Paper Lifecycle Status — 2026-05-10

Status: preview lifecycle completed
Runtime impact: none
Market-chain impact: none
Decision impact: preview-only
Execution impact: paper-preview only
Broker impact: none
Live trading: not enabled
Position mutation: not enabled

## Summary

The first sell-only lifecycle preview has completed end-to-end through the account-aware layers without broker submission.

The tested path:

| Layer | Preview module | Result |
|---|---|---|
| decision_gate | sell_only_decision_gate_preview_v1 | approved sell-only intent |
| execution_planner | sell_only_execution_plan_preview_v1 | planned sell-only limit plan |
| executor | sell_only_paper_executor_preview_v1 | advanced paper lifecycle to FILLED |

This validates the internal lifecycle path only.

It does not mean a real broker order was submitted.
It does not mean the BTC position was mutated.
It does not enable live trading.

## Current preview account

| Field | Value |
|---|---|
| account_code | paper_sell_only_preview |
| venue | bitvavo |
| account_mode | paper |
| enabled | 1 |
| live_trading_enabled | 0 |

## Current tested position

| Field | Value |
|---|---:|
| symbol | BTC |
| source_position_snapshot_id | 1 |
| quantity_base | 0.001 |
| available_quantity_base | 0.001 |
| reference_price_eur | 68696 |

The position snapshot is a manual paper smoke snapshot.

## Current lifecycle state

| Object | ID | State | Notes |
|---|---:|---|---|
| execution_sell_intent | 5 | APPROVED | PAPER_PREVIEW_APPROVED_SELL_LIMIT |
| execution_sell_plan | 1 | FILLED | Paper executor preview lifecycle |
| broker_order_snapshot | none | none | No broker order snapshot was created |

## Executor preview path

The paper executor preview advanced the plan through:

1. PLANNED
2. READY_TO_SUBMIT
3. SUBMITTED
4. FILLED

These are internal preview states only.

The executor preview explicitly kept disabled:

- broker submission
- live order submission
- position mutation

## Safety confirmations

Expected safety state after this preview:

| Check | Expected |
|---|---:|
| broker_order_snapshot rows | 0 |
| broker_submission_enabled plans | 0 |
| live_trading_enabled plans | 0 |
| real broker calls | 0 |
| position mutation | 0 |

## Architectural boundary

Layer responsibilities remain strict.

| Layer | Responsibility |
|---|---|
| selection_engine | Market-only ranking/state. No account, position, balance, order, or broker logic. |
| trade_setup_filter | Market-only setup filter. No account, position, balance, order, or broker logic. |
| policy_preview | Research/policy visibility. No permission to trade. |
| decision_gate | Account-aware permission layer. May approve/block intent. |
| execution_planner | Converts approved intent into execution plan. No broker submission. |
| executor | Handles lifecycle/order handling. Current version is paper-preview only. |

## Not yet implemented

The following remain intentionally not implemented:

- broker adapter write path
- live sell order submission
- paper position mutation
- real fill reconciliation
- broker order status polling
- cancellation flow
- multi-symbol sell lifecycle batch
- automatic sell trigger from market chain

## Recommended next step

Before adding broker interaction, add a read-only lifecycle report and keep using UNION output for combined lifecycle visibility.

After that, the next safe extension is one of:

1. paper position mutation preview
2. read-only broker account snapshot
3. broker adapter dry-run contract

Preferred next step: read-only broker account snapshot before any broker write path.
