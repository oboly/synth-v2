from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pymysql
import pytest
from pymysql.cursors import DictCursor
from pymysql.err import IntegrityError, OperationalError


BASE_MIGRATION = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
STATUS_MIGRATION = Path("db/migrations/20260706_native_short_scope_status_persistence_v1.sql")
MIGRATION = Path("db/migrations/20260718_native_short_scope_administration_v1.sql")
TEMP_DB_PREFIX = "synth_native_short_scope_admin_v1_tmp"

_REQUIRED_ENV = (
    "SYNTH_TEST_MARIADB_HOST",
    "SYNTH_TEST_MARIADB_PORT",
    "SYNTH_TEST_MARIADB_USER",
    "SYNTH_TEST_MARIADB_PASSWORD",
    "SYNTH_TEST_MARIADB_ADMIN_DATABASE",
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


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
            statements.append(statement[:-1] if statement.endswith(";") else statement)
            buffer = []
    if buffer:
        statements.append("\n".join(buffer).strip())
    return statements


def _explicit_test_config() -> dict[str, str]:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        pytest.skip(
            "explicit disposable MariaDB configuration is absent: "
            + ", ".join(missing)
        )
    if os.environ.get("SYNTH_TEST_MARIADB_DISPOSABLE") != "1":
        pytest.skip("SYNTH_TEST_MARIADB_DISPOSABLE=1 is required")
    return {name: os.environ[name] for name in _REQUIRED_ENV}


def _connect(config: dict[str, str], *, database: str) -> Any:
    return pymysql.connect(
        host=config["SYNTH_TEST_MARIADB_HOST"],
        port=int(config["SYNTH_TEST_MARIADB_PORT"]),
        user=config["SYNTH_TEST_MARIADB_USER"],
        password=config["SYNTH_TEST_MARIADB_PASSWORD"],
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


@contextmanager
def _disposable_schema(label: str) -> Iterator[tuple[Any, dict[str, str], str]]:
    config = _explicit_test_config()
    database = f"{TEMP_DB_PREFIX}_{label}_{os.getpid()}"
    admin_database = config["SYNTH_TEST_MARIADB_ADMIN_DATABASE"]
    admin = _connect(config, database=admin_database)
    connection = None
    try:
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
            cursor.execute(
                f"CREATE DATABASE `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        admin.commit()
        connection = _connect(config, database=database)
        yield connection, config, database
    finally:
        if connection is not None:
            connection.close()
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
        admin.commit()
        admin.close()


def _apply(connection: Any, path: Path) -> None:
    with connection.cursor() as cursor:
        for statement in _split_sql_statements(path.read_text(encoding="utf-8")):
            cursor.execute(statement)
    connection.commit()


def _apply_prerequisites(connection: Any) -> None:
    _apply(connection, BASE_MIGRATION)
    _apply(connection, STATUS_MIGRATION)


def _seed_legacy_rows(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO native_short_map_scope_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, scope_support_state
            ) VALUES ('bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED')
            """
        )
        cursor.execute(
            """
            INSERT INTO native_short_scope_support_event_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, scope_support_state,
                event_ts_utc, source_name, source_version
            ) VALUES (
                'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                '2026-07-01 00:00:00.000000', 'legacy_fixture', 'v1'
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO native_short_scope_cadence_config_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, cadence_contract_version,
                target_evaluation_interval,
                primary_source_freshness_limit_seconds,
                supporting_source_freshness_limit_seconds,
                evaluation_grace_seconds, recent_scope_grace_seconds,
                effective_from_utc, effective_to_utc, is_active
            ) VALUES (
                'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'legacy_v1',
                '1h', 43200, 10800, 900, 3600,
                '2026-07-01 00:00:00.000000', NULL, 1
            )
            """
        )
    connection.commit()


def _insert_operation(
    connection: Any,
    *,
    operation_uuid: str,
    symbol: str,
    operation_type: str = "PROMOTE_SCOPE",
    generation_before: int | None = None,
    generation_after: int | None = None,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO native_short_scope_admin_operation_v1 (
                operation_uuid, operation_type,
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval,
                actor_type, actor_id, trigger_type, request_source, reason,
                requested_at_utc, repository_sha, schema_version,
                metadata_digest, started_at_utc,
                support_generation_before, support_generation_after
            ) VALUES (
                %s, %s,
                'bitvavo', %s, 'EUR', 'SHORT', '4h', '1h',
                'TEST', 'migration-test', 'TEST',
                'tests/test_native_short_scope_administration_migration_v1.py',
                'explicit disposable MariaDB constraint test',
                '2026-07-18 10:00:00.000000', %s,
                'native_short_scope_administration_v1', %s,
                '2026-07-18 10:00:00.000000', %s, %s
            )
            """,
            (
                operation_uuid,
                operation_type,
                symbol,
                "0" * 40,
                "1" * 64,
                generation_before,
                generation_after,
            ),
        )
        operation_id = int(cursor.lastrowid)
    connection.commit()
    return operation_id


def _insert_cadence(
    connection: Any,
    *,
    symbol: str,
    version: str,
    effective_from: str,
    effective_to: str | None,
    is_active: int,
    activation_operation_id: int | None,
    deactivation_operation_id: int | None,
    support_generation: int | None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO native_short_scope_cadence_config_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, cadence_contract_version,
                target_evaluation_interval,
                primary_source_freshness_limit_seconds,
                supporting_source_freshness_limit_seconds,
                evaluation_grace_seconds, recent_scope_grace_seconds,
                effective_from_utc, effective_to_utc, is_active,
                activation_operation_id, deactivation_operation_id,
                support_generation
            ) VALUES (
                'bitvavo', %s, 'EUR', 'SHORT', '4h', '1h', %s,
                '1h', 43200, 10800, 900, 3600,
                %s, %s, %s, %s, %s, %s
            )
            """,
            (
                symbol,
                version,
                effective_from,
                effective_to,
                is_active,
                activation_operation_id,
                deactivation_operation_id,
                support_generation,
            ),
        )


def _insert_support_event(
    connection: Any,
    *,
    symbol: str,
    operation_id: int | None,
    generation: int | None,
    event_ts: str,
    state: str = "SUPPORTED",
    source_name: str = "admin_test",
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO native_short_scope_support_event_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, scope_support_state,
                scope_admin_operation_id, support_generation, event_ts_utc,
                source_name, source_version
            ) VALUES (
                'bitvavo', %s, 'EUR', 'SHORT', '4h', '1h', %s,
                %s, %s, %s, %s, 'v1'
            )
            """,
            (symbol, state, operation_id, generation, event_ts, source_name),
        )


def _expect_rejected(connection: Any, action: Any) -> Exception:
    with pytest.raises((IntegrityError, OperationalError)) as caught:
        action()
    connection.rollback()
    return caught.value


def test_migration_is_forward_only_legacy_safe_and_fail_closed() -> None:
    sql = _sql()
    assert MIGRATION.name.startswith("20260718_")
    # Forward-only, single-application: CREATE TABLE is idempotent (IF NOT
    # EXISTS, per the schema-family convention) while ALTERs are not re-runnable.
    assert "CREATE TABLE IF NOT EXISTS native_short_scope_admin_operation_v1" in sql
    assert "support_generation BIGINT UNSIGNED NULL" in sql
    assert "last_scope_admin_operation_id" not in sql
    assert "native_short_writer_scope_fence_v1" not in sql
    assert "GENERATED ALWAYS AS" in sql
    assert "CASE WHEN is_active = 1 THEN 1 ELSE NULL END" in sql
    assert "uq_native_short_scope_cadence_config_v1_active_slot" in sql
    assert "DROP INDEX uq_native_short_scope_cadence_config_v1_scope_version" in sql
    assert "uq_native_short_scope_cadence_config_v1_profile_generation" in sql
    assert "CREATE TEMPORARY TABLE native_short_scope_admin_preflight_v1" in sql
    assert "HAVING COUNT(*) > 1" in sql
    assert "later.cadence_config_id > earlier.cadence_config_id" in sql
    assert "UPDATE " not in sql.upper()
    assert "DELETE FROM" not in sql.upper()
    assert "INSERT INTO native_short_scope_admin_operation_v1" not in sql
    assert "INSERT INTO native_short_scope_support_event_v1" not in sql
    assert "INSERT INTO native_short_scope_cadence_config_v1" not in sql


def test_migration_declares_required_constraints_and_foreign_keys() -> None:
    sql = _sql()
    for expected in (
        "uq_native_short_scope_admin_operation_v1_uuid",
        "uq_native_short_scope_admin_operation_v1_id_scope",
        "chk_native_short_scope_admin_operation_v1_terminal",
        "chk_native_short_scope_admin_operation_v1_generation",
        "fk_native_short_scope_support_event_v1_admin_operation",
        "uq_native_short_scope_support_event_v1_scope_generation",
        "uq_native_short_scope_support_event_v1_admin_operation",
        "chk_native_short_scope_support_event_v1_admin_shape",
        "fk_native_short_scope_cadence_config_v1_activation_operation",
        "fk_native_short_scope_cadence_config_v1_deactivation_operation",
        "chk_native_short_scope_cadence_config_v1_active_effective",
        "chk_native_short_scope_cadence_config_v1_activation_shape",
        "chk_native_short_scope_cadence_config_v1_deactivation_shape",
        "chk_native_short_scope_cadence_config_v1_managed_state",
        # NULL-safe legacy slot + slot-based profile-generation uniqueness (Fix 1).
        "effective_generation_slot",
        "COALESCE(support_generation, 0)",
        "uq_native_short_scope_cadence_config_v1_profile_generation",
        "duplicate_legacy_cadence_profiles",
    ):
        assert expected in sql


def test_migration_declares_scope_bound_operation_foreign_keys() -> None:
    # Cross-scope attribution guard (Fix 2): the operation FKs must carry the full
    # six-part scope key, not only the numeric operation id, and reference the
    # scope-bound candidate key on the operation ledger.
    sql = _sql()
    scope_columns = (
        "venue",
        "symbol",
        "quote_currency",
        "fib_trading_horizon",
        "primary_interval",
        "supporting_interval",
    )
    for fk_column in (
        "scope_admin_operation_id",
        "activation_operation_id",
        "deactivation_operation_id",
    ):
        assert fk_column in sql
    # The scope-bound FK target candidate key must exist on the ledger.
    assert "uq_native_short_scope_admin_operation_v1_id_scope" in sql
    # Each scope column participates in the composite FK definitions.
    for column in scope_columns:
        assert column in sql


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 with explicit disposable MariaDB settings.",
)
def test_fresh_migration_and_constraints_in_disposable_mariadb() -> None:
    with _disposable_schema("constraints") as (connection, config, database):
        _apply_prerequisites(connection)
        _seed_legacy_rows(connection)
        _apply(connection, MIGRATION)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT support_generation FROM native_short_map_scope_v1 WHERE symbol='BTC'"
            )
            assert cursor.fetchone()["support_generation"] is None
            cursor.execute(
                """
                SELECT scope_admin_operation_id, support_generation
                FROM native_short_scope_support_event_v1 WHERE symbol='BTC'
                """
            )
            assert cursor.fetchone() == {
                "scope_admin_operation_id": None,
                "support_generation": None,
            }
            cursor.execute(
                """
                SELECT activation_operation_id, deactivation_operation_id,
                       support_generation, active_slot
                FROM native_short_scope_cadence_config_v1 WHERE symbol='BTC'
                """
            )
            assert cursor.fetchone() == {
                "activation_operation_id": None,
                "deactivation_operation_id": None,
                "support_generation": None,
                "active_slot": 1,
            }
            cursor.execute("SELECT COUNT(*) AS row_count FROM native_short_scope_admin_operation_v1")
            assert cursor.fetchone()["row_count"] == 0

        op1 = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000001",
            symbol="ETH",
            generation_after=1,
        )
        op2 = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000002",
            symbol="ETH",
            generation_before=1,
            generation_after=2,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO native_short_scope_support_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon,
                    primary_interval, supporting_interval, scope_support_state,
                    scope_admin_operation_id, support_generation, event_ts_utc,
                    source_name, source_version
                ) VALUES (
                    'bitvavo', 'ETH', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                    %s, 1, '2026-07-18 10:00:00', 'admin_test', 'v1'
                )
                """,
                (op1,),
            )
        connection.commit()

        _expect_rejected(
            connection,
            lambda: connection.cursor().execute(
                """
                INSERT INTO native_short_scope_support_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon,
                    primary_interval, supporting_interval, scope_support_state,
                    scope_admin_operation_id, support_generation, event_ts_utc,
                    source_name, source_version
                ) VALUES (
                    'bitvavo', 'ETH', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                    %s, 1, '2026-07-18 11:00:00', 'admin_test', 'v1'
                )
                """,
                (op2,),
            ),
        )
        _expect_rejected(
            connection,
            lambda: connection.cursor().execute(
                """
                INSERT INTO native_short_scope_support_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon,
                    primary_interval, supporting_interval, scope_support_state,
                    scope_admin_operation_id, support_generation, event_ts_utc,
                    source_name, source_version
                ) VALUES (
                    'bitvavo', 'SOL', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                    %s, NULL, '2026-07-18 11:00:00', 'admin_test', 'v1'
                )
                """,
                (op2,),
            ),
        )
        _expect_rejected(
            connection,
            lambda: connection.cursor().execute(
                """
                INSERT INTO native_short_scope_support_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon,
                    primary_interval, supporting_interval, scope_support_state,
                    scope_admin_operation_id, support_generation, event_ts_utc,
                    source_name, source_version
                ) VALUES (
                    'bitvavo', 'SOL', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                    NULL, 0, '2026-07-18 11:00:00', 'admin_test', 'v1'
                )
                """
            ),
        )
        _expect_rejected(
            connection,
            lambda: connection.cursor().execute(
                """
                INSERT INTO native_short_scope_support_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon,
                    primary_interval, supporting_interval, scope_support_state,
                    scope_admin_operation_id, support_generation, event_ts_utc,
                    source_name, source_version
                ) VALUES (
                    'bitvavo', 'SOL', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                    999999, 3, '2026-07-18 11:00:00', 'admin_test', 'v1'
                )
                """
            ),
        )
        with connection.cursor() as cursor:
            for hour in (11, 12):
                cursor.execute(
                    """
                    INSERT INTO native_short_scope_support_event_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon,
                        primary_interval, supporting_interval, scope_support_state,
                        scope_admin_operation_id, support_generation, event_ts_utc,
                        source_name, source_version
                    ) VALUES (
                        'bitvavo', 'XRP', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                        NULL, NULL, %s, 'legacy_test', 'v1'
                    )
                    """,
                    (f"2026-07-18 {hour}:00:00",),
                )
        connection.commit()

        eth5 = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000005",
            symbol="ETH",
            generation_after=5,
        )
        eth7 = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000007",
            symbol="ETH",
            generation_before=5,
            generation_after=7,
        )
        _insert_cadence(
            connection,
            symbol="ETH",
            version="managed_g5",
            effective_from="2026-07-18 10:00:00",
            effective_to=None,
            is_active=1,
            activation_operation_id=eth5,
            deactivation_operation_id=None,
            support_generation=5,
        )
        connection.commit()
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="ETH",
                version="managed_g7",
                effective_from="2026-07-18 11:00:00",
                effective_to=None,
                is_active=1,
                activation_operation_id=eth7,
                deactivation_operation_id=None,
                support_generation=7,
            ),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT support_generation, is_active
                FROM native_short_scope_cadence_config_v1
                WHERE symbol='ETH'
                """
            )
            assert cursor.fetchall() == [{"support_generation": 5, "is_active": 1}]

        sol3_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000013",
            symbol="SOL",
            generation_after=3,
        )
        sol3_deactivate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000014",
            symbol="SOL",
            operation_type="REMOVE_SCOPE",
            generation_before=3,
            generation_after=4,
        )
        sol5_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000015",
            symbol="SOL",
            generation_after=5,
        )
        sol5_deactivate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000016",
            symbol="SOL",
            operation_type="REMOVE_SCOPE",
            generation_before=5,
            generation_after=6,
        )
        sol7_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000017",
            symbol="SOL",
            generation_after=7,
        )
        _insert_cadence(
            connection,
            symbol="SOL",
            version="managed_g3",
            effective_from="2026-07-01 00:00:00",
            effective_to="2026-07-02 00:00:00",
            is_active=0,
            activation_operation_id=sol3_activate,
            deactivation_operation_id=sol3_deactivate,
            support_generation=3,
        )
        _insert_cadence(
            connection,
            symbol="SOL",
            version="managed_g5",
            effective_from="2026-07-02 00:00:00",
            effective_to="2026-07-03 00:00:00",
            is_active=0,
            activation_operation_id=sol5_activate,
            deactivation_operation_id=sol5_deactivate,
            support_generation=5,
        )
        _insert_cadence(
            connection,
            symbol="SOL",
            version="managed_g7",
            effective_from="2026-07-03 00:00:00",
            effective_to=None,
            is_active=1,
            activation_operation_id=sol7_activate,
            deactivation_operation_id=None,
            support_generation=7,
        )
        connection.commit()

        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="XLM",
                version="closed_active",
                effective_from="2026-07-01 00:00:00",
                effective_to="2026-07-02 00:00:00",
                is_active=1,
                activation_operation_id=None,
                deactivation_operation_id=None,
                support_generation=None,
            ),
        )
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="XLM",
                version="generation_without_operation",
                effective_from="2026-07-01 00:00:00",
                effective_to=None,
                is_active=1,
                activation_operation_id=None,
                deactivation_operation_id=None,
                support_generation=9,
            ),
        )
        xlm_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000021",
            symbol="XLM",
            generation_after=1,
        )
        xlm_remove = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000022",
            symbol="XLM",
            operation_type="REMOVE_SCOPE",
            generation_before=1,
            generation_after=2,
        )
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="XLM",
                version="zero_generation",
                effective_from="2026-07-01 00:00:00",
                effective_to=None,
                is_active=1,
                activation_operation_id=xlm_activate,
                deactivation_operation_id=None,
                support_generation=0,
            ),
        )
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="XLM",
                version="managed_closed_missing_end",
                effective_from="2026-07-01 00:00:00",
                effective_to=None,
                is_active=0,
                activation_operation_id=xlm_activate,
                deactivation_operation_id=xlm_remove,
                support_generation=1,
            ),
        )
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="XLM",
                version="invalid_deactivation_fk",
                effective_from="2026-07-01 00:00:00",
                effective_to="2026-07-02 00:00:00",
                is_active=0,
                activation_operation_id=xlm_activate,
                deactivation_operation_id=999999,
                support_generation=1,
            ),
        )

        xrp_a = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000031",
            symbol="XRP",
            generation_after=5,
        )
        xrp_b = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000032",
            symbol="XRP",
            generation_after=7,
        )
        first_inserted = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        outcomes: list[str] = []

        def first_writer() -> None:
            conn = _connect(config, database=database)
            try:
                _insert_cadence(
                    conn,
                    symbol="XRP",
                    version="concurrent_g5",
                    effective_from="2026-07-18 10:00:00",
                    effective_to=None,
                    is_active=1,
                    activation_operation_id=xrp_a,
                    deactivation_operation_id=None,
                    support_generation=5,
                )
                first_inserted.set()
                assert release_first.wait(timeout=10)
                conn.commit()
                outcomes.append("committed")
            finally:
                conn.close()

        def second_writer() -> None:
            conn = _connect(config, database=database)
            try:
                assert first_inserted.wait(timeout=10)
                with conn.cursor() as cursor:
                    cursor.execute("SET innodb_lock_wait_timeout = 5")
                second_started.set()
                try:
                    _insert_cadence(
                        conn,
                        symbol="XRP",
                        version="concurrent_g7",
                        effective_from="2026-07-18 11:00:00",
                        effective_to=None,
                        is_active=1,
                        activation_operation_id=xrp_b,
                        deactivation_operation_id=None,
                        support_generation=7,
                    )
                    conn.commit()
                    outcomes.append("committed")
                except (IntegrityError, OperationalError):
                    conn.rollback()
                    outcomes.append("rejected")
            finally:
                conn.close()

        first_thread = threading.Thread(target=first_writer)
        second_thread = threading.Thread(target=second_writer)
        first_thread.start()
        second_thread.start()
        assert second_started.wait(timeout=10)
        release_first.set()
        first_thread.join(timeout=15)
        second_thread.join(timeout=15)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert sorted(outcomes) == ["committed", "rejected"]
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS active_count
                FROM native_short_scope_cadence_config_v1
                WHERE symbol='XRP' AND is_active=1
                """
            )
            assert cursor.fetchone()["active_count"] == 1

        with pytest.raises(OperationalError):
            _apply(connection, MIGRATION)
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS table_count
                FROM information_schema.tables
                WHERE table_schema=DATABASE()
                  AND table_name='native_short_scope_admin_operation_v1'
                """
            )
            assert cursor.fetchone()["table_count"] == 1


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 with explicit disposable MariaDB settings.",
)
def test_failed_preflight_leaves_persistent_schema_and_data_unchanged() -> None:
    with _disposable_schema("preflight") as (connection, _config, _database):
        _apply_prerequisites(connection)
        with connection.cursor() as cursor:
            for values in (
                ("overlap_a", "2026-07-01 00:00:00", "2026-07-10 00:00:00", 0),
                ("overlap_b", "2026-07-05 00:00:00", None, 1),
            ):
                cursor.execute(
                    """
                    INSERT INTO native_short_scope_cadence_config_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon,
                        primary_interval, supporting_interval,
                        cadence_contract_version, target_evaluation_interval,
                        primary_source_freshness_limit_seconds,
                        supporting_source_freshness_limit_seconds,
                        evaluation_grace_seconds, recent_scope_grace_seconds,
                        effective_from_utc, effective_to_utc, is_active
                    ) VALUES (
                        'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', %s,
                        '1h', 43200, 10800, 900, 3600, %s, %s, %s
                    )
                    """,
                    values,
                )
        connection.commit()

        with pytest.raises(OperationalError):
            _apply(connection, MIGRATION)
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS row_count
                FROM native_short_scope_cadence_config_v1
                WHERE symbol='BTC'
                """
            )
            assert cursor.fetchone()["row_count"] == 2
            cursor.execute(
                """
                SELECT COUNT(*) AS table_count
                FROM information_schema.tables
                WHERE table_schema=DATABASE()
                  AND table_name='native_short_scope_admin_operation_v1'
                """
            )
            assert cursor.fetchone()["table_count"] == 0
            cursor.execute(
                """
                SELECT COUNT(*) AS column_count
                FROM information_schema.columns
                WHERE table_schema=DATABASE()
                  AND table_name='native_short_map_scope_v1'
                  AND column_name='support_generation'
                """
            )
            assert cursor.fetchone()["column_count"] == 0


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 with explicit disposable MariaDB settings.",
)
def test_cadence_uniqueness_legacy_and_managed_generations_in_disposable_mariadb() -> None:
    # Fix 1: the dropped uq_..._scope_version guard is replaced by a NULL-safe
    # slot-based key that (B) still forbids duplicate legacy/unmanaged rows and
    # (A) still allows distinct positive managed generations of one profile.
    with _disposable_schema("cadence_uniqueness") as (connection, _config, _database):
        _apply_prerequisites(connection)
        _apply(connection, MIGRATION)

        # (B) First legacy/unmanaged row (no operation, NULL generation) is allowed.
        _insert_cadence(
            connection,
            symbol="LTC",
            version="legacy_p",
            effective_from="2026-07-01 00:00:00",
            effective_to="2026-07-02 00:00:00",
            is_active=0,
            activation_operation_id=None,
            deactivation_operation_id=None,
            support_generation=None,
        )
        connection.commit()

        # (B) A duplicate legacy row for the same scope + profile is rejected even
        # though both carry support_generation=NULL (reserved legacy slot 0).
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="LTC",
                version="legacy_p",
                effective_from="2026-07-03 00:00:00",
                effective_to="2026-07-04 00:00:00",
                is_active=0,
                activation_operation_id=None,
                deactivation_operation_id=None,
                support_generation=None,
            ),
        )

        # A different legacy profile for the same scope remains allowed.
        _insert_cadence(
            connection,
            symbol="LTC",
            version="legacy_q",
            effective_from="2026-07-03 00:00:00",
            effective_to="2026-07-04 00:00:00",
            is_active=0,
            activation_operation_id=None,
            deactivation_operation_id=None,
            support_generation=None,
        )
        connection.commit()

        doge_g5_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000101",
            symbol="DOGE",
            generation_after=5,
        )
        doge_g5_deactivate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000102",
            symbol="DOGE",
            operation_type="REMOVE_SCOPE",
            generation_before=5,
            generation_after=6,
        )
        doge_g7_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000103",
            symbol="DOGE",
            generation_after=7,
        )

        # (A) generation 5 (inactive, closed) and generation 7 (active) of the
        # SAME cadence profile version are both allowed.
        _insert_cadence(
            connection,
            symbol="DOGE",
            version="managed_p",
            effective_from="2026-07-01 00:00:00",
            effective_to="2026-07-02 00:00:00",
            is_active=0,
            activation_operation_id=doge_g5_activate,
            deactivation_operation_id=doge_g5_deactivate,
            support_generation=5,
        )
        _insert_cadence(
            connection,
            symbol="DOGE",
            version="managed_p",
            effective_from="2026-07-02 00:00:00",
            effective_to=None,
            is_active=1,
            activation_operation_id=doge_g7_activate,
            deactivation_operation_id=None,
            support_generation=7,
        )
        connection.commit()

        # A duplicate managed generation (5) of the same profile is rejected.
        doge_g5_again = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000104",
            symbol="DOGE",
            generation_after=5,
        )
        doge_g5_again_deactivate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000105",
            symbol="DOGE",
            operation_type="REMOVE_SCOPE",
            generation_before=5,
            generation_after=6,
        )
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="DOGE",
                version="managed_p",
                effective_from="2026-07-05 00:00:00",
                effective_to="2026-07-06 00:00:00",
                is_active=0,
                activation_operation_id=doge_g5_again,
                deactivation_operation_id=doge_g5_again_deactivate,
                support_generation=5,
            ),
        )

        # A different inactive historical profile for the same scope is allowed.
        doge_q_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000106",
            symbol="DOGE",
            generation_after=9,
        )
        doge_q_deactivate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000107",
            symbol="DOGE",
            operation_type="REMOVE_SCOPE",
            generation_before=9,
            generation_after=10,
        )
        _insert_cadence(
            connection,
            symbol="DOGE",
            version="managed_q",
            effective_from="2026-07-03 00:00:00",
            effective_to="2026-07-04 00:00:00",
            is_active=0,
            activation_operation_id=doge_q_activate,
            deactivation_operation_id=doge_q_deactivate,
            support_generation=9,
        )
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS c FROM native_short_scope_cadence_config_v1 WHERE symbol='LTC'"
            )
            assert cursor.fetchone()["c"] == 2
            cursor.execute(
                "SELECT COUNT(*) AS c FROM native_short_scope_cadence_config_v1 WHERE symbol='DOGE'"
            )
            assert cursor.fetchone()["c"] == 3


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 with explicit disposable MariaDB settings.",
)
def test_cross_scope_operation_attribution_rejected_in_disposable_mariadb() -> None:
    # Fix 2: scope-bound composite FKs prevent attributing one scope's operation
    # to a different scope's support/cadence row, while NULL legacy references
    # remain allowed.
    with _disposable_schema("cross_scope") as (connection, config, _database):
        _apply_prerequisites(connection)
        _apply(connection, MIGRATION)

        aaa_op = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000201",
            symbol="AAA",
            generation_after=1,
        )
        # Distinct, otherwise-unreferenced operations isolate the FK from the
        # one-support-event-per-operation and one-activation-per-cadence guards.
        aaa_op_support = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000202",
            symbol="AAA",
            generation_after=2,
        )
        aaa_op_activation = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000203",
            symbol="AAA",
            generation_after=3,
        )

        # Same-scope support-event attribution is allowed.
        _insert_support_event(
            connection,
            symbol="AAA",
            operation_id=aaa_op,
            generation=1,
            event_ts="2026-07-18 10:00:00",
        )
        connection.commit()

        # Cross-scope support-event attribution is rejected by the composite FK
        # (shape is valid: operation id and generation are both present).
        _expect_rejected(
            connection,
            lambda: _insert_support_event(
                connection,
                symbol="BBB",
                operation_id=aaa_op_support,
                generation=2,
                event_ts="2026-07-18 11:00:00",
            ),
        )

        # Legacy NULL operation reference remains allowed.
        _insert_support_event(
            connection,
            symbol="BBB",
            operation_id=None,
            generation=None,
            event_ts="2026-07-18 12:00:00",
        )
        connection.commit()

        # Cross-scope cadence activation attribution is rejected.
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="BBB",
                version="activation_from_aaa",
                effective_from="2026-07-18 10:00:00",
                effective_to=None,
                is_active=1,
                activation_operation_id=aaa_op_activation,
                deactivation_operation_id=None,
                support_generation=3,
            ),
        )

        # Same-scope cadence activation attribution is allowed.
        bbb_op = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000204",
            symbol="BBB",
            generation_after=1,
        )
        _insert_cadence(
            connection,
            symbol="BBB",
            version="managed_own",
            effective_from="2026-07-18 10:00:00",
            effective_to=None,
            is_active=1,
            activation_operation_id=bbb_op,
            deactivation_operation_id=None,
            support_generation=1,
        )
        connection.commit()

        # Cross-scope cadence deactivation attribution is rejected: activation is
        # CCC's own operation, but deactivation references a DDD operation.
        ccc_activate = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000205",
            symbol="CCC",
            generation_after=1,
        )
        ddd_remove = _insert_operation(
            connection,
            operation_uuid="00000000-0000-4000-8000-000000000206",
            symbol="DDD",
            operation_type="REMOVE_SCOPE",
            generation_before=1,
            generation_after=2,
        )
        _expect_rejected(
            connection,
            lambda: _insert_cadence(
                connection,
                symbol="CCC",
                version="managed_ccc",
                effective_from="2026-07-18 10:00:00",
                effective_to="2026-07-19 00:00:00",
                is_active=0,
                activation_operation_id=ccc_activate,
                deactivation_operation_id=ddd_remove,
                support_generation=1,
            ),
        )
