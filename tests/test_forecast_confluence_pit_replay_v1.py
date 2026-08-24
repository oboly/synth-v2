from datetime import datetime, timedelta

from src.research.forecast_confluence_pit_replay_v1 import assess, fetch_rows, outcome


def test_enriched_assessment_changes_only_when_feature_is_present() -> None:
    row = {"trend_score": .7, "setup_score": .7, "compass_score": .7, "volume_score": .7, "distance_entry_to_target_pct": .7, "rotation_pressure_score": None, "sector_rotation_score": None}
    assert assess(row, enriched=False) == assess(row, enriched=True)


def test_outcome_uses_only_candles_after_forecast() -> None:
    ts = datetime(2026, 8, 1)
    row = {"asof_ts_utc": ts, "reference_price": 100}
    assessment = {"direction": "LONG", "confidence": .7, "confidence_bucket": "HIGH", "signal_combination": "momentum"}
    candles = [{"close_ts_utc": ts - timedelta(hours=4), "close_price": 200, "high_price": 200, "low_price": 200}, {"close_ts_utc": ts + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99}]
    result = outcome(row, assessment, candles, timedelta(hours=4))
    assert result is not None and result["return_pct"] == 1


def test_replay_join_is_point_in_time_and_bounded() -> None:
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def execute(self, sql, _): self.sql = sql
        def fetchall(self): return []
    class Conn:
        def __init__(self): self.cursor_value = Cursor()
        def cursor(self): return self.cursor_value
    conn = Conn()
    fetch_rows(conn, start=datetime(2026, 8, 1), end=datetime(2026, 8, 2), venue="bitvavo")
    sql = conn.cursor_value.sql
    assert "o.as_of_ts_utc <= m.asof_ts_utc" in sql
    assert "r.asof_ts_utc <= m.asof_ts_utc" in sql
    assert "INTERVAL 4 HOUR" in sql
