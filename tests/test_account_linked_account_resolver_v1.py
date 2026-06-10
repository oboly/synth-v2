"""
Regression tests for linked_account_resolver_v1.

Verifies:
  - Hugo resolves to hugo-bitvavo, NOT bitvavo_hugo_read
  - Joost resolves correctly
  - NO_PROFILE_FOUND fails closed
  - NO_ACTIVE_PRIMARY_LINK fails closed
  - AMBIGUOUS_PRIMARY_LINK fails closed
  - ACCOUNT_VENUE_MISMATCH fails closed
  - ACCOUNT_DISABLED fails closed
  - LIVE_TRADING_ENABLED fails closed
  - LinkedAccountIdentity fields are correct

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

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account.linked_account_resolver_v1 import (
    LinkedAccountIdentity,
    resolve_primary_linked_account,
)


# ---------------------------------------------------------------------------
# SQLite test fixtures
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_profile (
    app_profile_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_code     TEXT NOT NULL UNIQUE,
    display_timezone TEXT NOT NULL DEFAULT 'UTC',
    onboarding_state TEXT NOT NULL DEFAULT 'NO_EXCHANGE_ACCOUNT_CONNECTED',
    created_ts_utc   TEXT NOT NULL
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
"""

_NOW = "2026-06-09 12:00:00"


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _seed_profile(conn: sqlite3.Connection, *, profile_code: str) -> int:
    cur = conn.execute(
        "INSERT INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, 'UTC', 'ACTIVE', ?)",
        (profile_code, _NOW),
    )
    return int(cur.lastrowid)


def _seed_account(
    conn: sqlite3.Connection,
    *,
    account_code: str,
    venue: str = "bitvavo",
    enabled: int = 1,
    live: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO trading_account (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc)"
        " VALUES (?, ?, 'paper', ?, ?, ?)",
        (account_code, venue, enabled, live, _NOW),
    )
    return int(cur.lastrowid)


def _seed_link(
    conn: sqlite3.Connection,
    *,
    app_profile_id: int,
    trading_account_id: int,
    status: str = "ACTIVE",
    is_primary: int = 1,
) -> None:
    conn.execute(
        "INSERT INTO app_profile_trading_account_link"
        " (app_profile_id, trading_account_id, link_status, is_primary, created_ts_utc)"
        " VALUES (?, ?, ?, ?, ?)",
        (app_profile_id, trading_account_id, status, is_primary, _NOW),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_hugo_resolves_to_hugo_bitvavo() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo", venue="bitvavo")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)

    result = resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")

    assert result.account_code == "hugo-bitvavo"
    assert result.trading_account_id == ta_id
    assert result.profile_code == "hugo"
    assert result.venue == "bitvavo"


def test_hugo_account_code_is_not_bitvavo_hugo_read() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo", venue="bitvavo")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)

    result = resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")

    assert result.account_code != "bitvavo_hugo_read", (
        "account_code must come from the DB, not be inferred from the profile name"
    )


def test_joost_resolves_correctly() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="joost")
    ta_id = _seed_account(conn, account_code="joost-bitvavo", venue="bitvavo")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)

    result = resolve_primary_linked_account(conn, profile_code="joost", venue="bitvavo")

    assert result.account_code == "joost-bitvavo"
    assert result.trading_account_id == ta_id


def test_result_is_linked_account_identity() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)

    result = resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")

    assert isinstance(result, LinkedAccountIdentity)


def test_two_profiles_resolve_independently() -> None:
    conn = _fresh_db()
    pid_hugo = _seed_profile(conn, profile_code="hugo")
    pid_joost = _seed_profile(conn, profile_code="joost")
    ta_hugo = _seed_account(conn, account_code="hugo-bitvavo")
    ta_joost = _seed_account(conn, account_code="joost-bitvavo")
    _seed_link(conn, app_profile_id=pid_hugo, trading_account_id=ta_hugo)
    _seed_link(conn, app_profile_id=pid_joost, trading_account_id=ta_joost)

    hugo = resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
    joost = resolve_primary_linked_account(conn, profile_code="joost", venue="bitvavo")

    assert hugo.account_code == "hugo-bitvavo"
    assert joost.account_code == "joost-bitvavo"
    assert hugo.trading_account_id != joost.trading_account_id


# ---------------------------------------------------------------------------
# Fail-closed: NO_PROFILE_FOUND
# ---------------------------------------------------------------------------

def test_missing_profile_fails_closed() -> None:
    conn = _fresh_db()
    try:
        resolve_primary_linked_account(conn, profile_code="nobody", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "NO_PROFILE_FOUND" in str(exc)


# ---------------------------------------------------------------------------
# Fail-closed: NO_ACTIVE_PRIMARY_LINK
# ---------------------------------------------------------------------------

def test_no_link_fails_closed() -> None:
    conn = _fresh_db()
    _seed_profile(conn, profile_code="hugo")
    try:
        resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "NO_ACTIVE_PRIMARY_LINK" in str(exc)


def test_inactive_link_fails_closed() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id, status="REVOKED")
    try:
        resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "NO_ACTIVE_PRIMARY_LINK" in str(exc)


def test_non_primary_link_fails_closed() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id, is_primary=0)
    try:
        resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "NO_ACTIVE_PRIMARY_LINK" in str(exc)


# ---------------------------------------------------------------------------
# Fail-closed: AMBIGUOUS_PRIMARY_LINK
# ---------------------------------------------------------------------------

def test_two_primary_links_fails_closed() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta1 = _seed_account(conn, account_code="hugo-bitvavo")
    ta2 = _seed_account(conn, account_code="hugo-bitvavo-2")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta1)
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta2)
    try:
        resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "AMBIGUOUS_PRIMARY_LINK" in str(exc)


# ---------------------------------------------------------------------------
# Fail-closed: ACCOUNT_VENUE_MISMATCH
# ---------------------------------------------------------------------------

def test_venue_mismatch_fails_closed() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-kraken", venue="kraken")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)
    try:
        resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "ACCOUNT_VENUE_MISMATCH" in str(exc)


# ---------------------------------------------------------------------------
# Fail-closed: ACCOUNT_DISABLED
# ---------------------------------------------------------------------------

def test_disabled_account_fails_closed() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo", enabled=0)
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)
    try:
        resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "ACCOUNT_DISABLED" in str(exc)


# ---------------------------------------------------------------------------
# Fail-closed: LIVE_TRADING_ENABLED
# ---------------------------------------------------------------------------

def test_live_trading_enabled_fails_closed() -> None:
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo", live=1)
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)
    try:
        resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "LIVE_TRADING_ENABLED" in str(exc)


# ---------------------------------------------------------------------------
# No fallback to inferred names
# ---------------------------------------------------------------------------

def test_resolver_never_infers_account_code_from_profile_name() -> None:
    """account_code must always come from the DB, never from bitvavo_<profile>_read."""
    conn = _fresh_db()
    pid = _seed_profile(conn, profile_code="hugo")
    ta_id = _seed_account(conn, account_code="hugo-bitvavo")
    _seed_link(conn, app_profile_id=pid, trading_account_id=ta_id)

    result = resolve_primary_linked_account(conn, profile_code="hugo", venue="bitvavo")

    # The old inferred name pattern must never appear
    assert "bitvavo_hugo_read" not in result.account_code
    assert result.account_code == "hugo-bitvavo"


if __name__ == "__main__":
    tests = [
        test_hugo_resolves_to_hugo_bitvavo,
        test_hugo_account_code_is_not_bitvavo_hugo_read,
        test_joost_resolves_correctly,
        test_result_is_linked_account_identity,
        test_two_profiles_resolve_independently,
        test_missing_profile_fails_closed,
        test_no_link_fails_closed,
        test_inactive_link_fails_closed,
        test_non_primary_link_fails_closed,
        test_two_primary_links_fails_closed,
        test_venue_mismatch_fails_closed,
        test_disabled_account_fails_closed,
        test_live_trading_enabled_fails_closed,
        test_resolver_never_infers_account_code_from_profile_name,
    ]
    for t in tests:
        t()
    print("ok")
