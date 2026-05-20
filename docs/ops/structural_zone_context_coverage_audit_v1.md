# Structural Zone Context Coverage Audit V1

## Purpose
Structural Zone Context Coverage Audit V1 identifies assets where lower-timeframe market data is fresh but the latest 4h structural zone map is missing or incomplete.

This explains rows that still show missing lifecycle/progress fields such as:
- `LEG_DIRECTION_MISSING`
- `NEXT_ZONE_UNKNOWN`
- `PRICE_PROGRESS_UNKNOWN`
- `TARGET_UNKNOWN`
- `RISK_UNKNOWN`

The audit does not classify these rows as hard blocks. Hard-block severity belongs to paper-advice display calibration, not structural coverage diagnostics.

## Boundary
- Market-only audit/reporting.
- Read-only DB access.
- No broker calls.
- No broker writes.
- No order submission.
- No account mutation.
- No `decision_gate` changes.
- No `execution_planner` changes.
- No `executor` changes.
- No `selection_engine` behavior changes.

## Inputs
Reads:
- `asset`
- `market_price_snapshot`
- `obs_market_candle` 15m
- `execution_zone_context` latest 4h

Does not read:
- `account_position_snapshot`
- `trading_account_balance_snapshot`
- `broker_order_snapshot`
- broker/private APIs

## Implementation
Runner:

```bash
src/reporting/structural_zone_context_coverage_audit_v1.py
```

Per-asset output:
- `symbol`
- `asset_id`
- `venue`
- `structural_interval_code`
- `latest_zone_asof_ts_utc`
- `has_structural_map`
- `has_leg_direction`
- `has_entry_zone`
- `has_target_zone`
- `has_invalidation_price`
- `current_price`
- `price_snapshot_freshness`
- `latest_15m_close_ts_utc`
- `ltf_candle_freshness`
- `coverage_state`
- `missing_fields`
- `recommended_action`

## Coverage States
`STRUCTURAL_MAP_READY`
: Latest 4h structural map exists and has leg direction, entry zone, target zone, and invalidation.

`STRUCTURAL_MAP_PARTIAL`
: A 4h map exists but one or more required structural fields are missing.

`STRUCTURAL_MAP_MISSING`
: No latest 4h `execution_zone_context` row exists for the asset.

`STRUCTURAL_MAP_STALE`
: Structural map is complete but older than the audit freshness threshold.

`MARKET_DATA_READY_BUT_STRUCTURE_MISSING`
: Fresh price and fresh 15m candles exist, but 4h structural map fields are missing or incomplete.

`LTF_DATA_MISSING`
: No recent 15m candle data was found.

`PRICE_DATA_MISSING`
: No latest market price snapshot was found.

## Recommended Actions
`NO_ACTION`
: Structural map coverage is present.

`REFRESH_ZONE_CONTEXT`
: Recompute market-only structural zone context.

`REFRESH_ZONE_AND_ADVICE`
: Refresh zone context and asset-scoped paper advice after stale map detection.

`REVIEW_ASSET_ENABLEMENT`
: Reserved for a future asset metadata audit.

`CHECK_CANDLE_HISTORY`
: Inspect lower-timeframe candle ingestion coverage.

`SKIP_INSUFFICIENT_DATA`
: Insufficient market data for a useful structural coverage action.

## CLI
Selected symbols:

```bash
python -m src.reporting.structural_zone_context_coverage_audit_v1 \
  --venue bitvavo \
  --quote EUR \
  --structural-interval 4h \
  --ltf-interval 15m \
  --symbols HYPE NEAR ALGO RENDER INJ QNT TAO \
  --output table
```

JSON:

```bash
python -m src.reporting.structural_zone_context_coverage_audit_v1 \
  --symbols HYPE NEAR ALGO RENDER INJ QNT TAO \
  --output json
```

## Interpretation
If an asset has:
- fresh `market_price_snapshot`
- fresh 15m candles
- no 4h map or no leg/zone/invalidation fields

then the issue is structural coverage, not intrabar market data.

The expected state is:

```text
MARKET_DATA_READY_BUT_STRUCTURE_MISSING
```

with:

```text
recommended_action=REFRESH_ZONE_CONTEXT
```

## Safety Markers
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `live_orders=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`

## Verification
Recommended checks:

```bash
python -m py_compile src/reporting/structural_zone_context_coverage_audit_v1.py

python -m src.reporting.structural_zone_context_coverage_audit_v1 \
  --symbols HYPE NEAR ALGO RENDER INJ QNT TAO \
  --output table

git diff --check
```
