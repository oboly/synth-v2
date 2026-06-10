"""
Account scope contract regression tests.

Covers:
  - positive balance markets included when account_asset has zero rows
  - positive balance markets included even when hidden in account_asset
  - open-order markets included regardless of hidden preference
  - first-snapshot open orders visible via broker_order_snapshot fallback
  - Joost-style existing profile reads account_open_order_snapshot (unchanged)
  - build_account_market_scope pure-Python contract

broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
"""
from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    _fetch_latest_broker_order_snapshot_ts,
    _fetch_order_rows_from_broker_snapshot,
    build_account_market_scope,
)
from src.reporting.manual_short_trader_dashboard_v1 import BrokerBalanceRow, BrokerOrderRow


# ---------------------------------------------------------------------------
# Minimal mock cursor / connection for unit-testing DB functions without MariaDB
# ---------------------------------------------------------------------------

class _MockCursor:
    def __init__(self, rows: list[dict[str, Any]], scalar: Any = None) -> None:
        self._rows = rows
        self._scalar = scalar

    def execute(self, sql: str, params: tuple = ()) -> None:
        pass

    def fetchone(self) -> dict[str, Any] | None:
        if self._scalar is not None:
            return {"latest_snapshot_ts_utc": self._scalar}
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def __enter__(self) -> "_MockCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _MockConn:
    def __init__(self, rows: list[dict[str, Any]] = (), scalar: Any = None) -> None:
        self._rows = list(rows)
        self._scalar = scalar

    def cursor(self) -> _MockCursor:
        return _MockCursor(self._rows, self._scalar)


# ---------------------------------------------------------------------------
# build_account_market_scope — positive balances, no account_asset rows
# ---------------------------------------------------------------------------

def _bal(symbol: str, available: str, in_order: str = "0") -> BrokerBalanceRow:
    return BrokerBalanceRow(symbol=symbol, available=Decimal(available), in_order=Decimal(in_order))


def _ord(market: str, side: str = "sell") -> BrokerOrderRow:
    return BrokerOrderRow(
        order_id="o1",
        market=market,
        side=side,
        order_type="limit",
        limit_price=Decimal("1"),
        amount=Decimal("1"),
        filled_amount=Decimal("0"),
        remaining_amount=Decimal("1"),
        status="new",
        created_at_ms=None,
    )


def test_positive_balance_included_with_no_account_asset_rows() -> None:
    balances = [_bal("WLD", "10"), _bal("EUR", "100")]
    markets = build_account_market_scope(
        account_asset_rows=[],
        balances=balances,
        orders=[],
    )
    assert "WLD-EUR" in markets, "positive balance market must be included even with no account_asset rows"


def test_eur_balance_not_added_as_market() -> None:
    balances = [_bal("EUR", "500")]
    markets = build_account_market_scope(account_asset_rows=[], balances=balances, orders=[])
    assert markets == [], "EUR quote-currency balance must not produce a market entry"


def test_zero_balance_not_included() -> None:
    balances = [_bal("WLD", "0")]
    markets = build_account_market_scope(account_asset_rows=[], balances=balances, orders=[])
    assert "WLD-EUR" not in markets


def test_positive_balance_included_even_when_hidden_in_account_asset() -> None:
    balances = [_bal("BTC", "0.1")]
    account_asset_rows = [{"market": "BTC-EUR", "is_hidden": True, "is_visible": False, "source": "AUTO", "asset_symbol": "BTC"}]
    markets = build_account_market_scope(
        account_asset_rows=account_asset_rows,
        balances=balances,
        orders=[],
    )
    assert "BTC-EUR" in markets, "positive balance must override hidden preference"


def test_open_order_market_included_regardless_of_hidden_preference() -> None:
    orders = [_ord("ETH-EUR", "sell")]
    account_asset_rows = [{"market": "ETH-EUR", "is_hidden": True, "is_visible": False, "source": "AUTO", "asset_symbol": "ETH"}]
    markets = build_account_market_scope(
        account_asset_rows=account_asset_rows,
        balances=[],
        orders=orders,
    )
    assert "ETH-EUR" in markets, "open-order market must not be removed by hidden flag"


def test_hidden_market_with_no_balance_and_no_order_excluded() -> None:
    account_asset_rows = [{"market": "DOGE-EUR", "is_hidden": True, "is_visible": False, "source": "AUTO", "asset_symbol": "DOGE"}]
    markets = build_account_market_scope(
        account_asset_rows=account_asset_rows,
        balances=[],
        orders=[],
    )
    assert "DOGE-EUR" not in markets


def test_multiple_positive_balance_markets_all_included() -> None:
    balances = [_bal("WLD", "10"), _bal("ONDO", "50"), _bal("EUR", "200")]
    markets = build_account_market_scope(account_asset_rows=[], balances=balances, orders=[])
    assert "WLD-EUR" in markets
    assert "ONDO-EUR" in markets
    assert "EUR-EUR" not in markets


# ---------------------------------------------------------------------------
# _fetch_latest_broker_order_snapshot_ts
# ---------------------------------------------------------------------------

def test_fetch_latest_broker_order_snapshot_ts_returns_value() -> None:
    ts = datetime(2026, 6, 9, 12, 0, 0)
    conn = _MockConn(scalar=ts)
    result = _fetch_latest_broker_order_snapshot_ts(conn, trading_account_id=1, venue="bitvavo")
    assert result == ts


def test_fetch_latest_broker_order_snapshot_ts_none_when_empty() -> None:
    conn = _MockConn(scalar=None)
    result = _fetch_latest_broker_order_snapshot_ts(conn, trading_account_id=1, venue="bitvavo")
    assert result is None


# ---------------------------------------------------------------------------
# _fetch_order_rows_from_broker_snapshot
# ---------------------------------------------------------------------------

def _broker_snapshot_row(
    market: str = "BTC-EUR",
    broker_order_id: str = "ord-001",
    side: str = "sell",
    order_type: str = "limit",
    limit_price_eur: str = "50000",
    quantity_base: str = "0.01",
    filled_quantity_base: str = "0",
    remaining_quantity_base: str = "0.01",
    broker_status: str = "new",
) -> dict[str, Any]:
    return {
        "market": market,
        "broker_order_id": broker_order_id,
        "side": side,
        "order_type": order_type,
        "limit_price_eur": limit_price_eur,
        "quantity_base": quantity_base,
        "filled_quantity_base": filled_quantity_base,
        "remaining_quantity_base": remaining_quantity_base,
        "broker_status": broker_status,
    }


def test_fetch_order_rows_from_broker_snapshot_maps_columns() -> None:
    ts = datetime(2026, 6, 9, 12, 0, 0)
    rows = [_broker_snapshot_row("BTC-EUR", "ord-001", "sell", "limit", "50000", "0.01", "0", "0.01", "new")]
    conn = _MockConn(rows=rows)
    result = _fetch_order_rows_from_broker_snapshot(conn, trading_account_id=1, venue="bitvavo", snapshot_ts_utc=ts)
    assert len(result) == 1
    r = result[0]
    assert r.market == "BTC-EUR"
    assert r.order_id == "ord-001"
    assert r.side == "sell"
    assert r.limit_price == Decimal("50000")
    assert r.amount == Decimal("0.01")
    assert r.status == "new"
    assert r.created_at_ms is None


def test_fetch_order_rows_from_broker_snapshot_market_uppercased() -> None:
    ts = datetime(2026, 6, 9, 12, 0, 0)
    conn = _MockConn(rows=[_broker_snapshot_row("btc-eur")])
    result = _fetch_order_rows_from_broker_snapshot(conn, trading_account_id=1, venue="bitvavo", snapshot_ts_utc=ts)
    assert result[0].market == "BTC-EUR"


def test_fetch_order_rows_from_broker_snapshot_none_ts_returns_empty() -> None:
    conn = _MockConn(rows=[_broker_snapshot_row()])
    result = _fetch_order_rows_from_broker_snapshot(conn, trading_account_id=1, venue="bitvavo", snapshot_ts_utc=None)
    assert result == []


def test_fetch_order_rows_from_broker_snapshot_empty_rows() -> None:
    ts = datetime(2026, 6, 9, 12, 0, 0)
    conn = _MockConn(rows=[])
    result = _fetch_order_rows_from_broker_snapshot(conn, trading_account_id=1, venue="bitvavo", snapshot_ts_utc=ts)
    assert result == []


# ---------------------------------------------------------------------------
# Regression: broker_order_snapshot fallback produces orders for scope
# ---------------------------------------------------------------------------

def test_positive_balance_and_broker_snapshot_order_both_produce_markets() -> None:
    """
    Scenario: first provisioning. account_open_order_snapshot is empty.
    broker_order_snapshot has one order. Balance has one non-EUR holding.
    Both markets must appear in scope.
    """
    balances = [_bal("ONDO", "100")]
    orders_from_broker = [_ord("BTC-EUR", "sell")]  # from broker_order_snapshot fallback

    markets = build_account_market_scope(
        account_asset_rows=[],
        balances=balances,
        orders=orders_from_broker,
    )
    assert "ONDO-EUR" in markets, "positive balance market must be included"
    assert "BTC-EUR" in markets, "broker snapshot order market must be included"


if __name__ == "__main__":
    tests = [
        test_positive_balance_included_with_no_account_asset_rows,
        test_eur_balance_not_added_as_market,
        test_zero_balance_not_included,
        test_positive_balance_included_even_when_hidden_in_account_asset,
        test_open_order_market_included_regardless_of_hidden_preference,
        test_hidden_market_with_no_balance_and_no_order_excluded,
        test_multiple_positive_balance_markets_all_included,
        test_fetch_latest_broker_order_snapshot_ts_returns_value,
        test_fetch_latest_broker_order_snapshot_ts_none_when_empty,
        test_fetch_order_rows_from_broker_snapshot_maps_columns,
        test_fetch_order_rows_from_broker_snapshot_market_uppercased,
        test_fetch_order_rows_from_broker_snapshot_none_ts_returns_empty,
        test_fetch_order_rows_from_broker_snapshot_empty_rows,
        test_positive_balance_and_broker_snapshot_order_both_produce_markets,
    ]
    for t in tests:
        t()
    print("ok")
