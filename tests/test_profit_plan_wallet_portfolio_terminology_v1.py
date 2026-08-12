from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from src.reporting.account_scoped_short_trader_dashboard_v1 import build_account_market_scope
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
from src.reporting.run_manual_short_trader_profit_plan_v1 import portfolio_member_markets_for_rendered_account


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
    zero-balance portfolio asset must retain PORTFOLIO but never claim
    WALLET."""
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
    assert ">PORTFOLIO ASSET</span>" in html
    assert "wallet-held-badge" not in html
    assert ">WALLET HELD</span>" not in html
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
    assert ">PORTFOLIO ASSET</span>" in html
    assert ">WALLET HELD</span>" in html
    assert "PORTFOLIO HOLDING" not in html


def test_wallet_discovered_positive_balance_without_portfolio_membership() -> None:
    """A wallet-discovered holding (e.g. LIGHTER-style) that is not in the
    configured strategic portfolio/rotation universe: WALLET only."""
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
    assert ">WALLET HELD</span>" in html
    assert "portfolio-asset-badge" not in html
    assert ">PORTFOLIO ASSET</span>" not in html
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
    assert "wallet-held-badge" not in html
    assert "portfolio-asset-badge" not in html
    assert ">WALLET HELD</span>" not in html
    assert ">PORTFOLIO ASSET</span>" not in html
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


def test_cohort_member_core_and_wallet_overlays_render_independently() -> None:
    """All cohort/member combinations remain distinct account/reporting facts."""
    member_only = _card("ONDO", "ONDO-EUR", CARD_MODE_ACCOUNT_PLAN_ENABLED)
    wallet_only = _card("LIGHTER", "LIGHTER-EUR", CARD_MODE_POSITION_HELD)
    both = _card("BTC", "BTC-EUR", CARD_MODE_POSITION_HELD)
    cohort_only = _card("XLM", "XLM-EUR", CARD_MODE_MARKET_SELECTED)
    neither = _card("ADA", "ADA-EUR", CARD_MODE_MARKET_SELECTED)

    cards = apply_portfolio_account_evidence(
        [member_only, wallet_only, both, cohort_only, neither],
        held_amount_by_symbol={"LIGHTER": Decimal("1"), "BTC": Decimal("0.1")},
        held_eur_value_by_symbol={"LIGHTER": Decimal("2"), "BTC": Decimal("5000")},
        cost_basis_by_symbol={},
        portfolio_asset_markets={"ONDO-EUR", "BTC-EUR"},
        market_selected_markets={"BTC-EUR", "XLM-EUR"},
        core_sensor_markets={"BTC-EUR"},
    )
    html = render_full_html(cards, broker_mode="db_snapshot")

    # member-only, including the required zero-balance independence.
    assert "PORTFOLIO ASSET" in render_plan_card(cards[0])
    assert "market-selected-badge" not in render_plan_card(cards[0])
    assert "WALLET HELD" not in render_plan_card(cards[0])
    # wallet-only
    assert "WALLET HELD" in render_plan_card(cards[1])
    assert "PORTFOLIO ASSET" not in render_plan_card(cards[1])
    # both
    assert "PORTFOLIO ASSET" in render_plan_card(cards[2])
    assert "market-selected-badge" in render_plan_card(cards[2])
    assert "core-sensor-badge" in render_plan_card(cards[2])
    # cohort-only
    assert "market-selected-badge" in render_plan_card(cards[3])
    assert "PORTFOLIO ASSET" not in render_plan_card(cards[3])
    # neither
    assert "PORTFOLIO ASSET" not in render_plan_card(cards[4])
    assert "market-selected-badge" not in render_plan_card(cards[4])

    assert "PORTFOLIO HOLDING" not in html


def test_account_membership_is_scoped_and_reporting_has_no_decision_or_execution_dependency() -> None:
    account_a_markets = portfolio_member_markets_for_rendered_account(
        account_asset_rows=(
            {"trading_account_id": 11, "market": "BTC-EUR", "is_portfolio_member": 1},
            {"trading_account_id": 22, "market": "ETH-EUR", "is_portfolio_member": 1},
        ),
        trading_account_id=11,
    )
    assert account_a_markets == {"BTC-EUR"}
    assert build_account_market_scope(
        account_asset_rows=[
            {
                "market": "BTC-EUR",
                "is_visible": False,
                "is_candidate_enabled": False,
                "is_order_proposal_enabled": False,
                "is_hidden": True,
                "is_portfolio_member": True,
                "source": "DISCOVERY",
            }
        ],
        balances=[],
        orders=[],
    ) == ["BTC-EUR"]

    account_source = Path("src/reporting/account_scoped_short_trader_dashboard_v1.py").read_text(encoding="utf-8")
    runner_source = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    assert "aa.is_portfolio_member" in account_source
    assert "WHERE aa.trading_account_id = %s" in account_source
    assert "portfolio_member_markets_for_rendered_account" in runner_source
    for forbidden in ("from src.decision_gate", "from src.execution_planner", "from src.executor"):
        assert forbidden not in runner_source


def test_source_file_uses_canonical_badge_text_without_retired_label() -> None:
    source = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    assert "PORTFOLIO HOLDING" not in source
    assert "portfolio-held-badge" not in source
    for badge in ("WALLET HELD", "PORTFOLIO ASSET", "MARKET SELECTED", "CORE SENSOR"):
        assert badge in source


def test_reporting_uses_cohort_published_without_legacy_cohort_reason() -> None:
    dashboard_source = Path("src/reporting/account_scoped_short_trader_dashboard_v1.py").read_text(encoding="utf-8")
    runner_source = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    reporting_source = f"{dashboard_source}\n{runner_source}"
    legacy_reason = "PORTFOLIO" + "_MARKER"

    assert "COHORT_PUBLISHED" in reporting_source
    assert legacy_reason not in reporting_source
