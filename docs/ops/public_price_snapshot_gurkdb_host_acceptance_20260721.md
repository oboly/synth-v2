# Public Price Snapshot gurkDB Host Acceptance — 2026-07-21

## Outcome

`public_price_snapshot` passed exact-commit strict preflight and controlled
acceptance on `gurkdb`. The canonical service and timer are installed but remain
disabled and inactive. No production authorization file exists and no scheduled
cycle was activated in this rollout session.

```text
capability=public_price_snapshot
capability_identity=public-price-snapshot-writer
acceptance_host=gurkdb
accepted_commit=d5f5947eb1ff95558784cb7223ded79689031acc
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
timer_enabled=false
timer_active=false
authorization_file_present=false
```

The repository ownership decision is separate from acceptance. Acceptance alone
does not authorize production execution; see [Production Decision Evidence](#production-decision-evidence).

## Immutable Release and Host

The control-host `origin/main` and the acceptance checkout were both verified at:

```text
d5f5947eb1ff95558784cb7223ded79689031acc
```

gurkDB initially held clean commit
`e79709337e2b00d7c448a320fa4a68af24b862cc`. It was fetched and fast-forwarded
only after `origin/main` matched the immutable release. Post-alignment state:

```text
hostname=gurkdb
user=gurk
checkout=/home/gurk/projects/synth-v2
branch=main
HEAD=d5f5947eb1ff95558784cb7223ded79689031acc
working_tree_clean=true
python=/home/gurk/projects/synth-v2/.venv/bin/python
python_version=3.14.4
disk_free=192G
memory_available=11G
ntp_synchronized=true
```

## Strict Preflight Evidence

Fresh external evidence was observed at `2026-07-21T18:45:05Z` and bound to the
exact host, capability, and commit. The strict preflight ran with an evidence age
of 11.87 seconds.

```text
PREFLIGHT_LOCAL required PASS=12
PREFLIGHT_EXTERNAL required PASS=7
required WARN=0
required FAIL=0
required UNVERIFIED=0
strict_exit_code=0
```

The non-required `private_exchange_credentials` check remained `UNVERIFIED` by
design because this public writer requires no private exchange credentials.
Acceptance and cutover checks remained deferred until their later phases.

External probes proved:

- canonical MariaDB connectivity through one SELECT-only transaction;
- public Bitvavo `BTC-EUR` ticker connectivity over HTTPS;
- DNS and outbound firewall connectivity;
- NTP synchronization;
- journald access and active/enabled `logrotate.timer`;
- `.env` owner `gurk`, mode `0600`, and non-empty required DB settings without
  recording any values.

The external evidence artifact was host-local and was not committed.

## Global Runtime Inventory

Before host preparation and acceptance:

```text
devlap=INACTIVE_UNAUTHORIZED
  system timer=disabled/inactive
  system service=failed/inactive
  production authorization file=absent
  writer processes=0

gurkdb=ABSENT
  system timer=not-found
  system service=not-found
  production authorization file=absent
  writer processes=0

odroid=ABSENT
  market-price system/user units=not-found
  market-price cron entries=0
  market-price writer processes=0
```

```text
authorized_active_owner_count=0
legacy_active_owner_count=0
```

The devlap unit definition was inspected and preserved as historical evidence;
it was not adopted as authorization. The Odroid linked-profile timer remained
inactive, its failed service remained not running, and account-refresh process
count remained zero throughout this task.

## Prepared gurkDB Units

The installed unit definitions match the canonical gurkDB-bound repository
artifacts byte-for-byte:

```text
ConditionHost=gurkdb
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
ExecStartPre=.venv Python + canonical writer-capability authorization guard
ExecStart=bash scripts/run_market_price_snapshot_once.sh
lock=/tmp/synth-market-price-snapshot-writer-v1.lock
cadence=*-*-* *:00/5:00 UTC
```

The installed files are root-owned mode `0644`. `systemd-analyze verify` passed;
the only emitted messages were unrelated host `CPUAccounting` compatibility
notices. The timer and service remained disabled/inactive, and the production
authorization file remained absent.

Pre-install checks:

```text
bash_n=PASS
py_compile=PASS
imports=PASS
systemd_analyze_verify=PASS
focused_tests=157 passed
git_diff_check=PASS
```

The first test attempt exposed gurkDB test-shell configuration only: pytest
temporary files inherited a permissive umask, and subprocess tests could not
find `python` because the venv was not on `PATH`. The production-equivalent
rerun used `umask 0077` and the venv `PATH`; all 157 tests passed without code
changes.

## Controlled Manual Acceptance

A schema-valid, exact-commit, host-bound permit authorized ACCEPTANCE mode only.
It was installed under `/run/synth/writer-acceptance/` as a regular file owned
by `gurk`, mode `0600`. It cannot satisfy PRODUCTION mode.

### Run 1

```text
started=2026-07-21T21:19:21Z
finished=2026-07-21T21:19:22Z
exit_code=0
snapshot_rows=432
database_writes=432
elapsed_sec=0.88
user_cpu_sec=0.64
system_cpu_sec=0.13
max_rss_kb=53188
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```

The immediate bounded SELECT-only audit proved:

```text
latest_snapshot_ts=2026-07-21T21:19:22.232850Z
age_seconds=266.4997
batch_rows=432
distinct_symbols=432
distinct_markets=432
duplicate_symbol_groups=0
market_mismatches=0
invalid_prices=0
source_count=1
id_range=12016278..12016709
```

### Run 2

```text
started=2026-07-21T21:34:20Z
finished=2026-07-21T21:34:21Z
exit_code=0
snapshot_rows=432
database_writes=432
elapsed_sec=1.02
user_cpu_sec=0.70
system_cpu_sec=0.14
max_rss_kb=53300
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```

The second batch was separately persisted and internally consistent:

```text
latest_snapshot_ts=2026-07-21T21:34:20.984057Z
batch_rows=432
distinct_symbols=432
distinct_markets=432
duplicate_symbol_groups=0
market_mismatches=0
invalid_prices=0
source_count=1
id_range=12016710..12017141
```

The run-2 SELECT command was issued immediately but the remote execution result
was delayed by the control transport; its eventual wall-clock age was 1795.32
seconds. Freshness within the 900-second acceptance threshold was independently
proven by run 1. Run 2 proves repeat batch behavior and did not overlap run 1.

The first broad audit attempt grouped the full historical table and hit the
configured read timeout. It made no writes. The replacement audit was bounded
to the newest 1,500 primary-key rows and completed successfully.

## Lock Behavior

With the canonical host-local lock deliberately held, a wrapper invocation
failed before authorization, network, or database work:

```text
observed_at=2026-07-21T22:06:00Z
exit_code=75
reason=LOCK_HELD
public_exchange_calls=0
database_writes=0
```

## Rollback Proof

At `2026-07-21T22:30:53Z`:

```text
timer_enabled=false
timer_active=false
service_active=false
writer_process_count=0
production_authorization_file_present=false
prepared_service_installed=true
prepared_timer_installed=true
accepted_database_rows_preserved=true
```

The pre-install state was `ABSENT`, and the exact validated unit sources were
preserved during preparation. Before activation, rollback is:

1. stop and disable the timer;
2. stop the service;
3. verify writer process count is zero;
4. remove the two prepared units if host preparation must be reversed;
5. run `systemctl daemon-reload`;
6. leave the append-only accepted market snapshots installed;
7. leave the production authorization file absent.

No database rows are deleted during rollback.

## Production Decision Evidence

The user explicitly authorized the `public_price_snapshot` production-owner
rollout to gurkDB on 2026-07-21, separately from the controlled acceptance
permit. That authorization covered repository ownership-state changes,
gurkDB-specific systemd units, the future host-local production authorization
file, and timer activation only after independent review and merge.

Based on that separate decision and the successful gates above, this PR records:

```text
candidate_host=gurkdb
selected_host=gurkdb
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
```

`AUTHORIZED_INACTIVE` does not permit execution by itself. The runtime still
fails closed until a schema-valid production authorization file binds the
merged commit, host, capability, service, and decision evidence.

## Safety Counters

```text
preflight_public_exchange_calls=1
accepted_writer_runs=2
accepted_snapshot_rows_written=864
lock_blocked_wrapper_attempts=1
private_exchange_calls=0
broker_writes=0
order_submission=0
live_orders=0
withdrawals=0
account_runtime_changes=0
odroid_mutations=0
decision_gate_changes=0
execution_planner_changes=0
executor_activation=0
```

## Next Exact Action

Independent review and merge of this ownership PR. After merge, install a
schema-valid production authorization file bound to the exact merge commit,
rerun the canonical production guard, enable/start only the gurkDB timer,
observe a fresh scheduled cycle, and record the lifecycle transition to
`ACTIVE` in a later PR. Only after public-price freshness is proven should the
separate Odroid PR #127 deployment resume.
