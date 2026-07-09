# Credential scope and manual ladder execution boundary v1

Status: TODO
Owner: future execution-boundary lane
Created: 2026-07-09

## Purpose

Define the credential and execution boundary required before Synth stores or uses any trade-capable Bitvavo API key.

This is a follow-up design task. It must not be implemented inside the linked-profile runtime orchestrator lane.

## Current state

The linked-profile runtime orchestrator is read/account-refresh only:

- public price snapshot refresh may write public market-data snapshots
- account refresh may use read-only private calls for balance and open-order snapshots
- dashboard render reads persisted snapshots
- no broker writes
- no order submission
- no executor
- no native SHORT build in the safe render stage

The current credential repository supports one active credential per `trading_account_id + venue`, but it does not yet encode credential purpose/scope. That is acceptable for read-only onboarding, but not sufficient for storing trade-capable credentials.

## Required model

Mirror Bitvavo API policy with explicit Synth scopes.

### READ_ONLY_PRIVATE

Used for account visibility only.

Allowed:

- balance reads
- open-order reads
- account snapshot refresh
- dashboard rendering from persisted snapshots
- linked-profile runtime orchestrator account stage

Forbidden:

- order create
- order cancel
- order update
- executor access
- fallback to trade credential

Example account identity:

```text
account_code=bitvavo_joost_read
credential_scope=READ_ONLY_PRIVATE
```

### TRADE_EXECUTION

Used only by the executor.

Allowed:

- broker order creation only after decision_gate approval
- broker order cancellation only after decision_gate approval
- broker order update only after decision_gate approval

Forbidden:

- dashboard loading
- account refresh loading
- linked-profile orchestrator loading
- selection_engine loading
- execution_planner loading
- fallback to read credential
- withdrawal permission

Example account identity:

```text
account_code=bitvavo_joost_trade
credential_scope=TRADE_EXECUTION
```

## Onboarding flow

### Initial signup

The user supplies a read-only Bitvavo key first.

Expected outcome:

- account dashboards become available
- account snapshots refresh
- linked-profile runtime can run
- no trade-capable credential exists or is required

### Trade activation

The user supplies a separate trade-capable Bitvavo key later through explicit config/provisioning.

Expected outcome:

- the trade key is stored separately from the read key
- executor becomes eligible to use the trade key only if decision_gate approves
- live trading remains disabled by default
- no dashboard/account-refresh service can decrypt or load the trade key

## Manual ladder boundary

Manual ladder setup is intent/config only.

It may define:

- profile/account
- market
- side
- ladder levels
- size model
- expiry
- invalidation
- user approval state

It must not:

- load credentials
- call Bitvavo private APIs
- create orders
- cancel orders
- submit broker writes
- bypass decision_gate

## Layer ownership

### selection_engine

Market-only and account-agnostic.

Must not:

- load credentials
- read account state
- submit orders
- know about manual ladder ownership

### decision_gate

Account-aware permission layer.

Owns checks for:

- live_trading_enabled
- account-specific trade permission
- valid TRADE_EXECUTION credential availability
- manual ladder approval state
- stale market/account context
- risk limits
- duplicate active execution cycle prevention

Must not:

- place orders
- load plaintext credentials

### execution_planner

Execution-intent only.

Owns:

- converting approved manual ladder setup into deterministic execution intent
- preserving idempotency keys / execution cycle references

Must not:

- load credentials
- call broker
- decide permission

### executor

Only layer allowed to load `TRADE_EXECUTION` credentials and submit/cancel broker orders.

Owns:

- broker writes
- order submission
- order cancellation
- write audit logs
- idempotency handling
- broker response persistence

Must not:

- make market selection decisions
- bypass decision_gate
- infer permission from the presence of a key

## Storage boundary

Short-term acceptable model:

```text
trading_account.account_code=bitvavo_joost_read
trading_account.account_code=bitvavo_joost_trade
```

Each account identity has its own encrypted credential row.

Preferred schema addition:

```text
trading_account_credential.credential_scope:
  READ_ONLY_PRIVATE
  TRADE_EXECUTION

trading_account_credential.allowed_private_read: boolean
trading_account_credential.allowed_order_write: boolean
trading_account_credential.allowed_withdrawal: boolean always false / unsupported
```

Runtime must fail closed on:

- missing scope
- scope mismatch
- multiple active credentials for same scope
- fallback from read to trade
- fallback from trade to read
- withdrawal-capable credential detection if detectable

## Environment boundary

Read/account/dashboard services:

```text
/home/theone/.config/synth/web-auth.env
```

Executor service:

```text
/home/theone/.config/synth/executor-auth.env
```

The executor env should be the only runtime environment capable of decrypting or resolving `TRADE_EXECUTION` credentials.

## Required implementation tasks

1. Add credential scope model to schema/docs/tests.
2. Add read-key provisioning flow for `READ_ONLY_PRIVATE`.
3. Add trade-key provisioning flow for `TRADE_EXECUTION`.
4. Ensure trade-key provisioning is interactive and never takes secrets as CLI args.
5. Update account refresh to require `READ_ONLY_PRIVATE` scope.
6. Update linked-profile orchestrator to require read-only scope for account refresh stage.
7. Add executor-only credential resolver requiring `TRADE_EXECUTION` scope.
8. Add hard tests for scope mismatch refusal.
9. Add hard tests proving dashboard/orchestrator cannot load trade credentials.
10. Add decision_gate checks for trade-enabled account state.
11. Add manual ladder execution intent contract.
12. Add executor idempotency/audit contract before broker writes.
13. Explicitly document that withdrawal keys are unsupported.

## Acceptance criteria

- A user can onboard with only a read key.
- Account dashboards work with read key only.
- Manual ladder setup can be created without a trade key.
- Manual ladder execution is blocked until a trade key exists and decision_gate approves.
- Account refresh refuses `TRADE_EXECUTION` credentials.
- Executor refuses `READ_ONLY_PRIVATE` credentials.
- No non-executor service can decrypt or load trade credentials.
- No layer except executor can submit or cancel broker orders.
- Broker write logs include account, credential scope, decision_gate result, execution intent id, and permission source.
- No withdrawal-capable key is required or supported.

## Non-goals

- Do not add trade key support to the linked-profile runtime orchestrator.
- Do not enable live trading.
- Do not submit real orders.
- Do not bypass decision_gate for manual ladder execution.
- Do not store trade-capable credentials before the scope boundary exists.
