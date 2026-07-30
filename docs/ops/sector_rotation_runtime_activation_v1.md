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

### Registry onboarding is a required, separate follow-up

`deploy/ownership/writer_capability_ownership_v1.json` is validated by
`src.operations.validate_writer_capability_ownership_v1`, which enforces a
**closed** `EXPECTED_CAPABILITY_IDS` set (`registry.capabilities must
contain exactly {...}`) and a closed `CAPABILITY_IDENTITY` mapping in the
validator source itself. `sector_rotation_snapshot` is not yet a member of
that closed set. Adding a new writer capability therefore requires editing
the shared authorization validator module
(`src/operations/validate_writer_capability_ownership_v1.py`), not only the
JSON registry file.

That module is the shared, security-critical authorization boundary used by
every writer capability's `ExecStartPre` guard
(`src.operations.verify_writer_capability_authorization_v1`). This
preparation deliberately does **not** modify it: registry onboarding for a
new capability id is a distinct, reviewable change with its own blast
radius and deserves its own focused review, not a bundled edit inside a
"prepare, do not activate" runtime lane.

Consequence: the `ExecStartPre` authorization guard in
`deploy/systemd/synth-sector-rotation-writer.service` references capability
id `sector_rotation_snapshot`, which does not yet exist in the registry.
Run today, the guard fails closed with `WRITER_AUTHORIZATION_DENIED` --
this is the correct, safe behavior for an unregistered capability, not a
defect. **Registry onboarding (adding `sector_rotation_snapshot` to
`EXPECTED_CAPABILITY_IDS`, `CAPABILITY_IDENTITY`, and the registry JSON with
an explicit `SELECTED_PENDING_PREFLIGHT` entry) is a required prerequisite
before the writer service can pass its own authorization guard**, and must
land as its own reviewed change before any acceptance run described below.

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
and, once onboarded, a valid writer-capability acceptance permit):

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

1. Onboard `sector_rotation_snapshot` into the writer-capability registry
   (`EXPECTED_CAPABILITY_IDS`, `CAPABILITY_IDENTITY`,
   `deploy/ownership/writer_capability_ownership_v1.json`) as its own
   reviewed change, lifecycle `SELECTED_PENDING_PREFLIGHT`.
2. Run `python -m src.operations.run_host_preflight_v1 --capability
   sector_rotation_snapshot --expected-host gurkdb ... --strict` on gurkDB.
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
triggers). This is deliberate: `systemctl enable --now` on a timer does not
pull its service in as a dependency and does not execute it immediately.
Controlled manual acceptance (steps 2-4 and the bounded manual runs in
"Manual Pre-Activation Acceptance" above) must be performed as an explicit
`systemctl start <service>` or direct wrapper invocation, entirely separate
from installing or enabling the timer. Enabling a timer only arms future
scheduled cycles at its configured `OnCalendar=`; it is never itself an
acceptance run.

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
