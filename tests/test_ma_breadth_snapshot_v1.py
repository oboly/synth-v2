from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pandas as pd
import pytest
from src.features.ma_breadth_snapshot_v1 import (
    MABreadthInputError,
    UniverseMember,
    build_snapshot,
    fetch_candles_at_or_before,
    fetch_universe_members,
    universe_identity,
)

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


def test_same_asset_two_markets_fail_closed_without_canonical_candle_market_identity():
    members = [UniverseMember(1, "AAA-EUR", "AAA"), UniverseMember(1, "AAA-USDC", "AAA")]
    eur = _candles(1, 50, 1, market="AAA-EUR")[:-1] + _candles(1, 1, 2, market="AAA-EUR")
    usdc = _candles(1, 50, 2, market="AAA-USDC")
    with pytest.raises(MABreadthInputError, match="ambiguous candle market identity"):
        build_snapshot(members=members, candles=_frame(eur, usdc), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")


def test_duplicate_exact_asof_constituent_rows_fail_closed():
    rows = _candles(1, 50, 1) + [_candles(1, 1, 1)[0]]
    with pytest.raises(MABreadthInputError, match="duplicate exact-asof candle rows"):
        build_snapshot(members=[MEMBERS[0]], candles=_frame(rows), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")


def test_reversed_source_order_has_same_unambiguous_result():
    rows = _candles(1, 50, 1)[:-1] + _candles(1, 1, 2) + _candles(2, 50, 2)
    forward = build_snapshot(members=MEMBERS, candles=_frame(rows), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    reverse = build_snapshot(members=MEMBERS, candles=_frame(list(reversed(rows))), asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")
    assert forward == reverse


class _FixtureCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, _params):
        self.connection.queries.append(sql)
        if "FROM venue_market vm" in sql:
            self.rows = [
                row for row in self.connection.venue_markets
                if sum(
                    candidate["venue"] == row["venue"]
                    and candidate["asset_id"] == row["asset_id"]
                    and candidate["is_tradeable"]
                    for candidate in self.connection.venue_markets
                ) == 1
            ]
        else:
            self.rows = [
                row for row in self.connection.candle_rows
                if row["asset_id"] in _params[3:]
            ]

    def fetchall(self):
        return self.rows


class _FixtureConnection:
    def __init__(self):
        self.queries = []
        self.venue_markets = [
            {"venue": "bitvavo", "asset_id": 1, "market": "AAA-EUR", "symbol": "AAA", "is_tradeable": True},
            {"venue": "bitvavo", "asset_id": 1, "market": "AAA-USDC", "symbol": "AAA", "is_tradeable": True},
            {"venue": "bitvavo", "asset_id": 2, "market": "BBB-EUR", "symbol": "BBB", "is_tradeable": True},
        ]
        self.candle_rows = _candles(1, 50, 2) + _candles(2, 50, 2)

    def cursor(self):
        return _FixtureCursor(self)


def test_multi_market_fixture_excludes_ambiguous_asset_and_never_attributes_its_one_series_twice(monkeypatch):
    conn = _FixtureConnection()
    monkeypatch.setattr(
        "src.features.ma_breadth_snapshot_v1.fetch_publication_cohort_contract",
        lambda _conn: type("Contract", (), {"predicate": lambda self, _alias: "1=1"})(),
    )

    assert len([row for row in conn.candle_rows if row["asset_id"] == 1]) == 50
    members = fetch_universe_members(conn, venue="bitvavo")
    candles = fetch_candles_at_or_before(conn, members=members, venue="bitvavo", asof_ts_utc=ASOF)
    result = build_snapshot(members=members, candles=candles, asof_ts_utc=ASOF, venue="bitvavo", interval_code="4h")

    universe_sql, candle_sql = conn.queries
    assert "SELECT COUNT(*)" in universe_sql
    assert "candidate_vm.base_asset_id = vm.base_asset_id" in universe_sql
    assert "JOIN venue_market" not in candle_sql
    assert members == [UniverseMember(2, "BBB-EUR", "BBB")]
    assert set(candles["market"]) == {"BBB-EUR"}
    assert (result.eligible_count, result.evaluated_count, result.coverage_pct) == (1, 1, Decimal("100"))
