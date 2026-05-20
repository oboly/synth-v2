# Fast Recompute Lifecycle Refresh v1

P0-a is `src/reporting/run_fast_recompute_lifecycle_v1.py`. It is a read-only, market-only worklist/reporting runner that identifies stale, finished, reclaimed, or invalidated advice maps.

P0-b is `src/advice/run_fast_recompute_lifecycle_refresh_v1.py`. It consumes the P0-a worklist and can refresh market-only zone context plus paper advice for eligible assets.

## Boundaries

- Market-only and account-agnostic.
- No broker calls, broker writes, order submission, live orders, decision gate changes, execution planner changes, or executor use.
- Does not query account tables such as `account_position_snapshot`, `trading_account_balance_snapshot`, or `broker_order_snapshot`.
- Dry-run is the default. DB writes require explicit `--write-db`.

## Refresh Behavior

Default eligible scope:

- `ZONE_AND_ADVICE_RECOMPUTE`

Default skipped scope:

- `ADVICE_ONLY_REVIEW`
- active/fresh maps
- unknown-data rows

The consumer resolves `symbol -> asset_id`, recomputes zones for selected assets only, and refreshes paper advice only for those refreshed `asset_id` values.

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
  --max-assets 3 \
  --write-db \
  --output table
```

## Per-Asset Zone Context Requirement

`run_paper_advice_policy_v1` supports repeated `--asset-id` for asset-scoped refresh. Its zone lookup uses the latest `execution_zone_context` per asset, not one global latest zone timestamp. This matters because a fast refresh updates only selected assets; non-refreshed assets must keep their own latest zone context instead of losing context when another asset receives a newer zone timestamp.

## Safety Markers

The consumer prints:

```text
broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0
```
