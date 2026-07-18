# Native SHORT Scope Administration Contract V1

## Status and boundary

This document defines the repository contract and schema ownership established
by the first Native SHORT scope-administration implementation boundary. It does
not implement or authorize an administration transaction.

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
- `ADOPT_LEGACY_SCOPE`, `PROMOTE_SCOPE`, and `REMOVE_SCOPE` as distinct operations;
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

No historical operation rows are inserted. Administrative provenance is never
inferred from runtime writer provenance.

## Support history

`native_short_scope_support_event_v1` remains append-only historical support
evidence. New nullable `scope_admin_operation_id` and `support_generation` fields
are either both NULL for legacy evidence or both present with a positive
generation for attributable administration evidence.

The database permits at most one attributable support event per operation and
at most one event per exact scope and positive generation. Multiple legacy NULL-
generation events remain valid and unchanged.

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
transaction locks; no trigger is introduced.

The former scope-plus-cadence-version uniqueness is replaced by scope, cadence
profile, and support generation uniqueness. This permits later activation of the
same accepted profile in a new generation without reopening historical rows.

## Forward-only and deferred work

The migration is forward-only, non-destructive, and performs no historical
backfill. It fails before persistent DDL if current cadence rows contain multiple
active rows for one exact scope, contradictory active/effective state, or
overlapping effective windows. It does not repair those conditions.

The following remain explicitly deferred:

- repository transactions for adoption, promotion, and removal;
- first-creation serialization and transaction locking;
- writer selection and commit-time revalidation using scope ID, support state,
  support generation, and cadence config ID;
- narrow deterministic projection cleanup after coherent withdrawal;
- any scope mutation or operational acceptance.

No persistent writer-fence table is part of this contract.
