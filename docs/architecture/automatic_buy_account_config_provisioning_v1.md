# Automatic BUY account configuration provisioning v1 (Issue #498)

## Problem

Issue #456 Stage B production acceptance stopped fail-closed:
`strategy_bucket_account_config_v1` (#279) had zero rows for every trading
account, and its resolver treats a missing row as unresolved by design (fail
closed, never a permissive default). `automatic_buy_account_permission_v1`
(#474) was independently also empty. Neither table had a repository-owned
writer -- the only way to populate them was direct SQL, which is forbidden as
an operational shortcut (it would bypass this repository's own validation and
audit trail entirely).

#471 (`run_automatic_buy_dry_run_acceptance_v1.py`) and #474
(`automatic_buy_account_allocation_evidence_v1.py`, see
`docs/architecture/automatic_buy_account_allocation_evidence_v1.md`) already
provide the canonical DRY_RUN producer seam and the decision-gate-owned
account evidence projection. This change adds the missing piece: a canonical,
repository-owned way to *provision* the two account-owned configuration facts
that projection depends on.

## What this adds

Two provisioning services under `src/decision_gate/`, each the sole writer
for its table:

- `strategy_bucket_account_config_provisioning_v1.py` --
  `provision_strategy_bucket_account_config_v1` writes
  `strategy_bucket_account_config_v1` rows.
- `automatic_buy_account_permission_provisioning_v1.py` --
  `provision_automatic_buy_account_permission_v1` writes
  `automatic_buy_account_permission_v1` rows.

One CLI exposes both: `run_automatic_buy_account_config_provisioning_v1.py`
with subcommands `strategy-bucket-config` and `account-permission`.

Both writers and the CLI:

- resolve the target account by canonical `(account_code, venue)` identity
  only -- operator usage never takes a raw numeric `trading_account_id`.
  Resolution never trusts a bare `LIMIT 1`: zero matches is an unknown
  account, more than one match (a corrupt identity binding, since
  `account_code` carries a real `uq_trading_account_code` UNIQUE constraint
  in production) fails closed rather than silently picking one;
- normalize any UTC-equivalent-offset `effective_from_ts_utc` (e.g.
  `+02:00`) to true UTC before it is ever resolved, compared, or written --
  MariaDB `DATETIME` columns carry no offset, so an un-normalized value would
  otherwise persist the wrong wall-clock instant;
- validate the request, then **pre-validate the candidate row through the
  exact same canonical resolver** (`resolve_strategy_bucket_account_config_v1`
  / `resolve_automatic_buy_account_permission_v1`) the runtime gate path uses,
  before ever touching the DB -- so a row this writer accepts is guaranteed to
  be a row the #474 projection and #279/#474 resolvers will later accept;
- are deterministic and idempotent: rerunning with the exact same values for
  the same `(account, [bucket,] effective_from_ts_utc)` identity is a no-op
  that returns the existing row (no duplicate insert);
- fail closed on a conflicting rerun (an effective row already covers the
  identity with *different* values) -- raising
  `StrategyBucketAccountConfigConflictError` /
  `AutomaticBuyAccountPermissionConflictError` rather than silently
  superseding it. This also covers a row scheduled to start *after* the
  candidate: because every inserted row is open-ended, a future row would
  otherwise become simultaneously active once its own start passes, making
  the runtime resolver ambiguous -- so any persisted row for the identity
  with a later `effective_from_ts_utc` blocks the insert too, not just a
  row already effective right now;
- never UPDATE or DELETE -- both target tables are append-only by DB trigger.
  Ending or replacing an existing effective row is a revocation action,
  deliberately out of scope for these writers (this issue adds provisioning,
  not lifecycle/decommissioning);
- import no broker, executor, credential, or order module, and create/modify
  no market candidate truth.

## Why `automatic_buy_account_permission_v1` gets a writer, not a "derived, no seeding needed" answer

The acceptance criteria for #498 required determining whether this table is
durable operator configuration (needs a writer) or fully derived evidence
(must not be separately seeded). It is the former:
`automatic_buy_account_permission_repository_v1.py` only *reads* persisted
rows: there is no code anywhere that computes `execution_enabled` from
balances, positions, or any other account snapshot, and
`resolve_automatic_buy_account_permission_v1`'s own docstring states
"absence of a row is not evidence of permission" (default denied, not
default derived-true/false). This is architecturally identical to
`strategy_bucket_account_config_v1` and to the already-existing
`automatic_buy_live_decision_gate_permission_v1` writer pattern: a durable,
append-only, decision-gate-owned opt-in fact that must be explicitly granted.

## Idempotency and conflict resolution, precisely

Both writers use the same three-step read-then-decide shape (no DB-level
uniqueness constraint is added or required):

1. Load the account's full persisted history (rows + revocations) for the
   relevant table.
2. Resolve the currently *effective* row, if any, at the request's
   `effective_from_ts_utc`, using the canonical contract resolver (the same
   one the runtime gate path uses). "No effective row" is not an error here;
   it means it is safe to insert.
3. If an effective row exists: compare its stored values field-by-field
   against the request. Identical -> return it unchanged (idempotent, no
   insert). Different -> raise a conflict error and insert nothing. Anything
   the resolver itself treats as ambiguous/malformed persisted state is
   propagated as a provisioning error, never silently inserted over.

There is intentionally no DB-level unique constraint enforcing this: a
partial/conditional unique index on `(trading_account_id, strategy_bucket_id)`
for open-ended rows would also incorrectly block the existing
revoke-then-replace supersession flow the schema already relies on (a
revoked row keeps `effective_until_ts_utc IS NULL` forever; only the
revocation fact excludes it from resolution). This is an accepted trade-off
for a deliberate, low-frequency, human-reviewed operator action, not an
automated/high-concurrency path.

## Strategy-bucket identity validation

No canonical strategy-bucket registry table exists in this repository (#232
bucket definition/validation is explicitly out of scope upstream). "Unknown
bucket" is therefore enforced as identity well-formedness only (non-empty,
no surrounding whitespace, bounded length, restricted charset) -- the same
trust level every other module in the automatic-BUY path already applies to
`strategy_bucket_id`. If a canonical bucket registry is added later (#232),
this writer's validation should be tightened to check membership against it.

## Production mutation boundary

This change is repository-only. It adds no migration (both target tables
already exist in production per the #456 Stage A rollout) and performs no
production DB write itself. Running the new CLI against a real database --
including choosing which account, which bucket, and which limit values to
provision for the #456 Stage B acceptance account -- is a separate, explicitly
reviewed operational step with exact values recorded before execution, per
#498's stated production mutation boundary. Merging this PR grants no such
authorization.

```text
repository_phase_production_db_mutation=0
live_trading_enabled_mutation=0
executor_live_authority_grant=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```

Refs #456 #471 #474 #399 #279 #318
