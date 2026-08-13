# Sector Rotation Snapshot gurkDB Acceptance — 2026-08-11

## Outcome

Controlled gurkDB acceptance passed for `sector_rotation_snapshot`. One
`ACCEPTANCE`-mode writer invocation persisted a fresh 116-row cohort
(29 sectors x 4 windows); an immediate repeat invocation proved
idempotency; a concurrent invocation under a held host-local lock proved
fail-closed lock behavior. No production authorization was granted, no
timer was installed or started, and no trading/execution layer was touched.

```text
capability=sector_rotation_snapshot
host=gurkdb
commit=40ef0f838db0e0d0b4d47ebeca7d599bd8bed74a
preflight_local_required_pass=12
preflight_local_required_fail=0
preflight_external=UNVERIFIED by this read-only runner (no separately
  produced external-evidence manifest was supplied); DB connectivity,
  source candle freshness, required tables, and lock writability were
  independently verified read-only, see "Preflight Evidence" below
acceptance_status=ACCEPTED
production_runtime_owner=UNASSIGNED (unchanged)
production_authorization_status=UNASSIGNED (unchanged)
runtime_lifecycle=ACCEPTED_PENDING_CUTOVER
timer_installed=false
timer_enabled=false
timer_active=false
```

## Preflight Evidence

Fresh read-only evidence collected on gurkDB at commit
`40ef0f838db0e0d0b4d47ebeca7d599bd8bed74a` (`git status --short` clean):

`python -m src.operations.run_host_preflight_v1 --capability
sector_rotation_snapshot --expected-host gurkdb --expected-commit
40ef0f838db0e0d0b4d47ebeca7d599bd8bed74a --checkout-path
/home/gurk/projects/synth-v2 --output json` reported every required
`PREFLIGHT_LOCAL` check `PASS` (12/12, 0 FAIL): `capability_identity`,
`host_identity`, `checkout_commit`, `os_and_architecture`, `cpu_and_load`,
`ram_and_swap`, `disk_space_and_inodes`, `python_and_virtualenv`
(`.venv/bin/python`), `capability_module_imports`, `flock`,
`systemd_availability`, `systemd_unit_validation`.

Independently verified read-only (no mutation):

```text
DB connectivity: SELECT 1 -> ok
obs_market_candle (1h) MAX(close_ts_utc) = 2026-08-11T02:00:00Z (fresh)
sector_rotation_snapshot: exists, 116 rows before acceptance
asset_cluster_membership: exists, 473 rows
sector_definition: exists, 29 rows
lock path /tmp/synth-sector-rotation-writer-v1.lock: writable (touch ok)
no competing writer process
no sector-rotation systemd unit previously installed on gurkDB
(systemctl list-unit-files clean before this lane)
no production authorization file present for this capability
```

Authorization guard independently confirmed `PASS` in `ACCEPTANCE` mode
with a valid permit before any writer invocation:

```text
PASS capability=sector_rotation_snapshot service=synth-sector-rotation-writer.service
  mode=ACCEPTANCE authorization_guard=pass host_mutations=0 database_writes=0
  writer_invocations=0 systemctl_mutations=0
```

## Controlled Acceptance Run

An `ACCEPTANCE`-mode permit was issued under the canonical time-bounded
acceptance-permit mechanism
(`deploy/ownership/writer_capability_acceptance_permit_v1.schema.json`,
`src.operations.writer_capability_authorization_v1`), placed at
`/run/synth/writer-acceptance/sector-rotation-snapshot-acceptance-20260811T025025Z.json`
(tmpfs, capability-bound, host-bound, exact-commit-bound,
issued `2026-08-11T02:50:25Z`, expiry `2026-08-11T03:20:25Z`,
`approval_reference="User explicit CONTROLLED WRITER ACCEPTANCE
instruction for sector_rotation_snapshot, gurkdb session 2026-08-11,
bounded ACCEPTANCE-mode permit only, no production authorization or timer
activation"`). Removed after evidence capture (see "Permit Cleanup" below).

```bash
export SYNTH_WRITER_EXECUTION_MODE=ACCEPTANCE
export SYNTH_WRITER_ACCEPTANCE_PERMIT=/run/synth/writer-acceptance/sector-rotation-snapshot-acceptance-20260811T025025Z.json
bash scripts/run_sector_rotation_engine_once.sh --write-db
```

### Cycle 1 (real write)

```text
asof_ts_utc=2026-08-11T02:00:00Z venue=bitvavo windows=1h,4h,1d,7d
RECONCILIATION inserts=116 updates=0 unchanged=0 stale=0
sector_rotation_snapshot: 116 -> 232 rows
exit_status=0 elapsed_sec=4
```

### Cycle 2 (idempotency proof, same permit window)

```text
RECONCILIATION inserts=0 updates=0 unchanged=116 stale=0
row count unchanged: 232
exit_status=0 elapsed_sec=3
```

### Integrity checks

```text
duplicate_headers (sector_code, venue, window_code, asof_ts_utc) = 0
latest cohort row count (asof_ts_utc=2026-08-11T02:00:00Z, venue=bitvavo) = 116
  (29 sectors x 4 windows, matches expected shape)
```

### Runtime / resource usage (ACCEPTANCE stage evidence)

```text
run1_elapsed_sec=4 run2_elapsed_sec=3
compute_phase_elapsed_sec=~2.6 (both cycles)
source_counts: sectors=29 memberships=473 universe_assets=428 candles=109533
```

This is real measured writer runtime, superseding the "not yet observed"
caveat in `docs/ops/sector_rotation_runtime_activation_v1.md`'s cadence
section. At ~3-5s total wrapper runtime, the existing documented
17-minute writer-to-publisher separation margin is unaffected and remains
generously conservative; it is not being changed by this acceptance run.

### Lock behavior

```text
held external flock on /tmp/synth-sector-rotation-writer-v1.lock
concurrent wrapper invocation -> FAILED reason=LOCK_HELD exit_status=75
no database mutation attempted while lock held
lock released cleanly; row counts unchanged before/after (232)
```

### Safety boundary

Every invocation logged `broker_private_calls=0 broker_writes=0
order_submission=0 live_orders=0` and `selection_engine=none
decision_gate=none execution_planner=none executor=none
reporting=none dashboard_publish=none`. No dashboard/publisher file
touched. No SSH or cross-host orchestration performed by the writer.

### Rollback readiness

No systemd unit, service, or timer was installed on gurkDB by this
acceptance lane (`systemctl list-unit-files` clean before and after). No
production authorization file exists for this capability. Rollback
therefore requires no host action: nothing was activated to roll back.
Persisted `sector_rotation_snapshot` rows from this acceptance run are
left in place per the standing rule against deleting persisted market data
as part of rollback; they are ordinary accepted cohort rows, not test
artifacts requiring cleanup.

## Permit Cleanup

The acceptance permit file was removed from
`/run/synth/writer-acceptance/` after evidence capture completed. The
canonical permit root directory (`/run/synth/writer-acceptance`, `gurk:gurk
0700`) remains provisioned by
`deploy/tmpfiles.d/synth-writer-acceptance.conf` for future bounded
acceptance runs.

## Registry Update

`deploy/ownership/writer_capability_ownership_v1.json` updated for
`sector_rotation_snapshot`:

```text
acceptance_host: UNASSIGNED -> gurkdb
acceptance_status: PENDING -> ACCEPTED
acceptance_evidence: null -> {approval_reference, evidence_doc=this file,
  accepted_at_utc=2026-08-11T02:58:34Z, scope="ACCEPTANCE-mode controlled
  writer run, gurkDB, commit 40ef0f8"}
runtime_lifecycle: SELECTED_PENDING_PREFLIGHT -> ACCEPTED_PENDING_CUTOVER
production_authorization_status: SELECTED_PENDING_PREFLIGHT -> UNASSIGNED
production_runtime_owner: UNASSIGNED (unchanged)
```

`ACCEPTED_PENDING_CUTOVER` is a `NO_AUTHORIZATION_LIFECYCLES` member per
`src/operations/validate_writer_capability_ownership_v1.py`: it requires
`production_runtime_owner=UNASSIGNED` and forbids
`production_authorization_status=AUTHORIZED`. This registry change grants
no production authorization, assigns no production owner, and does not
change lifecycle to `AUTHORIZED_INACTIVE` or `ACTIVE`.

## Explicitly Not Done

- No production authorization file created or installed.
- No `production_runtime_owner` assignment.
- No systemd unit, service, or timer installed, enabled, or started on
  gurkDB or any host.
- No lifecycle change to `AUTHORIZED_INACTIVE` or `ACTIVE`.
- No dashboard/publisher activation.
- No trading, decision_gate, execution_planner, or executor path touched.

Remaining steps before production cutover per
`docs/ops/sector_rotation_runtime_activation_v1.md`: a separate explicit
production-authorization decision, systemd unit installation, and observed
real timer cycles -- none of which are performed by this acceptance run.

<a id="production-decision-evidence-20260812"></a>

## Production Decision Evidence — 2026-08-12

The user explicitly authorized the `sector_rotation_snapshot`
production-owner assignment to gurkDB on 2026-08-12, separately from the
2026-08-11 controlled acceptance run recorded above. This decision covers
repository ownership-state changes only: it assigns `production_runtime_owner`
and grants `production_authorization_status`. It does not create or install a
production authorization file, does not install/enable/start the writer
systemd timer, does not activate the publisher, and does not mark the
capability `ACTIVE`.

Basis for this decision:

```text
acceptance_evidence=this document, PR #365, merge commit
  de1187cb4c44f33fc1fca55ba4289bc9fcd7c8c3
acceptance_status=ACCEPTED (unchanged)
acceptance_host=gurkdb (unchanged)
12/12 required PREFLIGHT_LOCAL checks PASS
RUN 1: 116 inserts; RUN 2: 0 inserts / 116 unchanged (idempotent)
29 sectors x 4 windows, duplicate logical rows = 0
lock contention fails closed
measured runtime ~3-4 seconds
no trading/execution path touched
no systemd writer timer installed
```

Based on that separate decision and the acceptance evidence above, this PR
records:

```text
candidate_host=gurkdb
selected_host=gurkdb
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
```

`AUTHORIZED_INACTIVE` does not permit execution by itself. The runtime still
fails closed until a schema-valid production authorization file binds the
exact commit, host, capability, service, and this decision evidence, and
that authorization file has not been created by this change. Timer
installation, activation, and lifecycle `ACTIVE` remain separate, explicitly
authorized steps.

### Safety Counters

```text
writer_invocations=0
database_writes=0
systemctl_mutations=0
timer_changes=0
publisher_changes=0
account_inputs=0
selection_engine=none
decision_gate=none
execution_planner=none
executor=none
broker_writes=0
order_submission=0
```

<a id="writer-natural-cycle-observation-20260812"></a>

## Writer Natural Cycle Observation — 2026-08-12

Per `docs/ops/sector_rotation_runtime_activation_v1.md` step 5 ("Install and
enable the writer timer on gurkDB. Observe at least three real cycles before
considering it settled"), the writer timer
(`synth-sector-rotation-writer.timer`, `OnCalendar=*-*-* *:20:00 UTC`,
`RandomizedDelaySec=180`) was observed across its first three natural
production-authorized firings.

```text
cycle 1: fired 2026-08-12T08:21:45Z, asof=2026-08-12T08:00:00Z
cycle 2: fired ~2026-08-12T09:22:30Z, asof=2026-08-12T09:00:00Z
cycle 3: fired ~2026-08-12T10:21:07Z, asof=2026-08-12T10:00:00Z
```

### DB-side evidence (read-only query, this session, no writes)

```text
asof=2026-08-12T08:00:00Z  116 rows  29 sectors x 4 windows  1 model_version=sector-rotation-v1.0.0
asof=2026-08-12T09:00:00Z  116 rows  29 sectors x 4 windows  1 model_version=sector-rotation-v1.0.0
asof=2026-08-12T10:00:00Z  116 rows  29 sectors x 4 windows  1 model_version=sector-rotation-v1.0.0
duplicate_headers (sector_code, venue, window_code, asof_ts_utc), all 3 cycles = 0
venue consistent = bitvavo (all 3 cycles)
rotation_state distributions per cycle are consistent in shape across all 3
  cycles (no cohort-level DATA_UNAVAILABLE/INCOMPLETE_LATEST_COHORT failure;
  per-cell DATA_UNAVAILABLE/INSUFFICIENT_PARTICIPATION states present at a
  stable rate each cycle, matching cycle 1's already-accepted pattern)
4 additional natural cycles observed beyond the required 3, same shape:
  asof 11:00Z, 12:00Z, 13:00Z, 14:00Z UTC, all 116 rows / 29x4 / 0 duplicates
```

### Journalctl-side evidence (supplied by user from a gurkdb shell session, 2026-08-12)

`sudo journalctl -u synth-sector-rotation-writer.service --since "2026-08-12
08:15:00 UTC" --until "2026-08-12 14:30:00 UTC"` was run directly on gurkdb
and covers all 7 cycles above. Per-cycle correlation via the
Starting/Finished systemd bracket and per-invocation PID grouping (this
agent had no SSH access to gurkdb itself; the log was captured and pasted by
the user from their own gurkdb shell):

```text
cycle    fired(UTC)  wrapper_exit  engine_exit          rows  LOCK_HELD
08:00Z   08:21:45    0             transaction=committed 116  none
09:00Z   09:22:27    0             transaction=committed 116  none
10:00Z   10:21:04    0             transaction=committed 116  none
11:00Z   11:21:27    0             transaction=committed 116  none
12:00Z   12:21:09    0             transaction=committed 116  none
13:00Z   13:20:43    0             transaction=committed 116  none
14:00Z   14:22:37    0             transaction=committed 116  none
```

Every cycle shows exactly one `Starting synth-sector-rotation-writer.service`
/ `Finished synth-sector-rotation-writer.service` systemd bracket (no
unexpected extra invocations), an `authorization_guard=pass` line in
`mode=PRODUCTION` before compute, and `Deactivated successfully` on exit.
`grep -c LOCK_HELD` over the full window = 0. `systemctl status
synth-sector-rotation-writer.timer` confirms `enabled`/`active (waiting)`,
consistent hourly triggering, no unit-file drift.

This satisfies the Observation Requirements' writer-leg items (writer timer
window, writer exit status, `LOCK_HELD` absence, no unexpected extra
invocations) for far more than the required 3 consecutive cycles.

### ACTIVE readiness assessment

**`ACTIVE` is still not justified**, for one remaining reason:

Steps 6-8 of the canonical activation order have not been performed at all:
the Sector Overview publisher lane is not installed, the Nginx/public-route
verification has not been done, and no writer+publisher joint cycles have
been observed. `ACTIVE` per step 9 requires all prior steps, not writer
cycles alone. (The writer-only journalctl gap noted in an earlier draft of
this section is now closed — see above.)

No lifecycle field, registry, or authorization file was changed by this
observation. `runtime_lifecycle=AUTHORIZED_INACTIVE` and
`production_authorization_status=AUTHORIZED` remain unchanged.

Next step: a separate explicit decision to proceed with step 6 (publisher
install) is required before joint-cycle observation, Nginx verification, and
eventual `ACTIVE` consideration can begin.

### Observation Lane Safety Counters

These counters describe only the read-only documentation/observation
activity performed while producing this section (DB read queries, this
edit, git commit) -- they do not describe the writer capability itself.
The 7 real production timer cycles reported above each ran independently
under the writer's own systemd timer, executed one writer invocation, and
committed a 116-row database write; see "DB-side evidence" and the
"Journalctl-side evidence" table above for that record.

```text
OBSERVATION_LANE_MUTATIONS
writer_invocations_in_this_lane=0
database_writes_in_this_lane=0
systemctl_mutations=0
timer_changes=0
publisher_changes=0
account_inputs=0
selection_engine=none
decision_gate=none
execution_planner=none
executor=none
broker_writes=0
order_submission=0
```

<a id="step-8-9-active-cutover-20260813"></a>

## Step 8 Joint-Cycle Observation and Step 9 ACTIVE Decision — 2026-08-13

Per `docs/ops/sector_rotation_runtime_activation_v1.md` steps 6-9. The Odroid
publisher lane (`synth-sector-rotation-publisher.service`/`.timer`) was
installed pre-existing this session, confirmed `disabled`/`inactive` with no
persisted stamp file and no running process, then activated by explicit user
instruction:

```text
sudo systemctl enable --now synth-sector-rotation-publisher.timer
```

run manually by the user on Odroid (this agent has no passwordless sudo on
Odroid; `sudo -n true` required a password). Timer started
`2026-08-12T19:30:57Z`. Consistent with the first-ever-activation semantics
documented above (no persisted stamp before start), the timer did **not**
fire immediately; its first trigger occurred at the next natural
`*:40:00 UTC` boundary (`19:40:57Z`), matching the `synth-sector-rotation-writer.timer`
precedent recorded earlier in this document.

### Step 7 — public route

External authenticated `curl` from devlap against the live Nginx vhost
(`synth.aismid.nl`, HTTP basic auth) returned `200` for
`rotation-pressure.html`, `sector-overview.html`, and `sector-overview.json`
before publisher activation, and after activation reflects
`asof_ts_utc=2026-08-13T05:00:00Z` (user-supplied proof; this agent has no
basic-auth credentials for the vhost in this session). This is corroborated
independently below by direct Odroid filesystem inspection of the same
`sector-overview.json`, which nginx serves unmodified from
`/var/www/html/synth`.

### Step 8 — joint writer→publisher cycles

Read-only `journalctl -u synth-sector-rotation-publisher.service` inspection
and direct read of `/var/www/html/synth/sector-overview.json` on Odroid, this
session, no mutation:

```text
cycle              trigger(UTC)  wrapper_exit  publisher_exit  asof(UTC)             shape        LOCK_HELD  overlap
1 (live-monitored) 19:40:58      0             0               2026-08-12T19:00:00Z  29x4=116/116 none       none
2 (live-monitored) 20:41:03      0             0               2026-08-12T20:00:00Z  29x4=116/116 none       none
3 (live-monitored) 21:42:03      0             0               2026-08-12T21:00:00Z  29x4=116/116 none       none
4                  22:41:53      0             0               2026-08-12T22:00:00Z  29x4=116/116 none       none
5                  23:41:25      0             0               2026-08-12T23:00:00Z  29x4=116/116 none       none
6                  00:43:04      0             0               2026-08-13T00:00:00Z  29x4=116/116 none       none
7                  01:41:16      0             0               2026-08-13T01:00:00Z  29x4=116/116 none       none
8                  02:41:04      0             0               2026-08-13T02:00:00Z  29x4=116/116 none       none
9                  03:41:04      0             0               2026-08-13T03:00:00Z  29x4=116/116 none       none
10                 04:41:27      0             0               2026-08-13T04:00:00Z  29x4=116/116 none       none
11                 05:42:26      0             0               2026-08-13T05:00:00Z  29x4=116/116 none       none
```

Cycles 1-3 were watched live via a persistent `journalctl -f` monitor with
per-invocation correlation (systemd `Starting`/`Finished` bracket + app
`STARTED`/`PUBLISHED`/`FINISHED` lines); cycles 4-11 were confirmed
retroactively from the same unit's journal in a single bounded
`--since '2026-08-12 19:30:00 UTC'` query, cross-checked against
`sector-overview.json`'s current `asof_ts_utc=2026-08-13T05:00:00Z`, which
matches cycle 11 and independently corroborates the user's external route
proof for the same timestamp. Across all 11 cycles: `status=AVAILABLE
freshness=FRESH` every time (no `DATA_UNAVAILABLE`/`INCOMPLETE_LATEST_COHORT`
observed), zero `LOCK_HELD`, exactly one wrapper PID and one python PID per
cycle (no overlapping/duplicate invocation), and `db_writes=0
broker_writes=0 order_submission=0 live_orders=0 decision_gate=none
execution_planner=none executor=none` on every publisher invocation. Output
directory size stable at `27M` (in-place atomic overwrite of the same two
files each cycle, no unbounded growth). `systemctl status
synth-sector-rotation-publisher.timer` at time of writing:
`enabled`/`active (waiting)`, next trigger scheduled normally at
`2026-08-13T06:42:13Z`, no unit-file drift.

`systemctl list-unit-files 'synth-*'` on Odroid shows exactly one
sector-rotation-publisher service/timer pair installed
(`synth-sector-rotation-publisher.service`/`.timer`, both `disabled` before
this session's activation, `enabled` after); no second publisher instance on
this or any other reachable host.

### gurkDB writer health

This agent has no SSH access to gurkdb in this or the prior session (see
"Journalctl-side evidence" above). Direct confirmation remains the
2026-08-12 evidence already recorded in this document: `systemctl status
synth-sector-rotation-writer.timer` returned `enabled`/`active (waiting)`,
and 7 consecutive real production cycles (08:00Z-14:00Z) each showed
`wrapper_exit=0`, `engine_exit=transaction=committed`, 116 rows, zero
`LOCK_HELD`, exactly one systemd bracket per cycle.

That evidence is now extended, not superseded, by the 11 unbroken
publisher-side cycles above: since the publisher fails the whole cohort
closed (`DATA_UNAVAILABLE`) whenever the newest persisted cohort is missing,
incomplete, or stale, 11 consecutive `AVAILABLE`/`FRESH`/`116-of-116` publisher
cycles spanning `2026-08-12T19:00Z` through `2026-08-13T05:00Z` are only
possible if the gurkdb writer itself committed a fresh, complete 116-row
cohort every one of those 11 hours. This is treated here as strong indirect
corroboration of continued writer health across the full observation window,
not as a substitute for a direct gurkdb `systemctl`/`journalctl` check. No
fresh direct gurkdb evidence was collected in this session.

### No account/selection/decision/execution/broker coupling

Confirmed by the safety-counter lines quoted above on every one of the 11
observed publisher invocations, and by the writer-side safety counters
already recorded in the "Safety boundary" and "Production Decision Evidence"
sections of this document. No selection_engine, decision_gate,
execution_planner, executor, or broker reference in either lane; publisher
writes only `sector-overview.html`/`sector-overview.json` static files.

### Step 9 — ACTIVE decision

Steps 1-8 of `docs/ops/sector_rotation_runtime_activation_v1.md` are now
evidenced complete for this lane: registry onboarding, gurkdb preflight and
controlled writer acceptance, production-authorization decision
(`AUTHORIZED_INACTIVE`), writer timer install and >=3 observed natural
cycles, Odroid publisher install and Nginx public-route verification, and
now >=3 (in fact 11) observed joint writer->publisher cycles with freshness,
idempotency (stable 116-row shape every cycle, no duplicate headers reported
by either writer or publisher), no duplicate writer/publisher runtime, and
bounded disk growth.

Exactly one authorized production writer owner exists for
`sector_rotation_snapshot`: `production_runtime_owner=gurkdb`,
`production_authorization_status=AUTHORIZED` (unchanged by this section).
This registry change:

```text
capability=sector_rotation_snapshot
runtime_lifecycle: AUTHORIZED_INACTIVE -> ACTIVE
observed_runtime_state: [] -> [one entry: host=gurkdb,
  unit=synth-sector-rotation-writer.timer, current_state=ACTIVE_OBSERVED,
  authorization_status=AUTHORIZED,
  runtime_state_classification=AUTHORIZED_RUNTIME_OBSERVED,
  evidence_source=this document's "Writer Natural Cycle Observation" section]
production_runtime_owner: gurkdb (unchanged)
production_authorization_status: AUTHORIZED (unchanged)
production_decision_evidence: unchanged
acceptance_status / acceptance_host / acceptance_evidence: unchanged
authorization_guard.authorization_file: unchanged
service / timer / wrapper / cadence: unchanged
```

No other capability in `deploy/ownership/writer_capability_ownership_v1.json`
is touched by this change.

### Step 9 Safety Counters

```text
writer_invocations_in_this_lane=0
database_writes_in_this_lane=0
systemctl_mutations_by_this_agent=0
timer_changes_by_this_agent=0
publisher_changes_by_this_agent=0
registry_lifecycle_field_changes=1 (sector_rotation_snapshot only)
account_inputs=0
selection_engine=none
decision_gate=none
execution_planner=none
executor=none
broker_writes=0
order_submission=0
```

### Explicitly Not Done

- No change to `production_runtime_owner`, `production_authorization_status`,
  the authorization artifact path, service/timer/wrapper identities, or
  cadence for `sector_rotation_snapshot`.
- No other capability's registry entry touched.
- No fresh direct gurkdb SSH evidence collected (see "gurkDB writer health"
  above); ACTIVE readiness for the writer leg relies on the 2026-08-12 direct
  evidence plus this session's indirect freshness-chain corroboration.
- This PR is not merged by this agent.
