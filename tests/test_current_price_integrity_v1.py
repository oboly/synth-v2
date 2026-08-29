from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot, fetch_latest_prices_by_symbol
from src.reporting.current_price_snapshot_v1 import classify_current_price_snapshot


NOW = datetime(2026, 8, 29, 17, 30, tzinfo=UTC)


def _snapshot(
    *,
    price: str = "106.50",
    market: str = "AAVE-EUR",
    source_ts_utc: datetime | None = None,
    observed_ts_utc: datetime | None = None,
) -> MarketPriceSnapshot:
    return MarketPriceSnapshot(
        venue="bitvavo",
        symbol="AAVE",
        market=market,
        quote_currency="EUR",
        price=Decimal(price),
        source_name="bitvavo_public_ticker_v1",
        source_ts_utc=source_ts_utc,
        observed_ts_utc=observed_ts_utc or NOW - timedelta(minutes=2),
    )


def test_fresh_coherent_snapshot_remains_safe() -> None:
    display = classify_current_price_snapshot(
        _snapshot(source_ts_utc=NOW - timedelta(minutes=2, seconds=5)),
        now_utc=NOW,
    )

    assert display.status == "FRESH_CURRENT_PRICE"
    assert display.safe_price == Decimal("106.50")


def test_fresh_observation_cannot_make_stale_provider_price_fresh() -> None:
    display = classify_current_price_snapshot(
        _snapshot(
            price="108.58",
            observed_ts_utc=NOW - timedelta(minutes=2),
            source_ts_utc=NOW - timedelta(minutes=40),
        ),
        now_utc=NOW,
    )

    assert display.status == "STALE_CURRENT_PRICE"
    assert display.safe_price is None
    assert display.age_min == Decimal("2")


def test_noncanonical_market_cannot_be_used_as_current_symbol_price() -> None:
    display = classify_current_price_snapshot(
        _snapshot(
            market="AAVE-USDC",
            source_ts_utc=NOW - timedelta(minutes=2),
        ),
        now_utc=NOW,
    )

    assert display.status == "STALE_CURRENT_PRICE"
    assert display.safe_price is None


def test_future_provider_timestamp_fails_closed() -> None:
    display = classify_current_price_snapshot(
        _snapshot(source_ts_utc=NOW + timedelta(minutes=1)),
        now_utc=NOW,
    )

    assert display.status == "STALE_CURRENT_PRICE"
    assert display.safe_price is None


def test_missing_provider_timestamp_preserves_observation_freshness_fallback() -> None:
    display = classify_current_price_snapshot(
        _snapshot(source_ts_utc=None),
        now_utc=NOW,
    )

    assert display.status == "FRESH_CURRENT_PRICE"
    assert display.safe_price == Decimal("106.50")


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.sql = ""
        self.params: dict[str, object] = {}

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.sql = sql
        self.params = params

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.cursor_instance = _Cursor(rows)

    def cursor(self) -> _Cursor:
        return self.cursor_instance


def test_latest_lookup_keeps_market_identity_and_skips_noncanonical_rows() -> None:
    observed = NOW.replace(tzinfo=None)
    rows = [
        {
            "venue": "bitvavo",
            "symbol": "AAVE",
            "market": "AAVE-USDC",
            "quote_currency": "EUR",
            "price": Decimal("108.58"),
            "source_name": "wrong_market",
            "source_ts_utc": observed,
            "observed_ts_utc": observed,
        },
        {
            "venue": "bitvavo",
            "symbol": "AAVE",
            "market": "AAVE-EUR",
            "quote_currency": "EUR",
            "price": Decimal("106.50"),
            "source_name": "canonical",
            "source_ts_utc": observed - timedelta(seconds=1),
            "observed_ts_utc": observed - timedelta(seconds=1),
        },
    ]
    conn = _Connection(rows)

    result = fetch_latest_prices_by_symbol(
        conn,
        venue="bitvavo",
        quote_currency="EUR",
        symbols=["AAVE"],
    )

    sql = conn.cursor_instance.sql
    assert "GROUP BY venue, symbol, market, quote_currency" in sql
    assert "AND lp.market = m.market" in sql
    assert "ORDER BY m.symbol, m.observed_ts_utc DESC, m.source_ts_utc DESC, m.source_name DESC, m.price DESC" in sql
    assert result["AAVE"].market == "AAVE-EUR"
    assert result["AAVE"].price == Decimal("106.50")


def test_latest_lookup_resolves_fully_tied_rows_by_price() -> None:
    observed = NOW.replace(tzinfo=None)
    rows = [
        {
            "venue": "bitvavo",
            "symbol": "AAVE",
            "market": "AAVE-EUR",
            "quote_currency": "EUR",
            "price": Decimal("106.50"),
            "source_name": "same_source",
            "source_ts_utc": observed,
            "observed_ts_utc": observed,
        },
        {
            "venue": "bitvavo",
            "symbol": "AAVE",
            "market": "AAVE-EUR",
            "quote_currency": "EUR",
            "price": Decimal("108.58"),
            "source_name": "same_source",
            "source_ts_utc": observed,
            "observed_ts_utc": observed,
        },
    ]
    conn = _Connection(rows)

    result = fetch_latest_prices_by_symbol(
        conn,
        venue="bitvavo",
        quote_currency="EUR",
        symbols=["AAVE"],
    )

    assert result["AAVE"].price == Decimal("108.58")
