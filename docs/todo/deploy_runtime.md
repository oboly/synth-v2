# TODO — Deploy / Runtime Runners

## Status

Open / future runtime operations lane.

This lane tracks deployment of Synth runtime components to the Odroid and scheduled runners for market-data refresh and UI/webview data freshness.

## Sources

```text
Recent chat TODO: deploy Synth on Odroid and add runners for candle ingestion and webview data refresh.
Known infra context: Odroid C4 targeted for 24/7 runtime agents; MariaDB host is gurkdb.
Recent chat TODO: after Odroid runners are stable, select the first strategy candidate and develop Synth toward paper execution support.
docs/ops/synth_runtime_runners_v1.md
```

## P1 — Odroid runtime runners deployment plan

Status: drafted / review pending.

Plan:

```text
docs/ops/synth_runtime_runners_v1.md
```

Scope:

- Odroid host roles.
- Phase order from inventory through guarded market-only chain review.
- Allowed initial runner scope.
- Systemd timer preference.
- Locking / duplicate-writer guard.
- Freshness checks.
- Safety markers.
- Paper strategy follow-up gate.

Actual deployment remains open. No services, timers, chain scripts, secrets, schema changes, asset metadata, or selection/advice/decision/execution logic were changed by the plan.

## P2 — Deploy Synth runtime on Odroid

Status: open; plan drafted.

Goal:

Run selected Synth services/runners on the Odroid as a lightweight 24/7 runtime host.

Tasks:

- Define what belongs on Odroid versus dev laptop versus DB host.
- Confirm repository checkout path and Python environment on Odroid.
- Confirm `.env` / secrets handling without committing credentials.
- Confirm network access from Odroid to `gurkdb` MariaDB.
- Confirm log directory and service user.
- Decide whether runners are managed by cron, systemd timers, or a supervised process.

Boundary:

```text
No live trading.
No broker writes.
No order submission.
No executor/order runtime unless explicitly enabled later.
Read/write scope must be explicit per runner.
```

## P2 — Candle ingestion runner

Status: open.

Goal:

Keep market candles fresh from the selected venue, initially Bitvavo.

Tasks:

- Define allowed candle intervals for runtime refresh, e.g. 1h / 4h / 1d.
- Define safe cadence per interval.
- Ensure runner is idempotent and bounded.
- Ensure logs are retained but not committed.
- Verify DB writes target only intended market observation tables.
- Add freshness checks after each run.
- Avoid running duplicate candle writers from multiple hosts.

Boundary:

```text
Market-data ingestion only.
No selection/advice/decision/execution/order side effects.
No broker trading calls.
```

## P2 — Webview data refresh runner

Status: partially addressed by read-only chart freshness display.

Goal:

Refresh read-only data used by the chart/webview layer so UI inspection stays current without direct renderer-side ticker calls.

Tasks:

- Define market-only snapshot source for current/latest price display.
- Current chart v1 uses latest `obs_market_candle.close_price` for display.
- Current chart v1 displays source freshness in UTC and Europe/Amsterdam local time.
- Current chart v1 shows both chart-frame latest close and source latest candle close to make selected-window or cache differences visible.
- Current chart v1 derives display-only zone relation and distances from existing candle and execution-zone rows when stored values are absent:
  - latest close price
  - distance_to_zone_pct
  - distance_to_target_pct
  - zone_relation
- Current chart v1 draws display-only entry-zone, target-zone, and invalidation overlays from existing zone context.
- Decide whether refresh cadence should be 300 seconds or slower.
- Keep renderer read-only.
- Avoid direct live ticker calls inside chart renderer.
- Make source timestamp and freshness visible in UI.
- Keep any future refresh runner read-only for UI display sources unless a separate market-data ingestion task explicitly owns writes.

Boundary:

```text
Read-only display support.
No writes to decision, execution, order, account, balance, or position tables.
No broker/order path.
No direct ticker calls from chart renderer.
```

## P2 — First paper strategy lane after Odroid runners

Status: blocked until Odroid runners are deployed and stable.

Goal:

After the Odroid market-data / feature / signal runners are stable, select one first strategy candidate and develop the missing Synth paper-trading path around it.

Sequencing:

```text
Odroid runners stable
-> market-data freshness checks stable
-> first strategy candidate selected
-> paper-only strategy candidate contract
-> paper decision permission layer
-> paper execution intent / simulated fills
-> paper reporting
```

Tasks:

- Define the minimum stable-runner requirement before selecting a strategy candidate.
- Select exactly one initial strategy candidate for paper validation.
- Keep `asset != strategy`; the selected unit must be `asset + strategy_family + horizon_bucket + setup_context + validation_state`.
- Define paper-only candidate state and paper account assumptions.
- Ensure selection stays market-only and account-agnostic.
- Ensure decision_gate owns paper permission, exposure, sizing, and account constraints.
- Ensure execution_planner produces paper execution intent only.
- Ensure simulated fills are clearly marked as paper/simulated.
- Add paper run reporting before any live path is considered.

Boundary:

```text
Paper only.
No live trading.
No broker writes.
No real order submission.
No executor activation for live orders.
No bypass around decision_gate.
No strategy logic inside execution_planner/executor.
```

## P3 — Runtime orchestration standard

Status: drafted in ops plan / future implementation.

Tasks:

- Document runner ownership: Odroid vs dev laptop vs DB host.
- Document cron/systemd timer strategy.
- Document lock/guard strategy to prevent duplicate writers.
- Document failure logging and recovery.
- Document freshness checks per runner.
- Document when paper-only strategy runners are allowed to start after market-data runners are stable.

Potential doc target:

```text
docs/ops/synth_runtime_runners_v1.md
```

Next implementation remains blocked until the ops plan is reviewed.

## Non-goals

- No live trading enablement.
- No broker writes.
- No real order submission.
- No secrets in git.
- No paper strategy activation before Odroid runners are stable and the first strategy candidate is reviewed.
