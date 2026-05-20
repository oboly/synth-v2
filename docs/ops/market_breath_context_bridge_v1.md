# Market Breath Context Bridge V1

## Purpose
Market Breath Context Bridge V1 exposes Synth-native Market Breath context for cockpit and paper-advice diagnostics.

It makes Market Breath the current market-derived context source while keeping A+ Table 1 as read-only legacy freshness metadata. It does not change paper-advice policy behavior.

## Boundary
- Market-only Market Breath input.
- Account-agnostic.
- Read-only DB access.
- No broker calls.
- No broker writes.
- No order submission.
- No live orders.
- No `selection_engine` behavior changes.
- No `decision_gate`, `execution_planner`, `executor`, broker, or order handling imports.
- No conversion of Market Breath into buy/sell logic.

## Implementation
Helper:

```bash
src/reporting/market_breath_context_bridge_v1.py
```

The bridge reuses the Market Breath V1 scoring functions from:

```bash
src/research/run_market_breath_analysis_v1.py
```

Market Breath reads:
- `asset`
- `obs_market_candle`

A+ legacy diagnostics read:
- `aplus_table1_report`
- `aplus_table1_row`

No account tables are queried by the bridge.

## Output Fields
Per symbol:
- `symbol`
- `asof_ts_utc`
- `market_breath_phase`
- `market_breath_state`
- `market_breath_score`
- `market_breath_confidence`
- `compression_score`
- `expansion_score`
- `momentum_score`
- `reversal_pressure_score`
- `relative_strength_score`
- `btc_alignment_score`
- `breadth_alignment_score`
- `market_breath_context_state`
- `market_breath_context_reason`
- `aplus_table1_latest_prediction_ts_utc`
- `aplus_table1_age_hours`
- `aplus_table1_strategic_bias`
- `aplus_legacy_freshness_state`
- `aplus_legacy_block_strength`

## Context Mapping
- `EXHALE_EXPANSION` with positive momentum and relative strength -> `MARKET_BREATH_EXPANSION_CONTEXT`
- `INHALE_ACCUMULATION` -> `MARKET_BREATH_ACCUMULATION_CONTEXT`
- `OVERBREATH_EXTENSION` -> `MARKET_BREATH_LATE_RISK_CONTEXT`
- `COLLAPSE_RESET` -> `MARKET_BREATH_RESET_CONTEXT`
- `NEUTRAL_TRANSITION` -> `MARKET_BREATH_NEUTRAL_CONTEXT`
- `HOLD_COMPRESSION` -> `MARKET_BREATH_COMPRESSION_CONTEXT`
- `INSUFFICIENT_DATA` -> `MARKET_BREATH_UNKNOWN`

## A+ Legacy Freshness
A+ Table 1 is not current market context. It remains external symbolic legacy research metadata.

Freshness:
- `FRESH`: age <= 24h
- `AGING`: age > 24h and <= 72h
- `STALE`: age > 72h and <= 120h
- `VERY_STALE`: age > 120h

When A+ strategic bias is `avoid` and freshness is `STALE` or `VERY_STALE`, the bridge emits:

```bash
aplus_legacy_block_strength=LEGACY_CONTEXT_ONLY
```

This explicitly prevents stale or very stale `APLUS_AVOID` from being represented as a hard current veto in diagnostics.

## CLI
Run current context for selected symbols:

```bash
python -m src.reporting.market_breath_context_bridge_v1 \
  --venue bitvavo \
  --interval 4h \
  --symbols ALGO HYPE RENDER INJ QNT \
  --output table
```

JSON output:

```bash
python -m src.reporting.market_breath_context_bridge_v1 \
  --symbols ALGO HYPE RENDER INJ QNT \
  --output json
```

## Cockpit
`run_paper_advice_static_dashboard_v1` renders a read-only Market Breath Context column for displayed paper-advice rows:
- Market Breath phase/state.
- Market Breath context state.
- A+ legacy age and freshness.
- Suggested combined diagnostic context, for example:

```bash
STALE_APLUS_AVOID + MARKET_BREATH_NEUTRAL_CONTEXT
```

The cockpit does not write these values into `paper_advice_observation`.

## Verification
Recommended checks:

```bash
python -m py_compile \
  src/reporting/market_breath_context_bridge_v1.py \
  src/reporting/run_paper_advice_static_dashboard_v1.py

python -m src.reporting.market_breath_context_bridge_v1 \
  --symbols ALGO HYPE RENDER INJ QNT \
  --output table

git diff --check
```

Safety expectations:
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `live_orders=0`
- account table queries: none
- decision/execution imports: none
