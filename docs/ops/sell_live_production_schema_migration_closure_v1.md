# SELL LIVE production schema migration closure (Issue #562)

Date: 2026-08-28
Status: audit only. No migration applied, no production write, no credential,
LIVE-permission, or kill-switch mutation performed by this document or its
preparation.

```text
production_db_mutation=0
migration_apply=0
credential_mutation=0
live_permission_mutation=0
kill_switch_mutation=0
service_mutation=0
broker_writes=0
order_submission=0
live_activation=0
```

## 1. Scope and source of truth

This audit resolves the exact schema closure required for the
`PRODUCTION_SCHEMA_READY` phase of the SELL LIVE readiness controller
(`src/ops/sell_live_activation_controller_v1.py`, branch
`issue-551-sell-live-readiness-controller`, PR #556, not yet merged to
`main`). That controller's `_phase_production_schema_ready` check is a
presence-only `SHOW TABLES` test against the exact literal
`REQUIRED_PRODUCTION_TABLES` tuple below — this is the sole authority for
what "schema ready" means; this audit does not invent a broader definition.

```python
REQUIRED_PRODUCTION_TABLES = (
    "trading_account",
    "trading_account_credential",
    "executor_credential_binding",
    "automatic_exit_live_decision_gate_permission_v1",
    "automatic_exit_live_decision_gate_permission_revocation_v1",
    "executor_execution_handoff",
    "executor_execution_leg",
    "executor_live_authority_grant",
    "executor_live_authority_revocation",
    "executor_kill_switch_event",
)
```

Verification method: read-only `information_schema` queries against the
configured target database (`SELECT DATABASE()` confirmed `synth`), executed
via `src.common.db.get_db_connection()`. No `SHOW`/`SELECT` touched row
content beyond `trading_account`'s account-identity columns, which are
already read by the controller's own `PRECHECK` phase.

## 2. Exact migration closure

Only **one** required table is absent in the target `synth` database today.
Every other required table already exists.

| Required table | Present? | Creating migration |
| --- | --- | --- |
| `trading_account` | YES | not created by any migration in `db/migrations/` — pre-existing baseline schema (see §7) |
| `trading_account_credential` | YES | `db/migrations/20260609_trading_account_credential_v1.sql` |
| `executor_credential_binding` | YES | `db/migrations/20260812_manual_execution_executor_handoff_v1.sql` |
| `automatic_exit_live_decision_gate_permission_v1` | **NO** | `db/migrations/20260818_automatic_exit_live_decision_gate_permission_v1.sql` |
| `automatic_exit_live_decision_gate_permission_revocation_v1` | **NO** | same file as above |
| `executor_execution_handoff` | YES | `db/migrations/20260815_shared_executor_substrate_v1.sql` (extended by `20260819_shared_executor_persisted_consumer_v1.sql`) |
| `executor_execution_leg` | YES | `db/migrations/20260815_shared_executor_substrate_v1.sql` |
| `executor_live_authority_grant` | YES | `db/migrations/20260817_executor_live_authority_v1.sql` |
| `executor_live_authority_revocation` | YES | same file as above |
| `executor_kill_switch_event` | YES | same file as above |

**Exact migration closure needed to make `PRODUCTION_SCHEMA_READY` pass:**

```text
db/migrations/20260818_automatic_exit_live_decision_gate_permission_v1.sql
```

This single file creates both missing tables
(`automatic_exit_live_decision_gate_permission_v1` and its companion
`..._revocation_v1`). No other migration file is missing from this
environment for the `REQUIRED_PRODUCTION_TABLES` set. `executor_execution_handoff`
and the rest of the shared executor substrate are **already applied** in
this environment — the account-protection/executor/credential prerequisite
tables are also already applied. This corrects an earlier (2026-08-19,
`docs/status/issue_392_phase6_sell_live_readiness_v1.md`) audit statement
that `executor_execution_handoff` did not yet exist in production; it has
since been applied by a later migration pass and is confirmed present now.

## 3. Dependency / apply order

The one missing migration has exactly one schema dependency:
`trading_account` (referenced by `fk_automatic_exit_live_permission_account`,
`trading_account_id BIGINT UNSIGNED`). That table is already present with a
matching column type (`bigint(20) unsigned`, `InnoDB`,
`utf8mb4_unicode_ci`), so there is no further ordering constraint.

```text
1. db/migrations/20260818_automatic_exit_live_decision_gate_permission_v1.sql
```

Internally, this file's two `CREATE TABLE` statements are already ordered
correctly: `automatic_exit_live_decision_gate_permission_v1` first, then
`..._revocation_v1` (whose composite FK targets the permission table's
`(id, trading_account_id)` unique key). Apply the file whole, in one
transaction/session, in the order the statements already appear in the file.
Do not split or reorder the statements.

## 4. Tables / indexes / constraints / triggers created

`automatic_exit_live_decision_gate_permission_v1`:
- PK: `automatic_exit_live_decision_gate_permission_id`
- UNIQUE: `uq_automatic_exit_live_permission_account_binding (id, trading_account_id)` — this is what the revocation table's composite FK targets
- INDEX: `ix_automatic_exit_live_permission_lookup (trading_account_id, effective_from_ts_utc)`
- FK: `fk_automatic_exit_live_permission_account (trading_account_id) -> trading_account(trading_account_id)`
- CHECK: `chk_automatic_exit_live_permission_flag` (flag in {0,1}); `chk_automatic_exit_live_permission_window` (`effective_until_ts_utc IS NULL OR > effective_from_ts_utc`)
- TRIGGERS: `trg_automatic_exit_live_permission_v1_no_update`, `trg_automatic_exit_live_permission_v1_no_delete` — both `SIGNAL SQLSTATE '45000'`, making the row permanently append-only/immutable

`automatic_exit_live_decision_gate_permission_revocation_v1` (the revocation
table required by the audit's "revocation tables" checklist item):
- PK: `automatic_exit_live_decision_gate_permission_revocation_id`
- INDEXES: `ix_automatic_exit_live_permission_revocation_binding`, `ix_automatic_exit_live_permission_revocation_lookup`, `ix_automatic_exit_live_permission_revocation_account`
- FK (composite): `fk_automatic_exit_live_permission_revocation_permission_account (permission_id, trading_account_id) -> automatic_exit_live_decision_gate_permission_v1(id, trading_account_id)` — this single composite FK is the only account-linkage constraint; a separate direct FK to `trading_account` is deliberately omitted as redundant (transitively guaranteed via the permission row's own FK)
- CHECK: `chk_automatic_exit_live_permission_revocation_text` (`actor`/`reason` non-blank)
- TRIGGERS: `trg_automatic_exit_live_permission_revocation_v1_no_update`, `trg_automatic_exit_live_permission_revocation_v1_no_delete` — append-only, same `SIGNAL` pattern

No other index, FK, or trigger changes are required by this closure. No
existing table is altered.

## 5. Credential / executor / account-protection prerequisites (verified present)

Read-only `information_schema.tables` presence check against `synth`
confirmed all of the following are already applied and require no action
from this closure:

```text
trading_account                                   PRESENT
trading_account_credential                        PRESENT
executor_credential_binding                       PRESENT
executor_execution_handoff                        PRESENT
executor_execution_leg                            PRESENT
executor_live_authority_grant                     PRESENT
executor_live_authority_revocation                PRESENT
executor_kill_switch_event                        PRESENT
account_protection_policy_config_v1               PRESENT
account_protection_policy_config_revocation_v1    PRESENT
```

`executor_execution_handoff` / shared executor substrate (§ audit
requirement "whether `executor_execution_handoff` or other shared executor
substrate migrations are still unapplied") is **not** missing — it is
present and does not need to be part of this closure.

## 6. Preflight SQL (read-only)

Run against the target database before applying the migration:

```sql
-- 1. Confirm target database identity.
SELECT DATABASE();

-- 2. Confirm the two target tables are absent (expected: 0 rows).
SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN (
    'automatic_exit_live_decision_gate_permission_v1',
    'automatic_exit_live_decision_gate_permission_revocation_v1'
  );

-- 3. Confirm the FK target exists with a compatible column type.
SELECT column_name, column_type, is_nullable
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name = 'trading_account'
  AND column_name = 'trading_account_id';

-- 4. Confirm engine/collation compatibility with the new tables.
SELECT engine, table_collation
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name = 'trading_account';

-- 5. Confirm no name collision on the trigger/constraint identifiers used
--    by the migration (defensive; expected: 0 rows for all four).
SELECT trigger_name
FROM information_schema.triggers
WHERE trigger_schema = DATABASE()
  AND trigger_name IN (
    'trg_automatic_exit_live_permission_v1_no_update',
    'trg_automatic_exit_live_permission_v1_no_delete',
    'trg_automatic_exit_live_permission_revocation_v1_no_update',
    'trg_automatic_exit_live_permission_revocation_v1_no_delete'
  );
```

Verified 2026-08-28 against the configured `synth` database: query 1
returned `synth`; query 2 returned 0 rows (both tables absent, confirming
the gap); query 3 returned `trading_account_id / bigint(20) unsigned / NO`
(matches the migration's `BIGINT UNSIGNED NOT NULL` FK column exactly);
query 4 returned `InnoDB / utf8mb4_unicode_ci` (matches the migration's
`ENGINE=InnoDB ... COLLATE=utf8mb4_unicode_ci`); query 5 returned 0 rows.

## 7. Note: `trading_account` has no tracked migration file

No file under `db/migrations/` contains `CREATE TABLE ... trading_account`
(only later ALTER-shaped migrations that reference it as an FK target, e.g.
`20260607_app_profile_trading_account_link_v1.sql`,
`20260818_account_trading_account_link_v1.sql`). `trading_account` is
pre-existing baseline schema captured only in
`docs/database/schema_snapshot.sql` (the `make schema-snapshot` dump target),
not created by any migration in this repository's history. This is stated
here only as an audit fact for closure completeness — this issue does not
propose adding a retroactive migration for it, since it already exists in
the target environment and doing so would be schema cleanup outside this
issue's scope.

## 8. Post-apply verification SQL

```sql
-- All ten required tables now present (expected: 10 rows).
SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN (
    'trading_account', 'trading_account_credential',
    'executor_credential_binding',
    'automatic_exit_live_decision_gate_permission_v1',
    'automatic_exit_live_decision_gate_permission_revocation_v1',
    'executor_execution_handoff', 'executor_execution_leg',
    'executor_live_authority_grant', 'executor_live_authority_revocation',
    'executor_kill_switch_event'
  );

-- Zero rows in the new tables immediately after apply (append-only, no
-- backfill expected).
SELECT COUNT(*) FROM automatic_exit_live_decision_gate_permission_v1;
SELECT COUNT(*) FROM automatic_exit_live_decision_gate_permission_revocation_v1;

-- Both immutability triggers exist on both tables (expected: 4 rows).
SELECT event_object_table, trigger_name, event_manipulation
FROM information_schema.triggers
WHERE trigger_schema = DATABASE()
  AND event_object_table IN (
    'automatic_exit_live_decision_gate_permission_v1',
    'automatic_exit_live_decision_gate_permission_revocation_v1'
  );

-- FK from the revocation table resolves correctly (expected: 1 row).
SELECT constraint_name, table_name, referenced_table_name
FROM information_schema.referential_constraints
WHERE constraint_schema = DATABASE()
  AND table_name = 'automatic_exit_live_decision_gate_permission_revocation_v1';

-- Immutability enforced in practice: this must raise SQLSTATE 45000, not
-- silently succeed (run in a throwaway transaction; ROLLBACK regardless of
-- outcome; never leave this row committed):
--   BEGIN;
--   INSERT INTO automatic_exit_live_decision_gate_permission_v1
--     (trading_account_id, live_execution_permitted, effective_from_ts_utc,
--      source_provenance)
--   VALUES (<any existing trading_account_id>, 0, UTC_TIMESTAMP(6), 'post_apply_probe');
--   UPDATE automatic_exit_live_decision_gate_permission_v1
--     SET live_execution_permitted = 1
--     WHERE source_provenance = 'post_apply_probe';  -- expect ER_SIGNAL_EXCEPTION
--   ROLLBACK;
```

## 9. Idempotency expectations

The migration uses `CREATE TABLE IF NOT EXISTS` for both tables, so a
re-run against an environment where it already partially or fully applied
is safe for the table definitions themselves. `CREATE TRIGGER` in MariaDB
has **no** `IF NOT EXISTS` guard in this file — re-running the file against
an environment where the triggers already exist will fail with
`ER_TRIGGER_ALREADY_EXISTS` (this is the correct, safe failure mode: it
means the file was already fully applied, and CI/apply tooling must
recognize the migration as `ALREADY_APPLIED`, not `FAILED`, on that specific
error). Do not add `DROP TRIGGER IF EXISTS` guards to make it silently
re-runnable — that would let a broken/partial apply silently replace a
trigger with a different definition, undermining the append-only
invariant's provenance. Apply-order tooling must record migration
application state explicitly rather than relying on blind re-execution.

## 10. Stop / fail criteria

Stop and do not proceed to production apply if any of the following are
true at apply time:

- either target table already exists (re-check §6 query 2 immediately
  before apply; if a row is returned, the environment state has changed
  since this audit and the apply must be re-scoped, not blindly continued)
- `trading_account.trading_account_id` is not `BIGINT UNSIGNED` (would break
  the FK type match)
- any of the four trigger names in §6 query 5 already exist
- the migration runner does not run the full file in one transaction/session
  (MariaDB DDL is not transactional per-statement across `CREATE TABLE` +
  `DELIMITER`-scoped `CREATE TRIGGER` blocks in some runners; verify the
  apply tool executes the file as MariaDB expects, statement-by-statement,
  respecting the `DELIMITER //` / `DELIMITER ;` blocks literally, not naively
  splitting on `;`)
- database user lacks `CREATE TABLE`, `CREATE TRIGGER`, or `REFERENCES`
  privilege on `synth`
- any other required table in §5 is found absent at apply time (would
  indicate environment drift since this audit; re-run the full closure audit
  rather than assuming this document's §5 findings still hold)

If apply fails partway (e.g. permission table created, trigger creation
fails), do not manually patch state; re-run this document's §6 preflight
queries to determine exact partial state, then apply only the remaining
statements the file's `IF NOT EXISTS`/idempotency semantics (§9) make safe
to re-run.

## 11. Rollback strategy

Forward-only. No rollback migration is provided or recommended.

Rationale: both new tables are designed as strictly append-only, immutable,
audit-trail objects (permission/revocation facts for LIVE trading
authority). They start empty and, until a permission is actually granted,
have no rows and no read/write coupling from any other runtime path — no
production code queries them yet outside the not-yet-merged
`sell_live_activation_controller_v1` and the existing
`src/decision_gate/automatic_exit_live_permission_*` modules, which already
fail closed (`LIVE_PERMISSION_NOT_GRANTED`) on an empty table exactly as
they do on a missing one from the caller's perspective — the only observable
difference is `PRODUCTION_SCHEMA_READY` moving from BLOCKED to PASSED.
`DROP TABLE` is intentionally not documented as a rollback path: once any
permission/revocation row exists, dropping the table destroys the
append-only compliance/audit trail these tables exist to guarantee (see
Phase K in `docs/status/issue_392_phase6_sell_live_readiness_v1.md`, which
already states these specific tables must never be deleted). If this schema
change must be reverted before any row is ever written, an operator may
manually `DROP TABLE automatic_exit_live_decision_gate_permission_revocation_v1,
automatic_exit_live_decision_gate_permission_v1;` (child before parent, due
to the composite FK) as an explicit, separately authorized ops action — this
document does not pre-approve that action and it is out of scope to
automate.

## 12. Backfill requirements

None. Zero semantic data mutation is required. Both tables are new,
strictly append-only fact tables; the resolver contracts already treat "no
permission row" and "no matching, currently-effective permission row" as the
same `LIVE_PERMISSION_NOT_GRANTED` state
(`src/decision_gate/automatic_exit_live_permission_contract_v1.py`,
`resolve_automatic_exit_live_decision_gate_permission_v1`). No existing row
in any other table needs to change, and no seed/default permission row
should be inserted by this migration or its apply step — granting an actual
LIVE permission is a separate, explicitly authorized action outside this
issue's scope (see AGENTS.md live-trading-safety and this issue's own
safety boundary).

## 13. Expected effect on `sell_live_activation_controller_v1`

Applying only this one migration:

- flips `PRODUCTION_SCHEMA_READY` from `BLOCKED`
  (`PRODUCTION_SCHEMA_TABLES_MISSING`, listing the two tables above) to
  `PASSED` (`OK`, `required_tables_present=10`).
- does **not** flip the overall terminal state to `LIVE_AUTHORIZATION_REQUIRED`.
  Independently of schema, `PRECHECK` currently fails closed with
  `ACCOUNT_MODE_EVIDENCE_INCONSISTENT` for at least one `live`-mode account
  (`trading_account_id=2` and `3` both have `account_mode='live'` with
  `live_trading_enabled=0` in the target database as read 2026-08-28) unless
  the controller is invoked with a `trading_account_id` where that
  consistency holds. `LIVE_PERMISSION_READY` will also remain `BLOCKED`
  (`LIVE_PERMISSION_NOT_GRANTED`) since no permission row exists yet (§12),
  and `CREDENTIAL_BINDING_READY` / `KILL_SWITCH_READY` / `RUNTIME_READY`
  depend on separate, not-yet-provisioned prerequisites already tracked
  under #551's own Phase J checklist. This closure resolves exactly one
  named blocker (`PRODUCTION_SCHEMA_READY`) and does not claim to resolve
  the others; they are out of scope for issue #562.
- requires no compatibility shim in the controller: it already queries these
  exact table names via `SHOW TABLES`/presence check only, with no schema
  version negotiation, so once the tables exist with the names/columns this
  migration defines, no controller code change is needed.
