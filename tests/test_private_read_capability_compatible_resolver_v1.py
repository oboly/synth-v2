"""Focused tests for Issue #631 capability-compatible private-read resolution."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.account.private_read_capability_compatible_resolver_v1 import (
    resolve_private_read_capable_bitvavo_client,
    resolve_private_read_capable_credential,
)
from src.account.private_read_credential_resolver_v1 import (
    PrivateReadCredentialResolutionError,
    resolve_private_read_credential,
)
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
    generate_test_master_key,
    parse_master_key,
)

_NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)

_SCHEMA = """
CREATE TABLE trading_account (
    trading_account_id INTEGER PRIMARY KEY,
    account_code TEXT NOT NULL,
    venue TEXT NOT NULL,
    account_mode TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    live_trading_enabled INTEGER NOT NULL
);

CREATE TABLE trading_account_credential (
    trading_account_credential_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    credential_kind TEXT NOT NULL,
    encrypted_envelope TEXT NOT NULL,
    encryption_algorithm TEXT NOT NULL,
    key_version TEXT NOT NULL,
    credential_fingerprint TEXT NOT NULL,
    credential_status TEXT NOT NULL,
    validation_state TEXT NOT NULL,
    created_ts_utc TEXT NOT NULL,
    validated_ts_utc TEXT,
    credential_source TEXT NOT NULL,
    permission_scope TEXT NOT NULL,
    allowed_private_read INTEGER NOT NULL,
    allowed_order_write INTEGER NOT NULL,
    allowed_withdrawal INTEGER NOT NULL
);
"""


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        """
        INSERT INTO trading_account (
            trading_account_id, account_code, venue, account_mode,
            enabled, live_trading_enabled
        ) VALUES (5, 'bitvavo_joost_live', 'bitvavo', 'live', 1, 1)
        """
    )
    return conn


def _key() -> tuple[str, bytes]:
    return parse_master_key(generate_test_master_key())


def _seed(
    conn: sqlite3.Connection,
    *,
    key_version: str,
    master_key_bytes: bytes,
    permission_scope: str,
    api_key: str,
    validation_state: str | None = None,
    validated_ts_utc: str | None = None,
    allowed_private_read: int | None = None,
    allowed_order_write: int | None = None,
    allowed_withdrawal: int = 0,
) -> int:
    if permission_scope == "TRADE_EXECUTION":
        validation_state = validation_state or "VALID_TRADE_EXECUTION"
        if allowed_private_read is None:
            allowed_private_read = 1
        if allowed_order_write is None:
            allowed_order_write = 1
    else:
        validation_state = validation_state or "VALID_PRIVATE_READ"
        if allowed_private_read is None:
            allowed_private_read = 1
        if allowed_order_write is None:
            allowed_order_write = 0

    if validated_ts_utc is None:
        validated_ts_utc = _NOW.isoformat(sep=" ")

    plain = PlainBitvavoCredential(
        venue="bitvavo",
        api_key=api_key,
        api_secret=f"{api_key}-secret",
    )
    envelope = encrypt_credential(
        plain,
        trading_account_id=5,
        key_version=key_version,
        master_key_bytes=master_key_bytes,
    )
    cur = conn.execute(
        """
        INSERT INTO trading_account_credential (
            trading_account_id, venue, credential_kind, encrypted_envelope,
            encryption_algorithm, key_version, credential_fingerprint,
            credential_status, validation_state, created_ts_utc,
            validated_ts_utc, credential_source, permission_scope,
            allowed_private_read, allowed_order_write, allowed_withdrawal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            5,
            "bitvavo",
            "API_KEY_SECRET",
            envelope.to_json(),
            envelope.alg,
            key_version,
            compute_fingerprint("bitvavo", api_key, master_key_bytes),
            "ACTIVE",
            validation_state,
            _NOW.isoformat(sep=" "),
            validated_ts_utc,
            "db_encrypted",
            permission_scope,
            allowed_private_read,
            allowed_order_write,
            allowed_withdrawal,
        ),
    )
    return int(cur.lastrowid)


def _assert_code(exc: pytest.ExceptionInfo[PrivateReadCredentialResolutionError], code: str) -> None:
    assert exc.value.code == code
    assert str(exc.value).startswith(code + ":")


def test_strict_read_only_resolver_remains_unchanged() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="READ_ONLY_PRIVATE",
        api_key="readonly",
    )

    identity, resolved = resolve_private_read_credential(
        conn,
        master_key_bytes=kb,
        trading_account_id=5,
        venue="bitvavo",
    )

    assert identity.trading_account_id == 5
    assert resolved.profile.permission_scope == "READ_ONLY_PRIVATE"


def test_strict_read_only_resolver_does_not_accept_trade_execution() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            master_key_bytes=kb,
            trading_account_id=5,
            venue="bitvavo",
        )
    _assert_code(exc, "NO_CREDENTIAL_BINDING")


def test_compatible_resolver_accepts_validated_trade_execution_private_read() -> None:
    kv, kb = _key()
    conn = _db()
    credential_id = _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
    )

    identity, resolved = resolve_private_read_capable_credential(
        conn,
        master_key_bytes=kb,
        trading_account_id=5,
        venue="bitvavo",
    )

    assert identity.trading_account_id == 5
    assert resolved.profile.trading_account_credential_id == credential_id
    assert resolved.profile.permission_scope == "TRADE_EXECUTION"
    assert resolved.profile.allowed_private_read is True
    assert resolved.profile.allowed_order_write is True
    assert resolved.profile.allowed_withdrawal is False


def test_trade_execution_private_read_disabled_fails_closed() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
        allowed_private_read=0,
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_capable_credential(
            conn,
            master_key_bytes=kb,
            trading_account_id=5,
            venue="bitvavo",
        )
    _assert_code(exc, "MISSING_REQUIRED_PRIVATE_READ_SCOPE")


def test_unvalidated_trade_execution_fails_closed() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
        validation_state="UNVALIDATED",
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_capable_credential(
            conn,
            master_key_bytes=kb,
            trading_account_id=5,
            venue="bitvavo",
        )
    _assert_code(exc, "UNVALIDATED_CREDENTIAL")


def test_withdrawal_capable_trade_execution_fails_closed() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
        allowed_withdrawal=1,
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_capable_credential(
            conn,
            master_key_bytes=kb,
            trading_account_id=5,
            venue="bitvavo",
        )
    _assert_code(exc, "WITHDRAWAL_CAPABILITY_NOT_ALLOWED")


def test_missing_validation_timestamp_trade_execution_fails_closed() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
        validated_ts_utc="",
    )
    conn.execute(
        "UPDATE trading_account_credential SET validated_ts_utc = NULL"
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_capable_credential(
            conn,
            master_key_bytes=kb,
            trading_account_id=5,
            venue="bitvavo",
        )
    _assert_code(exc, "CREDENTIAL_VALIDATION_TIMESTAMP_MISSING")


def test_read_only_and_trade_execution_candidates_are_ambiguous() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="READ_ONLY_PRIVATE",
        api_key="readonly",
    )
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_capable_credential(
            conn,
            master_key_bytes=kb,
            trading_account_id=5,
            venue="bitvavo",
        )
    _assert_code(exc, "AMBIGUOUS_PRIVATE_READ_CAPABLE_CREDENTIALS")


def test_compatible_client_factory_receives_only_decrypted_key_secret() -> None:
    kv, kb = _key()
    conn = _db()
    _seed(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        permission_scope="TRADE_EXECUTION",
        api_key="trade",
    )
    calls: list[tuple[str, str]] = []
    sentinel = object()

    def factory(api_key: str, api_secret: str) -> object:
        calls.append((api_key, api_secret))
        return sentinel

    resolved = resolve_private_read_capable_bitvavo_client(
        conn,
        master_key_bytes=kb,
        trading_account_id=5,
        venue="bitvavo",
        client_factory=factory,
    )

    assert resolved.client is sentinel
    assert calls == [("trade", "trade-secret")]
    assert resolved.profile.permission_scope == "TRADE_EXECUTION"


def test_production_client_construction_is_private_read_only() -> None:
    source = Path(
        "src/account/private_read_capability_compatible_resolver_v1.py"
    ).read_text()
    assert "BitvavoClient.for_private_read(" in source
    assert ".place_order(" not in source
    assert ".cancel_order(" not in source
    assert ".withdraw" not in source


def test_exact_account_runner_opts_into_compatible_resolver_and_stays_bounded() -> None:
    source = Path("src/account/run_exact_account_state_refresh_v1.py").read_text()
    assert "resolve_private_read_capable_bitvavo_client_from_env" in source
    assert "client.get_balance()" in source
    assert "client.get_open_orders()" in source
    assert ".place_order(" not in source
    assert ".cancel_order(" not in source
    assert ".withdraw" not in source
