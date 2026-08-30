# Runtime capability systemd deployment v1 (Issue #585)

## Status

Ops/deploy runbook only. It documents a reversible, explicit,
human-operated install/acceptance/enable/rollback sequence for the two
runtime capabilities `AUTOMATIC_EXIT_POLICY_RUNTIME` and
`SHARED_EXECUTOR_RUNTIME` on their canonical owner host `gurkdb`. It grants
no authorization by itself: it never enables live trading, provisions
credentials, mutates the kill switch, or grants execution authority. See
`docs/ops/sell_live_activation_controller_v1.md`'s "RUNTIME_READY
truthfulness" section for how `RUNTIME_READY` consumes the state this
sequence produces.

```text
service_mutation=0 (this document; systemctl mutation commands below are
                     manual operator commands, never run by this repository
                     or any controller in it)
production_db_mutation=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority_grant=0
kill_switch_mutation=0
```

## Scope

```text
capability                    service unit                                    timer unit
AUTOMATIC_EXIT_POLICY_RUNTIME  synth-automatic-exit-policy-runtime.service     synth-automatic-exit-policy-runtime.timer
SHARED_EXECUTOR_RUNTIME        synth-shared-executor-runtime.service           synth-shared-executor-runtime.timer
```

Both unit pairs are committed, reviewed repository artifacts:

```text
deploy/systemd/synth-automatic-exit-policy-runtime.service
deploy/systemd/synth-automatic-exit-policy-runtime.timer
deploy/systemd/synth-shared-executor-runtime.service
deploy/systemd/synth-shared-executor-runtime.timer
```

`deploy/ownership/account_runtime_capability_ownership_v1.json` records
`owner_host=gurkdb` for both capabilities. This document is what makes that
ownership metadata match observed reality; the ownership registry itself is
never edited by this sequence (its schema and `activation_status` field
stay design-only, per `src/ops/systemd_runtime_readiness_v1.py`'s module
docstring -- readiness is decided from actual systemd state, never from that
field).

## 1. Install the reviewed units (gurkdb, as `gurk`, via `sudo`)

`AUTOMATIC_EXIT_POLICY_RUNTIME` (not currently installed on gurkdb):

```bash
sudo cp deploy/systemd/synth-automatic-exit-policy-runtime.service /etc/systemd/system/
sudo cp deploy/systemd/synth-automatic-exit-policy-runtime.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/synth-automatic-exit-policy-runtime.service
systemd-analyze verify /etc/systemd/system/synth-automatic-exit-policy-runtime.timer
```

`SHARED_EXECUTOR_RUNTIME` (already installed on gurkdb per the 2026-08-29
audit; re-run only if the unit content changed):

```bash
sudo cp deploy/systemd/synth-shared-executor-runtime.service /etc/systemd/system/
sudo cp deploy/systemd/synth-shared-executor-runtime.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/synth-shared-executor-runtime.service
systemd-analyze verify /etc/systemd/system/synth-shared-executor-runtime.timer
```

`synth-shared-executor-runtime.service` requires
`/etc/synth/shared-executor-runtime-v1.env` to exist
(`ConditionPathExists=`) before it can load; per the 2026-08-29 audit this
file is already present on gurkdb (`root:gurk`, mode `0640`).

## 2. `daemon-reload`

```bash
sudo systemctl daemon-reload
```

## 3. Keep disabled initially

Do not run `enable` or `start` yet. Confirm both pairs are loaded but
inert:

```bash
systemctl show synth-automatic-exit-policy-runtime.service --property=LoadState,ActiveState,UnitFileState,FragmentPath
systemctl show synth-automatic-exit-policy-runtime.timer --property=LoadState,ActiveState,UnitFileState,FragmentPath
systemctl show synth-shared-executor-runtime.service --property=LoadState,ActiveState,UnitFileState,FragmentPath
systemctl show synth-shared-executor-runtime.timer --property=LoadState,ActiveState,UnitFileState,FragmentPath
```

Expected at this step for both pairs: `LoadState=loaded`,
`UnitFileState=disabled`, `ActiveState=inactive`,
`FragmentPath=/etc/systemd/system/<unit>`.

## 4. Bounded manual acceptance run (one-shot, service only, timer still disabled)

Run the oneshot service exactly once by hand to confirm it starts, does
real (or, for the executor, `DRY_RUN`-only) work, and terminates cleanly,
without ever enabling the recurring timer:

```bash
sudo systemctl start synth-automatic-exit-policy-runtime.service
systemctl show synth-automatic-exit-policy-runtime.service --property=ActiveState,Result,ExecMainStatus
```

```bash
sudo systemctl start synth-shared-executor-runtime.service
systemctl show synth-shared-executor-runtime.service --property=ActiveState,Result,ExecMainStatus
```

`ExecMainStatus=0` and `Result=success` are the expected pass criteria for
a single bounded run. The service returns to `ActiveState=inactive`
afterward -- that is the expected idle state for a `Type=oneshot` unit
between firings, not a failure (see
`docs/ops/sell_live_activation_controller_v1.md`'s RUNTIME_READY section:
readiness never requires the service itself to stay `active`).

## 5. Inspect journal / persisted state

```bash
journalctl -u synth-automatic-exit-policy-runtime.service -n 100 --no-pager
journalctl -u synth-shared-executor-runtime.service -n 100 --no-pager
```

Confirm: exactly one `STARTED`/`FINISHED` (or `INTERRUPTED`/`FAILED`) pair
per run, `broker_private_calls=0`/`broker_writes=0`/`order_submission=0`/
`live_orders=0` markers present where the runner emits them, no traceback
loop, and (for the shared executor) `SYNTH_SHARED_EXECUTOR_MODE=DRY_RUN`
in the observed environment/log output -- never `PAPER` or `LIVE`, which
remain unavailable per `docs/ops/shared_executor_runtime_v1.md`.

## 6. Separately enable the timer

Only after step 4/5 evidence is reviewed and accepted, enable and start
each timer independently (never bundle both capabilities' enablement into
one action, and never enable a timer whose one-shot acceptance run in step
4 did not pass):

```bash
sudo systemctl enable --now synth-automatic-exit-policy-runtime.timer
```

```bash
sudo systemctl enable --now synth-shared-executor-runtime.timer
```

Confirm the resulting state:

```bash
systemctl show synth-automatic-exit-policy-runtime.timer --property=LoadState,ActiveState,UnitFileState,FragmentPath
systemctl show synth-shared-executor-runtime.timer --property=LoadState,ActiveState,UnitFileState,FragmentPath
```

Expected: `UnitFileState=enabled`, `ActiveState=active`. This is exactly
the state `src/ops/systemd_runtime_readiness_v1.py` requires for
`RUNTIME_READY` to pass for that capability (service `loaded` from its
expected `FragmentPath` in a known-benign `ActiveState`, timer `loaded`
from its expected `FragmentPath`, `enabled`, and `active`).

## 7. Rollback (reversible at service level)

Disable and stop a timer without removing anything:

```bash
sudo systemctl disable --now synth-automatic-exit-policy-runtime.timer
```

```bash
sudo systemctl disable --now synth-shared-executor-runtime.timer
```

This alone makes `RUNTIME_READY` fail closed again for that capability
(`TIMER_UNIT_INACTIVE`/`TIMER_UNIT_DISABLED`) without touching the
ownership registry, without any DB write, and without any broker,
credential, kill-switch, or live-authority action. Full removal (only if
explicitly decided separately) would additionally use:

```bash
sudo systemctl disable synth-automatic-exit-policy-runtime.service
sudo rm /etc/systemd/system/synth-automatic-exit-policy-runtime.service
sudo rm /etc/systemd/system/synth-automatic-exit-policy-runtime.timer
sudo systemctl daemon-reload
```

(equivalently for the shared-executor pair).

## Explicit non-goals

This document, and every command in it, never:

- grants LIVE trading permission or executor operational LIVE authority
  (`src/executor/execution_live_authority_v1.py`)
- provisions or rotates a broker credential
- engages/disengages the kill switch
  (`src/executor/execution_kill_switch_v1.py`)
- edits `deploy/ownership/account_runtime_capability_ownership_v1.json`
- runs from inside `src/ops/sell_live_activation_controller_v1.py` or
  `src/ops/systemd_runtime_readiness_v1.py` -- both stay strictly read-only;
  every `systemctl enable`/`start`/`daemon-reload`/`disable` command above
  is a manual operator action documented here, never code in this
  repository.

Enabling `SHARED_EXECUTOR_RUNTIME`'s timer only ever runs the executor in
`SYNTH_SHARED_EXECUTOR_MODE=DRY_RUN` (see the unit file and
`docs/ops/shared_executor_runtime_v1.md`); `PAPER` and `LIVE` executor modes
remain unavailable regardless of this sequence.
