"""
account_repository_v1 — trading_account and profile link persistence.

Caller-owned connection. No commits.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any, Mapping


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trading_account (
    trading_account_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    account_code         TEXT NOT NULL UNIQUE,
    venue                TEXT NOT NULL,
    account_mode         TEXT NOT NULL DEFAULT 'paper',
    enabled              INTEGER NOT NULL DEFAULT 1,
    live_trading_enabled INTEGER NOT NULL DEFAULT 0,
    created_ts_utc       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_profile (
    app_profile_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_code     TEXT NOT NULL UNIQUE,
    display_timezone TEXT NOT NULL DEFAULT 'UTC',
    onboarding_state TEXT NOT NULL DEFAULT 'NO_EXCHANGE_ACCOUNT_CONNECTED',
    created_ts_utc   TEXT NOT NULL,
    activated_ts_utc TEXT NULL
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


class SqliteAccountRepository:
    """
    SQLite account repository for tests.
    Caller-owned connection. No commits.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def create_schema(self) -> None:
        self._conn.executescript(_SCHEMA)

    def find_active_primary_link(self, app_profile_id: int) -> Mapping[str, object] | None:
        rows = self._conn.execute(
            """
            SELECT link_id, app_profile_id, trading_account_id, link_status, is_primary
            FROM app_profile_trading_account_link
            WHERE app_profile_id = ?
              AND link_status = 'ACTIVE'
              AND is_primary = 1
            LIMIT 2
            """,
            (app_profile_id,),
        ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise RuntimeError(f"AMBIGUOUS_PRIMARY_LINK app_profile_id={app_profile_id}")
        return rows[0]

    def create_trading_account(
        self,
        *,
        account_code: str,
        venue: str,
        account_mode: str,
        enabled: int,
        live_trading_enabled: int,
        created_ts_utc: datetime,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO trading_account
              (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (account_code, venue, account_mode, enabled, live_trading_enabled, _utc_text(created_ts_utc)),
        )
        return int(cur.lastrowid)

    def create_profile_link(
        self,
        *,
        app_profile_id: int,
        trading_account_id: int,
        is_primary: bool,
        created_ts_utc: datetime,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO app_profile_trading_account_link
              (app_profile_id, trading_account_id, link_status, is_primary, created_ts_utc)
            VALUES (?, ?, 'ACTIVE', ?, ?)
            """,
            (app_profile_id, trading_account_id, 1 if is_primary else 0, _utc_text(created_ts_utc)),
        )
        return int(cur.lastrowid)

    def update_onboarding_state(self, *, app_profile_id: int, onboarding_state: str) -> None:
        self._conn.execute(
            "UPDATE app_profile SET onboarding_state = ? WHERE app_profile_id = ?",
            (onboarding_state, app_profile_id),
        )


class MariaDbAccountRepository:
    """
    MariaDB account repository for production.
    Caller-owned connection. No commits.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _cursor(self) -> Any:
        try:
            import pymysql.cursors
            return self._conn.cursor(pymysql.cursors.DictCursor)
        except ImportError:
            return self._conn.cursor()

    def find_active_primary_link(self, app_profile_id: int) -> Mapping[str, object] | None:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT link_id, app_profile_id, trading_account_id, link_status, is_primary
                FROM app_profile_trading_account_link
                WHERE app_profile_id = %s
                  AND link_status = 'ACTIVE'
                  AND is_primary = 1
                LIMIT 2
                """,
                (app_profile_id,),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise RuntimeError(f"AMBIGUOUS_PRIMARY_LINK app_profile_id={app_profile_id}")
        return rows[0]

    def create_trading_account(
        self,
        *,
        account_code: str,
        venue: str,
        account_mode: str,
        enabled: int,
        live_trading_enabled: int,
        created_ts_utc: datetime,
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO trading_account
                  (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (account_code, venue, account_mode, enabled, live_trading_enabled, _utc_text(created_ts_utc)),
            )
            return int(cur.lastrowid)

    def create_profile_link(
        self,
        *,
        app_profile_id: int,
        trading_account_id: int,
        is_primary: bool,
        created_ts_utc: datetime,
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_profile_trading_account_link
                  (app_profile_id, trading_account_id, link_status, is_primary, created_ts_utc)
                VALUES (%s, %s, 'ACTIVE', %s, %s)
                """,
                (app_profile_id, trading_account_id, 1 if is_primary else 0, _utc_text(created_ts_utc)),
            )
            return int(cur.lastrowid)

    def update_onboarding_state(self, *, app_profile_id: int, onboarding_state: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE app_profile SET onboarding_state = %s WHERE app_profile_id = %s",
                (onboarding_state, app_profile_id),
            )
