# Synth v2.7 Sell Intent Policy Status — 2026-05-10

Status: pure decision_gate policy module
Runtime impact: none
Decision impact: preview-only
Execution impact: none
Broker impact: none
Live trading: not enabled

## Purpose

`sell_intent_policy_v1` contains the pure account-aware sell permission logic.

It does not read from the database.
It does not call Bitvavo.
It does not write intents.
It does not call execution_planner or executor.

## Inputs

The policy receives already-loaded account state:

- account enabled flag
- account live trading flag
- broker write permission state
- hard safety state
- position quantity
- available quantity
- reserved quantity
- open sell order remaining quantity
- requested sell quantity
- mark price presence

## Output

The policy returns:

- `WOULD_APPROVE_SELL_INTENT_PREVIEW`
- or `BLOCKED`
- blocker reasons
- `actual_execution_permission=NOT_GRANTED`

## Boundary

This is still preview-only.

The module is allowed to answer:

> Would this sell intent pass the local account-aware checks?

It is not allowed to:

- write `execution_sell_intent`
- create execution plans
- submit orders
- cancel orders
- bypass live trading guards

## Freshness guard

The policy now accepts `source_freshness_ok`.

If this is false, the policy blocks with:

    SOURCE_STALE

This keeps stale broker/account snapshots from being treated as valid sell permission.
