from __future__ import annotations

import ast
import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import src.reporting.run_account_wallet_dashboard_v1 as wallet_runner
from src.reporting.account_wallet_dashboard_v1 import (
    AccountAssetSettingsSummary,
    _fetch_trading_account,
    build_wallet_dashboard_payload,
    classify_wallet_freshness,
    payload_to_json_dict,
    render_wallet_html,
    write_wallet_dashboard,
)
from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot


def _base_now() -> datetime:
    return datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)


def _settings() -> AccountAssetSettingsSummary:
    return AccountAssetSettingsSummary(
        visible=2,
        candidate_enabled=1,
        proposal_enabled=0,
        hidden=0,
        disabled=0,
    )


def _display_timezone() -> str:
    return "Europe/Amsterdam"


def _management_account_assets() -> list[dict]:
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


def _management_venue_markets() -> list[dict]:
    return [
        {"market": "BTC-USDT", "quote_currency": "USDT", "is_tradeable": 1, "asset_symbol": "BTC"},
        {"market": "FET-EUR", "quote_currency": "EUR", "is_tradeable": 1, "asset_symbol": "FET"},
        {"market": "WLD-EUR", "quote_currency": "EUR", "is_tradeable": 1, "asset_symbol": "WLD"},
        {"market": "XRP-EUR", "quote_currency": "EUR", "is_tradeable": 1, "asset_symbol": "XRP"},
    ]


def _price(symbol: str, price: str, observed_minutes_ago: int = 3) -> MarketPriceSnapshot:
    now = _base_now()
    observed = (now - timedelta(minutes=observed_minutes_ago)).replace(tzinfo=None)
    return MarketPriceSnapshot(
        venue="bitvavo",
        symbol=symbol,
        market=f"{symbol}-EUR",
        quote_currency="EUR",
        price=Decimal(price),
        source_name="market_price_snapshot_v1",
        source_ts_utc=observed,
        observed_ts_utc=observed,
    )


def test_stale_detection():
    now = _base_now()
    latest = (now - timedelta(minutes=40)).replace(tzinfo=None)
    assert classify_wallet_freshness(latest, now_utc=now, fresh_after=timedelta(minutes=15)) == "STALE"


def test_empty_wallet_render():
    now = _base_now()
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=1,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=None,
        latest_order_snapshot_ts_utc=None,
        balance_rows=[],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={},
        account_asset_rows=[],
        venue_market_rows=[],
        now_utc=now,
    )
    html = render_wallet_html(payload)
    assert payload.freshness == "NEVER_REFRESHED"
    assert "No wallet balances found" in html
    assert "Manual refresh requires authenticated account action." in html


def test_unknown_asset_render():
    now = _base_now()
    payload = build_wallet_dashboard_payload(
        profile="hugo",
        account_code="bitvavo_hugo_read",
        trading_account_id=2,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=now.replace(tzinfo=None),
        balance_rows=[
            {
                "currency_code": "XYZ",
                "available_amount": Decimal("1.25"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("1.25"),
            }
        ],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={},
        account_asset_rows=[],
        venue_market_rows=[],
        now_utc=now,
    )
    html = render_wallet_html(payload)
    payload_json = payload_to_json_dict(payload)
    assert payload.market_data_warning is not None
    assert "XYZ" in html
    assert payload_json["balances"][0]["price_status"] == "MISSING_CURRENT_PRICE"


def test_stale_price_fails_closed_for_estimated_value() -> None:
    now = _base_now()
    stale_price = MarketPriceSnapshot(
        venue="bitvavo",
        symbol="HOME",
        market="HOME-EUR",
        quote_currency="EUR",
        price=Decimal("1.30"),
        source_name="market_price_snapshot_v1",
        source_ts_utc=(now - timedelta(days=2)).replace(tzinfo=None),
        observed_ts_utc=(now - timedelta(days=2)).replace(tzinfo=None),
    )
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=1,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=None,
        balance_rows=[
            {
                "currency_code": "HOME",
                "available_amount": Decimal("100"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("100"),
            }
        ],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={"HOME": stale_price},
        account_asset_rows=[],
        venue_market_rows=[],
        now_utc=now,
    )
    html = render_wallet_html(payload)
    payload_json = payload_to_json_dict(payload)
    assert payload.balances[0].estimated_eur_value is None
    assert payload_json["balances"][0]["price_status"] == "STALE_CURRENT_PRICE"
    assert payload_json["balances"][0]["estimated_eur_value"] is None
    assert "STALE_CURRENT_PRICE" in html


def test_joost_hugo_isolation():
    now = _base_now()
    joost = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=11,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=None,
        balance_rows=[
            {
                "currency_code": "BTC",
                "available_amount": Decimal("0.10"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("0.10"),
            }
        ],
        open_order_count_rows=[{"market": "BTC-EUR", "order_count": 1}],
        account_asset_settings=_settings(),
        price_by_symbol={"BTC": _price("BTC", "100000")},
        account_asset_rows=[],
        venue_market_rows=[],
        now_utc=now,
    )
    hugo = build_wallet_dashboard_payload(
        profile="hugo",
        account_code="bitvavo_hugo_read",
        trading_account_id=22,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=None,
        balance_rows=[
            {
                "currency_code": "ETH",
                "available_amount": Decimal("2"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("2"),
            }
        ],
        open_order_count_rows=[{"market": "ETH-EUR", "order_count": 3}],
        account_asset_settings=_settings(),
        price_by_symbol={"ETH": _price("ETH", "2000")},
        account_asset_rows=[],
        venue_market_rows=[],
        now_utc=now,
    )
    joost_json = payload_to_json_dict(joost)
    hugo_json = payload_to_json_dict(hugo)
    assert joost_json["profile"] == "joost"
    assert hugo_json["profile"] == "hugo"
    assert joost_json["account_code"] != hugo_json["account_code"]
    assert joost_json["balances"][0]["asset"] == "BTC"
    assert hugo_json["balances"][0]["asset"] == "ETH"


def test_no_secrets_in_html_json():
    now = _base_now()
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=1,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=None,
        balance_rows=[
            {
                "currency_code": "EUR",
                "available_amount": Decimal("500"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("500"),
            }
        ],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={},
        account_asset_rows=[],
        venue_market_rows=[],
        now_utc=now,
    )
    html = render_wallet_html(payload)
    payload_json = json.dumps(payload_to_json_dict(payload), sort_keys=True)
    assert "BITVAVO_API_KEY" not in html
    assert "BITVAVO_API_SECRET" not in html
    assert "BITVAVO_API_KEY" not in payload_json
    assert "BITVAVO_API_SECRET" not in payload_json


def test_write_wallet_dashboard_outputs_accounts_profile_files():
    now = _base_now()
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=1,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=now.replace(tzinfo=None),
        balance_rows=[
            {
                "currency_code": "EUR",
                "available_amount": Decimal("10"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("10"),
            }
        ],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={},
        account_asset_rows=[],
        venue_market_rows=[],
        now_utc=now,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path, json_path = write_wallet_dashboard(payload, output_root=Path(tmpdir))
        assert html_path.name == "wallet.html"
        assert json_path.name == "wallet.json"
        assert html_path.parent.name == "joost"
        assert json_path.parent.name == "joost"
        assert html_path.parent.parent.name == "accounts"
        assert json_path.parent.parent.name == "accounts"
        assert "/accounts/joost/wallet.html" in html_path.as_posix()
        assert "/accounts/joost/wallet.json" in json_path.as_posix()
        assert html_path.exists()
        assert json_path.exists()


def test_wallet_json_contains_management_payload():
    now = _base_now()
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=1,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=now.replace(tzinfo=None),
        balance_rows=[
            {
                "currency_code": "WLD",
                "available_amount": Decimal("5"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("5"),
            }
        ],
        open_order_count_rows=[{"market": "WLD-EUR", "order_count": 2}],
        account_asset_settings=_settings(),
        price_by_symbol={"WLD": _price("WLD", "1.25")},
        account_asset_rows=_management_account_assets(),
        venue_market_rows=_management_venue_markets(),
        now_utc=now,
    )
    payload_json = payload_to_json_dict(payload)
    assert "management" in payload_json
    assert sorted(payload_json["management"].keys()) == [
        "actions",
        "addable_markets",
        "all_assets",
        "open_orders_monitor",
        "profile",
        "relevant_assets",
        "safety_markers",
    ]
    assert all(action.get("enabled") is False for action in payload_json["management"]["actions"])
    assert payload_json["dashboard_links"]["about"] == "/synth/about.html"
    assert payload_json["dashboard_links"]["wallet"] == "/synth/accounts/joost/wallet.html"
    assert payload_json["dashboard_links"]["profit_plan"] == "/synth/accounts/joost/profit-plan.html"
    assert payload_json["dashboard_links"]["open_orders_monitor"] == "/synth/accounts/joost/open-orders-monitor.html"


def test_wallet_html_includes_management_sections():
    now = _base_now()
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=1,
        venue="bitvavo",
        display_timezone=_display_timezone(),
        latest_balance_snapshot_ts_utc=now.replace(tzinfo=None),
        latest_order_snapshot_ts_utc=now.replace(tzinfo=None),
        balance_rows=[
            {
                "currency_code": "WLD",
                "available_amount": Decimal("5"),
                "reserved_amount": Decimal("0"),
                "total_amount": Decimal("5"),
            }
        ],
        open_order_count_rows=[{"market": "WLD-EUR", "order_count": 2}],
        account_asset_settings=_settings(),
        price_by_symbol={"WLD": _price("WLD", "1.25")},
        account_asset_rows=_management_account_assets(),
        venue_market_rows=_management_venue_markets(),
        now_utc=now,
    )
    html = render_wallet_html(payload)
    assert "Management" in html
    assert "Add asset" in html
    assert "Hide selected" in html
    assert "Pause selected for 24h" in html
    assert "UI_PREP_ONLY_NO_AUTH_LAYER" in html
    assert "/synth/about.html" in html
    assert "/synth/accounts/joost/profit-plan.html" in html
    assert "/synth/accounts/joost/open-orders-monitor.html" in html
    assert "/synth/paper-advice.html" not in html
    assert "/synth/entry-candidates.html" not in html
    assert "/synth/rotation-preview.html" not in html
    assert "2026-06-03 14:00:00 CEST" in html


def test_wallet_dashboard_source_has_no_decision_execution_imports():
    src = Path("src/reporting/account_wallet_dashboard_v1.py").read_text()
    assert "from src.decision_gate" not in src
    assert "import src.decision_gate" not in src
    assert "from src.execution_planner" not in src
    assert "import src.execution_planner" not in src
    assert "from src.executor" not in src
    assert "import src.executor" not in src


def test_source_no_broker_writes_or_order_submission():
    for path in [
        Path("src/reporting/account_wallet_dashboard_v1.py"),
        Path("src/reporting/run_account_wallet_dashboard_v1.py"),
    ]:
        src = path.read_text()
        assert "place_order" not in src
        assert "cancel_order" not in src
        assert "BROKER_WRITE_PERMISSION" not in src


def test_source_ast_no_broker_calls():
    src = Path("src/reporting/account_wallet_dashboard_v1.py").read_text()
    tree = ast.parse(src)
    forbidden_attrs = {"place_order", "cancel_order", "submit_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            raise AssertionError(f"Forbidden method call .{node.attr}() in dashboard source")


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


def test_fetch_trading_account_fails_closed_on_ambiguous_match() -> None:
    conn = _FakeConn(
        [
            {"trading_account_id": 3, "account_code": "legacy_ref", "venue": "bitvavo"},
            {"trading_account_id": 9, "account_code": "legacy_ref", "venue": "bitvavo"},
        ]
    )
    try:
        _fetch_trading_account(conn, account_code="legacy_ref", venue="bitvavo")
    except RuntimeError as exc:
        assert "trading_account ambiguous" in str(exc)
    else:
        raise AssertionError("Expected ambiguous trading_account resolution to fail closed")


def test_wallet_runner_source_does_not_construct_account_code_from_profile_name() -> None:
    source = Path("src/reporting/run_account_wallet_dashboard_v1.py").read_text(encoding="utf-8")
    assert "bitvavo_{args.account_profile}_read" not in source


def test_wallet_runner_unmapped_profile_fails_closed() -> None:
    original_parse_args = wallet_runner.parse_args
    original_resolve_access = wallet_runner.resolve_dashboard_profile_access
    original_load = wallet_runner.load_and_write_wallet_dashboard
    try:
        wallet_runner.parse_args = lambda: type(
            "Args",
            (),
            {
                "account_profile": "hugo",
                "venue": "bitvavo",
                "output_root": "/tmp",
                "fresh_after_minutes": 15,
                "price_fresh_after_minutes": 15,
                "output": "none",
            },
        )()
        wallet_runner.resolve_dashboard_profile_access = lambda **_: (_ for _ in ()).throw(
            RuntimeError("PROFILE_HAS_NO_ACCOUNT_ACCESS: profile=hugo venue=bitvavo")
        )
        wallet_runner.load_and_write_wallet_dashboard = lambda **_: (_ for _ in ()).throw(
            AssertionError("load should not be reached for unmapped profile")
        )
        assert wallet_runner.main() == 1
    finally:
        wallet_runner.parse_args = original_parse_args
        wallet_runner.resolve_dashboard_profile_access = original_resolve_access
        wallet_runner.load_and_write_wallet_dashboard = original_load


def main():
    test_stale_detection()
    test_empty_wallet_render()
    test_unknown_asset_render()
    test_stale_price_fails_closed_for_estimated_value()
    test_joost_hugo_isolation()
    test_no_secrets_in_html_json()
    test_write_wallet_dashboard_outputs_accounts_profile_files()
    test_wallet_json_contains_management_payload()
    test_wallet_html_includes_management_sections()
    test_wallet_dashboard_source_has_no_decision_execution_imports()
    test_source_no_broker_writes_or_order_submission()
    test_source_ast_no_broker_calls()
    test_wallet_runner_source_does_not_construct_account_code_from_profile_name()
    test_wallet_runner_unmapped_profile_fails_closed()
    test_fetch_trading_account_fails_closed_on_ambiguous_match()
    print("ok")


if __name__ == "__main__":
    main()
