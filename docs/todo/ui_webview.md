# TODO — UI / Webview

## Status

Active / read-only freshness display updated.

The chart webview now exposes post-pipeline source freshness and zone context from existing database rows. It remains an inspection/display UI only.

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
- Show latest candle close timestamp.
- Show latest signal, selection, advice, execution-zone, and runtime snapshot timestamps where available.
- Show `entry_zone_low`, `entry_zone_high`, `tp_zone_low`, `tp_zone_high`, and `invalidation_price`.
- Show `distance_to_zone_pct`.
- Show `distance_to_target_pct`.
- Show `zone_relation` as `ABOVE_ZONE`, `INSIDE_ZONE`, or `BELOW_ZONE`.
- Optional 300-second auto-refresh.

Design rules:

- Reporting/display only.
- Prefer a separate market-only price snapshot source.
- Do not call a direct ticker from the renderer.
- Show `not available` when a source row or field is absent.
- Keep database retrieval in `src/ui_chart/chart_repository.py`.
- Keep renderer functions limited to assembled view models.

## Later UI v2 direction

- TradingView-style Lightweight Charts frontend.
- Python/FastAPI read-only backend.
- Better zoom/pan/crosshair/markers.
- Multi-pane charting.
- Paper/backtest/oracle marker overlays.

## Boundary

```text
UI is inspection/display only.
UI may not write to decision, execution, order, account, balance, or position tables.
UI queries must be bounded by asset_id, venue, interval_code, timestamp range, and limit.
No advice/selection/decision/execution/broker/order path changes.
```
