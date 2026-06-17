from __future__ import annotations

from decimal import Decimal

from src.reporting.account_scoped_short_trader_dashboard_v1 import build_account_market_scope
from src.reporting.manual_short_trader_dashboard_v1 import BrokerBalanceRow


def test_market_scope_includes_candidate_enabled_account_asset() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[
            {
                "market": "XLM-EUR",
                "quote_currency": "EUR",
                "asset_symbol": "XLM",
                "asset_is_enabled": 1,
                "source": "DISCOVERED",
                "is_visible": 0,
                "is_candidate_enabled": 1,
                "is_order_proposal_enabled": 0,
                "is_hidden": 0,
            },
        ],
        balances=[],
        orders=[],
    )

    assert markets == ["XLM-EUR"]


def test_market_scope_includes_order_proposal_enabled_account_asset() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[
            {
                "market": "XLM-EUR",
                "quote_currency": "EUR",
                "asset_symbol": "XLM",
                "asset_is_enabled": 1,
                "source": "DISCOVERED",
                "is_visible": 0,
                "is_candidate_enabled": 0,
                "is_order_proposal_enabled": 1,
                "is_hidden": 0,
            },
        ],
        balances=[],
        orders=[],
    )

    assert markets == ["XLM-EUR"]


def test_market_scope_excludes_unconfigured_account_asset_without_exposure() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[
            {
                "market": "XLM-EUR",
                "quote_currency": "EUR",
                "asset_symbol": "XLM",
                "asset_is_enabled": 1,
                "source": "DISCOVERED",
                "is_visible": 0,
                "is_candidate_enabled": 0,
                "is_order_proposal_enabled": 0,
                "is_hidden": 0,
            },
        ],
        balances=[],
        orders=[],
    )

    assert markets == []


def test_market_scope_keeps_hidden_market_with_positive_balance() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[
            {
                "market": "XLM-EUR",
                "quote_currency": "EUR",
                "asset_symbol": "XLM",
                "asset_is_enabled": 1,
                "source": "DISCOVERED",
                "is_visible": 0,
                "is_candidate_enabled": 0,
                "is_order_proposal_enabled": 0,
                "is_hidden": 1,
            },
        ],
        balances=[BrokerBalanceRow(symbol="XLM", available=Decimal("1"), in_order=Decimal("0"))],
        orders=[],
    )

    assert markets == ["XLM-EUR"]
