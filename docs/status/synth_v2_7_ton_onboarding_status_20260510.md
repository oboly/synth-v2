# Synth v2.7 TON Onboarding Status — 2026-05-10

Status: completed  
Runtime impact: market-chain only  
Decision impact: none  
Execution impact: none  
Broker impact: none  
Live trading: not enabled  
External PRO fibo values: research-only  

## Summary

TON has been added to the Synth universe and bootstrapped through the market-only runtime chain.

TON is now present in:

- asset table
- Bitvavo candle history
- feature layer
- selection state
- trade setup filter observations
- PRO fibo reference verifier

TON must still be treated as newly onboarded until enough runtime observations and policy outcomes exist.

## Asset

| Field | Value |
|---|---|
| symbol | TON |
| asset_id | 71 |
| name | Toncoin |
| venue | bitvavo |
| market | TON-EUR |
| quote_asset | EUR |
| asset_class | LARGE_ALT |
| is_enabled | 1 |
| is_portfolio | 1 |
| is_tradeable | 1 |

## Candle coverage after bootstrap

| Table | Interval | Rows | Min timestamp UTC | Max timestamp UTC |
|---|---:|---:|---|---|
| obs_market_candle | 1d | 640 | 2024-08-09 00:00:00 | 2026-05-10 00:00:00 |
| obs_market_candle | 4h | 3831 | 2024-08-09 12:00:00 | 2026-05-10 12:00:00 |
| obs_market_candle | 1h | 15001 | 2024-08-09 12:00:00 | 2026-05-10 13:00:00 |

## Feature coverage after bootstrap

| Table | Interval | Rows | Min timestamp UTC | Max timestamp UTC |
|---|---:|---:|---|---|
| feat_candle | 1d | 90 | 2026-02-09 00:00:00 | 2026-05-09 00:00:00 |
| feat_candle | 4h | 180 | 2026-04-10 12:00:00 | 2026-05-10 08:00:00 |
| feat_candle | 1h | 238 | 2026-04-30 14:00:00 | 2026-05-10 13:00:00 |

## Runtime visibility

TON appeared in selection/trade setup after bootstrap.

Observed 4h / 1h market-chain state:

| Field | Value |
|---|---|
| selection_state | WATCHLIST |
| selection_bias | DEFENSIVE |
| selection_score | 0.529516 |
| priority_rank | 12 |
| setup_filter_state | FAIL |
| setup_filter_reason | RANK_OUTSIDE_SWEET_SPOT |
| target_horizon | NONE |

This is market-only visibility. It is not permission to trade.

## Bootstrap nuance

An early bootstrap row showed TON as AVOID with missing advice timestamps.

This is treated as a bootstrap/order-of-operations artifact, not as a stable strategic classification.

Future research/backtest filters should be able to exclude or mark onboarding/bootstrap snapshots where required.

## PRO fibo reference values

TON PRO reference values from the 2026-05-07 Crypto Masterminds session are preserved in the research-only external reference lane.

TON values:

- continuation close range: 3.68 to 3.69
- shoulder break: 7.26
- target zone 1: 8.70 to 9.10
- target 2: 12
- extended target: 17

These values are external PRO context only.

They are not verified truth and are not direct signals.

## Architectural boundary

The PRO fibo reference lane may feed:

- research charts
- harvest maps
- fib/exit-profile comparison
- external target annotations
- candidate exit-profile hints

The PRO fibo reference lane must not feed directly:

- selection_engine override
- decision_gate override
- execution_planner instruction
- executor/order logic
- live or paper execution trigger

## Maintenance lock

A market-chain maintenance lock was added after TON onboarding.

Default lock path:

    /tmp/synth_maintenance.lock

Use this before future onboarding/backfill work:

    echo "asset onboarding / candle backfill" > /tmp/synth_maintenance.lock

Remove it after controlled work finishes:

    rm -f /tmp/synth_maintenance.lock

The lock prevents cron chains from writing partial/inconsistent runtime snapshots during maintenance.

## Relevant commits

- 173334a Clean maintenance guard forbidden scan comment
- 2b8adf5 Add market chain maintenance lock
- 32add7b Clean PRO fibo reference doc whitespace
- dab9655 Add PRO fibo reference verifier
- 2efa418 Add sell-only execution plan preview

## Current boundary status

| Layer | Status |
|---|---|
| market cron chains | active |
| maintenance lock | installed, not active |
| selection_engine | market-only |
| trade_setup_filter | market-only |
| policy_preview | research/policy visibility only |
| decision_gate | sell-only preview lane exists |
| execution_planner | sell-only preview lane exists |
| broker submission | disabled |
| live trading | not enabled |

## Next recommended step

Add research-only PRO fibo annotations / harvest-map visibility for TON, TAO, and NEAR.

Do not connect those annotations to decision_gate, execution_planner, executor, or live/paper execution.
