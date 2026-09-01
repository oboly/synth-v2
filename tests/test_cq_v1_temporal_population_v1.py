from __future__ import annotations

from datetime import datetime, timezone

from src.research.cq_v1_temporal_population_v1 import (
    SECTOR_CONTEXT_STATE,
    sampling_grid,
    source_age_hours,
    summarize,
)
from src.research.cq_v1_temporal_sampling_v1 import load_contract

UTC = timezone.utc


def test_sampling_grid_is_exact_frozen_daily_contract() -> None:
    contract = load_contract()
    grid = sampling_grid(contract)
    assert len(grid) == 45
    assert grid[0] == datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
    assert grid[-1] == datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
    assert all((later - earlier).total_seconds() == 86400 for earlier, later in zip(grid, grid[1:]))


def test_sector_context_is_explicitly_unavailable_historical_membership() -> None:
    assert SECTOR_CONTEXT_STATE == "UNAVAILABLE_HISTORICAL_MEMBERSHIP"


def test_source_age_hours_preserves_stale_support() -> None:
    asof = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    stale = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    assert source_age_hours(asof, stale) == 36.0


def test_source_age_hours_rejects_future_source() -> None:
    asof = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    future = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    try:
        source_age_hours(asof, future)
    except ValueError as exc:
        assert "future source timestamp" in str(exc)
    else:
        raise AssertionError("future source must fail closed")


def test_summary_preserves_daily_split_and_mrp_age() -> None:
    grid = [
        datetime(2026, 7, 18, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 23, 0, 0, tzinfo=UTC),
    ]
    base = {
        "mrp_aggregate_state": "AVAILABLE",
        "mrp_asset_state": "AVAILABLE",
        "cq_v1_mrp_balanced_v1_state": "AVAILABLE",
        "cq_v1_mrp_anchor_v1_state": "AVAILABLE",
        "quality_ts_1d_utc_age_hours": 1.0,
        "quality_ts_4h_utc_age_hours": 2.0,
        "quality_ts_1h_utc_age_hours": 3.0,
        "signal_ts_1d_utc_age_hours": 4.0,
        "signal_ts_4h_utc_age_hours": 5.0,
        "signal_ts_1h_utc_age_hours": 6.0,
        "mrp_aggregate_age_hours": 1.0,
        "mrp_asset_age_hours": 36.0,
    }
    rows = [
        {**base, "asof_ts_utc": "2026-07-18T00:00:00Z", "chronological_split": "discovery"},
        {**base, "asof_ts_utc": "2026-08-14T00:00:00Z", "chronological_split": "validation"},
        {**base, "asof_ts_utc": "2026-08-23T00:00:00Z", "chronological_split": "holdout"},
    ]
    result = summarize(rows, grid=grid)
    assert result["observation_split_counts"] == {"discovery": 1, "validation": 1, "holdout": 1}
    assert result["max_source_age_hours"]["mrp_asset_age_hours"] == 36.0
    assert result["sector_context_state"] == "UNAVAILABLE_HISTORICAL_MEMBERSHIP"
    assert result["forward_outcome_reads"] == 0
