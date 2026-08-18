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
                "INSERT INTO trading_account (trading_account_id) VALUES (7), (8)",
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
    %s, '1', 'policy-1', NULL, NULL, NULL, 900,
    '2026-08-17 00:00:00', NULL, 'operator-v1'
)
"""


def _insert_open_row(conn: Any, *, account_id: int = 7) -> int:
    with conn.cursor() as cursor:
        cursor.execute(_INSERT_OPEN_ROW, [account_id])
        row_id = int(cursor.lastrowid)
    conn.commit()
    return row_id


def _insert_revocation(
    conn: Any, *, config_id: int, account_id: int = 7, effective_ts_utc: str = "2026-08-18 00:00:00",
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO account_protection_policy_config_revocation_v1 (
                account_protection_policy_config_id, trading_account_id,
                revocation_version, effective_ts_utc, actor, reason
            ) VALUES (%s, %s, '1', %s, 'operator-v1', 'superseded')
            """,
            [config_id, account_id, effective_ts_utc],
        )
        revocation_id = int(cursor.lastrowid)
    conn.commit()
    return revocation_id


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
            assert "uq_account_protection_policy_config_account_binding" in constraints
            cursor.execute(
                """
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE constraint_schema=DATABASE()
                  AND table_name='account_protection_policy_config_revocation_v1'
                """
            )
            revocation_constraints = {str(row["constraint_name"]) for row in cursor.fetchall()}
            assert "fk_account_protection_policy_config_revocation_config_account" in revocation_constraints
            assert "fk_account_protection_policy_config_revocation_config" not in revocation_constraints
            assert "fk_account_protection_policy_config_revocation_account" not in revocation_constraints
            assert "chk_account_protection_policy_config_revocation_text" in revocation_constraints


def test_config_row_update_is_always_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)

        # Every shape of update is rejected, including the previously-permitted
        # "close the open window" transition: config rows are fully immutable.
        rejected_updates = (
            f"UPDATE account_protection_policy_config_v1 SET effective_until_ts_utc='2026-08-18 00:00:00' "
            f"WHERE account_protection_policy_config_id={row_id}",
            f"UPDATE account_protection_policy_config_v1 SET configuration_version='policy-2' "
            f"WHERE account_protection_policy_config_id={row_id}",
            f"UPDATE account_protection_policy_config_v1 SET source_provenance='other' "
            f"WHERE account_protection_policy_config_id={row_id}",
        )
        for statement in rejected_updates:
            with pytest.raises(OperationalError):
                with conn.cursor() as cursor:
                    cursor.execute(statement)
            conn.rollback()


def test_config_row_delete_is_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM account_protection_policy_config_v1 "
                    "WHERE account_protection_policy_config_id=%s",
                    [row_id],
                )
        conn.rollback()


def test_revocation_update_is_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)
        revocation_id = _insert_revocation(conn, config_id=row_id)
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE account_protection_policy_config_revocation_v1 SET reason='other' "
                    "WHERE account_protection_policy_config_revocation_id=%s",
                    [revocation_id],
                )
        conn.rollback()


def test_revocation_delete_is_rejected() -> None:
    from pymysql.err import OperationalError

    with _schema() as conn:
        row_id = _insert_open_row(conn)
        revocation_id = _insert_revocation(conn, config_id=row_id)
        with pytest.raises(OperationalError):
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM account_protection_policy_config_revocation_v1 "
                    "WHERE account_protection_policy_config_revocation_id=%s",
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
                    INSERT INTO account_protection_policy_config_revocation_v1 (
                        account_protection_policy_config_id, trading_account_id,
                        revocation_version, effective_ts_utc, actor, reason
                    ) VALUES (%s, 7, '1', '2026-08-18 00:00:00', '   ', 'superseded')
                    """,
                    [row_id],
                )
        conn.rollback()


def test_multiple_revocations_permitted_for_the_same_config_row() -> None:
    """A scheduled future revocation must never block a later immediate one."""
    with _schema() as conn:
        row_id = _insert_open_row(conn)
        _insert_revocation(conn, config_id=row_id, effective_ts_utc="2026-08-25 00:00:00")
        # This must succeed even though a revocation already exists for this
        # config row: multiple revocation facts per config are by design.
        second_id = _insert_revocation(conn, config_id=row_id, effective_ts_utc="2026-08-18 00:00:00")
        assert second_id > 0

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM account_protection_policy_config_revocation_v1 "
                "WHERE account_protection_policy_config_id=%s",
                [row_id],
            )
            assert int(cursor.fetchone()["n"]) == 2


def test_successor_and_revocation_leave_exactly_one_effective_config() -> None:
    with _schema() as conn:
        old_id = _insert_open_row(conn)
        _insert_revocation(conn, config_id=old_id, effective_ts_utc="2026-08-20 00:00:00")

        with conn.cursor() as cursor:
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
            new_id = int(cursor.lastrowid)
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.account_protection_policy_config_id, c.configuration_version
                FROM account_protection_policy_config_v1 c
                WHERE c.trading_account_id=7
                  AND c.effective_from_ts_utc <= '2026-08-21 00:00:00'
                  AND (c.effective_until_ts_utc IS NULL OR c.effective_until_ts_utc > '2026-08-21 00:00:00')
                  AND NOT EXISTS (
                      SELECT 1 FROM account_protection_policy_config_revocation_v1 r
                      WHERE r.account_protection_policy_config_id = c.account_protection_policy_config_id
                        AND r.effective_ts_utc <= '2026-08-21 00:00:00'
                  )
                """
            )
            effective = cursor.fetchall()
            assert len(effective) == 1
            assert effective[0]["account_protection_policy_config_id"] == new_id
            assert effective[0]["configuration_version"] == "policy-2"


def test_cross_account_revocation_insert_is_rejected_by_composite_fk() -> None:
    """A structurally corrupt revocation (Account A's config, Account B's
    trading_account_id) must be rejected by MariaDB itself -- the resolver's
    own mismatch check is defense-in-depth, not the only line of defense."""
    from pymysql.err import IntegrityError

    with _schema() as conn:
        account_a_config_id = _insert_open_row(conn, account_id=7)

        with pytest.raises(IntegrityError):
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO account_protection_policy_config_revocation_v1 (
                        account_protection_policy_config_id, trading_account_id,
                        revocation_version, effective_ts_utc, actor, reason
                    ) VALUES (%s, 8, '1', '2026-08-18 00:00:00', 'operator-v1', 'cross-account')
                    """,
                    [account_a_config_id],
                )
        conn.rollback()

        # The matching (non-corrupt) binding succeeds.
        matching_id = _insert_revocation(conn, config_id=account_a_config_id, account_id=7)
        assert matching_id > 0
