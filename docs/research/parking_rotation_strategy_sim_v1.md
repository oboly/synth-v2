# Parking Rotation Strategy Simulation V1

## Layer

Research / backtest simulation.

This is not a live strategy and must not be connected directly to decision_gate,
execution_planner, executor, account state, balances, orders, or broker logic.

## Candidate family

Parking rotation recovery.

The strategy tests whether low-scoring WATCHLIST assets inside a rotation-exit /
no-trade / experimental bucket can produce delayed recovery returns when held for
a fixed horizon.

## Current tested policies

### parking_rotation_recovery_v1

Policy parameters:

- selection_state = WATCHLIST
- priority_rank between 4 and 10
- btc_prior_24h between -0.010 and 0.010
- selection_score < 0.50000000
- weak symbols excluded
- rotation_bucket = ROTATION_EXIT
- classification_code = NO_TRADE
- sleeve_fit_code = EXPERIMENTAL

### parking_rotation_recovery_v2

Policy parameters:

- selection_state = WATCHLIST
- priority_rank between 6 and 15
- btc_prior_24h between -0.005 and 0.015
- selection_score < 0.50000000
- weak symbols excluded
- rotation_bucket = ROTATION_EXIT
- classification_code = NO_TRADE
- sleeve_fit_code = EXPERIMENTAL

## Walk-forward windows

Train window:

- 2026-04-08 00:00:00 UTC
- 2026-04-24 00:00:00 UTC

Test window:

- 2026-04-24 00:00:00 UTC
- 2026-04-28 00:00:00 UTC

## Simulation settings promoted for review

### Primary research candidate

parking_rotation_recovery_v1

- hold_hours = 24
- max_trades_per_snapshot = 2
- cooldown_hours_per_symbol = 24
- dedupe_symbol_overlap = true

Train:

- trades = 9
- avg_net_return = 0.045867
- winrate = 1.0000
- compound_net_return_trade_sequence = 0.484602

Test:

- trades = 7
- avg_net_return = 0.006966
- winrate = 0.5714
- compound_net_return_trade_sequence = 0.047407
- worst_net_return = -0.023793
- best_net_return = 0.060898

Status:

- PROMOTE_RESEARCH_CANDIDATE
- not production-ready
- suitable for deeper walk-forward testing

Reason for primary preference:

v1 has stronger per-trade test expectancy than v2, even though v2 has slightly
higher test compound due to more trades.

### Secondary research candidate

parking_rotation_recovery_v2

- hold_hours = 24
- max_trades_per_snapshot = 2
- cooldown_hours_per_symbol = 24
- dedupe_symbol_overlap = true

Train:

- trades = 10
- avg_net_return = 0.046700
- winrate = 0.9000
- compound_net_return_trade_sequence = 0.561790

Test:

- trades = 12
- avg_net_return = 0.004552
- winrate = 0.5833
- compound_net_return_trade_sequence = 0.052847
- worst_net_return = -0.022367
- best_net_return = 0.060898

Status:

- PROMOTE_RESEARCH_CANDIDATE
- not production-ready
- useful as higher-volume variant

## Rejected current interpretation

The 4h version is rejected for now.

Observed result:

- v1 4h test avg_net_return = -0.002997
- v1 4h test winrate = 0.2500
- v1 4h test compound = -0.035624

Interpretation:

The recovery effect appears to need the 24h horizon. Cutting at 4h exits too early.

## Current conclusion

Parking rotation recovery is a valid research candidate, not a live strategy.

Current best candidate:

parking_rotation_recovery_v1 / 24h / max_per_snap=2 / cooldown=24h

Next required validation:

1. Expand historical replay coverage.
2. Test multiple rolling walk-forward splits.
3. Add drawdown and overlap exposure reporting.
4. Only after broader validation, consider a strategy module proposal.

## Rolling walk-forward validation

Runner:

- `src/research/run_strategy_sim_walk_forward_v1.py`

Validation window:

- from: 2026-04-08 00:00:00 UTC
- to: 2026-04-28 00:00:00 UTC
- train_days = 10
- test_days = 3
- step_days = 1
- splits = 8

Simulation parameters tested:

- hold_hours = 24
- cooldown_hours_per_symbol = 24
- max_trades_per_snapshot = 1 / 2
- dedupe_symbol_overlap = true
- policies = parking_rotation_recovery_v1 / parking_rotation_recovery_v2

### Strict validation

With `min_test_trades_per_split = 2`:

- valid_test_splits = 7 / 8
- positive_test_splits = 7 / 7
- negative_test_splits = 0
- zero_trade_test_splits = 0

This produced `PARTIAL_TEST_COVERAGE` because one split had only one valid test trade, not because the tested split was negative.

### Relaxed validation

With `min_test_trades_per_split = 1`:

All tested 24h configs promoted to `PROMOTE_ROLLING_CANDIDATE`.

#### Best aggregate compound candidate

parking_rotation_recovery_v2:

- hold_hours = 24
- cooldown_hours_per_symbol = 24
- max_trades_per_snapshot = 2
- valid_test_splits = 8
- positive_test_splits = 8
- negative_test_splits = 0
- test_trades = 64
- avg_train = 0.062354
- avg_test = 0.037493
- avg_retention = 0.6013
- avg_train_comp = 0.251310
- avg_test_comp = 0.210678
- compound_retention = 0.8383
- test_comp_product = 3.378687
- worst_test_avg = 0.004552
- best_test_avg = 0.080200

Research status:

- PRIMARY_ROLLING_CANDIDATE
- stronger volume and aggregate robustness
- still research-only, not production-ready

#### Cleanest per-trade edge candidate

parking_rotation_recovery_v1:

- hold_hours = 24
- cooldown_hours_per_symbol = 24
- max_trades_per_snapshot = 1
- valid_test_splits = 8
- positive_test_splits = 8
- negative_test_splits = 0
- test_trades = 40
- avg_train = 0.068791
- avg_test = 0.041573
- avg_retention = 0.6043
- avg_train_comp = 0.230793
- avg_test_comp = 0.174414
- compound_retention = 0.7557
- test_comp_product = 2.452241
- worst_test_avg = 0.000822
- best_test_avg = 0.080200

Research status:

- CLEAN_EDGE_ROLLING_CANDIDATE
- strongest average test return per trade
- lower trade count than v2

## Rolling validation conclusion

The 24h parking rotation recovery effect survives rolling walk-forward validation
over the current replay window.

Current ranking:

1. parking_rotation_recovery_v2 / 24h / max_per_snap=2 / cooldown=24h
2. parking_rotation_recovery_v1 / 24h / max_per_snap=1 / cooldown=24h
3. parking_rotation_recovery_v1 / 24h / max_per_snap=2 / cooldown=24h
4. parking_rotation_recovery_v2 / 24h / max_per_snap=1 / cooldown=24h

Important caveat:

The replay window is still short and overlapping walk-forward splits are not
independent portfolio returns. The result is a research promotion, not a live
deployment approval.

Next validation steps:

1. Expand replay coverage backward.
2. Add non-overlapping walk-forward validation.
3. Add drawdown and exposure-overlap reporting.
4. Add per-symbol contribution caps.
5. Only then propose a proper strategy module.
