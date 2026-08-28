# trading_account_id 2/3 `live` -> `live_readonly` data migration (Issue #551)

Status: **prepared, NOT applied**. This document is the exact plan for a
narrow, explicitly-authorized follow-up data change. No production row has
been modified. `automatic_exit_execution_handoff_application_v1` and
`automatic_buy_execution_handoff_application_v1` performs no broker write,
order submission, LIVE activation, or credential mutation, and neither does
this document.

## Schema dependency (hard precondition)

This data correction depends on a prior, separate schema migration:

```text
db/migrations/20260828_trading_account_account_mode_live_readonly_v1.sql
```

Production's `trading_account.chk_trading_account_mode` CHECK constraint
currently only permits `account_mode IN ('paper','live')`. Applying the
`UPDATE` in this document against that constraint fails closed with a
MariaDB `4025` constraint-violation error (`CONSTRAINT
'chk_trading_account_mode' failed for 'synth'.'trading_account'`) -- no row
is changed. The schema migration above extends the same constraint to
`account_mode IN ('paper','live_readonly','live')` and touches no other
column, table, or constraint (in particular it does not touch
`chk_trading_account_live_requires_enabled` or `live_trading_enabled`).

Order of operations is strict:

1. schema migration `20260828_trading_account_account_mode_live_readonly_v1.sql`
   is merged, deployed, and confirmed applied to the target database
   (`information_schema.CHECK_CONSTRAINTS` shows `live_readonly` in
   `chk_trading_account_mode`'s `CHECK_CLAUSE`)
2. only then may the `UPDATE` in this document be applied

```text
production_db_mutation=0
credential_mutation=0
live_permission_mutation=0
kill_switch_mutation=0
service_mutation=0
broker_writes=0
order_submission=0
live_activation=0
```

## Scope

Exactly two rows, one column each:

```sql
UPDATE trading_account
   SET account_mode = 'live_readonly'
 WHERE trading_account_id IN (2, 3)
   AND account_mode = 'live'
   AND live_trading_enabled = 0;
```

`live_trading_enabled` is not touched -- it is already `0` for both rows and
`live_readonly` requires the same value. No other column, no other
`trading_account` row, and no other table is touched. No credential,
permission, or kill-switch row is read or written by this statement.

## Preconditions (verify immediately before apply, not only at plan time)

```sql
-- 0. Confirm the schema dependency above is already applied (expected:
--    CHECK_CLAUSE contains 'live_readonly').
SELECT CHECK_CLAUSE
FROM information_schema.CHECK_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = DATABASE()
  AND CONSTRAINT_NAME = 'chk_trading_account_mode';

-- 1. Confirm target database identity.
SELECT DATABASE();

-- 2. Confirm exact current state of the two target rows (expected: both
--    rows account_mode='live', live_trading_enabled=0, enabled=1).
SELECT trading_account_id, account_code, account_mode, live_trading_enabled, enabled, venue
FROM trading_account
WHERE trading_account_id IN (2, 3)
ORDER BY trading_account_id;

-- 3. Confirm no other trading_account row would be affected by a mode-only
--    predicate (expected: exactly the two rows above, nothing else).
SELECT trading_account_id
FROM trading_account
WHERE account_mode = 'live' AND live_trading_enabled = 0;
```

Stop and do not apply if:

- query 0 does not contain `live_readonly` -- the schema dependency above is
  not yet applied to this database; applying the `UPDATE` will fail closed
  with MariaDB error `4025` (`CONSTRAINT 'chk_trading_account_mode' failed`)
  and change nothing, but stop and fix the dependency instead of treating
  that failure as expected
- query 2 shows either row's `account_mode`, `live_trading_enabled`, or
  `enabled` has changed from the expected values above (re-run this
  document's audit, don't blindly proceed)
- query 3 returns any `trading_account_id` other than 2 and 3 (the
  `UPDATE ... WHERE trading_account_id IN (2, 3)` predicate above is exact
  and unaffected by this, but a changed environment shape means this
  document's scope assumption should be re-verified first)
- the repository code implementing `live_readonly` handling
  (`src/account/account_mode_contract_v1.py` and its consumers, this PR) is
  not yet merged/deployed to the environment being migrated -- applying the
  data change first would make `sell_live_activation_controller_v1` and the
  decision_gate gates evaluate `account_mode='live_readonly'` as
  `UNSUPPORTED_ACCOUNT_MODE` (fails closed, but for the wrong reason) until
  the code ships

## Post-apply verification

```sql
-- Expected: both rows now account_mode='live_readonly',
-- live_trading_enabled unchanged at 0.
SELECT trading_account_id, account_code, account_mode, live_trading_enabled, enabled, venue, updated_ts_utc
FROM trading_account
WHERE trading_account_id IN (2, 3)
ORDER BY trading_account_id;

-- Expected: 0 rows -- no trading_account row should still be the
-- pre-migration inconsistent 'live' + live_trading_enabled=0 shape.
SELECT trading_account_id
FROM trading_account
WHERE account_mode = 'live' AND live_trading_enabled = 0;
```

Then re-run the SELL LIVE readiness controller for each account and confirm
`PRECHECK` now reports `ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE` (canonically
consistent, permanently execution-ineligible) instead of
`ACCOUNT_MODE_EVIDENCE_INCONSISTENT`:

```bash
python -m src.ops.sell_live_activation_controller_v1 \
  --check \
  --trading-account-id 2 \
  --venue bitvavo \
  --executor-identity manual_execution_bitvavo_v1 \
  --runtime-owner odroid \
  --canary-market BTC-EUR \
  --canary-max-orders-per-cycle 1 \
  --canary-max-notional-eur 25
```

(repeat with `--trading-account-id 3`)

## Effect on overall readiness

This data migration only changes the `PRECHECK` reason code for accounts
2/3 from `ACCOUNT_MODE_EVIDENCE_INCONSISTENT` to
`ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE`. Both are `BLOCKED` outcomes; neither
account becomes execution-eligible or moves the controller's overall
`terminal_state` off `BLOCKED`. This migration does not, by itself,
provision a genuinely execution-capable live account -- that remains a
separate, explicitly authorized action outside this issue's scope, as
already flagged in the SELL LIVE readiness audit.

## Rollback / forward-fix strategy

Forward-only, same convention as
`docs/ops/sell_live_production_schema_migration_closure_v1.md` §11: this is
a data classification correction, not a destructive change.

- **Rollback** (only needed if the `account_mode='live_readonly'` value
  turns out to be wrong for these accounts, which is not expected): revert
  with the exact inverse statement,
  `UPDATE trading_account SET account_mode = 'live' WHERE trading_account_id
  IN (2, 3) AND account_mode = 'live_readonly';` This restores the
  pre-migration `ACCOUNT_MODE_EVIDENCE_INCONSISTENT` state; it does not
  restore any other side effect because there is none -- no other table or
  row is touched by the forward migration.
- **Forward-fix**: if a future account is discovered with the same
  real-broker/read-only shape, apply the same one-column `UPDATE` pattern
  scoped to that account's exact `trading_account_id`, after confirming its
  `live_trading_enabled` is already `0` (this migration never flips that
  flag; it only reclassifies `account_mode` for a row already provisioned
  as non-execution-eligible).
- No `DROP`/`DELETE` of any kind is part of either direction. No
  append-only/immutable table (e.g. `automatic_exit_live_decision_gate_permission_v1`)
  is touched by this migration in either direction.

## Explicit non-actions

This document does not authorize, and its author has not performed:

- applying the `UPDATE` statement above against any environment
- provisioning a genuinely execution-capable `live` account
- any `live_trading_enabled`, credential, LIVE permission, or kill-switch
  change
- any broker call, order submission, or LIVE activation

Applying the `UPDATE` statement is a separate, explicitly authorized
production action, to be performed only after this repository change is
merged and deployed, following the same preflight/apply/post-apply
discipline as `docs/ops/sell_live_production_schema_migration_closure_v1.md`.
