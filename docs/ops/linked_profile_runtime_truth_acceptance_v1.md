# Linked-Profile Runtime Truth — G0 Host Acceptance

## Purpose

This document is the release gate for accepting the P0-A paper-advice lifecycle
log-containment change on the real Odroid host before any linked-profile
orchestrator work is installed or any lifecycle timer is re-enabled.

It records required evidence; it does not claim that the host is accepted.

## Current Gate State

**G0 status: NOT ACCEPTED.**

Repository evidence confirms that P0-A containment code was merged through PR
#54. Host acceptance remains open until the evidence items below are captured
from the actual Odroid.

The following policy is absolute until this gate is accepted:

- `synth-paper-advice-lifecycle-refresh.timer` must remain inactive and
  disabled.
- No development or documentation worktree may run the write-capable lifecycle
  ETL against the shared production database.
- No live-trading, broker-write, order-submission, decision-gate,
  execution-planner, or executor behavior is permitted.

## Scope

G0 covers only the P0-A lifecycle log and disk-health containment path:

```text
synth-paper-advice-lifecycle-refresh.timer
-> synth-paper-advice-lifecycle-refresh.service
-> scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh
-> disk/log health gate
-> public 15m candle ETL
```

It does not create or install a linked-profile orchestrator. It does not change
Short Swing rendering, account snapshot ingestion, native SHORT context,
selection, decision, planning, or execution behavior.

## Repository Preconditions

Before any host observation starts, record all of the following in the host
acceptance evidence:

- deployed repository commit SHA;
- proof that the deployed commit contains PR #54 merge commit
  `47bf5967ea967bc886152f425de2f7cc78252df9`;
- effective service user, repository path, virtual environment path, and
  environment-file source;
- installed systemd unit contents, including any drop-ins, rather than only
  repository templates;
- lifecycle timer active state and enabled state as separate values.

A missing or ambiguous item fails G0.

## Required Host Evidence

### 1. Live systemd state

Capture the actual state and unit definitions for:

- `synth-paper-advice-lifecycle-refresh.timer` and `.service`;
- `synth-paper-advice-dashboard-render.timer` and `.service`;
- `synth-account-wallet-refresh@joost.timer` and `@hugo.timer`;
- `synth-account-wallet-dashboard@joost.timer` and `@hugo.timer`;
- `synth-4h-market-chain.timer` and `.service`.

Record timer schedule, most recent result, active state, enabled state, unit
source, and all local drop-ins. Repository templates are not host evidence.

Pass condition for the lifecycle timer:

```text
active_state  = inactive
unit_file_state = disabled
```

Any other lifecycle-timer state fails G0 and must be contained before moving
forward.

### 2. Effective logging and retention configuration

Inspect and archive the effective host configuration for all active sinks that
can receive lifecycle service output:

- journald configuration and drop-ins;
- journal disk usage and journal retention/vacuum policy;
- rsyslog unit definition, main configuration, and included configuration;
- logrotate global configuration and active rsyslog/syslog rules;
- actual ownership, size, rotation history, and filesystem location of the
  relevant syslog files.

Do not infer retention from package defaults or repository documentation. A
missing configuration file is itself evidence and must be recorded as such.

Pass condition: the service output sink and its retention/rotation owner are
known. Unknown ownership fails G0 because bounded application output alone
cannot prove bounded root-filesystem consumption.

### 3. Disk and filesystem baseline

Capture a baseline before any controlled lifecycle service run:

- root filesystem total, used, available, and inode availability;
- `/var/log` total and relevant syslog-file totals;
- journal disk usage;
- `/tmp` total;
- disk-health gate result using the actual runtime repository path and the
  actual lifecycle log path, when one is configured.

Record timestamps in UTC and preserve raw command output with the evidence
bundle. No log deletion, truncation, rotation, database cleanup, or dashboard
artifact deletion is permitted as part of this observation.

G0 cannot pass if the disk-health gate is `CRITICAL` or if root usage is already
trending upward for an unexplained reason.

### 4. Controlled lifecycle output measurement

The lifecycle timer remains disabled throughout this measurement.

Because the current lifecycle wrapper has no no-write mode, any run of that
wrapper against the production database is an explicit Odroid production
operation, not a smoke test. It may be performed only from the deployed Odroid
checkout after the pre-run baseline is captured. It must never be launched from
a development or documentation worktree.

For each controlled run, capture:

- start and finish timestamps;
- service exit result and elapsed time;
- journal lines attributable to the service;
- bytes added to the active service-output sink;
- root filesystem and journal/syslog totals immediately before and after;
- presence of `logging_mode=bounded` and aggregate-only warning output;
- absence of per-market chunk rows, per-gap warning floods, and debug logging;
- disk-health gate result before ETL;
- checkpoint artifact result and final lifecycle summary.

Run enough non-overlapping controlled cycles to demonstrate repeatability. The
evidence must include at least three successful cycles and must state the
observed maximum lines/run, maximum bytes/run, projected bytes/day at the
configured cadence, and the measurement interval.

Pass condition: output growth is bounded and repeatable, no cycle overlaps,
no run reaches `CRITICAL`, and the observed root usage does not show a
positive exhaustion trend attributable to the service.

### 5. Host acceptance decision

G0 is accepted only when all four evidence groups are complete and the recorded
operator decision says `ACCEPTED`.

G0 remains `NOT ACCEPTED` when any of the following is true:

- the lifecycle timer is active or enabled;
- host logging/retention ownership is not known;
- the P0-A merge is not proven deployed;
- a controlled run emits unbounded output or has unexplained disk growth;
- the disk-health gate warns critically or fails before ETL;
- evidence was produced from a non-Odroid worktree or a shared-production
  database run was described as dry or read-only.

## Safe Recovery and Rollback

### G0 containment rollback

On any failed G0 observation:

1. Stop the lifecycle service when it is active.
2. Keep `synth-paper-advice-lifecycle-refresh.timer` disabled and inactive.
3. Preserve logs, checkpoint artifacts, filesystem measurements, and systemd
   state before taking any corrective action.
4. Do not delete market data, database data, research outputs, or dashboard
   artifacts to make the host appear healthy.
5. Do not start or enable the lifecycle timer as a recovery shortcut.

### Dashboard freshness recovery

The current manual linked-profile dashboard recovery path may refresh public
price snapshots and render persisted account snapshots, but it does not refresh
wallet or open-order snapshots itself. It is not a substitute for the future
orchestrator and must not be treated as an ordered account-freshness pipeline.

When account data is stale, the existing private read-only account refresh
runner remains a separate, explicitly invoked stage. Its output must remain
`broker_writes=0` and `order_submission=0`.

### Forward rollback rule

A later linked-profile orchestrator rollback must stop and disable only its own
new timer. It must never reactivate `synth-paper-advice-lifecycle-refresh.timer`
as a fallback.

## Evidence Bundle Location

Store host evidence outside Git secrets and attach or summarize it in the
related rollout PR. The evidence record must include:

```text
host
captured_at_utc
operator
repo_commit
p0_a_ancestor_proof
systemd_state
systemd_unit_sources
logging_config_inventory
filesystem_baseline
controlled_cycle_measurements
acceptance_decision
rollback_exercise
```

## Next Gate

Only after G0 is accepted may the repository receive the P0 linked-profile
orchestrator slice.

That orchestrator must use one explicit owner for:

```text
public market-price snapshot
-> Joost read-only wallet/open-order snapshot
-> Hugo read-only wallet/open-order snapshot
-> renderer reading persisted snapshots only
```

It must not reuse a renderer wrapper that builds or publishes native SHORT
runtime context during the render stage.