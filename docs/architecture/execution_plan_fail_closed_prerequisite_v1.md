# Execution Plan Fail-Closed Prerequisite V1

```text
status=fail-closed prerequisite
live_execution_enabled=false
```

## Scope

This change establishes a persisted execution-plan contract without granting
live-execution authority.

Implemented:

- canonical planner writes persist explicit `trading_account_id`,
  `execution_mode`, `execution_intent`, `action_type`, `requested_side`, and
  `market` values;
- `account_id` is never reinterpreted as `trading_account_id`;
- planner mode, action, and side values are exact, case-sensitive enums;
- PAPER processing imports a standalone public market-data client and uses a
  DB-only environment loader;
- persisted PAPER plans stay on the simulated PAPER path, regardless of the
  global worker mode;
- persisted LIVE plans fail before permission lookup, private credentials,
  private-client construction, authenticated calls, submission state, or
  broker writes;
- direct buy and sell ladder construction and preview remain available, while
  direct broker placement is disabled.

Not implemented:

- canonical decision-gate permission producer;
- permission-evidence persistence or trust;
- signing or verification key infrastructure;
- account-bound trade credentials;
- atomic live-execution claims;
- broker submission;
- live order cancellation;
- authenticated live-order monitoring;
- broker idempotency or uncertain-result reconciliation.

## Planner Contract

Canonical planner writes require:

```text
trading_account_id = explicit positive canonical ID
execution_mode = PAPER | LIVE
execution_intent = nonblank canonical intent
action_type = PLACE_ORDER | CANCEL_ORDER | MONITOR_ORDER
requested_side = BUY | SELL
market = nonblank canonical venue market
```

The migration keeps new columns nullable so historical plans remain intact.
Python writer validation rejects incomplete new canonical writes before SQL.
Legacy `account_id` values do not satisfy `trading_account_id`.

The planner may persist a complete LIVE contract for future work, but that plan
cannot be consumed by the executor in this version.

## PAPER And LIVE Boundaries

The persisted plan owns execution mode. Runtime or environment settings cannot
promote PAPER to LIVE.

The PAPER import graph does not import the private Bitvavo client. Repository
`.env` loading is restricted to an explicit database-key allowlist, so exchange
credentials, the account credential master key, and trade signing material are
not loaded by the PAPER path.

Every LIVE plan raises:

```text
LIVE_EXECUTION_PREREQUISITES_UNAVAILABLE
CANONICAL_DECISION_GATE_PERMISSION_PRODUCER_REQUIRED
ACCOUNT_BOUND_TRADE_CREDENTIAL_BINDING_REQUIRED
LIVE_EXECUTOR_ACTIVATION_REQUIRED
```

There is no environment flag, global credential, manually inserted evidence,
or legacy account credential bypass.

## Migration

`20260721_execution_plan_explicit_intent_contract_v1.sql` adds only the retained
execution-plan fields. It validates each field's exact type, length,
nullability, default, charset, and collation, and validates the exact nullable
foreign key from `execution_plan.trading_account_id` to
`trading_account.trading_account_id`.

The migration preserves historical rows, normalizes only exact legacy `paper`
and `live` mode values, repairs compatible missing fields, fails explicitly on
incompatible retained fields, and is idempotent after success. It creates no
permission, signing, attempt, claim, or broker-order tables. Unmerged draft PR
#129 permission tables are not production migration history and are neither
created nor consumed by this change.

## Future Order

1. Merge this fail-closed prerequisite.
2. Merge private-read PR #127 after its independent review.
3. Implement account-bound trade credentials in separate PR B2.
4. Implement the canonical decision-gate permission producer.
5. Implement atomic live executor consumption.
6. Perform controlled non-production acceptance.
7. Obtain explicit deployment authorization.

Credentials authenticate broker requests. Credentials never authorize
execution.
