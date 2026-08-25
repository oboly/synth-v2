from datetime import datetime, timedelta

import src.research.forecast_confluence_pit_replay_v1 as replay
from src.research.forecast_confluence_pit_replay_v1 import assess, fetch_rows, outcome, outcome_with_exclusion


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


def test_exact_horizon_endpoints_are_accepted() -> None:
    ts = datetime(2026, 8, 1)
    row = {"asof_ts_utc": ts, "reference_price": 100}
    assessment = {"direction": "LONG", "confidence": .7, "confidence_bucket": "HIGH", "signal_combination": "momentum"}
    candles = [{"close_ts_utc": ts + timedelta(hours=h), "close_price": 101, "high_price": 102, "low_price": 99} for h in (4, 24, 168)]
    for hours in (4, 24, 168):
        result, reason = outcome_with_exclusion(row, assessment, candles, timedelta(hours=hours))
        assert result is not None and reason is None


def test_missing_endpoint_rejects_later_candle_and_does_not_extend_mfe_mae() -> None:
    ts = datetime(2026, 8, 1)
    row = {"asof_ts_utc": ts, "reference_price": 100}
    assessment = {"direction": "LONG", "confidence": .7, "confidence_bucket": "HIGH", "signal_combination": "momentum"}
    missing = [{"close_ts_utc": ts + timedelta(hours=8), "close_price": 102, "high_price": 1000, "low_price": 1}]
    result, reason = outcome_with_exclusion(row, assessment, missing, timedelta(hours=4))
    assert result is None and reason == "missing_endpoint_candle"
    exact_then_later = [{"close_ts_utc": ts + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99}, *missing]
    bounded, reason = outcome_with_exclusion(row, assessment, exact_then_later, timedelta(hours=4))
    assert reason is None and bounded is not None and bounded["mfe_pct"] == 2 and bounded["mae_pct"] == 1


def test_neutral_exclusion_is_unchanged() -> None:
    ts = datetime(2026, 8, 1)
    row = {"asof_ts_utc": ts, "reference_price": 100}
    assessment = {"direction": "NEUTRAL", "confidence": .5, "confidence_bucket": "LOW", "signal_combination": "none"}
    result, reason = outcome_with_exclusion(row, assessment, [], timedelta(hours=4))
    assert result is None and reason == "neutral_direction"


def test_no_gap_replay_is_deterministic(monkeypatch) -> None:
    ts = datetime(2026, 8, 1)
    row = {"asof_ts_utc": ts, "reference_price": 100, "market": "AAA", "pressure_state": None, "sector_rotation_state": None, "rotation_pressure_asof_ts_utc": None, "sector_rotation_asof_ts_utc": None, "trend_score": .8, "setup_score": .8, "compass_score": .8, "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None, "sector_rotation_score": None}
    candles = {"AAA": [{"close_ts_utc": ts + timedelta(hours=h), "close_price": 101, "high_price": 102, "low_price": 99} for h in (4, 24, 168)]}
    monkeypatch.setattr(replay, "fetch_rows", lambda *_args, **_kwargs: [row])
    monkeypatch.setattr(replay, "fetch_candles", lambda *_args, **_kwargs: candles)
    first = replay.run(object(), start=ts, end=ts + timedelta(days=1), venue="bitvavo")
    second = replay.run(object(), start=ts, end=ts + timedelta(days=1), venue="bitvavo")
    assert first == second


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
