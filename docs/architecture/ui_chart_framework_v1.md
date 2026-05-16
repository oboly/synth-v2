# UI Chart Framework V1

## Purpose

The UI chart framework is a read-only inspection surface for market candles, feature overlays, selection context, paper candidate rows, source freshness, and execution-zone display context.

It is not a trading interface and does not create strategy, decision, execution, order, account, balance, or position side effects.

## Read-Only Boundary

The Streamlit chart app and `src/ui_chart` modules may only read existing rows for display.

Forbidden in this lane:

- Broker calls.
- Broker writes.
- Order submission.
- Decision, execution, order, account, balance, or position table writes.
- Selection, advice, decision, execution, executor, or broker behavior changes.
- Direct ticker calls from the chart renderer.
- `run_chain_4h.sh` changes.

## Module Responsibilities

- `apps/synth_chart_app_v1.py` owns Streamlit controls and page layout.
- `src/ui_chart/chart_repository.py` owns database reads for chart data, freshness rows, latest close price, zone context, and runtime snapshot metadata.
- `src/ui_chart/chart_assembler.py` prepares dataframes and assembles display view models.
- `src/ui_chart/chart_renderer.py` renders Plotly figures and markdown from assembled view models only.
- `src/ui_chart/chart_config.py` owns UI defaults and column display lists.

## Source Tables

Current read-only sources include:

- `asset`
- `obs_market_candle`
- `feat_candle`
- `signal_engine_state`
- `selection_state`
- `asset_profile_snapshot`
- `research_paper_candidate_signal`, when present
- `paper_advice_observation`, when present
- `advice_state`, fallback only when present
- `vw_paper_advice_execution_zone_context_v1`, preferred for execution-zone display
- `execution_zone_context`, fallback for execution-zone display
- `strategy_runtime_snapshot`, when present

## Freshness Model

The UI displays latest available source timestamps independently:

- Latest plotted chart-frame candle `open_ts_utc`.
- Latest plotted chart-frame candle `close_ts_utc`.
- Latest candle `close_ts_utc`.
- Latest signal `signal_ts_utc`.
- Latest selection `asof_ts_utc`.
- Latest advice `asof_ts_utc`, when an advice source exists.
- Latest execution-zone `asof_ts_utc`.
- Latest `strategy_runtime_snapshot` timestamp and id, when available.

Database and repository timestamps remain UTC. Display rendering converts timestamps to Europe/Amsterdam local time with the correct CET or CEST abbreviation. The freshness table shows both UTC and Amsterdam time. Missing source rows or missing fields are rendered as `not available`.

## Zone Context

The UI displays existing zone context fields where available:

- `entry_zone_low`
- `entry_zone_high`
- `tp_zone_low`
- `tp_zone_high`
- `invalidation_price`
- `zone_relation`
- `distance_to_zone_pct`
- `distance_to_target_pct`

When stored relation or distance fields are absent, `chart_assembler.py` computes display-only values from the latest close and existing zone bounds. These derived values are for inspection only and are not strategy rules.

The chart renderer may draw display-only overlays from the assembled zone context:

- Entry zone band between `entry_zone_low` and `entry_zone_high`.
- Target zone band between `tp_zone_low` and `tp_zone_high`.
- Invalidation line at `invalidation_price`.

These overlays must not be labeled as buy or sell instructions.

## Time Alignment

Chart rows are bounded by asset, venue, interval, start timestamp, end timestamp, and limit. The chart x-axis uses the candle open timestamp because the plotted OHLC bar is anchored at `open_ts_utc`. Freshness uses candle close timestamps when reporting source completion.

Daily candles can therefore show the previous calendar date on the x-axis while the same candle closes after midnight in Europe/Amsterdam time. For example, a daily candle opened on May 15 UTC can close on May 16 at 02:00 CEST. This is expected and is shown explicitly through separate chart-frame open, chart-frame close, and source candle close fields.

Freshness rows intentionally use latest available source timestamps so the UI can show whether post-pipeline sources are current relative to the selected chart window. The displayed chart-frame latest close and source latest candle close may differ when the selected date window or cache excludes the newest source candle.

## Performance Rules

Queries must remain bounded by asset, venue, interval, timestamp range, or latest-row limits. Streamlit cache TTLs are used to avoid repeated refreshes during normal inspection.

## Current Features

- Candlestick chart from `obs_market_candle`.
- Candlestick hover shows local candle open and close times.
- EMA, RSI, volume, signal confidence, and signal label overlays where available.
- Selection vertical lines.
- Point-in-time asset profile display.
- Latest close price display from existing candle data.
- Source freshness metrics.
- Execution-zone and distance display.
- Paper candidate row display when the research table exists.

## Future Extensions

Future work may add a dedicated market-only display snapshot source or a non-renderer refresh runner. Any such runner must state its write scope explicitly and must not write to decision, execution, order, account, balance, or position tables.
