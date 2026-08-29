# SELL LIVE runtime readiness: deployment and acceptance sequence (Issue #585)

## Purpose

This document is the bounded, read-only-safe sequence for making
`sell_live_activation_controller_v1.py`'s `RUNTIME_READY` phase pass
truthfully on `gurkdb` for the two required capabilities:

- `AUTOMATIC_EXIT_POLICY_RUNTIME`
  (`synth-automatic-exit-policy-runtime.service`/`.timer`)
- `SHARED_EXECUTOR_RUNTIME`
  (`synth-shared-executor-runtime.service`/`.timer`)

It does **not** grant LIVE trading permission, LIVE authority, or touch the
kill switch. It only gets the underlying systemd units installed, verified,
and (as a separate, later step) enabled -- exactly the state
`RUNTIME_READY` (see `docs/ops/sell_live_activation_controller_v1.md`) then
observes and reports on.

Safety boundary for every step in this document:

```text
service_mutation=<explicit per step, see below>
production_db_mutation=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority_grant=0
kill_switch_mutation=0
decision_gate=none
execution_planner=none
executor=none
```

Host: **gurkdb** only (`ConditionHost=gurkdb` is already asserted inside
both unit files). Do not perform any step in this document on Odroid, a dev
laptop, or any other host.

## Evidence at time of writing (2026-08-29)

- gurkdb `main` was at `8d4c35cf5980a28eb1d236e7e0f4939eaf0fde04`.
- `synth-shared-executor-runtime.service`/`.timer` were already installed,
  disabled and inactive.
- `/etc/synth/shared-executor-runtime-v1.env` was present.
- `synth-automatic-exit-policy-runtime.service`/`.timer` were **not**
  installed.
- No relevant timer was active.

Re-verify current state with Step 1 before acting -- this snapshot will go
stale.

## Step 1 -- Inspect current state (read-only, no mutation)

```bash
systemctl --system show synth-automatic-exit-policy-runtime.service --no-pager \
  --property=LoadState,ActiveState,SubState,UnitFileState,FragmentPath
systemctl --system show synth-automatic-exit-policy-runtime.timer --no-pager \
  --property=LoadState,ActiveState,SubState,UnitFileState,FragmentPath
systemctl --system show synth-shared-executor-runtime.service --no-pager \
  --property=LoadState,ActiveState,SubState,UnitFileState,FragmentPath
systemctl --system show synth-shared-executor-runtime.timer --no-pager \
  --property=LoadState,ActiveState,SubState,UnitFileState,FragmentPath
```

`service_mutation=0`. This is exactly the read `RUNTIME_READY` performs.

## Step 2 -- Review the unit files before installing anything

Review `deploy/systemd/synth-automatic-exit-policy-runtime.{service,timer}`
and `deploy/systemd/synth-shared-executor-runtime.{service,timer}` in the
reviewed repository checkout. Confirm:

- `ConditionHost=gurkdb` is present on every unit.
- `SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED` and
  `SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED` are present on both services.
- `synth-shared-executor-runtime.service` runs `SYNTH_SHARED_EXECUTOR_MODE=DRY_RUN`
  and requires `/etc/synth/shared-executor-runtime-v1.env` to exist
  (`ConditionPathExists=`).
- Neither timer is already `Install`-enabled in a way that would auto-start
  on copy (copying alone never enables a unit; `enable` is a separate,
  explicit step below).

## Step 3 -- Install the reviewed units (`service_mutation=1`, install only)

Run **on gurkdb**, from the reviewed checkout:

```bash
sudo cp deploy/systemd/synth-automatic-exit-policy-runtime.service /etc/systemd/system/
sudo cp deploy/systemd/synth-automatic-exit-policy-runtime.timer /etc/systemd/system/
sudo cp deploy/systemd/synth-shared-executor-runtime.service /etc/systemd/system/
sudo cp deploy/systemd/synth-shared-executor-runtime.timer /etc/systemd/system/
sha256sum deploy/systemd/synth-automatic-exit-policy-runtime.service /etc/systemd/system/synth-automatic-exit-policy-runtime.service
sha256sum deploy/systemd/synth-automatic-exit-policy-runtime.timer /etc/systemd/system/synth-automatic-exit-policy-runtime.timer
sha256sum deploy/systemd/synth-shared-executor-runtime.service /etc/systemd/system/synth-shared-executor-runtime.service
sha256sum deploy/systemd/synth-shared-executor-runtime.timer /etc/systemd/system/synth-shared-executor-runtime.timer
```

Confirm every `sha256sum` pair matches before proceeding. This is a file
copy only -- no unit is enabled or started by `cp`.

## Step 4 -- daemon-reload (`service_mutation=1`, systemd metadata only)

```bash
sudo systemctl daemon-reload
```

No unit changes state as a result of `daemon-reload` alone.

## Step 5 -- Keep both timers disabled initially

Do not run `enable` yet. Re-run Step 1's `systemctl show` commands and
confirm:

- `LoadState=loaded` for all four units,
- `FragmentPath=/etc/systemd/system/<unit>` for all four,
- `UnitFileState=disabled` for both timers,
- `ActiveState=inactive` for all four.

At this point `RUNTIME_READY` still correctly reports `TIMER_NOT_ENABLED`
for both capabilities -- this is the expected, safe intermediate state.

## Step 6 -- Bounded manual acceptance (oneshot service only, no timer)

Before enabling either timer, run each oneshot service manually exactly
once to confirm it starts, completes, and exits cleanly:

```bash
sudo systemctl start synth-automatic-exit-policy-runtime.service
sudo systemctl status synth-automatic-exit-policy-runtime.service --no-pager
```

```bash
sudo systemctl start synth-shared-executor-runtime.service
sudo systemctl status synth-shared-executor-runtime.service --no-pager
```

`service_mutation=1` (a single bounded manual run of each already-reviewed
oneshot unit). This never enables a timer, never grants LIVE authority,
never touches the kill switch, and (per the unit files'
`SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED` /
`SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED` environment) can perform no
broker write or order submission regardless of any other state.

## Step 7 -- Inspect journal and persisted state after the manual run

```bash
journalctl -u synth-automatic-exit-policy-runtime.service --no-pager -n 200
journalctl -u synth-shared-executor-runtime.service --no-pager -n 200
```

Confirm:

- exit code `0` / `status=0/SUCCESS` for both,
- no unexpected exception traceback,
- no broker write or order submission log line (there must be none -- both
  services are DRY_RUN/PAPER-scoped only by their reviewed design),
- any persisted state each service writes (e.g. exit-policy evaluation
  output, shared-executor DRY_RUN handoff records) looks structurally sane
  for a first bounded run.

If anything here is unexpected, stop and fix the underlying issue before
touching a timer -- do not paper over it by disabling `RUNTIME_READY`'s
checks.

## Step 8 -- Separately enable each timer (`service_mutation=1`, explicit and reviewed)

Only after Step 6/7 pass cleanly:

```bash
sudo systemctl enable --now synth-automatic-exit-policy-runtime.timer
sudo systemctl enable --now synth-shared-executor-runtime.timer
```

Re-run Step 1's `systemctl show` commands and confirm both timers now show
`UnitFileState=enabled` and `ActiveState=active`. Re-run the controller
(read-only; see `docs/ops/sell_live_activation_controller_v1.md`'s
production check command) and confirm `RUNTIME_READY` reports `PASSED` for
both capabilities.

## Rollback

Disabling either timer is always safe and always available:

```bash
sudo systemctl disable --now synth-automatic-exit-policy-runtime.timer
sudo systemctl disable --now synth-shared-executor-runtime.timer
```

This immediately makes `RUNTIME_READY` correctly report `TIMER_NOT_ACTIVE`/
`TIMER_NOT_ENABLED` again -- there is no other rollback needed, since this
sequence never touched LIVE authority, the kill switch, or any credential.
To fully remove the units (not required for rollback, only for retirement):

```bash
sudo systemctl disable --now synth-automatic-exit-policy-runtime.timer synth-automatic-exit-policy-runtime.service
sudo systemctl disable --now synth-shared-executor-runtime.timer synth-shared-executor-runtime.service
sudo rm /etc/systemd/system/synth-automatic-exit-policy-runtime.service /etc/systemd/system/synth-automatic-exit-policy-runtime.timer
sudo rm /etc/systemd/system/synth-shared-executor-runtime.service /etc/systemd/system/synth-shared-executor-runtime.timer
sudo systemctl daemon-reload
```

## What this sequence explicitly never does

- Never grants LIVE trading permission or LIVE authority
  (`execution_live_authority_v1`).
- Never flips `execution_kill_switch_v1` state.
- Never provisions or rotates a broker credential.
- Never edits `deploy/ownership/account_runtime_capability_ownership_v1.json`'s
  schema to add an `ACTIVE`/`ENABLED`/`RUNNING` value -- that registry
  remains ownership/design metadata only; `RUNTIME_READY`'s truth source is
  the live `systemctl show` observation documented in
  `docs/ops/sell_live_activation_controller_v1.md`.
- Never has the controller itself install, enable, start, stop, or mutate
  any unit -- `src/ops/systemd_runtime_readiness_probe_v1.py` only issues
  `systemctl show`.
