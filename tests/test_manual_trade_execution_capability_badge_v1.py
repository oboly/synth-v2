from __future__ import annotations

from decimal import Decimal

from src.reporting.manual_short_trader_profit_plan_v1 import (
    EXECUTION_MODE_AUTOMATED,
    EXECUTION_MODE_MANUAL,
    EXECUTION_MODE_MANUAL_RFQ,
    EXECUTION_MODE_NONE,
    apply_execution_capability_overlay,
    build_profit_plan_card,
    is_manual_trade_card,
    render_plan_card,
)


def _card(symbol: str = "BTC", market: str = "BTC-EUR"):
    return build_profit_plan_card(
        symbol=symbol,
        market=market,
        current_price=Decimal("50000"),
    )


def test_default_execution_mode_is_automated_and_not_manual_trade() -> None:
    card = _card()
    assert card.execution_mode == EXECUTION_MODE_AUTOMATED
    assert is_manual_trade_card(card) is False


def test_overlay_defaults_absent_symbols_to_automated() -> None:
    cards = apply_execution_capability_overlay([_card("BTC"), _card("ETH", "ETH-EUR")], execution_mode_by_symbol={})
    assert all(c.execution_mode == EXECUTION_MODE_AUTOMATED for c in cards)
    assert all(is_manual_trade_card(c) is False for c in cards)


def test_overlay_marks_manual_rfq_symbol_as_manual_trade() -> None:
    cards = apply_execution_capability_overlay(
        [_card("MDT", "MDT-EUR")],
        execution_mode_by_symbol={"MDT": EXECUTION_MODE_MANUAL_RFQ},
    )
    assert cards[0].execution_mode == EXECUTION_MODE_MANUAL_RFQ
    assert is_manual_trade_card(cards[0]) is True


def test_overlay_marks_generic_manual_symbol_as_manual_trade_without_symbol_branching() -> None:
    """Proves the contract is generic: an arbitrary non-crypto instrument
    symbol (e.g. a future bond/commodity/OTC placeholder) gets the same
    manual-trade treatment as a crypto RFQ instrument, via the same
    execution_mode contract -- no symbol-specific branch."""
    cards = apply_execution_capability_overlay(
        [_card("XAUOTC", "XAUOTC-EUR")],
        execution_mode_by_symbol={"XAUOTC": EXECUTION_MODE_MANUAL},
    )
    assert is_manual_trade_card(cards[0]) is True


def test_none_execution_mode_is_not_treated_as_manual_trade() -> None:
    cards = apply_execution_capability_overlay(
        [_card("XRP", "XRP-EUR")],
        execution_mode_by_symbol={"XRP": EXECUTION_MODE_NONE},
    )
    assert is_manual_trade_card(cards[0]) is False


def test_render_plan_card_shows_compact_badge_and_hides_raw_mode_from_compact_label() -> None:
    cards = apply_execution_capability_overlay(
        [_card("MDT", "MDT-EUR")],
        execution_mode_by_symbol={"MDT": EXECUTION_MODE_MANUAL_RFQ},
    )
    html = render_plan_card(cards[0], buy_orders=(), sell_orders=())
    assert "MANUAL TRADE" in html
    assert "data-manual-trade='true'" in html
    assert "data-execution-mode='MANUAL_RFQ'" in html
    # Low-level mode stays out of the compact badge label, in the hover title only.
    assert "manual-trade-badge' title='" in html
    badge_start = html.index("manual-trade-badge'")
    badge_snippet = html[badge_start : badge_start + 400]
    assert ">MANUAL TRADE<" in badge_snippet


def test_render_plan_card_automated_asset_has_no_manual_trade_badge() -> None:
    """Existing automatically executable assets must render unchanged."""
    card = _card("BTC", "BTC-EUR")
    html = render_plan_card(card, buy_orders=(), sell_orders=())
    assert "manual-trade-badge" not in html
    assert "data-manual-trade='false'" in html
    assert "data-execution-mode='AUTOMATED'" in html
