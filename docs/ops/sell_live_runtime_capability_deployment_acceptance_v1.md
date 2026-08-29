# SELL LIVE runtime capability deployment/acceptance sequence v1 (Issue #585)

Status: ops/deploy procedure only. Nothing in this document authorizes LIVE
trading, grants execution authority, changes credential provisioning,
touches the kill switch, or performs a broker call.

```text
service_mutation=0 (by this repository's code; installation itself is a
    manual, reviewed, host-local systemd action described below)
production_db_mutation=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority_grant=0
kill_switch_mutation=0
```

## Scope

This document is the canonical operator sequence for taking
`AUTOMATIC_EXIT_POLICY_RUNTIME` and `SHARED_EXECUTOR_RUNTIME` from
"unit files exist in the repository" to "the SELL LIVE readiness
controller's `RUNTIME_READY` phase observes them as actually running,"
per the read-only systemd contract in
`src/ops/systemd_runtime_readiness_v1.py` (see
`docs/ops/sell_live_activation_controller_v1.md`'s "RUNTIME_READY" section
for the exact pass/fail conditions this sequence must satisfy).

Both capabilities are owned by `gurkdb` (`owner_host=gurkdb` in
`deploy/ownership/account_runtime_capability_ownership_v1.json`; that
registry entry is design/ownership metadata only and is never itself proof
of a running service). Run every step in this document on `gurkdb`, as the
`gurk` service user, from `/home/gurk/projects/synth-v2`.

## Canonical unit pairs

```text
deploy/systemd/synth-automatic-exit-policy-runtime.service
deploy/systemd/synth-automatic-exit-policy-runtime.timer

deploy/systemd/synth-shared-executor-runtime.service
deploy/systemd/synth-shared-executor-runtime.timer
```

Both services are `Type=oneshot`, invoked periodically by their timer.
`RUNTIME_READY` never checks the service's own `ActiveState` -- idle/dead
between firings is the expected, healthy state. Only the timer's
`enabled`+`active` state is authoritative.

`synth-shared-executor-runtime.service` additionally requires
`/etc/synth/shared-executor-runtime-v1.env` to exist
(`ConditionPathExists=`) before it will run; see
`docs/ops/shared_executor_runtime_v1.md` for that file's required, non-secret
contents. As of the 2026-08-29 host audit this file is already present on
`gurkdb`.

## 1. Install the reviewed unit files

Diff the repository's unit file against whatever may already be installed,
then copy it verbatim -- never hand-edit an installed unit out of band from
this repository:

```bash
diff -u /etc/systemd/system/synth-automatic-exit-policy-runtime.service \
  deploy/systemd/synth-automatic-exit-policy-runtime.service || true
sudo cp deploy/systemd/synth-automatic-exit-policy-runtime.service /etc/systemd/system/
sudo cp deploy/systemd/synth-automatic-exit-policy-runtime.timer /etc/systemd/system/

diff -u /etc/systemd/system/synth-shared-executor-runtime.service \
  deploy/systemd/synth-shared-executor-runtime.service || true
sudo cp deploy/systemd/synth-shared-executor-runtime.service /etc/systemd/system/
sudo cp deploy/systemd/synth-shared-executor-runtime.timer /etc/systemd/system/
```

Verify each unit parses before reloading:

```bash
systemd-analyze verify /etc/systemd/system/synth-automatic-exit-policy-runtime.service
systemd-analyze verify /etc/systemd/system/synth-automatic-exit-policy-runtime.timer
systemd-analyze verify /etc/systemd/system/synth-shared-executor-runtime.service
systemd-analyze verify /etc/systemd/system/synth-shared-executor-runtime.timer
```

## 2. daemon-reload

```bash
sudo systemctl daemon-reload
```

This is required before systemd will `show` the newly-installed unit's
`LoadState=loaded`; without it `RUNTIME_READY` correctly reports
`SERVICE_UNIT_NOT_FOUND` / `TIMER_UNIT_NOT_FOUND` even though the file exists
on disk.

## 3. Keep both timers disabled initially

Do not enable or start anything yet. Confirm the disabled/inactive baseline:

```bash
systemctl show synth-automatic-exit-policy-runtime.timer --no-pager \
  --property=LoadState,ActiveState,UnitFileState,FragmentPath
systemctl show synth-shared-executor-runtime.timer --no-pager \
  --property=LoadState,ActiveState,UnitFileState,FragmentPath
```

Expect `LoadState=loaded`, `UnitFileState=disabled`, `ActiveState=inactive`
for both. At this point `RUNTIME_READY` still reports `TIMER_NOT_ENABLED`
for both capabilities -- this is correct and expected; the controller must
never be satisfied by an installed-but-disabled timer.

## 4. Bounded manual acceptance run (service only, timer still disabled)

Before ever enabling the timer, run each service unit exactly once manually
and inspect its outcome:

```bash
sudo systemctl start synth-automatic-exit-policy-runtime.service
sudo systemctl start synth-shared-executor-runtime.service
```

Each is `Type=oneshot` with `Restart=no`; `systemctl start` blocks until the
one run finishes (bounded by each unit's `TimeoutStartSec`). Confirm each
completed with exit code 0:

```bash
systemctl show synth-automatic-exit-policy-runtime.service --no-pager \
  --property=Result,ExecMainStatus
systemctl show synth-shared-executor-runtime.service --no-pager \
  --property=Result,ExecMainStatus
```

Expect `Result=success`, `ExecMainStatus=0` for both.

## 5. Inspect journal / persisted state

```bash
journalctl -u synth-automatic-exit-policy-runtime.service --no-pager -n 200
journalctl -u synth-shared-executor-runtime.service --no-pager -n 200
```

Confirm each run's structured `STARTED`/`FINISHED` lines (per this
repository's Long-Running Runner Observability contract), the reported mode
(`SYNTH_SHARED_EXECUTOR_MODE=DRY_RUN` for the shared executor -- PAPER/LIVE
remain unavailable per `docs/ops/shared_executor_runtime_v1.md`), and no
unexpected broker/credential/private-read activity in the log. Cross-check
any persisted evidence rows the run is documented to write (see each
runtime's own architecture doc) against what was actually written -- do not
assume from the journal alone.

## 6. Separately enable the timer

Only after step 5's manual acceptance is clean, enable and start each timer
as its own explicit step:

```bash
sudo systemctl enable --now synth-automatic-exit-policy-runtime.timer
sudo systemctl enable --now synth-shared-executor-runtime.timer
```

Re-verify:

```bash
systemctl show synth-automatic-exit-policy-runtime.timer --no-pager \
  --property=LoadState,ActiveState,UnitFileState,FragmentPath
systemctl show synth-shared-executor-runtime.timer --no-pager \
  --property=LoadState,ActiveState,UnitFileState,FragmentPath
```

Expect `UnitFileState=enabled`, `ActiveState=active` for both. At this
point, and only at this point, does
`python -m src.ops.sell_live_activation_controller_v1 --check ...`'s
`RUNTIME_READY` phase report both capabilities `READY`.

## 7. Rollback

To revert to the disabled baseline (or fully remove):

```bash
sudo systemctl disable --now synth-automatic-exit-policy-runtime.timer
sudo systemctl disable --now synth-shared-executor-runtime.timer
```

`disable --now` stops the timer immediately and removes its enablement
symlink; it does not touch the service unit file, does not remove any
persisted evidence the runtime already wrote, and performs no database,
credential, kill-switch, or broker mutation. To remove the unit files
entirely (e.g. after a design change), remove them only after confirming no
timer references them:

```bash
sudo rm /etc/systemd/system/synth-automatic-exit-policy-runtime.service
sudo rm /etc/systemd/system/synth-automatic-exit-policy-runtime.timer
sudo rm /etc/systemd/system/synth-shared-executor-runtime.service
sudo rm /etc/systemd/system/synth-shared-executor-runtime.timer
sudo systemctl daemon-reload
```

## Explicit non-goals

This sequence, and the tooling it exercises, never:

- grants `executor_live_authority_v1` authority
- changes `automatic_exit_live_permission` (decision-gate LIVE permission)
- provisions or rotates a broker credential
- engages or disengages the kill switch
- submits a broker order or performs any broker-private call
- installs, enables, or starts anything outside the two unit pairs named
  above

Making `RUNTIME_READY` observe both capabilities as `READY` moves the SELL
LIVE readiness controller's terminal state closer to
`LIVE_AUTHORIZATION_REQUIRED`, never to an authorized LIVE state. See
`docs/ops/sell_live_activation_controller_v1.md`'s "Explicit LIVE
authorization boundary" section for the separate, explicit, human steps
still required after every phase passes.
