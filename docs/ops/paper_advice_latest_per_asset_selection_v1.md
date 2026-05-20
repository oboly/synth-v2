# Paper Advice Latest-Per-Asset Selection v1

The paper advice static dashboard selects the latest `paper_advice_observation` row per asset for the requested `venue` and `interval_code`.

This prevents a small fast-recompute batch from hiding older-but-current rows for assets that were not refreshed in that batch.

## Query Mode

Dashboard row mode:

```text
latest_per_asset
```

Selection uses `ROW_NUMBER()` partitioned by `asset_id`, ordered by:

1. `asof_ts_utc DESC`
2. `paper_advice_observation_id DESC`

This keeps duplicate same-asset/same-asof rows deterministic without requiring all assets to share one global timestamp.

## Counts And Timestamps

Advice-state counts are computed from the selected latest-per-asset rows.

The dashboard displays:

- latest overall advice asof
- row mode
- selected row asof range

## Boundary

This is reporting/dashboard only.

It does not:

- change paper advice generation
- change `selection_engine`
- change `decision_gate`
- change `execution_planner`
- change `executor`
- call broker APIs
- write broker orders
- submit orders
