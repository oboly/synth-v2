# Writer-Capability Host Ownership Contract v1

## Status

The contract records `public_price_snapshot`, (since 2026-08-10)
`public_candle_freshness`, and (since 2026-08-08) `market_rotation_pressure`
as active on gurkDB.

```text
public_candle_freshness_acceptance=ACCEPTED
public_candle_freshness_production_runtime_owner=gurkdb
public_candle_freshness_runtime_lifecycle=ACTIVE
public_candle_freshness_timer_active=true
public_candle_freshness_production_authorization_file_present=true
market_rotation_pressure_acceptance=ACCEPTED
market_rotation_pressure_production_runtime_owner=gurkdb
market_rotation_pressure_runtime_lifecycle=ACTIVE
market_rotation_pressure_timer_active=true
market_rotation_pressure_production_authorization_file_present=true
other_capability_changes=0
```

The machine-readable source of truth is
`deploy/ownership/writer_capability_ownership_v1.json`; its schema is
`deploy/ownership/writer_capability_ownership_v1.schema.json`; its executable
semantic validator is
`python -m src.operations.validate_writer_capability_ownership_v1`.

## Historical Correction

Earlier repository state inferred:

```text
devlap acceptance => devlap permanent production owner
```

That inference is invalid. Acceptance proves a capability at one exact commit
on one host. It does not select the permanent production runtime owner, and an
installed or historically active timer does not grant current authority.

Current correction state:

```text
public_price_snapshot.production_runtime_owner=gurkdb
public_candle_freshness.production_runtime_owner=gurkdb
market_rotation_pressure.production_runtime_owner=gurkdb
native_short_4h_chain.production_runtime_owner=devlap
native_short_4h_chain.runtime_lifecycle=ACTIVE
native_short_4h_chain.production_authorization_status=AUTHORIZED
```

Rotation Pressure's prior devlap assignment preserves historical facts
without granting authority (unchanged by the 2026-08-08 gurkDB authorization
below):

```text
historical_runtime_assignment.host=devlap
historical_runtime_assignment.status=SUPERSEDED
observed_runtime_state=last_observed_active_on_devlap_current_state_UNVERIFIED
```

Public Price Snapshot records a separate production decision after successful
gurkDB preflight and acceptance:

```text
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
timer=disabled/inactive
production_authorization_file=absent
```

Public Candle Freshness also records a separate production decision after
successful gurkDB preflight and controlled acceptance, and its gurkDB timer
was subsequently observed enabled and active on 2026-08-10 (discovered
incidentally during an unrelated Sector Rotation preflight, not a dedicated
cutover drill):

```text
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=ACTIVE
timer=enabled/active
production_authorization_file=present
```

See
`docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md#gurkdb-activation-evidence-20260810`
for the full activation observation and its evidence limits.

Market Rotation Pressure also records a separate production decision after
successful gurkDB preflight and controlled acceptance on 2026-08-08 (explicit
user production-cutover authorization for Issue #266), and its gurkDB timer
was enabled the same day:

```text
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=ACTIVE
timer=enabled/active
```

See `docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md` for the
full acceptance and activation evidence.

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

## Core Concepts

```text
candidate_host                 host being considered
selected_host                  host selected for preparation, not authorized
acceptance_host                host where controlled acceptance was proven
acceptance_status              finite acceptance evidence state
production_runtime_owner       host authorized to own the production cadence
production_authorization_status finite authorization state
runtime_lifecycle              finite lifecycle state for the capability
observed_runtime_state         observed installed/running facts, not authority
historical_runtime_assignment  superseded audit fact, not authority
```

Lifecycle states:

```text
UNASSIGNED
SELECTED_PENDING_PREFLIGHT
PREFLIGHT_PASSED
ACCEPTED_PENDING_CUTOVER
AUTHORIZED_INACTIVE
ACTIVE
SUPERSEDED
```

Required invariants:

```text
at_most_one_authorized_active_owner_per_capability=true
exactly_one_authorized_active_owner_required_when_lifecycle_active=true
unassigned_capability_must_have_zero_authorized_owners=true
historical_or_observed_runtime_state_does_not_grant_authorization=true
acceptance_does_not_grant_production_authorization=true
production_authorized_lifecycle_requires_acceptance_and_production_decision_evidence=true
```

`UNASSIGNED` means no canonical production authorization. It does not mean no
timer is installed or running on a host.

## Lifecycle Rules

`UNASSIGNED`:

- `production_runtime_owner=UNASSIGNED`
- `production_authorization_status=UNASSIGNED`
- zero authorized owners
- observed installed runtime, if any, must be non-authorized legacy state

`SELECTED_PENDING_PREFLIGHT`, `PREFLIGHT_PASSED`, and
`ACCEPTED_PENDING_CUTOVER`:

- `selected_host` may be present
- `production_runtime_owner` remains `UNASSIGNED`
- no active authorization exists
- host selection is not production authorization

`AUTHORIZED_INACTIVE`:

- exactly one `production_runtime_owner`
- `production_authorization_status=AUTHORIZED`
- `acceptance_status=ACCEPTED` with structured acceptance evidence
- `acceptance_host` and `selected_host` equal `production_runtime_owner`
- separate production-decision evidence recorded
- no authorized active runtime is observed before activation

`ACTIVE`:

- exactly one `production_runtime_owner`
- `production_authorization_status=AUTHORIZED`
- `acceptance_status=ACCEPTED` with structured acceptance evidence
- `acceptance_host` and `selected_host` equal `production_runtime_owner`
- the authorized runtime for the exact `production_runtime_owner` is observed active
- at most one authorized active owner for the capability

`SUPERSEDED`:

- historical only
- grants no current authority

## Writer-Capability Inventory

The registry records capability identity, host identity, acceptance status,
authorization state, observed runtime facts, systemd artifacts, wrappers,
modules, locks, database writes, artifact publications, and downstream state
changes as separate fields.

Summary:

| capability_id | kind | wrapper | current owner | lifecycle |
|---|---|---|---|---|
| `public_price_snapshot` | public market-data writer | `scripts/run_market_price_snapshot_once.sh` | gurkdb | ACTIVE |
| `public_candle_freshness` | public market-data writer | `scripts/run_market_candle_freshness_once.sh` | gurkdb | ACTIVE |
| `market_rotation_pressure` | public market-data writer | `scripts/run_market_rotation_pressure_once.sh` | gurkdb | ACTIVE |
| `native_short_4h_chain` | market-only chain | `scripts/run_chain_4h.sh` | devlap | ACTIVE |
| `sector_rotation_snapshot` | public market-data writer | `scripts/run_sector_rotation_engine_once.sh` | gurkdb | AUTHORIZED_INACTIVE |

Public Price Snapshot is active on gurkDB.
Public Candle Freshness passed strict gurkDB preflight and two controlled
manual cycles after its enabled-universe mismatch was resolved by disabling
only the eight stale historical-import asset rows. Generic live validation
reports zero mismatch. It is accepted and separately authorized to gurkDB in
`ACTIVE`; the gurkDB timer was observed enabled and running successfully on
2026-08-10. See
`docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md#gurkdb-activation-evidence-20260810`.
Rotation Pressure passed strict gurkDB preflight and a controlled acceptance
run on 2026-08-08 (explicit user production-cutover authorization for Issue
#266), and its gurkDB timer was enabled the same day with a successful first
observed `PRODUCTION`-mode run. It is accepted and separately authorized to
gurkDB in `ACTIVE`. See
`docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md`.
`native_short_4h_chain` is selected, authorized, and active on `devlap`.
Its supported Native SHORT scope remains `BTC_ONLY` in `PAPER` execution mode;
multi-asset and map-level expansion remain `CLOSED`, and live trading remains
`NOT_GRANTED`.

The same existing chain is the repository owner for the market-only canonical
4h Fibonacci dashboard-map publication step. That step covers the existing
public tracked dashboard universe through `canonical_fib_zone_map_v1`; it does
not expand `native_short_map_scope_v1`, inherit Native SHORT permission, or
change the BTC-only execution-related scope. It uses the existing chain timer
and requires the production migration/grant/deployment activation procedure in
`docs/research/canonical_fib_zone_map_v1.md`; this repository change does not
activate it.
`sector_rotation_snapshot` passed strict gurkDB preflight (12/12 required
`PREFLIGHT_LOCAL` PASS) and a controlled acceptance run on 2026-08-11 (116
inserts, idempotent repeat, fail-closed lock behavior; see
`docs/ops/sector_rotation_snapshot_gurkdb_acceptance_20260811.md`). It is
`acceptance_status=ACCEPTED` with `acceptance_host=gurkdb`. A separate
explicit production-authorization decision on 2026-08-12 (see that same
document's Production Decision Evidence section) sets
`production_runtime_owner=gurkdb`, `production_authorization_status=AUTHORIZED`,
and `runtime_lifecycle=AUTHORIZED_INACTIVE`. No production authorization
file has been installed, no systemd unit/timer has been installed, enabled,
or started, and the capability is not `ACTIVE`. See
`docs/ops/sector_rotation_runtime_activation_v1.md` for the remaining
cutover steps.

During review of that authorization decision, `sector_rotation_snapshot`'s
`authorization_guard.authorization_file` was found to collide with the
already-`ACTIVE` `public_price_snapshot` writer's installed host-local
authorization artifact
(`/etc/synth/writer-capability-runtime-authorization-v1.json`, the legacy
generic filename `public_price_snapshot` still uses). Sector Rotation now has
its own dedicated, registry-fixed path,
`/etc/synth/writer-capability-sector-rotation-snapshot-authorization-v1.json`,
matching the naming convention already used by `public_candle_freshness`,
`market_rotation_pressure`, and `native_short_4h_chain`. This corrects the
registry only; no authorization file was installed at either path by this
correction, and `public_price_snapshot`'s existing artifact and `ACTIVE`
authorization were not touched.

Native SHORT remains independently evaluated from the light DB writers because
it owns CPU-heavy chain stages, source-identity checks, DB writes beyond public
price/candle tables, artifact publication, manifests, and downstream market
state.

The repository-only ownership reconciliation and exact fail-closed blocker
contract are recorded in
`docs/ops/native_short_4h_chain_ownership_preflight_v1.md`. Its blocker,
acceptance, production-decision, and scheduled-activation evidence establish
`devlap` as the co-located writer and publication host for the supported
`BTC_ONLY` `PAPER` scope.

## Owner Identity

Wrapper log identity is immutable capability identity. It is not a host name,
not an environment override, and not a substitute for hostname or production
authorization.

The following arbitrary identity override fields are forbidden:

```text
SYNTH_MARKET_PRICE_WRITER_OWNER
SYNTH_MARKET_CANDLE_WRITER_OWNER
SYNTH_ROTATION_PRESSURE_WRITER_OWNER
SYNTH_NATIVE_SHORT_4H_CHAIN_OWNER
```

## Candidate Topology

```text
gurkDB  preferred candidate for light account-agnostic public market-data writers
Odroid  candidate for account runtimes, persisted-state consumers, dashboards
devlap  development and optional acceptance candidate; historical Rotation Pressure assignment SUPERSEDED
```

gurkDB is a preferred candidate, not a proven owner. devlap is a candidate or
historical acceptance host, not the canonical sole owner.

## Host Preflight Contract

The read-only preflight runner is:

```bash
python -m src.operations.run_host_preflight_v1 \
  --capability <capability_id> \
  --expected-host <host> \
  --expected-commit <40-char-sha> \
  --checkout-path <repo-path> \
  [--external-evidence-file <path>] \
  --strict
```

Preflight is stage-aware. Every check declares an explicit evidence stage:

```text
PREFLIGHT_LOCAL     provable by read-only local inspection in this runner
PREFLIGHT_EXTERNAL  provable only by a separately authorized external probe
ACCEPTANCE          provable only by a controlled acceptance run
CUTOVER             provable only by a documented cutover/rollback drill
```

Stage membership:

```text
PREFLIGHT_LOCAL:
  capability_identity, host_identity, checkout_commit, os_and_architecture,
  cpu_and_load, ram_and_swap, disk_space_and_inodes, python_and_virtualenv,
  capability_module_imports, flock, systemd_availability, systemd_unit_validation

PREFLIGHT_EXTERNAL:
  mariadb_connectivity, exchange_api_connectivity, dns, ntp_time_sync,
  journald_logrotation, runtime_configuration, private_exchange_credentials,
  firewall_outbound_connectivity

ACCEPTANCE (deferred, non-blocking during preflight):
  runtime_per_writer, resource_usage_per_writer

CUTOVER (deferred, non-blocking during preflight):
  rollback_capability
```

### Local versus external evidence

`PREFLIGHT_LOCAL` checks are measured here and are always authoritative. The
runner executes the virtualenv Python for import checks, verifies `flock`,
checks the exact checkout commit, verifies hostname, and runs
`systemd-analyze verify` on the selected capability units when available. It
does not read secret values, connect to MariaDB, call exchanges, run writers,
or mutate systemd state.

`PREFLIGHT_EXTERNAL` checks require a database, exchange, network, or host-policy
probe that this read-only runner never performs. They remain `UNVERIFIED` unless
a separately produced, matching external-evidence manifest is supplied with
`--external-evidence-file`. The manifest may fill only permitted
`PREFLIGHT_EXTERNAL` checks; it can never override a local check, and the runner
never executes any command from it. See
`deploy/ownership/host_preflight_external_evidence_v1.schema.json` and
`src/operations/validate_host_preflight_external_evidence_v1.py`.

`runtime_configuration` and `private_exchange_credentials` are separate checks.
Runtime configuration is MariaDB host/user/password/database resolved through
`src.common.db`, plus the runtime config file's presence, ownership, and
permissions; it never reads or returns secret values. "No private exchange key"
is not the same as "no runtime configuration required".

`journald_logrotation` means non-empty read-only `journalctl --disk-usage`
evidence plus exact `active` and `enabled` state for `logrotate.timer`. This is
the adopted host-preflight precedent; it proves journald accessibility and the
host logrotation timer state. It does not claim a universal journal size or
retention-duration bound. Historical host-specific values are not a canonical
threshold.

### Capability-specific external requirements

External requirements are proven from each capability's real call graph, not
inferred from names:

```text
public_price_snapshot:
  mariadb_connectivity=required
  exchange_api_connectivity=required (public bitvavo ticker)
  runtime_configuration=required
  private_exchange_credentials=not required

public_candle_freshness:
  mariadb_connectivity=required
  exchange_api_connectivity=required (public bitvavo candles)
  runtime_configuration=required
  private_exchange_credentials=not required

market_rotation_pressure:
  mariadb_connectivity=required
  exchange_api_connectivity=not required
  runtime_configuration=required
  private_exchange_credentials=not required
```

All three writers reach MariaDB through `src.common.db`, so
`runtime_configuration` is required for every one of them.
`market_rotation_pressure` reads persisted candles from MariaDB and uses only
optional public CoinGecko global context, so it has no exchange-API dependency.
Public exchange endpoints require no private exchange credentials, so
`private_exchange_credentials` is not required for the public writers.

### Bounded evidence freshness

External evidence is time-bounded so a strict `PASS` never rests on indefinitely
reusable evidence. `--max-external-evidence-age-seconds` (default 900) sets the
maximum age. The validator receives an explicit reference time and rejects:

- a manifest or check timestamp in the future beyond a 60s clock-skew allowance;
- a check newer than the manifest timestamp;
- any check older than the configured maximum age (all required checks must
  belong to one bounded evidence run).

JSON output records `external_evidence_observed_at_utc`,
`external_evidence_age_seconds`, and `external_evidence_max_age_seconds`.

### Validation errors and output format

Validation errors never echo manifest-controlled values or arbitrary key names.
They expose only stable error codes, canonical contract field/check names, and
safe structural metadata such as provided type, string length, field count, and
configured limit. This applies to both human-readable table output and JSON
output, so malformed evidence cannot copy a secret into preflight logs.

When `--output json` is selected, every runner outcome emits exactly one JSON
document, including unreadable evidence files, malformed JSON, validation
failure, successful preflight, and strict nonzero results. No text is printed
before or after that document.

The runtime validator and
`deploy/ownership/host_preflight_external_evidence_v1.schema.json` enforce the
same string limits: `detail` is at most 500 characters and `evidence_source` is
non-empty and at most 500 characters. Boundary-length strings are accepted;
longer strings are rejected before evidence normalization.

### Safety markers

The manifest must carry strict safety markers attesting that producing the
evidence performed no mutation:

```text
host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
order_submission=0 broker_writes=0 authorization_created=false deployment_performed=false
```

Read-only probe counters (`database_connections`, `database_read_queries`,
`dns_lookups`, `exchange_public_calls`) may be nonzero because they are the
purpose of this external probe lane. Missing required markers, wrong types,
negative counters, nonzero mutation/write/invocation/order counters,
`authorization_created=true`, `deployment_performed=true`, or unknown fields are
rejected.

### Strict-pass semantics

`--strict` for host preflight requires only `PREFLIGHT_LOCAL` and
`PREFLIGHT_EXTERNAL` checks. It returns zero only when every required preflight
check is `PASS`. Any required `FAIL`, `WARN`, or `UNVERIFIED` returns nonzero.
Deferred `ACCEPTANCE` and `CUTOVER` checks stay visible but never block a strict
preflight; they are never silently marked `PASS`. A required check whose
capability-specific requirement is `false` (for example rotation-pressure
exchange connectivity) stays `UNVERIFIED` without blocking.

The external-evidence manifest is non-authorizing: a strict preflight `PASS`
proves host readiness only. It does not grant production ownership, and it does
not change any lifecycle to `PREFLIGHT_PASSED`. Acceptance and cutover evidence
must not be presented inside a preflight manifest, and no external-evidence file
may contain secrets or credentials.

## Acceptance Procedure

Acceptance is per capability and must prove one exact commit on one exact host:

```text
exact commit
exact host
exact configuration
read-only preflight evidence
dependencies present
controlled writer run only after separate explicit authorization
expected database mutation or artifact publication
idempotency / reconciliation
runtime and resource usage
host-local lock behavior
failure behavior
rollback readiness
```

Acceptance may support a later production authorization decision. It must not
self-authorize production ownership.

## Acceptance Permit Root Provisioning

`verify_writer_execution_authorization`'s `DEFAULT_ACCEPTANCE_PERMIT_ROOT`
(`src/operations/writer_capability_authorization_v1.py`) fixes the ACCEPTANCE-mode
permit root at exactly:

```text
/run/synth/writer-acceptance
```

This path is never environment- or CLI-overridable. `/run` is `tmpfs`, so an
ad hoc `install -d` is lost on reboot. The repository owns a
systemd-tmpfiles config that recreates the canonical root deterministically on
every boot, on any authorized writer host:

```text
deploy/tmpfiles.d/synth-writer-acceptance.conf
```

Contract:

```text
d /run/synth                   0755 root root -
d /run/synth/writer-acceptance 0700 gurk gurk -
```

`/run/synth` stays root-owned, `0755`, and not group/world-writable -- only
the leaf `writer-acceptance` directory is owned by the `gurk` service user
with `0700`, matching the ownership/mode `_validate_writer_file_security`
already requires of every permit file placed under it. This repository
change performs no host installation, no acceptance permit creation, no
writer invocation, and no production authorization.

### Installation (privileged host step, not run by this repository change)

On an authorized writer host (for example `gurkdb`), as an operator with
sudo:

```bash
sudo install -m 0644 deploy/tmpfiles.d/synth-writer-acceptance.conf \
  /etc/tmpfiles.d/synth-writer-acceptance.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/synth-writer-acceptance.conf
```

`systemd-tmpfiles --create` only creates/repairs the declared directories and
fixes their ownership/mode if they already exist with the wrong ones. It does
not start a service or timer, does not create an acceptance permit, and does
not grant any authorization.

### Verification (read-only)

```bash
stat -c '%a %U %G %n' /run/synth /run/synth/writer-acceptance
```

Expected output:

```text
755 root root /run/synth
700 gurk gurk /run/synth/writer-acceptance
```

Because the config is installed under `/etc/tmpfiles.d/`, systemd recreates
both directories with the same ownership and mode on every boot without
further operator action, and `systemd-tmpfiles --create` is safely
re-runnable (idempotent) at any time.

Installation and verification above must not be combined with starting a
writer, issuing an acceptance permit, enabling a timer, or recording any
production authorization -- those remain separate, explicitly authorized
steps under "Acceptance Procedure" and "Cutover Procedure".

## Cutover Procedure

Use this order:

1. identify candidate host
2. record candidate/selected state without production authorization
3. complete read-only preflight
4. prepare host without activating timer
5. complete controlled acceptance after separate authorization
6. inventory every installed runtime instance for the capability
7. disable the old timer
8. prove old timer inactive and disabled
9. record new production authorization
10. activate new timer
11. observe natural scheduled cycles
12. verify persisted-state freshness and consumers
13. mark lifecycle `ACTIVE`
14. prove at most one authorized active owner

If an installed legacy timer is discovered while canonical authorization is
`UNASSIGNED`, classify it as
`OBSERVED_LEGACY_RUNTIME_PENDING_CONTAINMENT` or an equivalent non-authorized
state. Do not silently treat it as inactive.

## Executable Systemd Contract

Committed units are explicit host-bound artifacts. Public Price Snapshot,
Public Candle Freshness, and (since 2026-08-07) Market Rotation Pressure are
bound to gurkDB; remaining candidate/historical units are bound to devlap:

```text
public_price_snapshot ConditionHost=gurkdb
public_candle_freshness ConditionHost=gurkdb
market_rotation_pressure ConditionHost=gurkdb
native_short_4h_chain ConditionHost=devlap
sector_rotation_snapshot ConditionHost=gurkdb
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
```

They must not be described as host-neutral. Every executable writer service
must include the fail-closed guard:

```text
ExecStartPre=python -m src.operations.verify_writer_capability_authorization_v1 ...
```

The guard verifies capability id, actual hostname, registry authorization,
lifecycle, exact checkout commit, service identity, and explicit deployment
authorization configuration. Missing authorization configuration fails closed.

The `systemd_unit_validation` preflight check scopes `systemd-analyze verify`
diagnostics to the supplied capability unit files. Errors or warnings that
reference the selected service/timer remain blocking. Unrelated global unit
diagnostics on the host (for example an `xfs_scrub_all` warning) are retained as
informational metadata and never raise a capability warning. `systemd-analyze`
stderr is not broadly suppressed.

Host-local `flock` locks prevent manual/systemd overlap on one host only. They
cannot prevent cross-host overlap, which is why authorization and cutover guards
are mandatory.

## Rollback Procedure

Rollback must never activate two owners for one capability at the same time.

- Disable the newly activated timer first.
- Prove it inactive and disabled before considering any prior owner.
- Restoring a previously retired owner is a separate incident decision.
- Record exact commits, timer states, database freshness, and absence of
  overlapping owners.
- Never delete persisted market data as part of rollback.

A fail-closed freshness outage is safer than a duplicate writer.

## Forbidden

- No host mutation, deployment, or `systemctl` mutation from this repository
  correction.
- No writer invocation or database write from this repository correction.
- No acceptance evidence used as `production_decision_evidence`.
- No historical or observed runtime assignment used as current authority.
- No reporting, account, dashboard, decision_gate, execution_planner, executor,
  or broker path may start a public market-data writer.
- No two authorized active production owners for one capability.

## Mutation authorization contract

Authorization is enforced at every layer with one shared implementation
(`src.operations.writer_capability_authorization_v1`) and, critically, at the
lowest practical mutation boundary:

- Low-level mutation helpers require a validated, sealed
  `WriterMutationAuthorization` context, constructed only by the shared
  verification flow. This covers candle upsert, market-price persistence,
  rotation history/pressure persistence, the canonical fib-context artifact
  publication, and **every** Native SHORT scope/map SQL helper — the
  materializer-run insert/finalize, observation and lifecycle-event inserts, the
  scope-status projection upsert, and the map generation-event/map-row inserts
  and scope-seed insert. A missing, `None`, plain-dict, or wrong-capability
  context fails closed before the first
  `INSERT`/`UPDATE`/`executemany`/`commit` or any canonical file replacement.
  The capability is determined by the mutation performed, never by a
  caller-supplied identity. The manual Native SHORT map runners authorize
  before writing their initial run row — never a partial run record authorized
  later.
- The production authorization file path is registry-declared
  (`authorization_guard.authorization_file`) and is never environment- or
  CLI-overridable — the public verifier
  (`verify_writer_execution_authorization`) exposes no `authorization_path`
  parameter, and the guard CLI has no `--authorization-file` flag. The file must
  be a regular file, not a symlink, safely owned, and not group/world writable.
- Acceptance permits are capability-bound, host-bound, exact-commit-bound and
  **time-bounded**. A permit may be reused within its valid time window; it is
  **not** single-use and **not** invocation-count-bounded (there is no
  `max_invocations` counter). A permit never grants production authorization.
  Containment of a running timer remains an explicit operator action.
- The production authorization file's `authorized_commit` normally requires
  exact `HEAD` equality (`commit_verification_mode` absent/`EXACT`, the
  default and unchanged legacy semantics for every existing authorization
  file). An authorization file may opt into
  `commit_verification_mode=ANCESTOR` plus `required_branch="main"`, which
  instead requires `authorized_commit` to be an ancestor of (never equal
  to) `HEAD` on the `main` branch -- so one stable file survives every later
  approved fast-forward deploy without a per-commit edit. See
  `docs/ops/native_short_production_promotion_wrapper_v1.md` for the full
  rationale, the `synth-native-short-promote` wrapper that consumes it, and
  the deprecated manual per-commit edit procedure it replaces for
  `native_short_4h_chain`.
- All `*_utc` timestamps use canonical literal UTC (`YYYY-MM-DDTHH:MM:SSZ`).
  A numeric offset (`+01:00`, `-05:00`) or a timezone-less timestamp is rejected;
  offsets are never silently normalized. Validation is not shape-only: the
  semantic validator and the shared parser both parse the timestamp as a real
  calendar date, so impossible dates (`2026-02-31`, `2026-13-01`,
  `2026-01-01T24:00:00Z`) are rejected while valid leap days (`2024-02-29`) pass.
  This applies to ownership acceptance evidence, observed runtime timestamps,
  production authorization timestamps, and acceptance-permit issued/expiry
  timestamps.

## Market-only processing chains

`scripts/run_chain_1h.sh` and `scripts/run_chain_1d.sh` are market-only
processing chains. They do **not** ingest public candles (ingestion is owned by
the `public_candle_freshness` capability); they consume already-persisted
candles and run a read-only persisted-candle freshness gate before any
write-capable stage, failing closed on missing, stale, or DB-unavailable state.
They own zero public-market-data writer capabilities.
