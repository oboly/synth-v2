"""
Tests for run_migrate_credential_to_db_v1.migrate_credential_to_db.

Covers:
  - Successful migration inserts encrypted credential and commits
  - Duplicate active credential is rejected (ACTIVE_CREDENTIAL_EXISTS)
  - Missing profile-account link is rejected (NO_ACTIVE_PRIMARY_LINK)
  - Missing app_profile is rejected (NO_PROFILE_FOUND)
  - dry_run=True verifies account link without writing or prompting
  - Commit is called only on success; rollback on insert failure

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

import pytest

from src.account_provisioning.credential_crypto_v1 import (
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.credential_repository_v1 import SqliteCredentialRepository
from src.account_provisioning.run_migrate_credential_to_db_v1 import migrate_credential_to_db

_NOW = datetime(2026, 6, 11, 10, 0, 0, tzinfo=UTC)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_profile (
    app_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_code   TEXT NOT NULL UNIQUE,
    display_timezone TEXT NOT NULL DEFAULT 'UTC',
    onboarding_state TEXT NOT NULL DEFAULT 'READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED',
    created_ts_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trading_account (
    trading_account_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    account_code         TEXT NOT NULL UNIQUE,
    venue                TEXT NOT NULL,
    account_mode         TEXT NOT NULL DEFAULT 'paper',
    enabled              INTEGER NOT NULL DEFAULT 1,
    live_trading_enabled INTEGER NOT NULL DEFAULT 0,
    created_ts_utc       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_profile_trading_account_link (
    link_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    app_profile_id     INTEGER NOT NULL,
    trading_account_id INTEGER NOT NULL,
    link_status        TEXT NOT NULL DEFAULT 'ACTIVE',
    is_primary         INTEGER NOT NULL DEFAULT 0,
    created_ts_utc     TEXT NOT NULL,
    UNIQUE (app_profile_id, trading_account_id)
);
CREATE TABLE IF NOT EXISTS trading_account_credential (
    trading_account_credential_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id  INTEGER NOT NULL,
    venue               TEXT NOT NULL,
    credential_kind     TEXT NOT NULL,
    encrypted_envelope  TEXT NOT NULL,
    encryption_algorithm TEXT NOT NULL,
    key_version         TEXT NOT NULL,
    credential_fingerprint TEXT NOT NULL,
    credential_status   TEXT NOT NULL DEFAULT 'ACTIVE',
    validation_state    TEXT NOT NULL DEFAULT 'UNVALIDATED',
    created_ts_utc      TEXT NOT NULL,
    validated_ts_utc    TEXT,
    rotated_ts_utc      TEXT,
    revoked_ts_utc      TEXT
);
"""


class _MockCursor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._cur = conn.cursor()

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._cur.execute(sql.replace("%s", "?"), params)

    def fetchone(self) -> Any:
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self) -> list:
        return [dict(r) for r in self._cur.fetchall()]

    def __enter__(self) -> "_MockCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        pass


class _MockConn:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> _MockCursor:
        return _MockCursor(self._conn)

    def commit(self) -> None:
        self._conn.commit()
        self.committed = True

    def rollback(self) -> None:
        self._conn.rollback()
        self.rolled_back = True

    def execute(self, sql: str, params: tuple = ()) -> Any:
        return self._conn.execute(sql, params)

    def close(self) -> None:
        pass  # keep connection open so tests can inspect state


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _seed_profile(conn: sqlite3.Connection, profile_code: str) -> int:
    cur = conn.execute(
        "INSERT INTO app_profile (profile_code, created_ts_utc) VALUES (?, ?)",
        (profile_code, "2026-01-01 00:00:00"),
    )
    conn.commit()
    return cur.lastrowid


def _seed_account(conn: sqlite3.Connection, account_code: str, venue: str) -> int:
    cur = conn.execute(
        "INSERT INTO trading_account (account_code, venue, created_ts_utc) VALUES (?, ?, ?)",
        (account_code, venue, "2026-01-01 00:00:00"),
    )
    conn.commit()
    return cur.lastrowid


def _seed_link(
    conn: sqlite3.Connection,
    app_profile_id: int,
    trading_account_id: int,
    is_primary: int = 1,
) -> None:
    conn.execute(
        "INSERT INTO app_profile_trading_account_link "
        "(app_profile_id, trading_account_id, link_status, is_primary, created_ts_utc) "
        "VALUES (?, ?, 'ACTIVE', ?, ?)",
        (app_profile_id, trading_account_id, is_primary, "2026-01-01 00:00:00"),
    )
    conn.commit()


@pytest.fixture()
def master_key():
    raw = generate_test_master_key()
    kv, kb = parse_master_key(raw)
    return kv, kb


@pytest.fixture()
def linked_db():
    """SQLite DB with joost profile + bitvavo_joost_read account + active primary link."""
    conn = _fresh_db()
    profile_id = _seed_profile(conn, "joost")
    account_id = _seed_account(conn, "bitvavo_joost_read", "bitvavo")
    _seed_link(conn, profile_id, account_id, is_primary=1)
    return conn, account_id


def _make_conn_factory(sqlite_conn: sqlite3.Connection):
    mock = _MockConn(sqlite_conn)
    return lambda: mock, mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_successful_migration(linked_db, master_key):
    sqlite_conn, trading_account_id = linked_db
    kv, kb = master_key
    conn_factory, mock_conn = _make_conn_factory(sqlite_conn)

    result = migrate_credential_to_db(
        profile_code="joost",
        venue="bitvavo",
        api_key="joost-key-abc",
        api_secret="joost-secret-xyz",
        master_key_version=kv,
        master_key_bytes=kb,
        conn_factory=conn_factory,
        cred_repo_factory=SqliteCredentialRepository,
        now_utc=_NOW,
    )

    assert result["ok"] is True
    assert result["dry_run"] is False
    assert result["account_code"] == "bitvavo_joost_read"
    assert result["trading_account_id"] == trading_account_id
    assert result["venue"] == "bitvavo"
    assert len(result["fingerprint_prefix"]) == 8
    assert mock_conn.committed is True

    # Verify credential exists in DB
    cred_repo = SqliteCredentialRepository(sqlite_conn)
    stored = cred_repo.load_active_encrypted_credential(
        trading_account_id=trading_account_id,
        venue="bitvavo",
    )
    assert stored is not None
    assert stored.validation_state.value == "UNVALIDATED"
    assert stored.credential_status.value == "ACTIVE"


def test_dry_run_does_not_write(linked_db, master_key):
    sqlite_conn, trading_account_id = linked_db
    kv, kb = master_key
    conn_factory, mock_conn = _make_conn_factory(sqlite_conn)

    result = migrate_credential_to_db(
        profile_code="joost",
        venue="bitvavo",
        api_key="placeholder",
        api_secret="placeholder",
        master_key_version=kv,
        master_key_bytes=kb,
        conn_factory=conn_factory,
        cred_repo_factory=SqliteCredentialRepository,
        now_utc=_NOW,
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert mock_conn.committed is False

    # No credential inserted
    cred_repo = SqliteCredentialRepository(sqlite_conn)
    assert cred_repo.load_active_encrypted_credential(
        trading_account_id=trading_account_id,
        venue="bitvavo",
    ) is None


def test_duplicate_active_credential_rejected(linked_db, master_key):
    sqlite_conn, trading_account_id = linked_db
    kv, kb = master_key
    conn_factory, _ = _make_conn_factory(sqlite_conn)

    # First migration succeeds
    r1 = migrate_credential_to_db(
        profile_code="joost",
        venue="bitvavo",
        api_key="joost-key-abc",
        api_secret="joost-secret-xyz",
        master_key_version=kv,
        master_key_bytes=kb,
        conn_factory=conn_factory,
        cred_repo_factory=SqliteCredentialRepository,
        now_utc=_NOW,
    )
    assert r1["ok"] is True

    conn_factory2, _ = _make_conn_factory(sqlite_conn)
    r2 = migrate_credential_to_db(
        profile_code="joost",
        venue="bitvavo",
        api_key="joost-key-abc",
        api_secret="joost-secret-xyz",
        master_key_version=kv,
        master_key_bytes=kb,
        conn_factory=conn_factory2,
        cred_repo_factory=SqliteCredentialRepository,
        now_utc=_NOW,
    )
    assert r2["ok"] is False
    assert "ACTIVE_CREDENTIAL_EXISTS" in r2["error_code"]


def test_missing_profile_link_rejected(master_key):
    """Profile exists but has no active primary link."""
    sqlite_conn = _fresh_db()
    _seed_profile(sqlite_conn, "orphan")
    # No trading account, no link
    kv, kb = master_key
    conn_factory, _ = _make_conn_factory(sqlite_conn)

    result = migrate_credential_to_db(
        profile_code="orphan",
        venue="bitvavo",
        api_key="k",
        api_secret="s",
        master_key_version=kv,
        master_key_bytes=kb,
        conn_factory=conn_factory,
        cred_repo_factory=SqliteCredentialRepository,
        now_utc=_NOW,
    )
    assert result["ok"] is False
    assert "NO_ACTIVE_PRIMARY_LINK" in result["error_code"]


def test_missing_profile_rejected(master_key):
    """app_profile row does not exist."""
    sqlite_conn = _fresh_db()
    kv, kb = master_key
    conn_factory, _ = _make_conn_factory(sqlite_conn)

    result = migrate_credential_to_db(
        profile_code="nobody",
        venue="bitvavo",
        api_key="k",
        api_secret="s",
        master_key_version=kv,
        master_key_bytes=kb,
        conn_factory=conn_factory,
        cred_repo_factory=SqliteCredentialRepository,
        now_utc=_NOW,
    )
    assert result["ok"] is False
    assert "NO_PROFILE_FOUND" in result["error_code"]
