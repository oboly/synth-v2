from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_MODE_ACCOUNT_PLAN_ENABLED,
    CARD_MODE_MARKET_SELECTED,
    CARD_MODE_POSITION_HELD,
    apply_portfolio_account_evidence,
    build_json_snapshot,
    build_profit_plan_card,
    render_full_html,
    render_plan_card,
)


def _card(symbol: str, market: str, presentation_mode: str):
    return build_profit_plan_card(
        symbol=symbol,
        market=market,
        current_price=Decimal("1"),
        short_context_input_status="MISSING_ZONE_CONTEXT",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        presentation_mode=presentation_mode,
    )


def test_portfolio_asset_with_zero_balance_keeps_asset_badge_without_wallet_badge() -> None:
    """Strategic portfolio membership is independent of current balance: a
    zero-balance portfolio asset must retain PORTFOLIO ASSET but never claim
    WALLET HELD."""
    card = _card("ONDO", "ONDO-EUR", CARD_MODE_ACCOUNT_PLAN_ENABLED)
    [composed] = apply_portfolio_account_evidence(
        [card],
        held_amount_by_symbol={},
        held_eur_value_by_symbol={},
        cost_basis_by_symbol={},
        portfolio_asset_markets={"ONDO-EUR"},
    )
    assert composed.is_portfolio_asset is True
    assert composed.is_wallet_held is False

    html = render_plan_card(composed)
    assert "PORTFOLIO ASSET" in html
    assert "WALLET HELD" not in html
    assert "PORTFOLIO HOLDING" not in html


def test_portfolio_asset_with_positive_balance_shows_both_badges() -> None:
    """Both facts may be true at once and both badges must render."""
    card = _card("BTC", "BTC-EUR", CARD_MODE_POSITION_HELD)
    [composed] = apply_portfolio_account_evidence(
        [card],
        held_amount_by_symbol={"BTC": Decimal("0.5")},
        held_eur_value_by_symbol={"BTC": Decimal("25000")},
        cost_basis_by_symbol={},
        portfolio_asset_markets={"BTC-EUR"},
    )
    assert composed.is_portfolio_asset is True
    assert composed.is_wallet_held is True

    html = render_plan_card(composed)
    assert "PORTFOLIO ASSET" in html
    assert "WALLET HELD" in html
    assert "PORTFOLIO HOLDING" not in html


def test_wallet_discovered_positive_balance_without_portfolio_membership() -> None:
    """A wallet-discovered holding (e.g. LIGHTER-style) that is not in the
    configured strategic portfolio/rotation universe: WALLET HELD only."""
    card = _card("LIGHTER", "LIGHTER-EUR", CARD_MODE_POSITION_HELD)
    [composed] = apply_portfolio_account_evidence(
        [card],
        held_amount_by_symbol={"LIGHTER": Decimal("12.5")},
        held_eur_value_by_symbol={"LIGHTER": Decimal("25")},
        cost_basis_by_symbol={},
        portfolio_asset_markets=set(),
    )
    assert composed.is_portfolio_asset is False
    assert composed.is_wallet_held is True

    html = render_plan_card(composed)
    assert "WALLET HELD" in html
    assert "PORTFOLIO ASSET" not in html
    assert "PORTFOLIO HOLDING" not in html


def test_non_portfolio_watchlist_asset_shows_neither_badge() -> None:
    card = _card("XLM", "XLM-EUR", CARD_MODE_MARKET_SELECTED)
    [composed] = apply_portfolio_account_evidence(
        [card],
        held_amount_by_symbol={},
        held_eur_value_by_symbol={},
        cost_basis_by_symbol={},
        portfolio_asset_markets=set(),
    )
    assert composed.is_portfolio_asset is False
    assert composed.is_wallet_held is False

    html = render_plan_card(composed)
    assert "WALLET HELD" not in html
    assert "PORTFOLIO ASSET" not in html
    assert "PORTFOLIO HOLDING" not in html


def test_json_snapshot_exposes_separate_booleans_and_deprecated_alias_only() -> None:
    portfolio_only = _card("ONDO", "ONDO-EUR", CARD_MODE_ACCOUNT_PLAN_ENABLED)
    wallet_only = _card("LIGHTER", "LIGHTER-EUR", CARD_MODE_POSITION_HELD)
    both = _card("BTC", "BTC-EUR", CARD_MODE_POSITION_HELD)
    neither = _card("XLM", "XLM-EUR", CARD_MODE_MARKET_SELECTED)

    cards = apply_portfolio_account_evidence(
        [portfolio_only, wallet_only, both, neither],
        held_amount_by_symbol={"LIGHTER": Decimal("1"), "BTC": Decimal("0.1")},
        held_eur_value_by_symbol={"LIGHTER": Decimal("2"), "BTC": Decimal("5000")},
        cost_basis_by_symbol={},
        portfolio_asset_markets={"ONDO-EUR", "BTC-EUR"},
    )
    snapshot = build_json_snapshot(cards, broker_mode="db_snapshot")
    by_symbol = {row["symbol"]: row for row in snapshot["symbols"]}

    assert by_symbol["ONDO"]["is_portfolio_asset"] is True
    assert by_symbol["ONDO"]["is_wallet_held"] is False

    assert by_symbol["LIGHTER"]["is_portfolio_asset"] is False
    assert by_symbol["LIGHTER"]["is_wallet_held"] is True

    assert by_symbol["BTC"]["is_portfolio_asset"] is True
    assert by_symbol["BTC"]["is_wallet_held"] is True

    assert by_symbol["XLM"]["is_portfolio_asset"] is False
    assert by_symbol["XLM"]["is_wallet_held"] is False

    # Deprecated compatibility alias only -- must equal is_wallet_held, never
    # be treated as the canonical semantic field.
    for row in by_symbol.values():
        assert row["is_portfolio_held"] == row["is_wallet_held"]

    assert snapshot["wallet_held_count"] == 2
    assert snapshot["portfolio_asset_count"] == 2
    assert snapshot["portfolio_held_count"] == snapshot["wallet_held_count"]


def test_no_remaining_operator_facing_portfolio_holding_or_ambiguous_held_label() -> None:
    """Full-page render must contain neither the retired 'PORTFOLIO HOLDING'
    label nor a bare, ambiguous 'HELD' tag (must always be 'WALLET HELD')."""
    portfolio_only = _card("ONDO", "ONDO-EUR", CARD_MODE_ACCOUNT_PLAN_ENABLED)
    wallet_only = _card("LIGHTER", "LIGHTER-EUR", CARD_MODE_POSITION_HELD)
    both = _card("BTC", "BTC-EUR", CARD_MODE_POSITION_HELD)
    neither = _card("XLM", "XLM-EUR", CARD_MODE_MARKET_SELECTED)

    cards = apply_portfolio_account_evidence(
        [portfolio_only, wallet_only, both, neither],
        held_amount_by_symbol={"LIGHTER": Decimal("1"), "BTC": Decimal("0.1")},
        held_eur_value_by_symbol={"LIGHTER": Decimal("2"), "BTC": Decimal("5000")},
        cost_basis_by_symbol={},
        portfolio_asset_markets={"ONDO-EUR", "BTC-EUR"},
    )
    html = render_full_html(cards, broker_mode="db_snapshot")

    assert "PORTFOLIO HOLDING" not in html
    # Every standalone occurrence of the word HELD (not part of a longer
    # identifier such as data-presentation-mode='POSITION_HELD') must be
    # part of the label "WALLET HELD".
    for match in re.finditer(r"\bHELD\b", html):
        start = max(0, match.start() - 7)
        assert html[start:match.end()].endswith("WALLET HELD"), html[start - 20:match.end() + 10]


def test_source_file_has_no_remaining_portfolio_holding_or_bare_held_css_js_text() -> None:
    """Static guard on the source itself: badge text, CSS class names, and
    left-rail JS tag text must use the corrected terminology."""
    source = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    assert "PORTFOLIO HOLDING" not in source
    assert "portfolio-held-badge" not in source
    assert ">HELD<" not in source
    assert "'HELD'" not in source
    assert '"HELD"' not in source
