from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest


MIGRATION_PATH = Path("db/migrations/20260603_account_asset_settings_v1.sql")
TEMP_DB_PREFIX = "synth_account_asset_settings_v1_tmp"


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement.endswith(";"):
                statement = statement[:-1]
            if statement:
                statements.append(statement)
            buffer = []
    trailing = "\n".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _temp_db_name() -> str:
    return f"{TEMP_DB_PREFIX}_{os.getpid()}"


def test_migration_declares_required_settings_columns() -> None:
    sql = _sql()
    assert "ADD COLUMN IF NOT EXISTS disabled_reason VARCHAR(64) DEFAULT NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS first_seen_at_utc DATETIME DEFAULT NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS last_seen_at_utc DATETIME DEFAULT NULL" in sql


def test_backfill_explicitly_preserves_foundation_updated_ts() -> None:
    sql = _sql()
    assert "last_seen_at_utc = COALESCE(last_seen_at_utc, updated_ts)" in sql
    assert "updated_ts = updated_ts" in sql


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_migration_executes_idempotently_and_preserves_updated_ts() -> None:
    from pymysql.err import OperationalError

    from src.common.db import get_connection

    temp_db_name = _temp_db_name()
    schema_created = False
    try:
        admin_conn = get_connection(database="information_schema")
        try:
            with admin_conn.cursor() as cur:
                try:
                    cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
                    cur.execute(
                        f"CREATE DATABASE `{temp_db_name}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                except OperationalError as exc:
                    if exc.args and exc.args[0] == 1044:
                        pytest.skip(
                            "Configured DB user lacks CREATE/DROP DATABASE privilege for disposable schema validation."
                        )
                    raise
            admin_conn.commit()
            schema_created = True
        finally:
            admin_conn.close()

        conn = get_connection(database=temp_db_name)
        try:
            created_ts = datetime(2026, 6, 3, 10, 0, 0)
            original_updated_ts = datetime(2026, 7, 4, 12, 34, 56)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE account_asset (
                        account_asset_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        disabled_until_utc DATETIME DEFAULT NULL,
                        source VARCHAR(32) NOT NULL DEFAULT 'MANUAL_ADD',
                        created_ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    INSERT INTO account_asset (
                        disabled_until_utc,
                        source,
                        created_ts,
                        updated_ts
                    ) VALUES (NULL, 'WALLET_DISCOVERY', %s, %s)
                    """,
                    (created_ts, original_updated_ts),
                )
                for statement in _split_sql_statements(_sql()):
                    cur.execute(statement)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COLUMN_NAME
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s
                      AND TABLE_NAME = 'account_asset'
                      AND COLUMN_NAME IN (
                          'disabled_reason',
                          'first_seen_at_utc',
                          'last_seen_at_utc'
                      )
                    ORDER BY COLUMN_NAME
                    """,
                    (temp_db_name,),
                )
                assert [row["COLUMN_NAME"] for row in cur.fetchall()] == [
                    "disabled_reason",
                    "first_seen_at_utc",
                    "last_seen_at_utc",
                ]

                cur.execute(
                    """
                    SELECT
                        source,
                        created_ts,
                        updated_ts,
                        disabled_reason,
                        first_seen_at_utc,
                        last_seen_at_utc
                    FROM account_asset
                    WHERE account_asset_id = 1
                    """
                )
                row = cur.fetchone()
                assert row is not None
                assert row["source"] == "WALLET_DISCOVERY"
                assert row["disabled_reason"] is None
                assert row["first_seen_at_utc"] == created_ts
                assert row["last_seen_at_utc"] == original_updated_ts
                assert row["updated_ts"] == original_updated_ts

                for statement in _split_sql_statements(_sql()):
                    cur.execute(statement)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT first_seen_at_utc, last_seen_at_utc, updated_ts
                    FROM account_asset
                    WHERE account_asset_id = 1
                    """
                )
                row = cur.fetchone()
                assert row is not None
                assert row["first_seen_at_utc"] == created_ts
                assert row["last_seen_at_utc"] == original_updated_ts
                assert row["updated_ts"] == original_updated_ts
        finally:
            conn.close()
    finally:
        if schema_created:
            cleanup_conn = get_connection(database="information_schema")
            try:
                with cleanup_conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
                cleanup_conn.commit()
            finally:
                cleanup_conn.close()
