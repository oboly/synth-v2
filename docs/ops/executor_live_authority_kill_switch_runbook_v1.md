# Executor LIVE authority / kill-switch runbook v1

Status: canonical operator runbook.

Issue: #512 (pre-activation LIVE acceptance). This runbook documents
inspection, engage, disengage, verification, and rollback for the global
executor kill switch and the finite executor LIVE authority grant. It grants
nothing by itself. Running the read-only inspection commands below is always
safe; the engage/disengage commands mutate production state and must only be
run with explicit human authorization for the exact host named in the
authorization.

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```

## Scope and ownership

- Host: `gurkdb` (the only host with the `synth` production database).
- Database: `synth`, tables `executor_kill_switch_event`,
  `executor_live_authority_grant`, `executor_live_authority_revocation`.
- Code: `src/executor/execution_kill_switch_v1.py`,
  `src/executor/execution_live_authority_v1.py`.
- All three tables are append-only. `UPDATE`/`DELETE` are rejected at the DB
  layer by immutability triggers (`trg_ekse_*`, `trg_elag_*`, `trg_elar_*`).
  State changes are always new rows, never edits.
- This runbook does not cover credential provisioning, `live_trading_enabled`,
  or automatic-BUY decision-gate permission. Those are separate, independently
  authorized controls; disengaging the kill switch and holding a valid LIVE
  authority grant are necessary but not sufficient for an order to be placed.

## Global effect of the kill switch

`execution_kill_switch_v1.ExecutionKillSwitchRepositoryV1.is_engaged()` is the
single global switch consulted by `require_execution_live_authority_v1` before
any LIVE authority resolution. When the latest event's `state` is `ENGAGED`,
every LIVE authority lookup fails closed with
`EXECUTION_LIVE_AUTHORITY_KILL_SWITCH_ENGAGED`, regardless of any grant that
exists. When no event has ever been recorded, the switch is treated as
disengaged (there is no "unknown but safe" state once any operator has ever
engaged it — see Verification below for how to confirm the current state
before relying on it).

## 1. Inspect current switch state (read-only, always safe)

Run on `gurkdb`, from the repository root, with the production `.env` in
place:

```bash
python3 - <<'PY'
from src.executor.execution_kill_switch_v1 import ExecutionKillSwitchRepositoryV1
event = ExecutionKillSwitchRepositoryV1().latest_event()
print("latest_event:", event)
print("is_engaged:", ExecutionKillSwitchRepositoryV1().is_engaged())
PY
```

Equivalent read-only SQL (for an operator without a Python shell):

```sql
SELECT * FROM executor_kill_switch_event
ORDER BY executor_kill_switch_event_id DESC LIMIT 1;
```

If no row is returned, the switch has never been touched and resolves as
disengaged. Before any LIVE authorization step, an operator must explicitly
confirm this output, not assume it.

## 2. Engage the kill switch

Only ever required before any LIVE authorization step, during an incident, or
before rollback/disable. Requires an explicit actor and reason; both are
mandatory non-empty text and are permanently recorded.

```bash
python3 - <<'PY'
from src.executor.execution_kill_switch_v1 import ExecutionKillSwitchRepositoryV1, KILL_SWITCH_ENGAGED
event = ExecutionKillSwitchRepositoryV1().append_event(
    state=KILL_SWITCH_ENGAGED,
    actor="<your-name-or-role>",
    reason="<explicit reason, e.g. pre-activation safety hold for issue #512>",
)
print(event)
PY
```

## 3. Prove the engaged switch blocks LIVE authority

After engaging, prove the block deterministically before relying on it. This
call makes no broker/private request; it only resolves DB state and always
denies before evaluating any grant:

```bash
python3 - <<'PY'
from datetime import datetime, timezone
from src.executor.execution_live_authority_v1 import (
    ExecutionLiveAuthorityDeniedError,
    require_execution_live_authority_v1,
)
try:
    require_execution_live_authority_v1(
        trading_account_id=1,
        venue="bitvavo",
        side="BUY",
        market="BTC-EUR",
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
        as_of_ts_utc=datetime.now(timezone.utc),
    )
    print("UNEXPECTED: authority resolved despite engaged switch")
except ExecutionLiveAuthorityDeniedError as exc:
    print("EXPECTED_DENY:", exc)
PY
```

Expected output is `EXPECTED_DENY: EXECUTION_LIVE_AUTHORITY_KILL_SWITCH_ENGAGED`
(the exact `trading_account_id`/`market` arguments above do not need to match
any real grant -- the kill switch denies before any grant is even looked up).

## 4. Disengage (explicit authorization only)

Never run this as a default or routine step. Disengaging removes the global
block; it does not by itself grant any LIVE authority (a grant must separately
exist, be effective, and match exactly), but it is a necessary precondition
for a matching grant to ever resolve.

```bash
python3 - <<'PY'
from src.executor.execution_kill_switch_v1 import ExecutionKillSwitchRepositoryV1, KILL_SWITCH_DISENGAGED
event = ExecutionKillSwitchRepositoryV1().append_event(
    state=KILL_SWITCH_DISENGAGED,
    actor="<your-name-or-role>",
    reason="<explicit authorization reference, e.g. approved production LIVE acceptance for issue #NNN>",
)
print(event)
PY
```

Re-run step 1 immediately after to confirm the latest event now shows
`DISENGAGED`.

## 5. Inspect current LIVE authority grants (read-only)

```sql
SELECT g.*, r.revoked_ts_utc, r.revoked_by, r.revocation_reason
FROM executor_live_authority_grant g
LEFT JOIN executor_live_authority_revocation r
  ON r.executor_live_authority_grant_id = g.executor_live_authority_grant_id
ORDER BY g.executor_live_authority_grant_id DESC;
```

An empty result means no grant has ever been created -- this is the expected
state at the end of Issue #512; `require_execution_live_authority_v1` fails
closed with `EXECUTION_LIVE_AUTHORITY_NOT_GRANTED` for every request.

## 6. Revoke a LIVE authority grant

Only ever performed under separate explicit authorization, and only for a
grant that already exists. Revocation is immediate and immutable; a grant can
be revoked at most once (`uq_elar_one_per_grant`).

```bash
python3 - <<'PY'
from src.executor.execution_live_authority_v1 import ExecutionLiveAuthorityRepositoryV1
revocation = ExecutionLiveAuthorityRepositoryV1().revoke(
    grant_id=<exact_grant_id>,
    revoked_by="<your-name-or-role>",
    revocation_reason="<explicit reason>",
)
print(revocation)
PY
```

A revoked grant is immediately no longer effective:
`_EFFECTIVE_SELECT` excludes any grant with a revocation whose
`revoked_ts_utc` is at or before the resolution timestamp, independent of the
grant's own `effective_until_ts_utc`.

## 7. Emergency shutdown path

In order of speed and blast radius, narrowest first:

1. **Engage the kill switch** (step 2 above). This is the fastest global stop
   and requires no service restart; every LIVE authority resolution across
   every account/market/side fails closed immediately.
2. **Revoke the specific grant** (step 6) if the concern is scoped to one
   account/market/side and other LIVE activity must continue.
3. **Stop/disable the runtime service**, if installed and running:
   ```bash
   sudo systemctl disable --now synth-shared-executor-runtime.timer
   sudo systemctl stop synth-shared-executor-runtime.service
   systemctl is-enabled synth-shared-executor-runtime.timer synth-shared-executor-runtime.service
   systemctl is-active synth-shared-executor-runtime.timer synth-shared-executor-runtime.service
   ```
   Confirm both report `disabled`/`inactive`. Do not delete or rearm any
   persisted handoff/leg; let any lease expire and rely on normal
   reconciliation (see `docs/ops/shared_executor_runtime_v1.md`).
4. Set `SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED` and
   `SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED` in the host environment file if
   they were ever set otherwise, and restart nothing until reviewed.

The kill switch (step 1) is the correct first action in every incident: it
requires no host access beyond DB credentials already used for read-only
reporting, and it blocks every account/market/side at once.

## 8. Which host/runtime/account is affected

- This runbook affects exactly the `synth` production database on `gurkdb`.
  There is no per-host kill switch; it is a single global row set.
- A LIVE authority grant is scoped to an exact
  (`trading_account_id`, `venue`, `side`, `market` or wildcard,
  `executor_identity`, `runtime_owner`) tuple (step 5's query shows every
  field). Revoking or inspecting a grant always requires reading the exact
  row first -- never infer scope from memory or from this document.
- `executor_identity` for the shared executor is exactly `shared-executor-v1`;
  `runtime_owner` for the reviewed candidate deployment is exactly `gurkdb`.
  A grant for any other `executor_identity`/`runtime_owner` does not apply to
  this runtime.
