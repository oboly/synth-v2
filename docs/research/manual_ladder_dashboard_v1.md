# Manual Ladder Dashboard V1

## Status

Initial reporting-only implementation for Synth v2.14.

Runner:

```text
src/reporting/run_manual_ladder_static_dashboard_v1.py
```

Default smoke output:

```text
/tmp/manual_ladder_dashboard_v1.html
```

Later Odroid publish target:

```text
/var/www/html/synth/manual-ladders.html
```

## Purpose

Render the first Breath-Fibo-Regime manual dashboard.

Primary reading order:

```text
1. Breathline / A+ phase and prognosis
2. Fibo + external zone map
3. Regime as first Synth interpretation layer
4. Price position inside the map
5. Synth confirmation sensors
6. Manual ladder / review state
7. Debug details
```

This dashboard is not the old Paper Advice dashboard with cosmetic changes. The old Paper Advice dashboard remains debug/review context.

## Architecture boundary

Allowed:

```text
static HTML render
read-only DB queries
read-only CSV research-map input
market-only context display
manual review ladder display
```

Forbidden:

```text
broker private calls
broker writes
order submission
decision_gate changes
execution_planner changes
executor changes
selection_engine behavior changes
setup_filter behavior changes
live trading
account-aware sizing or allocation
```

The output is manual context only. The user places or cancels orders manually.

## Inputs

V1 uses best-effort existing sources:

```text
paper_advice_observation
obs_market_candle
data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv
strategy_runtime_snapshot or comparable regime snapshot tables if available
manual ALGO/WLD fallback context from the v2.14 chat bundle
```

Missing sources are displayed as unavailable rather than forcing a false conclusion.

## Current source handling

### Current price

Preferred source:

```text
obs_market_candle.close_price
```

The runner tries common asset joins and falls back cleanly if the schema differs.

### Fibo / map context

Preferred source:

```text
data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv
```

If no row is found:

```text
FIB_MAP_UNKNOWN
```

### Regime

Preferred source order:

```text
strategy_runtime_snapshot
market_regime_snapshot
regime_snapshot
```

If unavailable:

```text
not available
```

Regime is shown as interpretation context only, not permission.

### Manual fallback examples

V1 includes explicit ALGO and WLD fallback context from the v2.14 chat bundle so the first dashboard smoke can preserve the desired reading model even when local map data is incomplete.

ALGO fallback:

```text
current context around 0.113067
harvest ladder: 0.114 / 0.120
reload ladder: 0.106 / 0.101
```

WLD fallback:

```text
reaction zone: 0.286849..0.299955
invalidation: 0.244420
next target: 0.355490
```

These are display-context fallbacks, not orders.

## Display model

Per symbol the dashboard shows:

```text
symbol
current price
price freshness/source
Breathline/A+ phase/context if available
Fibo/external map source
regime context
leg direction
invalidation
support/reaction/reload zone
T1 / first reaction target
T1 touched status
next target
runner target
harvest ladder
reload ladder
source modules
debug payload
```

## State labels

Neutral dashboard labels:

```text
NEAR_T1
T1_TOUCHED
WAIT_RETEST
REBUY_ZONE_NEAR
INVALIDATION_NEAR
NO_MAP
FIB_MAP_UNKNOWN
MANUAL_ONLY
```

Old dashboard labels such as `AVOID`, `BUY_READY`, `SETUP_FAIL`, `NO_EDGE_PERMISSION`, `POLICY_WATCH_ONLY`, and `SELECTION_STATE_NOT_ELIGIBLE` are not headline state in this dashboard.

## Key display rule

Do not hide the next target after first target is touched.

Show separately:

```text
T1 / first reaction target
T1 touched status
next target
runner target
```

This fixes the WLD-style issue where a first reaction-zone touch can obscure the higher runner target.

## Commands

Compile:

```bash
python -m py_compile src/reporting/run_manual_ladder_static_dashboard_v1.py
```

Smoke render:

```bash
python -m src.reporting.run_manual_ladder_static_dashboard_v1 \
  --venue bitvavo \
  --quote EUR \
  --interval 4h \
  --limit 80 \
  --output-html /tmp/manual_ladder_dashboard_v1.html \
  --output summary
```

Expected safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
account_awareness=0
```

## Known V1 limitations

- Breathline/A+ fields depend on what is already present in joined source rows; there is no new A+ DB integration in this runner.
- External zones are not normalized yet; V1 only reads the fib target map CSV and manual fallback examples.
- Regime context is a best-effort display string from existing snapshot tables.
- Confirmation sensors are deliberately secondary; old policy/action labels are not promoted to headline state.
- No Odroid service/timer is added yet.

## Next steps

P1:

```text
normalize external zones as map inputs
add explicit source/freshness/precision labels for external zones
improve regime-to-playbook display labels
publish to /var/www/html/synth/manual-ladders.html only after local smoke review
```

Still forbidden:

```text
external zone -> direct BUY_READY
manual ladder -> order creation
regime context -> decision_gate permission
research map -> executor
```
