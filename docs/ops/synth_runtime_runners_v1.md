# Synth Runtime Runners V1

## Purpose

Run Synth on the Odroid as a lightweight 24/7 market-data/runtime host.

This document is an ops/design plan only. It does not install services, does not modify active chain behavior, and does not enable paper or live trading.

## Host Roles

Odroid:

- scheduled market-data candle refresh runners
- scheduled feature and signal refresh runners
- optional read-only freshness checks
- optional read-only webview data support

gurkdb:

- MariaDB only
- shared persistence for market observations, features, signals, and later approved runtime snapshots

dev laptop:

- development
- research
- manual reviews
- branch work and deployment review

game PC:

- optional heavy compute / ML only
- not required for initial runtime runners

## Phase Order

Phase 0: inventory.

- Confirm OS, architecture, disk, memory, Python, Git, systemd, network, and DB reachability.
- Confirm repo path, service user, log path, and `.env` location.

Phase 1: repo checkout + venv + env.

- Check out the reviewed branch or release commit.
- Create and test a Python virtual environment.
- Place `.env` outside git or keep it untracked.
- Confirm no secrets are committed.

Phase 2: DB connectivity test.

- Confirm Odroid can reach `gurkdb`.
- Confirm MariaDB credentials load from the approved local source.
- Confirm read/write permissions only for the intended runner tables.

Phase 3: market-data candle refresh runner.

- Start with bounded candle ETL for `1h`, `4h`, and `1d`.
- Treat Bitvavo access as public market-data access only.
- Add freshness checks after each run.

Phase 4: feature/signal refresh runner.

- Refresh `feat_candle`.
- Refresh `signal_engine_state`.
- Keep the runner market-only and account-agnostic.

Phase 5: freshness/reporting runner.

- Report source freshness by table and interval.
- Support read-only webview freshness where useful.
- Do not call direct ticker APIs from renderers.
- Refresh the static paper advice dashboard more frequently than the 4h advice snapshot when useful.
- Keep paper advice setup and policy state sourced from the 4h `paper_advice_observation` snapshot.
- Use 1h `obs_market_candle` rows for display-only DOWN pullback lifecycle badges.

Phase 6: guarded full market-only chain review.

- Review whether a full market-only chain can run safely on Odroid.
- Keep `decision_gate`, `execution_planner`, executor, broker writes, and order paths disabled.
- Avoid duplicate chain writers from dev laptop and Odroid.

Phase 7: first paper strategy candidate lane after stability.

- Only after Odroid runners are stable, select exactly one first paper strategy candidate.
- Paper support is a separate reviewed lane.
- No paper strategy activation happens in this plan.

## Runner Scope

Allowed initial runners:

- candles ETL for `1h`, `4h`, and `1d`
- `feat_candle` refresh
- `signal_engine_state` refresh
- sparse candle diagnostics / freshness checks
- read-only webview data support
- read-only static paper advice dashboard lifecycle refresh

Not initially allowed:

- broker/private write calls
- real orders
- executor
- live `decision_gate`
- paper strategy activation
- duplicated chain writers from dev laptop and Odroid at the same time

## Scheduling Proposal

Prefer systemd timers over cron if possible. Systemd gives clearer logs, dependencies, missed-run behavior, and operational status.

Suggested cadence:

- `1h` candle/features/signals: hourly after candle close with buffer.
- `4h` refresh: every 4 hours after close with buffer.
- `1d` refresh: daily after UTC daily close with buffer.
- freshness check: after each runner.
- paper advice dashboard lifecycle refresh: frequent static HTML render after 1h candle data is fresh.
- log rotation: daily or weekly depending on volume.

Initial timers should use conservative buffers. A late run is safer than a duplicate or partial candle run.

## Locking / Duplicate-Writer Guard

Each writer runner needs a fail-closed lock strategy before service installation.

Acceptable lock options:

- file lock under a host-local runtime directory
- DB advisory lock if the runner already has DB access and the lock lifecycle is explicit

Rules:

- one writer per runner
- acquire lock before any write
- fail closed if the lock cannot be acquired
- logs must show skipped duplicate runs
- do not run duplicate candle/feature/signal writers from dev laptop and Odroid at the same time
- manual runs must either use the same lock or be run only after stopping timers

## Environment

Required checks:

- Python version
- repo path
- venv path
- `.env` location
- DB host reachability
- MariaDB credentials source
- Bitvavo public market-data access
- no broker write credentials needed for initial runners

Secrets rule:

- no secrets in git
- no `.env` commits
- no broker/private write credentials required for the initial Odroid runner scope

## Freshness Checks

Minimum checks:

- `obs_market_candle` max `close_ts_utc` by interval
- `feat_candle` max `close_ts_utc` by interval
- `signal_engine_state` max `signal_ts_utc` by interval
- `strategy_runtime_snapshot` only if a guarded full market-only chain is later allowed

Watchlist note:

- APT, KITE, and SXT are included as analysis-enabled but non-tradeable and non-portfolio assets.
- Their inclusion in analysis data does not grant runtime, selection, advice, decision, execution, or order permission.

Freshness output should make stale or missing intervals visible without guessing. Daily candles may close at UTC midnight and display as a different local calendar date in UI contexts.

## Safety Markers

Every planned runner must declare safety markers in logs or docs before installation.

Candles ETL:

```text
broker_calls=0 except public market-data API only
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

Feature/signal refresh:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

Freshness/reporting runner:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

Read-only webview data support:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

Paper advice dashboard lifecycle refresh:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

The dashboard refresh reads the latest 4h `paper_advice_observation` snapshot and 1h `obs_market_candle` path data. It writes static HTML only. Frequent dashboard refresh does not grant trade permission.

For DOWN pullback rows, `INVALIDATED` means the displayed zone context is stale and upstream recomputation is needed in `execution_zone_context` / paper advice. The dashboard must not recompute zones.

Guarded full market-only chain review:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

## Paper Strategy Follow-Up

Only after Odroid runners are stable:

- select exactly one first paper strategy candidate
- do not use a raw asset as the strategy candidate
- candidate equals `asset + strategy_family + horizon_bucket + setup_context + validation_state`
- `decision_gate` owns account-aware paper permission and sizing
- `execution_planner` produces paper intent only
- simulated fills must be marked paper/simulated
- no live path

This follow-up must be a separate reviewed lane. The Odroid runner plan does not activate paper strategy logic.

## Manual Inventory Commands

Run on the Odroid:

```bash
uname -a
hostname -I
python3 --version
git --version
systemctl --version
df -h
free -h
ping gurkdb
```

If the MySQL/MariaDB client exists:

```bash
mysql --version
mysql -h gurkdb -u "$SYNTH_DB_USER" -p -e "SELECT 1;"
```

Check repo path:

```bash
pwd
git status --short
git rev-parse --show-toplevel
```

## Candidate Systemd Units

Do not create these files in this lane. Intended future unit/timer names:

- `synth-candles-1h.service` / `synth-candles-1h.timer`
- `synth-candles-4h.service` / `synth-candles-4h.timer`
- `synth-candles-1d.service` / `synth-candles-1d.timer`
- `synth-features-signals-1h.service` / `synth-features-signals-1h.timer`
- `synth-features-signals-4h.service` / `synth-features-signals-4h.timer`
- `synth-features-signals-1d.service` / `synth-features-signals-1d.timer`
- `synth-freshness-check.service` / `synth-freshness-check.timer`
- `synth-paper-advice-dashboard-refresh.service` / `synth-paper-advice-dashboard-refresh.timer`

## Boundaries

- Docs / ops plan only.
- No live trading.
- No broker writes.
- No order submission.
- No executor activation.
- No decision_gate activation.
- No paper strategy activation yet.
- No `run_chain_1h.sh`, `run_chain_4h.sh`, or `run_chain_1d.sh` changes.
- No secrets in git.
- No DB schema migrations.
- No asset metadata changes.
- No selection/advice/decision/execution logic changes.
