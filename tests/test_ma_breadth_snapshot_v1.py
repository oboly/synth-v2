from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pandas as pd
import pytest
from src.features.ma_breadth_snapshot_v1 import MABreadthInputError, UniverseMember, build_snapshot, fetch_candles_at_or_before, universe_identity

ASOF = datetime(2026, 9, 1, tzinfo=UTC)
MEMBERS = [UniverseMember(1, "BTC-EUR", "BTC"), UniverseMember(2, "ETH-EUR", "ETH")]

def _candles(asset_id: int, count: int, close: float, *, market: str | None = None, at_asof: bool = True) -> list[dict]:
    end = ASOF if at_asof else ASOF - timedelta(hours=4)
    market = market or ("BTC-EUR" if asset_id == 1 else "ETH-EUR")
    return [{"venue": "bitvavo", "asset_id": asset_id, "market": market, "interval_code": "4h", "close_ts_utc": end - timedelta(hours=4 * (count - i - 1)), "open_price": close, "high_price": close, "low_price": close, "close_price": close, "volume_base": 1} for i in range(count)]

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


def test_same_asset_two_markets_keep_market_specific_sma50_truth():
    members = [UniverseMember(1, "AAA-EUR", "AAA"), UniverseMember(1, "AAA-USDC", "AAA")]
    eur = _candles(1, 50, 1, market="AAA-EUR")[:-1] + _candles(1, 1, 2, market="AAA-EUR")
    usdc = _candles(1, 50, 2, market="AAA-USDC")
    result = build_snapshot(members=members, candles=_frame(eur, usdc), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    assert (result.eligible_count, result.evaluated_count, result.universe_above_sma50_count) == (2, 2, 1)
    assert result.universe_above_sma50_pct == Decimal("50")


def test_missing_market_specific_rows_are_stale_and_not_reused():
    members = [UniverseMember(1, "AAA-EUR", "AAA"), UniverseMember(1, "AAA-USDC", "AAA")]
    result = build_snapshot(members=members, candles=_frame(_candles(1, 50, 1, market="AAA-EUR")), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    assert (result.eligible_count, result.evaluated_count, result.stale_constituent_count, result.insufficient_history_count) == (2, 1, 1, 0)
    assert result.coverage_pct == Decimal("50")


def test_duplicate_exact_asof_constituent_rows_fail_closed():
    rows = _candles(1, 50, 1) + [_candles(1, 1, 1)[0]]
    with pytest.raises(MABreadthInputError, match="duplicate exact-asof candle rows"):
        build_snapshot(members=[MEMBERS[0]], candles=_frame(rows), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")


def test_reversed_source_order_has_same_market_specific_result():
    members = [UniverseMember(1, "AAA-EUR", "AAA"), UniverseMember(1, "AAA-USDC", "AAA")]
    rows = _candles(1, 50, 1, market="AAA-EUR")[:-1] + _candles(1, 1, 2, market="AAA-EUR") + _candles(1, 50, 2, market="AAA-USDC")
    forward = build_snapshot(members=members, candles=_frame(rows), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    reverse = build_snapshot(members=members, candles=_frame(list(reversed(rows))), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    assert forward == reverse


class _FetchCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = ()

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FetchConn:
    def __init__(self, rows):
        self.cursor_instance = _FetchCursor(rows)

    def cursor(self):
        return self.cursor_instance


def test_fetch_candles_preserves_persisted_market_identity_for_same_asset():
    rows = [
        {"venue": "bitvavo", "asset_id": 1, "market": "AAA-EUR", "interval_code": "4h", "close_ts_utc": ASOF, "open_price": 1, "high_price": 1, "low_price": 1, "close_price": 1, "volume_base": 1},
        {"venue": "bitvavo", "asset_id": 1, "market": "AAA-USDC", "interval_code": "4h", "close_ts_utc": ASOF, "open_price": 2, "high_price": 2, "low_price": 2, "close_price": 2, "volume_base": 1},
    ]
    conn = _FetchConn(rows)
    result = fetch_candles_at_or_before(
        conn,
        members=[UniverseMember(1, "AAA-EUR", "AAA"), UniverseMember(1, "AAA-USDC", "AAA")],
        venue="bitvavo",
        asof_ts_utc=ASOF,
    )
    assert set(result["market"]) == {"AAA-EUR", "AAA-USDC"}
    assert "c.market" in conn.cursor_instance.sql
    assert "JOIN venue_market" not in conn.cursor_instance.sql
    assert conn.cursor_instance.params[-4:] == (1, "AAA-EUR", 1, "AAA-USDC")


def test_stale_and_insufficient_history_have_distinct_exact_asof_provenance():
    members = [
        UniverseMember(1, "AAA-EUR", "AAA"),
        UniverseMember(2, "BBB-EUR", "BBB"),
        UniverseMember(3, "CCC-EUR", "CCC"),
        UniverseMember(4, "DDD-EUR", "DDD"),
    ]
    above = _candles(1, 50, 1, market="AAA-EUR")[:-1] + _candles(1, 1, 2, market="AAA-EUR")
    below = _candles(2, 50, 2, market="BBB-EUR")
    stale = _candles(3, 50, 2, market="CCC-EUR", at_asof=False)
    insufficient = _candles(4, 49, 2, market="DDD-EUR")
    result = build_snapshot(
        members=members,
        candles=_frame(above, below, stale, insufficient),
        asof_ts_utc=ASOF,
        venue="bitvavo",
        interval_code="4h",
    )
    assert result.eligible_count == 4
    assert result.evaluated_count == 2
    assert result.stale_constituent_count == 1
    assert result.insufficient_history_count == 1
    assert result.universe_above_sma50_count == 1
    assert result.universe_above_sma50_pct == Decimal("50")
    assert result.coverage_pct == Decimal("50")
