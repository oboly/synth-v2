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


def _require_disposable_mariadb_opt_in() -> None:
    if os.getenv(DDL_TEST_OPT_IN_ENV) != "1":
        pytest.skip(
            f"Set {DDL_TEST_OPT_IN_ENV}=1 only against a disposable MariaDB instance."
        )

    database_name = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or ""
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST") or ""
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or ""

    if database_name not in {"", "information_schema"}:
        pytest.skip("Disposable DDL test requires DB_NAME unset or information_schema.")
    if host not in {"127.0.0.1", "localhost"}:
        pytest.skip("Disposable DDL test requires local MariaDB host.")
    if "disposable" not in password.lower():
        pytest.skip("Disposable DDL test requires an explicitly disposable DB password marker.")


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


def _seed_scope(conn: object) -> tuple[int, int, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trading_account (
                account_code,
                venue,
                account_mode,
                enabled,
                live_trading_enabled,
                created_ts_utc
            ) VALUES (
                'DISPOSABLE_TEST',
                'bitvavo',
                'live',
                1,
                1,
                '2026-07-21 00:00:00.000000'
            )
            """
        )
        trading_account_id = int(cur.lastrowid)

        cur.execute(
            """
            INSERT INTO decision_gate_audit_log (
                trading_account_id,
                venue,
                asset_id,
                interval_code,
                execution_mode,
                permission_state,
                decision_state,
                asof_ts_utc
            ) VALUES (
                %s,
                'bitvavo',
                42,
                '1h',
                'live',
                'EXECUTION_PERMITTED',
                'EXECUTION_ALLOWED',
                '2026-07-21 12:00:00.000000'
            )
            """,
            (trading_account_id,),
        )
        decision_gate_audit_log_id = int(cur.lastrowid)

        cur.execute(
            """
            INSERT INTO execution_plan (
                account_id,
                asset_id,
                sleeve_code,
                venue,
                side,
                desired_action,
                execution_intent,
                execution_mode,
                plan_ts_utc,
                valid_until_ts_utc,
                plan_state
            ) VALUES (
                %s,
                42,
                'CORE',
                'bitvavo',
                'BUY',
                'SPREAD_CAPTURE_PASSIVE',
                'PLACE_PASSIVE_LIMIT',
                'live',
                '2026-07-21 12:00:00.000000',
                '2026-07-21 13:00:00.000000',
                'IDLE'
            )
            """,
            (trading_account_id,),
        )
        execution_plan_id = int(cur.lastrowid)
    conn.commit()

    return trading_account_id, decision_gate_audit_log_id, execution_plan_id


def _insert_evidence(
    conn: object,
    *,
    trading_account_id: int,
    decision_gate_audit_log_id: int,
    execution_plan_id: int,
    evidence_state: str = "ACTIVE",
    permitted_ts_utc: str = "2026-07-21 11:59:00.000000",
    valid_until_ts_utc: str = "2026-07-21 12:05:00.000000",
    revoked_ts_utc: str | None = None,
    superseded_by_evidence_id: int | None = None,
    explicit_id: int | None = None,
) -> int:
    columns = [
        "decision_gate_audit_log_id",
        "execution_plan_id",
        "trading_account_id",
        "venue",
        "asset_id",
        "market",
        "execution_intent",
        "action_type",
        "requested_side",
        "permission_state",
        "decision_state",
        "evidence_state",
        "permitted_ts_utc",
        "valid_until_ts_utc",
        "revoked_ts_utc",
        "superseded_by_evidence_id",
    ]
    values: list[object] = [
        decision_gate_audit_log_id,
        execution_plan_id,
        trading_account_id,
        "bitvavo",
        42,
        "BTC-EUR",
        "PLACE_PASSIVE_LIMIT",
        "SPREAD_CAPTURE_PASSIVE",
        "BUY",
        "EXECUTION_PERMITTED",
        "EXECUTION_ALLOWED",
        evidence_state,
        permitted_ts_utc,
        valid_until_ts_utc,
        revoked_ts_utc,
        superseded_by_evidence_id,
    ]
    if explicit_id is not None:
        columns.insert(0, "execution_permission_evidence_id")
        values.insert(0, explicit_id)

    placeholders = ", ".join(["%s"] * len(values))
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO execution_permission_evidence (
                    {", ".join(columns)}
                ) VALUES ({placeholders})
                """,
                values,
            )
            row_id = int(explicit_id if explicit_id is not None else cur.lastrowid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return row_id


def test_executor_permission_evidence_migration_applies_to_disposable_mariadb() -> None:
    from src.common.db import get_connection

    _require_disposable_mariadb_opt_in()

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
            _apply_statements(
                conn,
                _split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8")),
            )
            with conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM execution_permission_evidence")
                columns = {str(row["Field"]) for row in cur.fetchall()}
                cur.execute("SHOW COLUMNS FROM execution_plan")
                plan_columns = {str(row["Field"]) for row in cur.fetchall()}
                cur.execute("SHOW INDEX FROM execution_permission_evidence")
                indexes = {str(row["Key_name"]) for row in cur.fetchall()}

            trading_account_id, audit_id, plan_id = _seed_scope(conn)
            active_id = _insert_evidence(
                conn,
                trading_account_id=trading_account_id,
                decision_gate_audit_log_id=audit_id,
                execution_plan_id=plan_id,
            )
            revoked_id = _insert_evidence(
                conn,
                trading_account_id=trading_account_id,
                decision_gate_audit_log_id=audit_id,
                execution_plan_id=plan_id,
                evidence_state="REVOKED",
                revoked_ts_utc="2026-07-21 12:01:00.000000",
            )
            superseded_id = _insert_evidence(
                conn,
                trading_account_id=trading_account_id,
                decision_gate_audit_log_id=audit_id,
                execution_plan_id=plan_id,
                evidence_state="SUPERSEDED",
                superseded_by_evidence_id=active_id,
            )
            _insert_evidence(
                conn,
                trading_account_id=trading_account_id,
                decision_gate_audit_log_id=audit_id,
                execution_plan_id=plan_id,
                permitted_ts_utc="2026-07-21 10:00:00.000000",
                valid_until_ts_utc="2026-07-21 11:00:00.000000",
            )
            _insert_evidence(
                conn,
                trading_account_id=trading_account_id,
                decision_gate_audit_log_id=audit_id,
                execution_plan_id=plan_id,
                permitted_ts_utc="2026-07-21 12:30:00.000000",
                valid_until_ts_utc="2026-07-21 13:00:00.000000",
            )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT execution_permission_evidence_id
                    FROM execution_permission_evidence
                    WHERE execution_plan_id = %s
                      AND evidence_state = 'ACTIVE'
                      AND revoked_ts_utc IS NULL
                      AND superseded_by_evidence_id IS NULL
                      AND permitted_ts_utc <= '2026-07-21 12:00:00.000000'
                      AND valid_until_ts_utc >= '2026-07-21 12:00:00.000000'
                    ORDER BY execution_permission_evidence_id ASC
                    """,
                    (plan_id,),
                )
                current_rows = [int(row["execution_permission_evidence_id"]) for row in cur.fetchall()]

                cur.execute(
                    """
                    SELECT evidence_state, COUNT(*) AS cnt
                    FROM execution_permission_evidence
                    WHERE execution_plan_id = %s
                    GROUP BY evidence_state
                    """,
                    (plan_id,),
                )
                history_counts = {
                    str(row["evidence_state"]): int(row["cnt"])
                    for row in cur.fetchall()
                }

            from pymysql.err import IntegrityError, OperationalError

            constraint_errors = (IntegrityError, OperationalError)
            with pytest.raises(constraint_errors):
                _insert_evidence(
                    conn,
                    trading_account_id=trading_account_id,
                    decision_gate_audit_log_id=audit_id,
                    execution_plan_id=plan_id,
                    permitted_ts_utc="2026-07-21 12:05:00.000000",
                    valid_until_ts_utc="2026-07-21 12:00:00.000000",
                )
            with pytest.raises(constraint_errors):
                _insert_evidence(
                    conn,
                    trading_account_id=trading_account_id,
                    decision_gate_audit_log_id=audit_id,
                    execution_plan_id=plan_id,
                    evidence_state="REVOKED",
                )
            with pytest.raises(constraint_errors):
                _insert_evidence(
                    conn,
                    trading_account_id=trading_account_id,
                    decision_gate_audit_log_id=audit_id,
                    execution_plan_id=plan_id,
                    revoked_ts_utc="2026-07-21 12:01:00.000000",
                )
            with pytest.raises(constraint_errors):
                _insert_evidence(
                    conn,
                    trading_account_id=trading_account_id,
                    decision_gate_audit_log_id=audit_id,
                    execution_plan_id=plan_id,
                    evidence_state="ACTIVE",
                    superseded_by_evidence_id=active_id,
                )
            with pytest.raises(constraint_errors):
                _insert_evidence(
                    conn,
                    trading_account_id=trading_account_id,
                    decision_gate_audit_log_id=audit_id,
                    execution_plan_id=plan_id,
                    evidence_state="SUPERSEDED",
                )
        finally:
            conn.close()

        assert "execution_permission_evidence_id" in columns
        assert "execution_plan_id" in columns
        assert "trading_account_id" in columns
        assert "permitted_ts_utc" in columns
        assert "valid_until_ts_utc" in columns
        assert "execution_intent" in plan_columns
        assert "ix_epe_plan_state_v1" in indexes
        assert not any(name.lower().startswith("uq_") for name in indexes)
        assert current_rows == [active_id]
        assert history_counts["ACTIVE"] == 3
        assert history_counts["REVOKED"] == 1
        assert history_counts["SUPERSEDED"] == 1
        assert revoked_id > active_id
        assert superseded_id > active_id
    finally:
        _drop_database(db_name)
