# TODO — Deploy / Runtime Runners

## Status

Active runtime operations lane. Initial Odroid runtime is deployed; follow-up work remains open for market damage hysteresis, A+ DB integration, dashboard quality display, and final ops cleanup.

2026-07-18 ownership correction: any older section below that assigns public
market-price or candle database writes to Odroid is historical deployment
context, not the target contract.

2026-07-19 ownership correction, amended by PR #124 follow-up: the "devlap sole
public market-data writer host" claim is retired. A capability has at most one
authorized active production owner, and exactly one only when its lifecycle is
`ACTIVE`. All four capabilities are `UNASSIGNED` by this correction, including
`market_rotation_pressure`. Its devlap acceptance (PR #100/#101) and last
observed installed active timer are preserved as historical audit context
(SUPERSEDED as production authorization), not a current production assignment;
acceptance evidence and observed runtime state do not grant production
ownership. gurkDB is a preferred candidate, not a proven owner. The
authoritative contract and machine-readable registry are
`docs/ops/writer_capability_host_ownership_contract_v1.md` and
`deploy/ownership/writer_capability_ownership_v1.json`. Host rollout remains
pending; no host mutation or writer invocation is performed by this correction.

This lane tracks deployment of Synth runtime components to the Odroid and scheduled runners for market-data refresh and UI/webview data freshness.

## Sources

```text
Recent chat TODO: deploy Synth on Odroid and add runners for candle ingestion and webview data refresh.
Known infra context: Odroid C4 targeted for 24/7 runtime agents; MariaDB host is gurkdb.
Recent chat TODO: after Odroid runners are stable, the next step is manual paper advice cockpit / strategy candidate inbox work before any paper execution or simulated fills.
docs/ops/synth_runtime_runners_v1.md
docs/architecture/market_trigger_engine_v1.md
```

## P1 — Odroid runtime runners deployment plan

Status: done / Odroid runtime active.

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

Initial Odroid deployment is active. The installed runtime uses systemd timers on the Odroid with `User=theone` and `WorkingDirectory=/home/theone/projects/synth-v2`. Safety remains paper/read-only: live execution permission and broker write permission are disabled.

## P2 — Deploy Synth runtime on Odroid

Status: done / Odroid runtime active.

Goal:

Run selected Synth services/runners on the Odroid as a lightweight 24/7 runtime host.

Tasks:

- Define what belongs on Odroid versus dev laptop versus DB host.
- Confirm repository checkout path and Python environment on Odroid.
- Confirm `.env` / secrets handling without committing credentials.
- Confirm network access from Odroid to `gurkdb` MariaDB.
- Confirm log directory and service user.
- Decide whether runners are managed by cron, systemd timers, or a supervised process.
- Review generated systemd templates under `docs/ops/systemd/`.
- Confirm Odroid service user and repo path before copying templates to `/etc/systemd/system`.
- Current Odroid template defaults are `User=theone` and `WorkingDirectory=/home/theone/projects/synth-v2`.
- Do not install or enable timers until the templates are reviewed on the Odroid.

Boundary:

```text
No live trading.
No broker writes.
No order submission.
No executor/order runtime unless explicitly enabled later.
Read/write scope must be explicit per runner.
```

## P2 — Candle ingestion runner

Status: gurkDB controlled acceptance passed; production cutover blocked on administrator-capable sudo.

Current acceptance state (2026-07-24):

- strict gurkDB preflight passed at exact clean commit `2e762b58ab9e311f4a8d403d8d97332e5ebb0f16`;
- devlap writer remains disabled and Odroid candle units remain masked;
- eight stale historical-import asset rows were disabled without deleting
  18,660 historical candles;
- enabled-universe validation reports 421 enabled assets, 430 current Bitvavo
  EUR trading markets, and zero mismatch;
- two controlled five-interval manual cycles passed with 421/421 persisted
  asset coverage, lock containment, idempotent repeat operation, and zero
  duplicate writers;
- production ownership remains `UNASSIGNED`; no production authorization or
  timer activation occurred;
- rerun strict preflight at the final registry head, then perform separately
  authorized cutover only with administrator-capable sudo.

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

Status: done for static paper advice dashboard freshness display; broader UI/webview work remains parked in `docs/todo/ui_webview.md`.

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
- Paper advice dashboard refresh may render static HTML frequently using the latest 4h `paper_advice_observation` snapshot plus 15m candle path data for display-only DOWN pullback lifecycle badges.
- Frequent lifecycle refresh does not imply trade permission, paper execution permission, or runtime promotion.
- If a DOWN row is `INVALIDATED`, the dashboard should show `RECOMPUTE NEEDED`; zone recomputation belongs upstream in `execution_zone_context` / paper advice, not in the dashboard.

Boundary:

```text
Read-only display support.
No writes to decision, execution, order, account, balance, or position tables.
No broker/order path.
No direct ticker calls from chart renderer.
No dashboard zone recomputation.
```

## P2 — Paper advice dashboard lifecycle refresh runner

Status: **timer was stopped during the 2026-07-05 incident** (verified
recovery action), pending log-containment fix. Previously: done / systemd
timer active on Odroid. Its current `active`/`enabled` state must be
checked on-host (`systemctl is-active` / `systemctl is-enabled`; see
`docs/ops/synth_runtime_runners_v1.md`) rather than assumed from this line.
Required policy regardless of current live state: do not start or
re-enable `synth-paper-advice-lifecycle-refresh.timer` until
`docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md`
P0-A is verified. See
`docs/incidents/2026-07-05_odroid_disk_exhaustion_and_stale_short_swing_data.md`
for the incident record.

Script:

```text
scripts/odroid/run_paper_advice_dashboard_refresh_once.sh
scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh
scripts/odroid/run_mvp_market_context_refresh_once.sh
docs/ops/systemd/synth-paper-advice-lifecycle-refresh.service
docs/ops/systemd/synth-paper-advice-lifecycle-refresh.timer
docs/ops/systemd/synth-paper-advice-dashboard-render.service
docs/ops/systemd/synth-paper-advice-dashboard-render.timer
```

Tasks:

- Render the static paper advice dashboard from the latest 4h paper advice snapshot.
- Use faster `obs_market_candle` ranges for path-aware DOWN pullback lifecycle display.
- Use `15m` as the initial fast lifecycle interval.
- Runs every 5 minutes via `synth-paper-advice-lifecycle-refresh.timer` on Odroid.
- Render `/var/www/html/synth/paper-advice.html`.
- Smoke-test `5m` separately before using it operationally.
- Use `flock` to avoid duplicate dashboard renders.
- Print explicit safety markers.
- Keep output as static HTML only.
- Do not refresh features, signals, selection, advice, policy, execution, or order state in the fast lifecycle runner.
- Keep `INVALIDATED` as a display context requiring upstream recomputation; the dashboard must not recompute zones.

Boundary:

```text
Separated ownership.
Lifecycle market refresh is public candle ETL only.
Dashboard render is static HTML only.
No strategy/policy/decision/execution changes.
No broker/private calls.
No broker writes.
No order submission.
```

Manual freshness checks:

- latest `paper_advice_observation` snapshot timestamp
- latest `obs_market_candle.close_ts_utc` for `15m`
- dashboard rendered timestamp
- lifecycle badge sample in the static HTML

Required safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

## P2 — 4h market chain timer templates

Status: done / systemd timer active on Odroid.

Templates:

```text
docs/ops/systemd/synth-4h-market-chain.service
docs/ops/systemd/synth-4h-market-chain.timer
```

Goal:

Run the reviewed 4h market-only chain on a conservative schedule after each 4h candle close so `paper_advice_observation`, setup zones, policy map, and runtime snapshot freshness are updated before the faster lifecycle dashboard runner observes path state.

Tasks:

- Review 4h schedule: `00,04,08,12,16,20:12 UTC`.
- Confirm the service calls the existing `scripts/run_chain_4h.sh`.
- Confirm `User=theone` and `WorkingDirectory=/home/theone/projects/synth-v2` match the Odroid host before installing.
- Confirm decision/execution/order permissions remain disabled.
- Confirm broker writes remain disabled.
- Confirm journal logging and safety markers after manual dry run.
- Confirm latest `strategy_runtime_snapshot` after a successful run.

Boundary:

```text
Templates only.
No service installation by this lane.
No chain script changes.
No broker writes.
No order submission.
No decision_gate/execution_planner/executor activation.
```

## P2 — Market trigger engine design

Status: design drafted / implementation blocked.

Design:

```text
docs/architecture/market_trigger_engine_v1.md
```

Goal:

Define a reusable public market-data trigger engine for threshold and zone events that can later feed paper advice lifecycle state, dashboard refreshes, alerts, and future execution-agent / order-monitor components.

Tasks:

- Keep the current fast lifecycle runner as a polling bridge.
- Review watch definition, event, and state schema proposals.
- Decide whether future storage should use DB event log plus current state.
- Decide how dynamic symbol subscriptions should be built from the latest paper advice snapshot.
- Keep trigger events as market facts, not trade permission.

Boundary:

```text
No service installation yet.
No DB migration yet.
No private broker calls.
No broker writes.
No order submission.
No bypass around decision_gate.
No replacement for execution_planner.
No runtime promotion.
```

## P2 — First paper strategy lane after Odroid runners

Status: open / blocked until runtime stability is observed and first strategy candidate is reviewed.

Immediate sequencing note:

- before paper execution intent or simulated fills, finish the manual paper advice cockpit / strategy candidate inbox path
- keep that step read-only and review-only
- do not treat dashboard completion as paper trading enablement

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

## P2 — Trade setup rank eligibility correction

Status: done / committed to main.

Context:

- Old setup-filter rank sweet spot required rank `4..10`.
- That was inverted relative to the original intent because rank `1..3` could fail setup purely for being top-ranked.
- Correct setup eligibility should allow rank `1..10`; top-rank rows may carry priority/chase-risk context only.
- Actionable count limiting belongs downstream in paper advice policy preview or the account-aware decision gate.

Boundary:

```text
No decision_gate changes.
No execution_planner changes.
No executor changes.
No broker writes.
No order submission.
No runtime permission changes.
```

## P2 — Paper advice setup-fail reason display

Status: done / committed to main.

Goal:

Expose the setup-filter primary fail reason in the static paper advice dashboard so rows do not only show generic `SETUP FAILED`.

Current display behavior:

- `SETUP FAILED` remains the generic setup-state badge.
- Specific setup-filter guards such as `MARKET_DAMAGE_RISK` are shown as visible row badges and added to the Reasons column when available.
- This is display-only and reads the reason from the existing paper advice / setup-filter observation context.

Boundary:

```text
No trade_setup_filter behavior changes.
No advice/policy behavior changes.
No decision_gate changes.
No execution_planner changes.
No executor changes.
No broker writes.
No order submission.
No systemd timer changes.
```

## P3 — Runtime orchestration standard

Status: open / needs final ops cleanup and runtime verification checklist.

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
