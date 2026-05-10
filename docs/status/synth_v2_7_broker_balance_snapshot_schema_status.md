# Synth v2.7 Broker Balance Snapshot Schema Status

Status: schema proposal only
Runtime impact: none
Broker write impact: none
Order impact: none
Live trading impact: none

## Decision

Do not write Bitvavo broker balances into account_balance_snapshot.

Reason:

account_balance_snapshot.account_id references exchange_account.account_id.

That table belongs to an older account schema.

The v2 account-aware execution lane uses trading_account.trading_account_id consistently in the current execution path:

- trading_account.trading_account_id
- account_position_snapshot.trading_account_id
- broker_order_snapshot.trading_account_id
- execution_sell_intent.trading_account_id
- execution_sell_plan.trading_account_id
- execution_sell_event.trading_account_id

## Proposed v2 table

Use:

trading_account_balance_snapshot

This table stores broker balance snapshots keyed by trading_account_id.

## Boundary

This table is for private broker read snapshots only.

It must not:

- place orders
- mutate positions
- enable live trading
- bypass decision_gate
- create execution plans
- create broker order snapshots

Broker private read requires:

SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA

Broker write permission remains not granted.

## Apply workflow

This SQL file is a schema proposal/reference.

Apply manually in DBeaver only after explicit approval.

Do not run this migration automatically from a chain, cron job, executor, planner, or broker path.
