# Fast Recompute Lifecycle Refresh v1

P0-a is `src/reporting/run_fast_recompute_lifecycle_v1.py`. It is a read-only, market-only worklist/reporting runner that identifies stale, finished, reclaimed, or invalidated advice maps.

P0-b is `src/advice/run_fast_recompute_lifecycle_refresh_v1.py`. It consumes the P0-a worklist and can refresh market-only zone context plus paper advice for eligible assets.

P0-c is `scripts/odroid/run_mvp_dashboard_render_once.sh`. It wires the P0-b consumer into the Odroid read-only cockpit lifecycle before dashboard render, so stale/reclaimed/target-hit maps can be refreshed between normal 4h baseline runs.

Cooldown/fairness v1 adds a same-advice-asof cooldown marker to refreshed `paper_advice_observation.source_ref_json`. A symbol successfully refreshed by this consumer is skipped on later cockpit renders while the latest paper-advice row still carries the same marker. The `--max-assets` throttle is then applied to the remaining eligible candidates, so the selected set advances instead of repeatedly refreshing the same top rows.

## Boundaries

- Market-only and account-agnostic.
- No broker calls, broker writes, order submission, live orders, decision gate changes, execution planner changes, or executor use.
- Does not query account tables such as `account_position_snapshot`, `trading_account_balance_snapshot`, or `broker_order_snapshot`.
- Dry-run is the default. DB writes require explicit `--write-db`.
- Runtime wiring uses `--write-db` only for market-only zone/advice refresh. It does not mutate account state, submit orders, reserve capital, or call broker APIs.

## Refresh Behavior

Default eligible scope:

- `ZONE_AND_ADVICE_RECOMPUTE`

Default skipped scope:

- `ADVICE_ONLY_REVIEW`
- active/fresh maps
- unknown-data rows

The consumer resolves `symbol -> asset_id`, recomputes zones for selected assets only, and refreshes paper advice only for those refreshed `asset_id` values.

Fairness behavior:

- `PAPER_ADVICE_REFRESHED`: zone and paper advice were refreshed for the selected asset.
- `SKIPPED_ALREADY_REFRESHED_THIS_ASOF`: the latest paper-advice row already records a successful fast recompute refresh for the same advice asof window.
- `SKIPPED_MAX_ASSETS_THROTTLE`: the row remains eligible but was behind the current `--max-assets` limit after cooldown filtering.
- `SKIPPED_SCOPE_NOT_ENABLED`: the row is outside the market-only zone/advice recompute scope, such as `WAIT_FOR_NEXT_CANDLE`, active/fresh maps, or unknown-data rows.

Post-refresh display state:

- `REFRESH_NEEDED`: no successful refresh or cooldown marker explains the current recompute trigger.
- `REFRESHED_THIS_RUN`: this consumer recomputed the zone/advice during the current run.
- `REFRESHED_RECENTLY`: same-candle refresh metadata exists and the row is no longer currently actionable.
- `COOLDOWN_MONITOR`: same-candle refresh metadata exists, but the market trigger still deserves watch status.
- `RECOMPUTED_BUT_STILL_TRIGGERING`: a recomputed row still shows a critical trigger, such as touched invalidation.
- `REFRESH_FAILED_OR_STALE`: refresh was attempted but did not produce a usable refreshed state.
- `NO_REFRESH_NEEDED`: active/current map does not need refresh.

The cooldown marker is metadata only. It is not a trading decision, not a veto, and not a selection-engine input. A normal later paper-advice refresh or a new structural cycle naturally replaces the latest paper-advice metadata and clears the same-asof cooldown.

Example dry-run:

```bash
python -m src.advice.run_fast_recompute_lifecycle_refresh_v1 \
  --venue bitvavo \
  --interval 4h \
  --quote EUR \
  --output table
```

Example write smoke:

```bash
python -m src.advice.run_fast_recompute_lifecycle_refresh_v1 \
  --venue bitvavo \
  --interval 4h \
  --quote EUR \
  --max-assets 8 \
  --write-db \
  --output table
```

## Odroid Runtime Wiring

`scripts/odroid/run_mvp_dashboard_render_once.sh` runs the refresh consumer after the market price snapshot refresh and before dashboard rendering:

```bash
python -m src.advice.run_fast_recompute_lifecycle_refresh_v1 \
  --venue "${VENUE}" \
  --interval "${SYNTH_FAST_RECOMPUTE_INTERVAL:-4h}" \
  --quote "${QUOTE}" \
  --max-assets "${SYNTH_FAST_RECOMPUTE_MAX_ASSETS:-8}" \
  --write-db \
  --output table
```

Runtime knobs:

- `SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED`, default `1`
- `SYNTH_FAST_RECOMPUTE_MAX_ASSETS`, default `8`
- `SYNTH_FAST_RECOMPUTE_INTERVAL`, default `4h`
- `SYNTH_FAST_RECOMPUTE_COOLDOWN_MINUTES`, default `15`
- `SYNTH_FAST_RECOMPUTE_ALLOW_INTRABAR_REPEAT`, default `1`
- `SYNTH_FAST_RECOMPUTE_MAX_PER_ASSET_PER_4H`, default `3`

When `SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED=0`, the runner skips the consumer and renders dashboards as before.

When enabled, the runner fails closed: if the market-only refresh consumer fails, the script exits non-zero before rendering dashboards. This prevents stale or ambiguous cockpit output after a failed refresh attempt.

Default runtime is still throttled: only up to eight eligible assets are refreshed per run unless `SYNTH_FAST_RECOMPUTE_MAX_ASSETS` is explicitly changed.

Manual Odroid verification command:

```bash
SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED=1 \
SYNTH_FAST_RECOMPUTE_MAX_ASSETS=8 \
SYNTH_FAST_RECOMPUTE_INTERVAL=4h \
scripts/odroid/run_mvp_dashboard_render_once.sh
```

Disable refresh wiring while preserving dashboard rendering:

```bash
SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED=0 \
scripts/odroid/run_mvp_dashboard_render_once.sh
```

## Per-Asset Zone Context Requirement

`run_paper_advice_policy_v1` supports repeated `--asset-id` for asset-scoped refresh. Its zone lookup uses the latest `execution_zone_context` per asset, not one global latest zone timestamp. This matters because a fast refresh updates only selected assets; non-refreshed assets must keep their own latest zone context instead of losing context when another asset receives a newer zone timestamp.

## Safety Markers

The consumer prints:

```text
broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0
```

The Odroid dashboard runner also prints these safety markers before invoking the consumer.
