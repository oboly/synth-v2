from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pandas as pd
import pytest
from src.features.ma_breadth_snapshot_v1 import MABreadthInputError, UniverseMember, build_snapshot, universe_identity

ASOF = datetime(2026, 9, 1, tzinfo=UTC)
MEMBERS = [UniverseMember(1, "BTC-EUR", "BTC"), UniverseMember(2, "ETH-EUR", "ETH")]

def _candles(asset_id: int, count: int, close: float, *, at_asof: bool = True) -> list[dict]:
    end = ASOF if at_asof else ASOF - timedelta(hours=4)
    return [{"asset_id": asset_id, "market": "BTC-EUR" if asset_id == 1 else "ETH-EUR", "interval_code": "4h", "close_ts_utc": end - timedelta(hours=4 * (count - i - 1)), "open_price": close, "high_price": close, "low_price": close, "close_price": close, "volume_base": 1} for i in range(count)]

def _frame(*rows): return pd.DataFrame([item for group in rows for item in group])

def test_all_evaluable_uses_shared_sma50_and_evaluated_denominator():
    first = _candles(1, 50, 1)[:-1] + _candles(1, 1, 2)
    second = _candles(2, 50, 2)
    result = build_snapshot(members=MEMBERS, candles=_frame(first, second), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    assert result.eligible_count == result.evaluated_count == 2
    assert result.universe_above_sma50_count == 1
    assert result.universe_above_sma50_pct == Decimal("50")
    assert result.coverage_pct == Decimal("100")

def test_insufficient_history_is_not_below_and_zero_evaluable_fails_closed():
    result = build_snapshot(members=MEMBERS, candles=_frame(_candles(1, 49, 2), _candles(2, 49, 1)), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    assert result.data_status == "INSUFFICIENT_DATA"
    assert result.evaluated_count == result.universe_above_sma50_count == 0
    assert result.insufficient_history_count == 2
    assert result.universe_above_sma50_pct is None

def test_partial_coverage_and_exact_asof_stale_semantics_are_deterministic():
    result = build_snapshot(members=MEMBERS, candles=_frame(_candles(1, 50, 1), _candles(2, 50, 1, at_asof=False)), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    assert (result.evaluated_count, result.stale_constituent_count, result.insufficient_history_count) == (1, 1, 0)
    assert result.coverage_pct == Decimal("50")
    assert result.universe_hash == universe_identity(reversed(MEMBERS))
    assert result.model_id == "ma_breadth_snapshot" and result.model_version == "1.0"

def test_wrong_interval_fails_closed():
    with pytest.raises(MABreadthInputError):
        build_snapshot(members=MEMBERS, candles=_frame(_candles(1, 50, 1)), asof_ts_utc=ASOF, venue="bitvavo", interval_code="1h")
