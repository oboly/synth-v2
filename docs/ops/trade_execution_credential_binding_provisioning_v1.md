# TRADE_EXECUTION credential-binding provisioning v1

Status: **repository code only**. This change provisions no production row.
No shared-executor binding has been created by this change; the manual
binding (`executor_credential_binding_id=2`) is untouched.

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

## Module

```text
src/account_provisioning/trade_execution_provisioning_v1.py
src/account_provisioning/run_provision_trade_execution_credential_v1.py
```

Provisions a `trading_account_credential` (`permission_scope=TRADE_EXECUTION`)
plus one `executor_credential_binding` row. It has no broker-client imports
and never decrypts a credential; see
`test_provisioning_path_has_no_broker_import_or_live_gate_mutation` in
`tests/test_trade_execution_provisioning_v1.py`.

## Credential vs. binding: two separate concerns

One `trading_account_credential` (TRADE_EXECUTION scope, per
`trading_account_id` + `venue`) may back **multiple** `executor_credential_binding`
rows -- one per distinct `(executor_identity, runtime_owner)` tuple. This is
the schema's actual grain, per
`db/migrations/20260812_manual_execution_executor_handoff_v1.sql`:

```text
UNIQUE KEY uq_ecb_credential_identity
    (trading_account_credential_id, executor_identity, runtime_owner)
UNIQUE KEY uq_ecb_active_identity_scope
    (trading_account_id, venue, executor_identity, runtime_owner, active_binding_scope)
```

Table comment: "one TRADE_EXECUTION credential per explicit executor identity
+ runtime owner." Provisioning a second executor's binding therefore never
creates a second credential -- it looks up the existing ACTIVE credential and
adds an additional binding row against it.

## Binding lookup/persistence is tuple-scoped

`TradeExecutionProvisioningRepository.find_active_binding` and
`insert_binding` are scoped by the full identity tuple: `trading_account_id`,
`venue`, `permission_scope`, `executor_identity`, `runtime_owner`,
`binding_status='ACTIVE'`. Prior to this change the lookup was scoped only by
`trading_account_id` + `venue` + `permission_scope`, which meant a second
legitimate ACTIVE binding for the same account/venue (a different executor)
would make the lookup return two rows and fail closed with
`AMBIGUOUS_EXACT_IDENTITY` even for an honest, correctly-scoped call. The
tuple-scoped lookup fixes this: resolving one executor's binding never
observes another executor's binding for the same account/venue/credential.

## Canonical identity/owner tuples

Only reviewed tuples are accepted --
`trade_execution_provisioning_v1.SUPPORTED_EXECUTOR_BINDING_TUPLES`:

| Role | executor_identity | runtime_owner | Identity module |
| --- | --- | --- | --- |
| Manual execution | `manual_execution_bitvavo_v1` | `odroid` | `src/executor/manual_execution_identity_v1.py` |
| Shared executor | `shared-executor-v1` | `gurkdb` | `src/executor/shared_executor_identity_v1.py` |

`provision_trade_execution_credential(...)` and `readiness_report(...)` both
default `executor_identity`/`runtime_owner` to the manual tuple for backward
compatibility, and both raise `UNSUPPORTED_EXECUTOR_BINDING_TUPLE` for any
pair not in the supported set -- there is no fallback to the manual identity
for an unrecognized pair. Adding a future executor requires a reviewed
identity module (mirroring the two above) plus an explicit addition to
`SUPPORTED_EXECUTOR_BINDING_TUPLES`, not an arbitrary caller-supplied string.

The CLI (`run_provision_trade_execution_credential_v1.py`) exposes
`--executor-identity`/`--runtime-owner` (defaulting to the manual tuple) and
validates the pair against the same supported set before doing anything else.

## Manual vs. shared-executor binding roles

- **Manual binding** (`manual_execution_bitvavo_v1` / `odroid`,
  `executor_credential_binding_id=2` for `trading_account_id=5` at the time
  of writing): backs the existing, currently-deployed manual-execution
  runtime. It is provisioned by the CLI's default path and is unaffected by
  this change.
- **Shared-executor binding** (`shared-executor-v1` / `gurkdb`): required
  before `SHARED_EXECUTOR_RUNTIME` (see
  `deploy/ownership/account_runtime_capability_ownership_v1.json`,
  `docs/ops/shared_executor_runtime_v1.md`) can resolve a credential scope at
  all -- `src/executor/execution_credential_scope_v1.py` denies by default
  when no exact `(executor_identity, runtime_owner)` binding exists. This
  binding does not exist in production as of this change; provisioning it is
  a separately authorized deployment action, not performed here.

Provisioning one tuple never mutates, revokes, or replaces the other tuple's
binding row.

## Idempotency

- Exact active tuple already exists with matching credential/identity/owner
  -> resolved, not re-inserted (`created_binding=False`).
- Same credential, a different legitimate tuple -> a new binding row is
  inserted; the credential is reused, not duplicated.
- A found row whose own identity fields don't match the requested tuple
  (data-integrity anomaly) -> fails closed with
  `ACTIVE_EXECUTOR_CREDENTIAL_BINDING_CONFLICT`.
- An unsupported `(executor_identity, runtime_owner)` pair -> fails closed
  with `UNSUPPORTED_EXECUTOR_BINDING_TUPLE` before any DB write.

## Controller readiness must target the intended executor tuple

`src/ops/sell_live_activation_controller_v1.py`'s `CREDENTIAL_BINDING_READY`
phase resolves the binding for the canonical shared-executor tuple
(`SHARED_EXECUTOR_IDENTITY` / `SHARED_EXECUTOR_RUNTIME_OWNER`) when checking
SELL LIVE readiness for the shared-executor runtime -- see
`docs/ops/sell_live_activation_controller_v1.md`. A controller run against the
manual tuple only proves manual-execution readiness; it is not evidence that
the shared-executor binding exists or is ready. Operators must run the
controller against whichever executor tuple is actually intended to perform
LIVE execution, and must not read a PASSED result for one tuple as readiness
for the other.
