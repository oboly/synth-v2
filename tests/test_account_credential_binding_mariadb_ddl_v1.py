from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import pytest


BASE_CREDENTIAL_MIGRATION = Path("db/migrations/20260609_trading_account_credential_v1.sql")
VALID_PRIVATE_READ_MIGRATION = Path(
    "db/migrations/20260609_trading_account_credential_add_valid_private_read.sql"
)
BINDING_MIGRATION = Path("db/migrations/20260721_account_credential_binding_contract_v1.sql")

TEMP_DB_PREFIX = "synth_tac_binding_ddl_tmp"
DIAGNOSTIC_CODE = "ACCOUNT_CREDENTIAL_BINDING_DUPLICATE_ACTIVE_PRECONDITION_FAILED"
GUARD_OBJECT_NAME = "tac_binding_duplicate_active_guard_v1"
ADDED_BINDING_COLUMNS = frozenset(
    {
        "credential_source",
        "permission_scope",
        "allowed_private_read",
        "allowed_order_write",
        "allowed_withdrawal",
        "last_validation_error_code",
        "active_permission_scope",
    }
)
ADDED_BINDING_CONSTRAINTS = frozenset(
    {
        "chk_tac_credential_source_v1",
        "chk_tac_permission_scope_v1",
        "chk_tac_capability_flags_v1",
    }
)
ADDED_BINDING_INDEXES = frozenset({"uq_tac_active_account_venue_scope_v1"})


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


def _read_statements(path: Path) -> list[str]:
    return _split_sql_statements(path.read_text(encoding="utf-8"))


def _apply_statements(conn: object, statements: Iterable[str]) -> None:
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


def _apply_migration(conn: object, path: Path) -> None:
    _apply_statements(conn, _read_statements(path))


def _temp_db_name(suffix: str) -> str:
    return f"{TEMP_DB_PREFIX}_{suffix}_{os.getpid()}"


def _create_database(name: str) -> None:
    from src.common.db import get_connection
    from pymysql.err import OperationalError

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
                    pytest.skip(
                        "Configured DB user lacks CREATE/DROP DATABASE privilege "
                        "for disposable schema validation."
                    )
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


def _create_trading_account_prerequisite(conn: object) -> None:
    _apply_statements(
        conn,
        [
            """
            CREATE TABLE IF NOT EXISTS trading_account (
                trading_account_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                account_code VARCHAR(63) NOT NULL,
                venue VARCHAR(32) NOT NULL,
                account_mode VARCHAR(32) NOT NULL DEFAULT 'paper',
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                live_trading_enabled TINYINT(1) NOT NULL DEFAULT 0,
                created_ts_utc DATETIME NOT NULL,
                PRIMARY KEY (trading_account_id),
                UNIQUE KEY uq_trading_account_account_code (account_code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ],
    )


def _apply_credential_base_chain(conn: object) -> None:
    _create_trading_account_prerequisite(conn)
    _apply_migration(conn, BASE_CREDENTIAL_MIGRATION)
    _apply_migration(conn, VALID_PRIVATE_READ_MIGRATION)


def _insert_account(cur: object, account_id: int, account_code: str) -> None:
    cur.execute(
        """
        INSERT INTO trading_account (
            trading_account_id, account_code, venue, account_mode, enabled,
            live_trading_enabled, created_ts_utc
        ) VALUES (%s, %s, 'bitvavo', 'paper', 1, 0, '2026-07-21 00:00:00')
        """,
        (account_id, account_code),
    )


def _insert_credential(
    cur: object,
    *,
    credential_id: int,
    account_id: int,
    status: str,
    fingerprint: str,
    validation_state: str = "VALID_PRIVATE_READ",
) -> None:
    cur.execute(
        """
        INSERT INTO trading_account_credential (
            trading_account_credential_id,
            trading_account_id,
            venue,
            credential_kind,
            encrypted_envelope,
            encryption_algorithm,
            key_version,
            credential_fingerprint,
            credential_status,
            validation_state,
            created_ts_utc
        ) VALUES (
            %s, %s, 'bitvavo', 'API_KEY_SECRET', %s, 'AESGCM-256', 'v1',
            %s, %s, %s, '2026-07-21 00:00:00'
        )
        """,
        (
            credential_id,
            account_id,
            '{"alg":"AESGCM-256","ct":"not-secret-test-ciphertext"}',
            fingerprint,
            status,
            validation_state,
        ),
    )


def _add_permission_scope_only_partial_schema(conn: object) -> None:
    _apply_statements(
        conn,
        [
            """
            ALTER TABLE trading_account_credential
                ADD COLUMN permission_scope VARCHAR(32) NOT NULL
                    DEFAULT 'READ_ONLY_PRIVATE'
                    COMMENT 'READ_ONLY_PRIVATE | TRADE_EXECUTION'
            """,
        ],
    )


def _column_names(conn: object) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM trading_account_credential")
        return {str(row["Field"]) for row in cur.fetchall()}


def _constraint_names(conn: object) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT CONSTRAINT_NAME
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = DATABASE()
              AND TABLE_NAME = 'trading_account_credential'
            """
        )
        return {str(row["CONSTRAINT_NAME"]) for row in cur.fetchall()}


def _index_names(conn: object) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW INDEX FROM trading_account_credential")
        return {str(row["Key_name"]) for row in cur.fetchall()}


def _persistent_guard_artifacts(conn: object) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT TABLE_NAME AS artifact_name
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            UNION ALL
            SELECT ROUTINE_NAME AS artifact_name
            FROM information_schema.ROUTINES
            WHERE ROUTINE_SCHEMA = DATABASE()
              AND ROUTINE_NAME = %s
            """,
            (GUARD_OBJECT_NAME, GUARD_OBJECT_NAME),
        )
        return {str(row["artifact_name"]) for row in cur.fetchall()}


def _assert_no_partial_binding_ddl(
    conn: object,
    *,
    allowed_existing_columns: set[str] | None = None,
) -> None:
    allowed_columns = allowed_existing_columns or set()

    assert not (ADDED_BINDING_COLUMNS - allowed_columns) & _column_names(conn)
    assert not ADDED_BINDING_CONSTRAINTS & _constraint_names(conn)
    assert not ADDED_BINDING_INDEXES & _index_names(conn)
    assert not _persistent_guard_artifacts(conn)


def _assert_guard_table_not_accessible(conn: object) -> None:
    from pymysql.err import OperationalError, ProgrammingError

    with conn.cursor() as cur:
        with pytest.raises((OperationalError, ProgrammingError)):
            cur.execute(f"SELECT COUNT(*) FROM `{GUARD_OBJECT_NAME}`")


def _cleanup_temp_db(name: str) -> None:
    try:
        _drop_database(name)
    except Exception:
        pass


def test_migration_chain_order_places_valid_private_read_before_binding() -> None:
    from src.web.run_website_registration_db_migration_v1 import MIGRATION_CHAIN

    chain = [path.name for path in MIGRATION_CHAIN]

    assert chain.index(VALID_PRIVATE_READ_MIGRATION.name) < chain.index(BINDING_MIGRATION.name)


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_account_credential_binding_migration_empty_schema_reruns_in_mariadb() -> None:
    from src.common.db import get_connection

    temp_db = _temp_db_name("empty")
    _create_database(temp_db)
    conn = get_connection(database=temp_db)
    try:
        _apply_credential_base_chain(conn)

        _apply_migration(conn, BINDING_MIGRATION)
        _apply_migration(conn, BINDING_MIGRATION)

        columns = _column_names(conn)
        assert "credential_source" in columns
        assert "permission_scope" in columns
        assert "allowed_private_read" in columns
        assert "allowed_order_write" in columns
        assert "allowed_withdrawal" in columns
        assert "last_validation_error_code" in columns
        assert "active_permission_scope" in columns

        with conn.cursor() as cur:
            cur.execute(
                """
                SHOW INDEX FROM trading_account_credential
                WHERE Key_name = 'uq_tac_active_account_venue_scope_v1'
                """
            )
            assert len(cur.fetchall()) == 3
    finally:
        conn.close()
        _cleanup_temp_db(temp_db)


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_account_credential_binding_migration_valid_rows_and_rerun_in_mariadb() -> None:
    from src.common.db import get_connection
    from pymysql.err import IntegrityError, OperationalError

    temp_db = _temp_db_name("valid")
    _create_database(temp_db)
    conn = get_connection(database=temp_db)
    try:
        _apply_credential_base_chain(conn)
        with conn.cursor() as cur:
            _insert_account(cur, 1, "bitvavo_primary")
            _insert_account(cur, 2, "bitvavo_secondary")
            _insert_credential(
                cur,
                credential_id=101,
                account_id=1,
                status="ACTIVE",
                fingerprint="a" * 64,
            )
            _insert_credential(
                cur,
                credential_id=102,
                account_id=1,
                status="REVOKED",
                fingerprint="b" * 64,
                validation_state="UNVALIDATED",
            )
            _insert_credential(
                cur,
                credential_id=103,
                account_id=1,
                status="ROTATED",
                fingerprint="c" * 64,
            )
            _insert_credential(
                cur,
                credential_id=104,
                account_id=1,
                status="INVALID",
                fingerprint="d" * 64,
                validation_state="INVALID_CREDENTIALS",
            )
            _insert_credential(
                cur,
                credential_id=201,
                account_id=2,
                status="ACTIVE",
                fingerprint="e" * 64,
            )
        conn.commit()

        _apply_migration(conn, BINDING_MIGRATION)
        _apply_migration(conn, BINDING_MIGRATION)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    trading_account_credential_id,
                    credential_source,
                    permission_scope,
                    allowed_private_read,
                    allowed_order_write,
                    allowed_withdrawal,
                    active_permission_scope
                FROM trading_account_credential
                ORDER BY trading_account_credential_id
                """
            )
            rows = cur.fetchall()

            assert rows[0]["credential_source"] == "db_encrypted"
            assert rows[0]["permission_scope"] == "READ_ONLY_PRIVATE"
            assert rows[0]["allowed_private_read"] == 1
            assert rows[0]["allowed_order_write"] == 0
            assert rows[0]["allowed_withdrawal"] == 0
            assert rows[0]["active_permission_scope"] == "READ_ONLY_PRIVATE"
            assert rows[1]["active_permission_scope"] is None
            assert rows[2]["active_permission_scope"] is None
            assert rows[3]["active_permission_scope"] is None

            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO trading_account_credential (
                        trading_account_id, venue, credential_kind, encrypted_envelope,
                        encryption_algorithm, key_version, credential_fingerprint,
                        credential_status, validation_state, created_ts_utc
                    ) VALUES (
                        1, 'bitvavo', 'API_KEY_SECRET', '{}', 'AESGCM-256', 'v1',
                        %s, 'ACTIVE', 'VALID_PRIVATE_READ', '2026-07-21 00:01:00'
                    )
                    """,
                    ("f" * 64,),
                )
            conn.rollback()

            cur.execute(
                """
                INSERT INTO trading_account_credential (
                    trading_account_id, venue, credential_kind, encrypted_envelope,
                    encryption_algorithm, key_version, credential_fingerprint,
                    credential_status, validation_state, permission_scope,
                    allowed_order_write, created_ts_utc
                ) VALUES (
                    1, 'bitvavo', 'API_KEY_SECRET', '{}', 'AESGCM-256', 'v1',
                    %s, 'ACTIVE', 'VALID_PRIVATE_READ', 'TRADE_EXECUTION',
                    1, '2026-07-21 00:03:00'
                )
                """,
                ("2" * 64,),
            )
            cur.execute(
                """
                INSERT INTO trading_account_credential (
                    trading_account_id, venue, credential_kind, encrypted_envelope,
                    encryption_algorithm, key_version, credential_fingerprint,
                    credential_status, validation_state, created_ts_utc
                ) VALUES (
                    1, 'bitvavo', 'API_KEY_SECRET', '{}', 'AESGCM-256', 'v1',
                    %s, 'REVOKED', 'UNVALIDATED', '2026-07-21 00:04:00'
                )
                """,
                ("3" * 64,),
            )

            with pytest.raises(OperationalError):
                cur.execute(
                    """
                    INSERT INTO trading_account_credential (
                        trading_account_id, venue, credential_kind, encrypted_envelope,
                        encryption_algorithm, key_version, credential_fingerprint,
                        credential_status, validation_state, permission_scope,
                        allowed_order_write, created_ts_utc
                    ) VALUES (
                        2, 'bitvavo', 'API_KEY_SECRET', '{}', 'AESGCM-256', 'v1',
                        %s, 'ACTIVE', 'VALID_PRIVATE_READ', 'READ_ONLY_PRIVATE',
                        1, '2026-07-21 00:05:00'
                    )
                    """,
                    ("4" * 64,),
                )
            conn.rollback()

            with pytest.raises(OperationalError):
                cur.execute(
                    """
                    INSERT INTO trading_account_credential (
                        trading_account_id, venue, credential_kind, encrypted_envelope,
                        encryption_algorithm, key_version, credential_fingerprint,
                        credential_status, validation_state, allowed_withdrawal,
                        created_ts_utc
                    ) VALUES (
                        2, 'bitvavo', 'API_KEY_SECRET', '{}', 'AESGCM-256', 'v1',
                        %s, 'ACTIVE', 'VALID_PRIVATE_READ', 1,
                        '2026-07-21 00:06:00'
                    )
                    """,
                    ("5" * 64,),
                )
            conn.rollback()
    finally:
        conn.close()
        _cleanup_temp_db(temp_db)


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_duplicate_active_precondition_aborts_before_schema_mutation_in_mariadb() -> None:
    from src.common.db import get_connection

    temp_db = _temp_db_name("duplicate")
    _create_database(temp_db)
    conn = get_connection(database=temp_db)
    try:
        _apply_credential_base_chain(conn)
        with conn.cursor() as cur:
            _insert_account(cur, 1, "bitvavo_duplicate")
            _insert_credential(
                cur,
                credential_id=101,
                account_id=1,
                status="ACTIVE",
                fingerprint="a" * 64,
            )
            _insert_credential(
                cur,
                credential_id=102,
                account_id=1,
                status="ACTIVE",
                fingerprint="b" * 64,
            )
        conn.commit()

        before_columns = _column_names(conn)
        before_constraints = _constraint_names(conn)
        before_indexes = _index_names(conn)
        with pytest.raises(Exception) as exc:
            _apply_migration(conn, BINDING_MIGRATION)

        assert DIAGNOSTIC_CODE in str(exc.value)
        assert _column_names(conn) == before_columns
        assert _constraint_names(conn) == before_constraints
        assert _index_names(conn) == before_indexes
        _assert_no_partial_binding_ddl(conn)

        conn.close()
        conn = get_connection(database=temp_db)
        _assert_guard_table_not_accessible(conn)
        _assert_no_partial_binding_ddl(conn)
    finally:
        conn.close()
        _cleanup_temp_db(temp_db)


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_permission_scope_partial_duplicate_precondition_aborts_before_further_ddl_in_mariadb() -> None:
    from src.common.db import get_connection

    temp_db = _temp_db_name("partial_duplicate")
    _create_database(temp_db)
    conn = get_connection(database=temp_db)
    try:
        _apply_credential_base_chain(conn)
        _add_permission_scope_only_partial_schema(conn)
        with conn.cursor() as cur:
            _insert_account(cur, 1, "bitvavo_partial_duplicate")
            _insert_credential(
                cur,
                credential_id=101,
                account_id=1,
                status="ACTIVE",
                fingerprint="a" * 64,
            )
            _insert_credential(
                cur,
                credential_id=102,
                account_id=1,
                status="ACTIVE",
                fingerprint="b" * 64,
            )
        conn.commit()

        before_columns = _column_names(conn)
        before_constraints = _constraint_names(conn)
        before_indexes = _index_names(conn)
        with pytest.raises(Exception) as exc:
            _apply_migration(conn, BINDING_MIGRATION)

        assert DIAGNOSTIC_CODE in str(exc.value)
        assert _column_names(conn) == before_columns
        assert _constraint_names(conn) == before_constraints
        assert _index_names(conn) == before_indexes
        _assert_no_partial_binding_ddl(
            conn,
            allowed_existing_columns={"permission_scope"},
        )

        conn.close()
        conn = get_connection(database=temp_db)
        _assert_guard_table_not_accessible(conn)
        _assert_no_partial_binding_ddl(
            conn,
            allowed_existing_columns={"permission_scope"},
        )
    finally:
        conn.close()
        _cleanup_temp_db(temp_db)


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_permission_scope_partial_nonconflicting_schema_completes_in_mariadb() -> None:
    from src.common.db import get_connection

    temp_db = _temp_db_name("partial_valid")
    _create_database(temp_db)
    conn = get_connection(database=temp_db)
    try:
        _apply_credential_base_chain(conn)
        _add_permission_scope_only_partial_schema(conn)
        with conn.cursor() as cur:
            _insert_account(cur, 1, "bitvavo_partial_valid")
            _insert_credential(
                cur,
                credential_id=101,
                account_id=1,
                status="ACTIVE",
                fingerprint="a" * 64,
            )
            _insert_credential(
                cur,
                credential_id=102,
                account_id=1,
                status="ROTATED",
                fingerprint="b" * 64,
            )
            _insert_credential(
                cur,
                credential_id=103,
                account_id=1,
                status="REVOKED",
                fingerprint="c" * 64,
                validation_state="UNVALIDATED",
            )
        conn.commit()

        _apply_migration(conn, BINDING_MIGRATION)
        _apply_migration(conn, BINDING_MIGRATION)

        columns = _column_names(conn)
        assert ADDED_BINDING_COLUMNS <= columns
        assert ADDED_BINDING_CONSTRAINTS <= _constraint_names(conn)
        assert ADDED_BINDING_INDEXES <= _index_names(conn)
        assert not _persistent_guard_artifacts(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    trading_account_credential_id,
                    credential_status,
                    permission_scope,
                    active_permission_scope
                FROM trading_account_credential
                ORDER BY trading_account_credential_id
                """
            )
            rows = cur.fetchall()

        assert rows[0]["permission_scope"] == "READ_ONLY_PRIVATE"
        assert rows[0]["active_permission_scope"] == "READ_ONLY_PRIVATE"
        assert rows[1]["credential_status"] == "ROTATED"
        assert rows[1]["active_permission_scope"] is None
        assert rows[2]["credential_status"] == "REVOKED"
        assert rows[2]["active_permission_scope"] is None
    finally:
        conn.close()
        _cleanup_temp_db(temp_db)
