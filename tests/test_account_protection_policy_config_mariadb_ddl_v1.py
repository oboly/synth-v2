from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest


MIGRATION = Path("db/migrations/20260817_account_protection_policy_config_v1.sql")
DISPOSABLE_OPT_IN = "SYNTH_RUN_DISPOSABLE_MARIADB_DDL_TESTS"


def _require_disposable_mariadb() -> None:
    if os.getenv(DISPOSABLE_OPT_IN) != "1":
        pytest.skip(f"Set {DISPOSABLE_OPT_IN}=1 only for disposable MariaDB.")
    database = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or ""
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST") or ""
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or ""
    if database not in {"", "information_schema"}:
        pytest.fail("DDL test refuses a configured application database")
    if host not in {"127.0.0.1", "localhost"}:
        pytest.fail("DDL test refuses a non-local MariaDB host")
    if "disposable" not in password.lower():
        pytest.fail("DDL test password must contain the disposable marker")


def _split_sql(sql_text: str) -> list[str]:
    delimiter = ";"
    buffer: list[str] = []
    statements: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            if buffer:
                raise ValueError("delimiter changed with pending SQL")
            delimiter = stripped.split(maxsplit=1)[1]
            continue
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(delimiter):
            statement = "\n".join(buffer).strip()[: -len(delimiter)].rstrip()
            if statement:
                statements.append(statement)
            buffer = []
    if buffer:
        raise ValueError("unterminated migration SQL")
    return statements


def _apply(conn: Any, statements: list[str]) -> None:
    with conn.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    conn.commit()


@contextmanager
def _schema() -> Iterator[Any]:
    from src.common.db import get_connection

    _require_disposable_mariadb()
    name = f"synth_protection_policy_{uuid.uuid4().hex[:10]}"
    admin = get_connection(database="information_schema")
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci"
            )
        admin.commit()
    finally:
        admin.close()
    conn = get_connection(database=name)
    try:
        _apply(
            conn,
            [
                """
                CREATE TABLE trading_account (
                    trading_account_id BIGINT UNSIGNED NOT NULL,
                    PRIMARY KEY (trading_account_id)
                ) ENGINE=InnoDB
                """,
                "INSERT INTO trading_account (trading_account_id) VALUES (7)",
                """
                CREATE TABLE automatic_exit_evaluation_audit_v1 (
                    automatic_exit_evaluation_audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    gate_reason_code VARCHAR(128) NULL,
                    PRIMARY KEY (automatic_exit_evaluation_audit_id)
                ) ENGINE=InnoDB
                """,
            ],
        )
        _apply(conn, _split_sql(MIGRATION.read_text(encoding="utf-8")))
        yield conn
    finally:
        conn.close()
        admin = get_connection(database="information_schema")
        try:
            with admin.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
            admin.commit()
        finally:
            admin.close()


_INSERT_OPEN_ROW = """
INSERT INTO account_protection_policy_config_v1 (
    trading_account_id, config_version, configuration_version,
    max_account_drawdown, max_daily_realized_loss, max_repeated_stoploss_streak,
    max_metric_age_seconds, effective_from_ts_utc, effective_until_ts_utc,
    source_provenance
) VALUES (
    7, '1', 'policy-1', NULL, NULL, NULL, 900,
    '2026-08-17 00:00:00', NULL, 'operator-v1'
)
"""


def test_migration_executes_and_audit_columns_are_added() -> None:
    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema=DATABASE()
                  AND table_name='automatic_exit_evaluation_audit_v1'
                  AND column_name IN ('protection_code', 'protection_reason_code')
                """
            )
            columns = {str(row["column_name"]) for row in cursor.fetchall()}
            assert columns == {"protection_code", "protection_reason_code"}
            cursor.execute(
                """
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE constraint_schema=DATABASE()
                  AND table_name='account_protection_policy_config_v1'
                """
            )
            constraints = {str(row["constraint_name"]) for row in cursor.fetchall()}
            assert "chk_account_protection_policy_config_window" in constraints
            assert "chk_account_protection_policy_config_drawdown" in constraints
            assert "chk_account_protection_policy_config_daily_loss" in constraints
            assert "chk_account_protection_policy_config_streak" in constraints
            assert "fk_account_protection_policy_config_account" in constraints


def test_config_row_can_be_closed_exactly_once_to_supersede_it() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(_INSERT_OPEN_ROW)
            row_id = int(cursor.lastrowid)
        conn.commit()

        # The permitted lifecycle transition: close the open window so a new
        # row can become the sole effective row from that point on.
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE account_protection_policy_config_v1 "
                "SET effective_until_ts_utc='2026-08-18 00:00:00' "
                "WHERE account_protection_policy_config_id=%s",
                [row_id],
            )
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT effective_until_ts_utc FROM account_protection_policy_config_v1 "
                "WHERE account_protection_policy_config_id=%s",
                [row_id],
            )
            closed = cursor.fetchone()
            assert str(closed["effective_until_ts_utc"]) == "2026-08-18 00:00:00"

        # A now-closed row cannot be closed again, reopened, or otherwise edited.
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE account_protection_policy_config_v1 "
                    "SET effective_until_ts_utc='2026-08-19 00:00:00' "
                    "WHERE account_protection_policy_config_id=%s",
                    [row_id],
                )
        conn.rollback()
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE account_protection_policy_config_v1 "
                    "SET effective_until_ts_utc=NULL "
                    "WHERE account_protection_policy_config_id=%s",
                    [row_id],
                )
        conn.rollback()


def test_close_transition_rejects_value_edits_and_invalid_windows() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(_INSERT_OPEN_ROW)
            row_id = int(cursor.lastrowid)
        conn.commit()

        # Closing must not smuggle in an edit to any other column.
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE account_protection_policy_config_v1 "
                    "SET effective_until_ts_utc='2026-08-18 00:00:00', configuration_version='policy-2' "
                    "WHERE account_protection_policy_config_id=%s",
                    [row_id],
                )
        conn.rollback()

        # The new effective_until must still be a valid (later) window.
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE account_protection_policy_config_v1 "
                    "SET effective_until_ts_utc='2026-08-16 00:00:00' "
                    "WHERE account_protection_policy_config_id=%s",
                    [row_id],
                )
        conn.rollback()


def test_config_row_cannot_be_deleted() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(_INSERT_OPEN_ROW)
            row_id = int(cursor.lastrowid)
        conn.commit()

        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM account_protection_policy_config_v1 "
                    "WHERE account_protection_policy_config_id=%s",
                    [row_id],
                )
        conn.rollback()


def test_supersession_produces_exactly_one_effective_row_matching_resolver_contract() -> None:
    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(_INSERT_OPEN_ROW)
            old_id = int(cursor.lastrowid)
        conn.commit()

        # Supersede: close the old row and insert the new row in one transaction,
        # both anchored at the same boundary timestamp.
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE account_protection_policy_config_v1 "
                "SET effective_until_ts_utc='2026-08-20 00:00:00' "
                "WHERE account_protection_policy_config_id=%s",
                [old_id],
            )
            cursor.execute(
                """
                INSERT INTO account_protection_policy_config_v1 (
                    trading_account_id, config_version, configuration_version,
                    max_account_drawdown, max_daily_realized_loss, max_repeated_stoploss_streak,
                    max_metric_age_seconds, effective_from_ts_utc, effective_until_ts_utc,
                    source_provenance
                ) VALUES (
                    7, '1', 'policy-2', NULL, NULL, NULL, 900,
                    '2026-08-20 00:00:00', NULL, 'operator-v1'
                )
                """
            )
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT account_protection_policy_config_id, configuration_version "
                "FROM account_protection_policy_config_v1 "
                "WHERE trading_account_id=7 "
                "  AND effective_from_ts_utc <= '2026-08-21 00:00:00' "
                "  AND (effective_until_ts_utc IS NULL OR effective_until_ts_utc > '2026-08-21 00:00:00')"
            )
            effective = cursor.fetchall()
            assert len(effective) == 1
            assert effective[0]["configuration_version"] == "policy-2"
