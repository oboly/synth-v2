from __future__ import annotations

from decimal import Decimal

import src.reporting.account_scoped_short_trader_dashboard_v1 as dashboard
from src.reporting.account_scoped_short_trader_dashboard_v1 import build_account_market_scope
from src.reporting.manual_short_trader_dashboard_v1 import BrokerBalanceRow


class _NoopConnection:
    def close(self) -> None:
        pass


def test_publication_cohort_emits_cohort_published_reason(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "get_connection", lambda: _NoopConnection())
    monkeypatch.setattr(
        dashboard,
        "_resolve_trading_account",
        lambda *args, **kwargs: {"trading_account_id": 7},
    )
    monkeypatch.setattr(dashboard, "_fetch_latest_balance_snapshot_ts", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "_fetch_latest_order_snapshot_ts", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "_fetch_latest_broker_order_snapshot_ts", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "_fetch_balance_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(dashboard, "_fetch_open_order_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(dashboard, "_fetch_account_asset_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dashboard,
        "_fetch_selected_asset_market_rows",
        lambda *args, **kwargs: [
            {
                "market": "XLM-EUR",
                "quote_currency": "EUR",
                "asset_is_publication_cohort": 1,
                "asset_is_core_sensor": 0,
            }
        ],
    )
    monkeypatch.setattr(dashboard, "fetch_latest_prices_by_symbol", lambda *args, **kwargs: {})

    context = dashboard.load_account_scoped_short_dashboard_context(
        profile="demo",
        account_code="bitvavo_demo",
    )

    assert context.market_inclusion_reasons_by_market == {
        "XLM-EUR": frozenset({"COHORT_PUBLISHED"})
    }


def test_market_scope_includes_asset_selected_market_without_account_overlay() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[],
        balances=[],
        orders=[],
        selected_asset_market_rows=[
            {
                "market": "XLM-EUR",
                "quote_currency": "EUR",
                "asset_symbol": "XLM",
                "asset_is_enabled": 1,
                "asset_is_tradeable": 1,
                "asset_is_publication_cohort": 1,
                "asset_is_core_sensor": 0,
            },
        ],
    )

    assert markets == ["XLM-EUR"]


def test_market_scope_excludes_unselected_asset_without_account_overlay() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[],
        balances=[],
        orders=[],
        selected_asset_market_rows=[],
    )

    assert markets == []


def test_market_scope_includes_candidate_enabled_account_overlay() -> None:
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
        selected_asset_market_rows=[],
    )

    assert markets == ["XLM-EUR"]


def test_market_scope_respects_hidden_account_overlay_for_passive_asset_selection() -> None:
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
        balances=[],
        orders=[],
        selected_asset_market_rows=[
            {
                "market": "XLM-EUR",
                "quote_currency": "EUR",
                "asset_symbol": "XLM",
                "asset_is_enabled": 1,
                "asset_is_tradeable": 1,
                "asset_is_publication_cohort": 1,
                "asset_is_core_sensor": 0,
            },
        ],
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
        selected_asset_market_rows=[],
    )

    assert markets == ["XLM-EUR"]
