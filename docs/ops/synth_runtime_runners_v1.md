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
- Treat `signal_engine_state` as the canonical live signal output table.
- Treat legacy `signal_state` as non-canonical unless a separate reviewed lane
  explicitly revives it.

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
- separated refresh-vs-render ownership for dashboard support

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
- paper advice lifecycle market refresh: bounded public candle ETL for `15m`; `5m` only after ETL/API smoke test.
- paper advice dashboard render: frequent static HTML render after lifecycle candle data is fresh.
- MVP market context refresh: market-price snapshot plus bounded market-only lifecycle refresh before cockpit render.
- log rotation: daily or weekly depending on volume.

Initial timers should use conservative buffers. A late run is safer than a duplicate or partial candle run.

Template files for review:

```text
docs/ops/systemd/synth-paper-advice-lifecycle-refresh.service
docs/ops/systemd/synth-paper-advice-lifecycle-refresh.timer
docs/ops/systemd/synth-paper-advice-dashboard-render.service
docs/ops/systemd/synth-paper-advice-dashboard-render.timer
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

Paper advice lifecycle market refresh:

- timer cadence: every 5 minutes (**timer currently stopped; see P0-A status
  below and the incident record before assuming any live state**)
- service command: `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh`
- lifecycle candle interval: `SYNTH_PAPER_ADVICE_LIFECYCLE_INTERVAL=15m`
- scope: public candle ETL only
- excluded: dashboard render, features, signals, selection, advice, policy, decision, execution, orders

### P0-A: Bounded Logging and Disk/Log Health (2026-07-05 incident follow-up)

Implemented in this pass. Full detail, acceptance evidence, and remaining
verification gaps are tracked in
`docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md`
(P0-A). Summary for operators:

**Traced log path** (verified: live query against the production DB found
429 enabled assets; a partial local smoke run against the same DB confirmed
the exact behavior below):

```text
synth-paper-advice-lifecycle-refresh.timer (every 5 min)
-> scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh
-> python -m src.etl.bitvavo.run_candles_etl --interval 15m (no --asset filter)
-> run_candles_etl.py: loops ALL enabled assets x 1 interval (429 tasks/cycle)
-> etl_bitvavo_candles.py: per-asset chunk/gap/done prints
```

Before this fix, this chain unconditionally printed at least ~6 lines per
enabled asset per 5-minute cycle (~2,574+ lines/cycle at 429 assets, before
any gap warnings), a strong candidate contributor to the 2026-07-05
`/var/log/syslog` growth. This remains a strong, code-and-measurement-backed
lead, not a byte-for-byte proof of that specific incident's total growth.

**Bounded default logging** (`src/etl/bitvavo/run_candles_etl.py`,
`src/etl/bitvavo/etl_bitvavo_candles.py`):

- Default mode emits phase start/end, a bounded heartbeat (first task, every
  `SYNTH_CANDLES_ETL_PROGRESS_EVERY` tasks — default 50 — and the last task),
  aggregate counts, elapsed duration, and a concise failure summary. No
  per-market candle chunk rows, no repeated per-gap warning lines, and no
  per-commit checkpoint stdout/syslog flood.
- `STARTED run_candles_etl` is emitted immediately before config load with the
  already-known request context (`ts`, mode, requested scope, requested
  intervals or `FROM_CONFIG`, worker count, logging mode, safety markers).
  After config load, a concise `RUN_CONTEXT run_candles_etl` line records the
  resolved intervals plus the effective `checkpoint_state_path`.
- Inactive/delisted markets are reported as one aggregate
  `SKIPPED_MARKETS_INACTIVE count=N sample=[...]` line instead of one line
  per market.
- Gap warnings are counted per chunk and summed into `gap_warnings_total=N`
  on the `FINISHED` line, instead of one `[ETL][WARN]` line per gap.
- Normal bounded `PROGRESS` / `FINISHED` output now also aggregates
  `raw_payload_rows`, `accepted_rows`, and `dropped_rows` so row-quality drift
  is visible without re-enabling per-chunk logs.
- Exact per-commit checkpoint state is preserved separately in a single
  atomically replaced artifact whose default path is derived from the
  effective config path, interval set, and scope under `/tmp/synth_runtime/`.
  Precedence is: explicit `--checkpoint-state-path`, then
  `SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH`, then the derived default. The
  paper-advice wrapper intentionally passes its own explicit stable path via
  `SYNTH_PAPER_ADVICE_LIFECYCLE_CHECKPOINT_STATE_PATH`. The JSON records the
  last successful DB commit only, is updated after every commit, preserves
  unknown `rows_written` as JSON `null` instead of silently coercing to zero,
  and is intentionally retained across interruption/failure so operators can
  inspect the exact final committed market/interval without relying on journal
  spam.
- Checkpoint durability is fail-visible: the temp file is flushed and fsynced,
  then `os.replace(...)` swaps it into place, then the parent directory is
  fsynced. A pre-replace failure preserves the prior valid artifact.
- Bounded `PROGRESS` / `FINISHED` / `INTERRUPTED` / `FAILED` lines include
  both the checkpoint artifact path and the latest checkpoint identity so an
  interrupted run can be followed directly to the preserved artifact.
- Genuine per-market failures (`MarketUnavailableError`, HTTP 400/404) remain
  visible without unbounded log growth: normal mode aggregates
  `unavailable_market_errors=N unavailable_market_sample=[...]`, while debug
  mode emits the individual `SKIPPED_MARKET_ERROR ...` lines.
- Full original verbose per-task/per-chunk/per-gap detail is preserved
  behind an explicit debug switch: `SYNTH_CANDLES_ETL_DEBUG=1` (env var, read
  by both modules) or `--debug-logging` (CLI flag on `run_candles_etl.py`,
  which also sets the env var so downstream calls agree). Use only for
  manual debugging; do not enable by default in a scheduled run.

**Disk/log health gate** (`src/operations/run_runtime_disk_log_health_v1.py`,
wired into `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh`):

- Runs immediately after lock acquisition, before any candle ETL.
- Read-only: `os.statvfs` (`f_bavail`-based writer-available capacity) plus
  optional `os.path.getsize` for named logs — no DB access, no network call,
  no broker call, no deletion or rotation.
- Reports `OK` / `WARN` / `CRITICAL` for the filesystem backing the repo
  directory using non-root writer-available capacity (`f_bavail`) rather than
  root-visible free space, so reserved blocks can trigger `CRITICAL` before a
  normal runtime user hits `ENOSPC`. Thresholds remain percentage-based
  (default warn=85%, critical=95% — override via
  `SYNTH_DISK_HEALTH_WARN_PCT` / `SYNTH_DISK_HEALTH_CRITICAL_PCT`; review
  these against the actual host's disk size before relying on them).
  An optional named log file can also be checked by absolute size via
  `SYNTH_DISK_HEALTH_LOG_PATH` (with `SYNTH_DISK_HEALTH_LOG_WARN_BYTES` /
  `SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES`, forwarded to the runner as
  `--log-warn-bytes` / `--log-critical-bytes` when set); omitted by default since no
  specific log path has been verified against actual host retention
  configuration yet.
- On `CRITICAL`, the wrapper script prints an explicit
  `[DISK_HEALTH][CRITICAL]` line and exits non-zero **before** running any
  candle ETL — confirmed by a local smoke test that forced `CRITICAL` via
  threshold override and observed the script exit 1 without ever reaching
  the ETL window computation or `run_candles_etl` invocation.

**What remains before `synth-paper-advice-lifecycle-refresh.timer` may be
re-enabled** (see P0-A acceptance criteria in the backlog): multi-cycle log
growth verification on the actual Odroid host. The above was verified via
code inspection, focused unit tests, and one partial local smoke run against
the production DB (429 real enabled assets, 6 real inactive markets
correctly aggregated into one line) from this development worktree — not
yet via repeated scheduled runs on Odroid itself. The timer stays stopped
and must not be started or re-enabled until that host verification is done.

**Correction:** that production-connected smoke was not dry/read-only. It
connected to and executed against the live production database, so it was a
production-state mutation risk, even though it made no private broker calls
and touched no account/order/decision/execution data. Read-only
verification performed afterward confirms zero inserts. Whether any
update-only write to an already-existing row occurred is not fully excluded
from process output alone. Full evidence and confidence levels are in the
backlog (P0-A). **Future validation of this runner must use no-write mode,
an isolated DB, or fixtures — do not rerun the production-connected ETL
smoke test.**

Paper advice dashboard render:

- timer cadence: every 5 minutes, offset from market refresh
- service command: `scripts/odroid/run_paper_advice_dashboard_refresh_once.sh`
- output: `/var/www/html/synth/paper-advice.html`
- scope: static dashboard render only
- excluded: candle ETL, features, signals, selection, advice, policy, decision, execution, orders

MVP market context refresh:

- timer cadence: every 5 minutes, offset before cockpit render
- service command: `scripts/odroid/run_mvp_market_context_refresh_once.sh`
- scope: `market_price_snapshot` plus bounded market-only structural/lifecycle refresh writes
- excluded: HTML render, broker private calls, broker writes, decision, execution, orders

MVP cockpit render:

- timer cadence: every 5 minutes after market context refresh
- service command: `scripts/odroid/run_mvp_dashboard_render_once.sh`
- scope: static cockpit render only
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

For the hard ownership boundary between canonical runtime chains and dashboard
rendering, see `docs/ops/runtime_chain_ownership_v1.md`.

Minimum checks:

- `obs_market_candle` max `close_ts_utc` by interval
- `feat_candle` max `close_ts_utc` by interval
- `signal_engine_state` max `signal_ts_utc` by interval
- `strategy_runtime_snapshot` only if a guarded full market-only chain is later allowed

4h freshness interpretation:

- judge freshness against the latest completed eligible 4h snapshot, not against
  the still-forming current wall-clock 4h bucket
- `signal_engine_state` is only expected to advance after `feat_candle` has a
  sufficiently complete snapshot for enabled assets
- a 4h market candle at `12:00Z` does not by itself guarantee that the
  canonical live signal snapshot should already be `12:00Z`
- treat 4h signal freshness as `WARN` or `FAIL` only when the chain misses a
  completed eligible cycle, not merely because candle ETL reached a newer raw
  boundary first

Paper advice monitoring checks:

- latest `paper_advice_observation` snapshot timestamp
- latest `obs_market_candle.close_ts_utc` for `15m`
- dashboard rendered timestamp in `/var/www/html/synth/paper-advice.html`
- latest `strategy_runtime_snapshot` for the 4h chain when the chain timer is enabled

MVP cockpit monitoring checks:

- latest `market_price_snapshot.snapshot_ts_utc`
- latest `execution_zone_context` and `paper_advice_observation` timestamps used by the lifecycle refresh consumers
- dashboard rendered timestamp in the cockpit HTML outputs

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

## Linked-Profile Account Dashboard Pipeline (Short Swing)

This section covers the Joost/Hugo linked-profile Short Swing pipeline
(Wallet, Open Orders Monitor, Profit Plan) as a distinct runtime lane from
the market-only 4h/paper-advice chain documented above. It was extended
following the incident recorded in:

```text
docs/incidents/2026-07-05_odroid_disk_exhaustion_and_stale_short_swing_data.md
```

and the follow-up backlog in:

```text
docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md
```

### Pipeline Ownership

Strict ownership, in order:

1. **Public market ingestion** — `src/market_data/run_market_price_snapshot_v1.py`.
   Market-only, account-agnostic. Public Bitvavo `GET /ticker/price` only.
   See `docs/ops/market_price_snapshot_v1.md`.
2. **Read-only account snapshot ingestion** — `src/account/run_account_wallet_refresh_v1.py`
   (wrapped by `scripts/odroid/run_account_wallet_refresh_once.sh`).
   Authenticated private read-only balances/open-orders only. No broker
   writes, no order submission. See `docs/ops/multi_account_wallet_refresh_v1.md`.
3. **Linked-profile dashboard render** — `scripts/odroid/run_account_wallet_dashboard_render_once.sh`
   (called per profile by `scripts/odroid/run_linked_profile_dashboard_refresh_once.sh`).
   **Presentation-only.** Reads persisted public-price and account snapshot
   observations from the DB and displays their freshness; it does not
   originate freshness truth. `broker_private_calls=0`. See
   `docs/ops/account_wallet_dashboard_v1.md` and
   `docs/ops/manual_short_trader_profit_plan_v1.md`.
4. **`selection_engine`** — market-only, account-agnostic. Not part of this
   pipeline; must never receive wallet/order state from it.
5. **`decision_gate`** — owns account-aware freshness/action permission and
   fails closed. It consumes the same persisted snapshot
   timestamps/statuses that stage 3 reads (i.e. `market_price_snapshot`,
   `trading_account_balance_snapshot`, `account_open_order_snapshot`), or a
   pure account-freshness evaluator derived directly from those persisted
   observations. **`decision_gate` must never consume renderer HTML, JSON,
   or any other renderer-generated output as an authority for account
   permission** — the renderer is a downstream display of the same
   underlying truth, not the source of it. It does not perform ingestion
   itself.
6. **`execution_planner` / executor** — unchanged by this pipeline. No order
   placement, cancellation, or broker writes occur anywhere in stages 1–3.

The renderer (stage 3) must never privately poll Bitvavo. Wallet/open-order
freshness is entirely the responsibility of stage 2; if stage 2 has not run
recently, stage 3 must show stale account data as stale, not silently reuse
old rows as if current (see the freshness contract in the backlog, P1-B).
This "show stale as stale" rule describes the renderer's own display
behavior — it is a separate, parallel consumer of the persisted snapshots,
not a source that `decision_gate` reads from.

### Current Implementation Status (verified, as of this writing)

- Stage 1 and stage 3 are consolidated today by
  `scripts/odroid/run_linked_profile_dashboard_refresh_once.sh`, which
  refreshes public prices once, discovers linked profiles via
  `src/account/run_linked_profile_dashboard_refresh_v1.py`, builds a shared
  native SHORT context, then renders each profile via
  `scripts/odroid/run_account_wallet_dashboard_render_once.sh`.
- **Documented gap:** `run_linked_profile_dashboard_refresh_once.sh` has
  **no systemd unit** in this repository. Neither `docs/ops/systemd/` nor
  `scripts/odroid/systemd/` contains one. Its production scheduling
  mechanism (if any, beyond manual invocation) is not captured in this
  repository. This is tracked as backlog item P0-B.
- Stage 2 (private wallet/order refresh) has an existing per-profile
  template pair, `docs/ops/systemd/synth-account-wallet-refresh@.service` /
  `.timer` (`OnUnitActiveSec=5min`), documented in
  `docs/ops/multi_account_wallet_refresh_v1.md`.
- A separate, older per-profile render-only template pair also exists,
  `docs/ops/systemd/synth-account-wallet-dashboard@.service` / `.timer`
  (`OnUnitActiveSec=5min`). **Documented gap:** this timer and the
  wallet-refresh timer above are two independent timers with no explicit
  ordering between them — each runs on its own 5-minute interval with no
  `After=`/dependency relationship guaranteeing wallet-refresh completes
  before wallet-dashboard renders. This is exactly the anti-pattern
  flagged in backlog item P0-B and must not be treated as a safe pipeline
  as-is.
- Do not assume which of these mechanisms is actually active on the Odroid
  host right now without checking (see "Current-State Inspection Commands"
  below). This document describes what exists in the repository, not a
  live status feed.

### Timer State: Verified Facts vs. Required Policy vs. Live State

Keep these three things distinct; do not collapse them into a single
"disabled" claim:

- **Incident-time verified fact:** `synth-paper-advice-lifecycle-refresh.timer`
  was stopped on the host as a recovery action during the 2026-07-05
  incident (`systemctl stop`). That a manual stop leaves the unit inactive
  is expected behavior, not a newly discovered runtime defect.
- **Required policy (independent of current live state):** this timer must
  not be started or re-enabled before backlog item P0-A is verified,
  regardless of what its current `active`/`enabled` state turns out to be.
- **Current live state:** whether the timer is currently *active* (running)
  and whether it is currently *enabled* (will start on boot / was
  `systemctl enable`d) are two separate, independently-checkable facts that
  this document does not assert. A `systemctl stop` alone does not disable
  a unit — `disabled` specifically means `systemctl is-enabled` reports
  `disabled`. **Check both before relying on either:**

```bash
systemctl is-active synth-paper-advice-lifecycle-refresh.timer
systemctl is-enabled synth-paper-advice-lifecycle-refresh.timer
```

- This document's description of any other timer's active/enabled state
  reflects what was true at incident time or at last inspection, not
  necessarily the current live state. **Always re-verify current state with
  the commands below before acting.**

### Current-State Inspection Commands

Run on the Odroid host:

```bash
systemctl list-timers --all | grep -i synth
systemctl status synth-paper-advice-lifecycle-refresh.timer
systemctl status synth-paper-advice-dashboard-render.timer
systemctl status synth-account-wallet-refresh@joost.timer
systemctl status synth-account-wallet-refresh@hugo.timer
systemctl status synth-account-wallet-dashboard@joost.timer
systemctl status synth-account-wallet-dashboard@hugo.timer
systemctl status synth-4h-market-chain.timer
```

Recent logs for a specific unit:

```bash
journalctl -u synth-paper-advice-lifecycle-refresh.service -n 200 --no-pager
journalctl -u synth-account-wallet-refresh@joost.service -n 100 --no-pager
journalctl -u synth-account-wallet-dashboard@joost.service -n 100 --no-pager
```

### Manual Recovery Path

The actual script used during the 2026-07-05 recovery:

```bash
cd /home/theone/projects/synth-v2
scripts/odroid/run_linked_profile_dashboard_refresh_once.sh
```

This refreshes public prices once, discovers all active linked profiles,
and renders each profile's Wallet, Open Orders Monitor, and Profit Plan
pages from persisted DB snapshots. It does **not** refresh wallet/open-order
data — run the private read-only refresh separately per profile first if
account data is also stale:

```bash
scripts/odroid/run_account_wallet_refresh_once.sh joost
scripts/odroid/run_account_wallet_refresh_once.sh hugo
```

### Freshness Verification Procedure

Read-only audit runner (does not call brokers, does not write the DB):

```bash
python -m src.operations.run_runtime_freshness_audit_v1 --venue bitvavo --output table
```

Direct checks:

- `market_price_snapshot` latest `snapshot_ts_utc` per symbol.
- `trading_account_balance_snapshot` / `account_open_order_snapshot` latest
  observed timestamp per `trading_account_id`.
- Rendered JSON per profile
  (`/var/www/html/synth/accounts/<profile>/profit-plan.json`) already
  carries `generated_ts_utc`, `account_snapshot_ts_utc`,
  `order_snapshot_ts_utc`, and `market_price_snapshot_ts_utc` — compare each
  against wall-clock time to judge freshness until the P1-B
  `FRESH`/`STALE`/`MISSING`/`UNAVAILABLE` contract lands.

### Disk, Filesystem, Journal, Syslog, Logrotate, Service-Log Verification

Inspect before changing any global logging configuration — do not assume
current rsyslog/logrotate/journald config without reading it:

```bash
df -h /
du -sh /var/log
ls -lh /var/log/syslog /var/log/syslog.1 2>/dev/null
du -sh /var/log/syslog* 2>/dev/null
journalctl --disk-usage
cat /etc/logrotate.d/rsyslog 2>/dev/null
systemctl cat rsyslog 2>/dev/null | head -30
du -sh /tmp
df -i /
```

A deterministic, read-only, scriptable equivalent for the disk-usage check
(and optionally one named log file's size) now exists (P0-A) and is also run
automatically at the start of every
`scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh` invocation:

```bash
python -m src.operations.run_runtime_disk_log_health_v1 \
  --path /home/theone/projects/synth-v2 \
  --log-path /var/log/syslog \
  --output table
```

Exits `0` for `OK`/`WARN`, `1` for `CRITICAL` — safe to use in scripts as a
fail-visible gate. Does not read the actual host's current
rsyslog/logrotate/journald configuration; it only measures current disk/file
size, so the manual commands above are still required before changing any
retention setting.

### Rollback Procedure

If a newly installed orchestration timer (P0-B) misbehaves:

```bash
systemctl stop <new-orchestrator>.timer
systemctl disable <new-orchestrator>.timer
```

Then fall back to the manual recovery path above. Rollback must **not**
start or re-enable `synth-paper-advice-lifecycle-refresh.timer` as a side
effect — that timer must remain stopped and must not be re-enabled until
P0-A is verified, regardless of orchestrator rollback. Check its actual
current `is-active`/`is-enabled` state with the commands above rather than
assuming it from this document.

### Explicit Warnings

- Never delete market data, database data, research outputs, or dashboard
  artifacts as part of any recovery or log-reduction step.
- Inspect the actual host rsyslog/logrotate/journald configuration before
  changing any retention setting — do not assume a configuration that has
  not been read on the host in question.
- Log reduction must be controlled, host-specific, and verified afterward
  (confirm freed space with `df -h` / `du -sh` and confirm the affected
  service still logs correctly after reduction). The 2026-07-05 incident's
  reduction covered active syslog, rotated syslogs, and journal usage
  together, not rotated files alone — do not narrow future reductions to
  "rotated files only" as if that were the established safe boundary.
- Do not invent recovery commands beyond what the incident record
  (`docs/incidents/2026-07-05_odroid_disk_exhaustion_and_stale_short_swing_data.md`)
  or an actual host runbook supports. The incident record remains the
  factual account of what was done; this operations document must not
  restate it more narrowly or more broadly than what it says.
- The renderer (stage 3 above) must never make private Bitvavo calls. If a
  future change adds a broker call inside a renderer script, that is an
  architecture violation of this pipeline, not a valid freshness fix.

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
- No private broker polling inside any renderer script.
- No re-enabling `synth-paper-advice-lifecycle-refresh.timer` before backlog
  item P0-A is verified.
