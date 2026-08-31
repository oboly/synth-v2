from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pytest


BASE_MIGRATION = Path("db/migrations/20260603_account_open_order_snapshot_v1.sql")
PRECISION_MIGRATION = Path(
    "db/migrations/20260831_account_open_order_snapshot_timestamp_precision_v1.sql"
)
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
    statements: list[str] = []
    for chunk in sql_text.split(";"):
        lines = [
            line
            for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
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
    name = f"synth_open_order_ts_{uuid.uuid4().hex[:10]}"
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
                "INSERT INTO trading_account (trading_account_id) VALUES (5)",
                # Minimal stand-ins for the two sibling aligned components so
                # verify_persisted_component_counts() can run all three of its
                # checks; only the open-order component is under test here.
                """
                CREATE TABLE account_position_snapshot (
                    trading_account_id BIGINT UNSIGNED NOT NULL,
                    venue VARCHAR(32) NOT NULL,
                    source_name VARCHAR(96) NOT NULL,
                    snapshot_ts_utc DATETIME(6) NOT NULL
                ) ENGINE=InnoDB
                """,
                """
                CREATE TABLE trading_account_balance_snapshot (
                    trading_account_id BIGINT UNSIGNED NOT NULL,
                    venue VARCHAR(32) NOT NULL,
                    source_name VARCHAR(96) NOT NULL,
                    snapshot_ts_utc DATETIME(6) NOT NULL
                ) ENGINE=InnoDB
                """,
            ],
        )
        _apply(conn, _split_sql(BASE_MIGRATION.read_text(encoding="utf-8")))
        _apply(conn, _split_sql(PRECISION_MIGRATION.read_text(encoding="utf-8")))
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


def test_snapshot_ts_utc_is_datetime_precision_6_and_not_null() -> None:
    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT data_type, datetime_precision, is_nullable
                FROM information_schema.columns
                WHERE table_schema=DATABASE()
                  AND table_name='account_open_order_snapshot'
                  AND column_name='snapshot_ts_utc'
                """
            )
            row = cursor.fetchone()
        assert row is not None
        assert str(row["data_type"]).lower() == "datetime"
        assert int(row["datetime_precision"]) == 6
        assert str(row["is_nullable"]).upper() == "NO"


def test_unique_key_on_account_snapshot_and_order_is_preserved() -> None:
    with _schema() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT k.column_name, k.ordinal_position
                FROM information_schema.statistics k
                WHERE k.table_schema=DATABASE()
                  AND k.table_name='account_open_order_snapshot'
                  AND k.index_name='uq_order_snapshot'
                ORDER BY k.ordinal_position
                """
            )
            columns = [str(row["column_name"]) for row in cursor.fetchall()]
        assert columns == ["trading_account_id", "snapshot_ts_utc", "broker_order_id"]


def test_microsecond_snapshot_round_trips_exactly() -> None:
    """Regression for #644: a microsecond-bearing snapshot timestamp must be
    stored and re-queryable exactly, matching the other aligned
    account-state components that already use DATETIME(6)."""
    with _schema() as conn:
        snapshot_ts_utc = datetime(2026, 8, 31, 12, 0, 0, 123456)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO account_open_order_snapshot (
                    snapshot_ts_utc, trading_account_id, venue, market,
                    broker_order_id, side, order_type,
                    quantity, filled_quantity, remaining_quantity, broker_status
                ) VALUES (
                    %s, 5, 'bitvavo', 'BTC-EUR',
                    'order-1', 'BUY', 'LIMIT',
                    1, 0, 1, 'open'
                )
                """,
                [snapshot_ts_utc],
            )
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS n FROM account_open_order_snapshot
                WHERE trading_account_id = 5
                  AND venue = 'bitvavo'
                  AND snapshot_ts_utc = %s
                """,
                [snapshot_ts_utc],
            )
            row = cursor.fetchone()
        assert int(row["n"]) == 1


def test_exact_count_verification_succeeds_with_microsecond_snapshot() -> None:
    """End-to-end regression for #644 using the production write/verify
    functions: a microsecond-bearing snapshot_ts_utc must survive the
    open-order write and the exact-count re-query used by the exact-account
    persistence flow, with no Python-side timestamp rounding."""
    from src.account.account_state_snapshot_alignment_v1 import (
        verify_persisted_component_counts,
    )
    from src.account.account_snapshot_models_v1 import WalletOpenOrderRow
    from src.account.run_account_wallet_refresh_v1 import write_open_order_snapshot

    with _schema() as conn:
        snapshot_ts_utc = datetime(2026, 8, 31, 12, 0, 0, 654321)
        orders = [
            WalletOpenOrderRow(
                market="BTC-EUR",
                broker_order_id="order-1",
                client_order_id=None,
                side="BUY",
                order_type="LIMIT",
                limit_price=None,
                quantity=1,
                filled_quantity=0,
                remaining_quantity=1,
                broker_status="open",
            )
        ]

        order_writes = write_open_order_snapshot(
            conn,
            trading_account_id=5,
            venue="bitvavo",
            orders=orders,
            snapshot_ts_utc=snapshot_ts_utc,
        )
        conn.commit()
        assert order_writes == len(orders)

        # This is the exact call exact_account_state_persistence_v1 makes
        # after writing all components. Before the DATETIME(6) fix this
        # raised OPEN_ORDER_SNAPSHOT_COUNT_MISMATCH because the stored row
        # had its microseconds truncated to zero on insert.
        verify_persisted_component_counts(
            conn,
            trading_account_id=5,
            venue="bitvavo",
            snapshot_ts_utc=snapshot_ts_utc,
            position_source_name="unused",
            expected_position_count=0,
            balance_source_name="unused",
            expected_balance_count=0,
            expected_open_order_count=order_writes,
        )
