from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.research.cq_v1_temporal_population_v1 import (
    END_ASOF_UTC,
    GRID_HOURS,
    START_ASOF_UTC,
    evidence_key,
    fetch_sampling_grid,
    source_age_hours,
    summarize,
)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.cursor_obj = _Cursor(rows)

    def cursor(self):
        return self.cursor_obj


def test_sampling_grid_keeps_only_actual_exact_4h_snapshots():
    conn = _Conn(
        [
            {"as_of_ts_utc": datetime(2026, 7, 16, 20, 0)},
            {"as_of_ts_utc": datetime(2026, 7, 16, 21, 0)},
            {"as_of_ts_utc": datetime(2026, 7, 17, 0, 0)},
            {"as_of_ts_utc": datetime(2026, 7, 17, 4, 1)},
        ]
    )

    grid = fetch_sampling_grid(conn, venue="bitvavo")

    assert [value.hour for value in grid] == [20, 0]
    assert all(value.hour in GRID_HOURS for value in grid)
    assert conn.cursor_obj.executed is not None
    _, params = conn.cursor_obj.executed
    assert params == ("bitvavo", "1.0", START_ASOF_UTC, END_ASOF_UTC)


def test_evidence_key_is_order_independent_and_requires_all_six_fields():
    evidence = {
        "quality_ts_1d_utc": datetime(2026, 7, 16, 19, 0),
        "quality_ts_4h_utc": datetime(2026, 7, 16, 19, 1),
        "quality_ts_1h_utc": datetime(2026, 7, 16, 19, 2),
        "signal_ts_1d_utc": datetime(2026, 7, 16, 0, 0),
        "signal_ts_4h_utc": datetime(2026, 7, 16, 16, 0),
        "signal_ts_1h_utc": datetime(2026, 7, 16, 19, 0),
    }
    assert evidence_key(evidence) == evidence_key(dict(reversed(list(evidence.items()))))

    evidence.pop("signal_ts_1h_utc")
    with pytest.raises(ValueError, match="signal_ts_1h_utc"):
        evidence_key(evidence)


def test_source_age_rejects_future_evidence():
    asof = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
    assert source_age_hours(asof, datetime(2026, 7, 16, 16, 0)) == 4.0
    with pytest.raises(ValueError, match="future source timestamp"):
        source_age_hours(asof, datetime(2026, 7, 16, 21, 0))


def test_summary_preserves_missingness_and_candidate_support():
    grid = [
        datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc),
    ]
    rows = [
        {
            "candidate_asof_ts_utc": "2026-07-16T20:00:00Z",
            "cq_v0": 0.5,
            "mrp_available": True,
            "signal_ts_1d_utc_age_hours": 20.0,
            "signal_ts_1h_utc_age_hours": 1.0,
            "cq_v1_scores": [
                {"candidate_id": "cq_v1_mrp_balanced_v1", "state": "AVAILABLE"},
                {"candidate_id": "cq_v1_mrp_anchor_v1", "state": "AVAILABLE"},
            ],
        },
        {
            "candidate_asof_ts_utc": "2026-07-17T00:00:00Z",
            "cq_v0": None,
            "mrp_available": False,
            "signal_ts_1d_utc_age_hours": 24.0,
            "signal_ts_1h_utc_age_hours": 5.0,
            "cq_v1_scores": [
                {"candidate_id": "cq_v1_mrp_balanced_v1", "state": "INSUFFICIENT_DATA"},
                {"candidate_id": "cq_v1_mrp_anchor_v1", "state": "INSUFFICIENT_DATA"},
            ],
        },
    ]

    result = summarize(rows, grid=grid)

    assert result["candidate_asof_count"] == 2
    assert result["included_asof_count"] == 2
    assert result["observation_count"] == 2
    assert result["cq_v0_available_count"] == 1
    assert result["mrp_available_count"] == 1
    assert result["candidate_available_count"]["cq_v1_mrp_balanced_v1"] == 1
    assert result["max_signal_source_age_hours"]["signal_ts_1d_utc_age_hours"] == 24.0
    assert result["forward_outcome_reads"] == 0
