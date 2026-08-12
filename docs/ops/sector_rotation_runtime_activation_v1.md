# Sector Rotation Runtime Activation v1

## Status

**runtime artifacts prepared — not installed — not enabled — not
production-accepted.** This document and the paired wrapper/systemd
artifacts prepare the writer→publisher chain for the merged Sector Rotation
Engine v1 writer (PR history: engine + migration) and the merged Phase C1
Sector Overview publisher (PR #166). No host file, systemd unit, or timer has
been installed, enabled, or started on any host as part of this preparation.
No production authorization has been granted.

```text
latest_persisted_cohort_before_this_preparation=2026-07-16T18:00:00Z
latest_persisted_cohort_after_this_preparation=2026-07-16T18:00:00Z (unchanged)
writer_capability_registry_change=0
host_mutation=0
systemctl_mutation=0
db_writes=0
```

## Chain

```text
canonical public candle writer (public_candle_freshness capability)
    -> Sector Rotation Engine writer (python -m src.research.run_sector_rotation_engine_v1 --write-db)
    -> persisted sector_rotation_snapshot cohort
    -> Sector Overview publisher (python -m src.reporting.run_sector_rotation_dashboard_v1)
    -> static HTML and JSON (sector-overview.html, sector-overview.json)
```

The writer and publisher are separate runtime roles on separate candidate
hosts, connected only through persisted database state:

- the publisher never invokes the writer;
- the writer never invokes the publisher or any reporting module;
- no cross-host SSH orchestration;
- no cross-host systemd `Requires=`/`After=`.

## Ownership and Host Selection

Per `docs/ops/writer_capability_host_ownership_contract_v1.md`, candidate
topology prefers gurkDB for light, account-agnostic public/analytics
writers, and Odroid for read-only publication/dashboard consumers. This
matches the already-accepted pattern for `public_candle_freshness` (writer,
gurkDB) and the Rotation Pressure writer/publisher split (writer candidate
gurkDB, publisher Odroid).

```text
selected_writer_host = gurkdb (candidate; not yet production-authorized)
selected_publisher_host = odroid (candidate; not yet production-authorized)
```

Neither host is authorized as `production_runtime_owner` by this
preparation. Both remain candidate selections only, consistent with
`SELECTED_PENDING_PREFLIGHT` in the ownership contract's lifecycle model.

### Registry onboarding is complete; preflight, acceptance, and authorization remain outstanding

`deploy/ownership/writer_capability_ownership_v1.json` is validated by
`src.operations.validate_writer_capability_ownership_v1`, which enforces a
**closed** `EXPECTED_CAPABILITY_IDS` set (`registry.capabilities must
contain exactly {...}`) and a closed `CAPABILITY_IDENTITY` mapping in the
validator source itself. `sector_rotation_snapshot` is now a member of that
closed set (five capabilities total), and the shared authorization module
(`src/operations/writer_capability_authorization_v1.py`) recognizes its
`capability_identity` as `sector-rotation-snapshot-writer`. Registry
onboarding landed as its own reviewed, non-authorizing change: the registry
entry carries `runtime_lifecycle=SELECTED_PENDING_PREFLIGHT`,
`production_runtime_owner=UNASSIGNED`,
`production_authorization_status=SELECTED_PENDING_PREFLIGHT`,
`acceptance_status=PENDING`, and `acceptance_evidence=null`. No production
authorization, acceptance permit, host mutation, or database write was
performed by that change.

`deploy/ownership/writer_capability_acceptance_permit_v1.schema.json` is a
separate closed contract for the acceptance permit itself (not the
registry) and has been extended in a later, equally non-authorizing change
to recognize the `sector_rotation_snapshot` / `sector-rotation-snapshot-writer`
pair with an exact identity binding. This only allows a structurally valid
ACCEPTANCE-mode permit to be *created and validated*; it grants no
production authorization, assigns no production owner, runs no writer, and
installs or activates no timer.

Consequence: the `ExecStartPre` authorization guard in
`deploy/systemd/synth-sector-rotation-writer.service` still fails closed
with `WRITER_AUTHORIZATION_DENIED` when run today -- this remains the
correct, safe behavior while the capability is `SELECTED_PENDING_PREFLIGHT`
and unowned, not a defect. gurkDB host preflight (step 2 below), controlled
writer acceptance (step 3), and a separate production authorization
decision (step 4) remain required and unresolved before the guard can pass
and any acceptance run described below may proceed.

The publisher is read-only and writes no database table, so it carries no
writer-capability registry entry, matching the existing
`market_rotation_pressure` dashboard publisher precedent (also
unregistered, since only write-capable capabilities are tracked in that
registry).

## Cadence Evidence

```text
source_timer = public candle persistence (Odroid candle-freshness observed cadence)
writer_timer_utc = *:20:00 UTC (RandomizedDelaySec=180)
publisher_timer_utc = *:40:00 UTC (RandomizedDelaySec=180)
minimum_cadence_separation = 17 minutes (writer worst-case start :23:00 -> publisher best-case start :40:00; required minimum 5 minutes)
```

This reuses the same observed hourly-candle-availability evidence already
documented and accepted for the `market_rotation_pressure` writer in
`docs/ops/market_rotation_pressure_runtime_owners_v1.md`: the Odroid
candle-freshness cadence ingests 1h `obs_market_candle` rows on a ~15m30s
cadence, completing persistence by ~HH:11:28. Minute `:20` preserves the
same safety margin used by the already-accepted Rotation Pressure writer.

The publisher margin is widened relative to Rotation Pressure's 12-minute
separation to a 17-minute separation, because the Sector Rotation Engine
computes four windows (`1h`, `4h`, `1d`, `7d`) across ~29 sectors in a single
run and its real production runtime has not yet been observed. **This
cadence has not been re-measured against a live sector-rotation writer run
and must be reconfirmed during controlled acceptance** before the timer
values are treated as final.

`public_candle_freshness` itself is currently `AUTHORIZED_INACTIVE` (not
actively running in production per
`docs/ops/writer_capability_host_ownership_contract_v1.md`). The Sector
Rotation Engine writer's cadence therefore depends on that capability's own
separate activation; this preparation does not activate
`public_candle_freshness` and does not assume it is currently live.

## Dependency Boundaries

```text
writer owner:      research/analytics runtime (gurkDB candidate)
publisher owner:   reporting/GUI runtime (Odroid candidate)
writer reads:      canonical public candles, asset_cluster_membership, sector_definition, BTC/ETH benchmarks
writer writes:      sector_rotation_snapshot only
publisher reads:   sector_rotation_snapshot, sector_definition (read-only)
publisher writes:  sector-overview.html, sector-overview.json (static files only)
```

No selection_engine, decision_gate, execution_planner, executor, broker, or
native-SHORT coupling in either role.

## Output Root and Public Route

```text
output_root = /var/www/html/synth
files       = sector-overview.html, sector-overview.json
public_url_or_path = UNVERIFIED
```

This matches the existing `market_rotation_pressure` dashboard publisher's
output root convention (`scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh`
default), which serves from the Odroid host already hosting
`/var/www/html/synth` for that capability. This preparation does not
introduce a new output root, a new Nginx vhost, or a new public path; it
reuses the existing convention. **The exact live Nginx vhost/document-root
mapping on Odroid, and therefore the exact public URL this file becomes
reachable at, is `UNVERIFIED` and remains an explicit activation blocker.**
Confirming it is a `PREFLIGHT_EXTERNAL` check (per
`docs/ops/writer_capability_host_ownership_contract_v1.md`) that requires a
reachable Odroid host and separately produced external evidence; it is out
of scope for this repository-only preparation and must be proven, not
assumed, before the publisher timer is installed or enabled.

## Duplicate-Owner Check

```text
duplicate_owner_check = no existing sector-rotation writer or publisher wrapper, service, or timer found in the repository prior to this change
```

Verified by exhaustive filename search across `scripts/`, `scripts/odroid/`,
`deploy/systemd/`, and `docs/ops/systemd/` for any `sector_rotation` or
`sector-rotation` artifact before adding these files. None existed.

## Installation Commands (not executed by this preparation)

### gurkDB installation (writer)

```bash
sudo cp deploy/systemd/synth-sector-rotation-writer.service /etc/systemd/system/
sudo cp deploy/systemd/synth-sector-rotation-writer.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/synth-sector-rotation-writer.service
systemd-analyze verify /etc/systemd/system/synth-sector-rotation-writer.timer
sudo systemctl daemon-reload
# sudo systemctl enable --now synth-sector-rotation-writer.timer   -- NOT executed; separate activation decision
```

### Odroid installation (publisher)

```bash
sudo cp docs/ops/systemd/synth-sector-rotation-publisher.service /etc/systemd/system/
sudo cp docs/ops/systemd/synth-sector-rotation-publisher.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/synth-sector-rotation-publisher.service
systemd-analyze verify /etc/systemd/system/synth-sector-rotation-publisher.timer
sudo systemctl daemon-reload
# sudo systemctl enable --now synth-sector-rotation-publisher.timer   -- NOT executed; separate activation decision
```

## Manual Pre-Activation Acceptance (bounded, read-only-for-publisher)

Writer dry-run/validate-only (no DB write):

```bash
python -m src.research.run_sector_rotation_engine_v1 --validate-only
```

Writer bounded manual write run (requires separate explicit authorization
and a valid writer-capability acceptance permit; the shared acceptance-permit
contract now recognizes `sector_rotation_snapshot` /
`sector-rotation-snapshot-writer`, but no permit has been issued and no
acceptance run has occurred):

```bash
bash scripts/run_sector_rotation_engine_once.sh --write-db
```

Publisher bounded manual run to a temporary output directory:

```bash
python -m src.reporting.run_sector_rotation_dashboard_v1 \
  --output-root /tmp/sector-overview-acceptance --output summary
```

Inspect the resulting `sector-overview.json` and `sector-overview.html`
before any further step.

## Activation Order (not performed by this preparation)

### Canonical external host-preflight evidence

The repository-owned producer extends the canonical
`host_preflight_external_evidence_v1` manifest and validator; it is not a
sector-rotation-specific evidence framework. Run it only in a separately
authorized host-preflight window on the candidate gurkDB host. This repository
lane did not run it against production.

Use a private temporary directory and an explicit, non-existing output path:

```bash
evidence_dir="$(mktemp -d /tmp/synth-sector-rotation-preflight.XXXXXX)"
chmod 0700 "${evidence_dir}"
evidence_file="${evidence_dir}/host-preflight-external-evidence.json"
trap 'rm -f "${evidence_file}"; rmdir "${evidence_dir}"' EXIT

python -m src.operations.produce_host_preflight_external_evidence_v1 \
  --capability sector_rotation_snapshot \
  --expected-host gurkdb \
  --expected-commit "$(git rev-parse HEAD)" \
  --checkout-path /home/gurk/projects/synth-v2 \
  --runtime-config-file /home/gurk/projects/synth-v2/.env \
  --output-file "${evidence_file}"
```

The capability profile fixes its outbound target to `api.coingecko.com:443`;
the caller cannot substitute a local or weaker target. The outbound probe opens
only a bounded TCP connection; it sends no HTTP, exchange, broker, or
credential-bearing request. The producer refuses to overwrite an existing
output file. It records no configuration values, command output, hostnames from
configuration, DSNs, passwords, or tokens.

Validate the manifest against the canonical runtime validator before strict
preflight consumes it:

```bash
python -m src.operations.validate_host_preflight_external_evidence_v1 \
  --evidence-file "${evidence_file}" \
  --capability sector_rotation_snapshot \
  --expected-host gurkdb \
  --expected-commit "$(git rev-parse HEAD)" \
  --output json
```

Then run the strict preflight against the same host, checkout, commit, and fresh
evidence file:

```bash
python -m src.operations.run_host_preflight_v1 \
  --capability sector_rotation_snapshot \
  --expected-host gurkdb \
  --expected-commit "$(git rev-parse HEAD)" \
  --checkout-path /home/gurk/projects/synth-v2 \
  --external-evidence-file "${evidence_file}" \
  --output json \
  --strict
```

Missing commands, permissions, configuration fields, connectivity, time-sync
proof, non-empty journald usage evidence, or exact active/enabled
`logrotate.timer` state produce stable `FAIL` reason codes and a nonzero
producer result. No repository-wide retention threshold is asserted. Unreadable
or malformed manifests fail canonical validation, and required `FAIL`, `WARN`,
or `UNVERIFIED` evidence blocks strict preflight. There are no force, skip,
trust, or caller-asserted status options.

A strict preflight `PASS` is read-only readiness evidence only. It does not
accept, authorize, assign, deploy, install, enable, start, or activate
`sector_rotation_snapshot`; the capability remains
`SELECTED_PENDING_PREFLIGHT`, `production_runtime_owner=UNASSIGNED`, and
`acceptance_status=PENDING` until separately reviewed lifecycle steps occur.

1. ~~Onboard `sector_rotation_snapshot` into the writer-capability registry
   (`EXPECTED_CAPABILITY_IDS`, `CAPABILITY_IDENTITY`,
   `deploy/ownership/writer_capability_ownership_v1.json`) as its own
   reviewed change, lifecycle `SELECTED_PENDING_PREFLIGHT`.~~ **Complete.**
   Live gurkDB and Odroid preflight remain unresolved; no acceptance or
   activation is claimed by registry onboarding.
2. In a separately authorized read-only host-preflight window on gurkDB,
   produce, validate, and consume the canonical external-evidence manifest
   using the commands above.
3. Complete controlled writer acceptance on gurkDB: one exact commit, one
   exact host, a real write-capable run, idempotency/reconciliation proof,
   runtime and resource usage, lock behavior, failure behavior, rollback
   readiness.
4. Record production authorization for the writer only after acceptance
   plus separate production-decision evidence (acceptance does not
   self-authorize).
5. Install and enable the writer timer on gurkDB. Observe at least three
   real cycles before considering it settled.
6. Only after the writer has observed real production cycles, install and
   accept the Odroid publisher (mirroring the Rotation Pressure precedent of
   not installing the publisher before the writer has observed cycles).
7. Verify the public `sector-overview.html`/`sector-overview.json` route
   resolves correctly on the live Odroid Nginx configuration.
8. Observe multiple real writer→publisher cycles; verify freshness,
   idempotency, no duplicate writers, and disk/log growth bounds.
9. Mark lifecycle `ACTIVE` only after all of the above, with proof of at
   most one authorized active owner per capability.

Neither timer unit declares `Requires=`/`Wants=` on its own service (only
the canonical `Unit=` directive that names which service the timer
triggers). This is deliberate and correct as far as it goes: it prevents
the service from being pulled in as an ordinary systemd dependency of the
timer unit itself.

**It does not mean starting the timer is harmless or execution-free.**
`systemctl enable <timer>` alone only creates the `[Install]` symlink and
does not start the timer. `systemctl start <timer>` or `systemctl enable
--now <timer>` **starts** the timer, and because both timers set
`Persistent=true`, an *already-established* timer -- one with genuine
persisted trigger history (a stamp file under
`/var/lib/systemd/timers/stamp-<unit>` from a prior run) -- will run the
service immediately on start if its last configured `OnCalendar=` trigger
was missed while the timer was stopped (for example, because the system was
off) -- subject only to the timer's own `RandomizedDelaySec=`, not to any
external gate.

This does **not** extend to a timer's first-ever start. With no persisted
stamp file, systemd has no missed trigger to catch up on merely because
earlier `OnCalendar=` boundaries existed in the abstract; it schedules the
next `OnCalendar=` boundary normally, the same as any other future trigger.
This is what was observed on gurkDB's first writer-timer activation: the
timer was started at 2026-08-12T08:02:22Z and did not fire immediately --
the first service run occurred at the next natural `*:20:00 UTC` boundary
(~08:21:45Z), not at timer-start time.

**Consequence: starting an *already-established* timer (one with persisted
trigger history) must be treated as potentially activating a real writer or
publisher cycle immediately, not as a harmless scheduling-only action --**
even though a timer's genuine first-ever start does not carry that same
immediate-catch-up risk. Removing `Requires=`/`Wants=` only stops the
*service* from being pulled in by ordinary dependency ordering; it does
nothing to stop `Persistent=true` from firing a real run the moment an
established *timer* is restarted. Controlled manual acceptance (steps 2-4
and the bounded manual runs in "Manual Pre-Activation Acceptance" above)
must therefore already be complete, and the writer capability must already
carry a valid production authorization (see "Registry onboarding is a
required, separate follow-up" above) -- **before** either timer is started
or enabled with `--now`, not merely before it is expected to fire on its
next `OnCalendar=` boundary, since a later restart of an established timer
can trigger an immediate run even when the original first-ever start did
not. Manual acceptance remains conceptually separate from scheduled timer
activation (they exercise the service directly, not through the timer), but
that separation is a procedural discipline this document requires, not a
guarantee `Persistent=true` timer semantics provide automatically.

## Observation Requirements

Each activation cycle must be independently verified via
per-invocation `journalctl` correlation (`InvocationID`/`LastTriggerUSec`),
not `TriggeredBy=` alone, per the standard already established in
`docs/ops/market_rotation_pressure_runtime_owners_v1.md`. At minimum,
confirm for each of three consecutive cycles: writer timer window,
publisher timer window, effective separation, writer exit status, publisher
exit status, freshness state, `LOCK_HELD` absence, and no unexpected extra
invocations.

## Rollback

Rollback targets only this lane (`sector_rotation_snapshot` writer and
Sector Overview publisher):

- disable the publisher timer first if publisher-only rollback is needed
  (publication is read-only and reversible without data loss);
- disable the writer timer to stop new cohorts;
- never delete persisted `sector_rotation_snapshot` rows as part of
  rollback;
- a fail-closed freshness outage (publisher republishing `STALE` or
  `DATA_UNAVAILABLE`) is safer than a duplicate writer or a silently stale
  "current" page;
- restoring a previously retired owner, if any, is a separate incident
  decision, never automatic.

No other capability's rollback procedure is affected by this lane's
rollback.

## Stale and DATA_UNAVAILABLE Behavior

The publisher (`src/reporting/sector_rotation_dashboard_v1.py`,
`src/reporting/run_sector_rotation_dashboard_v1.py`) already implements, and
this runtime preparation preserves without modification:

- inspecting only the newest `asof_ts_utc` for the requested venue/model,
  never falling back to an older complete cohort;
- requiring exactly the canonical window set (`1h`, `4h`, `1d`, `7d`);
- failing the whole cohort closed (`DATA_UNAVAILABLE` /
  `INCOMPLETE_LATEST_COHORT`) when any required sector/window cell is
  missing in the newest cohort;
- atomically publishing `DATA_UNAVAILABLE` HTML/JSON, replacing any
  previously published output rather than leaving stale content visible;
- a non-zero exit status after publishing the unavailable state.

The publisher wrapper and systemd unit added here propagate that exit
status unchanged; no wrapper or unit logic treats a `DATA_UNAVAILABLE`
publish as success or suppresses the atomic replacement.

## Forbidden

Same forbidden list as
`docs/ops/writer_capability_host_ownership_contract_v1.md`, plus, specific
to this lane:

- the publisher must never invoke the writer wrapper, service, or Python
  runner;
- the writer must never invoke the publisher wrapper, service, or Python
  runner, or any `src.reporting` module;
- no cross-host `Requires=`/`After=` between the writer and publisher
  units;
- no SSH orchestration in either wrapper or unit;
- no selection_engine, decision_gate, execution_planner, executor, or
  native-SHORT reference in either lane.
