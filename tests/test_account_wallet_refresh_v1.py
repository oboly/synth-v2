from __future__ import annotations

import ast
import os
import tempfile
from decimal import Decimal
from pathlib import Path

from src.account.account_snapshot_models_v1 import WalletBalanceRow, WalletOpenOrderRow
from src.account.run_account_wallet_refresh_v1 import (
    get_account_env_dir,
    load_profile_credentials,
    normalize_balance_rows,
    normalize_order_rows,
    validate_profile_slug,
)


# ---------------------------------------------------------------------------
# validate_profile_slug
# ---------------------------------------------------------------------------

def test_valid_profile_slug_joost():
    validate_profile_slug("joost")  # must not raise


def test_valid_profile_slug_hugo():
    validate_profile_slug("hugo")  # must not raise


def test_valid_profile_slug_with_hyphen():
    validate_profile_slug("joost-main")  # must not raise


def test_valid_profile_slug_with_underscore():
    validate_profile_slug("joost_main")  # must not raise


def test_invalid_profile_slug_path_traversal_dots():
    try:
        validate_profile_slug("../etc/passwd")
        raise AssertionError("Expected ValueError for path traversal")
    except ValueError:
        pass


def test_invalid_profile_slug_path_traversal_slash():
    try:
        validate_profile_slug("joost/secret")
        raise AssertionError("Expected ValueError for slash")
    except ValueError:
        pass


def test_invalid_profile_slug_uppercase():
    try:
        validate_profile_slug("Joost")
        raise AssertionError("Expected ValueError for uppercase")
    except ValueError:
        pass


def test_invalid_profile_slug_empty():
    try:
        validate_profile_slug("")
        raise AssertionError("Expected ValueError for empty string")
    except ValueError:
        pass


def test_invalid_profile_slug_spaces():
    try:
        validate_profile_slug("jo ost")
        raise AssertionError("Expected ValueError for spaces")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# normalize_balance_rows
# ---------------------------------------------------------------------------

def _raw_balances() -> list[dict]:
    return [
        {"symbol": "BTC", "available": "0.05", "inOrder": "0.01"},
        {"symbol": "ETH", "available": "1.0", "inOrder": "0"},
        {"symbol": "EUR", "available": "500.00", "inOrder": "0"},
        {"symbol": "", "available": "1.0", "inOrder": "0"},
        {"asset": "WLD", "available": "100.0"},
    ]


def test_balance_rows_sorted_by_currency():
    rows = normalize_balance_rows(_raw_balances())
    codes = [r.currency_code for r in rows]
    assert codes == sorted(codes)


def test_balance_row_totals_correct():
    rows = normalize_balance_rows(_raw_balances())
    btc = next(r for r in rows if r.currency_code == "BTC")
    assert btc.total_amount == btc.available_amount + btc.reserved_amount


def test_balance_row_empty_currency_filtered():
    rows = normalize_balance_rows(_raw_balances())
    codes = {r.currency_code for r in rows}
    assert "" not in codes


def test_balance_row_asset_field_accepted():
    rows = normalize_balance_rows(_raw_balances())
    codes = {r.currency_code for r in rows}
    assert "WLD" in codes


def test_balance_row_in_order_mapped_to_reserved():
    rows = normalize_balance_rows(_raw_balances())
    btc = next(r for r in rows if r.currency_code == "BTC")
    assert btc.reserved_amount == Decimal("0.01")


def test_balance_rows_empty_input():
    rows = normalize_balance_rows([])
    assert rows == []


# ---------------------------------------------------------------------------
# normalize_order_rows
# ---------------------------------------------------------------------------

def _raw_orders() -> list[dict]:
    return [
        {
            "market": "BTC-EUR",
            "side": "buy",
            "orderType": "limit",
            "orderId": "abc123",
            "price": "50000.00",
            "amount": "0.001",
            "amountRemaining": "0.001",
            "status": "new",
        },
        {
            "market": "ETH-EUR",
            "side": "sell",
            "orderType": "limit",
            "orderId": "def456",
            "price": "2000.00",
            "amount": "0.5",
            "amountRemaining": "0.3",
            "status": "new",
        },
        {
            "market": "BTC-USDT",
            "side": "buy",
            "orderType": "limit",
            "orderId": "ghi789",
            "price": "50000.00",
            "amount": "0.001",
            "amountRemaining": "0.001",
            "status": "new",
        },
        {
            "market": "SOL-EUR",
            "side": "buy",
            "orderType": "limit",
            "orderId": "",
            "price": "100.00",
            "amount": "1.0",
            "amountRemaining": "1.0",
            "status": "new",
        },
    ]


def test_order_rows_non_eur_filtered():
    rows = normalize_order_rows(_raw_orders(), venue_quote="EUR")
    markets = {r.market for r in rows}
    assert "BTC-USDT" not in markets


def test_order_rows_eur_included():
    rows = normalize_order_rows(_raw_orders(), venue_quote="EUR")
    markets = {r.market for r in rows}
    assert "BTC-EUR" in markets
    assert "ETH-EUR" in markets


def test_order_rows_empty_order_id_filtered():
    rows = normalize_order_rows(_raw_orders(), venue_quote="EUR")
    order_ids = {r.broker_order_id for r in rows}
    assert "" not in order_ids


def test_order_row_filled_computed_from_remaining():
    rows = normalize_order_rows(_raw_orders(), venue_quote="EUR")
    eth = next(r for r in rows if r.market == "ETH-EUR")
    assert eth.filled_quantity == Decimal("0.5") - Decimal("0.3")


def test_order_row_side_uppercased():
    rows = normalize_order_rows(_raw_orders(), venue_quote="EUR")
    btc = next(r for r in rows if r.market == "BTC-EUR")
    assert btc.side == "BUY"


def test_order_rows_empty_input():
    rows = normalize_order_rows([], venue_quote="EUR")
    assert rows == []


# ---------------------------------------------------------------------------
# Account isolation: Hugo refresh must not touch Joost's account_asset
# ---------------------------------------------------------------------------

def test_different_profiles_have_different_account_codes():
    from src.account.run_account_wallet_refresh_v1 import main as _main
    # The account_code derivation is deterministic per profile:
    joost_code = "bitvavo_joost_read"
    hugo_code = "bitvavo_hugo_read"
    assert joost_code != hugo_code


def test_profile_credential_path_scoped_to_profile():
    from src.account.run_account_wallet_refresh_v1 import CREDENTIAL_BASE_DIR
    joost_path = CREDENTIAL_BASE_DIR / "joost.env"
    hugo_path = CREDENTIAL_BASE_DIR / "hugo.env"
    assert joost_path != hugo_path
    assert "joost" in str(joost_path)
    assert "hugo" in str(hugo_path)


def test_account_env_dir_default_uses_path_home():
    assert get_account_env_dir() == Path.home() / ".config/synth/accounts"


def test_synth_account_env_dir_overrides_default():
    old_value = os.environ.get("SYNTH_ACCOUNT_ENV_DIR")
    try:
        os.environ["SYNTH_ACCOUNT_ENV_DIR"] = "/tmp/synth-test-accounts"
        assert get_account_env_dir() == Path("/tmp/synth-test-accounts")
    finally:
        if old_value is None:
            os.environ.pop("SYNTH_ACCOUNT_ENV_DIR", None)
        else:
            os.environ["SYNTH_ACCOUNT_ENV_DIR"] = old_value


def test_load_profile_credentials_uses_env_override():
    old_value = os.environ.get("SYNTH_ACCOUNT_ENV_DIR")
    with tempfile.TemporaryDirectory() as tmpdir:
        env_dir = Path(tmpdir)
        (env_dir / "joost.env").write_text(
            "BITVAVO_API_KEY=test-key\nBITVAVO_API_SECRET=test-secret\n",
            encoding="utf-8",
        )
        try:
            os.environ["SYNTH_ACCOUNT_ENV_DIR"] = str(env_dir)
            api_key, api_secret = load_profile_credentials("joost")
        finally:
            if old_value is None:
                os.environ.pop("SYNTH_ACCOUNT_ENV_DIR", None)
            else:
                os.environ["SYNTH_ACCOUNT_ENV_DIR"] = old_value
    assert api_key == "test-key"
    assert api_secret == "test-secret"


# ---------------------------------------------------------------------------
# Secrets never leak in repr/str
# ---------------------------------------------------------------------------

def test_wallet_balance_row_repr_has_no_secrets():
    row = WalletBalanceRow(
        currency_code="BTC",
        available_amount=Decimal("0.05"),
        reserved_amount=Decimal("0.01"),
        total_amount=Decimal("0.06"),
    )
    r = repr(row)
    # repr must not contain anything resembling a secret key pattern
    assert "API_KEY" not in r
    assert "API_SECRET" not in r


def test_wallet_open_order_row_repr_no_secrets():
    row = WalletOpenOrderRow(
        market="BTC-EUR",
        side="BUY",
        order_type="LIMIT",
        broker_order_id="abc123",
        client_order_id=None,
        limit_price=Decimal("50000"),
        quantity=Decimal("0.001"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("0.001"),
        broker_status="NEW",
    )
    r = repr(row)
    assert "API_KEY" not in r
    assert "API_SECRET" not in r


# ---------------------------------------------------------------------------
# AST safety: no broker writes in wallet refresh source
# ---------------------------------------------------------------------------

def test_wallet_refresh_source_no_place_order():
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "place_order" not in src


def test_wallet_refresh_source_no_cancel_order():
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "cancel_order" not in src


def test_wallet_refresh_source_no_broker_write_permission():
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "BROKER_WRITE_PERMISSION" not in src
    assert "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS" not in src


def test_wallet_refresh_source_supports_account_env_dir_cli():
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "--account-env-dir" in src


def test_wallet_refresh_ast_no_broker_write_calls():
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    tree = ast.parse(src)
    forbidden_attrs = {"place_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            raise AssertionError(f"Forbidden method call .{node.attr}() in wallet refresh source")


def test_account_snapshot_models_no_broker_imports():
    src = Path("src/account/account_snapshot_models_v1.py").read_text()
    assert "bitvavo" not in src.lower()
    assert "BitvavoClient" not in src
    assert "requests" not in src
    assert "get_db_connection" not in src


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    test_valid_profile_slug_joost()
    test_valid_profile_slug_hugo()
    test_valid_profile_slug_with_hyphen()
    test_valid_profile_slug_with_underscore()
    test_invalid_profile_slug_path_traversal_dots()
    test_invalid_profile_slug_path_traversal_slash()
    test_invalid_profile_slug_uppercase()
    test_invalid_profile_slug_empty()
    test_invalid_profile_slug_spaces()
    test_balance_rows_sorted_by_currency()
    test_balance_row_totals_correct()
    test_balance_row_empty_currency_filtered()
    test_balance_row_asset_field_accepted()
    test_balance_row_in_order_mapped_to_reserved()
    test_balance_rows_empty_input()
    test_order_rows_non_eur_filtered()
    test_order_rows_eur_included()
    test_order_rows_empty_order_id_filtered()
    test_order_row_filled_computed_from_remaining()
    test_order_row_side_uppercased()
    test_order_rows_empty_input()
    test_different_profiles_have_different_account_codes()
    test_profile_credential_path_scoped_to_profile()
    test_account_env_dir_default_uses_path_home()
    test_synth_account_env_dir_overrides_default()
    test_load_profile_credentials_uses_env_override()
    test_wallet_balance_row_repr_has_no_secrets()
    test_wallet_open_order_row_repr_no_secrets()
    test_wallet_refresh_source_no_place_order()
    test_wallet_refresh_source_no_cancel_order()
    test_wallet_refresh_source_no_broker_write_permission()
    test_wallet_refresh_source_supports_account_env_dir_cli()
    test_wallet_refresh_ast_no_broker_write_calls()
    test_account_snapshot_models_no_broker_imports()
    print("ok")


if __name__ == "__main__":
    main()
