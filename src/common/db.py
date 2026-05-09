from __future__ import annotations

"""
Synth v2 - canonical MariaDB connection helper.

Boundary:
- Centralizes DB connection settings.
- Forces the project-wide charset/collation for every normal Synth runtime connection.
- Prevents MariaDB client/version defaults from leaking utf8mb4_uca1400_* or other
  incompatible collations into string literals, views, temp expressions, or queries.
- Preserves the legacy db_cursor context manager contract used by older modules.

Canonical text standard:
- charset: utf8mb4
- collation: utf8mb4_unicode_ci
"""

import os
from contextlib import contextmanager
from typing import Iterator

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor


load_dotenv()


DEFAULT_CHARSET = "utf8mb4"
DEFAULT_COLLATION = "utf8mb4_unicode_ci"
DEFAULT_DATABASE = "synth"


def _env_first(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def _env_int(*names: str, default: int) -> int:
    value = _env_first(*names, default=str(default))
    try:
        return int(str(value))
    except ValueError as exc:
        joined = ", ".join(names)
        raise ValueError(f"Invalid integer DB env value for one of: {joined}") from exc


def _db_charset() -> str:
    return _env_first("DB_CHARSET", "MYSQL_CHARSET", default=DEFAULT_CHARSET) or DEFAULT_CHARSET


def _db_collation() -> str:
    return (
        _env_first("DB_COLLATION", "MYSQL_COLLATION", default=DEFAULT_COLLATION)
        or DEFAULT_COLLATION
    )


def get_db_connection():
    return get_connection()


def get_connection(database: str | None = None):
    charset = _db_charset()
    collation = _db_collation()

    return pymysql.connect(
        host=_env_first("DB_HOST", "MYSQL_HOST", default="localhost"),
        port=_env_int("DB_PORT", "MYSQL_PORT", default=3306),
        user=_env_first("DB_USER", "MYSQL_USER", default="synth"),
        password=_env_first("DB_PASSWORD", "MYSQL_PASSWORD", default=""),
        database=database
        or _env_first("DB_NAME", "MYSQL_DATABASE", default=DEFAULT_DATABASE),
        charset=charset,
        init_command=f"SET NAMES {charset} COLLATE {collation}",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=_env_int("DB_CONNECT_TIMEOUT", default=10),
        read_timeout=_env_int("DB_READ_TIMEOUT", default=60),
        write_timeout=_env_int("DB_WRITE_TIMEOUT", default=60),
    )


@contextmanager
def db_cursor(commit: bool = False, database: str | None = None) -> Iterator[tuple[object, object]]:
    """
    Legacy-compatible cursor context manager.

    Important:
    - Uses the canonical get_connection() path, so charset/collation protection stays active.
    - commit=False rolls back after successful read-style usage, matching the old helper.
    - commit=True commits after successful write-style usage.
    """
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            yield conn, cur

        if commit:
            conn.commit()
        else:
            conn.rollback()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def test_connection(database: str | None = None) -> dict[str, object]:
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    DATABASE() AS db_name,
                    USER() AS user_name,
                    @@hostname AS db_host,
                    @@datadir AS datadir,
                    @@character_set_connection AS character_set_connection,
                    @@collation_connection AS collation_connection
                """
            )
            row = cur.fetchone()
            if not isinstance(row, dict):
                raise TypeError("Expected dict cursor row")
            return row
    finally:
        conn.close()
