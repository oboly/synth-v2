from decimal import Decimal

import src.research.run_entry_quality_shadow_bounded_v1 as runner


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)

    def cursor(self):
        return self.cursor_obj


def _candidate_row():
    return {
        "asset_id": 7,
        "symbol": "AAVE",
        "quality_status_1d": "TRUSTED",
        "quality_status_4h": "TRUSTED",
        "quality_status_1h": "TRUSTED",
        "trend_score_1d": Decimal("0.7"),
        "setup_score_1d": Decimal("0.6"),
        "signal_confidence_1d": Decimal("0.8"),
        "risk_score_1d": Decimal("0.1"),
        "volume_score_4h": Decimal("0.5"),
        "compass_score_4h": Decimal("0.6"),
        "setup_score_4h": Decimal("0.7"),
        "relative_score_4h": Decimal("0.4"),
        "signal_confidence_4h": Decimal("0.8"),
        "expansion_position_score_4h": Decimal("0.3"),
        "pullback_quality_score_4h": Decimal("0.9"),
        "risk_score_4h": Decimal("0.2"),
        "setup_score_1h": Decimal("0.5"),
        "signal_confidence_1h": Decimal("0.6"),
        "risk_score_1h": Decimal("0.1"),
        "latest_quality_asof_ts_utc": "2026-08-29 12:00:00",
        "advice_ts_1h_utc": "2026-08-29 12:05:00",
        "advice_ts_4h_utc": "2026-08-29 12:05:00",
    }


def test_bounded_candidate_query_limits_asset_population_before_history() -> None:
    conn = _Connection([_candidate_row()])
    result = runner.fetch_bounded_selection_candidates(
        conn, venue="bitvavo", asset_id=7, limit=1
    )

    sql = conn.cursor_obj.sql
    assert sql is not None
    assert "FROM (" in sql
    assert "ORDER BY asset_id\n        LIMIT %s\n    ) a" in sql
    assert sql.index("LIMIT %s") < sql.index("LEFT JOIN asset_interval_quality")
    assert "SELECT MAX(q.asof_ts_utc)" in sql
    assert "SELECT MAX(s.signal_ts_utc)" in sql
    assert result[0].asset_id == 7
    assert result[0].symbol == "AAVE"
    assert result[0].venue == "bitvavo"


def test_bounded_candidate_limit_is_fail_closed() -> None:
    conn = _Connection([])
    for bad_limit in (0, 1001):
        try:
            runner.fetch_bounded_selection_candidates(
                conn, venue="bitvavo", asset_id=None, limit=bad_limit
            )
        except ValueError as exc:
            assert "1..1000" in str(exc)
        else:
            raise AssertionError("invalid limit must fail")


def test_evidence_query_uses_scalar_latest_lookups_without_history_join_product() -> None:
    conn = _Connection(
        [
            {
                "asset_id": 7,
                "quality_ts_1d_utc": "2026-08-29 00:00:00",
                "quality_ts_4h_utc": "2026-08-29 08:00:00",
                "quality_ts_1h_utc": "2026-08-29 12:00:00",
                "signal_ts_1d_utc": "2026-08-29 00:05:00",
                "signal_ts_4h_utc": "2026-08-29 08:05:00",
                "signal_ts_1h_utc": "2026-08-29 12:05:00",
            }
        ]
    )
    result = runner.fetch_bounded_evidence_timestamps(
        conn, venue="bitvavo", asset_ids=[7]
    )

    sql = conn.cursor_obj.sql
    assert sql is not None
    assert "LEFT JOIN asset_interval_quality" not in sql
    assert "LEFT JOIN signal_engine_state" not in sql
    assert sql.count("SELECT CAST(MAX(") == 6
    assert result[7]["signal_ts_1h_utc"] == "2026-08-29 12:05:00"
