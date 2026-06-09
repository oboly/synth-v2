"""
Tests for account_credential_loader_v1 and account_snapshot_service_v1.

All broker calls are mocked — broker_private_calls=0 in automated tests.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account_provisioning.account_credential_loader_v1 import load_account_credential
from src.account_provisioning.account_snapshot_service_v1 import SnapshotResult, take_first_snapshot
from src.account_provisioning.account_repository_v1 import SqliteAccountRepository
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import (
    encrypt_credential,
    compute_fingerprint,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.credential_repository_v1 import (
    CREDENTIAL_KIND_API_KEY_SECRET,
    SqliteCredentialRepository,
)
from src.web.website_registration_v1 import SqliteWebsiteRegistrationRepository


_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_DB_COUNTER = [0]


def _next_db() -> str:
    _DB_COUNTER[0] += 1
    return f"snap_test_{_DB_COUNTER[0]}"


def _shared_conn(db_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_name}?mode=memory&cache=shared", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


_SNAPSHOT_TABLES = """
CREATE TABLE IF NOT EXISTS trading_account_balance_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts_utc TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    available_amount TEXT NOT NULL,
    reserved_amount TEXT NOT NULL,
    total_amount TEXT NOT NULL,
    source_name TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_order_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts_utc TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    execution_intent_id INTEGER NULL,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    limit_price_eur TEXT NULL,
    quantity_base TEXT NOT NULL,
    filled_quantity_base TEXT NOT NULL,
    remaining_quantity_base TEXT NOT NULL,
    broker_status TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
"""


def _seed_schema(db_name: str) -> sqlite3.Connection:
    conn = _shared_conn(db_name)
    SqliteWebsiteRegistrationRepository(conn).create_schema()
    SqliteAccountRepository(conn).create_schema()
    SqliteCredentialRepository(conn).create_schema()
    conn.executescript(_SNAPSHOT_TABLES)
    conn.commit()
    return conn


def _seed_account_with_credential(seed: sqlite3.Connection, master_key_bytes: bytes, kv: str,
                                   api_key: str = "hugo-api-key-123", api_secret: str = "hugo-api-secret-456") -> int:
    """Insert trading_account + encrypted credential, return trading_account_id."""
    seed.execute(
        "INSERT INTO trading_account (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("hugo-bitvavo", "bitvavo", "paper", 1, 0, "2026-06-09 12:00:00"),
    )
    seed.commit()
    ta_id = seed.execute("SELECT trading_account_id FROM trading_account WHERE account_code = 'hugo-bitvavo'").fetchone()["trading_account_id"]

    plain = PlainBitvavoCredential(venue="bitvavo", api_key=api_key, api_secret=api_secret)
    envelope = encrypt_credential(plain, ta_id, kv, master_key_bytes)
    fingerprint = compute_fingerprint("bitvavo", api_key, master_key_bytes)

    SqliteCredentialRepository(seed).insert_active_credential(
        trading_account_id=ta_id,
        venue="bitvavo",
        credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
        encrypted_envelope=envelope.to_json(),
        encryption_algorithm=envelope.alg,
        key_version=envelope.kv,
        credential_fingerprint=fingerprint,
        now_utc=_NOW,
        validation_state="VALID_PRIVATE_READ",
    )
    seed.commit()
    return int(ta_id)


# ---------------------------------------------------------------------------
# Credential loader
# ---------------------------------------------------------------------------

def test_load_credential_returns_plain_credential() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv, api_key="hugo-key", api_secret="hugo-secret")
    conn = _shared_conn(db)
    plain = load_account_credential(conn, trading_account_id=ta_id, venue="bitvavo", master_key_bytes=kb, cred_repo_factory=SqliteCredentialRepository)
    assert plain.api_key == "hugo-key"
    assert plain.api_secret == "hugo-secret"
    conn.close()
    seed.close()


def test_load_credential_raises_on_missing() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    conn = _shared_conn(db)
    raised = False
    try:
        load_account_credential(conn, trading_account_id=9999, venue="bitvavo", master_key_bytes=kb, cred_repo_factory=SqliteCredentialRepository)
    except ValueError as exc:
        raised = True
        assert "NO_ACTIVE_CREDENTIAL" in str(exc)
    assert raised
    conn.close()
    seed.close()


def test_load_credential_never_uses_global_env() -> None:
    """Hugo's load must use the stored credential, not BITVAVO_API_KEY env."""
    import os
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv, api_key="hugo-explicit-key", api_secret="hugo-explicit-secret")

    old_key = os.environ.get("BITVAVO_API_KEY")
    old_secret = os.environ.get("BITVAVO_API_SECRET")
    os.environ["BITVAVO_API_KEY"] = "joost-global-env-key"
    os.environ["BITVAVO_API_SECRET"] = "joost-global-env-secret"
    try:
        conn = _shared_conn(db)
        plain = load_account_credential(conn, trading_account_id=ta_id, venue="bitvavo", master_key_bytes=kb, cred_repo_factory=SqliteCredentialRepository)
        assert plain.api_key == "hugo-explicit-key", "must use stored credential, not global env"
        assert plain.api_key != "joost-global-env-key"
        conn.close()
    finally:
        if old_key is None:
            os.environ.pop("BITVAVO_API_KEY", None)
        else:
            os.environ["BITVAVO_API_KEY"] = old_key
        if old_secret is None:
            os.environ.pop("BITVAVO_API_SECRET", None)
        else:
            os.environ["BITVAVO_API_SECRET"] = old_secret
    seed.close()


def test_hugo_cannot_get_joost_credentials() -> None:
    """Loading with a different trading_account_id must not return Hugo's credential."""
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv, api_key="hugo-key", api_secret="hugo-secret")
    conn = _shared_conn(db)
    wrong_ta_id = ta_id + 1000
    raised = False
    try:
        load_account_credential(conn, trading_account_id=wrong_ta_id, venue="bitvavo", master_key_bytes=kb, cred_repo_factory=SqliteCredentialRepository)
    except ValueError:
        raised = True
    assert raised, "loading with wrong trading_account_id must raise"
    conn.close()
    seed.close()


# ---------------------------------------------------------------------------
# Snapshot service — mocked BitvavoClient
# ---------------------------------------------------------------------------

def _mock_client(balances=None, orders=None, balance_exc=None, orders_exc=None):
    client = MagicMock()
    if balance_exc:
        client.get_balance.side_effect = balance_exc
    else:
        client.get_balance.return_value = balances or [
            {"symbol": "EUR", "available": "100.00", "inOrder": "0"},
            {"symbol": "BTC", "available": "0.01", "inOrder": "0"},
        ]
    if orders_exc:
        client.get_open_orders.side_effect = orders_exc
    else:
        client.get_open_orders.return_value = orders or []
    return client


def test_snapshot_writes_balance_rows() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv)
    conn = _shared_conn(db)
    client = _mock_client(balances=[
        {"symbol": "EUR", "available": "100.00", "inOrder": "0"},
        {"symbol": "BTC", "available": "0.001", "inOrder": "0"},
    ])
    result = take_first_snapshot(conn, trading_account_id=ta_id, venue="bitvavo", bitvavo_client=client, now_utc=_NOW)
    assert result.ok is True
    assert result.balance_row_count == 2
    count = seed.execute("SELECT COUNT(*) AS n FROM trading_account_balance_snapshot WHERE trading_account_id = ?", (ta_id,)).fetchone()["n"]
    assert count == 2
    conn.close()
    seed.close()


def test_snapshot_writes_order_rows() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv)
    conn = _shared_conn(db)
    client = _mock_client(orders=[
        {"orderId": "ord-001", "market": "BTC-EUR", "side": "sell", "orderType": "limit",
         "price": "50000", "amount": "0.001", "filledAmount": "0", "amountRemaining": "0.001", "status": "new"},
    ])
    result = take_first_snapshot(conn, trading_account_id=ta_id, venue="bitvavo", bitvavo_client=client, now_utc=_NOW)
    assert result.ok is True
    assert result.order_row_count == 1
    count = seed.execute("SELECT COUNT(*) AS n FROM broker_order_snapshot WHERE trading_account_id = ?", (ta_id,)).fetchone()["n"]
    assert count == 1
    conn.close()
    seed.close()


def test_snapshot_balance_fetch_failure_returns_error() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv)
    conn = _shared_conn(db)
    client = _mock_client(balance_exc=RuntimeError("API unavailable"))
    result = take_first_snapshot(conn, trading_account_id=ta_id, venue="bitvavo", bitvavo_client=client, now_utc=_NOW)
    assert result.ok is False
    assert result.error_code == "BALANCE_FETCH_FAILED"
    conn.close()
    seed.close()


def test_snapshot_orders_fetch_failure_returns_error() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv)
    conn = _shared_conn(db)
    client = _mock_client(orders_exc=RuntimeError("orders unavailable"))
    result = take_first_snapshot(conn, trading_account_id=ta_id, venue="bitvavo", bitvavo_client=client, now_utc=_NOW)
    assert result.ok is False
    assert result.error_code == "ORDERS_FETCH_FAILED"
    conn.close()
    seed.close()


def test_snapshot_failure_leaves_no_rows_on_write_error() -> None:
    """If snapshot write fails, no partial rows committed."""
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    ta_id = _seed_account_with_credential(seed, kb, kv)
    conn = _shared_conn(db)
    # Drop the table so the INSERT fails
    conn.execute("DROP TABLE IF EXISTS trading_account_balance_snapshot")
    client = _mock_client()
    result = take_first_snapshot(conn, trading_account_id=ta_id, venue="bitvavo", bitvavo_client=client, now_utc=_NOW)
    assert result.ok is False
    conn.close()
    seed.close()


# ---------------------------------------------------------------------------
# ProvisioningResult includes trading_account_id
# ---------------------------------------------------------------------------

def test_provisioning_result_includes_trading_account_id() -> None:
    from src.account_provisioning.account_provisioning_service_v1 import (
        AccountProvisioningService, AuthenticatedProfileIdentity,
    )
    from src.account_provisioning.credential_validator_v1 import MockBitvavoCredentialValidator

    db = _next_db()
    seed = _seed_schema(db)
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc) VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])
    kv, kb = parse_master_key(generate_test_master_key())
    service = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = service.provision_bitvavo_account(
        identity=identity,
        api_key="mock-valid-read-only-key",
        api_secret="test-secret",
        withdrawal_disabled_confirmed=True,
        conn_factory=lambda: _shared_conn(db),
        now_utc=_NOW,
    )
    assert result.ok is True
    assert result.trading_account_id is not None
    assert isinstance(result.trading_account_id, int)
    seed.close()


# ---------------------------------------------------------------------------
# Architecture safety
# ---------------------------------------------------------------------------

def test_no_global_env_fallback_in_loader() -> None:
    source = Path("src/account_provisioning/account_credential_loader_v1.py").read_text()
    # No env-var fallback calls in functional code
    assert "os.getenv" not in source
    assert "os.environ" not in source
    # BitvavoClient is NOT imported (loader returns PlainBitvavoCredential, not a client)
    assert "BitvavoClient" not in source


def test_no_broker_writes_in_snapshot_service() -> None:
    source = Path("src/account_provisioning/account_snapshot_service_v1.py").read_text()
    assert "place_order" not in source
    assert "cancel_order" not in source


if __name__ == "__main__":
    tests = [
        test_load_credential_returns_plain_credential,
        test_load_credential_raises_on_missing,
        test_load_credential_never_uses_global_env,
        test_hugo_cannot_get_joost_credentials,
        test_snapshot_writes_balance_rows,
        test_snapshot_writes_order_rows,
        test_snapshot_balance_fetch_failure_returns_error,
        test_snapshot_orders_fetch_failure_returns_error,
        test_snapshot_failure_leaves_no_rows_on_write_error,
        test_provisioning_result_includes_trading_account_id,
        test_no_global_env_fallback_in_loader,
        test_no_broker_writes_in_snapshot_service,
    ]
    for t in tests:
        t()
    print("ok")
