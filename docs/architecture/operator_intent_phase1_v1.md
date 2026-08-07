# Operator Intent — Phase 1 (Issue #262, parent #254)

## Purpose

Establish one authoritative, multi-account-safe canonical persistence model
and command/read boundary for account-scoped operator intent. This is the
foundation layer only. It deliberately stops before `decision_gate`,
`execution_planner`, executor/order handling, and Profit Plan mutation
controls — those are later phases of #254.

Operator intent expresses **preference**, never **permission**.

## Architecture boundary

```text
operator-intent command/service layer
-> canonical persistence + append-only revision/audit history
-> authorized read model
```

Not in this phase (owned by later #254 phases):

```text
decision_gate integration        -> not_in_phase_1
execution_planner integration    -> not_in_phase_1
executor / order handling        -> not_in_phase_1
Profit Plan write controls       -> not_in_phase_1
broker calls / order submission  -> never in this layer
```

`selection_engine` must remain completely account-agnostic. It must never
import or read `src.operator_intent.*`. Enforced by
`tests/test_manual_execution_p0_architecture_boundaries_v1.py::TestSelectionEngineNeverImportsOperatorIntent`
and `tests/test_operator_intent_phase1_v1.py::test_selection_engine_does_not_import_operator_intent`.

## Canonical identity reuse

Phase 1 does not invent a parallel identity model. It reuses the existing
canonical chain, audited before implementation:

```text
app_user --(app_user_profile_access)--> app_profile
app_profile --(app_profile_trading_account_link, ACTIVE)--> trading_account
```

- **Operator identity**: `AuthenticatedProfileIdentity` (`app_user_id`,
  `app_profile_id`, `profile_code`) — the same server-derived-from-session
  type already used by
  `src.account_provisioning.account_provisioning_service_v1`. Re-exported
  from `src.operator_intent.contracts_v1` rather than redefined. Authorization
  identity is **user + profile context**, not just the user: the same
  `app_user_id` may hold access to more than one `app_profile_id` (the
  existing `app_user_profile_access` model already supports this). Every
  audit field therefore persists both IDs — see "Profile-aware audit fields"
  below.
- **Trading account identity**: `trading_account_id` (BIGINT FK), never a
  profile slug. `profile_code` is never used as a persistence or scope key —
  see `test_profile_slug_is_not_authoritative_persistence_key`.
- **Venue identity**: validated string code against the existing
  `src.account_provisioning.contracts_v1.SUPPORTED_VENUES` allow-list, and
  additionally cross-checked against the target account's own `venue` column
  (defense in depth against a caller supplying a mismatched venue).
- **Canonical market identity**: composite `SYMBOL-QUOTE` string (matching
  the existing market-data convention — there is no `markets` table in this
  repository), validated structurally (`validate_canonical_market`). Phase 1
  performs structural validation only; it does not resolve market identity
  against a live asset registry.

## Schema

Migration: `db/migrations/20260807_operator_intent_phase1_v1.sql`. Follows
existing conventions: idempotent (`CREATE TABLE IF NOT EXISTS`), flat
`db/migrations/` directory, `YYYYMMDD_<slug>_v1.sql` naming, InnoDB /
utf8mb4, FK constraints to `trading_account` and `app_user`.

### Current-state model: `operator_intent`

One row per intent. Multiple rows may exist over time for the same
`(trading_account_id, venue, canonical_market, intent_type)` scope — e.g.
one `CANCELLED` row followed later by a new `ACTIVE` row — but the service
layer enforces that **at most one open-status row exists per scope at a
time**. This is a service-enforced invariant, not a DB constraint, matching
the existing `execution_ladder_leg` convention of resolver-enforced
(not DB-enforced) cross-row invariants.

Key columns: `operator_intent_id` (PK), `trading_account_id`, `venue`,
`canonical_market`, `intent_type`, `priority`, `status`, `reason`, `source`,
`created_by_app_user_id` / `created_by_app_profile_id` / `created_ts_utc`,
`updated_by_app_user_id` / `updated_by_app_profile_id` / `updated_ts_utc`,
`expires_ts_utc`, `version` (optimistic concurrency), `supersedes_intent_id`
/ `superseded_by_intent_id` (supersession lineage).

All timestamps are UTC (`DATETIME(6)`), stored and compared as naive UTC
text/values — callers must pass timezone-aware datetimes; the service
rejects naive datetimes.

### Revision/audit history model: `operator_intent_revision`

Append-only. One row per `CREATED` / `UPDATED` / `CANCELLED` / `SUPERSEDED` /
`EXPIRED` event, capturing the full post-mutation snapshot plus
`revision_version` (mirrors `operator_intent.version` at that point),
`actor_app_user_id` / `actor_app_profile_id`, and `event_ts_utc`. Never
updated or deleted. Unique on `(operator_intent_id, revision_version)`.

The snapshot also includes `supersedes_intent_id` / `superseded_by_intent_id`
— current-state lineage is never left unaudited. Every revision row carries
the row's lineage values *as of that event* (both `NULL` for a normally
created top-level intent; `supersedes_intent_id` set from the first
`CREATED` revision onward for an intent born via `supersede_intent`;
`superseded_by_intent_id` set starting exactly from the `SUPERSEDED` event
that assigns it).

### Profile-aware audit fields

`created_by_app_user_id` / `updated_by_app_user_id` / `actor_app_user_id`
alone do not capture *which authorized profile context* performed a
mutation, and a single `app_user_id` can be linked to more than one
`app_profile_id`. Every current-state and revision-history write therefore
persists **both** IDs from the authorizing `AuthenticatedProfileIdentity`:

- `operator_intent.created_by_app_profile_id` / `updated_by_app_profile_id`
- `operator_intent_revision.actor_app_profile_id`

Both carry `FOREIGN KEY ... REFERENCES app_profile (app_profile_id)`,
alongside the existing `app_user_id` FKs — matching the repository's
existing pattern of referencing `app_profile` directly wherever a
profile-scoped actor is recorded (e.g.
`app_profile_trading_account_link`). `app_user_id` is never replaced or
dropped; both identifiers are always written together. See
`test_same_user_different_authorized_profiles_preserve_distinct_profile_audit_context`.

### Current-state vs terminal/historical reads

`read_current_intents` is a **current-state-only** read model: it returns
`OPEN_STATUSES` rows only (`ACTIVE`, `WAITING_FOR_MARKET_CONTEXT`,
`WAITING_FOR_PERMISSION`, `READY_FOR_PLANNING`, `PLANNED_PREVIEW_AVAILABLE`,
`BLOCKED`). Terminal rows (`CANCELLED`, `EXPIRED`, `SUPERSEDED`) never leak
through it — a superseded/cancelled/expired intent disappears from this read
the moment it becomes terminal, even though the row itself is retained.

Terminal/historical single-intent lookups go through two explicit,
purpose-named paths instead of overloading the current-state read:

- `read_intent_by_id` — authorized single-intent lookup by ID, regardless of
  status (open or terminal).
- `read_revision_history` — full append-only lifecycle history for one
  intent, including every terminal event.

See `test_cancelled_intent_disappears_from_read_current_intents`,
`test_expired_intent_disappears_from_read_current_intents`,
`test_superseded_old_intent_disappears_from_read_current_intents_replacement_visible`,
and `test_revision_history_contains_full_terminal_lifecycle`.

## Intent types and lifecycle status

Intent types: `BUY_PRIORITY`, `REENTRY_WATCH`, `BUY_LADDER_REQUESTED`,
`SELL_LADDER_REQUESTED`, `HOLD_ONLY`, `DO_NOT_ADD`, `MANUAL_REVIEW_PRIORITY`.

Lifecycle status: `ACTIVE`, `WAITING_FOR_MARKET_CONTEXT`,
`WAITING_FOR_PERMISSION`, `READY_FOR_PLANNING`, `PLANNED_PREVIEW_AVAILABLE`,
`BLOCKED` (open/non-terminal), and `EXPIRED`, `CANCELLED`, `SUPERSEDED`
(terminal).

Phase 1 owns persistence of all of these values and owns the lifecycle
events that are purely its own: creation, operator-controlled field updates,
explicit cancellation, explicit supersession, and wall-clock expiration.
**It does not simulate** the market/decision-driven transitions between open
states (e.g. `ACTIVE` -> `READY_FOR_PLANNING`) — those belong to
`decision_gate`/`execution_planner` in a later phase and are out of scope
here.

Contradictory intent types for the same market (e.g. `BUY_PRIORITY` and
`DO_NOT_ADD` both open on the same account/market) are permitted to persist
structurally in Phase 1. Reconciling that contradiction is decision-gate
precedence, explicitly deferred — see
`test_contradictory_intent_types_persist_without_decision_semantics`.

## Authorization boundary

Every command and read is authorized against the reused identity chain,
inside the same transaction as the operation:

1. `app_user_profile_access` must have a row for `(app_user_id,
   app_profile_id)` — else `UnauthorizedOperatorIntentAccess`.
2. `app_profile_trading_account_link` must have an `ACTIVE` row for
   `(app_profile_id, trading_account_id)` — else
   `UnauthorizedOperatorIntentAccess`.
3. `trading_account` must resolve for `trading_account_id`, and its `venue`
   must match the requested `venue` — else `UnresolvedCanonicalIdentity`.

Unresolved identity or failed authorization always fails closed: no row is
written, and the transaction is rolled back. There is no cross-account or
cross-user leakage in reads or writes — see the multi-user/multi-account/
multi-venue isolation tests in `tests/test_operator_intent_phase1_v1.py`.

## Optimistic concurrency

`operator_intent.version` is an integer token. Every mutating command
(`update_intent`, `cancel_intent`, `supersede_intent`, `expire_due_intents`)
requires (or derives, for expiration) an `expected_version` and performs a
single guarded `UPDATE ... WHERE operator_intent_id = ? AND version = ?`.
A zero-row update result means the version no longer matches — the service
raises `OptimisticConcurrencyConflict` and rolls back rather than silently
overwriting a concurrent change. See
`test_optimistic_concurrency_conflict_prevents_lost_update`.

### Concurrent-create verification is still required before deployment

The one-open-intent-per-scope invariant on `create_intent` is enforced by a
read-then-check-then-insert transaction:
`MariaDbOperatorIntentRepository.find_open_intent_for_scope` issues
`SELECT ... FOR UPDATE` before the service decides whether to insert. This
design has intentionally not been redesigned in the Phase 1 amendment
(#262) — no correctness defect was found in it during audit, and the issue
scope is explicitly persistence/command-boundary only, not concurrency
redesign.

However, the test suite backing this PR runs entirely against **sequential
SQLite transactions** (`SqliteOperatorIntentRepository`, no real row
locking). Sequential tests prove the read-then-check-then-insert *logic* is
correct; they do **not** prove MariaDB's actual `SELECT ... FOR UPDATE`
locking/isolation behavior prevents two truly concurrent transactions from
both passing the "no open intent" check and both inserting for the same
scope. **True concurrent-create behavior against MariaDB must be verified
(e.g. two overlapping transactions racing to create the first open intent
for the same scope) before this migration is applied to any database or any
later phase relies on the one-open-intent-per-scope guarantee under
concurrent load.**

## Command / read API

`src.operator_intent.operator_intent_service_v1.OperatorIntentService` is
the **only** owner of `operator_intent` / `operator_intent_revision` writes.
Reporting/UI and any later `decision_gate`/`execution_planner` integration
must call this service; they must never write the tables directly.

Commands:

- `create_intent` — fails closed on duplicate open intent for the same scope
  (`DuplicateActiveIntent`) and on attempting to create directly into a
  terminal status (`InvalidLifecycleTransition`).
- `update_intent` — operator-controlled fields only: `priority`, `reason`,
  `expires_ts_utc`. Cannot change `status`, `intent_type`, or scope. Only
  valid while the intent is in an open status.
- `set_expiration` / `clear_expiration` — thin named wrappers over
  `update_intent`, matching the issue's explicit "set/clear expiration"
  command.
- `cancel_intent` — explicit terminal transition to `CANCELLED`.
- `supersede_intent` — explicit terminal transition to `SUPERSEDED` on the
  old intent plus creation of its replacement, linked via
  `supersedes_intent_id` / `superseded_by_intent_id`. Supersession is one
  atomic transaction with exactly **one** versioned mutation of the old
  row — there is no separate unversioned "link" update. Step order:
  (1) authorize + validate the old intent is open; (2) validate no
  conflicting open replacement scope exists; (3) create the replacement
  intent (`supersedes_intent_id` set at creation); (4) a single guarded
  `UPDATE` on the old row setting `status=SUPERSEDED`,
  `superseded_by_intent_id=<replacement id>`, `updated_by_*`,
  `updated_ts_utc`, and `version = old_version + 1` together; (5) the old
  intent's `SUPERSEDED` revision is written *after* that update, so the
  revision snapshot itself already carries the replacement lineage. A
  version conflict (`OptimisticConcurrencyConflict`) or a duplicate
  replacement scope (`DuplicateActiveIntent`) at any step rolls back the
  entire transaction — no replacement row and no revision row survive a
  failed supersession. See
  `test_supersede_optimistic_concurrency_conflict_rolls_back_everything` and
  `test_supersede_duplicate_replacement_conflict_rolls_back_everything`.
- `expire_due_intents` — explicit, account-scoped wall-clock maintenance
  command; transitions open intents whose `expires_ts_utc` has passed to
  `EXPIRED`. Not a background job in Phase 1 — callers invoke it explicitly.

Reads:

- `read_current_intents` — authorized current-state read (`OPEN_STATUSES`
  only, see above), optionally filtered by `canonical_market` /
  `intent_type`, always scoped to one authorized `trading_account_id`.
- `read_intent_by_id` — authorized single-intent lookup by ID, any status
  (open or terminal).
- `read_revision_history` — authorized append-only history read for one
  `operator_intent_id`, covering the full lifecycle including terminal
  events.

Every command commits on success and rolls back on any failure or
exception; callers never commit/rollback the connection they pass in
(`conn_factory`), mirroring the transaction-ownership convention in
`src.account_provisioning.account_provisioning_service_v1`.

## Wallet-balance independence

Operator intent has no coupling to wallet/balance state anywhere in this
package — no wallet table, column, or call exists in
`src/operator_intent/*`. A wallet balance reaching zero cannot implicitly
remove or alter an intent, because nothing here reads wallet balance in the
first place. See `test_wallet_balance_reaching_zero_never_implicitly_removes_intent`.

## Deferred to later #254 phases

- `decision_gate` reading/consuming operator intent for permission decisions.
- `execution_planner` consuming operator intent for ladder preview
  construction.
- Executor/order-handling integration.
- Profit Plan UI write controls that call this command boundary.
- Any simulated transition between open lifecycle states driven by market or
  decision logic.

## Tests

`tests/test_operator_intent_phase1_v1.py` covers: multi-user isolation,
multi-account isolation, multi-venue scope, unauthorized access (both
missing profile access and missing account link), profile-slug-is-not-a-key,
same-user-different-authorized-profiles preserving distinct profile audit
context, canonical identity validation (venue, market, intent type,
unresolved account), duplicate active intent, contradictory intent types,
optimistic concurrency conflict, cancellation (including double-cancel
rejection and scope reopening), expiration (including scope reopening),
set/clear expiration, supersession lineage and append-only history
(including the exactly-once version increment on the old row and the
replacement lineage embedded in the revision snapshot itself), supersession
rollback atomicity under both optimistic-concurrency conflict and duplicate
replacement conflict, dedicated cancelled/expired/superseded-disappear-from-
current-intents cases, full terminal lifecycle retained in revision history,
unauthorized history read, wallet-zero independence, and the forbidden-import
guards (no
`decision_gate`/`execution_planner`/`executor`/`broker` import from this
package; no `operator_intent` import from `selection_engine`, enforced both
here and in `tests/test_manual_execution_p0_architecture_boundaries_v1.py::TestSelectionEngineNeverImportsOperatorIntent`).
