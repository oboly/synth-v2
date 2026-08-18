from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest


MIGRATION = Path("db/migrations/20260818_automatic_exit_live_decision_gate_permission_v1.sql")
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
    name = f"synth_live_permission_{uuid.uuid4().hex[:10]}"
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
                "INSERT INTO trading_account (trading_account_id) VALUES (7), (8)",
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
INSERT INTO automatic_exit_live_decision_gate_permission_v1 (
    trading_account_id, live_execution_permitted, effective_from_ts_utc,
    effective_until_ts_utc, permission_version, source_provenance
) VALUES (
    %s, 1, '2026-08-18 00:00:00', NULL, '1', 'operator-v1'
)
"""


def _insert_open_row(conn: Any, *, account_id: int = 7) -> int:
    with conn.cursor() as cursor:
        cursor.execute(_INSERT_OPEN_ROW, [account_id])
        row_id = int(cursor.lastrowid)
    conn.commit()
    return row_id


def _insert_revocation(
    conn: Any, *, permission_id: int, account_id: int = 7, effective_ts_utc: str = "2026-08-19 00:00:00",
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO automatic_exit_live_decision_gate_permission_revocation_v1 (
                automatic_exit_live_decision_gate_permission_id, trading_account_id,
                revocation_version, effective_ts_utc, actor, reason
            ) VALUES (%s, %s, '1', %s, 'operator-v1', 'superseded')
            """,
            [permission_id, account_id, effective_ts_utc],
        )
        revocation_id = int(cursor.lastrowid)
    conn.commit()
    return revocation_id


def test_migration_executes_and_constraints_are_present() -> None:
    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE constraint_schema=DATABASE()
                  AND table_name='automatic_exit_live_decision_gate_permission_v1'
                """
            )
            constraints = {str(row["constraint_name"]) for row in cursor.fetchall()}
            assert "chk_automatic_exit_live_permission_flag" in constraints
            assert "chk_automatic_exit_live_permission_window" in constraints
            assert "fk_automatic_exit_live_permission_account" in constraints
            assert "uq_automatic_exit_live_permission_account_binding" in constraints
            cursor.execute(
                """
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE constraint_schema=DATABASE()
                  AND table_name='automatic_exit_live_decision_gate_permission_revocation_v1'
                """
            )
            revocation_constraints = {str(row["constraint_name"]) for row in cursor.fetchall()}
            assert "fk_automatic_exit_live_permission_revocation_permission_account" in revocation_constraints
            assert "chk_automatic_exit_live_permission_revocation_text" in revocation_constraints


def test_permission_row_update_is_always_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)

        # Every shape of update is rejected, including the "close the open
        # window" transition: permission rows are fully immutable.
        rejected_updates = (
            f"UPDATE automatic_exit_live_decision_gate_permission_v1 SET effective_until_ts_utc='2026-08-19 00:00:00' "
            f"WHERE automatic_exit_live_decision_gate_permission_id={row_id}",
            f"UPDATE automatic_exit_live_decision_gate_permission_v1 SET live_execution_permitted=0 "
            f"WHERE automatic_exit_live_decision_gate_permission_id={row_id}",
            f"UPDATE automatic_exit_live_decision_gate_permission_v1 SET source_provenance='other' "
            f"WHERE automatic_exit_live_decision_gate_permission_id={row_id}",
        )
        for statement in rejected_updates:
            with pytest.raises(OperationalError):
                with conn.cursor() as cursor:
                    cursor.execute(statement)
            conn.rollback()


def test_permission_row_delete_is_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM automatic_exit_live_decision_gate_permission_v1 "
                    "WHERE automatic_exit_live_decision_gate_permission_id=%s",
                    [row_id],
                )
        conn.rollback()


def test_revocation_update_is_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)
        revocation_id = _insert_revocation(conn, permission_id=row_id)
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE automatic_exit_live_decision_gate_permission_revocation_v1 SET reason='other' "
                    "WHERE automatic_exit_live_decision_gate_permission_revocation_id=%s",
                    [revocation_id],
                )
        conn.rollback()


def test_revocation_delete_is_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)
        revocation_id = _insert_revocation(conn, permission_id=row_id)
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM automatic_exit_live_decision_gate_permission_revocation_v1 "
                    "WHERE automatic_exit_live_decision_gate_permission_revocation_id=%s",
                    [revocation_id],
                )
        conn.rollback()


def test_revocation_requires_nonempty_actor_and_reason() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO automatic_exit_live_decision_gate_permission_revocation_v1 (
                        automatic_exit_live_decision_gate_permission_id, trading_account_id,
                        revocation_version, effective_ts_utc, actor, reason
                    ) VALUES (%s, 7, '1', '2026-08-19 00:00:00', '   ', 'superseded')
                    """,
                    [row_id],
                )
        conn.rollback()


def test_multiple_revocations_permitted_for_the_same_permission_row() -> None:
    """A scheduled future revocation must never block a later immediate one."""
    with _schema() as conn:
        row_id = _insert_open_row(conn)
        _insert_revocation(conn, permission_id=row_id, effective_ts_utc="2026-08-25 00:00:00")
        # This must succeed even though a revocation already exists for this
        # permission row: multiple revocation facts per permission are by design.
        second_id = _insert_revocation(conn, permission_id=row_id, effective_ts_utc="2026-08-19 00:00:00")
        assert second_id > 0

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM automatic_exit_live_decision_gate_permission_revocation_v1 "
                "WHERE automatic_exit_live_decision_gate_permission_id=%s",
                [row_id],
            )
            assert int(cursor.fetchone()["n"]) == 2


def test_cross_account_revocation_insert_is_rejected_by_composite_fk() -> None:
    """A structurally corrupt revocation (Account A's permission, Account B's
    trading_account_id) must be rejected by MariaDB itself -- the resolver's
    own mismatch check is defense-in-depth, not the only line of defense."""
    from pymysql.err import IntegrityError

    with _schema() as conn:
        account_a_permission_id = _insert_open_row(conn, account_id=7)

        with pytest.raises(IntegrityError):
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO automatic_exit_live_decision_gate_permission_revocation_v1 (
                        automatic_exit_live_decision_gate_permission_id, trading_account_id,
                        revocation_version, effective_ts_utc, actor, reason
                    ) VALUES (%s, 8, '1', '2026-08-19 00:00:00', 'operator-v1', 'cross-account')
                    """,
                    [account_a_permission_id],
                )
        conn.rollback()

        # The matching (non-corrupt) binding succeeds.
        matching_id = _insert_revocation(conn, permission_id=account_a_permission_id, account_id=7)
        assert matching_id > 0
