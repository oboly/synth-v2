# Market Rotation Pressure Runtime Owners V1

## Status

Repository-reviewed deployment candidate only. No host systemd unit has been
installed, enabled, started, or restarted as part of this document or its
companion unit files. Separate host activation and multi-cycle acceptance are
still required (see Activation Order and Multi-Cycle Acceptance below).

This is step 2 ("Separate Runtime Owner PR") of the Lane C operational
sequence recorded in `docs/todo/README.md`.

## Ownership

```text
devlap (host: devlap, user: gurk):
  owns rotation history ingestion and persisted rotation pressure writes
  scripts/run_market_rotation_pressure_once.sh --write-db
  -> src.research.run_market_rotation_history_v1 --write-db
  -> src.research.run_market_rotation_pressure_v1 --write-db

Odroid (host: odroid, user: theone):
  owns read-only publication of persisted rotation pressure
  scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh
  -> src.reporting.run_market_rotation_pressure_dashboard_v1
```

The writer and publisher are separate runtime owners on separate hosts, with
separate systemd units and separate timers. Neither unit declares a
cross-host or cross-service `Requires=`/`After=` dependency. No SSH
orchestration is introduced by this lane.

## Lock Isolation (PrivateTmp)

Both services set `PrivateTmp=false` deliberately. Each wrapper takes a
non-blocking `flock` on a default lock file under the host `/tmp` namespace:

```text
writer:    /tmp/synth-market-rotation-pressure-v1.lock
publisher: /tmp/synth-market-rotation-pressure-dashboard-v1.lock
```

Neither wrapper's lock path is changed by this lane. If a service instead
ran with `PrivateTmp=true`, systemd would give that service invocation its
own private `/tmp` mount namespace; a timer-triggered run and a manual
`bash scripts/run_market_rotation_pressure_once.sh --write-db` (or the
publisher equivalent) invoked directly in a shell would then resolve the
"same" default lock path to two different underlying files, and the
non-blocking `flock` would never see the other invocation — defeating the
lock and allowing concurrent execution. `PrivateTmp=false` keeps one
host-wide lock domain per wrapper, so systemd-triggered and manually
invoked runs of the same wrapper always contend for the same lock file.

This is the only hardening directive intentionally weakened from the usual
per-service default. `NoNewPrivileges=true`, `UMask=0077`, the dedicated
`User=` (`gurk` for the writer, `theone` for the publisher), and all other
hardening remain intact.

## Evidence

### Accepted production evidence (devlap writer)

- devlap writer acceptance: PASS
- resolved pressure source snapshots:
  - 24h snapshot_id=5
  - 168h snapshot_id=6
  - source `as_of_ts_utc=2026-07-14 18:00:00 UTC`
- persisted pressure observations: 115
- score values finite and bounded in `[-100, 100]`
- duplicate and idempotency audits: PASS
- unrelated writes: none

### Accepted production evidence (Odroid publisher)

- Odroid read-only publisher acceptance: PASS

### Existing runtime-owner audit (read-only inspection performed for this task)

Devlap (`systemctl list-timers --all`, `systemctl cat ...`): this devlap shell
is not running under a live systemd instance (`systemctl` reports "System has
not been booted with systemd as init system"), so no live devlap timer/unit
query could be executed. `systemctl list-unit-files` (static, does not
require the bus) was queried and shows no `synth-*rotation*` or
`synth-*pressure*` unit installed. Repository search of
`deploy/systemd/*.service|*.timer` and `docs/ops/systemd/*.service|*.timer`
found no existing unit that invokes:

- `scripts/run_market_rotation_pressure_once.sh`
- `run_market_rotation_history_v1`
- `run_market_rotation_pressure_v1`

The only existing devlap-owned market chain unit is `synth-chain-4h`
(`deploy/systemd/synth-chain-4h.service` / `.timer`), a 4-hourly market-only
chain unrelated to hourly rotation pressure; it is not modified by this task.

Odroid (`ssh odroid 'systemctl --user list-timers --all'`,
`systemctl --user list-unit-files'`, and equivalent system-level queries):
live inspection succeeded. Installed timers/units as of this audit
(2026-07-14, ~18:56 UTC):

```text
synth-account-wallet-dashboard@{joost,hugo}.timer
synth-account-wallet-refresh@{hugo,joost}.timer
synth-live-like-shadow-heartbeat.timer
synth-mvp-readonly-cockpit.timer
synth-mvp-account-refresh.timer
synth-market-candle-freshness.timer   (user, theone)
synth-linked-profile-runtime-refresh.timer   (system)
synth-4h-market-chain.timer                  (system)
```

No installed unit on Odroid invokes
`scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh`.
Repository search of `deploy/systemd/`, `docs/ops/systemd/`, and
`scripts/odroid/systemd/` on both the devlap checkout and the Odroid checkout
(`~/projects/synth-v2` on odroid, read-only `ssh` inspection) found no
existing Rotation Pressure publisher unit; the only "rotation" string match
was the unrelated `SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML` variable already
used by `synth-mvp-readonly-cockpit.service`.

`current installed timer ownership for this new lane: not yet created` is
confirmed correct on both hosts.

### Source availability / cadence evidence

The rotation-pressure source chain is `obs_market_candle (1h)` ->
`market_rotation_history_v1` -> `market_rotation_pressure_v1`
(`CANDLE_INTERVAL = "1h"` in `src/research/run_market_rotation_history_v1.py`).

`obs_market_candle` 1h-interval freshness is owned by the existing Odroid
`synth-market-candle-freshness` user timer
(`scripts/odroid/systemd/synth-market-candle-freshness.timer`,
`OnBootSec=3min`, `OnUnitActiveSec=15min`), which refreshes `15m/1h/4h/1d/1w`
candle coverage on an approximately 15-minute cadence.

Read-only journal evidence collected for this task
(`ssh odroid 'journalctl --user -u synth-market-candle-freshness.service -n 40 --no-pager'`)
shows a stable, repeating cadence:

```text
start=18:04:52 finish=18:11:28
start=18:20:22 finish=18:26:28
start=18:35:52 finish=18:41:53
start=18:51:22 finish=(in progress at audit time)
```

Spacing is consistently ~15m30s between starts, and each run's own duration
is ~6-7 minutes. For any hourly candle close at `HH:00:00`, the next
candle-freshness run starts no later than `HH:04:52`-class offset within its
own phase and completes persistence by `HH:11:28`-class offset in the
observed pattern. This is consistent with the accepted production evidence's
source timestamp of `18:00:00 UTC` being fully resolved and available for the
writer well before the top of the following cycle.

### Cadence decision

Required relationship:

```text
hourly source data available (candle freshness completes by ~HH:11-12)
-> safety margin
-> devlap pressure writer:            HH:20:00 UTC
-> additional separation
-> Odroid read-only publisher:        HH:35:00 UTC
```

- writer_timer_utc = `*:20:00 UTC` (`RandomizedDelaySec=180`, worst-case
  latest start `HH:23:00`)
- publisher_timer_utc = `*:35:00 UTC` (`RandomizedDelaySec=180`, worst-case
  earliest start `HH:35:00`)
- minimum effective separation = `HH:35:00 - HH:23:00` = 12 minutes, which
  exceeds the required minimum of 5 minutes.

The writer minute (`:20`) carries an ~8-9 minute margin beyond the observed
candle-freshness completion offset (`~:11:28`). The publisher cannot start
before the writer under normal `RandomizedDelaySec` bounds.

## Installation Commands

Do not execute these commands as part of this task. They are recorded for a
separate, explicitly approved host-activation operation.

### Devlap installation

```bash
# on devlap, as gurk
cd /home/gurk/projects/synth-v2
git fetch origin
git checkout <accepted-commit>
sudo cp deploy/systemd/synth-market-rotation-pressure-writer.service /etc/systemd/system/
sudo cp deploy/systemd/synth-market-rotation-pressure-writer.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/synth-market-rotation-pressure-writer.service
systemd-analyze verify /etc/systemd/system/synth-market-rotation-pressure-writer.timer
sudo systemctl daemon-reload
# timer enablement happens only during the separate approved activation step:
# sudo systemctl enable --now synth-market-rotation-pressure-writer.timer
```

### Odroid installation

```bash
# on odroid, as theone
cd /home/theone/projects/synth-v2
git fetch origin
git checkout <accepted-commit>
sudo cp docs/ops/systemd/synth-market-rotation-pressure-publisher.service /etc/systemd/system/
sudo cp docs/ops/systemd/synth-market-rotation-pressure-publisher.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/synth-market-rotation-pressure-publisher.service
systemd-analyze verify /etc/systemd/system/synth-market-rotation-pressure-publisher.timer
sudo systemctl daemon-reload
# timer enablement happens only during the separate approved activation step:
# sudo systemctl enable --now synth-market-rotation-pressure-publisher.timer
```

## Pre-Activation Checks

Before any enablement:

- deployed repository worktree is clean (`git status --short` empty);
- exact deployed commit is recorded and matches the accepted/reviewed PR
  commit on both hosts;
- no duplicate installed owner exists for either the writer or the publisher
  (`systemctl list-unit-files` / `systemctl --user list-unit-files` show no
  prior `synth-market-rotation-pressure-*` unit);
- `bash -n` wrapper syntax checks pass for both wrapper scripts;
- a manual oneshot run of each wrapper succeeds
  (`bash scripts/run_market_rotation_pressure_once.sh --write-db` on devlap;
  `bash scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh`
  on Odroid);
- `systemctl list-timers` schedule inspection confirms the intended
  `OnCalendar` minute before enabling;
- journal and DB baseline captured immediately before first enablement;
- existing HTML/JSON web artifact baseline captured on Odroid before first
  enablement.

## Activation Order

```text
1. install and accept devlap writer
2. observe successful writer cycle
3. install and accept Odroid publisher
4. observe multiple complete cycles
```

Do not install or enable the publisher before the writer has an observed
successful cycle. Do not perform any of these steps in this repository task.

## Multi-Cycle Acceptance

Require at least three real hourly cycles, verifying:

- source timestamps advance each cycle;
- exactly one pressure header per venue/model/hour;
- observation count equals eligible count;
- no duplicate asset rows;
- writer lock behaves correctly (non-blocking, no overlap);
- publisher lock behaves correctly (non-blocking, no overlap);
- publisher remains read-only (no `--write-db`, no history/pressure runner
  invocation, no market-data mutation);
- dashboard freshness becomes and remains `FRESH`;
- no cross-host coupling (no SSH orchestration, no shared `Requires=`);
- journal volume stays bounded;
- disk growth stays bounded;
- a failed publisher cycle does not block or alter the writer timer/state;
- a failed or delayed writer cycle does not cause the publisher to claim
  fresh state that does not exist (the reporting layer's own fail-closed
  freshness classification governs this, per
  `docs/research/market_rotation_pressure_dashboard_v1.md`).

## Rollback

### Devlap rollback

```bash
sudo systemctl disable --now synth-market-rotation-pressure-writer.timer
sudo rm /etc/systemd/system/synth-market-rotation-pressure-writer.service
sudo rm /etc/systemd/system/synth-market-rotation-pressure-writer.timer
sudo systemctl daemon-reload
sudo systemctl reset-failed
systemctl list-timers --all | grep -i rotation-pressure-writer   # expect no match
# do not delete persisted market data
```

### Odroid rollback

```bash
sudo systemctl disable --now synth-market-rotation-pressure-publisher.timer
sudo rm /etc/systemd/system/synth-market-rotation-pressure-publisher.service
sudo rm /etc/systemd/system/synth-market-rotation-pressure-publisher.timer
sudo systemctl daemon-reload
sudo systemctl reset-failed
systemctl list-timers --all | grep -i rotation-pressure-publisher   # expect no match
# preserve last valid HTML/JSON unless an explicit removal is separately approved
```

Rollback never modifies Profit Plan or broker/account state.

## Non-Goals

This lane does not:

- change the Rotation Pressure scoring model;
- change the existing writer or publisher wrapper responsibility split;
- combine the writer and publisher into one service;
- allow the publisher to trigger or depend on the writer, or vice versa;
- grant live trading, broker write, or order-submission permission;
- change Profit Plan code; the light-bar embed remains a deferred,
  read-only, reporting-only follow-up per
  `docs/research/market_rotation_pressure_dashboard_v1.md`.
