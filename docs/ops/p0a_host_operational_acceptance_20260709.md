# P0-A Host Operational Acceptance — 2026-07-09

## Status

PASS.

This document records the host-level operational acceptance for PR #54 / P0-A containment on the Odroid runtime host.

This is an evidence record, not a replacement for live host checks. Always re-check the host before enabling or changing recurring runtime owners.

## Scope

Accepted scope:

```text
P0-A host operational acceptance for paper-advice lifecycle containment
```

Out of scope:

```text
linked-profile orchestrator deployment
native SHORT runtime-owner deployment
Profit Plan resolver migration
account snapshot orchestration
live ladder repair
server preview
decision_gate
execution_planner
executor
broker writes
order submission
```

## Host evidence

Captured on Odroid.

```text
hostname=odroid
service_user=theone
repo_path=/home/theone/projects/synth-v2
python_venv=/home/theone/projects/synth-v2/venv/bin/python3
python_version=Python 3.12.3
git_branch=main
git_head=73591665efe1ea357287dffc2f39ea9bd4a87a40
working_tree=clean
```

## Required timer isolation

For isolated P0-A measurement, these recurring timers were paused:

```text
synth-paper-advice-lifecycle-refresh.timer=inactive/disabled
synth-linked-profile-runtime-refresh.timer=inactive/disabled
synth-4h-market-chain.timer=inactive/disabled
```

The lifecycle timer remaining blocked is part of the P0-A policy. Linked-profile and 4h timers were paused only to avoid contaminating log-growth measurements.

## Disk and log state

Host inspection showed:

```text
root_filesystem=/dev/mmcblk0p2
root_size=15G
root_used=11G
root_available_approx=3.5G
root_use_pct=76
/var/log_initial=343M
/var/log/journal_initial=216M
/var/log/syslog_initial=122M
journal_initial=200.0M
```

After timer isolation baseline:

```text
root_available_bytes=3671650304
/var/log_bytes=424754199
syslog_size_bytes=143131865
journal_usage=191.0M
```

## Real logging configuration inspected

The host logging configuration was inspected directly.

journald:

```text
systemd-journald=active/static
SystemMaxUse=200M
RuntimeMaxUse=50M
MaxRetentionSec=14day
```

rsyslog:

```text
rsyslog=active/enabled
RepeatedMsgReduction=on
syslog_target=*.*;auth,authpriv.none -/var/log/syslog
```

logrotate:

```text
global=weekly
rotate=4
rsyslog_logrotate_config_present=true
```

## Disk/log health gate evidence

Normal health check:

```text
overall_status=OK
disk_status=OK
writer_used_pct=75.86
syslog_status=OK
normal_health_rc=0
broker_private_calls=0
broker_writes=0
order_submission=0
decision_gate=none
execution_planner=none
executor=none
```

Forced-critical read-only health check:

```text
overall_status=CRITICAL
forced_health_rc=1
broker_private_calls=0
broker_writes=0
order_submission=0
```

Forced-critical wrapper abort:

```text
PHASE_STARTED phase=disk_log_health
overall_status=CRITICAL
result=aborted_disk_health_critical
wrapper_forced_critical_rc=1
```

The wrapper aborted before candle ETL started. The forced-critical output did not contain `STARTED run_candles_etl` or `etl_window_start`.

## Isolated no-write dry-run evidence

A transient systemd unit was used for an isolated dry-run ETL check:

```text
unit=synth-p0a-candles-etl-dryrun-20260709T161714Z.service
result=success
ExecMainCode=0
ExecMainStatus=0
runtime=42.810s
```

The dry-run emitted:

```text
mode=dry_run
logging_mode=bounded
scope=ALL_ENABLED
intervals=15m
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

Bounded logging proof:

```text
task_count=423
progress_every=50
PROGRESS emitted at completed=1,50,100,150,200,250,300,350,400,423
gap_warnings_total=66
no per-gap spam observed
```

No production DB mutation proof:

```text
before_obs_market_candle_count=3190266
after_obs_market_candle_count=3190266
before_obs_market_candle_max_close_ts_utc=2026-07-09 16:00:00
after_obs_market_candle_max_close_ts_utc=2026-07-09 16:00:00
```

Log growth across isolated dry-run:

```text
before_root_available_bytes=3670982656
after_root_available_bytes=3670970368
delta_root_available_bytes=-12288

before_var_log_bytes=425111785
after_var_log_bytes=425120477
delta_var_log_bytes=8692

before_syslog_bytes=143477057
after_syslog_bytes=143483501
delta_syslog_bytes=6444

journal_usage_before=191.0M
journal_usage_after=191.0M
```

Final timer verification after dry-run:

```text
synth-paper-advice-lifecycle-refresh.timer=inactive/disabled
synth-linked-profile-runtime-refresh.timer=inactive/disabled
synth-4h-market-chain.timer=inactive/disabled
```

## Acceptance decision

P0-A host operational acceptance is PASS.

Accepted evidence:

```text
current_host_unit_states_known=true
lifecycle_timer_blocked=true
journald_rsyslog_logrotate_inspected=true
root_and_log_usage_measured=true
disk_log_health_gate_fails_before_etl_under_critical=true
bounded_logging_proven_in_isolated_dry_run=true
production_db_mutation_outside_accepted_test=false
broker_private_calls=0
broker_writes=0
order_submission=0
rollback_path_documented=true
```

## Keep lifecycle timer blocked

The lifecycle timer remains blocked unless a later explicit rollout decision enables it.

Verify blocked state:

```bash
systemctl is-active synth-paper-advice-lifecycle-refresh.timer
systemctl is-enabled synth-paper-advice-lifecycle-refresh.timer
systemctl is-active synth-paper-advice-lifecycle-refresh.service || true
systemctl show synth-paper-advice-lifecycle-refresh.service \
  -p ActiveState \
  -p SubState \
  -p Result \
  -p ExecMainStatus \
  --no-pager
```

Expected blocked state:

```text
synth-paper-advice-lifecycle-refresh.timer=inactive/disabled
synth-paper-advice-lifecycle-refresh.service=inactive/dead
```

## Manual safe check

Run only the read-only disk/log health gate:

```bash
cd /home/theone/projects/synth-v2
/home/theone/projects/synth-v2/venv/bin/python3 -m src.operations.run_runtime_disk_log_health_v1 \
  --path /home/theone/projects/synth-v2 \
  --log-path /var/log/syslog \
  --output table
```

Expected safe markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Rollback

If acceptance-only timer isolation was applied and normal non-P0-A runtime should be restored, re-enable only the runtime owners explicitly approved for the current lane.

Do not re-enable the P0-A lifecycle timer by accident.

Restore linked-profile runtime timer only if that lane remains approved:

```bash
sudo systemctl enable --now synth-linked-profile-runtime-refresh.timer
systemctl is-active synth-linked-profile-runtime-refresh.timer
systemctl is-enabled synth-linked-profile-runtime-refresh.timer
```

Restore 4h market-chain timer only if that lane remains approved:

```bash
sudo systemctl enable --now synth-4h-market-chain.timer
systemctl is-active synth-4h-market-chain.timer
systemctl is-enabled synth-4h-market-chain.timer
```

Keep lifecycle timer blocked:

```bash
sudo systemctl disable --now synth-paper-advice-lifecycle-refresh.timer
systemctl is-active synth-paper-advice-lifecycle-refresh.timer || true
systemctl is-enabled synth-paper-advice-lifecycle-refresh.timer || true
```

## What not to enable

Do not enable any of the following as part of P0-A acceptance:

```text
synth-paper-advice-lifecycle-refresh.timer
native SHORT runtime-owner timers
execution/planner/executor units
live ladder / broker-write units
```

## Evidence required before enabling any recurring owner

Before any recurring owner is enabled or restored, capture:

```text
current git commit
working tree state
unit active/enabled state before change
root filesystem free bytes
/var/log bytes
/var/log/syslog bytes
journal disk usage
expected owner
safety markers for broker_private_calls / broker_writes / order_submission
post-enable unit status
post-run metadata or completion log
rollback command
```

## Notes

P0-A passing does not approve native SHORT runtime deployment, Profit Plan migration, decision gate work, execution planner work, executor work, or broker writes. Those remain separate gated lanes.
