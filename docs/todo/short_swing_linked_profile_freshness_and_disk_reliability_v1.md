# TODO — Short Swing Linked-Profile Freshness and Disk Reliability

## Status

```text
open P2 operational / freshness hygiene
```

This lane originated from the 2026-07-05 Odroid disk-exhaustion and stale-static-page incident. Repository implementation has progressed, but installed-host activation and multi-cycle operational acceptance remain separate and must not be inferred from merged templates alone.

## Sources

```text
docs/incidents/2026-07-05_odroid_disk_exhaustion_and_stale_short_swing_data.md
docs/ops/synth_runtime_runners_v1.md
docs/ops/runtime_chain_ownership_v1.md
docs/ops/runtime_freshness_audit_v1.md
docs/ops/linked_profile_runtime_orchestrator_v1.md
docs/architecture/dashboard_time_display_policy_v1.md
```

## Completed repository work

### Disk/log containment

PR #54 merged the bounded candle-ETL logging and pre-run disk/log health gate.
Standing facts:

- default output is bounded;
- verbose per-market/per-gap output is debug-only;
- checkpoint state is persisted separately from journal volume;
- disk pressure can fail visibly before ETL;
- `synth-paper-advice-lifecycle-refresh.timer` must not be re-enabled as an implicit fallback.

The earlier production-connected smoke was write-capable even though inserts were later disproven. Future validation must use an explicit no-write path, isolated database, fixtures, or a separately authorized production operation.

### Linked-profile orchestration candidate

PR #72 merged one repository-level owner candidate for:

```text
disk health
-> public price snapshot
-> linked-profile discovery
-> read-only account refresh per profile
-> persisted-snapshot render per profile
```

The orchestrator keeps public ingestion, account ingestion, and rendering as separate modules and adds one global lock.
Repository systemd files are templates; their presence is not installed-host acceptance.

### Native SHORT runtime line

PR #87 closed and accepted the canonical repository runtime wiring for native SHORT using the existing 4h owner.
Installed service/timer activation was explicitly not performed and remains separate from this lane's repository closure.

## P2-A — Installed-host ownership and activation truth

Before any installed-unit mutation:

1. inspect the actual Odroid checkout, branch/commit, service files, environment, and paths;
2. record `systemctl is-active` and `systemctl is-enabled` for relevant old and new units;
3. prove one owner per pipeline and no unordered duplicate timers;
4. keep the paper-advice lifecycle timer inactive/disabled unless a separate acceptance explicitly changes that decision;
5. run manual one-shots with timers disabled;
6. inspect bounded logs, locks, metadata, and rendered outputs;
7. define exact rollback before enabling or restarting anything.

Installed-host changes require explicit instruction. This docs lane authorizes none.

## P2-B — Absolute freshness authority

The renderer and any account-aware gate must consume persisted observations, not frozen presentation strings.

Required data classes:

```text
market_price_observed_ts_utc
wallet_observed_ts_utc
position_observed_ts_utc
open_orders_observed_ts_utc
dashboard_generated_ts_utc
```

Each class exposes an explicit status:

```text
FRESH
STALE
MISSING
UNAVAILABLE
```

Rules:

- relative age may be displayed only when derived client-side from an absolute timestamp;
- static HTML must never make stopped rendering look newly fresh;
- stale wallet, position, or open-order truth suppresses account-specific ladder/action claims;
- market-only context may remain visible under its own freshness contract;
- `decision_gate` consumes persisted freshness authority or a pure evaluator over it, never renderer HTML/JSON.

This requirement is a prerequisite for safe Profit Plan Live Ladder authority but remains operationally owned here rather than duplicated in its guardrail history file.

## P2-C — Multi-cycle Odroid acceptance

Measure over several consecutive real cycles:

- runtime duration versus cadence;
- non-overlap and lock behavior;
- per-stage success/failure metadata;
- Joost and Hugo snapshot/render freshness;
- filesystem free space trend;
- journal/log growth in bytes per day;
- stale-source fail-closed behavior;
- rollback behavior.

A single manual run is not multi-cycle acceptance.

## P2-D — Deferred runtime-host capacity decision

The Odroid remains the current runtime host until explicitly changed.
A later dedicated runtime server may be evaluated, but the database host and runtime host should remain separate failure domains.
Host replacement does not substitute for fixing ownership, freshness, and logging on the current host.

## Boundary

```text
public market ingestion    = market-only, account-agnostic
account snapshot ingestion = authenticated read-only persistence only
renderer                   = persisted snapshots only
selection_engine           = unchanged
decision_gate              = account-aware freshness permission only
execution_planner          = unchanged
executor                   = unchanged
```

Forbidden:

- live trading;
- broker writes;
- order submission;
- private broker calls from rendering;
- rendering that builds native market truth;
- systemd/timer mutation without explicit instruction;
- collapsing runtime and database onto one failure domain as incident remediation.

## Definition of done

- installed owner state is documented and non-duplicated;
- absolute timestamps/statuses prevent frozen freshness;
- both linked profiles meet the chosen SLO across a multi-hour window;
- disk/log growth is measured and bounded;
- rollback is documented and exercised safely;
- no trading or execution layer was touched.
