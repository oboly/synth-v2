# Swing Pullback Strategy Simulation V1

## Layer

Research / backtest simulation.

This is not a live strategy and must not be connected directly to:

- decision_gate
- execution_planner
- executor
- account state
- balances
- positions
- orders
- broker logic

## Candidate family

Swing pullback recovery.

The strategy tests whether early rotation pullback candidates inside the
`SWING_STRUCTURAL` sleeve produce positive fixed-horizon forward returns.

Core context:

- rotation_bucket = ROTATION_EARLY
- classification_code = PULLBACK_WATCH
- sleeve_fit_code = SWING_STRUCTURAL

This is structurally cleaner than the parking rotation recovery family because
it works with early pullback context instead of degraded rotation-exit context.

## Current tested policies

### swing_pullback_recovery_v1

- selection_state IN WATCHLIST, PREPARE, BUY_READY
- priority_rank between 1 and 3
- btc_prior_24h between -0.030 and 0.000
- no selection_score floor
- weak symbols excluded
- rotation_bucket = ROTATION_EARLY
- classification_code = PULLBACK_WATCH
- sleeve_fit_code = SWING_STRUCTURAL

### swing_pullback_recovery_v2

Same as v1, plus:

- selection_score >= 0.52000000

### swing_pullback_recovery_v3

- selection_state IN WATCHLIST, PREPARE, BUY_READY
- priority_rank between 1 and 10
- btc_prior_24h between -0.030 and 0.000
- no selection_score floor
- weak symbols excluded
- rotation_bucket = ROTATION_EARLY
- classification_code = PULLBACK_WATCH
- sleeve_fit_code = SWING_STRUCTURAL

### swing_pullback_recovery_v4

Same as v3, plus:

- selection_score >= 0.52000000

## Expanded non-overlapping walk-forward validation

Runner:

- `src/research/run_swing_pullback_strategy_sim_v1.py`

Validation window:

- from: 2026-03-20 00:00:00 UTC
- to: 2026-04-28 00:00:00 UTC
- train_days = 14
- test_days = 3
- step_days = 3
- splits = 8

Simulation settings:

- hold_hours = 24
- cooldown_hours_per_symbol = 24
- max_trades_per_snapshot = 1 / 2
- dedupe_symbol_overlap = true
- min_test_trades_per_split = 2
- min_valid_test_splits = 2

## Result summary

All tested variants passed as `PASS_WITH_ONE_WEAK_SPLIT`.

Best aggregate candidate:

### swing_pullback_recovery_v3, max_trades_per_snapshot = 2

- valid_test_splits = 6 / 8
- positive_test_splits = 5
- negative_test_splits = 1
- zero_trade_test_splits = 0
- train_trades = 143
- test_trades = 34
- avg_train = 0.027519
- avg_test = 0.024124
- avg_retention = 0.8766
- avg_train_comp = 0.557812
- avg_test_comp = 0.083962
- compound_retention = 0.1505
- test_comp_product = 0.594194

Interpretation:

- v3 has the strongest aggregate compound result.
- v3 also has better coverage than v1/v2 because it avoids zero-trade test splits.
- v1/v2 are cleaner rank filters but have weaker coverage.
- v4 score floor reduces trade count and does not improve the result enough to justify the extra filter.

## Current status

- RESEARCH_CANDIDATE
- stronger than parking_rotation_recovery after sleeve-fit repair
- not approved for decision_gate
- not approved for execution_planner
- not approved for paper/live trading

## Next validation steps

1. Run a 4h versus 24h sanity check.
2. Confirm whether this is a true swing edge or only delayed 24h recovery.
3. Check symbol concentration and worst-split composition.
4. Only after that, consider converting the candidate into a persistent named research policy.

## 4h versus 24h sanity check

A focused sanity check compared `swing_pullback_recovery_v3` and
`swing_pullback_recovery_v4` across 4h and 24h holding horizons.

Result:

- 24h hold remains the only structurally valid horizon.
- 4h hold is positive in some configurations, but unstable.
- 4h with 24h cooldown turns weak or negative.
- v4 score floor reduces coverage and does not improve robustness enough.
- v3 remains the preferred candidate.

Best current candidate:

- policy = swing_pullback_recovery_v3
- hold_hours = 24
- max_trades_per_snapshot = 2
- cooldown_hours_per_symbol = 24 or 4 produced identical 24h result in this test
- valid_test_splits = 6
- positive_test_splits = 5
- negative_test_splits = 1
- train_trades = 143
- test_trades = 34
- avg_train = 0.027519
- avg_test = 0.024124
- avg_retention = 0.8766
- test_comp_product = 0.594194

Interpretation:

This behaves like a delayed swing recovery edge, not a tactical 4h edge.
Do not promote this as a short-horizon exit strategy.

Current status:

- RESEARCH_CANDIDATE
- 24h-only candidate
- not approved for decision_gate
- not approved for execution_planner
- not approved for paper/live trading

## No-symbol-block refinement

Symbol blocking was deliberately removed from the policy layer.

Reason:

- universe quality belongs upstream
- research policy should test market context, not hard-code asset exclusions
- decision/execution layers must not inherit symbol hygiene hacks from research

Added policies:

### swing_pullback_recovery_v5

Same core context as v3, but:

- selection_state = WATCHLIST
- no weak-symbol exclusion
- excludes the local weak bucket:
  - selection_score >= 0.50000000
  - selection_score < 0.52000000
  - priority_rank between 4 and 6

### swing_pullback_recovery_v6

Same core context as v3, but:

- selection_state = WATCHLIST
- no weak-symbol exclusion
- excludes the full mid-score band:
  - selection_score >= 0.50000000
  - selection_score < 0.52000000

These remain research-only policies.
