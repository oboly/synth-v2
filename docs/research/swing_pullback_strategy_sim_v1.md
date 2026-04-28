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

## Correction after v5/v6 exclusion hook repair

The first v5/v6 no-symbol-block run did not actually apply the custom score exclusions because
`build_policy_where()` appended exclusion clauses to a non-existing `where` variable.

Fix:

- `build_policy_where()` now appends custom exclusion clauses to `filters`
- v5/v6 filters are confirmed active because v5 and v6 now produce different counts and results
- no symbol blocker is used for v5/v6
- universe quality is handled outside this runner

Corrected active-filter result:

### Primary candidate

`swing_pullback_recovery_v5`

- hold_hours = 24
- cooldown_hours_per_symbol = 24
- max_trades_per_snapshot = 2
- valid_test_splits = 8
- positive_test_splits = 7
- negative_test_splits = 1
- zero_trade_test_splits = 0
- train_trades = 132
- test_trades = 31
- avg_train = 0.031618
- avg_test = 0.027586
- avg_retention = 0.8725
- avg_train_comp = 0.617647
- avg_test_comp = 0.108999
- compound_retention = 0.1765
- test_comp_product = 1.207758

### Secondary candidate

`swing_pullback_recovery_v6`

- hold_hours = 24
- cooldown_hours_per_symbol = 24
- max_trades_per_snapshot = 2
- valid_test_splits = 8
- positive_test_splits = 7
- negative_test_splits = 1
- zero_trade_test_splits = 0
- train_trades = 126
- test_trades = 30
- avg_train = 0.033448
- avg_test = 0.027198
- avg_retention = 0.8131
- test_comp_product = 1.111102

Interpretation:

- v5 is currently preferred over v6
- v5 keeps slightly more coverage
- v5 has the better corrected test compound product
- both remain 24h swing-recovery research candidates
- neither is approved for decision_gate, execution_planner, paper trading, or live trading

Current status:

- `swing_pullback_recovery_v5` = PRIMARY_RESEARCH_CANDIDATE
- `swing_pullback_recovery_v6` = SECONDARY_RESEARCH_CANDIDATE
- no symbol-block strategy logic
- universe quality must be handled upstream

## V5 walk-forward stress validation

`swing_pullback_recovery_v5` was stress-tested without adding new filters.

Policy shape:

- selection_state = WATCHLIST
- priority_rank between 1 and 10
- btc_prior_24h between -0.030 and 0.000
- rotation_bucket = ROTATION_EARLY
- classification_code = PULLBACK_WATCH
- sleeve_fit_code = SWING_STRUCTURAL
- no symbol blocker
- excludes only the weak context bucket:
  - selection_score >= 0.50000000
  - selection_score < 0.52000000
  - priority_rank between 4 and 6

Stress results:

| Case | Splits | Valid | Positive | Negative | Train trades | Test trades | Avg train | Avg test | Test compound product |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline 14d train / 3d test | 8 | 8 | 7 | 1 | 132 | 31 | 0.031618 | 0.027586 | 1.207758 |
| strict min 2 test trades | 8 | 7 | 6 | 1 | 132 | 31 | 0.031618 | 0.028881 | 1.167619 |
| short 10d train / 3d test | 9 | 9 | 8 | 1 | 106 | 38 | 0.030727 | 0.026182 | 1.947197 |
| long 21d train / 3d test | 6 | 6 | 5 | 1 | 152 | 20 | 0.031640 | 0.026980 | 0.774970 |
| later-only 10d train / 3d test | 5 | 5 | 4 | 1 | 56 | 21 | 0.030962 | 0.020003 | 0.698084 |

Interpretation:

- V5 survives train-window sensitivity.
- V5 survives later-window validation.
- The edge remains 24h-oriented.
- The result does not justify short-horizon execution.
- The strategy remains market-only research logic.
- It is still not allowed to bypass decision_gate or execution_planner.

Current status:

- RESEARCH_PROMOTION_CANDIDATE
- eligible for further paper-candidate design
- not approved for live trading
- not connected to account-aware layers

## Final V5 research promotion verdict

`swing_pullback_recovery_v5` survived the first cost-stress pass.

Cost-stress result:

- baseline net return with 25 bps per side: 0.029066
- net return with 50 bps per side: 0.024066
- net return with 75 bps per side: 0.019066
- net return with 100 bps per side: 0.014066
- net return with 25 bps per side plus 25 bps total slippage: 0.026566

Verdict:

- status = RESEARCH_PROMOTION_CANDIDATE
- preferred hold horizon = 24h
- preferred max trades per snapshot = 2
- preferred cooldown per symbol = 24h
- no symbol blocker inside the strategy
- universe quality must be handled upstream by the tradable universe / asset selection process

Architectural boundary:

This candidate remains market-only research logic.

It must not read:

- balances
- open orders
- live positions
- execution plans
- account state

It must not write:

- decision_state
- execution_intent
- execution_plan
- orders
- account-aware portfolio state

Next allowed step:

Design a paper-candidate wrapper/spec that can be evaluated by `decision_gate` later.

Not allowed:

Direct wiring from this research runner into `decision_gate`, `execution_planner`, executor, or live trading.

## Default runner policy

After promotion to `RESEARCH_PROMOTION_CANDIDATE`, the runner default policy was changed to:

- `swing_pullback_recovery_v5`

Older policies remain available for explicit comparison, but they are no longer the default research path.

This does not promote v5 into production.

The runner remains research-only and must not be wired directly into:

- decision_gate
- execution_planner
- executor
- account-aware portfolio layers
