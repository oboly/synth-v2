# Intrabar Lifecycle Context V1

## Purpose
Intrabar Lifecycle Context V1 exposes a market-only lower-timeframe lifecycle overlay for cockpit diagnostics.

The operational 4h chain keeps using complete 4h candles for structural maps. This overlay uses latest `market_price_snapshot` and available 15m candles only to show whether the current market has touched, reclaimed, invalidated, or extended a current 4h zone map before the next complete 4h candle exists.

## Boundary
- Market-only.
- Account-agnostic overlay.
- Read-only DB access.
- No broker calls.
- No broker writes.
- No order submission.
- No live orders.
- No `decision_gate` changes.
- No `execution_planner` changes.
- No `executor` changes.
- No `selection_engine` behavior changes.
- Does not contaminate 4h baseline candles with partial candle data.

## Inputs
The helper reads:
- `execution_zone_context` latest 4h structural map per asset
- `market_price_snapshot` latest price
- `obs_market_candle` latest 15m candles when available
- `asset` metadata

It does not read:
- `account_position_snapshot`
- `trading_account_balance_snapshot`
- `broker_order_snapshot`
- broker/private APIs

## Implementation
Helper and CLI:

```bash
src/reporting/intrabar_lifecycle_context_v1.py
```

The helper emits one row per requested symbol or per latest structural map:
- `symbol`
- `venue`
- `structural_interval_code`
- `lifecycle_interval_code`
- `structural_zone_asof_ts_utc`
- `latest_15m_close_ts_utc`
- `current_price`
- `price_source`
- `leg_direction`
- `entry_zone_low`
- `entry_zone_high`
- `tp_zone_low`
- `tp_zone_high`
- `invalidation_price`
- `intrabar_lifecycle_state`
- `intrabar_progress_state`
- `intrabar_recompute_hint`
- `intrabar_reason`
- `data_quality_state`

## State Semantics
Lifecycle states:
- `INTRABAR_ACTIVE`
- `INTRABAR_TARGET_TOUCHED`
- `INTRABAR_TARGET_OVERSHOT`
- `INTRABAR_RECLAIM_TOUCHED`
- `INTRABAR_RECLAIM_CONFIRMED`
- `INTRABAR_INVALIDATION_TOUCHED`
- `INTRABAR_EXTENSION_CONTINUING`
- `INTRABAR_RETESTING_NEW_ZONE`
- `INTRABAR_UNKNOWN`

Recompute hints:
- `INTRABAR_RECOMPUTE_REVIEW`
- `INTRABAR_MONITOR_RECOMPUTE`
- `NO_INTRABAR_RECOMPUTE_HINT`
- `NO_STRUCTURAL_MAP`

Data quality labels:
- `PRICE_SNAPSHOT_FRESH`: latest price snapshot observed within 10 minutes
- `PRICE_SNAPSHOT_STALE`: latest price snapshot older than 10 minutes
- `LTF_CANDLES_FRESH`: latest 15m close within the expected tolerance
- `LTF_CANDLES_STALE`: latest 15m close outside tolerance
- `LTF_HISTORY_SHORT`: fewer than 4 recent 15m candles found
- `LTF_MISSING`: no 15m candle row found
- `STRUCTURAL_MAP_MISSING`: no current 4h structural zone map found

`data_quality_state` can contain multiple semicolon-separated labels, for example:

```text
PRICE_SNAPSHOT_FRESH;LTF_CANDLES_FRESH
PRICE_SNAPSHOT_FRESH;LTF_MISSING
STRUCTURAL_MAP_MISSING;LTF_HISTORY_SHORT;LTF_CANDLES_FRESH
```

## CLI
Run selected symbols:

```bash
python -m src.reporting.intrabar_lifecycle_context_v1 \
  --venue bitvavo \
  --quote EUR \
  --structural-interval 4h \
  --lifecycle-interval 15m \
  --symbols HYPE NEAR BTC ALGO RENDER \
  --output table
```

JSON:

```bash
python -m src.reporting.intrabar_lifecycle_context_v1 \
  --symbols HYPE NEAR BTC ALGO RENDER \
  --output json
```

## Dashboard
The paper advice and rotation dashboards show compact intrabar context:
- intrabar state
- recompute hint
- price source
- latest 15m close timestamp or missing
- data quality labels

Dashboard copy states:

```text
Intrabar context, not trade advice.
```

## Why Incomplete 4h Candles Are Not Used
The 4h structural map remains the baseline because the 4h chain is designed around complete candles. Using incomplete 4h candles would mix partial market movement into the structural baseline and make historical interpretation inconsistent.

This overlay solves a different problem: showing current lifecycle movement against an already-created 4h map.

## Limitations
- The overlay is context only and does not alter paper advice decisions.
- The fast recompute worklist does not consume intrabar hints in V1.
- If `market_price_snapshot` is stale and 15m candles are missing, state can be `INTRABAR_UNKNOWN`.
- 15m candle availability depends on ingestion coverage.

## Verification
Recommended checks:

```bash
python -m py_compile \
  src/reporting/intrabar_lifecycle_context_v1.py \
  src/reporting/run_paper_advice_static_dashboard_v1.py \
  src/reporting/run_position_rotation_static_dashboard_v1.py

python -m src.reporting.intrabar_lifecycle_context_v1 \
  --symbols HYPE NEAR BTC ALGO RENDER \
  --output table

git diff --check
```

Safety markers:
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `live_orders=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
