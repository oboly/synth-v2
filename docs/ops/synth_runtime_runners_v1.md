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
- Use faster `obs_market_candle` rows for display-only DOWN pullback lifecycle badges.
- Start the fast lifecycle runner with `15m` candles; smoke-test `5m` separately before using it operationally.
- Treat the fast lifecycle runner as route-state display support only, not as selection, advice, policy, execution, or order refresh.

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
- paper advice dashboard lifecycle refresh: frequent static HTML render after lifecycle candle data is fresh.
- fast paper advice lifecycle refresh: bounded public candle ETL for `15m` followed by static HTML render; `5m` only after ETL/API smoke test.
- log rotation: daily or weekly depending on volume.

Initial timers should use conservative buffers. A late run is safer than a duplicate or partial candle run.

Template files for review:

```text
docs/ops/systemd/synth-paper-advice-lifecycle-refresh.service
docs/ops/systemd/synth-paper-advice-lifecycle-refresh.timer
docs/ops/systemd/synth-4h-market-chain.service
docs/ops/systemd/synth-4h-market-chain.timer
```

These files are templates only. They are not installed, copied to `/etc/systemd/system`, enabled, or started by this repository lane.

The templates use Odroid-oriented defaults:

```text
User=theone
WorkingDirectory=/home/theone/projects/synth-v2
```

Review the host user, repo path, venv path, `.env` location, and web output directory before copying any unit to `/etc/systemd/system`.

Paper advice lifecycle refresh:

- timer cadence: every 5 minutes
- service command: `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh`
- lifecycle candle interval: `SYNTH_PAPER_ADVICE_LIFECYCLE_INTERVAL=15m`
- output: `/var/www/html/synth/paper-advice.html`
- scope: public candle ETL plus static dashboard render
- excluded: features, signals, selection, advice, policy, decision, execution, orders

4h market chain:

- timer cadence: 12 minutes after each 4h UTC candle close
- service command: `scripts/run_chain_4h.sh`
- source of setup / policy / zone / `paper_advice_observation` snapshots
- must remain market-only with decision/execution disabled
- must not enable broker writes

Logging:

- use systemd journal by default through `StandardOutput=journal` and `StandardError=journal`
- runner scripts already print safety markers
- optional host-local log paths can be added later if journal retention is insufficient

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

Paper advice monitoring checks:

- latest `paper_advice_observation` snapshot timestamp
- latest `obs_market_candle.close_ts_utc` for `15m`
- dashboard rendered timestamp in `/var/www/html/synth/paper-advice.html`
- latest `strategy_runtime_snapshot` for the 4h chain when the chain timer is enabled

Setup-fail diagnostics:

```bash
python -m src.research.run_trade_setup_fail_reason_diagnostic_v1 \
  --venue bitvavo \
  --interval 4h \
  --limit 80 \
  --output table
```

This diagnostic is read-only. It explains `SETUP FAILED` rows from stored paper advice and trade setup filter observations before any setup-filter or policy change is considered.

Watchlist note:

- APT, KITE, and SXT are included as analysis-enabled but non-tradeable and non-portfolio assets.
- Their inclusion in analysis data does not grant runtime, selection, advice, decision, execution, or order permission.

Freshness output should make stale or missing intervals visible without guessing. Daily candles may close at UTC midnight and display as a different local calendar date in UI contexts.

## Safety Markers

Every planned runner must declare safety markers in logs or docs before installation.

Required safety marker set for paper advice monitoring runners:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

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
broker_calls=0 except public market-data API only
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

The standard dashboard refresh reads the latest 4h `paper_advice_observation` snapshot and candle path data. It writes static HTML only. Frequent dashboard refresh does not grant trade permission.

Fast lifecycle refresh:

```text
broker_calls=0 except public market-data API only
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

The fast lifecycle refresh performs bounded public candle ETL for the lifecycle interval, then renders the static paper advice dashboard. It does not refresh features, signals, selection, advice, policy, execution, or order state.

Initial interval:

- `15m` via `SYNTH_PAPER_ADVICE_LIFECYCLE_INTERVAL=15m`.
- `5m` may be used only after a smoke test confirms the ETL/API path supports it cleanly.

Architecture note:

- The 4h chain produces the setup / policy / zone map.
- The fast lifecycle runner updates route / path / invalidation / entry-touch display state from public candles.
- This is a polling bridge toward a future shared `market_trigger_engine`.

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
- `synth-paper-advice-lifecycle-refresh.service` / `synth-paper-advice-lifecycle-refresh.timer`
- `synth-4h-market-chain.service` / `synth-4h-market-chain.timer`
- future `synth-market-trigger-engine.service`

## Market Trigger Engine Path

The future shared market trigger engine is documented in:

```text
docs/architecture/market_trigger_engine_v1.md
```

It is the future public-market trigger layer for dashboard lifecycle state, alerts, and later execution-agent / order-monitor use after explicit decision and execution permission exists.

Boundary:

- no private broker calls
- no broker writes
- no order submission
- no bypass around `decision_gate`
- no replacement for `execution_planner`
- no dashboard zone recomputation

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
