from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest


MIGRATION = Path("db/migrations/20260817_executor_live_authority_v1.sql")
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
    name = f"synth_executor_authority_{uuid.uuid4().hex[:10]}"
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


def test_authority_migration_executes_and_enforces_immutability() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, constraint_name
                FROM information_schema.table_constraints
                WHERE constraint_schema=DATABASE()
                  AND table_name IN (
                      'executor_live_authority_grant',
                      'executor_live_authority_revocation',
                      'executor_kill_switch_event'
                  )
                """
            )
            constraints = {
                (str(row["table_name"]), str(row["constraint_name"]))
                for row in cursor.fetchall()
            }
            assert (
                "executor_live_authority_grant",
                "fk_elag_trading_account",
            ) in constraints
            assert (
                "executor_live_authority_revocation",
                "fk_elar_grant",
            ) in constraints
            assert ("executor_live_authority_grant", "chk_elag_side") in constraints
            assert (
                "executor_live_authority_grant",
                "chk_elag_finite_window",
            ) in constraints
            assert ("executor_kill_switch_event", "chk_ekse_state") in constraints
            cursor.execute(
                """
                SELECT table_name, index_name
                FROM information_schema.statistics
                WHERE table_schema=DATABASE()
                  AND index_name IN (
                      'ix_elag_exact_resolution',
                      'uq_elar_one_per_grant',
                      'ix_elar_effective'
                  )
                """
            )
            indexes = {
                (str(row["table_name"]), str(row["index_name"]))
                for row in cursor.fetchall()
            }
            assert indexes == {
                ("executor_live_authority_grant", "ix_elag_exact_resolution"),
                ("executor_live_authority_revocation", "uq_elar_one_per_grant"),
                ("executor_live_authority_revocation", "ix_elar_effective"),
            }
            cursor.execute(
                """
                INSERT INTO executor_live_authority_grant (
                    trading_account_id, venue, side, market, executor_identity,
                    runtime_owner, effective_from_ts_utc, effective_until_ts_utc,
                    authorized_by, authorization_reason
                ) VALUES (
                    7, 'bitvavo', 'BUY', 'BTC-EUR', 'executor-v1', 'host-v1',
                    '2026-08-17 00:00:00', '2026-08-24 00:00:00',
                    'operator-v1', 'bounded test'
                )
                """
            )
            grant_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO executor_live_authority_revocation (
                    executor_live_authority_grant_id, revoked_ts_utc,
                    revoked_by, revocation_reason
                ) VALUES (%s, '2026-08-18 00:00:00', 'operator-v1', 'stop')
                """,
                [grant_id],
            )
            cursor.execute(
                "INSERT INTO executor_kill_switch_event "
                "(state, actor, reason, created_ts_utc) "
                "VALUES ('ENGAGED', 'operator-v1', 'stop all', '2026-08-18 00:00:00')"
            )
        conn.commit()

        immutable_targets = (
            ("executor_live_authority_grant", "venue='kraken'"),
            ("executor_live_authority_revocation", "revoked_by='other'"),
            ("executor_kill_switch_event", "state='DISENGAGED'"),
        )
        for table, assignment in immutable_targets:
            with pytest.raises(OperationalError):
                with conn.cursor() as cursor:
                    cursor.execute(f"UPDATE {table} SET {assignment}")
            conn.rollback()
            with pytest.raises(OperationalError):
                with conn.cursor() as cursor:
                    cursor.execute(f"DELETE FROM {table}")
            conn.rollback()


def test_authority_migration_rejects_unbounded_window_and_invalid_state() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO executor_live_authority_grant (
                        trading_account_id, venue, side, market, executor_identity,
                        runtime_owner, effective_from_ts_utc, effective_until_ts_utc,
                        authorized_by, authorization_reason
                    ) VALUES (
                        7, 'bitvavo', 'BUY', NULL, 'executor-v1', 'host-v1',
                        '2026-08-17 00:00:00', '2026-08-24 00:00:00.000001',
                        'operator-v1', 'too long'
                    )
                    """
                )
        conn.rollback()
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO executor_kill_switch_event "
                    "(state, actor, reason, created_ts_utc) "
                    "VALUES ('UNKNOWN', 'operator-v1', 'invalid', '2026-08-18 00:00:00')"
                )
        conn.rollback()
