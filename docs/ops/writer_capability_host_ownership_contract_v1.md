# Writer-Capability Host Ownership Contract v1

## Status

Repository and architecture correction only. **No host mutation, timer
activation, writer invocation, database mutation, deployment, or host selection
is performed or implied by this document.** It defines the contract that must be
followed before any of those steps happen.

```text
host_mutations=0
database_writes=0
writer_invocations=0
deployment=not_performed
acceptance_host=UNASSIGNED
production_runtime_owner=UNASSIGNED
gurkDB=UNVERIFIED
devlap=UNVERIFIED
Odroid=UNVERIFIED
```

## Why this document exists (historical correction)

Earlier repository state canonized:

```text
devlap acceptance  =>  devlap permanent production owner
```

That inference was never a separate infrastructure decision. `devlap` was an
acceptance/development convenience host, and the repository then documented it
as the *sole public market-data database writer host* for every public
market-data writer capability. A successful acceptance run proves the
software/runtime on the host it ran on; it does **not** by itself select or
canonize where production must permanently run.

This contract removes that implicit inference. Production ownership is now an
explicit, separately evidenced decision, recorded per writer capability in the
machine-readable registry:

```text
deploy/ownership/writer_capability_ownership_v1.json
```

The single capability that carries a genuine, separately recorded host
acceptance decision is `market_rotation_pressure` (devlap, PR #100 / PR #101,
three real per-invocation-verified cycles — see
`docs/ops/market_rotation_pressure_runtime_owners_v1.md`). Every other public
market-data writer capability is `UNASSIGNED` until an explicit host selection
plus acceptance is recorded here.

## Core concepts

```text
acceptance_host         host on which a writer capability is proven to run
                        correctly at an exact commit and configuration.
production_runtime_owner the single host authorized to run a writer capability
                        on its production timer cadence.
writer_capability       one market-only public-market-data write responsibility
                        with exactly one production_runtime_owner.
host_preflight          read-only host-readiness evaluation; proves nothing is
                        installed, run, or written.
runtime_acceptance      controlled, separately authorized proof of a writer
                        capability on a chosen host at an exact commit.
```

Rules:

- `acceptance_host` and `production_runtime_owner` are separate roles.
- An acceptance run never automatically decides where production permanently
  runs.
- The same host MAY hold both roles, but only when both decisions are
  separately justified and recorded.
- Exactly one active `production_runtime_owner` may exist per writer capability.
- Reporting, dashboards, and account runtimes must never start a
  public-market-data writer or a repair path.
- Host choice must be explicit, technically justified, and operationally
  accepted.

## Writer-capability inventory

Authoritative machine-readable form:
`deploy/ownership/writer_capability_ownership_v1.json`. Summary:

| capability_id | kind | neutral owner identity | wrapper | cadence | production owner |
|---|---|---|---|---|---|
| `public_price_snapshot` | public market-data writer | `public-price-snapshot-writer` | `scripts/run_market_price_snapshot_once.sh` | `*:00/5:00 UTC` | UNASSIGNED |
| `public_candle_freshness` | public market-data writer | `public-candle-freshness-writer` | `scripts/run_market_candle_freshness_once.sh` | `:02,17,32,47 UTC` | UNASSIGNED |
| `market_rotation_pressure` | public market-data writer | `market-rotation-pressure-writer` | `scripts/run_market_rotation_pressure_once.sh` | `:20 UTC` | devlap (ACCEPTED, PR #100/#101) |
| `native_short_4h_chain` | market-only chain | `native-short-4h-chain` | `scripts/run_chain_4h.sh` | `:12 after 4h close UTC` | UNASSIGNED |

Per capability the registry records: current repository owner identity (neutral,
host-independent), acceptance host + status, production owner + status, the
separate production-decision evidence, DB/artifact writes, account/reporting
coupling (must be `false`), cadence, lock, and candidate hosts. Unknown host
facts remain `UNVERIFIED`.

### Native SHORT 4h chain is evaluated separately

`native_short_4h_chain` must **not** be moved automatically together with the
light database writers. It carries CPU, repository-source-identity, publication,
and artifact-manifest dependencies that the light writers do not. Its host
selection assesses CPU, repository, publication, and artifact dependencies on
their own merits.

## Owner identity is host-independent

Owner identity now names the *capability role*, never a host. The wrappers emit
a neutral identity, overridable per capability:

```text
public_price_snapshot     SYNTH_MARKET_PRICE_WRITER_OWNER   default public-price-snapshot-writer
public_candle_freshness   SYNTH_MARKET_CANDLE_WRITER_OWNER  default public-candle-freshness-writer
```

No wrapper, service description, or timer may encode a host name as the writer's
identity. Host identity (systemd `User=` / `WorkingDirectory=`) is an *output of
host selection*, assigned at cutover, not a canonical property of the capability.

## Candidate topology (preference, not outcome)

```text
gurkDB
  light account-agnostic public-market-data writers
  possibly acceptance for those same writers

Odroid
  account runtimes
  persisted-state consumers
  dashboards and publication

devlap
  development
  tests
  optional controlled acceptance
  no implicit permanent production ownership
```

This is a preferred direction only. gurkDB is a **preferred candidate, not a
proven owner**. gurkDB must not be chosen solely because MariaDB runs there, and
devlap must not be retained solely because it is currently documented. Odroid
may remain or become a writer owner only when that is technically the best
choice, not merely because runtimes already run there.

## Host-selection contract

Before a capability gains a `production_runtime_owner`:

1. State the candidate host explicitly.
2. Run the read-only host preflight (below) on that host; require PASS on all
   measurable local checks; unresolved external facts stay `UNVERIFIED` until
   proven.
3. Record a technical justification (CPU/RAM/disk/network/artifact fit) for the
   capability on that host.
4. Obtain operational acceptance of that host for that capability.
5. Only then record `production_runtime_owner` and the separate
   `production_decision_evidence` in the registry.

## Host preflight contract

A generic, read-only preflight must check at least:

```text
host identity
OS and architecture
CPU and load
RAM and swap
disk space and inodes
Python and virtualenv
deployment-artifact strategy
MariaDB connectivity
exchange API connectivity
DNS
NTP / time synchronization
systemd
journald / log rotation
secrets and configuration
locks and overlap protection
runtime per writer
resource usage per writer
firewall / outbound connectivity
rollback capability
```

A read-only preflight runner is provided:

```bash
python -m src.operations.run_host_preflight_v1 --output table
```

It performs **no** installation, **no** writer run, and **no** database write.
Locally measurable facts are reported `PASS`/`WARN`/`FAIL`; anything not proven
read-only on the host stays `UNVERIFIED`. It never probes the exchange or writes
the database.

## Acceptance procedure

Acceptance is per writer capability and must prove, for one exact commit on one
exact host:

```text
exact commit
exact host
exact configuration
dependencies present
read-only preflight PASS
controlled writer run ONLY after separate explicit authorization
expected database mutation
idempotency / reconciliation
runtime and resource usage
lock behavior
failure behavior
rollback readiness
```

An acceptance result MAY recommend that the same host become
`production_runtime_owner`. It MUST NOT self-activate or self-canonize that
ownership. Recording production ownership is the separate cutover step.

## Cutover procedure

1. Record the chosen `production_runtime_owner` explicitly in the registry.
2. Inventory the current owner and timer status for the capability.
3. Prepare the new host without activating any timer.
4. Complete acceptance on the chosen host.
5. Disable the old owner's timer.
6. Prove the old timer inactive and disabled.
7. Only then enable the new timer.
8. Observe natural scheduled cycles.
9. Verify database freshness and downstream consumers.
10. Prove the absence of overlapping owners for the capability.

## Rollback procedure

Rollback must never activate two owners for one capability at the same time.

- Disable the newly activated owner's timer first.
- Prove it inactive and disabled before considering any prior owner.
- Restoring a previously retired owner is a separate incident decision requiring
  its exact pre-cutover commit and proof the new owner is disabled.
- Record exact commits, timer states, database freshness, and the absence of
  overlapping owners.
- Never delete persisted market data as part of rollback.

A fail-closed freshness outage is the accepted safe state during rollback; a
second concurrent owner is not.

## Forbidden

- No SSH host mutations, deployment, or `systemctl` mutations from this lane.
- No writer invocations or database writes from this lane.
- No inventing host facts; unproven host facts stay `UNVERIFIED`.
- No choosing gurkDB solely because MariaDB runs there.
- No retaining devlap solely because it is currently documented.
- No moving account or reporting logic into market writers.
- No two production owners for one capability.
