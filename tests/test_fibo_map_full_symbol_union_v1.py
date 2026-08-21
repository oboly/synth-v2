from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.reporting import run_breath_fibo_strategy_static_dashboard_v1 as dashboard


def _price(symbol: str) -> dashboard.PriceSnapshot:
    return dashboard.PriceSnapshot(
        symbol=symbol,
        current_price=Decimal("1.0"),
        latest_candle_ts_utc=datetime(2026, 8, 21, 0, 0, tzinfo=UTC),
        source="obs_market_candle",
    )


def test_build_rows_renders_full_deterministic_union_beyond_80_symbols() -> None:
    price_rows = {f"P{index:03d}": _price(f"P{index:03d}") for index in range(90)}
    fib_rows = {
        f"F{index:03d}": {"symbol": f"F{index:03d}", "current_leg": "RANGE"}
        for index in range(15)
    }
    fib_rows["XRP"] = {"symbol": "XRP", "current_leg": "RANGE"}

    rows = dashboard.build_rows(
        interval="4h",
        price_rows=price_rows,
        fib_rows=fib_rows,
        regime_by_class={},
    )

    assets = [row.asset for row in rows]
    expected = sorted(set(price_rows) | set(fib_rows))
    assert len(rows) == 106
    assert len(assets) == len(set(assets))
    assert set(assets) == set(expected)
    assert "XRP" in assets


def test_dashboard_cli_has_no_row_limit_option() -> None:
    args = dashboard.parse_args([])
    assert not hasattr(args, "limit")
    with pytest.raises(SystemExit):
        dashboard.parse_args(["--limit", "80"])


def test_row_build_and_price_fetch_apis_have_no_limit_parameter() -> None:
    assert "limit" not in inspect.signature(dashboard.build_rows).parameters
    assert "limit" not in inspect.signature(dashboard.fetch_latest_price_rows).parameters


def test_latest_price_query_has_no_arbitrary_row_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, tuple[object, ...]]] = []

    def fake_try_query(conn, sql: str, params: tuple[object, ...] = ()):
        captured.append((sql, params))
        return [
            {
                "symbol": "XRP",
                "close_price": Decimal("1.23"),
                "close_ts_utc": datetime(2026, 8, 21, 0, 0, tzinfo=UTC),
            }
        ]

    monkeypatch.setattr(dashboard, "try_query", fake_try_query)

    rows = dashboard.fetch_latest_price_rows(object(), venue="bitvavo", interval="4h")

    assert set(rows) == {"XRP"}
    assert captured
    sql, params = captured[0]
    assert "LIMIT" not in sql.upper()
    assert params == ("bitvavo", "4h", "bitvavo", "4h")
    assert "MAX(close_ts_utc)" in sql
    assert "GROUP BY asset_id" in sql
