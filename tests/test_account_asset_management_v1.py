from __future__ import annotations

import ast
from pathlib import Path

from src.reporting.account_asset_management_v1 import (
    UI_PREP_REASON,
    build_account_asset_management_payload,
    build_manual_add_catalog,
    build_open_orders_monitor_view,
    build_relevant_view,
)


def _venue_markets() -> list[dict]:
    return [
        {"market": "BTC-USDT", "quote_currency": "USDT", "is_tradeable": 1, "asset_symbol": "BTC"},
        {"market": "FET-EUR", "quote_currency": "EUR", "is_tradeable": 1, "asset_symbol": "FET"},
        {"market": "WLD-EUR", "quote_currency": "EUR", "is_tradeable": 1, "asset_symbol": "WLD"},
        {"market": "XRP-EUR", "quote_currency": "EUR", "is_tradeable": 1, "asset_symbol": "XRP"},
    ]


def _account_assets() -> list[dict]:
    return [
        {
            "market": "WLD-EUR",
            "source": "WALLET_DISCOVERY",
            "is_visible": 1,
            "is_candidate_enabled": 0,
            "is_order_proposal_enabled": 0,
            "is_hidden": 0,
            "has_wallet_balance": True,
        },
        {
            "market": "XRP-EUR",
            "source": "MANUAL_ADD",
            "is_visible": 0,
            "is_candidate_enabled": 0,
            "is_order_proposal_enabled": 0,
            "is_hidden": 1,
            "has_wallet_balance": False,
        },
    ]


def test_non_eur_market_excluded_by_default_filter():
    rows = build_manual_add_catalog(
        profile="hugo",
        venue_market_rows=_venue_markets(),
        account_asset_rows=_account_assets(),
        open_order_count_by_market={},
        show_all=False,
    )
    markets = {row["market"] for row in rows}
    assert "BTC-USDT" not in markets


def test_active_account_coins_sorted_first():
    rows = build_manual_add_catalog(
        profile="hugo",
        venue_market_rows=_venue_markets(),
        account_asset_rows=_account_assets(),
        open_order_count_by_market={"WLD-EUR": 1},
        show_all=False,
    )
    assert rows[0]["market"] == "WLD-EUR"
    assert rows[0]["already_added"] is True


def test_hidden_excluded_from_relevant_but_present_in_all_settings():
    relevant = build_relevant_view(
        profile="hugo",
        account_asset_rows=_account_assets(),
        open_order_count_by_market={},
    )
    settings = build_manual_add_catalog(
        profile="hugo",
        venue_market_rows=_venue_markets(),
        account_asset_rows=_account_assets(),
        open_order_count_by_market={},
        show_all=True,
    )
    relevant_markets = {row["market"] for row in relevant}
    settings_markets = {row["market"] for row in settings}
    assert "XRP-EUR" not in relevant_markets
    assert "XRP-EUR" in settings_markets


def test_disabled_still_appears_in_open_orders_monitor_dataset_if_open_order_exists():
    rows = build_open_orders_monitor_view(
        profile="hugo",
        account_asset_rows=_account_assets(),
        open_order_count_by_market={"WLD-EUR": 2},
    )
    assert rows[0]["market"] == "WLD-EUR"
    assert rows[0]["open_order_count"] == 2
    assert rows[0]["is_candidate_enabled"] == 0


def test_ui_action_metadata_prepared_disabled_only():
    payload = build_account_asset_management_payload(
        profile="hugo",
        venue_market_rows=_venue_markets(),
        account_asset_rows=_account_assets(),
        open_order_count_by_market={"WLD-EUR": 1},
    )
    first_action = payload["manual_add_rows"][0]["actions"][0]
    assert first_action["enabled"] is False
    assert first_action["reason"] == UI_PREP_REASON


def test_no_broker_private_read_imports_in_dashboard_management_renderer():
    src = Path("src/reporting/account_asset_management_v1.py").read_text()
    assert "BitvavoClient" not in src
    assert "run_account_wallet_refresh_v1" not in src
    assert "dotenv_values" not in src


def test_source_checks_forbid_broker_writes_order_submission():
    src = Path("src/reporting/account_asset_management_v1.py").read_text()
    assert "place_order" not in src
    assert "cancel_order" not in src
    assert "order_submission=1" not in src


def test_no_decision_gate_execution_planner_executor_imports():
    src = Path("src/reporting/account_asset_management_v1.py").read_text()
    assert "import src.decision_gate" not in src
    assert "from src.decision_gate" not in src
    assert "import src.execution_planner" not in src
    assert "from src.execution_planner" not in src
    assert "import src.executor" not in src
    assert "from src.executor" not in src


def test_no_broker_ast_calls():
    src = Path("src/reporting/account_asset_management_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = {"place_order", "cancel_order", "create_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"Forbidden broker-like call .{node.attr}() found")


def main():
    test_non_eur_market_excluded_by_default_filter()
    test_active_account_coins_sorted_first()
    test_hidden_excluded_from_relevant_but_present_in_all_settings()
    test_disabled_still_appears_in_open_orders_monitor_dataset_if_open_order_exists()
    test_ui_action_metadata_prepared_disabled_only()
    test_no_broker_private_read_imports_in_dashboard_management_renderer()
    test_source_checks_forbid_broker_writes_order_submission()
    test_no_decision_gate_execution_planner_executor_imports()
    test_no_broker_ast_calls()
    print("ok")


if __name__ == "__main__":
    main()
