# Recompute Post-Refresh State And Cadence Cleanup v1

Fast recompute lifecycle rows can still carry old trigger labels after a successful refresh or same-candle cooldown skip. This cleanup separates the old trigger from the current display/action state.

## State Model

`post_refresh_state` values:

- `REFRESH_NEEDED`: latest map/advice still needs recompute and there is no successful refresh or cooldown marker explaining it.
- `REFRESHED_THIS_RUN`: the refresh consumer recomputed the zone/advice in the current run.
- `REFRESHED_RECENTLY`: latest paper advice carries a fast recompute marker for the same advice asof and no current trigger requires attention.
- `COOLDOWN_MONITOR`: the row still has reclaim/target movement, but same-candle cooldown says do not recompute again yet.
- `RECOMPUTED_BUT_STILL_TRIGGERING`: latest recomputed map still shows a critical trigger such as touched invalidation.
- `REFRESH_FAILED_OR_STALE`: refresh was attempted but failed or did not produce a usable refreshed zone/advice state.
- `NO_REFRESH_NEEDED`: active/current map does not need refresh.

Dashboard `display_severity` maps these states to presentation:

- `DISPLAY_CONTEXT`: refreshed/current context.
- `DISPLAY_MUTED`: refreshed recently or not currently actionable.
- `DISPLAY_WATCH`: cooldown monitor state.
- `DISPLAY_CRITICAL`: still needs refresh, failed refresh, or true current invalidation.

## Old Trigger Versus Current State

`lifecycle_state` and `recompute_reason` remain the market trigger context. They can still contain labels such as `RECLAIM_NEAR` or `MAP_RECOMPUTE_NEEDED`.

`post_refresh_state` is the current operational display state. Refreshed or cooldown rows should not remain red solely because the old trigger text still contains `MAP_RECOMPUTE_NEEDED`.

## Cadence

The refresh consumer keeps the existing same-asof safety posture but now exposes cadence knobs:

- `SYNTH_FAST_RECOMPUTE_COOLDOWN_MINUTES`, default `15`
- `SYNTH_FAST_RECOMPUTE_ALLOW_INTRABAR_REPEAT`, default `1`
- `SYNTH_FAST_RECOMPUTE_MAX_PER_ASSET_PER_4H`, default `3`

During the cooldown window, a same-asof refreshed row is skipped and shown as `COOLDOWN_MONITOR` or `REFRESHED_RECENTLY`.

After cooldown, another same-asof refresh may be considered only when:

- intrabar/lifecycle reason changed, or
- current price moved materially versus the last refresh marker, or
- the previous refresh failed.

The existing `--max-assets` throttle and fairness behavior still apply.

## Marker Fields

The existing `paper_advice_observation.source_ref_json.fast_recompute_refresh` marker remains the persisted metadata carrier. New marker context can include:

- `refresh_count_for_asof`
- `current_price`
- `lifecycle`
- `reason`
- `old_next_zone_state`
- `refreshed_at_utc`

No new schema is required.

## Boundary

This is reporting/dashboard and market-only refresh orchestration.

It does not:

- call broker APIs
- write broker state
- submit orders
- create live orders
- change `decision_gate`
- change `execution_planner`
- activate `executor`
- change `selection_engine` behavior
