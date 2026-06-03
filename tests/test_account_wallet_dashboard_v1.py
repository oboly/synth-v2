from __future__ import annotations

import ast
import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.reporting.account_wallet_dashboard_v1 import (
    AccountAssetSettingsSummary,
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
        latest_balance_snapshot_ts_utc=None,
        latest_order_snapshot_ts_utc=None,
        balance_rows=[],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={},
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
        now_utc=now,
    )
    html = render_wallet_html(payload)
    payload_json = payload_to_json_dict(payload)
    assert payload.market_data_warning is not None
    assert "XYZ" in html
    assert payload_json["balances"][0]["price_status"] == "MISSING"


def test_joost_hugo_isolation():
    now = _base_now()
    joost = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=11,
        venue="bitvavo",
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
        now_utc=now,
    )
    hugo = build_wallet_dashboard_payload(
        profile="hugo",
        account_code="bitvavo_hugo_read",
        trading_account_id=22,
        venue="bitvavo",
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
        profile="hugo",
        account_code="bitvavo_hugo_read",
        trading_account_id=2,
        venue="bitvavo",
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
        now_utc=now,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path, json_path = write_wallet_dashboard(payload, output_root=Path(tmpdir))
        assert html_path.name == "wallet.html"
        assert json_path.name == "wallet.json"
        assert html_path.parent.name == "hugo"
        assert json_path.parent.name == "hugo"
        assert html_path.exists()
        assert json_path.exists()


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


def main():
    test_stale_detection()
    test_empty_wallet_render()
    test_unknown_asset_render()
    test_joost_hugo_isolation()
    test_no_secrets_in_html_json()
    test_write_wallet_dashboard_outputs_accounts_profile_files()
    test_source_no_broker_writes_or_order_submission()
    test_source_ast_no_broker_calls()
    print("ok")


if __name__ == "__main__":
    main()
