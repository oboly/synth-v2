# Writer-Capability Host Ownership Contract v1

## Status

Repository and architecture correction only. No host mutation, timer
activation, writer invocation, database mutation, deployment, or host selection
is performed or implied by this document.

```text
host_mutations=0
database_writes=0
writer_invocations=0
deployment=not_performed
systemctl_mutations=0
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
public_price_snapshot.production_runtime_owner=UNASSIGNED
public_candle_freshness.production_runtime_owner=UNASSIGNED
market_rotation_pressure.production_runtime_owner=UNASSIGNED
native_short_4h_chain.production_runtime_owner=UNASSIGNED
```

Rotation Pressure preserves historical facts without granting authority:

```text
acceptance_host=devlap
acceptance_status=ACCEPTED
historical_runtime_assignment.host=devlap
historical_runtime_assignment.status=SUPERSEDED
production_decision_evidence=""
observed_runtime_state=last_observed_active_on_devlap_current_state_UNVERIFIED
```

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
- separate production-decision evidence recorded
- timer proven inactive before activation

`ACTIVE`:

- exactly one `production_runtime_owner`
- `production_authorization_status=AUTHORIZED`
- expected runtime observed active
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
| `public_price_snapshot` | public market-data writer | `scripts/run_market_price_snapshot_once.sh` | UNASSIGNED | UNASSIGNED |
| `public_candle_freshness` | public market-data writer | `scripts/run_market_candle_freshness_once.sh` | UNASSIGNED | UNASSIGNED |
| `market_rotation_pressure` | public market-data writer | `scripts/run_market_rotation_pressure_once.sh` | UNASSIGNED | UNASSIGNED |
| `native_short_4h_chain` | market-only chain | `scripts/run_chain_4h.sh` | UNASSIGNED | UNASSIGNED |

Native SHORT remains independently evaluated from the light DB writers because
it owns CPU-heavy chain stages, source-identity checks, DB writes beyond public
price/candle tables, artifact publication, manifests, and downstream market
state.

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
  --strict
```

Strict mode returns nonzero for any required `FAIL`, `WARN`, or `UNVERIFIED`.
MariaDB, exchange API, DNS, NTP, firewall, secrets, runtime-per-writer,
resource-usage-per-writer, journald/logrotation, and rollback evidence remain
`UNVERIFIED` unless separately proven. Host selection cannot proceed while a
required item is unresolved.

The runner executes the virtualenv Python for import checks, verifies `flock`,
checks the exact checkout commit, verifies hostname, and runs
`systemd-analyze verify` on the selected capability units when available. It
does not read secret values, connect to MariaDB, call exchanges, run writers,
or mutate systemd state.

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

Committed units are explicit devlap-bound candidate or historical artifacts
when they contain:

```text
ConditionHost=devlap
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
