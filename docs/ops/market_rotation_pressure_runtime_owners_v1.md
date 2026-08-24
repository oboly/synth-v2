# Market Rotation Pressure Runtime Owners V1

## Status

**HISTORICAL ACCEPTANCE RECORD — production authorization SUPERSEDED.** The
devlap writer and Odroid publisher were previously observed installed, enabled,
and active, and three consecutive real hourly writer(:20 UTC)→publisher(:35 UTC)
cycles were independently verified against per-invocation timer-origin evidence
(not `TriggeredBy=` alone). That remains valid acceptance and installed-runtime
evidence, not current production authorization.

This closes step 3 ("Separate host acceptance") of the Lane C operational
sequence recorded in `docs/todo/README.md`. This document itself remains the
repository record for step 2 ("Separate Runtime Owner PR").

No host systemd unit has been changed by this repository-only public market-data
ownership correction.

## 2026-07-19 production-ownership reset (audit context, not authorization)

This document remains the truthful record of the devlap writer **acceptance** and
its three-cycle runtime, idempotency/reconciliation, and installed active-timer
evidence. None of that evidence is erased or altered.

Under the writer-capability host-ownership contract
(`docs/ops/writer_capability_host_ownership_contract_v1.md`), the earlier
implication that this acceptance made devlap the canonical
`production_runtime_owner` for `market_rotation_pressure` is **reset**:

```text
market_rotation_pressure.acceptance_host=devlap
market_rotation_pressure.acceptance_status=ACCEPTED
market_rotation_pressure.production_runtime_owner=UNASSIGNED
market_rotation_pressure.production_authorization_status=UNASSIGNED
market_rotation_pressure.production_decision_evidence=""
historical_runtime_assignment: host=devlap source=PR #100/#101 status=SUPERSEDED
observed_runtime_state:
  host=devlap
  unit=synth-market-rotation-pressure-writer.timer
  installed_at_observation=true
  enabled_at_observation=true
  active_at_observation=true
  observed_at_utc=2026-07-14T18:56:00Z
  observed_at_precision=approximate_minute
  current_state=UNVERIFIED
  authorization_status=SUPERSEDED
  runtime_state_classification=OBSERVED_LEGACY_RUNTIME_PENDING_CONTAINMENT
```

The acceptance record, the three-cycle evidence, and the fact that devlap was
last observed with an installed active timer describe acceptance and observed
runtime state only. Current state is `UNVERIFIED`; canonical authorization is
absent. A production owner is assigned only by a separate, explicitly evidenced
host-selection and cutover decision.

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

## 2026-07-20 gurkDB preflight selection (selection only, not authorization)

`market_rotation_pressure` is selected to gurkDB for strict host preflight:

```text
market_rotation_pressure.candidate_host=gurkdb
market_rotation_pressure.selected_host=gurkdb
market_rotation_pressure.runtime_lifecycle=SELECTED_PENDING_PREFLIGHT
market_rotation_pressure.production_runtime_owner=UNASSIGNED
market_rotation_pressure.production_authorization_status=UNASSIGNED
```

This selection is repository-only and means only "selected for strict host
preflight". The acceptance record, the devlap historical assignment
(`SUPERSEDED`), and the observed devlap timer (`current_state=UNVERIFIED`) above
are unchanged; none of them is production authorization. gurkDB is not prepared,
not preflighted, not accepted, not authorized, and runs no writer. No host
systemd unit is changed. Strict gurkDB preflight and a separately evidenced
cutover, per `docs/ops/writer_capability_host_ownership_contract_v1.md`, remain
required before any production ownership.

## 2026-08-07 gurkDB writer cutover preparation (repository-only, Issue #266)

### Root cause

A read-only production audit (Issue #266) traced why the public rotation
snapshot (`freshness=STALE`, `source_ts_utc=2026-07-20T04:00:00Z`) had stopped
advancing while the Profit Plan read-only projection continued to work
correctly:

- `obs_market_candle` (1h) is fresh (gurkDB `public_candle_freshness` writer
  active, cadence minutes `:02,17,32,47` UTC);
- `market_rotation_history_v1`/`market_rotation_pressure_v1` last advanced at
  `as_of_ts_utc=2026-07-20T04:00:00Z` (`created_at=2026-07-20T04:21:53Z`),
  exactly when the devlap writer was correctly disabled as part of the
  `production-ownership reset` above;
- gurkDB was only ever `SELECTED_PENDING_PREFLIGHT` for this capability and
  never taken through preflight/acceptance/authorization/activation, unlike
  `public_price_snapshot` and `public_candle_freshness`;
- the Odroid publisher remained enabled and active throughout, correctly
  fail-closed reporting `STALE` from the last persisted row;
- Profit Plan's projection performs no recomputation and correctly surfaced
  the upstream staleness.

Root cause: a production runtime-ownership gap (no active writer anywhere for
this capability since 2026-07-20T04:21:53Z), not a repository code defect and
not a Profit Plan/publisher defect.

### Repository change in this section

Per explicit user authorization, this repository is prepared for a gurkDB
cutover for `market_rotation_pressure`, following the same pattern already
used for `public_candle_freshness` (see
`docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md` and the
"Prepare gurkDB candle writer acceptance" precedent commit):

```text
market_rotation_pressure.committed_unit_binding.condition_host: devlap -> gurkdb
market_rotation_pressure.authorization_guard.authorization_file:
  /etc/synth/writer-capability-runtime-authorization-v1.json
  -> /etc/synth/writer-capability-market-rotation-pressure-authorization-v1.json
  (previously shared with public_price_snapshot's authorization file; now
  capability-distinct, so installing one capability's authorization file can
  never silently deauthorize the other)
```

`deploy/systemd/synth-market-rotation-pressure-writer.service` now declares
`ConditionHost=gurkdb`, keeps `User=gurk` /
`WorkingDirectory=/home/gurk/projects/synth-v2` (gurkDB uses the same service
account and checkout path as the historical devlap acceptance), and its
`ExecStartPre` authorization guard and `ExecStart` invocation of
`scripts/run_market_rotation_pressure_once.sh --write-db` are unchanged in
substance (the `ExecStart` venv-activation prefix, which referenced a
non-existent `venv/` path, is removed in favor of the wrapper script's own
existing `venv`/`.venv` auto-detection, matching the `public_candle_freshness`
convention).

This is a **repository-only preparation**. It does **not** change any registry
lifecycle field:

```text
market_rotation_pressure.candidate_host=gurkdb            (unchanged)
market_rotation_pressure.selected_host=gurkdb              (unchanged)
market_rotation_pressure.acceptance_host=devlap             (unchanged, historical)
market_rotation_pressure.production_runtime_owner=UNASSIGNED         (unchanged)
market_rotation_pressure.production_authorization_status=UNASSIGNED  (unchanged)
market_rotation_pressure.runtime_lifecycle=SELECTED_PENDING_PREFLIGHT (unchanged)
```

No host systemd unit is changed by this repository change. devlap's
`synth-market-rotation-pressure-writer.timer` remains installed and
**disabled** (contained); this change does not re-enable it and does not
install, enable, or start anything on gurkDB. gurkDB remains
not-preflighted, not-accepted, not-authorized, and runs no writer until a
separate, explicitly evidenced production cutover is performed and recorded,
following `docs/ops/writer_capability_host_ownership_contract_v1.md`.

### Architecture decision (Issue #266)

```text
devlap = development only
gurkdb = canonical production market-data writer host
odroid = public/dashboard publisher only
```

### Expected worst-case candle-to-visibility lag (post-cutover, once activated)

```text
candle close                    HH:00:00 UTC
candle-freshness writer (gurkdb) first tick HH:02:00, worst case HH:02:30
  (RandomizedDelaySec=30); observed full-universe completion ~4-7 min
  -> persisted by roughly HH:06-HH:09
rotation-pressure writer (gurkdb, this capability) HH:20:00,
  worst case HH:23:00 (RandomizedDelaySec=180); history+pressure runtime
  historically ~1-2 min -> persisted by roughly HH:24-HH:25
Odroid publisher HH:35:00, worst case HH:38:00 (RandomizedDelaySec=180);
  publish runtime ~1 min -> published by roughly HH:39
Profit Plan reads the published snapshot on demand (no additional lag)
```

Worst-case candle-close-to-Profit-Plan-visibility lag: **~39 minutes**.
Typical/best-case lag is materially lower (~21-25 minutes), since the
`RandomizedDelaySec` worst cases on all three timers rarely coincide.

## 2026-08-08 gurkDB controlled acceptance and production authorization

Per explicit user production-cutover authorization for Issue #266, gurkDB
completed strict preflight (all `PREFLIGHT_LOCAL` checks `PASS`) and one
controlled `ACCEPTANCE`-mode writer invocation, proven idempotent with zero
duplicate snapshot headers. Full evidence, including before/after row counts
and exact commands, is recorded in
`docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md`.

```text
market_rotation_pressure.acceptance_host=gurkdb
market_rotation_pressure.acceptance_status=ACCEPTED
market_rotation_pressure.production_runtime_owner=gurkdb
market_rotation_pressure.production_authorization_status=AUTHORIZED
market_rotation_pressure.runtime_lifecycle=AUTHORIZED_INACTIVE
market_rotation_pressure.production_decision_evidence=docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md#production-decision-evidence
```

This records production authorization only. `runtime_lifecycle` is
`AUTHORIZED_INACTIVE`, not `ACTIVE`: the gurkDB timer remains disabled and
inactive as of this repository state. Activation (enabling the timer,
observing a real scheduled cycle, and marking `ACTIVE`) is a separate,
subsequent operator action per the cutover order in
`docs/ops/writer_capability_host_ownership_contract_v1.md`. The devlap
historical assignment remains `SUPERSEDED`; devlap's
`synth-market-rotation-pressure-writer.timer` remains disabled and inactive
and is not touched by this authorization.

## 2026-08-08 gurkDB timer activation

Per explicit user production-cutover authorization for Issue #266, the
gurkDB timer was enabled the same day:

```bash
sudo systemctl enable --now synth-market-rotation-pressure-writer.timer
```

```text
market_rotation_pressure.production_runtime_owner=gurkdb
market_rotation_pressure.production_authorization_status=AUTHORIZED
market_rotation_pressure.runtime_lifecycle=ACTIVE
market_rotation_pressure.production_decision_evidence=docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md#production-decision-evidence
```

The first observed run (a `Persistent=true` catch-up invocation) succeeded in
`mode=PRODUCTION`: `market_rotation_snapshot_v1` advanced 222 -> 224 rows and
`market_rotation_pressure_snapshot_v1` advanced 111 -> 112 rows, both to
`as_of_ts_utc=2026-08-08T11:00:00Z`, matching the latest canonical
`obs_market_candle` (1h) close exactly. Zero duplicate snapshot headers.
Devlap re-verified disabled/inactive with no writer process at activation
time. Exactly one rotation-pressure systemd unit installed anywhere
(gurkDB). Full evidence is in
`docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md#gurkdb-activation-evidence-20260808`,
including confirmation that Profit Plan (which reads
`market_rotation_pressure_snapshot_v1` directly at render time, independent
of the Odroid-published JSON) already reported `rotation.freshness=FRESH`
matching this timestamp.

## Historical Runtime Roles

```text
devlap (host: devlap, user: gurk):
  historical acceptance host for rotation history ingestion and persisted
  rotation pressure writes; production authorization is SUPERSEDED.
  Per the Issue #266 architecture decision, devlap is development only and
  is not a production writer candidate going forward.
  scripts/run_market_rotation_pressure_once.sh --write-db
  -> src.research.run_market_rotation_history_v1 --write-db
  -> src.research.run_market_rotation_pressure_v1 --write-db

gurkDB (host: gurkdb, user: gurk) -- prepared candidate, not yet authorized:
  committed_unit_binding.condition_host=gurkdb (see "2026-08-07 gurkDB writer
  cutover preparation" above); same writer command as devlap above, unchanged.
  Not preflighted, not accepted, not authorized, runs no writer.

Odroid (host: odroid, user: theone):
  historical read-only publication host for persisted rotation pressure
  scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh
  -> src.reporting.run_market_rotation_pressure_dashboard_v1
```

The writer and publisher were implemented as separate runtime roles on separate
hosts, with separate systemd units and separate timers. Neither unit declares a
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

### Accepted writer evidence (devlap writer)

- devlap writer acceptance: PASS
- resolved pressure source snapshots:
  - 24h snapshot_id=5
  - 168h snapshot_id=6
  - source `as_of_ts_utc=2026-07-14 18:00:00 UTC`
- persisted pressure observations: 115
- score values finite and bounded in `[-100, 100]`
- duplicate and idempotency audits: PASS
- unrelated writes: none

### Accepted publisher evidence (Odroid publisher)

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

The existing devlap-bound market chain artifact is `synth-chain-4h`
(`deploy/systemd/synth-chain-4h.service` / `.timer`), a 4-hourly market-only
chain unrelated to hourly rotation pressure; its canonical production owner is
also `UNASSIGNED`.

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

The repository target assigns `obs_market_candle` 1h-interval freshness to the
devlap `synth-market-candle-freshness-writer.timer`, which refreshes
`15m/1h/4h/1d/1w` through the canonical host-neutral wrapper. The prior Odroid
timer evidence below is historical cadence evidence only; that timer is no
longer a valid active owner and its repository templates are retired.

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

`market_rotation_history_v1` reads only closed `1h` observations and aligns
every requested `as_of_ts` to the hour boundary. Its 24h and 7d windows
therefore contain 24 and 168 source candles respectively. A 5m or 15m run
before the next closed hourly observation cannot produce a new canonical
Rotation Pressure value; it would only repeat the same source window. The
meaningful canonical cadence is hourly, preserving append-only history without
duplicate sub-hourly snapshots.

Required relationship:

```text
hourly source data available from the separately authorized candle capability
-> safety margin
-> devlap historical pressure writer: HH:20:00 UTC
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

The Devlap installation commands below are frozen historical evidence for the
superseded devlap activation only. Since the "2026-08-07 gurkDB writer cutover
preparation" section above, the committed
`deploy/systemd/synth-market-rotation-pressure-writer.service` declares
`ConditionHost=gurkdb`, so copying it to devlap as shown below would install a
unit that never starts (`ConditionHost` fails closed on a host mismatch) --
it is preserved here only as a record of what was actually run during the
superseded devlap acceptance, not as a usable rollout path. Do not treat any
of these commands as generic rollout instructions. A future rollout must
follow `docs/ops/writer_capability_host_ownership_contract_v1.md`.

### Devlap installation (historical, superseded)

```bash
# on devlap, as gurk -- historical record only, no longer a valid target
# for the current committed unit (ConditionHost=gurkdb)
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

### gurkDB installation (current committed candidate, not yet authorized)

```bash
# on gurkdb, as gurk -- installation only; do NOT enable or start the timer.
# Preflight, acceptance, and a separate production authorization decision
# (per docs/ops/writer_capability_host_ownership_contract_v1.md) must be
# completed and recorded before any enablement.
cd /home/gurk/projects/synth-v2
git fetch origin
git checkout <accepted-commit>
sudo cp deploy/systemd/synth-market-rotation-pressure-writer.service /etc/systemd/system/
sudo cp deploy/systemd/synth-market-rotation-pressure-writer.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/synth-market-rotation-pressure-writer.service
systemd-analyze verify /etc/systemd/system/synth-market-rotation-pressure-writer.timer
sudo systemctl daemon-reload
# production authorization file (installed only after a recorded production
# decision, never by this repository change):
#   /etc/synth/writer-capability-market-rotation-pressure-authorization-v1.json
# timer enablement happens only during a separate approved activation step:
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

## Historical Activation Order

```text
1. install and accept devlap writer            -- DONE
2. observe successful writer cycle              -- DONE
3. install and accept Odroid publisher          -- DONE
4. observe multiple complete cycles             -- DONE (3 of 3 real cycles)
```

The publisher was not installed or enabled before the writer had an observed
successful cycle. See "Host Activation & Multi-Cycle Acceptance Evidence"
below for the complete record.

## Host Activation & Multi-Cycle Acceptance Evidence

### Deployed commits

- devlap: `4dce01998328d7215d40451e77eb5e121d8483d3` (origin/main, clean
  worktree, fast-forward only)
- Odroid: `4dce01998328d7215d40451e77eb5e121d8483d3` (origin/main, clean
  worktree, fast-forwarded from `84c78162a5da8c6b4defb1aa43f22c8b402f0347`)

### Last Observed Installed/Enabled/Active Timer Evidence

- `synth-market-rotation-pressure-writer.timer` — devlap — last observed
  installed,
  `enabled`, `active`; `OnCalendar=*:20:00 UTC`, `RandomizedDelaySec=180`,
  `User=gurk`, `WorkingDirectory=/home/gurk/projects/synth-v2`; `ExecStart`
  invokes only `scripts/run_market_rotation_pressure_once.sh --write-db`; no
  remote/reporting/Profit Plan/broker reference.
- `synth-market-rotation-pressure-publisher.timer` — Odroid — last observed
  installed,
  `enabled`, `active`; `OnCalendar=*:35:00 UTC`, `RandomizedDelaySec=180`,
  `User=theone`, `WorkingDirectory=/home/theone/projects/synth-v2`;
  `ExecStart` invokes only
  `scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh`
  (no `--write-db`); no history/pressure-writer invocation, no cross-host
  dependency.
- No duplicate owner existed on either host prior to installation
  (`systemctl list-unit-files` / `systemctl --user list-unit-files` /
  `systemctl list-timers --all`, checked on both hosts before install).

Two `Persistent=true` catch-up invocations occurred at enable time (writer:
started ~14:48 UTC vs. its `14:20:00-14:23:00` window; publisher: started
~16:40:21 UTC vs. its `16:35:00-16:38:00` window). Both were excluded from
the three-cycle count below; they served only as install-time functional
proof that each unit fires and completes successfully.

### Three real qualifying cycles

Acceptance standard per cycle (both writer and publisher): timer
`LastTriggerUSec`, service `ExecMainStartTimestamp`/`ExecMainExitTimestamp`,
`InvocationID`, `Result`, `ExecMainStatus`; journal retrieved by exact
`_SYSTEMD_INVOCATION_ID` match (not `TriggeredBy=` alone, which only proves a
static unit relationship, not which invocation is being inspected);
`ExecMainStartTimestamp` inside the expected `RandomizedDelaySec` window
(writer `HH:20:00-HH:23:00` UTC, publisher `HH:35:00-HH:38:00` UTC);
`LastTriggerUSec` within 5s of `ExecMainStartTimestamp`; published JSON
`header.as_of_ts_utc` equal to the expected cycle hour.

| Cycle | as_of (UTC) | Writer start (UTC) | Writer window check | Writer trigger-match | Publisher start (UTC) | Publisher window check | Publisher trigger-match | DB obs==eligible | Duplicate assets | Duplicate headers | Score bounded | Freshness |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 18:00 | 18:21:02 | PASS | PASS (0s) | 18:36:49 | PASS | PASS (0s) | 114==114 | 0 | 0 | -3.4093 | FRESH |
| 2 | 19:00 | 19:22:19 | PASS | PASS (0s) | 19:37:39 | PASS | PASS (0s) | 111==111 | 0 | 0 | +0.7575 | FRESH |
| 3 | 20:00 | 20:21:19 | PASS | PASS (0s) | 20:35:22 | PASS | PASS (0s) | 110==110 | 0 | 0 | -8.2390 | FRESH |

All three cycles: `Result=success` / `ExecMainStatus=0` on both writer and
publisher; unique `InvocationID` per run; `pressure_snapshot_id` values 11,
12, 13 respectively, each the sole header for its `(venue, as_of_ts_utc,
model_version)`; zero duplicate header groups across all persisted snapshots
at each check.

A fourth candidate hour (17:00 UTC, `pressure_snapshot_id=10`) also ran
successfully with clean DB evidence (114==114 observations, no duplicates,
score -13.3437 bounded), but its live `systemctl` invocation properties were
already overwritten by later cycles before it could be captured. Its
timer-origin reconstruction (journal time-window search, embedded
application timestamps, in-window presence) did not reach the same
evidentiary standard as the three counted cycles above — specifically, its
historical `LastTriggerUSec` could not be retrieved for correlation, since
that property only ever reflects the most recent invocation. It is retained
here as corroborating reference only and is **not** counted toward the
three-cycle requirement.

### Database idempotency and duplicate evidence

- Devlap manual acceptance (pre-timer): writer run, then rerun within the
  same source hour; second run reported `NOOP_ALREADY_COMPLETE` on both the
  rotation-history and rotation-pressure phases (0 rows written); DB state
  unchanged between runs.
- Across all snapshots inspected at each of the three cycle checks:
  `duplicate_header_groups_all_time=0`; `duplicate_asset_rows=0` for every
  inspected `pressure_snapshot_id`.

### Freshness evidence

Odroid published JSON `freshness_state=FRESH` and `status=AVAILABLE` at
every one of the three cycle checks, with `header.as_of_ts_utc` matching the
expected cycle hour exactly each time (`AS_OF_MATCH_CHECK=PASS`).

### Lock evidence

No `LOCK_HELD` journal entries at any writer or publisher invocation
inspected (install catch-ups, the three real cycles, or the reconstructed
17:00 candidate). No overlapping runs observed on either host.

### Disk and journal bounds

- devlap: `943G` avail / `2%` used throughout; journal held at `525.3M`
  across all checks (no growth observed in the acceptance window).
- Odroid: `2.1-2.2G` avail / `86%` used throughout (pre-existing tight
  baseline, unchanged by this lane); journal grew modestly from `183.0M`
  baseline to `199.0M` across the acceptance window, then held steady.

### Rollback verification

The canonical rollback commands (see "Rollback" below) were not exercised,
because no failure occurred that required rollback. Both hosts' installed
unit files, `systemd-analyze verify` output, and `daemon-reload` state were
independently confirmed read-only at each check; the documented rollback
commands target only the two files each lane installed
(`synth-market-rotation-pressure-writer.{service,timer}` on devlap,
`synth-market-rotation-pressure-publisher.{service,timer}` on Odroid) and
remain available unchanged for future use if ever needed.

### Architecture boundaries

At every checked invocation, both units logged
`broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0`
and `selection_engine=none decision_gate=none execution_planner=none
executor=none`; the publisher additionally logged `market_data_writes=0
pressure_writes=0`. No cross-host `Requires=`/`After=` dependency exists
between the two timers. No Profit Plan file was touched.

### Final classification

**PASS.** Three real, independently verified, per-invocation-proven writer→
publisher cycles (18:00, 19:00, 20:00 UTC) meet every criterion in
"Multi-Cycle Acceptance" below.

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

### gurkDB rollback

Only relevant after a future gurkDB installation/activation step; nothing on
gurkDB is installed or enabled by this repository change.

```bash
sudo systemctl disable --now synth-market-rotation-pressure-writer.timer
sudo rm /etc/systemd/system/synth-market-rotation-pressure-writer.service
sudo rm /etc/systemd/system/synth-market-rotation-pressure-writer.timer
sudo systemctl daemon-reload
sudo systemctl reset-failed
systemctl list-timers --all | grep -i rotation-pressure-writer   # expect no match
sudo rm -f /etc/synth/writer-capability-market-rotation-pressure-authorization-v1.json
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
