# Structural Missing Refresh v1

`src/advice/run_structural_missing_refresh_v1.py` is a market-only refresh consumer for assets where current market data exists but the latest 4h structural zone context and paper advice are missing.

It is separate from fast recompute:

- Structural missing refresh handles missing `execution_zone_context` / missing `paper_advice_observation`.
- Fast recompute handles stale, reclaimed, invalidated, or target-finished maps that already have structural context.

## Boundary

- Market-only and account-agnostic.
- No broker calls, broker writes, order submission, live orders, decision gate changes, execution planner changes, executor use, or trade intent creation.
- Does not query account tables such as `account_position_snapshot`, `trading_account_balance_snapshot`, or `broker_order_snapshot`.
- Writes require explicit `--write-db` and use only existing market/advice tables: `fib_observation_v2`, `zone_observation_v2`, `execution_zone_context`, and `paper_advice_observation`.

## Eligibility

The runner consumes `paper_advice_structural_consistency_audit_v1` and selects rows where:

- `structural_coverage_state = MARKET_DATA_READY_BUT_STRUCTURE_MISSING`
- `consistency_state = ZONE_MISSING_ADVICE_MISSING`
- `recommended_action = REFRESH_ZONE_AND_ADVICE_FOR_ASSET`
- the asset is enabled and tradeable in the market universe
- enough recent structural candles exist for the requested interval

Eligible rows are throttled by `--max-assets`, default `8`.

## Usage

Dry-run:

```bash
python -m src.advice.run_structural_missing_refresh_v1 \
  --venue bitvavo \
  --interval 4h \
  --quote EUR \
  --symbols APT SXT \
  --max-assets 8 \
  --output table
```

Write smoke:

```bash
python -m src.advice.run_structural_missing_refresh_v1 \
  --venue bitvavo \
  --interval 4h \
  --quote EUR \
  --symbols APT SXT \
  --max-assets 8 \
  --write-db \
  --output table
```

Output scopes include:

- `STRUCTURAL_ZONE_AND_ADVICE_REFRESH`
- `STRUCTURAL_ZONE_REFRESH_ONLY`
- `SKIPPED_NOT_ENABLED`
- `SKIPPED_NO_RECENT_MARKET_DATA`
- `SKIPPED_ALREADY_STRUCTURAL_MAP_READY`
- `SKIPPED_MAX_ASSETS_THROTTLE`
- `SKIPPED_UNKNOWN_DATA`

## Odroid Runtime

`scripts/odroid/run_mvp_market_context_refresh_once.sh` runs structural missing refresh after the market price snapshot and before fast recompute.

Runtime knobs:

- `SYNTH_STRUCTURAL_MISSING_REFRESH_ENABLED`, default `1`
- `SYNTH_STRUCTURAL_MISSING_MAX_ASSETS`, default `8`

Disable it while preserving the rest of dashboard rendering:

```bash
SYNTH_STRUCTURAL_MISSING_REFRESH_ENABLED=0 \
scripts/odroid/run_mvp_market_context_refresh_once.sh
```

## Safety Marker

The runner prints:

```text
broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0
```
