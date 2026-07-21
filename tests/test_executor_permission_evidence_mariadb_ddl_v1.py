from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import pytest


MIGRATION_PATH = Path("db/migrations/20260721_executor_permission_evidence_v1.sql")
TEMP_DB_PREFIX = "synth_epe_ddl_tmp"
DDL_TEST_OPT_IN_ENV = "SYNTH_RUN_DISPOSABLE_MARIADB_DDL_TESTS"


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


def _apply_statements(conn: object, statements: Iterable[str]) -> None:
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


def _temp_db_name() -> str:
    return f"{TEMP_DB_PREFIX}_{os.getpid()}"


def _create_database(name: str) -> None:
    from pymysql.err import OperationalError
    from src.common.db import get_connection

    conn = get_connection(database="information_schema")
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
                cur.execute(
                    f"CREATE DATABASE `{name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            except OperationalError as exc:
                if exc.args and exc.args[0] == 1044:
                    pytest.skip("Configured DB user lacks disposable schema privileges.")
                raise
        conn.commit()
    finally:
        conn.close()


def _drop_database(name: str) -> None:
    from src.common.db import get_connection

    conn = get_connection(database="information_schema")
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        conn.commit()
    finally:
        conn.close()


def _create_prerequisites(conn: object) -> None:
    _apply_statements(
        conn,
        [
            """
            CREATE TABLE trading_account (
                trading_account_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                account_code VARCHAR(63) NOT NULL,
                venue VARCHAR(32) NOT NULL,
                account_mode VARCHAR(32) NOT NULL DEFAULT 'paper',
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                live_trading_enabled TINYINT(1) NOT NULL DEFAULT 0,
                created_ts_utc DATETIME(6) NOT NULL,
                PRIMARY KEY (trading_account_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE decision_gate_audit_log (
                decision_gate_audit_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                trading_account_id BIGINT UNSIGNED NOT NULL,
                venue VARCHAR(32) NOT NULL,
                asset_id BIGINT UNSIGNED NOT NULL,
                interval_code VARCHAR(16) NOT NULL,
                execution_mode VARCHAR(32) NOT NULL,
                permission_state VARCHAR(64) NULL,
                decision_state VARCHAR(64) NULL,
                asof_ts_utc DATETIME(6) NOT NULL,
                created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                PRIMARY KEY (decision_gate_audit_log_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE execution_plan (
                execution_plan_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                account_id BIGINT UNSIGNED NOT NULL,
                asset_id BIGINT UNSIGNED NOT NULL,
                sleeve_code VARCHAR(32) NOT NULL,
                venue VARCHAR(32) NOT NULL,
                side VARCHAR(16) NOT NULL,
                desired_action VARCHAR(64) NOT NULL,
                execution_mode VARCHAR(32) NOT NULL,
                plan_ts_utc DATETIME(6) NOT NULL,
                valid_until_ts_utc DATETIME(6) NULL,
                plan_state VARCHAR(32) NOT NULL,
                PRIMARY KEY (execution_plan_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ],
    )


def test_executor_permission_evidence_migration_applies_to_disposable_mariadb() -> None:
    from src.common.db import get_connection

    if os.getenv(DDL_TEST_OPT_IN_ENV) != "1":
        pytest.skip(
            f"Set {DDL_TEST_OPT_IN_ENV}=1 only against a disposable MariaDB instance."
        )

    db_name = _temp_db_name()
    _create_database(db_name)
    try:
        conn = get_connection(database=db_name)
        try:
            _create_prerequisites(conn)
            _apply_statements(
                conn,
                _split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8")),
            )
            with conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM execution_permission_evidence")
                columns = {str(row["Field"]) for row in cur.fetchall()}
                cur.execute("SHOW INDEX FROM execution_permission_evidence")
                indexes = {str(row["Key_name"]) for row in cur.fetchall()}
        finally:
            conn.close()

        assert "execution_permission_evidence_id" in columns
        assert "execution_plan_id" in columns
        assert "trading_account_id" in columns
        assert "valid_until_ts_utc" in columns
        assert "ix_epe_plan_state_v1" in indexes
    finally:
        _drop_database(db_name)
