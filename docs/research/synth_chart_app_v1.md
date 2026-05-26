# Synth Chart App V1

## Purpose

`apps/synth_chart_app_v1.py` is the existing read-only Streamlit chart
framework for interactive chart review in Synth.

It is the reusable interactive chart surface for:

- symbol-level market inspection
- point-in-time chart context review
- paper candidate inspection
- selection timing review
- zone and freshness review

It is not:

- a static cockpit page
- execution
- paper trading
- live trading
- order submission

## How To Run

```bash
streamlit run apps/synth_chart_app_v1.py
```

## Primary Modules

App entry:

- `apps/synth_chart_app_v1.py`

Chart assembly/config/render/data access:

- `src/ui_chart/chart_assembler.py`
- `src/ui_chart/chart_config.py`
- `src/ui_chart/chart_renderer.py`
- `src/ui_chart/chart_repository.py`

## Current Structure

`apps/synth_chart_app_v1.py` provides the Streamlit shell, sidebar controls,
caching, and top-level page layout.

`chart_repository.py` is the read-only data-access layer. It reads:

- enabled assets
- market candles
- feature overlays
- signal-engine fields
- selection history
- paper candidate rows
- point-in-time profile
- latest display context / zone context / runtime snapshot

`chart_assembler.py` normalizes frames and builds the display bundle:

- chart frame
- selection frame
- paper candidate frame
- point-in-time profile
- display context

`chart_renderer.py` renders the Plotly chart and the related display markdown.

`chart_config.py` defines supported venue/interval defaults and feature/signal
column sets.

## Existing Features

Current app features already include:

- symbol control
- venue control
- interval control
- date range controls
- max-candle control
- candle chart
- `EMA20`
- `EMA50`
- `RSI` panel
- signal confidence panel
- signal labels on chart
- selection vertical lines
- paper candidate rows/table
- point-in-time profile
- freshness display
- zone context display
- runtime snapshot display

More specifically:

- candlesticks come from `obs_market_candle`
- EMAs / RSI / feature columns are joined from `feat_candle`
- signal labels and confidence come from `signal_engine_state`
- selection timing markers come from `selection_state`
- paper candidate rows come from the paper candidate source queried in
  `chart_repository.py`
- point-in-time profile is fetched separately and rendered alongside the chart
- latest display context includes freshness and execution-zone-style context for
  review only

## Safety

This app is read-only.

Safety boundaries:

- read-only
- no DB writes
- no broker writes
- no order submission
- no executor
- no paper trading
- no live trading

The repository layer uses read queries only through `get_connection()` and does
not create any execution path.

## Relation To Cockpit

This app and the static cockpit serve different purposes.

`apps/synth_chart_app_v1.py`:

- interactive Streamlit chart review
- manual inspection tool
- chart-first visual analysis

`/var/www/html/synth` cockpit pages:

- static HTML dashboards
- lightweight operational readout
- table/card review surfaces

The Streamlit app should be treated as the interactive chart companion to the
static cockpit, not as a replacement for the cockpit pages.

## Reuse Direction

This existing chart framework should be reused for lifecycle outcome visual
review instead of building a separate chart system.

That means the next extension should be:

- lifecycle outcome event overlay from
  `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`

Planned reuse path:

- keep `synth_chart_app_v1.py` as the interactive chart shell
- add lifecycle-event selection / overlay controls
- reuse `src/ui_chart` repository/renderer patterns where possible
- keep lifecycle outcome visualization read-only and research-only

## Boundary Notes

This documentation is intentionally narrow:

- it documents the existing app as found
- it does not redefine cockpit architecture
- it does not promote this app into execution or paper trading
- it does not add account-aware trade permission logic

The app remains an interactive chart-review framework only.
