# LIVE execution `trading_account` provisioning (Issue #551 follow-up)

Status: **repository code only, not applied to production**. No production
`trading_account` row has been created by this change.

## Background

The SELL LIVE readiness audit found that no canonical MariaDB service
creates an `account_mode='live'` trading account. `trading_account_id` 2 and
3 (`bitvavo_synth_read`, `bitvavo_joost_read`) are canonical `live_readonly`
snapshot-source identities (see
`docs/ops/trading_account_live_readonly_mode_migration_v1.md`,
`docs/architecture/account_mode_contract_v1.md`) and must never be reused or
mutated for execution -- `account_mode` is a whole-row, single-valued field,
and `EXECUTION_ELIGIBLE_ACCOUNT_MODES = {"live"}` in
`src/account/account_mode_contract_v1.py` excludes `live_readonly`
permanently.

The only pre-existing trading-account-creation code path,
`src/account_provisioning/account_provisioning_service_v1.py` +
`account_repository_v1.py`, is a **SQLite-backed self-service website
onboarding flow** hardcoded to `account_mode='paper'`, backed by a different
database entirely. It is not reused here.

`src/account_provisioning/trade_execution_provisioning_v1.py` (credential +
`executor_credential_binding` provisioning) already assumes the target
`trading_account` row exists. This document's module is the missing step
before that one.

## Scope

This module provisions **the `trading_account` row only**:

```text
src/account_provisioning/live_execution_trading_account_provisioning_v1.py
src/account_provisioning/run_provision_live_execution_trading_account_v1.py
```

It does not, and must never:

- provision a credential or `executor_credential_binding`
  (`trade_execution_provisioning_v1.py`'s responsibility, run separately
  afterward)
- grant decision-gate LIVE permission
- change kill-switch state
- activate a runtime capability
- call any broker endpoint
- submit an order
- mutate `trading_account_id` 2 or 3, or any existing row, in any way

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

## Canonical target row

```text
account_code='bitvavo_joost_live'
venue='bitvavo'
account_mode='live'
enabled=1
live_trading_enabled=1
description='Bitvavo execution-capable LIVE trading identity paired with read-only snapshot source trading_account_id=3'
```

`account_mode='live'` + `live_trading_enabled=1` is exactly the pairing
required by
`src.account.account_mode_contract_v1.is_account_mode_live_trading_enabled_consistent`;
the module asserts this at import time rather than merely assuming it.

Designed for future multiple execution accounts: `account_code` and
`--source-trading-account-id` are both caller-supplied, not hardcoded, so a
second execution account (e.g. paired with `trading_account_id=2`) can be
provisioned with the same module under a different `account_code`.

## Provisioning contract

1. **Source validation** (read-only, never mutates the source row):
   `--source-trading-account-id` must resolve to an existing row with
   `venue` matching `--venue`, `account_mode='live_readonly'`, and
   `enabled=1`. Any mismatch fails closed
   (`SOURCE_ACCOUNT_NOT_FOUND` / `SOURCE_ACCOUNT_VENUE_MISMATCH` /
   `SOURCE_ACCOUNT_NOT_LIVE_READONLY` / `SOURCE_ACCOUNT_DISABLED`).
2. **Lookup by `account_code`.**
3. **Absent** -> `--apply` inserts the exact canonical row in one
   transaction, then commits. `--check` reports `WOULD_CREATE` and performs
   no `INSERT`.
4. **Present, exact protected-field match** -> `ALREADY_PROVISIONED`, no
   mutation, in both `--check` and `--apply` modes. This is the idempotent
   retry path.
5. **Present, any protected field differs** -> fails closed with
   `ACCOUNT_IDENTITY_CONFLICT` naming the mismatched fields, in both
   `--check` and `--apply` modes. **The existing row is never
   auto-corrected.**

Protected fields: `venue`, `account_mode`, `enabled`, `live_trading_enabled`,
`description`.

The repository (`LiveExecutionTradingAccountProvisioningRepository`) issues
only `SELECT` (source validation, existing-row lookup) and `INSERT`
(new-row creation) against `trading_account` -- no `UPDATE`/`DELETE`
statement exists anywhere in the module.

## CLI

```bash
# Read-only: resolve and report, never mutate.
python -m src.account_provisioning.run_provision_live_execution_trading_account_v1 \
  --account-code bitvavo_joost_live \
  --source-trading-account-id 3 \
  --check

# Explicit mutation: insert the row only if absent; idempotent on retry.
python -m src.account_provisioning.run_provision_live_execution_trading_account_v1 \
  --account-code bitvavo_joost_live \
  --source-trading-account-id 3 \
  --apply
```

`--check` and `--apply` are mutually exclusive and one is required. Output
is machine-readable `KEY=VALUE` lines (`STATUS`, `TRADING_ACCOUNT_ID`,
`CREATED`, safety markers); no secret is read, held, or printed by this
module -- it never imports credential/crypto code.

## What happens after this (not part of this change)

```text
trading_account (this module)
-> TRADE_EXECUTION credential + executor_credential_binding
   (src/account_provisioning/trade_execution_provisioning_v1.py, existing)
-> decision_gate LIVE permission grant
   (src/decision_gate/automatic_exit_live_permission_repository_v1.py, existing)
-> kill-switch known-safe (DISENGAGED) state
   (src/executor/execution_kill_switch_v1.py, existing)
-> runtime capability activation
   (deploy/ownership/account_runtime_capability_ownership_v1.json, ops action)
-> python -m src.ops.sell_live_activation_controller_v1 --check
-> LIVE_AUTHORIZATION_REQUIRED (separate, explicit human authorization)
```

Each step above is owned by its existing module/contract; none is created
or modified by this change.
