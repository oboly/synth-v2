"""
Tests for src/account_provisioning/connect_bitvavo_v1.py

All broker calls are mocked. No real API calls.
broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account_provisioning.account_credential_loader_v1 import load_account_credential
from src.account_provisioning.account_provisioning_service_v1 import (
    AccountProvisioningService,
    AuthenticatedProfileIdentity,
    ProvisioningResult,
)
from src.account_provisioning.account_repository_v1 import SqliteAccountRepository
from src.account_provisioning.account_snapshot_service_v1 import SnapshotResult
from src.account_provisioning.connect_bitvavo_v1 import build_connect_bitvavo
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.credential_repository_v1 import (
    CREDENTIAL_KIND_API_KEY_SECRET,
    SqliteCredentialRepository,
)
from src.account_provisioning.credential_validator_v1 import MockBitvavoCredentialValidator
from src.web.website_registration_v1 import SqliteWebsiteRegistrationRepository


_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_IDENTITY = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=1, profile_code="hugo")
_DB_COUNTER = [0]


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


def _next_db() -> str:
    _DB_COUNTER[0] += 1
    return f"connect_callable_test_{_DB_COUNTER[0]}"


def _shared_conn(db_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_name}?mode=memory&cache=shared", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_schema(db_name: str) -> sqlite3.Connection:
    conn = _shared_conn(db_name)
    SqliteWebsiteRegistrationRepository(conn).create_schema()
    SqliteAccountRepository(conn).create_schema()
    SqliteCredentialRepository(conn).create_schema()
    conn.executescript(_SNAPSHOT_TABLES)
    conn.commit()
    return conn


def _seed_profile_and_account(
    seed: sqlite3.Connection,
    *,
    master_key_bytes: bytes,
    kv: str,
    profile_code: str = "hugo",
    api_key: str = "hugo-api-key",
    api_secret: str = "hugo-api-secret",
) -> tuple[int, int]:
    """Seed profile + trading_account + credential. Returns (app_profile_id, trading_account_id)."""
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        (profile_code, "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    app_profile_id = int(
        seed.execute(
            "SELECT app_profile_id FROM app_profile WHERE profile_code = ?", (profile_code,)
        ).fetchone()["app_profile_id"]
    )
    seed.execute(
        "INSERT INTO trading_account (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("hugo-bitvavo", "bitvavo", "paper", 1, 0, "2026-06-09 12:00:00"),
    )
    seed.commit()
    ta_id = int(
        seed.execute(
            "SELECT trading_account_id FROM trading_account WHERE account_code = 'hugo-bitvavo'"
        ).fetchone()["trading_account_id"]
    )
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
    seed.execute(
        "INSERT INTO app_profile_trading_account_link"
        " (app_profile_id, trading_account_id, link_status, is_primary, created_ts_utc)"
        " VALUES (?, ?, 'ACTIVE', 1, ?)",
        (app_profile_id, ta_id, "2026-06-09 12:00:00"),
    )
    seed.commit()
    return app_profile_id, ta_id


def _mock_client(balances=None, balance_exc=None):
    client = MagicMock()
    if balance_exc:
        client.get_balance.side_effect = balance_exc
    else:
        client.get_balance.return_value = balances or [
            {"symbol": "EUR", "available": "100.00", "inOrder": "0"},
        ]
    client.get_open_orders.return_value = []
    return client


def _noop_renderer(**_kwargs: Any) -> None:
    pass


def _failing_renderer(**_kwargs: Any) -> None:
    raise RuntimeError("render failed")


# ---------------------------------------------------------------------------
# Provisioning success → snapshot → render → refresh_pending=False
# ---------------------------------------------------------------------------

def test_successful_activation_sets_refresh_pending_false() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    seed.execute(
        "INSERT INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=lambda: _shared_conn(db),
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _as: _mock_client(),
        activation_renderer=_noop_renderer,
        output_root=Path("/tmp/test_out"),
    )
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

    assert result.ok is True
    assert result.refresh_pending is False
    assert result.refresh_error_code is None
    seed.close()


def test_snapshot_failure_sets_refresh_pending_true() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    seed.execute(
        "INSERT INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=lambda: _shared_conn(db),
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _as: _mock_client(balance_exc=RuntimeError("API down")),
        activation_renderer=_noop_renderer,
        output_root=Path("/tmp/test_out"),
    )
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

    assert result.ok is True
    assert result.refresh_pending is True
    assert result.refresh_error_code == "BALANCE_FETCH_FAILED"
    seed.close()


def test_render_failure_sets_refresh_pending_true() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    seed.execute(
        "INSERT INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=lambda: _shared_conn(db),
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _as: _mock_client(),
        activation_renderer=_failing_renderer,
        output_root=Path("/tmp/test_out"),
    )
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

    assert result.ok is True
    assert result.refresh_pending is True
    assert result.refresh_error_code == "ACTIVATION_RENDER_FAILED"
    seed.close()


# ---------------------------------------------------------------------------
# Safe retry: ACCOUNT_ALREADY_CONNECTED → snapshot + render with stored credential
# ---------------------------------------------------------------------------

def test_already_connected_retry_succeeds_returns_ok_refresh_false() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    pid, ta_id = _seed_profile_and_account(seed, master_key_bytes=kb, kv=kv)

    # Seed onboarding state to already-connected
    seed.execute(
        "UPDATE app_profile SET onboarding_state = 'READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED' WHERE app_profile_id = ?",
        (pid,),
    )
    seed.commit()

    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=lambda: _shared_conn(db),
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _as: _mock_client(),
        activation_renderer=_noop_renderer,
        output_root=Path("/tmp/test_out"),
    )
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

    assert result.ok is True
    assert result.refresh_pending is False
    assert result.refresh_error_code is None
    assert result.profile_code == "hugo"
    seed.close()


def test_already_connected_retry_snapshot_failure_returns_refresh_pending() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    pid, ta_id = _seed_profile_and_account(seed, master_key_bytes=kb, kv=kv)
    seed.execute(
        "UPDATE app_profile SET onboarding_state = 'READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED' WHERE app_profile_id = ?",
        (pid,),
    )
    seed.commit()

    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=lambda: _shared_conn(db),
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _as: _mock_client(balance_exc=RuntimeError("down")),
        activation_renderer=_noop_renderer,
        output_root=Path("/tmp/test_out"),
    )
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

    assert result.ok is True
    assert result.refresh_pending is True
    assert result.profile_code == "hugo"
    seed.close()


# ---------------------------------------------------------------------------
# Provisioning errors pass through unchanged
# ---------------------------------------------------------------------------

def test_invalid_credentials_returned_unchanged() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())
    seed.execute(
        "INSERT INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=lambda: _shared_conn(db),
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _as: _mock_client(),
        activation_renderer=_noop_renderer,
        output_root=Path("/tmp/test_out"),
    )
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    # MockBitvavoCredentialValidator uses "mock-invalid" prefix to trigger failure
    result = connect(identity, "mock-invalid-key", "bad-secret", True, _NOW)

    assert result.ok is False
    assert result.error_code == "INVALID_CREDENTIALS"
    seed.close()


# ---------------------------------------------------------------------------
# No broker calls leaking into the callable itself
# ---------------------------------------------------------------------------

def test_no_global_env_credentials_in_connect_bitvavo_module() -> None:
    source = Path("src/account_provisioning/connect_bitvavo_v1.py").read_text()
    assert "BITVAVO_API_KEY" not in source
    assert "BITVAVO_API_SECRET" not in source
    assert "os.getenv" not in source
    assert "os.environ" not in source


def test_no_broker_writes_in_connect_bitvavo_module() -> None:
    source = Path("src/account_provisioning/connect_bitvavo_v1.py").read_text()
    assert "place_order" not in source
    assert "cancel_order" not in source


if __name__ == "__main__":
    tests = [
        test_successful_activation_sets_refresh_pending_false,
        test_snapshot_failure_sets_refresh_pending_true,
        test_render_failure_sets_refresh_pending_true,
        test_already_connected_retry_succeeds_returns_ok_refresh_false,
        test_already_connected_retry_snapshot_failure_returns_refresh_pending,
        test_invalid_credentials_returned_unchanged,
        test_no_global_env_credentials_in_connect_bitvavo_module,
        test_no_broker_writes_in_connect_bitvavo_module,
    ]
    for t in tests:
        t()
    print("ok")
