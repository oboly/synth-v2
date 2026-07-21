from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest


MIGRATION_PATH = Path(
    "db/migrations/20260721_execution_plan_explicit_intent_contract_v1.sql"
)
DDL_TEST_OPT_IN_ENV = "SYNTH_RUN_DISPOSABLE_MARIADB_DDL_TESTS"


def _split_sql_statements(sql_text: str) -> list[str]:
    delimiter = ";"
    buffer: list[str] = []
    statements: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            if buffer:
                raise ValueError("delimiter changed with a pending SQL statement")
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
        raise ValueError("unterminated migration SQL statement")
    return statements


def _apply_statements(conn: Any, statements: Iterable[str]) -> None:
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


def _apply_migration(conn: Any) -> None:
    _apply_statements(
        conn,
        _split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8")),
    )


def _require_disposable_mariadb() -> None:
    if os.getenv(DDL_TEST_OPT_IN_ENV) != "1":
        pytest.skip(f"Set {DDL_TEST_OPT_IN_ENV}=1 only for disposable MariaDB.")
    database = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or ""
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST") or ""
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or ""
    if database not in {"", "information_schema"}:
        pytest.fail("DDL test refuses a configured application database")
    if host not in {"127.0.0.1", "localhost"}:
        pytest.fail("DDL test refuses a non-local MariaDB host")
    if "disposable" not in password.lower():
        pytest.fail("DDL test password must contain the disposable marker")


def _create_base_schema(conn: Any) -> None:
    _apply_statements(
        conn,
        [
            """
            CREATE TABLE trading_account (
                trading_account_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                legacy_account_id BIGINT UNSIGNED NOT NULL,
                account_code VARCHAR(63) NOT NULL,
                PRIMARY KEY (trading_account_id),
                UNIQUE KEY uq_trading_account_legacy (legacy_account_id),
                UNIQUE KEY uq_trading_account_composite (trading_account_id, legacy_account_id)
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
                plan_state VARCHAR(32) NOT NULL,
                PRIMARY KEY (execution_plan_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ],
    )


@contextmanager
def _schema() -> Iterator[Any]:
    from src.common.db import get_connection

    _require_disposable_mariadb()
    name = f"synth_epc_{uuid.uuid4().hex[:12]}"
    admin = get_connection(database="information_schema")
    try:
        with admin.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        admin.commit()
    finally:
        admin.close()
    conn = get_connection(database=name)
    try:
        _create_base_schema(conn)
        yield conn
    finally:
        conn.close()
        admin = get_connection(database="information_schema")
        try:
            with admin.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
            admin.commit()
        finally:
            admin.close()


def _column_names(conn: Any) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name='execution_plan'"
        )
        return {str(row["column_name"]) for row in cur.fetchall()}


def _add_trading_account_id(conn: Any) -> None:
    _apply_statements(
        conn,
        ["ALTER TABLE execution_plan ADD trading_account_id BIGINT UNSIGNED NULL AFTER account_id"],
    )


def _foreign_keys_for_trading_account_id(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                kcu.constraint_name,
                kcu.column_name,
                kcu.referenced_table_name,
                kcu.referenced_column_name,
                kcu.ordinal_position,
                rc.update_rule,
                rc.delete_rule
            FROM information_schema.key_column_usage AS kcu
            JOIN information_schema.referential_constraints AS rc
              ON rc.constraint_schema = kcu.constraint_schema
             AND rc.constraint_name = kcu.constraint_name
             AND rc.table_name = kcu.table_name
            WHERE kcu.table_schema = DATABASE()
              AND kcu.table_name = 'execution_plan'
              AND kcu.constraint_name IN (
                  SELECT involving.constraint_name
                  FROM information_schema.key_column_usage AS involving
                  WHERE involving.table_schema = DATABASE()
                    AND involving.table_name = 'execution_plan'
                    AND involving.column_name = 'trading_account_id'
                    AND involving.referenced_table_name IS NOT NULL
              )
            ORDER BY kcu.constraint_name, kcu.ordinal_position
            """
        )
        return list(cur.fetchall())


def test_migration_parser_keeps_procedure_atomic() -> None:
    statements = _split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert len(statements) == 4
    assert statements[1].startswith("CREATE PROCEDURE")
    assert "decision_gate_permission_evidence" not in MIGRATION_PATH.read_text(encoding="utf-8")
    assert "execution_attempt" not in MIGRATION_PATH.read_text(encoding="utf-8")


def test_fresh_rerun_partial_columns_and_history_are_preserved() -> None:
    with _schema() as conn:
        _apply_statements(
            conn,
            [
                "ALTER TABLE execution_plan ADD market VARCHAR(32) "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL",
                """
                INSERT INTO execution_plan (
                    account_id, asset_id, sleeve_code, venue, side, desired_action,
                    execution_mode, plan_ts_utc, plan_state, market
                ) VALUES (7, 9, 'CORE', 'bitvavo', 'BUY', 'PREPARE_PLAN',
                          'paper', UTC_TIMESTAMP(6), 'IDLE', 'BTC-EUR')
                """,
            ],
        )
        _apply_migration(conn)
        _apply_migration(conn)

        assert {
            "trading_account_id",
            "market",
            "execution_intent",
            "action_type",
            "requested_side",
        } <= _column_names(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT account_id, market, execution_mode FROM execution_plan "
                "WHERE execution_plan_id=1"
            )
            assert cur.fetchone() == {
                "account_id": 7,
                "market": "BTC-EUR",
                "execution_mode": "PAPER",
            }
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=DATABASE() AND table_name IN "
                "('execution_permission_evidence','decision_gate_permission_evidence','execution_attempt')"
            )
            assert cur.fetchall() == ()
            cur.execute(
                "SELECT column_name, collation_name FROM information_schema.columns "
                "WHERE table_schema=DATABASE() AND table_name='execution_plan' "
                "AND column_name IN ('market','execution_intent','action_type','requested_side')"
            )
            assert {row["collation_name"] for row in cur.fetchall()} == {"utf8mb4_bin"}

        assert _foreign_keys_for_trading_account_id(conn) == [
            {
                "constraint_name": "fk_execution_plan_trading_account_contract_v1",
                "column_name": "trading_account_id",
                "referenced_table_name": "trading_account",
                "referenced_column_name": "trading_account_id",
                "ordinal_position": 1,
                "update_rule": "RESTRICT",
                "delete_rule": "RESTRICT",
            }
        ]


@pytest.mark.parametrize(
    ("partial_sql", "code"),
    [
        (
            "ALTER TABLE execution_plan ADD requested_side BIGINT NULL",
            "EPC_MIGRATION_INCOMPATIBLE_REQUESTED_SIDE",
        ),
        (
            "ALTER TABLE execution_plan ADD action_type VARCHAR(64) NOT NULL DEFAULT ''",
            "EPC_MIGRATION_INCOMPATIBLE_ACTION_TYPE",
        ),
        (
            "ALTER TABLE execution_plan ADD execution_intent VARCHAR(64) "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL",
            "EPC_MIGRATION_INCOMPATIBLE_EXECUTION_INTENT",
        ),
    ],
)
def test_incompatible_partial_shape_fails_explicitly(partial_sql: str, code: str) -> None:
    with _schema() as conn:
        _apply_statements(conn, [partial_sql])
        with pytest.raises(Exception, match=code):
            _apply_migration(conn)


def test_only_exact_lowercase_legacy_modes_are_normalized() -> None:
    with _schema() as conn:
        for mode in ("PAPER", "paper", "Paper", "LIVE", "live", "Live"):
            _apply_statements(
                conn,
                [
                    "INSERT INTO execution_plan "
                    "(account_id, asset_id, sleeve_code, venue, side, desired_action, "
                    "execution_mode, plan_ts_utc, plan_state) VALUES "
                    f"(7, 9, 'CORE', 'bitvavo', 'BUY', 'PREPARE_PLAN', '{mode}', "
                    "UTC_TIMESTAMP(6), 'IDLE')"
                ],
            )

        _apply_migration(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT execution_mode FROM execution_plan ORDER BY execution_plan_id")
            assert [row["execution_mode"] for row in cur.fetchall()] == [
                "PAPER",
                "PAPER",
                "Paper",
                "LIVE",
                "LIVE",
                "Live",
            ]


def test_existing_exact_single_column_fk_is_accepted() -> None:
    with _schema() as conn:
        _add_trading_account_id(conn)
        _apply_statements(
            conn,
            [
                "ALTER TABLE execution_plan ADD CONSTRAINT fk_existing_exact "
                "FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id) "
                "ON UPDATE RESTRICT ON DELETE RESTRICT"
            ],
        )
        _apply_migration(conn)
        _apply_migration(conn)
        assert len(_foreign_keys_for_trading_account_id(conn)) == 1


@pytest.mark.parametrize(
    "setup_statements",
    [
        [
            "CREATE TABLE alternate_account (trading_account_id BIGINT UNSIGNED NOT NULL, "
            "PRIMARY KEY (trading_account_id)) ENGINE=InnoDB",
            "ALTER TABLE execution_plan ADD CONSTRAINT fk_wrong_table "
            "FOREIGN KEY (trading_account_id) REFERENCES alternate_account (trading_account_id)",
        ],
        [
            "ALTER TABLE execution_plan ADD CONSTRAINT fk_wrong_column "
            "FOREIGN KEY (trading_account_id) REFERENCES trading_account (legacy_account_id)",
        ],
        [
            "ALTER TABLE execution_plan ADD CONSTRAINT fk_composite "
            "FOREIGN KEY (trading_account_id, account_id) "
            "REFERENCES trading_account (trading_account_id, legacy_account_id)",
        ],
        [
            "ALTER TABLE execution_plan ADD CONSTRAINT fk_exact_first "
            "FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id)",
            "ALTER TABLE execution_plan ADD CONSTRAINT fk_second_wrong "
            "FOREIGN KEY (trading_account_id) REFERENCES trading_account (legacy_account_id)",
        ],
        [
            "ALTER TABLE execution_plan ADD CONSTRAINT fk_wrong_rules "
            "FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id) "
            "ON UPDATE CASCADE ON DELETE CASCADE",
        ],
    ],
    ids=["wrong-table", "wrong-column", "composite", "multiple", "wrong-rules"],
)
def test_incompatible_foreign_key_definitions_fail_explicitly(
    setup_statements: list[str],
) -> None:
    with _schema() as conn:
        _add_trading_account_id(conn)
        _apply_statements(conn, setup_statements)
        with pytest.raises(Exception, match="EPC_MIGRATION_INCOMPATIBLE_TRADING_ACCOUNT_FK"):
            _apply_migration(conn)
