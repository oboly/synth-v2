# TODO — UI / Webview

> **Migration pointer — PARTIAL migration only.** GitHub Issue
> [#233 — Implement accepted Profit Plan coin-card scanability improvements](https://github.com/oboly/synth-v2/issues/233)
> owns **only** the four accepted-but-unbuilt items in
> "### Profit Plan coin-card scanability decisions" below (PPP display
> compaction, tooltip registry entry, removing the duplicate Current-price
> tile, and the variable-field alignment follow-up). Current status,
> priority, blockers, acceptance criteria, next action, and closure for
> that scope belong to Issue #233.
>
> All other sections describe already-implemented UI work (`P2 — Document
> UI/chart framework`, `P2 — Webview / paper advice overlay TODO`,
> `P1 — Local-only UI timestamps`) and remain **historical record, not
> active scope** — not migrated by this batch.
>
> GitHub Issue
> [#325 — Stabilize and verify UI/chart framework v1 debug app](https://github.com/oboly/synth-v2/issues/325)
> owns "P2 — Stabilize UI/chart framework v1" (verification/stabilization
> pass on the existing debug chart app, distinct from #240's cockpit/wallet
> surface and #278's research-backtest cockpit exposure).
>
> "Later UI v2 direction" (TradingView-style Lightweight Charts frontend,
> FastAPI backend) is vague roadmap prose with no bounded scope, no
> acceptance criteria, and no current evidence it is scheduled — it is not
> converted into an Issue per the explicit instruction not to file a generic
> "UI v2" Issue from roadmap prose. It remains historical/design direction
> only.
>
> This file must not become a parallel status board for the migrated scope.
>
> See `docs/development/github_issues_workflow.md`,
> `docs/todo/MIGRATION_FREEZE.md`, and
> `docs/development/github_issues_batch_2b_migration_v1.md`.
>
> ## GitHub Issue migration
>
> Status: migrated
>
> Operational status/priority is owned by GitHub Issues.
>
> Section ownership:
> - Profit Plan coin-card scanability decisions -> Issue #233
> - P2 — Stabilize UI/chart framework v1 -> Issue #325
> - P2 — Document UI/chart framework, P2 — Webview/paper advice overlay TODO, P1 — Local-only UI timestamps -> no Issue required; already-implemented historical record
> - Later UI v2 direction -> no Issue required; vague roadmap prose, not bounded/scheduled
>
> Unmigrated executable scope:
> - none

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

### Profit Plan coin-card scanability decisions

Status: accepted design / implementation later.

The primary user already knows the card semantics and scans many coins rapidly. Compact, fixed-position values take priority over repeating explanatory text inside each value.

PPP display:

```text
label: MAP | ACTIONABLE PPP  ⓘ
value: 99,9 | —
```

Rules:

- `MAP PPP` is the user-facing name for the current theoretical map potential formerly presented as Planning PPP.
- `Actionable PPP` remains the current evidence-gated potential used for actionable ranking/sorting.
- Render both values in one fixed-width field separated by `|`.
- Do not repeat `Map`, `Planning`, `Actionable`, `P`, or `A` inside the value line.
- Use `—` for unavailable values.
- Use tabular numerals and stable column widths so cards remain visually aligned.
- Keep sorting on Actionable PPP; this UI compaction must not change calculation or ranking semantics.
- Preserve existing structured field names for compatibility unless a separately reviewed data-contract migration renames them.

Tooltip:

- Add one information icon to the combined label.
- Tooltip explains that Map PPP is theoretical potential from the current map and Actionable PPP is the currently usable potential after evidence/activation gates.
- Later generalize label tooltips through one central field-definition registry reused by card, sidebar, and detail view.
- Do not duplicate tooltip strings independently in multiple renderers.

Price presentation:

- Remove the duplicate `Current price` body tile because price is already present in the card header.
- Increase the header-price font size and weight for faster scanning.
- Keep freshness/age visually secondary beside or below the header price.

Variable-field alignment follow-up:

- Optional rows such as `Market Event` currently cause later fields to shift between cards.
- Later evaluate fixed semantic groups or two stable definition lists instead of independently flowing tiles.
- Candidate grouping: setup/market context versus trade plan.
- Until redesigned, optional fields should reserve stable layout space or render an explicit `—` rather than shifting subsequent content.
- This is presentation-only; no market, action, decision, or execution semantics may change.

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
