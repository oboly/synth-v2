"""
operator_intent.operator_intent_repository_v1 — operator_intent /
operator_intent_revision persistence.

Caller-owned connection. No commits. Mirrors the dual Sqlite/MariaDb
repository pattern used by src.account_provisioning.account_repository_v1.

The Sqlite repository additionally mirrors the minimal shape of the
canonical identity tables (app_user, app_profile, app_user_profile_access,
app_profile_trading_account_link, trading_account) so this package's tests
are self-contained, exactly as account_repository_v1 already does for its
own tests. Production identity tables remain owned by their existing
migrations; this module never redefines them for MariaDB.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping, Sequence


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def _normalize_ts_field(value: Any) -> str | None:
    """Accepts a datetime (from a service call) or an already-stringified
    value read back from a row (e.g. a field the service is passing through
    unchanged) and returns the stored TEXT form, or None if unset."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc_text(value)
    return str(value)


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    app_user_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    email_normalized TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS app_profile (
    app_profile_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_code     TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS app_user_profile_access (
    app_user_profile_access_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_user_id                INTEGER NOT NULL,
    app_profile_id              INTEGER NOT NULL,
    access_role                 TEXT NOT NULL DEFAULT 'OWNER',
    UNIQUE (app_user_id, app_profile_id)
);
CREATE TABLE IF NOT EXISTS trading_account (
    trading_account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_code        TEXT NOT NULL UNIQUE,
    venue                TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_profile_trading_account_link (
    link_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    app_profile_id     INTEGER NOT NULL,
    trading_account_id INTEGER NOT NULL,
    link_status        TEXT NOT NULL DEFAULT 'ACTIVE',
    is_primary         INTEGER NOT NULL DEFAULT 0,
    UNIQUE (app_profile_id, trading_account_id)
);
CREATE TABLE IF NOT EXISTS operator_intent (
    operator_intent_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id       INTEGER NOT NULL,
    venue                    TEXT NOT NULL,
    canonical_market         TEXT NOT NULL,
    intent_type              TEXT NOT NULL,
    priority                 INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL,
    reason                   TEXT NULL,
    source                   TEXT NOT NULL DEFAULT 'OPERATOR_MANUAL',
    created_by_app_user_id    INTEGER NOT NULL,
    created_by_app_profile_id INTEGER NOT NULL,
    created_ts_utc            TEXT NOT NULL,
    updated_by_app_user_id    INTEGER NOT NULL,
    updated_by_app_profile_id INTEGER NOT NULL,
    updated_ts_utc            TEXT NOT NULL,
    expires_ts_utc            TEXT NULL,
    version                  INTEGER NOT NULL DEFAULT 1,
    supersedes_intent_id     INTEGER NULL,
    superseded_by_intent_id  INTEGER NULL
);
CREATE TABLE IF NOT EXISTS operator_intent_revision (
    operator_intent_revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_intent_id          INTEGER NOT NULL,
    revision_version             INTEGER NOT NULL,
    event_type                   TEXT NOT NULL,
    trading_account_id           INTEGER NOT NULL,
    venue                        TEXT NOT NULL,
    canonical_market             TEXT NOT NULL,
    intent_type                  TEXT NOT NULL,
    priority                     INTEGER NOT NULL,
    status                       TEXT NOT NULL,
    reason                       TEXT NULL,
    source                       TEXT NOT NULL,
    actor_app_user_id            INTEGER NOT NULL,
    actor_app_profile_id         INTEGER NOT NULL,
    event_ts_utc                  TEXT NOT NULL,
    expires_ts_utc                TEXT NULL,
    UNIQUE (operator_intent_id, revision_version)
);
"""

_OPEN_STATUSES_SQL = (
    "'ACTIVE', 'WAITING_FOR_MARKET_CONTEXT', 'WAITING_FOR_PERMISSION', "
    "'READY_FOR_PLANNING', 'PLANNED_PREVIEW_AVAILABLE', 'BLOCKED'"
)


class SqliteOperatorIntentRepository:
    """SQLite operator_intent repository for tests. Caller-owned connection, no commits."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def create_schema(self) -> None:
        self._conn.executescript(_SQLITE_SCHEMA)

    # -- identity/authorization lookups (mirrors production tables) --------

    def find_user_profile_access(self, *, app_user_id: int, app_profile_id: int) -> Mapping[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM app_user_profile_access WHERE app_user_id = ? AND app_profile_id = ?",
            (app_user_id, app_profile_id),
        ).fetchone()
        return row

    def find_active_account_link(self, *, app_profile_id: int, trading_account_id: int) -> Mapping[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT * FROM app_profile_trading_account_link
            WHERE app_profile_id = ? AND trading_account_id = ? AND link_status = 'ACTIVE'
            """,
            (app_profile_id, trading_account_id),
        ).fetchone()
        return row

    def get_trading_account(self, *, trading_account_id: int) -> Mapping[str, Any] | None:
        return self._conn.execute(
            "SELECT * FROM trading_account WHERE trading_account_id = ?",
            (trading_account_id,),
        ).fetchone()

    # -- operator_intent current state --------------------------------------

    def find_open_intent_for_scope(
        self, *, trading_account_id: int, venue: str, canonical_market: str, intent_type: str
    ) -> Mapping[str, Any] | None:
        return self._conn.execute(
            f"""
            SELECT * FROM operator_intent
            WHERE trading_account_id = ? AND venue = ? AND canonical_market = ? AND intent_type = ?
              AND status IN ({_OPEN_STATUSES_SQL})
            """,
            (trading_account_id, venue, canonical_market, intent_type),
        ).fetchone()

    def get_intent(self, *, operator_intent_id: int) -> Mapping[str, Any] | None:
        return self._conn.execute(
            "SELECT * FROM operator_intent WHERE operator_intent_id = ?",
            (operator_intent_id,),
        ).fetchone()

    def insert_intent(self, **fields: Any) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO operator_intent (
                trading_account_id, venue, canonical_market, intent_type, priority, status,
                reason, source, created_by_app_user_id, created_by_app_profile_id, created_ts_utc,
                updated_by_app_user_id, updated_by_app_profile_id, updated_ts_utc, expires_ts_utc, version,
                supersedes_intent_id, superseded_by_intent_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["trading_account_id"],
                fields["venue"],
                fields["canonical_market"],
                fields["intent_type"],
                fields["priority"],
                fields["status"],
                fields.get("reason"),
                fields["source"],
                fields["created_by_app_user_id"],
                fields["created_by_app_profile_id"],
                _utc_text(fields["created_ts_utc"]),
                fields["updated_by_app_user_id"],
                fields["updated_by_app_profile_id"],
                _utc_text(fields["updated_ts_utc"]),
                _normalize_ts_field(fields.get("expires_ts_utc")),
                fields.get("version", 1),
                fields.get("supersedes_intent_id"),
                fields.get("superseded_by_intent_id"),
            ),
        )
        return int(cur.lastrowid)

    def update_intent_versioned(
        self, *, operator_intent_id: int, expected_version: int, new_version: int, **fields: Any
    ) -> int:
        """UPDATE guarded by expected_version. Returns rows affected (0 = conflict)."""
        set_fields = dict(fields)
        set_fields["version"] = new_version
        columns = list(set_fields.keys())
        assignments = ", ".join(f"{col} = ?" for col in columns)
        values: list[Any] = []
        for col in columns:
            value = set_fields[col]
            if col in {"updated_ts_utc", "expires_ts_utc"}:
                values.append(_normalize_ts_field(value))
            else:
                values.append(value)
        cur = self._conn.execute(
            f"""
            UPDATE operator_intent SET {assignments}
            WHERE operator_intent_id = ? AND version = ?
            """,
            (*values, operator_intent_id, expected_version),
        )
        return int(cur.rowcount)

    def link_superseded_by(self, *, operator_intent_id: int, superseded_by_intent_id: int) -> None:
        self._conn.execute(
            "UPDATE operator_intent SET superseded_by_intent_id = ? WHERE operator_intent_id = ?",
            (superseded_by_intent_id, operator_intent_id),
        )

    def list_open_intents_for_account(
        self,
        *,
        trading_account_id: int,
        venue: str | None = None,
        canonical_market: str | None = None,
        intent_type: str | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """The 'current intents' read model: OPEN_STATUSES only. Terminal
        rows (CANCELLED / EXPIRED / SUPERSEDED) never leak through here —
        use get_intent(operator_intent_id=...) or
        list_revisions_for_intent(...) for terminal/historical lookups."""
        clauses = ["trading_account_id = ?", f"status IN ({_OPEN_STATUSES_SQL})"]
        params: list[Any] = [trading_account_id]
        if venue is not None:
            clauses.append("venue = ?")
            params.append(venue)
        if canonical_market is not None:
            clauses.append("canonical_market = ?")
            params.append(canonical_market)
        if intent_type is not None:
            clauses.append("intent_type = ?")
            params.append(intent_type)
        where = " AND ".join(clauses)
        return self._conn.execute(
            f"SELECT * FROM operator_intent WHERE {where} ORDER BY operator_intent_id",
            params,
        ).fetchall()

    def find_expirable_intents(
        self, *, now_ts_utc: datetime, trading_account_id: int | None = None
    ) -> Sequence[Mapping[str, Any]]:
        clauses = [f"status IN ({_OPEN_STATUSES_SQL})", "expires_ts_utc IS NOT NULL", "expires_ts_utc <= ?"]
        params: list[Any] = [_utc_text(now_ts_utc)]
        if trading_account_id is not None:
            clauses.append("trading_account_id = ?")
            params.append(trading_account_id)
        where = " AND ".join(clauses)
        return self._conn.execute(
            f"SELECT * FROM operator_intent WHERE {where} ORDER BY operator_intent_id", params
        ).fetchall()

    # -- operator_intent_revision (append-only) -----------------------------

    def insert_revision(self, **fields: Any) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO operator_intent_revision (
                operator_intent_id, revision_version, event_type, trading_account_id, venue,
                canonical_market, intent_type, priority, status, reason, source,
                actor_app_user_id, actor_app_profile_id, event_ts_utc, expires_ts_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["operator_intent_id"],
                fields["revision_version"],
                fields["event_type"],
                fields["trading_account_id"],
                fields["venue"],
                fields["canonical_market"],
                fields["intent_type"],
                fields["priority"],
                fields["status"],
                fields.get("reason"),
                fields["source"],
                fields["actor_app_user_id"],
                fields["actor_app_profile_id"],
                _utc_text(fields["event_ts_utc"]),
                _normalize_ts_field(fields.get("expires_ts_utc")),
            ),
        )
        return int(cur.lastrowid)

    def list_revisions_for_intent(self, *, operator_intent_id: int) -> Sequence[Mapping[str, Any]]:
        return self._conn.execute(
            """
            SELECT * FROM operator_intent_revision
            WHERE operator_intent_id = ?
            ORDER BY revision_version
            """,
            (operator_intent_id,),
        ).fetchall()


class MariaDbOperatorIntentRepository:
    """MariaDB operator_intent repository for production. Caller-owned connection, no commits."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _cursor(self) -> Any:
        try:
            import pymysql.cursors
            return self._conn.cursor(pymysql.cursors.DictCursor)
        except ImportError:
            return self._conn.cursor()

    def find_user_profile_access(self, *, app_user_id: int, app_profile_id: int) -> Mapping[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM app_user_profile_access WHERE app_user_id = %s AND app_profile_id = %s",
                (app_user_id, app_profile_id),
            )
            return cur.fetchone()

    def find_active_account_link(self, *, app_profile_id: int, trading_account_id: int) -> Mapping[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM app_profile_trading_account_link
                WHERE app_profile_id = %s AND trading_account_id = %s AND link_status = 'ACTIVE'
                """,
                (app_profile_id, trading_account_id),
            )
            return cur.fetchone()

    def get_trading_account(self, *, trading_account_id: int) -> Mapping[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM trading_account WHERE trading_account_id = %s",
                (trading_account_id,),
            )
            return cur.fetchone()

    def find_open_intent_for_scope(
        self, *, trading_account_id: int, venue: str, canonical_market: str, intent_type: str
    ) -> Mapping[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM operator_intent
                WHERE trading_account_id = %s AND venue = %s AND canonical_market = %s AND intent_type = %s
                  AND status IN ({_OPEN_STATUSES_SQL})
                FOR UPDATE
                """,
                (trading_account_id, venue, canonical_market, intent_type),
            )
            return cur.fetchone()

    def get_intent(self, *, operator_intent_id: int) -> Mapping[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM operator_intent WHERE operator_intent_id = %s FOR UPDATE",
                (operator_intent_id,),
            )
            return cur.fetchone()

    def insert_intent(self, **fields: Any) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO operator_intent (
                    trading_account_id, venue, canonical_market, intent_type, priority, status,
                    reason, source, created_by_app_user_id, created_by_app_profile_id, created_ts_utc,
                    updated_by_app_user_id, updated_by_app_profile_id, updated_ts_utc, expires_ts_utc, version,
                    supersedes_intent_id, superseded_by_intent_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fields["trading_account_id"],
                    fields["venue"],
                    fields["canonical_market"],
                    fields["intent_type"],
                    fields["priority"],
                    fields["status"],
                    fields.get("reason"),
                    fields["source"],
                    fields["created_by_app_user_id"],
                    fields["created_by_app_profile_id"],
                    _utc_text(fields["created_ts_utc"]),
                    fields["updated_by_app_user_id"],
                    fields["updated_by_app_profile_id"],
                    _utc_text(fields["updated_ts_utc"]),
                    _normalize_ts_field(fields.get("expires_ts_utc")),
                    fields.get("version", 1),
                    fields.get("supersedes_intent_id"),
                    fields.get("superseded_by_intent_id"),
                ),
            )
            return int(cur.lastrowid)

    def update_intent_versioned(
        self, *, operator_intent_id: int, expected_version: int, new_version: int, **fields: Any
    ) -> int:
        set_fields = dict(fields)
        set_fields["version"] = new_version
        columns = list(set_fields.keys())
        assignments = ", ".join(f"{col} = %s" for col in columns)
        values: list[Any] = []
        for col in columns:
            value = set_fields[col]
            if col == "updated_ts_utc" and isinstance(value, datetime):
                values.append(_utc_text(value))
            elif col == "expires_ts_utc":
                values.append(_utc_text(value) if value else None)
            else:
                values.append(value)
        with self._cursor() as cur:
            cur.execute(
                f"""
                UPDATE operator_intent SET {assignments}
                WHERE operator_intent_id = %s AND version = %s
                """,
                (*values, operator_intent_id, expected_version),
            )
            return int(cur.rowcount)

    def link_superseded_by(self, *, operator_intent_id: int, superseded_by_intent_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE operator_intent SET superseded_by_intent_id = %s WHERE operator_intent_id = %s",
                (superseded_by_intent_id, operator_intent_id),
            )

    def list_open_intents_for_account(
        self,
        *,
        trading_account_id: int,
        venue: str | None = None,
        canonical_market: str | None = None,
        intent_type: str | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """The 'current intents' read model: OPEN_STATUSES only. Terminal
        rows (CANCELLED / EXPIRED / SUPERSEDED) never leak through here —
        use get_intent(operator_intent_id=...) or
        list_revisions_for_intent(...) for terminal/historical lookups."""
        clauses = ["trading_account_id = %s", f"status IN ({_OPEN_STATUSES_SQL})"]
        params: list[Any] = [trading_account_id]
        if venue is not None:
            clauses.append("venue = %s")
            params.append(venue)
        if canonical_market is not None:
            clauses.append("canonical_market = %s")
            params.append(canonical_market)
        if intent_type is not None:
            clauses.append("intent_type = %s")
            params.append(intent_type)
        where = " AND ".join(clauses)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM operator_intent WHERE {where} ORDER BY operator_intent_id", params
            )
            return cur.fetchall()

    def find_expirable_intents(
        self, *, now_ts_utc: datetime, trading_account_id: int | None = None
    ) -> Sequence[Mapping[str, Any]]:
        clauses = [f"status IN ({_OPEN_STATUSES_SQL})", "expires_ts_utc IS NOT NULL", "expires_ts_utc <= %s"]
        params: list[Any] = [_utc_text(now_ts_utc)]
        if trading_account_id is not None:
            clauses.append("trading_account_id = %s")
            params.append(trading_account_id)
        where = " AND ".join(clauses)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM operator_intent WHERE {where} ORDER BY operator_intent_id", params
            )
            return cur.fetchall()

    def insert_revision(self, **fields: Any) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO operator_intent_revision (
                    operator_intent_id, revision_version, event_type, trading_account_id, venue,
                    canonical_market, intent_type, priority, status, reason, source,
                    actor_app_user_id, actor_app_profile_id, event_ts_utc, expires_ts_utc
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fields["operator_intent_id"],
                    fields["revision_version"],
                    fields["event_type"],
                    fields["trading_account_id"],
                    fields["venue"],
                    fields["canonical_market"],
                    fields["intent_type"],
                    fields["priority"],
                    fields["status"],
                    fields.get("reason"),
                    fields["source"],
                    fields["actor_app_user_id"],
                    fields["actor_app_profile_id"],
                    _utc_text(fields["event_ts_utc"]),
                    _normalize_ts_field(fields.get("expires_ts_utc")),
                ),
            )
            return int(cur.lastrowid)

    def list_revisions_for_intent(self, *, operator_intent_id: int) -> Sequence[Mapping[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM operator_intent_revision
                WHERE operator_intent_id = %s
                ORDER BY revision_version
                """,
                (operator_intent_id,),
            )
            return cur.fetchall()
