from __future__ import annotations

from src.research.cq_v1_temporal_source_audit_v1 import (
    SOURCE_SPECS,
    bind_params,
    classify_history,
    overall_state,
    source_result,
)
from src.research.run_cq_v1_temporal_source_audit_v1 import (
    _capture_audit_window,
    _fetch_history_summary,
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


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        self.executions: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict:
        return self.rows.pop(0)


def test_audit_window_is_captured_once_and_bound_to_history_query() -> None:
    cursor = _FakeCursor(
        [
            {
                "audit_asof_ts_utc": "2026-08-31 05:20:00",
                "history_cutoff_ts_utc": "2026-07-17 05:20:00",
            },
            {
                "row_count": 10,
                "distinct_ts_count": 3,
                "first_ts": "2026-08-01 00:00:00",
                "last_ts": "2026-08-30 00:00:00",
            },
        ]
    )
    audit_asof, cutoff = _capture_audit_window(cursor, lookback_days=45)
    assert audit_asof == "2026-08-31 05:20:00"
    assert cutoff == "2026-07-17 05:20:00"

    summary = _fetch_history_summary(
        cursor,
        from_sql="asset_interval_quality",
        ts_col="asof_ts_utc",
        where_sql="venue=%s",
        params=("bitvavo",),
        history_cutoff_ts_utc=cutoff,
        audit_asof_ts_utc=audit_asof,
    )
    assert summary["row_count"] == 10

    capture_sql, capture_params = cursor.executions[0]
    assert "UTC_TIMESTAMP()" in capture_sql
    assert capture_params == (45,)

    history_sql, history_params = cursor.executions[1]
    assert "UTC_TIMESTAMP()" not in history_sql
    assert "asof_ts_utc >= %s" in history_sql
    assert "asof_ts_utc <= %s" in history_sql
    assert history_params == (
        "bitvavo",
        "2026-07-17 05:20:00",
        "2026-08-31 05:20:00",
    )
