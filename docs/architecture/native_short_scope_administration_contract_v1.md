# Native SHORT Scope Administration Contract V1

## Status and boundary

This document defines the repository contract and schema ownership for Native
SHORT scope administration. The pure request contract, the forward-only schema,
and the deterministic repository transactions for `ADOPT_LEGACY_SCOPE`,
`PROMOTE_SCOPE`, `REMOVE_SCOPE`, and automatic `AUTO_ONBOARD_SCOPE` are
implemented in the repository. This
document authorizes no production database mutation, deployment, migration
application, host acceptance, or new production scope.

Native SHORT scope administration belongs to `src/market_data/` and remains
market-only and account-agnostic. It has no account, wallet, private-broker,
selection, decision-gate, execution-planner, executor, order, or reporting-
mutation responsibility.

## Canonical identity and current authority

`native_short_map_scope_v1` is the sole canonical Native SHORT scope identity:

```text
(venue, symbol, quote_currency, fib_trading_horizon,
 primary_interval, supporting_interval)
= (bitvavo, <SYMBOL>, EUR, SHORT, 4h, 1h)
```

The same row owns current `scope_support_state` and the nullable
`support_generation` administration epoch. There is no duplicate administration
key table and no `last_scope_admin_operation_id` cache. An attributable operation
is derived through the support event for `(scope key, support_generation)`.

`support_generation=NULL` on a scope means `LEGACY_UNADOPTED`. Existing rows are
left NULL. A future accepted administration transaction must assign a positive
generation; this migration never does so.

## Pure request contract

`src/market_data/native_short_scope_administration_v1.py` owns deterministic,
database-free values for:

- exact canonical scope-key normalization;
- `ADOPT_LEGACY_SCOPE`, `PROMOTE_SCOPE`, `REMOVE_SCOPE`, and
  `AUTO_ONBOARD_SCOPE` as distinct operations;
- explicit actor and trigger provenance, including explicit test-only values;
- closed result classes and result codes;
- canonical JSON metadata and the SHA-256 digest of the complete immutable
  request identity.

No actor, operation UUID, reason, trigger, repository SHA, or schema version has
an implicit default.

## Administrative operation ledger

`native_short_scope_admin_operation_v1` is the only new table. It owns operation
UUID uniqueness, immutable normalized scope snapshot, typed provenance, request
digest, timestamps, support generation before/after, and terminal result. It is
the sole idempotency authority.

The table is not a second scope registry and has no mutable scope authority. The
scope snapshot makes an operation auditable even for first creation and does not
replace the unique canonical identity in `native_short_map_scope_v1`.

The immutable scope snapshot is also a scope-bound foreign-key target. A
composite candidate key `(scope_admin_operation_id, venue, symbol,
quote_currency, fib_trading_horizon, primary_interval, supporting_interval)`
lets support and cadence rows reference an operation *together with* its exact
scope. This makes cross-scope attribution structurally impossible at the
database layer — a support or cadence row for one scope cannot reference an
operation recorded for a different scope — rather than relying on a future
application convention. Legacy rows keep a NULL operation id, so the composite
foreign key is simply not enforced for them (MariaDB `MATCH SIMPLE`).

No historical operation rows are inserted. Administrative provenance is never
inferred from runtime writer provenance.

## Support history

`native_short_scope_support_event_v1` remains append-only historical support
evidence. New nullable `scope_admin_operation_id` and `support_generation` fields
are either both NULL for legacy evidence or both present with a positive
generation for attributable administration evidence.

The database permits at most one attributable support event per operation and
at most one event per exact scope and positive generation. Multiple legacy NULL-
generation events remain valid and unchanged. Each attributable event's
composite foreign key binds it to its operation's exact scope snapshot.

## Cadence authority and active-row invariant

`native_short_scope_cadence_config_v1` remains the sole cadence authority. New
nullable activation operation, deactivation operation, and support generation
fields preserve legacy rows without attribution.

For administratively managed rows:

- activation operation and positive support generation are present together;
- an active row has no deactivation operation or effective end;
- a deactivated row has both explicit deactivation operation and effective end.

The database-generated `active_slot` is `1` when `is_active=1` and NULL
otherwise. A unique key over the exact six-part scope plus `active_slot` uses
MariaDB's unique-key NULL behavior to reject a second active row while allowing
multiple inactive historical rows. Historical effective-window non-overlap is
validated by migration preflight and must later be validated under deterministic
transaction locks; no trigger is introduced. Ongoing effective-window
non-overlap enforcement is deliberately deferred to that later locked
repository-transaction PR, not added as a trigger in this pure schema contract.

The former scope-plus-cadence-version uniqueness is replaced by scope, cadence
profile, and generation uniqueness, but on a NULL-safe generation *slot* rather
than the raw nullable `support_generation`. A stored generated
`effective_generation_slot` projects `support_generation` onto the reserved
legacy sentinel `0` when NULL (managed generations are always positive and can
never collide with it). The profile-generation unique key is enforced on that
slot, which:

- permanently forbids a second legacy/unmanaged cadence row (slot `0`) for one
  exact scope and cadence profile — restoring the invariant the dropped
  `uq_native_short_scope_cadence_config_v1_scope_version` index enforced, which a
  raw-nullable key would have silently lost (MariaDB treats NULLs as distinct);
- still permits distinct positive managed generations of the same profile;
- still rejects a duplicate managed generation of the same profile.

The migration preflight additionally fails before persistent DDL if current data
already holds duplicate legacy `(scope + cadence_contract_version)` rows.

## Implemented repository transaction boundary

`src/market_data/native_short_scope_administration_transaction_v1.py` owns the
deterministic repository transactions, and
`src/market_data/run_native_short_scope_administration_v1.py` is the thin manual
CLI. The transaction module:

- separates a pure decision function (`classify_scope_state` /
  `decide_administration`) from explicit per-branch SQL, with no generic
  administration framework;
- serializes each exact scope with one zero-wait MariaDB advisory lock derived
  from the six-part canonical scope key, plus `SELECT ... FOR UPDATE` row locks
  on the existing scope, cadence, support, and operation rows; the advisory lock
  serializes first creation when no scope row exists yet;
- treats `native_short_scope_admin_operation_v1` as the sole idempotency
  authority with no unledgered mutation path: every write-capable request —
  including a repeat removal that only clears derived residue — commits exactly
  one immutable terminal operation-ledger row atomically with its mutations, so a
  committed ledger row is always terminal. Replay of a completed `operation_uuid`
  with the identical request digest returns `OPERATION_ALREADY_COMPLETED`; a
  different digest or immutable metadata returns `OPERATION_METADATA_MISMATCH`; a
  non-terminal committed row fails closed as `COMMIT_STATUS_UNKNOWN`;
- assigns the first positive administration generation for adoption and new
  promotion, increments the generation for re-promotion after withdrawal and for
  removal, appends exactly one attributable support event per support-state
  operation, and keeps at most one active cadence row per exact scope;
- fully validates managed state before and after every mutation: for a managed
  SUPPORTED scope it proves exactly one active canonical cadence row whose
  `support_generation` equals the scope generation and whose activation operation
  is present with no deactivation/effective-end, plus exactly one operation-linked
  `SUPPORTED` support event for that generation; for a managed removed scope it
  proves zero active cadence rows, a `NOT_APPLICABLE` operation-linked support
  event for the current generation, a coherently deactivated latest managed
  cadence generation, and no cadence generation ahead of the scope generation.
  Post-mutation revalidation binds each mutated scope/cadence/support row to the
  exact new operation id and generation;
- performs, on removal, only the narrow deterministic cleanup of the current
  derived projections (`native_short_scope_status_v1` and
  `native_short_map_level_status_v1`) that would otherwise remain falsely
  actionable, using the stable `ADMIN_SCOPE_WITHDRAWN` reason code that never
  masquerades as a market-lifecycle outcome. A repeat removal whose only residue
  is such a projection performs a ledgered `ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED`
  cleanup that records `support_generation_before == support_generation_after`,
  appends no support event, and deletes no immutable map, generation, lifecycle,
  observation, run, or support history;
- materializes no map and publishes no snapshot;
- exposes an explicit `commit_state` (`NOT_ATTEMPTED` / `COMMITTED` /
  `ROLLED_BACK` / `UNKNOWN`). Failures before `conn.commit()` roll back and return
  `commit_state=ROLLED_BACK` with `persisted=false`; deadlock and lock timeout
  before commit map to their existing typed RETRYABLE codes. An exception at the
  commit boundary whose committed state cannot be proven returns
  `COMMIT_STATUS_UNKNOWN` with `commit_state=UNKNOWN` and `persisted=null` — it
  never claims rollback certainty, and a retry resolves through the operation
  ledger;
- defaults to a read-only dry run that computes the planned transition and
  expected result without any persistent write, lock acquisition, operation
  ledger row, or production mutation authorization. Write mode verifies the exact
  clean repository source identity and requires canonical
  `native_short_4h_chain` writer mutation authorization before any mutation. The
  CLI emits exactly one deterministic JSON result document on stdout (progress and
  authorization/source-identity failures included) with operational progress on
  stderr.

This transaction provides its own commit-time transaction validation only. It
does not add or perform the separate 4h map-writer commit-time fencing, which
remains the next blocker.

## Forward-only and deferred work

The migration is forward-only, non-destructive, and performs no historical
backfill. It fails before persistent DDL if current cadence rows contain multiple
active rows for one exact scope, contradictory active/effective state,
overlapping effective windows, or duplicate legacy scope-and-profile rows. It
does not repair those conditions.

The migration is single-application, matching the Native SHORT schema-family
convention: `CREATE TABLE` statements are idempotent (`IF NOT EXISTS`), while
`ALTER TABLE ADD COLUMN / ADD CONSTRAINT / DROP INDEX` statements are not
re-runnable (siblings `20260707` and `20260716` behave identically). A second
application against an already-migrated schema fails loudly (duplicate column /
duplicate key) rather than silently corrupting state; this is the intended guard
against accidental reapplication and is asserted by the migration integration
test. No migration-runner state table is introduced by this contract.

The following remain explicitly deferred:

- 4h map-writer commit-time fencing (writer selection and commit-time
  revalidation of scope ID, support state, support generation, and cadence
  config ID immediately before the bounded writer transaction commits);
- `NO_CURRENT_MAP` bootstrap semantics for a newly supported scope;
- per-symbol failure isolation across a multi-scope rollout;
- historical sequential-canary rollout administration; it has no authority
  over ongoing automatic onboarding;
- any production database mutation, migration application, host acceptance, or
  operational acceptance.

No persistent writer-fence table is part of this contract.

## Ongoing automatic onboarding (Issue #539)

`AUTO_ONBOARD_SCOPE` is the normal market-data lifecycle transition for an
unsupported Bitvavo EUR market whose canonical evidence evaluates `READY`.
It persists the same atomic scope, cadence, support-event, and operation-ledger
invariants as an administrative promotion, but requires no sequential canary,
per-symbol approval, bootstrap manifest, removal-contract evidence, or manual
`PROMOTE_SCOPE`. Historical `ADOPT_LEGACY_SCOPE`, `PROMOTE_SCOPE`, and
`REMOVE_SCOPE` tooling remains for repair/history only and has no authority
over automatic onboarding.
