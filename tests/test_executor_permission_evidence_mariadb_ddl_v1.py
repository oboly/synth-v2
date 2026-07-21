from __future__ import annotations

import base64
import os
import threading
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.decision_gate.permission_evidence_v1 import (
    EVIDENCE_PRIVATE_KEY_ENV,
    EVIDENCE_PUBLIC_KEY_ENV,
    build_provenance_payload,
    sign_provenance,
)
from src.execution.permission_gate_v1 import (
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
    LIVE_EXECUTION_PERMISSION_ENV,
    LIVE_EXECUTION_PERMISSION_GRANTED_VALUE,
)


MIGRATION_PATH = Path("db/migrations/20260721_executor_permission_evidence_v1.sql")
DDL_TEST_OPT_IN_ENV = "SYNTH_RUN_DISPOSABLE_MARIADB_DDL_TESTS"
CLAIM_NOW = datetime(2026, 7, 21, 12, 0, 0)
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
PRIVATE_KEY_B64 = base64.b64encode(
    PRIVATE_KEY.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
).decode("ascii")
PUBLIC_KEY_B64 = base64.b64encode(
    PRIVATE_KEY.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
).decode("ascii")
PRODUCER_ENV = {EVIDENCE_PRIVATE_KEY_ENV: PRIVATE_KEY_B64}
CLAIM_ENV = {
    EVIDENCE_PUBLIC_KEY_ENV: PUBLIC_KEY_B64,
    LIVE_EXECUTION_PERMISSION_ENV: LIVE_EXECUTION_PERMISSION_GRANTED_VALUE,
    BROKER_WRITE_PERMISSION_ENV: BROKER_WRITE_PERMISSION_GRANTED_VALUE,
}


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
            statement = "\n".join(buffer).strip()
            statement = statement[: -len(delimiter)].rstrip()
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
    _apply_statements(conn, _split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8")))


def _require_disposable_mariadb_opt_in() -> None:
    if os.getenv(DDL_TEST_OPT_IN_ENV) != "1":
        pytest.skip(f"Set {DDL_TEST_OPT_IN_ENV}=1 only for disposable MariaDB.")
    database_name = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or ""
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST") or ""
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or ""
    if database_name not in {"", "information_schema"}:
        pytest.fail("DDL test refuses a configured application database")
    if host not in {"127.0.0.1", "localhost"}:
        pytest.fail("DDL test refuses a non-local MariaDB host")
    if "disposable" not in password.lower():
        pytest.fail("DDL test password must contain the disposable marker")


def _create_prerequisites(conn: Any) -> None:
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
                created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                PRIMARY KEY (trading_account_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE decision_gate_audit_log (
                decision_gate_audit_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                trading_account_id BIGINT UNSIGNED NOT NULL,
                venue VARCHAR(32) NOT NULL,
                asset_id BIGINT UNSIGNED NOT NULL,
                symbol VARCHAR(32) NULL,
                interval_code VARCHAR(16) NOT NULL,
                execution_mode VARCHAR(32) NOT NULL,
                permission_state VARCHAR(64) NULL,
                decision_state VARCHAR(64) NULL,
                decision_reason VARCHAR(128) NULL,
                execution_intent VARCHAR(64) NULL,
                action_type VARCHAR(64) NULL,
                requested_side VARCHAR(16) NULL,
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
                target_fraction DECIMAL(18,8) NOT NULL DEFAULT 0,
                reference_price_eur DECIMAL(28,10) NULL,
                passive_price_eur DECIMAL(28,10) NULL,
                plan_state VARCHAR(32) NOT NULL,
                updated_ts_utc DATETIME(6) NULL,
                PRIMARY KEY (execution_plan_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ],
    )


@contextmanager
def _disposable_schema() -> Iterator[Any]:
    from src.common.db import get_connection

    _require_disposable_mariadb_opt_in()
    name = f"synth_epe_{uuid.uuid4().hex[:12]}"
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
        _create_prerequisites(conn)
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


def _names(conn: Any, query: str, params: tuple[Any, ...]) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return {str(next(iter(row.values()))) for row in cur.fetchall()}


def test_migration_parser_keeps_stored_procedure_as_one_statement() -> None:
    statements = _split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert len(statements) == 4
    assert statements[1].startswith("CREATE PROCEDURE")
    assert "SIGNAL SQLSTATE '45000'" in statements[1]


def test_fresh_migration_and_clean_rerun_are_complete() -> None:
    with _disposable_schema() as conn:
        _apply_migration(conn)
        _apply_migration(conn)
        tables = _names(
            conn,
            "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",
            (),
        )
        plan_columns = _names(
            conn,
            "SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s",
            ("execution_plan",),
        )
        assert {"decision_gate_permission_evidence", "execution_attempt"} <= tables
        assert {
            "trading_account_id",
            "decision_gate_permission_evidence_id",
            "execution_intent",
            "action_type",
            "requested_side",
            "market",
        } <= plan_columns


def test_old_draft_table_and_historical_rows_are_preserved_but_not_authoritative() -> None:
    with _disposable_schema() as conn:
        _apply_statements(
            conn,
            [
                """
                CREATE TABLE execution_permission_evidence (
                    execution_permission_evidence_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    execution_plan_id BIGINT UNSIGNED NULL,
                    evidence_state VARCHAR(32) NOT NULL,
                    PRIMARY KEY (execution_permission_evidence_id)
                ) ENGINE=InnoDB
                """,
                "INSERT INTO execution_permission_evidence (execution_plan_id, evidence_state) VALUES (77, 'REVOKED')",
            ],
        )
        _apply_migration(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT execution_plan_id, evidence_state FROM execution_permission_evidence")
            assert cur.fetchone() == {"execution_plan_id": 77, "evidence_state": "REVOKED"}
            cur.execute("SELECT COUNT(*) AS cnt FROM decision_gate_permission_evidence")
            assert int(cur.fetchone()["cnt"]) == 0


def test_existing_execution_plan_columns_without_permission_tables_upgrade() -> None:
    with _disposable_schema() as conn:
        _apply_statements(
            conn,
            [
                """
                ALTER TABLE execution_plan
                    ADD trading_account_id BIGINT UNSIGNED NULL,
                    ADD decision_gate_permission_evidence_id BIGINT UNSIGNED NULL,
                    ADD market VARCHAR(32) NULL,
                    ADD execution_intent VARCHAR(64) NULL,
                    ADD action_type VARCHAR(64) NULL,
                    ADD requested_side VARCHAR(16) NULL
                """
            ],
        )
        _apply_migration(conn)
        assert "decision_gate_permission_evidence" in _names(
            conn,
            "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",
            (),
        )


def test_missing_indexes_foreign_keys_and_constraints_are_repaired() -> None:
    with _disposable_schema() as conn:
        _apply_migration(conn)
        _apply_statements(
            conn,
            [
                "ALTER TABLE execution_plan DROP FOREIGN KEY fk_execution_plan_permission_v2",
                "ALTER TABLE decision_gate_permission_evidence DROP FOREIGN KEY fk_dgpe_account_v2",
                "ALTER TABLE decision_gate_permission_evidence DROP CONSTRAINT chk_dgpe_window_v2",
                "ALTER TABLE execution_attempt DROP INDEX uq_execution_attempt_idempotency_v2",
            ],
        )
        _apply_migration(conn)
        constraints = _names(
            conn,
            "SELECT constraint_name FROM information_schema.table_constraints WHERE constraint_schema=DATABASE()",
            (),
        )
        indexes = _names(
            conn,
            "SELECT DISTINCT index_name FROM information_schema.statistics WHERE table_schema=DATABASE()",
            (),
        )
        assert {
            "fk_execution_plan_permission_v2",
            "fk_dgpe_account_v2",
            "chk_dgpe_window_v2",
        } <= constraints
        assert "uq_execution_attempt_idempotency_v2" in indexes


def test_nullable_empty_audit_provenance_is_repaired_to_not_null() -> None:
    with _disposable_schema() as conn:
        _apply_migration(conn)
        _apply_statements(
            conn,
            [
                "ALTER TABLE decision_gate_permission_evidence DROP FOREIGN KEY fk_dgpe_audit_v2",
                "ALTER TABLE decision_gate_permission_evidence DROP INDEX uq_dgpe_audit_v2",
                "ALTER TABLE decision_gate_permission_evidence MODIFY decision_gate_audit_log_id BIGINT UNSIGNED NULL",
            ],
        )
        _apply_migration(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT is_nullable FROM information_schema.columns
                WHERE table_schema=DATABASE() AND table_name='decision_gate_permission_evidence'
                  AND column_name='decision_gate_audit_log_id'
                """
            )
            assert cur.fetchone()["is_nullable"] == "NO"


def test_nullable_provenance_with_data_fails_with_precise_manual_repair_error() -> None:
    from pymysql.err import OperationalError

    with _disposable_schema() as conn:
        _apply_migration(conn)
        _apply_statements(
            conn,
            [
                "ALTER TABLE decision_gate_permission_evidence DROP FOREIGN KEY fk_dgpe_audit_v2",
                "ALTER TABLE decision_gate_permission_evidence DROP INDEX uq_dgpe_audit_v2",
                "ALTER TABLE decision_gate_permission_evidence MODIFY decision_gate_audit_log_id BIGINT UNSIGNED NULL",
                """
                INSERT INTO trading_account (account_code, venue, enabled, live_trading_enabled)
                VALUES ('TEST', 'bitvavo', 1, 1)
                """,
                """
                INSERT INTO decision_gate_permission_evidence (
                    decision_gate_audit_log_id, producer_name, provenance_signature,
                    trading_account_id, venue, asset_id, market, execution_intent,
                    action_type, requested_side, permission_state, decision_state,
                    evidence_state, permitted_ts_utc, valid_until_ts_utc
                ) VALUES (
                    NULL, 'decision_gate_permission_service_v1', REPEAT('a',88),
                    1, 'bitvavo', 42, 'BTC-EUR', 'PLACE_PASSIVE_LIMIT',
                    'PLACE_ORDER', 'BUY', 'EXECUTION_PERMITTED', 'EXECUTION_ALLOWED',
                    'ACTIVE', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6) + INTERVAL 5 MINUTE
                )
                """,
            ],
        )
        with pytest.raises(OperationalError) as exc_info:
            _apply_migration(conn)
        assert "EPE_MIGRATION_NULL_AUDIT_PROVENANCE_REQUIRES_MANUAL_REPAIR" in str(exc_info.value)


def test_wrong_execution_plan_account_type_fails_explicitly() -> None:
    from pymysql.err import OperationalError

    with _disposable_schema() as conn:
        _apply_statements(
            conn,
            ["ALTER TABLE execution_plan ADD trading_account_id VARCHAR(32) NULL"],
        )
        with pytest.raises(OperationalError) as exc_info:
            _apply_migration(conn)
        assert "EPE_MIGRATION_INCOMPATIBLE_EXECUTION_PLAN_TRADING_ACCOUNT_ID" in str(exc_info.value)


def test_partially_created_claim_table_fails_explicitly() -> None:
    from pymysql.err import OperationalError

    with _disposable_schema() as conn:
        _apply_statements(
            conn,
            [
                """
                CREATE TABLE execution_attempt (
                    execution_attempt_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    PRIMARY KEY (execution_attempt_id)
                ) ENGINE=InnoDB
                """
            ],
        )
        with pytest.raises(OperationalError) as exc_info:
            _apply_migration(conn)
        assert "EPE_MIGRATION_INCOMPATIBLE_EXECUTION_ATTEMPT_COLUMNS" in str(exc_info.value)


def _seed_claim_scope(conn: Any) -> tuple[int, int, int]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO trading_account (account_code, venue, enabled, live_trading_enabled) VALUES ('CLAIM', 'bitvavo', 1, 1)"
        )
        account_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO decision_gate_audit_log (
                trading_account_id, venue, asset_id, symbol, market, interval_code,
                execution_mode, permission_state, decision_state, decision_reason,
                execution_intent, action_type, requested_side, asof_ts_utc
            ) VALUES (%s, 'bitvavo', 42, 'BTC', 'BTC-EUR', '1h', 'LIVE',
                      'EXECUTION_PERMITTED', 'EXECUTION_ALLOWED', 'OK',
                      'PLACE_PASSIVE_LIMIT', 'PLACE_ORDER', 'BUY', %s)
            """,
            (account_id, CLAIM_NOW),
        )
        audit_id = int(cur.lastrowid)
        permitted = CLAIM_NOW - timedelta(minutes=1)
        valid_until = CLAIM_NOW + timedelta(minutes=5)
        payload = build_provenance_payload(
            decision_gate_audit_log_id=audit_id,
            trading_account_id=account_id,
            venue="bitvavo",
            asset_id=42,
            market="BTC-EUR",
            execution_intent="PLACE_PASSIVE_LIMIT",
            action_type="PLACE_ORDER",
            requested_side="BUY",
            permission_state="EXECUTION_PERMITTED",
            decision_state="EXECUTION_ALLOWED",
            permitted_ts_utc=permitted,
            valid_until_ts_utc=valid_until,
        )
        signature = sign_provenance(payload, PRODUCER_ENV)
        cur.execute(
            """
            INSERT INTO decision_gate_permission_evidence (
                decision_gate_audit_log_id, producer_name, provenance_signature,
                trading_account_id, venue, asset_id, market, execution_intent,
                action_type, requested_side, permission_state, decision_state,
                evidence_state, permitted_ts_utc, valid_until_ts_utc
            ) VALUES (%s, 'decision_gate_permission_service_v1', %s,
                      %s, 'bitvavo', 42, 'BTC-EUR', 'PLACE_PASSIVE_LIMIT',
                      'PLACE_ORDER', 'BUY', 'EXECUTION_PERMITTED', 'EXECUTION_ALLOWED',
                      'ACTIVE', %s, %s)
            """,
            (audit_id, signature, account_id, permitted, valid_until),
        )
        evidence_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO execution_plan (
                account_id, trading_account_id, decision_gate_permission_evidence_id,
                asset_id, sleeve_code, venue, market, side, desired_action,
                execution_intent, action_type, requested_side, execution_mode,
                plan_ts_utc, valid_until_ts_utc, target_fraction,
                reference_price_eur, passive_price_eur, plan_state
            ) VALUES (99, %s, %s, 42, 'CORE', 'bitvavo', 'BTC-EUR', 'BUY',
                      'SPREAD_CAPTURE_PASSIVE', 'PLACE_PASSIVE_LIMIT', 'PLACE_ORDER',
                      'BUY', 'LIVE', %s, %s,
                      0.1, 100, 99, 'IDLE')
            """,
            (account_id, evidence_id, CLAIM_NOW, valid_until),
        )
        plan_id = int(cur.lastrowid)
    conn.commit()
    return account_id, evidence_id, plan_id


def test_database_uniqueness_prevents_two_claims_for_same_plan_action() -> None:
    from pymysql.err import IntegrityError

    with _disposable_schema() as conn:
        _apply_migration(conn)
        account_id, evidence_id, plan_id = _seed_claim_scope(conn)
        insert_sql = """
            INSERT INTO execution_attempt (
                execution_plan_id, decision_gate_permission_evidence_id,
                trading_account_id, action_type, attempt_number, claim_token,
                claim_owner, claimed_ts_utc, authorization_snapshot_ts_utc,
                idempotency_key, broker_client_order_id, attempt_state
            ) VALUES (%s, %s, %s, 'PLACE_ORDER', 1, %s, 'worker',
                      UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), %s, %s, 'CLAIMED')
        """
        with conn.cursor() as cur:
            cur.execute(insert_sql, (plan_id, evidence_id, account_id, str(uuid.uuid4()), "a" * 64, str(uuid.uuid4())))
        conn.commit()
        with pytest.raises(IntegrityError):
            with conn.cursor() as cur:
                cur.execute(insert_sql, (plan_id, evidence_id, account_id, str(uuid.uuid4()), "c" * 64, str(uuid.uuid4())))
            conn.commit()
        conn.rollback()


def test_two_real_repository_transactions_allow_exactly_one_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.common.db import get_connection
    from src.execution import permission_gate_v1

    with _disposable_schema() as conn:
        _apply_migration(conn)
        _, _, plan_id = _seed_claim_scope(conn)
        database_name = conn.db.decode("utf-8") if isinstance(conn.db, bytes) else str(conn.db)
        monkeypatch.setattr(
            permission_gate_v1,
            "get_connection",
            lambda: get_connection(database=database_name),
        )
        claims: list[Any] = []
        errors: list[str] = []
        lock = threading.Lock()

        def claim() -> None:
            try:
                result = permission_gate_v1.ExecutionPermissionRepository().claim_live_action(
                    execution_plan_id=plan_id,
                    action_type="PLACE_ORDER",
                    claim_owner="ddl-concurrency-test",
                    env=CLAIM_ENV,
                    now_utc=CLAIM_NOW,
                )
                with lock:
                    claims.append(result)
            except permission_gate_v1.LiveExecutionPermissionError as exc:
                with lock:
                    errors.append(exc.code)

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive()

        assert len(claims) == 1
        assert errors == ["PLAN_NOT_ACTIONABLE"]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM execution_attempt WHERE execution_plan_id=%s",
                (plan_id,),
            )
            assert int(cur.fetchone()["cnt"]) == 1


def test_permission_lifecycle_constraints_preserve_valid_history() -> None:
    from pymysql.err import OperationalError

    with _disposable_schema() as conn:
        _apply_migration(conn)
        account_id, _, _ = _seed_claim_scope(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decision_gate_audit_log (
                    trading_account_id, venue, asset_id, symbol, market, interval_code,
                    execution_mode, permission_state, decision_state, execution_intent,
                    action_type, requested_side, asof_ts_utc
                ) VALUES (%s, 'bitvavo', 42, 'BTC', 'BTC-EUR', '1h', 'LIVE',
                          'EXECUTION_PERMITTED', 'EXECUTION_ALLOWED', 'PLACE_PASSIVE_LIMIT',
                          'PLACE_ORDER', 'BUY', UTC_TIMESTAMP(6))
                """,
                (account_id,),
            )
            audit_id = int(cur.lastrowid)
        conn.commit()
        with conn.cursor() as cur:
            with pytest.raises(OperationalError) as exc_info:
                cur.execute(
                    """
                    INSERT INTO decision_gate_permission_evidence (
                        decision_gate_audit_log_id, producer_name, provenance_signature,
                        trading_account_id, venue, asset_id, market, execution_intent,
                        action_type, requested_side, permission_state, decision_state,
                        evidence_state, permitted_ts_utc, valid_until_ts_utc
                    ) VALUES (%s, 'decision_gate_permission_service_v1', REPEAT('d',88),
                              %s, 'bitvavo', 42, 'BTC-EUR', 'PLACE_PASSIVE_LIMIT',
                              'PLACE_ORDER', 'BUY', 'EXECUTION_PERMITTED', 'EXECUTION_ALLOWED',
                              'REVOKED', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6) + INTERVAL 1 MINUTE)
                    """,
                    (audit_id, account_id),
                )
            assert exc_info.value.args[0] == 4025
        conn.rollback()


def test_case_insensitive_collation_cannot_admit_lowercase_side() -> None:
    from pymysql.err import OperationalError

    with _disposable_schema() as conn:
        _apply_migration(conn)
        account_id, _, _ = _seed_claim_scope(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decision_gate_audit_log (
                    trading_account_id, venue, asset_id, symbol, market, interval_code,
                    execution_mode, permission_state, decision_state, execution_intent,
                    action_type, requested_side, asof_ts_utc
                ) VALUES (%s, 'bitvavo', 42, 'BTC', 'BTC-EUR', '1h', 'LIVE',
                          'EXECUTION_PERMITTED', 'EXECUTION_ALLOWED', 'PLACE_PASSIVE_LIMIT',
                          'PLACE_ORDER', 'buy', UTC_TIMESTAMP(6))
                """,
                (account_id,),
            )
            audit_id = int(cur.lastrowid)
        conn.commit()
        with conn.cursor() as cur:
            with pytest.raises(OperationalError) as exc_info:
                cur.execute(
                    """
                    INSERT INTO decision_gate_permission_evidence (
                        decision_gate_audit_log_id, producer_name, provenance_signature,
                        trading_account_id, venue, asset_id, market, execution_intent,
                        action_type, requested_side, permission_state, decision_state,
                        evidence_state, permitted_ts_utc, valid_until_ts_utc
                    ) VALUES (%s, 'decision_gate_permission_service_v1', REPEAT('e',88),
                              %s, 'bitvavo', 42, 'BTC-EUR', 'PLACE_PASSIVE_LIMIT',
                              'PLACE_ORDER', 'buy', 'EXECUTION_PERMITTED', 'EXECUTION_ALLOWED',
                              'ACTIVE', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6) + INTERVAL 1 MINUTE)
                    """,
                    (audit_id, account_id),
                )
            assert exc_info.value.args[0] == 4025
        conn.rollback()
