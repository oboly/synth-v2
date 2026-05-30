# Reload Reaction Scalp Parameter Sweep V1

## Purpose

`run_reload_reaction_scalp_parameter_sweep_v1.py` is a research-only parameter
sweep for one strategy candidate:

- `RELOAD_REACTION_SCALP_V1`

This tunes one candidate lane only.
It does not tune the whole bot.

It exists to test whether reload-after-spike / reaction-zone logic behaves more
like a short reaction scalp than a long hold.

## Why This Exists

The motivating chart review case was a `LINK` `RELOAD_REVIEW`
`APLUS_CONTEXT` event.

Observed visual pattern:

- the zone looked plausible
- the trigger looked too late
- `MFE` was positive
- `24h` return was weak or flat

That suggests a hypothesis:

- some reload review events may work as reaction scalps
- the same events may not work well as passive 24h holds

This runner tests that hypothesis repeatedly across a parameter grid.

Current first-read finding:

- Reload Reaction Scalp currently looks more like a `15m/30m` reaction lane
  than a `24h` hold lane
- the top raw edge candidate is `LINK`-heavy
- a broader `entry_low` variant with lower symbol concentration currently looks
  like the better initial research candidate
- this remains a research proxy result, not real fills

Additional visual finding:

- XRP-like weak examples suggest close-only reference checks can be too late or
  wrong for reload scalps
- reload touch should prefer wick / intrabar zone interaction when public event
  candle OHLC is available
- close is better treated as confirmation than as the only reload touch signal
- NEAR / XRP-style invalidation-triggered examples are not valid reload scalp
  samples and must be excluded from `RELOAD_REACTION_SCALP_V1` by default
- target zones inside the entry zone are invalid for this lane and must be
  rejected by default

## Current Verdict

Current status:

- `RESEARCH_ONLY`
- `NOT_PROMOTABLE`

Current reason:

- clean default `wick_touch` mode has no robust candidate
- `close_reference` fallback is intentionally blocked in default mode
- invalidation-near contamination is excluded by default
- target-integrity gates are active by default

Current default outcome with `--min-samples 20`:

- `NO_VALID_WICK_TOUCH_CANDIDATE`
- `NO_ROBUST_CANDIDATE`

Interpretation:

- `RELOAD_REACTION_SCALP_V1` is still a research lane only
- it must not be promoted into runtime, paper execution, or live execution
- it must not be treated as a validated strategy candidate yet

## Diagnostic Finding

Lower-threshold diagnostic runs can still be useful as case-study evidence.

Current diagnostic finding with lower sample threshold:

- `local_reaction|15m|wick_touch_entry_low|entry_low|1.5|0.25|false`
- `sample_count=9`
- `excess_return_vs_hold_pct` about `+2.95%`
- `avg_mae_pct` about `-0.73%`
- `top_symbol_concentration_pct` about `66.67%`
- dominant symbol concentration is `LINK`

Interpretation:

- this looks like a promising `wick_touch_entry_low` micro-pattern
- but it is not robust enough for promotion
- sample count is too low
- symbol concentration is too high
- treat it as a `LINK`-heavy watch-pattern / case study only
- do not promote

## Next Research Steps

- expand the lifecycle event window and accumulate more clean history
- keep the same invalidation, trigger-family, and target-integrity gates
- keep event dedup / cooldown behavior active when comparing repeated rows
- generate separate `LINK`-heavy case-study chart packs for manual review
- compare `local_reaction` target behavior against fib targets only after a
  larger clean wick-touch sample exists

## Architecture Boundary

- no `selection_engine` change
- no `decision_gate` change
- no `execution_planner` change
- no `executor` change
- no paper trading
- no live trading
- strategy remains research-only

## Trigger Family Default

Default CLI:

- `--trigger-family wick_touch`

Allowed families:

- `wick_touch`
- `close_reference`
- `all`

Behavior:

- `wick_touch` allows only:
  - `wick_touch_zone`
  - `wick_touch_entry_low`
  - `close_confirm_after_touch`
- `close_reference` allows only:
  - `current_price_near_zone`
  - `current_price_inside_zone`
  - `current_price_above_entry_high_max_late`
- `all` allows both families and must be treated as mixed-mode diagnostics

Hard rule:

- when `--trigger-family wick_touch`, a close/reference candidate must not be
  promoted as `ROBUST`
- if no wick-touch candidate clears the robust gates, the runner reports:
  - `NO_VALID_WICK_TOUCH_CANDIDATE`
- it must not silently fall back to close/reference as the robust default

## Inputs

Primary input:

- `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`

Optional secondary input:

- `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`

Current safety guard:

- latest symbol-level fibo map rows are not point-in-time safe for historical
  lifecycle events
- therefore fib target modes are guarded and skipped unless a safe historical
  fib source exists

The runner does not create fills and does not claim real execution PnL.

Lifecycle rows may also carry canonical regime enrichment from:

- `docs/research/canonical_regime_context_source_v1.md`
- `active_regime_observation`

This runner reuses those existing regime fields when present.
It does not define a new regime model.

## Scope

This lane is:

- research-only
- account-aware read-only only because lifecycle outcome rows come from the
  lifecycle validation lane
- non-executable

Forbidden:

- orders
- paper fills
- executor
- `decision_gate`
- `execution_planner`
- `selection_engine` changes

## Base Event Filter

Base event universe:

- `position_lifecycle_action == RELOAD_REVIEW`
- `current_price` present
- `entry_zone_low` and `entry_zone_high` present
- prefer `leg_direction == UP`
- skip stale or missing critical inputs as needed
- exclude invalidation-near events by default

Default invalidation exclusion:

- `reason_bucket == INVALIDATION_NEAR`
- or `position_lifecycle_reason` contains `INVALIDATION`
- or `secondary_reason_buckets` contains `INVALIDATION_NEAR`
- or `current_price` is within the default invalidation-near distance threshold
  of `invalidation_price`

Optional contaminated comparison mode:

- `--include-invalidation-near`

This is diagnostic only. It allows comparison against the contaminated sample
set and should not be treated as the default strategy lane.

CLI filters:

- `--action RELOAD_REVIEW`
- `--primary-bucket APLUS_CONTEXT` or `ALL`
- `--symbols BTC,ETH,...`

## Parameter Grid

Swept families:

1. `reload_zone_part`
- `entry_low`
- `entry_mid`
- `entry_high`

2. `near_zone_threshold_pct`
- `0.5`
- `1.0`
- `1.5`
- `2.0`
- `3.0`

3. `trigger_basis`
- `current_price_near_zone`
- `current_price_inside_zone`
- `wick_touch_zone`
- `wick_touch_entry_low`
- `close_confirm_after_touch`
- `current_price_above_entry_high_max_late`

4. `max_late_distance_above_zone_pct`
- `0.25`
- `0.5`
- `1.0`

5. `target_mode`
- `local_reaction`
- `fib_1272_if_available`
- `fib_1618_if_available`

6. `max_hold_horizon`
- `15m`
- `30m`
- `1h`
- `2h`
- `4h`
- `24h`

7. `require_aplus_context`
- `false`
- `true`

Additional gating controls:

- `--min-target-distance-pct 0.5`
- `--allow-target-inside-entry-zone` default false

## Return Model

This runner uses:

- `POLICY_PROXY_RETURN`

It is not real PnL.

Current proxy rule:

- if the candidate target return is less than or equal to event `MFE`, the
  sweep assumes the target could have been hit within the chosen horizon
- otherwise it falls back to the same-horizon close return already stored in the
  lifecycle outcome row

This is intentionally labeled:

- `POLICY_PROXY_RETURN`

because it is not a fill engine, not a live strategy result, and not a paper
execution result.

For `close_confirm_after_touch`, the runner also labels the trigger as:

- `POLICY_PROXY_CONFIRMATION`

because true intrabar sequencing is still approximated from public event-candle
OHLC rather than a fill model.

## Metrics

Per parameter set:

- `parameter_key`
- `sample_count`
- `events_considered`
- `events_selected`
- `events_rejected_by_zone_part`
- `events_rejected_by_threshold`
- `events_rejected_by_aplus`
- `events_rejected_by_missing_zone`
- `events_rejected_by_missing_return`
- `events_rejected_by_missing_intrabar_touch_input`
- `events_rejected_by_invalidation_near`
- `events_rejected_by_target_inside_entry_zone`
- `events_rejected_by_target_too_close`
- `max_late_filter_effect_count`
- `events_selected_by_wick_touch`
- `events_selected_by_close_only`
- `close_only_late_trigger_count`
- `selected_events_with_invalidation_near`
- `selected_events_with_wrong_trigger_family`
- `selected_events_with_target_inside_entry_zone`
- `invalidation_near_ratio_pct`
- `invalidation_distance_pct`
- `invalidation_filter_reason`
- `avg_distance_from_entry_low_pct`
- `avg_distance_from_entry_high_pct`
- `target_distance_pct`
- `target_integrity_status`
- `target_integrity_reason`
- `target_inside_entry_zone_flag`
- `avg_strategy_return_pct`
- `median_strategy_return_pct`
- `avg_hold_return_pct`
- `median_hold_return_pct`
- `excess_return_vs_hold_pct`
- `winrate_pct`
- `avg_mfe_pct`
- `avg_mae_pct`
- `avg_opportunity_missed_pct`
- `max_drawdown_proxy_pct`
- `avg_drawdown_improvement_vs_hold_pct`
- `symbol_count`
- `top_symbol_concentration_pct`
- `robust_candidate_rank`
- `trigger_family`
- `trigger_family_candidate_count`
- `no_valid_trigger_family_candidate`
- `close_reference_fallback_blocked`

Robust candidate gates:

- `sample_count >= min_samples`
- `excess_return_vs_hold_pct > 0`
- `top_symbol_concentration_pct <= 30`
- `overfit_risk_flag == false`
- `selected_events_with_invalidation_near == 0`
- `selected_events_with_wrong_trigger_family == 0`
- `selected_events_with_target_inside_entry_zone == 0`
- `target_integrity_status in {OK, PASS}`

If no candidate clears these gates:

- report `NO_ROBUST_CANDIDATE`
- keep diagnostics and rejected variants
- do not export any `ROBUST` selected-event rows

## HOLD Baseline Rule

Every strategy candidate must be compared against:

- `HOLD` / buy-and-hold baseline

Required interpretation:

- report excess return versus `HOLD`
- report drawdown improvement versus `HOLD`
- profit alone is not sufficient

If a scalp variant is profitable in isolation but does not improve on the
matching hold baseline, it is not enough.

## Overfit And Concentration Guards

Default guard:

- `--min-samples 20`

Additional warnings:

- report symbol concentration
- flag overfit risk if one symbol is more than `30%` of the sample
- prefer transition-only lifecycle input rows when available/generated that way

Current interpretation:

- the best raw `15m` candidate can still be too concentrated to treat as the
  first promotion candidate
- lower concentration and less negative `MAE` may matter more than absolute raw
  excess return when selecting the next research variant

This runner does not assume broad validity from one symbol-dominated bucket.

## Current Fibo Guard

The optional Fibo target map file is useful for future ladder-aware variants,
but the currently available latest symbol-level file is not point-in-time safe
for historical lifecycle events.

Therefore:

- `fib_1272_if_available`
- `fib_1618_if_available`

are currently guarded and skipped unless a point-in-time-safe fib source is
available later.

This avoids using latest context as historical truth.

## Outputs

When `--write-files` is enabled:

- `reload_reaction_scalp_parameter_sweep_rows_v1.csv`
- `reload_reaction_scalp_parameter_sweep_rows_v1.jsonl`
- `reload_reaction_scalp_top_candidates_v1.csv`
- `reload_reaction_scalp_rejected_candidates_v1.csv`
- `reload_reaction_scalp_by_symbol_v1.csv`
- `reload_reaction_scalp_selected_events_v1.jsonl`
- `manifest_v1.json`

`reload_reaction_scalp_selected_events_v1.jsonl` is a visual chart-review
export, not a thin summary row dump.

It keeps chart-usable lifecycle fields such as:

- `symbol`
- `event_ts_utc`
- `position_lifecycle_action`
- `position_lifecycle_reason`
- `reason_bucket`
- `secondary_reason_buckets`
- `current_price`
- `entry_zone_low`
- `entry_zone_high`
- `tp_zone_low`
- `tp_zone_high`
- `invalidation_price`
- forward returns for `15m/30m/1h/2h/4h/24h`
- adjusted return scores for `15m/30m/1h/4h/24h`
- `max_favorable_excursion_pct`
- `max_adverse_excursion_pct`
- `source_modules`
- `missing_inputs`

It also adds candidate metadata for chart review:

- `selected_candidate_label`
- `parameter_key`
- `candidate_role`
- `robust_candidate_rank`
- `overfit_risk_flag`
- `sample_count`
- `symbol_count`
- `top_symbol_concentration_pct`

And trigger-review fields:

- `trigger_basis`
- `trigger_family`
- `trigger_family_status`
- `trigger_family_reason`
- `trigger_price_basis`
- `zone_touch_detected`
- `entry_low_touch_detected`
- `close_confirm_detected`
- `close_only_late_trigger`
- `distance_from_entry_low_pct`
- `distance_from_entry_high_pct`
- `invalidation_near_flag`
- `invalidation_distance_pct`
- `invalidation_filter_reason`
- `target_integrity_status`
- `target_integrity_reason`
- `target_distance_pct`
- `target_inside_entry_zone_flag`

And it preserves canonical regime review fields when available:

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
- `regime_state`
- `regime_freshness`
- `regime_lookup_status`
- canonical `global_regime`
- canonical `asset_class_regime`
- canonical `global_class_regime`

These are copied through from lifecycle outcome rows without reinterpretation.
If `active_regime_observation` has no usable point-in-time row, the export keeps
`UNKNOWN` or `SOURCE_MISSING` rather than inventing substitute regime labels.

Candidate roles are:

- `RAW_EDGE`
- `ROBUST`
- `LOW_MAE`
- `APLUS`
- `WICK_TOUCH` when the best wick/touch candidate differs from the robust
  close-based candidate

The export is capped by:

- `--selected-events-per-candidate 30`

and fails closed on chart-useless rows with missing `current_price`,
missing entry zone, or fully missing forward returns.

Default output root:

- `data/research/reload_reaction_scalp_parameter_sweep_v1`

## Terminal Summary

Summary output includes:

- report name/version
- events loaded
- events eligible
- parameter sets tested
- `best_raw_edge_candidate`
- `best_robust_candidate`
- `best_low_mae_candidate`
- `best_aplus_candidate`
- `best_wick_touch_candidate`
- `best_close_reference_candidate`
- requested `trigger_family`
- `NO_VALID_WICK_TOUCH_CANDIDATE` when wick-touch mode has no valid candidate
- `NO_ROBUST_CANDIDATE` when no variant clears the robust gates
- warning when top raw edge has `SYMBOL_CONCENTRATION_HIGH`
- invalidation exclusion counts and default-vs-contaminated mode
- `trigger_basis_summary` for close-vs-touch cohort comparison
- selected event export validation counts
- regime-split summaries for selected candidate roles when canonical regime
  fields are present
- top candidates by `excess_return_vs_hold_pct`
- top candidates by drawdown improvement
- rejected variants with negative excess return
- selected-variant parameter keys for event export
- safety markers

The terminal summary is deduplicated by full `parameter_key`, so variants that
only looked identical in the earlier abbreviated printout now stay explicit.

## Safety

This runner must remain:

- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `live_trading=false`
- `research_only=true`

It does not create order intents.

Future lane note:

- `INVALIDATION_BOUNCE_SCALP_V1` is a possible separate strategy later
- it is not implemented here
- invalidation-near events are excluded from `RELOAD_REACTION_SCALP_V1` by
  default to avoid cross-strategy contamination

## CLI

Compile:

```bash
python -m py_compile src/research/run_reload_reaction_scalp_parameter_sweep_v1.py
```

Help:

```bash
python -m src.research.run_reload_reaction_scalp_parameter_sweep_v1 --help
```

Smoke:

```bash
python -m src.research.run_reload_reaction_scalp_parameter_sweep_v1 \
  --max-events 5000 \
  --min-samples 20 \
  --output summary
```

Write-files smoke:

```bash
python -m src.research.run_reload_reaction_scalp_parameter_sweep_v1 \
  --max-events 5000 \
  --min-samples 20 \
  --write-files \
  --output summary
```
