from __future__ import annotations

from decimal import Decimal

import pytest

import src.reporting.run_manual_short_trader_profit_plan_v1 as profit_plan_runner
from src.reporting.manual_short_trader_profit_plan_v1 import (
    EXECUTION_MODE_AUTOMATED,
    EXECUTION_MODE_MANUAL,
    EXECUTION_MODE_MANUAL_RFQ,
    EXECUTION_MODE_NONE,
    apply_execution_capability_overlay,
    build_profit_plan_card,
    is_manual_trade_card,
)


def _card(symbol: str, market: str) -> "profit_plan_runner.ProfitPlanCard":
    return build_profit_plan_card(
        symbol=symbol,
        market=market,
        current_price=Decimal("100"),
    )


class _FakeConn:
    """Read-only fake connection proving close() always runs."""

    def __init__(self, rows_by_symbol: dict[str, str]):
        self.rows_by_symbol = rows_by_symbol
        self.closed = False

    def cursor(self):
        rows = [
            {"symbol": symbol, "execution_mode": mode}
            for symbol, mode in self.rows_by_symbol.items()
        ]
        return _FakeCursor(rows)

    def close(self) -> None:
        self.closed = True


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql

    def fetchall(self):
        return self.rows


def test_resolves_manual_rfq_and_manual_modes_and_activates_badge(monkeypatch) -> None:
    conn = _FakeConn({"MDT": "MANUAL_RFQ", "XAUOTC": "MANUAL", "BTC": "AUTOMATED"})
    monkeypatch.setattr(profit_plan_runner, "get_connection", lambda: conn)

    cards = [
        _card("MDT", "MDT-EUR"),
        _card("XAUOTC", "XAUOTC-EUR"),
        _card("BTC", "BTC-EUR"),
    ]
    execution_mode_by_symbol = profit_plan_runner.resolve_execution_mode_by_symbol_for_cards(cards)
    overlaid = apply_execution_capability_overlay(
        cards, execution_mode_by_symbol=execution_mode_by_symbol
    )

    by_symbol = {c.symbol: c for c in overlaid}
    assert by_symbol["MDT"].execution_mode == EXECUTION_MODE_MANUAL_RFQ
    assert is_manual_trade_card(by_symbol["MDT"]) is True
    assert by_symbol["XAUOTC"].execution_mode == EXECUTION_MODE_MANUAL
    assert is_manual_trade_card(by_symbol["XAUOTC"]) is True
    assert conn.closed is True


def test_automated_mode_rendering_unchanged(monkeypatch) -> None:
    conn = _FakeConn({"BTC": "AUTOMATED"})
    monkeypatch.setattr(profit_plan_runner, "get_connection", lambda: conn)

    cards = [_card("BTC", "BTC-EUR")]
    execution_mode_by_symbol = profit_plan_runner.resolve_execution_mode_by_symbol_for_cards(cards)
    overlaid = apply_execution_capability_overlay(
        cards, execution_mode_by_symbol=execution_mode_by_symbol
    )

    assert overlaid[0].execution_mode == EXECUTION_MODE_AUTOMATED
    assert is_manual_trade_card(overlaid[0]) is False


def test_none_mode_does_not_activate_manual_trade_badge(monkeypatch) -> None:
    conn = _FakeConn({"XRP": "NONE"})
    monkeypatch.setattr(profit_plan_runner, "get_connection", lambda: conn)

    cards = [_card("XRP", "XRP-EUR")]
    execution_mode_by_symbol = profit_plan_runner.resolve_execution_mode_by_symbol_for_cards(cards)
    overlaid = apply_execution_capability_overlay(
        cards, execution_mode_by_symbol=execution_mode_by_symbol
    )

    assert overlaid[0].execution_mode == EXECUTION_MODE_NONE
    assert is_manual_trade_card(overlaid[0]) is False


def test_db_read_failure_falls_back_to_empty_map_without_fabricating_mode(monkeypatch, capsys) -> None:
    def _raise_get_connection():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(profit_plan_runner, "get_connection", _raise_get_connection)

    cards = [_card("MDT", "MDT-EUR")]
    execution_mode_by_symbol = profit_plan_runner.resolve_execution_mode_by_symbol_for_cards(cards)
    assert execution_mode_by_symbol == {}

    overlaid = apply_execution_capability_overlay(
        cards, execution_mode_by_symbol=execution_mode_by_symbol
    )
    assert overlaid[0].execution_mode == EXECUTION_MODE_AUTOMATED
    assert is_manual_trade_card(overlaid[0]) is False

    captured = capsys.readouterr()
    assert "execution capability read failed" in captured.err


def test_connection_always_closed_even_when_adapter_read_raises(monkeypatch) -> None:
    class _RaisingConn(_FakeConn):
        def cursor(self):
            raise RuntimeError("query failed")

    conn = _RaisingConn({})
    monkeypatch.setattr(profit_plan_runner, "get_connection", lambda: conn)

    cards = [_card("BTC", "BTC-EUR")]
    execution_mode_by_symbol = profit_plan_runner.resolve_execution_mode_by_symbol_for_cards(cards)
    assert execution_mode_by_symbol == {}
    assert conn.closed is True


def test_no_symbol_specific_branch_in_wiring_hook_source() -> None:
    import inspect

    source = inspect.getsource(profit_plan_runner.resolve_execution_mode_by_symbol_for_cards)
    assert "MDT" not in source
    assert "card.symbol ==" not in source
    assert "if symbol" not in source
