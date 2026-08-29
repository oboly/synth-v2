# TRADE_EXECUTION credential validation v1

Issue #584 defines the credential-validation boundary required before an
existing Bitvavo TRADE_EXECUTION credential may satisfy shared-executor LIVE
readiness.

## Scope

This belongs to `account_provisioning`. It does not grant decision-gate
permission, executor LIVE authority, runtime activation, or broker-write
permission, and it does not create or bind a credential.

The canonical persisted success state is:

```text
VALID_TRADE_EXECUTION
```

`VALID_READ_ONLY` and `VALID_PRIVATE_READ` are not sufficient for a
TRADE_EXECUTION credential to satisfy the executor credential-scope resolver.
The successful state must also have a non-null `validated_ts_utc`.

## Static requirements

Before any private broker read is attempted, the validator requires exactly
one ACTIVE credential for `(trading_account_id, venue, TRADE_EXECUTION)` with:

- `credential_source=db_encrypted`
- `allowed_private_read=1`
- `allowed_order_write=1`
- `allowed_withdrawal=0`
- an enabled trading account
- exact account/venue/scope identity
- supported encrypted-envelope algorithm/schema/key-version metadata
- envelope account and venue matching the persisted credential
- successful decryption with the host-local credential master key
- constant-time fingerprint equality after decryption

Ambiguity or any metadata mismatch fails closed before the validator can make a
broker call.

## Broker validation

The service intentionally reuses `RealBitvavoCredentialValidator`. The probe is
read-only:

1. `get_balance()` proves API Read permission.
2. `get_open_orders()` proves API Trade permission is available to the key.

No order is placed or cancelled. No withdrawal endpoint is called. Successful
completion with both `read_balance` and `read_orders` capabilities is persisted
as `VALID_TRADE_EXECUTION`.

Definitive authentication/permission failures are persisted as
`INVALID_CREDENTIALS`. Transport, infrastructure, or missing operator private-
read permission returns `VALIDATION_UNAVAILABLE` and leaves the existing
credential state unchanged.

## Operator CLI

Metadata-only check:

```text
python -m src.account_provisioning.run_revalidate_trade_execution_credential_v1 \
  --trading-account-id <id> \
  --venue bitvavo \
  --check
```

Explicit validation operation:

```text
python -m src.account_provisioning.run_revalidate_trade_execution_credential_v1 \
  --trading-account-id <id> \
  --venue bitvavo \
  --validate
```

`--validate` requires the canonical host-local credential master key and the
existing explicit `SYNTH_BROKER_PRIVATE_READ_PERMISSION` grant used by the
Bitvavo private-read validator. It does not require or grant broker-write
permission.

## Runtime enforcement

`ExecutorCredentialScopeRepository` includes `validation_state` in the exact
binding join and denies anything except `VALID_TRADE_EXECUTION`. It separately
requires `db_encrypted`, private-read permission, order-write permission, and
withdrawal disabled.

This keeps the safety sequence explicit:

```text
credential validation
  -> canonical shared-executor binding
  -> runtime readiness
  -> separately authorized LIVE authority
```

A binding alone never upgrades an unvalidated credential into LIVE readiness.

## Safety markers

```text
broker_private_calls=0 for --check
broker_private_calls<=2 for explicit --validate
broker_writes=0
order_submission=0
live_orders=0
withdrawal_calls=0
decision_gate=none
execution_planner=none
executor=scope-read-only
```
