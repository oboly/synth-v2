# Position Lifecycle Outcome Validation V1

## Purpose

`run_position_lifecycle_outcome_validation_v1.py` is a research-only runner that
measures what happened after account-aware position lifecycle review labels.

This is outcome validation only.

It is not:

- a strategy backtest
- paper execution
- simulated fills
- live trading
- executor enablement

The labels being measured are manual review states, not orders:

- `TRIM_REVIEW`
- `REDUCE_REVIEW`
- `HOLD`
- `RELOAD_REVIEW`

## Questions

Primary questions:

- Did `TRIM_REVIEW` occur before pullback or drawdown?
- Did `REDUCE_REVIEW` avoid poor forward outcomes, or is it too conservative?
- Did `HOLD` outperform trim/reduce review labels?
- Are target-touch trim labels useful on `15m`, `30m`, `1h`, `2h`, `4h`, `8h`,
  and `24h` horizons?

## Boundary

This lane is account-aware read-only research because it validates lifecycle
review for existing positions.

Allowed:

- read `account_position_snapshot`
- read historical `paper_advice_observation`
- read public `market_price_snapshot`
- read public `obs_market_candle`
- reconstruct lifecycle review events for research
- write research artifacts under `data/research/...`

Forbidden:

- broker calls
- broker writes
- order submission
- paper fills
- executor
- live trading
- changing `selection_engine`
- changing `decision_gate`
- changing `execution_planner`

## Reconstruction Rule

There is currently no stored historical lifecycle-event table and no reliable
historical `position_rotation_preview` output history.

There is also no reliable historical `execution_zone_context` series for this
lane. Operational `execution_zone_context` is latest-only.

Therefore the runner reconstructs historical lifecycle review events from:

- `account_position_snapshot`
- historical `paper_advice_observation` zone fields
- historical `market_price_snapshot` when available
- historical `obs_market_candle` 15m path data

If this reconstruction is not possible because required history is missing, the
runner fails closed and reports exact blockers.

## Canonical Regime Source

Lifecycle outcome validation reuses the existing canonical regime lane only:

- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/active_regime_observation_preview_v1.md`
- `src/regime/run_active_regime_observation_v1.py`
- DB table: `active_regime_observation`

It does not define a new regime model.
It does not invent new regime categories.
It does not invent new regime thresholds.

Point-in-time lookup rule:

- map each symbol to canonical `asset_class`
- read `active_regime_observation` for the same `venue` and `interval`
- use the latest row at or before `event_ts_utc`

Because canonical downstream freshness rules are not separately documented yet,
historical lifecycle enrichment exposes:

- `regime_asof`
- `source_candle_ts_utc`
- `regime_freshness=UNKNOWN`

## Event Fields

Each reconstructed event row can include:

- `event_ts_utc`
- `symbol`
- `venue`
- `quote`
- `interval`
- `trading_account_id`
- `position_lifecycle_action`
- `position_lifecycle_reason`
- `paper_action`
- `policy_action`
- `position_review_state`
- `setup_fail_reason`
- target / reaction / invalidation context when available
- `current_price`
- `position_qty`
- `position_value`
- `source_modules`
- `missing_inputs`
- intrabar target-touch context when available
- `asset_class`
- `regime_source`
- `regime_asof`
- `regime_source_candle_ts_utc`
- `regime_asset_class`
- `regime_global`
- `regime_global_version`
- `regime_asset_class_state`
- `regime_asset_class_version`
- `regime_bucket`
- `regime_validation_status`
- `regime_validated_hypothesis_tags_json`
- `regime_freshness`
- `regime_lookup_status`
- canonical `global_regime`
- canonical `asset_class_regime`
- canonical `global_class_regime`

Canonical lookup behavior:

- source is `active_regime_observation` only
- join is point-in-time on `venue`, `interval`, mapped `asset_class`, and latest
  `asof_ts_utc <= event_ts_utc`
- `regime_lookup_status=FOUND` when a canonical row is found
- `regime_lookup_status=UNKNOWN` when the source exists but no eligible row exists
- `regime_lookup_status=SOURCE_MISSING` when the canonical source table is absent
  or has no usable rows
- `regime_freshness=UNKNOWN` unless canonical freshness rules are defined
- if the source is missing, summary output prints
  `CANONICAL_REGIME_SOURCE_NOT_AVAILABLE`

## Outcome Horizons

Forward outcomes are measured on:

- `15m`
- `30m`
- `1h`
- `2h`
- `4h`
- `8h`
- `24h`

The current runner derives all horizons from 15m public candle history. If a
separate 30m table is absent, that is reported as a warning, not a blocker.

## Metrics

Per event:

- forward return per horizon
- action-adjusted return score per horizon
- `max_favorable_excursion_pct`
- `max_adverse_excursion_pct`
- `drawdown_after_event_pct`
- `hit_target_like_move`
- `broke_invalidation_like_move`
- per-horizon completeness flags

Action intent polarity:

- `HOLD` -> long exposure keep
- `RELOAD_REVIEW` -> long exposure add or restore
- `TRIM_REVIEW` -> reduce exposure review
- `REDUCE_REVIEW` -> reduce exposure review
- `NO_POSITION_LIFECYCLE_EDGE` -> neutral

Raw forward return and action-adjusted usefulness are different.

- For `HOLD` and `RELOAD_REVIEW`, positive forward return is favorable.
- For `TRIM_REVIEW` and `REDUCE_REVIEW`, negative forward return after the event
  can be favorable because the review would have reduced exposure before
  drawdown.

Therefore the runner also computes:

- `adjusted_return_score_h`
- `avoided_drawdown_score_h`
- `opportunity_cost_h`
- `upside_capture_score_h`
- `adverse_move_score_h`

For neutral actions, adjusted score is left `null`, not zero, so the metric does
not imply usefulness where no directional intent existed.

Per lifecycle action summary:

- count
- complete horizon counts
- average and median forward return by horizon
- average and median adjusted score by horizon
- average avoided drawdown at `4h` / `24h`
- average opportunity cost at `4h` / `24h`
- average upside capture at `4h` / `24h`
- average adverse move at `4h` / `24h`
- average and median MFE / MAE

Additional diagnostic summaries:

- by lifecycle action
- by normalized reason bucket
- by action + reason bucket
- by symbol
- by action + symbol
- optional market-leg and freshness buckets
- promotion-diagnostic bucket report on action + reason only
- by canonical regime bucket and state
- `RELOAD_REVIEW` by canonical regime bucket and state
- `RELOAD_REVIEW|APLUS_CONTEXT` by canonical regime bucket and state
- `HOLD` by canonical regime bucket and state
- `TRIM_REVIEW` by canonical regime bucket and state
- `REDUCE_REVIEW` by canonical regime bucket and state

## Sampling Modes

Repeated lifecycle rows can be highly autocorrelated.

Supported modes:

- `--event-mode all`
  - every reconstructed event row is used
- `--event-mode transition-only`
  - only rows where `symbol` changes lifecycle action versus the previous row
- `--event-mode cooldown`
  - keeps the first `symbol + lifecycle_action` row
  - skips repeated rows of that same `symbol + lifecycle_action` until
    `--cooldown-minutes` has elapsed

This does not make the study causal. It only reduces repeated-state inflation.

`transition-only` should be the first interpretation view because repeated
position rows can otherwise overstate the apparent sample size of a lifecycle
state.

## Diagnostic Buckets

Reason buckets are diagnostic summaries, not strategy rules.

Current conservative normalized buckets can include:

- `TARGET_TOUCH_INTRABAR`
- `EXTENSION_TOUCH_INTRABAR`
- `TARGET_REACHED_STALE`
- `INVALIDATION_NEAR`
- `INVALIDATION_TOUCHED`
- `RECLAIM_CONFIRMED`
- `RECOMPUTE_PENDING`
- `CHASE_RISK`
- `SETUP_FAIL`
- `APLUS_AVOID`
- `APLUS_CONTEXT`
- `SUPPORT_RETEST_BELOW`
- `REACTION_ZONE_NEAR`
- `UNKNOWN_REASON_BUCKET`

These buckets are inferred from currently available event fields and reason
context. They are not canonical runtime states.

Primary bucket priority is intentional:

- target / intrabar / extension context outranks generic setup failure
- invalidation / reclaim context outranks generic setup failure
- chase-risk and market-damage context outrank generic setup failure
- recompute / wait-fresh-map context outranks generic setup failure
- `APLUS_AVOID` outranks generic `APLUS_CONTEXT`
- `SETUP_FAIL` is fallback only when no more specific bucket is available

If available, `secondary_reason_buckets` retain all matched contexts while the
summary tables continue to use one primary bucket for grouping.

Interpretation warnings:

- bucket inference is approximate and downstream of the original review label
- one symbol can dominate a bucket and create a false sense of generality
- symbol concentration must be checked before treating a bucket as reusable edge
- action + reason is usually more informative than action alone
- `SETUP_FAIL` should be treated as unresolved leftover context, not as a useful
  edge bucket by itself

## Interpretation Rules

Interpret results narrowly.

- `TRIM_REVIEW` means trim/harvest review context only, not an executed trim.
- `REDUCE_REVIEW` means defensive review context only, not a sell.
- `HOLD` means no stronger manual review edge was visible from current inputs.
- `RELOAD_REVIEW` means reload/support review context only, not proof that a
  prior trim happened.

Adjusted usefulness is diagnostic, not a promotion rule.

- A positive adjusted score does not prove a deployable edge.
- A high avoided-drawdown score for reduce/trim review can still come with high
  opportunity cost.
- A high upside-capture score for hold/reload context can still hide large
  adverse-move risk.
- Promotion diagnostics must still pass later baseline, symbol-concentration, and
  regime checks before any separate research lane considers promotion.

## Lifecycle Bucket Promotion Diagnostics

The runner also emits a read-only diagnostic report that flags promising and
dangerous `action + reason_bucket` combinations using action-adjusted metrics.

This is not strategy promotion.

It does not:

- change `selection_engine`
- change `decision_gate`
- change `execution_planner`
- change dashboards
- enable paper trading
- enable live trading

Default minimum bucket size is `20`, configurable with:

- `--min-bucket-count 20`

The report includes:

- `promotion_candidate_buckets`
- `strong_promotion_candidate_buckets`
- `rejection_candidate_buckets`
- `needs_more_sample_buckets`
- `high_opportunity_cost_buckets`
- `high_protection_buckets`
- `high_reload_upside_buckets`

Current criteria:

- promotion candidate:
  - `avg_adjusted_score_4h > 0`
  - `avg_adjusted_score_24h >= 0` or missing
  - `count >= min_bucket_count`
- strong promotion candidate:
  - `avg_adjusted_score_4h >= 0.5`
  - `count >= min_bucket_count`
- rejection candidate:
  - `avg_adjusted_score_4h < 0`
  - `count >= min_bucket_count`
- high opportunity cost:
  - trim/reduce buckets ranked by `avg_opportunity_cost_4h`
- high protection:
  - trim/reduce buckets ranked by `avg_avoided_drawdown_4h`
- high reload upside:
  - `HOLD` / `RELOAD_REVIEW` buckets ranked by `avg_upside_capture_4h`

Interpretation warnings:

- These buckets are research diagnostics only.
- They are not approval to promote a lifecycle bucket into runtime logic.
- A bucket can look strong because one symbol dominates it.
- A bucket can look protective while still imposing large opportunity cost.
- Any later promotion review still needs bucket-vs-baseline, symbol-level, and
  regime-level checks.

When `--write-files` is enabled, the runner now also writes:

- `lifecycle_bucket_promotion_candidates_v1.csv`
- `lifecycle_bucket_promotion_candidates_v1.json`
- `TRIM_REVIEW` and `REDUCE_REVIEW` remain review labels, not sell orders.

Do not promote these labels into strategy logic or execution behavior without
validation.

Validation here still does not cover:

- fills
- fees
- slippage
- order timing
- capital sizing
- account constraints

## Safety

Required safety markers:

```text
broker_calls=0
broker_writes=0
order_submission=0
executor=none
live_trading=false
```

## Outputs

When `--write-files` is enabled:

```text
data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl
data/research/position_lifecycle_outcome_validation_v1/outcome_summary_v1.json
data/research/position_lifecycle_outcome_validation_v1/manifest_v1.json
data/research/position_lifecycle_outcome_validation_v1/bucket_summary_by_action_reason_v1.csv
data/research/position_lifecycle_outcome_validation_v1/bucket_summary_by_symbol_v1.csv
data/research/position_lifecycle_outcome_validation_v1/bucket_summary_by_action_reason_adjusted_v1.csv
data/research/position_lifecycle_outcome_validation_v1/bucket_summary_by_symbol_adjusted_v1.csv
```
