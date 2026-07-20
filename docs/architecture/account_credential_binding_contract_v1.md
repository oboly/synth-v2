# Account credential binding contract v1

Status: canonical

## Purpose

Synth account runtime must bind an account to credentials deterministically:

```text
trading_account_id
+ venue
+ required_permission_scope
-> exactly one ACTIVE credential profile
```

Account selection does not imply credential selection. Credential resolution occurs
only after exact account identity is known.

## Layer ownership

- `selection_engine`: market-only and account-agnostic; no account rows, credentials, balances, orders, or broker state.
- `decision_gate`: account-aware permission and risk layer; may require credential availability metadata, but must not decrypt credentials.
- `execution_planner`: execution intent only after permission; must not load credentials or call brokers.
- `executor/agents`: broker/order handling only; the only future layer allowed to use execution credentials for broker writes.
- account runtime/infrastructure: resolves private-read credential profiles for account snapshots and provisioning.

Credential resolution is not owned by selection, planning, or dashboard rendering.

## Canonical non-secret fields

The binding profile must represent:

```text
trading_account_id
account_code
venue
trading_account_credential_id
credential_source
credential_status
permission_scope
allowed_private_read
allowed_order_write
allowed_withdrawal
credential_fingerprint
key_version
validation_state
validated_ts_utc
last_validation_error_code
```

`trading_account_credential_id` is the credential profile identifier for v1.

## Credential source policy

Canonical production source:

```text
db_encrypted
```

Deprecated migration-only source:

```text
legacy_profile_env_deprecated
```

The deprecated source must be explicitly selected for migration only. It is never
the default, never an implicit fallback, and never production-authorized without
an explicit account binding.

Repository-global `.env` credentials are not a valid multi-account binding.
Private clients require an explicit resolved credential profile.

## Permission scopes

```text
READ_ONLY_PRIVATE
TRADE_EXECUTION
```

`READ_ONLY_PRIVATE` may allow private account reads. It must not allow order
writes.

`TRADE_EXECUTION` is reserved for future executor-only broker writes after
decision-gate permission. PR A defines metadata only; it does not authorize
runtime write behavior.

`allowed_withdrawal` must always be false. Synth does not require or accept
withdrawal-capable credentials.

## Secret storage boundary

Allowed in database:

```text
encrypted credential envelope
non-secret credential_fingerprint
credential_source
permission_scope
capability flags
validation_state
validated_ts_utc
last_validation_error_code
key_version
```

Forbidden in database, repository, docs, logs, and rendered output:

```text
plaintext API key
plaintext API secret
master decryption material
secret values
```

Master decryption material remains in a host-local EnvironmentFile outside the
repository.

## Fail-closed rules

Runtime/repository validation must reject:

- no credential binding
- multiple active credentials matching account, venue, and required scope
- credential venue mismatch
- disabled trading account
- unknown credential status
- unknown credential source
- unknown permission scope
- missing required private-read capability
- order-write capability in read-only context
- withdrawal capability
- global `.env` fallback requirement
- unvalidated credential when validation is required

## Database invariants

Migration:

```text
db/migrations/20260721_account_credential_binding_contract_v1.sql
```

Adds only non-secret columns to `trading_account_credential`:

```text
credential_source
permission_scope
allowed_private_read
allowed_order_write
allowed_withdrawal
last_validation_error_code
active_permission_scope
```

The generated `active_permission_scope` column backs a unique index enforcing
one active credential per `(trading_account_id, venue, permission_scope)` while
preserving historical revoked/rotated/invalid rows.

## PR A boundary

PR A is schema/contract only:

```text
no runtime credential resolution change
no BitvavoClient behavior change
no private API caller change
no host mutation
no API call
no production authorization
```

Follow-up PR B must wire private runtimes to this contract and remove legacy
global credential fallback from runtime behavior.
