# TODO — UI / Webview

## Status

Active / read-only freshness and zone display updated.

The chart webview now exposes post-pipeline source freshness, Amsterdam-local timestamp display, chart/source candle timestamp comparison, and zone context overlays from existing database rows. It remains an inspection/display UI only.

## Sources

```text
docs/status/synth_v2_5_todo.md
apps/synth_chart_app_v1.py
src/ui_chart/chart_repository.py
src/ui_chart/chart_assembler.py
src/ui_chart/chart_renderer.py
src/ui_chart/chart_config.py
```

## Current state

```text
UI/chart framework v1 exists as read-only Streamlit + Plotly debug UI.
Commit reference: 7e69da2 Add read-only Synth chart debug UI.
Freshness display reference: research/webview-freshness-display-v1.
```

## P2 — Stabilize UI/chart framework v1

Status: open / parked.

Tasks:

- Confirm BTC 1h chart renders.
- Confirm EMA20/EMA50 overlays render.
- Confirm RSI and signal confidence panels render.
- Confirm selection overlays do not crash Plotly.
- Confirm Streamlit UI remains read-only.
- Keep v1 as debug UI, not final trading interface.

## P2 — Document UI/chart framework

Status: done / keep current.

Create or update:

```text
docs/architecture/ui_chart_framework_v1.md
```

Required content:

- purpose
- read-only boundary
- module responsibilities
- time alignment
- performance rules
- current features
- future extensions

## P2 — Webview / paper advice overlay TODO

Status: done for read-only freshness v1.

Display tasks:

- Show latest close price from `obs_market_candle`.
- Show latest chart-frame open timestamp, chart-frame close timestamp, and latest source candle close timestamp.
- Convert display timestamps to Europe/Amsterdam local time with CET/CEST abbreviation while keeping DB/repository timestamps in UTC.
- Show freshness footer with Amsterdam-local timestamps only.
- Show candle hover text with local open time, local close time, OHLC, and signal fields where available.
- Show latest signal, selection, advice, execution-zone, and runtime snapshot timestamps where available.
- Show `entry_zone_low`, `entry_zone_high`, `tp_zone_low`, `tp_zone_high`, and `invalidation_price`.
- Show `distance_to_zone_pct`.
- Show `distance_to_target_pct`.
- Show `zone_relation` as `ABOVE_ZONE`, `INSIDE_ZONE`, or `BELOW_ZONE`.
- Draw display-only entry-zone band, target-zone band, and invalidation line on the chart when values exist.
- Optional 300-second auto-refresh.

Design rules:

- Reporting/display only.
- Prefer a separate market-only price snapshot source.
- Do not call a direct ticker from the renderer.
- Show `not available` when a source row or field is absent.
- Keep database retrieval in `src/ui_chart/chart_repository.py`.
- Keep renderer functions limited to assembled view models.
- Do not label chart overlays as buy or sell instructions.

## P2 — Market Confluence & Events Dashboard v1

Status: TODO — design documented, pre-implementation.

See: [`docs/architecture/market_confluence_events_dashboard_v1.md`](../architecture/market_confluence_events_dashboard_v1.md)

Next step: Phase 1 inventory — inspect existing event, sentiment, and outcome tables before any schema design or implementation.

---

## Later UI v2 direction

- TradingView-style Lightweight Charts frontend.
- Python/FastAPI read-only backend.
- Better zoom/pan/crosshair/markers.
- Multi-pane charting.
- Paper/backtest/oracle marker overlays.

## P1 — Cockpit usability and reading flow

Status: open / active design follow-up.

Table usability:

- Keep symbol, current price, relevant target/zone columns sticky where useful.
- Keep dashboard table header rows sticky for wide cockpit tables.
- Preserve mobile/simple rendering.

Information architecture:

- Split cockpit information into clear sections:
  - market state
  - policy/action state
  - pipeline/recompute state
- Keep policy/action blocks separate from market context and next-zone previews.
- Continue to label dashboard context as review context, not trade permission.

Final simplified user dashboard:

- One practical overview based on natural reading flow.
- Per-coin compact cards.
- 5-day mini graph/sparkline.
- Markers for entry, current price, target, invalidation, reclaim, and recompute.
- Compact state plus human-readable reason.

Boundary:

- UI/reporting only.
- No market logic changes.
- No selection, advice, decision, execution, broker, or order path changes.

## P1 — Local-only UI timestamps

Status: implemented in `feature/ui-local-time-only-v1`.

Goal:
All human-facing dashboards and chart HTML should display Europe/Amsterdam local time only.

Rules:
- UI should not show UTC timestamps by default.
- Use Europe/Amsterdam timezone conversion.
- Label as "Amsterdam time" or "Local time".
- Do not hardcode CEST, because winter uses CET.
- JSONL, DB fields, logs, and internal reproducibility artifacts remain UTC.
- Optional: keep UTC only in machine-readable JSONL, not chart labels/tooltips.

Affected UI:
- rotation-preview.html
- paper-advice.html
- index.html
- pipeline visual backtest HTML
- Streamlit chart app

Implementation notes:
- Human-facing dashboards and chart HTML use Europe/Amsterdam via `zoneinfo`.
- Runtime logs, DB field names, and research JSONL remain UTC for reproducibility.
## Boundary

```text
UI is inspection/display only.
UI may not write to decision, execution, order, account, balance, or position tables.
UI queries must be bounded by asset_id, venue, interval_code, timestamp range, and limit.
No advice/selection/decision/execution/broker/order path changes.
```
