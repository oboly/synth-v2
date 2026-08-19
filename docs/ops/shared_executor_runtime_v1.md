# Shared executor runtime v1

Status: candidate deployment artifact only. No service has been installed or
enabled, no production migration has been applied, and no broker/private API
operation is authorized.

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```

## Topology and ownership

The single side-neutral runtime consumes the immutable shared handoff only:

```text
approved BUY or SELL execution plan
-> executor_execution_handoff
-> shared-executor-v1 runtime
-> persisted leg submission/reconciliation
```

It does not import a planner, policy, decision gate, automatic BUY/SELL
producer, or a manual-execution transport. The candidate host is `gurkdb`.
The persisted `runtime_owner` is exactly `gurkdb`; the executor identity is
exactly `shared-executor-v1`. Discovery requires all three persisted fields:
`executor_mode`, `runtime_owner`, and `executor_identity`.

The one committed candidate unit pair is:

```text
deploy/systemd/synth-shared-executor-runtime.service
deploy/systemd/synth-shared-executor-runtime.timer
```

It runs as `gurk`, uses `/home/gurk/projects/synth-v2`, invokes the checked-out
`.venv`, reads host-only configuration from
`/etc/synth/shared-executor-runtime-v1.env`, and writes bounded output to the
systemd journal under `synth-shared-executor-runtime`. The file is deliberately
absent from this repository and must contain database configuration plus a
non-secret positive `SYNTH_SHARED_EXECUTOR_OPERATOR_ID`. It must never contain
broker credentials.

The unit and timer are candidate artifacts only: they are not installed,
enabled, or started. The timer is bounded every 15 seconds rather than
long-running so every invocation has one STARTED and exactly one terminal line.

## Mode contract

`DRY_RUN`, `PAPER`, and `LIVE` are distinct canonical persisted modes.

- `DRY_RUN` is the only mode composed by this Phase-J runtime. Its adapter
  records a deterministic `SYNTHETIC_DRY_RUN_NO_BROKER` acknowledgement from
  the immutable leg fields and makes no network, credential, private API, or
  broker call.
- `PAPER` is intentionally unavailable as `PAPER_ADAPTER_NOT_CONFIGURED`.
  The older paper executor uses a different plan/account-state contract; it
  is not a safe shared-paper adapter and must not be reused.
- `LIVE` is intentionally unavailable as `LIVE_RUNTIME_NOT_AUTHORIZED`.
  The dormant handoff-bound Bitvavo adapter, credential binding, kill switch,
  and finite LIVE authority remain separate prerequisites and are not composed
  by this runtime.

The unit sets `DRY_RUN`, `SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED`, and
`SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED` explicitly. Host configuration
must not override those safety values for this deployment class. Its ExecStart
also passes DRY_RUN, `gurkdb`, `shared-executor-v1`, the 60-second lease, and
batch limit explicitly, so the EnvironmentFile can supply only DB settings and
the operator ID rather than changing the ownership tuple.

## Claim, restart, and shutdown

One service invocation is intended at a time; systemd serializes its own
oneshot unit. DB-backed claims protect accidental concurrent/manual consumers.
Discovery is deterministic ascending handoff ID. A 60-second exact-token lease
is acquired atomically, renewed before hydration/submission and before every
placement or reconciliation lookup, and finished only by the still-unexpired
token owner.

On a clean stop between handoffs, the runner exits without a new claim. For an
in-flight handoff, the consumer releases it only when its exact token is still
unexpired; a crash leaves the claim reclaimable after lease expiry. A stale
worker cannot renew or finalize a reclaimed claim.

The runner handles SIGINT/SIGTERM as one `INTERRUPTED` terminal summary. The
candidate unit allows two minutes for its bounded DRY_RUN batch and 15 seconds
for graceful termination. A normal terminal line contains deterministic reason
counts and one bounded `OUTCOME` line per handoff. A claim loss or unresolved
submission is `FINISHED result=incomplete` with exit status zero because the
next timer cycle must recover persisted state; a runner/configuration failure
is `FAILED` and nonzero.

After any restart, persisted legs are authoritative. `PREPARED` can attempt
once; `SUBMISSION_UNCERTAIN` and `RECONCILIATION_REQUIRED` use lookup-only
reconciliation and never re-post. Claim loss before a placement or lookup
makes zero corresponding delegate calls.

## Rollout and rollback

Software deployment and LIVE authorization are separate operations.

Non-live software rollout, only after separate authorization:

1. Apply the required migrations in a reviewed maintenance window.
2. Install the reviewed release, virtualenv, and root-owned host environment.
3. Verify the unit remains disabled and run only a bounded DRY_RUN acceptance.
4. Review journal output, persisted claim/leg state, and duplicate-consumer
   evidence before enabling the DRY_RUN timer.

Rollback is `systemctl disable --now synth-shared-executor-runtime.timer`,
followed by confirmation that no unexpired claims remain. Do not delete or
rearm handoffs/legs; allow the lease to expire and use normal reconciliation.
Removing a unit never authorizes changing broker, credential, account, or LIVE
authority state.

## Remaining production prerequisites

Required before non-live DRY_RUN deployment: reviewed application deployment;
confirmation of the existing credential/binding schema; shared substrate migration
`20260815_shared_executor_substrate_v1.sql`; reconciliation migration
`20260815_executor_reconciliation_evidence_v1.sql`; persisted-consumer
migration `20260819_shared_executor_persisted_consumer_v1.sql`; a selected
runtime operator ID; host-only DB configuration; unit installation; controlled
acceptance; and explicit timer enablement. None are performed by this change.

Read-only gurkDB inventory on 2026-08-19 found
`executor_credential_binding` present and all of the following absent:
`executor_execution_handoff`, `executor_execution_handoff_plan_leg`,
`executor_execution_handoff_consumption`, `executor_execution_leg`,
`executor_live_authority_grant`, and `executor_kill_switch_event`. This is
schema-presence evidence only; it does not inspect credentials or grant any
deployment authority.

LIVE authorization is a later independent operation requiring, at minimum:
the LIVE-authority/kill-switch migration; an authoritative engaged/disengaged
kill-switch state; account protection configuration and lock-state review;
scoped withdrawal-disabled `TRADE_EXECUTION` credential provisioning and
binding; broker write capability; explicit finite LIVE authority; account
`live_trading_enabled` authorization; a handoff-bound LIVE adapter review; and
separate automatic BUY/SELL activation authorization. No item in this list is
granted by software deployment.
