# TRADE_EXECUTION credential rotation v1

Issue: #589

Status: repository implementation only. No production credential has been rotated by this change.

## Purpose

Rotate the encrypted Bitvavo API key/secret for one exact existing ACTIVE `TRADE_EXECUTION` credential **in place**.

The credential row id is preserved. Existing `executor_credential_binding` rows are never inserted, updated, revoked, or rebound by this operation.

This is an `account_provisioning` concern only.

```text
selection_engine=unchanged
decision_gate=unchanged
execution_planner=unchanged
executor_order_handling=unchanged
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
withdrawal_calls=0
live_authorization=0
```

## CLI

Read-only preflight:

```bash
python -m src.account_provisioning.run_rotate_trade_execution_credential_v1 \
  --trading-account-id 5 \
  --trading-account-credential-id 5 \
  --venue bitvavo \
  --check
```

Explicit mutation:

```bash
python -m src.account_provisioning.run_rotate_trade_execution_credential_v1 \
  --trading-account-id 5 \
  --trading-account-credential-id 5 \
  --venue bitvavo \
  --apply
```

`--apply` requires `SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY` in the process environment and prompts interactively, with hidden echo, for the new Bitvavo API key and API secret. API secrets are never CLI flags.

`--check` requires neither broker secrets nor the master key and performs no write.

## Required existing metadata

The exact credential must satisfy:

- requested credential id exists
- requested account id matches
- requested venue is `bitvavo` and matches the row
- `credential_kind=API_KEY_SECRET`
- `credential_status=ACTIVE`
- `credential_source=db_encrypted`
- `permission_scope=TRADE_EXECUTION`
- `allowed_private_read=1`
- `allowed_order_write=1`
- `allowed_withdrawal=0`
- encryption algorithm is canonical `AESGCM-256`
- fingerprint and key version are present

## Mutation contract

The update is optimistic and exact. The WHERE clause repeats identity, scope, capabilities, old fingerprint, and old key version. If exactly one row is not changed, the transaction fails closed with:

`EXACT_ACTIVE_TRADE_EXECUTION_CREDENTIAL_UPDATE_REQUIRED`

A successful rotation changes only:

- `encrypted_envelope`
- `encryption_algorithm`
- `key_version`
- `credential_fingerprint`
- `validation_state` -> `UNVALIDATED`
- `validated_ts_utc` -> `NULL`
- `last_validation_error_code` -> `NULL`

It does not change the credential id, account id, venue, status, source, permission scope, capability flags, or any executor binding.

A new API key whose fingerprint matches the current API key is rejected with `NEW_CREDENTIAL_MATCHES_CURRENT_API_KEY` to prevent an ambiguous/no-op rotation.

## Required sequencing for account 5

1. Create and email-confirm the replacement Bitvavo API key.
2. Grant View + Trade; leave Withdraw disabled.
3. Run rotation `--check` on gurkdb.
4. Separately authorize and run rotation `--apply` on gurkdb.
5. Run the #584 private-read validation (`get_balance` + `get_open_orders`).
6. Require `VALID_TRADE_EXECUTION` before #583 shared-executor binding eligibility.
7. LIVE authorization remains a later, separate gate.
