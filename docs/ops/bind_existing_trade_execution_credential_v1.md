# Bind an existing TRADE_EXECUTION credential to a new executor tuple v1

Status: **repository code only**. This change provisions no production row.
No binding has been created by this change; the manual binding
(`executor_credential_binding_id=2`, `manual_execution_bitvavo_v1` / `odroid`)
is untouched.

```text
production_db_mutation=0 (in this repository-code-only change)
credential_mutation=0
live_permission_mutation=0
kill_switch_mutation=0
service_mutation=0
broker_writes=0
order_submission=0
live_activation=0
```

## Purpose

`run_provision_trade_execution_credential_v1.py` always prompts for a broker
API key/secret, even when the caller only wants to add a second executor
binding to a credential that already exists. This is the wrong tool for that
operation: it forces re-entry of secrets that must not be re-entered or
rotated.

This module is the canonical, narrow alternative: it binds an **existing**
ACTIVE `trading_account_credential` (`permission_scope=TRADE_EXECUTION`) to
one additional reviewed `(executor_identity, runtime_owner)` tuple, without
any secret input, credential mutation, decryption, or broker call.

## Module

```text
src/account_provisioning/existing_trade_execution_credential_binding_v1.py
src/account_provisioning/run_bind_existing_trade_execution_credential_v1.py
```

Safety, verified by
`test_no_broker_import_or_crypto_import` in
`tests/test_bind_existing_trade_execution_credential_v1.py`:

- no broker-client import
- no `credential_crypto_v1` import (no decryption capability at all)
- no secret CLI flags (`--api-key`, `--api-secret`)

## CLI

```bash
python -m src.account_provisioning.run_bind_existing_trade_execution_credential_v1 \
    --trading-account-id <id> \
    --trading-account-credential-id <id> \
    --executor-identity <identity> \
    --runtime-owner <owner>
```

All four flags are required. There is no `--api-key`/`--api-secret` flag and
no interactive secret prompt.

## Credential verification (fail closed)

Given `--trading-account-id` and `--trading-account-credential-id`, the
existing `trading_account_credential` row is read (metadata columns only --
never `encrypted_envelope`, `key_version`, or `credential_fingerprint`) and
must satisfy all of:

| Check | Failure code |
| --- | --- |
| row exists | `TRADE_EXECUTION_CREDENTIAL_NOT_FOUND` |
| `trading_account_id` matches the requested account | `CREDENTIAL_ACCOUNT_ID_MISMATCH` |
| `permission_scope = TRADE_EXECUTION` | `CREDENTIAL_PERMISSION_SCOPE_MISMATCH` |
| `credential_status = ACTIVE` | `CREDENTIAL_NOT_ACTIVE` |
| `allowed_order_write = 1` | `CREDENTIAL_MISSING_ORDER_WRITE_SCOPE` |
| `allowed_withdrawal = 0` | `CREDENTIAL_WITHDRAWAL_CAPABILITY_NOT_ALLOWED` |

`venue` is read from the credential row itself (not accepted from the
caller) and cross-validated against the `trading_account` table
(`TRADING_ACCOUNT_VENUE_NOT_FOUND` if the account/venue pair does not exist),
so a caller cannot steer the binding onto an unintended venue.

## Only reviewed executor tuples

Only tuples in
`trade_execution_provisioning_v1.SUPPORTED_EXECUTOR_BINDING_TUPLES` are
accepted -- the same canonical set used by
`docs/ops/trade_execution_credential_binding_provisioning_v1.md`:

| Role | executor_identity | runtime_owner |
| --- | --- | --- |
| Manual execution | `manual_execution_bitvavo_v1` | `odroid` |
| Shared executor | `shared-executor-v1` | `gurkdb` |

Both the CLI (`parse_args`) and the service function
(`bind_existing_trade_execution_credential`) reject any other pair with
`UNSUPPORTED_EXECUTOR_BINDING_TUPLE` before touching the database.

## Binding lookup/persistence is tuple-scoped and append/create-only

`find_active_binding`/`insert_binding` are scoped by the full identity tuple
(`trading_account_id`, `venue`, `permission_scope='TRADE_EXECUTION'`,
`executor_identity`, `runtime_owner`, `binding_status='ACTIVE'`), matching
the real `uq_ecb_active_identity_scope` DB constraint. The credential row is
never inserted, updated, or revoked by this module.

## Idempotency and conflict handling

- Exact tuple has no ACTIVE binding yet -> a new `executor_credential_binding`
  row is inserted (`created_binding=True`).
- Exact tuple already has an ACTIVE binding pointing at the same
  `trading_account_credential_id` -> resolved, not re-inserted
  (`created_binding=False`).
- Exact tuple already has an ACTIVE binding pointing at a **different**
  credential (data-integrity anomaly) -> fails closed with
  `ACTIVE_EXECUTOR_CREDENTIAL_BINDING_CONFLICT`; no write occurs.
- A different tuple's binding for the same account/venue/credential (e.g. the
  existing manual binding, `executor_credential_binding_id=2`) is never
  observed or touched -- see
  `test_existing_manual_binding_id_two_is_untouched` in
  `tests/test_bind_existing_trade_execution_credential_v1.py`.

## Multi-account safety

All lookups and inserts are scoped by the caller-provided
`trading_account_id`; the credential's own `trading_account_id` must match
it exactly (`CREDENTIAL_ACCOUNT_ID_MISMATCH` otherwise). Binding one
account's tuple never reads or mutates another account's rows -- see
`test_multi_account_isolation`.

## Example: `trading_account_id=5`, existing `credential_id=5`

```bash
python -m src.account_provisioning.run_bind_existing_trade_execution_credential_v1 \
    --trading-account-id 5 \
    --trading-account-credential-id 5 \
    --executor-identity shared-executor-v1 \
    --runtime-owner gurkdb
```

This adds a `shared-executor-v1` / `gurkdb` binding against the same
`credential_id=5` already backing the manual binding
(`executor_credential_binding_id=2`, `manual_execution_bitvavo_v1` /
`odroid`), without any secret re-entry, credential rotation, or mutation of
the manual binding. Running this command against production is a separately
authorized deployment action and was not performed as part of this change.
