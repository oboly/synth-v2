from __future__ import annotations

from src.research.cq_v1_temporal_source_audit_v1 import (
    SOURCE_SPECS,
    bind_params,
    classify_history,
    overall_state,
    source_result,
)


def test_source_registry_contains_frozen_cq_dependencies() -> None:
    ids = {spec.source_id for spec in SOURCE_SPECS}
    assert {
        "asset_interval_quality",
        "signal_engine_state",
        "mrp_aggregate",
        "mrp_asset",
        "sector_rotation",
        "canonical_candles_15m",
    } <= ids


def test_bind_params_only_replaces_venue_marker() -> None:
    spec = next(item for item in SOURCE_SPECS if item.source_id == "mrp_aggregate")
    assert bind_params(spec, venue="bitvavo") == ("bitvavo", "1.0")


def test_mrp_asset_history_is_venue_scoped_through_snapshot_join() -> None:
    spec = next(item for item in SOURCE_SPECS if item.source_id == "mrp_asset")
    assert spec.history_from_sql is not None
    assert "market_rotation_pressure_snapshot_v1 s" in spec.history_from_sql
    assert "s.pressure_snapshot_id=o.pressure_snapshot_id" in spec.history_from_sql
    assert "s.venue=%s" in spec.where_sql
    assert bind_params(spec, venue="bitvavo") == ("bitvavo", "1.0", "1.0")


def test_history_requires_multiple_timestamps() -> None:
    assert classify_history(row_count=0, distinct_ts_count=0) == "UNAVAILABLE_NO_ROWS"
    assert classify_history(row_count=10, distinct_ts_count=1) == "BLOCKED_SINGLE_TIMESTAMP_ONLY"
    assert classify_history(row_count=10, distinct_ts_count=2) == "REPLAYABLE_HISTORY_PRESENT"


def test_source_result_preserves_index_evidence() -> None:
    spec = SOURCE_SPECS[0]
    result = source_result(
        spec,
        row_count=10,
        distinct_ts_count=3,
        first_ts="2026-08-01 00:00:00",
        last_ts="2026-08-03 00:00:00",
        indexes=[{"index_name": "ix_test", "column_name": "asof_ts_utc"}],
    )
    assert result["history_state"] == "REPLAYABLE_HISTORY_PRESENT"
    assert result["indexes"][0]["index_name"] == "ix_test"


def test_overall_state_fails_only_on_required_source_history() -> None:
    rows = [
        {"source_id": "required", "required_for_temporal_cq": True, "history_state": "REPLAYABLE_HISTORY_PRESENT"},
        {"source_id": "optional", "required_for_temporal_cq": False, "history_state": "UNAVAILABLE_NO_ROWS"},
    ]
    assert overall_state(rows) == ("READY_TO_FREEZE_TEMPORAL_SAMPLING", [])
    rows[0]["history_state"] = "BLOCKED_SINGLE_TIMESTAMP_ONLY"
    assert overall_state(rows) == ("BLOCKED_SOURCE_HISTORY", ["required"])
