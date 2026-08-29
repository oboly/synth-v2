# Bind an existing TRADE_EXECUTION credential v1

This operator path binds an **existing** credential to a reviewed executor tuple. It never accepts broker API key/secret input, never decrypts or rotates credentials, and never performs broker calls or order operations.

## Safety contract

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
withdrawal_calls=0
credential_mutation=0
decision_gate=none
execution_planner=none
executor=none
```

## Eligibility

The exact credential id must belong to the requested trading account and satisfy:

- `permission_scope=TRADE_EXECUTION`
- `credential_status=ACTIVE`
- `credential_source=db_encrypted`
- `validation_state=VALID_TRADE_EXECUTION`
- non-null `validated_ts_utc`
- `allowed_private_read=1`
- `allowed_order_write=1`
- `allowed_withdrawal=0`
- account/venue cross-validation against `trading_account`

The historical manual binding is never mutated or revoked.

## Read-only check

```bash
python -m src.account_provisioning.run_bind_existing_trade_execution_credential_v1 \
  --trading-account-id 5 \
  --trading-account-credential-id 5 \
  --executor-identity shared-executor-v1 \
  --runtime-owner gurkdb \
  --check
```

`--check` performs no insert and rolls back the read transaction. Omitting both mode flags is intentionally equivalent to the safe `--check` mode for backward-compatible operator safety.

A missing eligible binding reports `BINDING_EXISTS=0` and `CREATED_BINDING=0`. An existing exact ACTIVE binding reports its id and remains unchanged.

## Explicit apply

```bash
python -m src.account_provisioning.run_bind_existing_trade_execution_credential_v1 \
  --trading-account-id 5 \
  --trading-account-credential-id 5 \
  --executor-identity shared-executor-v1 \
  --runtime-owner gurkdb \
  --apply
```

`--apply` is the only mode allowed to insert a missing `executor_credential_binding`. It is idempotent when the exact ACTIVE tuple already exists. It never creates or updates the credential row and never touches a different tuple such as `manual_execution_bitvavo_v1 / odroid`.

Production `--apply` remains a separately authorized mutation.