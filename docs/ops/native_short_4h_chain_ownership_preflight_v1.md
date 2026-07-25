# Native SHORT 4h Chain Ownership Preflight v1

## Decision

```text
capability=native_short_4h_chain
recommended_owner=UNASSIGNED
writer_host=UNASSIGNED
publication_host=UNASSIGNED
candidate_host=UNASSIGNED
selected_host=UNASSIGNED
production_authorization=none
activation_authorization=none
scope=BTC_ONLY
```

The repository evidence does not prove one deployable production owner.
`native_short_4h_chain` therefore remains fail-closed and `UNASSIGNED`.

PR #143 is merged as `76e6b8c`, with writer commit-time fencing at
`c20cb7c`. This closes the repository dependency only. It does not select a
host, grant writer authority, prove the installed implementation, or authorize
activation.

## Reconciliation

The canonical capability is one market-only writer chain:

```text
one timer
-> one service
-> scripts/run_chain_4h.sh
-> DB-backed Native SHORT and downstream market-state writes
-> canonical Native SHORT filesystem publication
```

Reporting and linked-profile orchestration are read-only consumers. They own no
Native SHORT DB mutation, snapshot construction, publication fallback, repair
path, or scheduler.

Repository and historical host evidence do not currently form one consistent
deployment contract:

- the only runnable committed pair is
  `deploy/systemd/synth-chain-4h.timer` and
  `deploy/systemd/synth-chain-4h.service`; it is bound to `devlap`,
  `User=gurk`, and `/home/gurk/projects/synth-v2`;
- the observed Odroid implementation used the different
  `synth-4h-market-chain.timer` and `synth-4h-market-chain.service` names,
  `User=theone`, `/home/theone/projects/synth-v2`, and an Odroid-local
  `/var/www/html/synth/_runtime/native_short_context_snapshot_v1/`
  publication root;
- the committed `docs/ops/systemd/synth-4h-market-chain.*` files are now
  non-startable retirement stubs;
- historical Odroid acceptance and a disabled/inactive installed timer do not
  authorize the current committed `synth-chain-4h` implementation;
- no current exact-commit evidence proves DB connectivity, DB writer grants,
  canonical publication-path write authority, or installed unit equivalence
  for either devlap, Odroid, or gurkDB.

## Canonical Devlap Unit Contract

The repository-side devlap candidate is exact and intentionally
pre-activation:

```text
service=synth-chain-4h.service
timer=synth-chain-4h.timer
condition_host=devlap
user=gurk
group=gurk
working_directory=/home/gurk/projects/synth-v2
exec_start=/bin/bash /home/gurk/projects/synth-v2/scripts/run_chain_4h.sh
environment_files=[]
outer_lock=/tmp/synth_chain_4h.lock
outer_lock_scope=HOST_LOCAL
service_unit_file_state=disabled
service_active_state=inactive
timer_unit_file_state=disabled
timer_active_state=inactive
```

No `EnvironmentFile=` directive is permitted. Runtime modules load the
working-directory `.env` themselves; systemd does not inject the full file
into the service environment. The unit pins only repository, lock, paper-mode,
broker/live denial, and `SYNTH_WRITER_EXECUTION_MODE=PRODUCTION` values.

Authorization is fail-closed before the wrapper starts:

```text
/home/gurk/projects/synth-v2/venv/bin/python
  -m src.operations.verify_writer_capability_authorization_v1
  --capability native_short_4h_chain
  --service synth-chain-4h.service
  --checkout-path /home/gurk/projects/synth-v2
  --registry deploy/ownership/writer_capability_ownership_v1.json
```

The fixed outer lock is acquired by `scripts/run_chain_4h.sh` with
`flock -n` for the full chain lifetime. `PrivateTmp=false` keeps manual and
timer-triggered invocations in the same host-local lock namespace. Inherited
repository or lock environment values cannot bypass that lock.

The exact timer contract is:

```text
OnCalendar=*-*-* 00,04,08,12,16,20:12:00 UTC
Persistent=true
RandomizedDelaySec=120
AccuracySec=1s
Unit=synth-chain-4h.service
ConditionHost=devlap
Unit.Requires=[]
Unit.Wants=[]
```

The service is activated only when `Timer.Unit=` fires at timer expiry. The
timer `[Unit]` section must not pull the oneshot into the timer start
transaction through `Requires=` or `Wants=`.

This host-bound repository artifact does not select devlap, assign ownership,
grant production authorization, or authorize activation.

## Installed-Unit Equivalence Preflight

Run the repository preflight from the exact candidate checkout:

```bash
python -m src.operations.run_native_short_systemd_equivalence_preflight_v1 \
  --checkout-path /home/gurk/projects/synth-v2
```

It uses only `systemctl show` and read access to reported fragment paths. It
compares service/timer presence, exact SHA-256 content, drop-ins, user/group,
working directory, `ExecStart`, `ExecStartPre`, environment-file set, pinned
environment, lock visibility, cadence, host conditions, and the required
disabled/inactive state. It also requires the named legacy
`synth-4h-market-chain.service` and `.timer` to be absent. Any missing,
unreadable, enabled, active, drifted, or overridden unit returns
`status=MISMATCH`; the runner does not install or change anything.

The Lane F devlap observation is a mismatch, not canonical evidence:

```text
installed_service=absent
installed_timer=present
installed_timer_sha256=0311364ca21ba7109405b08982282fd270c78c170b4ff63e75a4d698cdb362b4
lane_f_repository_timer_sha256=52b6227bb47f18aaf37828d8c1e48db09e3d7b075e00b59c9a1d887e1abf1fdd
installed_timer_enabled=false
installed_timer_active=false
active_native_short_schedulers=0
legacy_systemd_units=absent
equivalence=MISMATCH
```

Matching cadence does not override absent service state, content drift, or
missing host binding. This focused preflight proves only the installed
system-level unit pair on one host. It does not replace the required
cross-host system/user-systemd, cron, container, and manual-wrapper inventory.

The approximately seven-day-old BTC-only snapshot and
`TRANSIENT_NON_CANONICAL_CONTEXT_AVAILABLE` render state are consumer-visible
staleness evidence. They do not select a writer host and must not trigger a
reporting fallback.

## Single-Scheduler Proof

The repository topology permits exactly one scheduler:

```text
deploy/systemd/synth-chain-4h.timer
-> deploy/systemd/synth-chain-4h.service
-> scripts/run_chain_4h.sh
```

`scripts/run_chain_4h.sh` invokes
`src.market_data.run_native_short_fib_context_snapshot_v1 --publish` directly.
No publication timer is permitted. The retired
`docs/ops/systemd/synth-4h-market-chain.*` stubs are not an alternate
scheduler.

This is repository topology proof only. Production single-scheduler proof
remains blocked until a read-only inventory covers system and user systemd
units, cron, containers, and manually installed wrappers on every candidate
and historical host.

## Publication Ownership

Publication is part of the writer capability today. It cannot be split from
writer execution under the current contract because the canonical publisher
builds and atomically publishes the snapshot from DB truth inside the owning
chain.

A separate publication host would require a new, explicitly designed transport
of an immutable writer-produced bundle plus digest verification and atomic
promotion by a read-only consumer. Until that contract exists, a second host
running the publisher would duplicate canonical truth and violate the
single-scheduler invariant.

Therefore:

```text
publication_host must equal writer_host
```

for any future owner decision under this version of the contract.

## Exact Blocker Contract

All blockers below must be closed for one and the same host at one exact merged
commit before `selected_host` may change from `UNASSIGNED`:

```text
OWNER_EXACT_COMMIT_PREFLIGHT_MISSING
DB_CONNECTIVITY_PROOF_MISSING
DB_WRITER_AUTHORITY_PROOF_MISSING
PUBLICATION_PATH_OWNERSHIP_PROOF_MISSING
EXACT_INSTALLED_UNIT_EQUIVALENCE_MISSING
ALL_HOST_SCHEDULER_INVENTORY_MISSING
ROLLBACK_PROOF_MISSING
WRITER_PUBLICATION_COLOCATION_PROOF_MISSING
```

Required evidence:

1. `OWNER_EXACT_COMMIT_PREFLIGHT_MISSING`
   - candidate checkout contains merged PR #143;
   - checkout HEAD equals the reviewed expected 40-character commit;
   - repository authorization preflight passes without granting production
     authorization.
2. `DB_CONNECTIVITY_PROOF_MISSING`
   - read-only connection succeeds from the candidate service user and exact
     service environment;
   - the resolved database endpoint is recorded without secrets.
3. `DB_WRITER_AUTHORITY_PROOF_MISSING`
   - grants are inspected without mutation and prove only the exact required
     Native SHORT and market-only tables;
   - no account, broker, order, decision, planning, or execution grants are
     introduced.
4. `PUBLICATION_PATH_OWNERSHIP_PROOF_MISSING`
   - one absolute canonical publication root is selected;
   - the candidate service user owns atomic create, fsync, rename, lock, and
     rollback access;
   - reporting consumers have read-only access and no fallback publisher.
5. `EXACT_INSTALLED_UNIT_EQUIVALENCE_MISSING`
   - installed service and timer names, hashes, user, working directory,
     group, command, authorization guard, environment-file set, environment,
     lock, cadence, and `ConditionHost` equal the reviewed host-bound
     repository artifacts;
   - both canonical units are disabled/inactive during pre-activation
     reconciliation;
   - `python -m
     src.operations.run_native_short_systemd_equivalence_preflight_v1` passes;
   - legacy `synth-4h-market-chain.*` units are absent.
6. `ALL_HOST_SCHEDULER_INVENTORY_MISSING`
   - devlap, Odroid, and gurkDB are checked for system/user timers, cron,
     containers, and direct publisher wrappers;
   - exactly zero active schedulers exist before cutover and exactly one named
     scheduler is proposed;
   - no second publisher schedule exists.
7. `ROLLBACK_PROOF_MISSING`
   - rollback disables only the proposed timer and removes its host-local
     authorization;
   - DB ledger/history is not reverted or rewritten;
   - the last digest-valid snapshot remains readable and visibly stale.
8. `WRITER_PUBLICATION_COLOCATION_PROOF_MISSING`
   - the same host and service own DB writer execution and canonical
     publication;
   - otherwise a separately reviewed immutable-bundle transport contract must
     replace this blocker before ownership selection.

Any ambiguity or failed item keeps:

```text
candidate_host=UNASSIGNED
selected_host=UNASSIGNED
production_runtime_owner=UNASSIGNED
production_authorization_status=UNASSIGNED
runtime_lifecycle=UNASSIGNED
```

## Activation Gate

This repository decision grants no production authorization. After all blocker
evidence exists, ownership selection, controlled BTC-only acceptance,
production authorization, and activation remain separate reviewed lifecycle
transitions.

Safety boundary:

```text
database_writes=0
canonical_publication=0
host_mutations=0
timer_mutations=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
multi_asset_promotion=0
reporting_fallback=0
```
