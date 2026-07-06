from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest


PREREQUISITE_MIGRATION_PATH = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
A1_MIGRATION_PATH = Path("db/migrations/20260706_native_short_scope_status_persistence_v1.sql")
MIGRATION_PATH = Path("db/migrations/20260707_native_short_cadence_unavailable_v1.sql")

TEMP_DB_NAME = "synth_a1b_native_short_cadence_unavailable_tmp"


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


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


def _temp_db_name() -> str:
    return f"{TEMP_DB_NAME}_{os.getpid()}"


def _ts(offset_minutes: int = 0) -> datetime:
    from datetime import timedelta

    return datetime(2026, 7, 7, 12, 0, tzinfo=UTC) + timedelta(minutes=offset_minutes)


def test_a1b_migration_filename_sorts_after_a1_migration() -> None:
    assert PREREQUISITE_MIGRATION_PATH.name < A1_MIGRATION_PATH.name < MIGRATION_PATH.name
    assert MIGRATION_PATH.name.startswith("20260707_")
    assert A1_MIGRATION_PATH.name.startswith("20260706_")


def test_migration_only_alters_the_two_affected_tables() -> None:
    sql = _sql()
    assert "CREATE TABLE" not in sql
    assert "ALTER TABLE native_short_scope_observation_v1" in sql
    assert "ALTER TABLE native_short_scope_status_v1" in sql
    for forbidden_table in (
        "native_short_scope_support_event_v1",
        "native_short_scope_cadence_config_v1",
        "native_short_materializer_run_v1",
        "native_short_map_v1",
        "native_short_map_generation_event_v1",
        "native_short_map_lifecycle_event_v1",
        "native_short_map_scope_v1",
    ):
        assert f"ALTER TABLE {forbidden_table}" not in sql


def test_migration_has_no_data_manipulation_statements() -> None:
    sql = _sql()
    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE FROM" not in sql


def test_migration_relaxes_only_the_specified_observation_columns_to_nullable() -> None:
    sql = _sql()
    observation_section = sql.split("ALTER TABLE native_short_scope_observation_v1", 1)[1]
    observation_section = observation_section.split("ALTER TABLE native_short_scope_status_v1", 1)[0]

    for column in (
        "MODIFY COLUMN cadence_contract_version VARCHAR(32) NULL",
        "MODIFY COLUMN source_state VARCHAR(64) NULL",
        "MODIFY COLUMN primary_source_freshness_limit_seconds INT UNSIGNED NULL",
        "MODIFY COLUMN supporting_source_freshness_limit_seconds INT UNSIGNED NULL",
        "MODIFY COLUMN geometry_action VARCHAR(64) NULL",
    ):
        assert column in observation_section

    # observation_status stays NOT NULL; it is the discriminator, not relaxed.
    assert "MODIFY COLUMN observation_status VARCHAR(64) NOT NULL" in observation_section


def test_migration_relaxes_only_the_specified_status_columns_to_nullable() -> None:
    sql = _sql()
    status_section = sql.split("ALTER TABLE native_short_scope_status_v1", 1)[1]

    for column in (
        "MODIFY COLUMN primary_source_freshness_limit_seconds INT UNSIGNED NULL",
        "MODIFY COLUMN supporting_source_freshness_limit_seconds INT UNSIGNED NULL",
        "MODIFY COLUMN cadence_contract_version VARCHAR(32) NULL",
    ):
        assert column in status_section
    assert "MODIFY COLUMN source_freshness_state VARCHAR(64) NULL" in status_section

    # discriminators stay NOT NULL
    assert "MODIFY COLUMN scope_status_code VARCHAR(64) NOT NULL" in status_section
    assert "MODIFY COLUMN observation_freshness_state VARCHAR(64) NOT NULL" in status_section
    assert "MODIFY COLUMN actionability_state VARCHAR(64) NOT NULL" in status_section


def test_migration_extends_domains_with_the_four_new_enum_values_and_keeps_existing_ones() -> None:
    sql = _sql()

    observation_section = sql.split("ALTER TABLE native_short_scope_observation_v1", 1)[1]
    observation_section = observation_section.split("ALTER TABLE native_short_scope_status_v1", 1)[0]
    assert "'SKIPPED_CONFIGURATION_UNAVAILABLE'" in observation_section
    for existing in ("'EVALUATED'", "'FAILED'", "'SKIPPED_SOURCE_UNAVAILABLE'"):
        assert existing in observation_section

    status_section = sql.split("ALTER TABLE native_short_scope_status_v1", 1)[1]
    assert "'CONFIGURATION_UNAVAILABLE'" in status_section
    assert "'BLOCKED_CONFIGURATION'" in status_section
    assert "'OBSERVATION_CONFIGURATION_UNAVAILABLE'" in status_section
    for existing in (
        "'SOURCE_UNAVAILABLE'",
        "'SOURCE_STALE'",
        "'MAP_INVALIDATED'",
        "'MAP_COMPLETED'",
        "'SCOPE_RECENTLY_ADDED'",
        "'OBSERVATION_OVERDUE'",
        "'CURRENT_EVALUATION'",
        "'ACTIONABLE_ACTIVE_MAP'",
        "'NO_ACTIONABLE_MAP'",
        "'TERMINAL_MAP'",
        "'BLOCKED_SOURCE'",
        "'BLOCKED_OBSERVATION'",
        "'BLOCKED_SCOPE'",
        "'OBSERVATION_CURRENT'",
        "'NO_OBSERVATION'",
    ):
        assert existing in status_section


def test_migration_replaces_only_the_affected_check_constraints_by_name() -> None:
    sql = _sql()

    for name in (
        "chk_native_short_scope_observation_v1_status",
        "chk_native_short_scope_observation_v1_source",
        "chk_native_short_scope_observation_v1_geometry",
    ):
        assert sql.count(f"DROP CONSTRAINT {name}") == 1
        assert sql.count(f"ADD CONSTRAINT {name}") == 1

    for name in (
        "chk_native_short_scope_status_v1_code",
        "chk_native_short_scope_status_v1_observation_freshness",
        "chk_native_short_scope_status_v1_source_freshness",
        "chk_native_short_scope_status_v1_actionability",
    ):
        assert sql.count(f"DROP CONSTRAINT {name}") == 1
        assert sql.count(f"ADD CONSTRAINT {name}") == 1

    # Untouched CHECK constraints from the A1 migration must not be dropped here.
    for untouched in (
        "chk_native_short_scope_observation_v1_horizon",
        "chk_native_short_scope_status_v1_horizon",
        "chk_native_short_scope_status_v1_support",
        "chk_native_short_scope_status_v1_map_lifecycle",
    ):
        assert "DROP CONSTRAINT " + untouched not in sql
        assert "ADD CONSTRAINT " + untouched not in sql


def test_migration_adds_named_conditional_nullability_constraints() -> None:
    sql = _sql()
    for name in (
        "chk_native_short_scope_observation_v1_cadence_version",
        "chk_native_short_scope_observation_v1_freshness_limits",
        "chk_native_short_scope_observation_v1_config_reason",
        "chk_native_short_scope_observation_v1_config_due",
        "chk_native_short_scope_status_v1_config_cadence_version",
        "chk_native_short_scope_status_v1_config_freshness_limits",
        "chk_native_short_scope_status_v1_config_reason",
        "chk_native_short_scope_status_v1_config_actionability",
        "chk_native_short_scope_status_v1_config_obs_freshness",
        "chk_native_short_scope_status_v1_config_next_eval",
        "chk_native_short_scope_status_v1_config_overdue_after",
    ):
        assert f"ADD CONSTRAINT {name}" in sql


def test_migration_conditional_constraints_enforce_both_branches() -> None:
    sql = _sql()
    # Each conditional CHECK must express both: the configuration-unavailable
    # branch (field IS NULL) and the ordinary branch (field IS NOT NULL / IN
    # the closed domain), never a single unconditional relaxation.
    observation_section = sql.split("ALTER TABLE native_short_scope_observation_v1", 1)[1]
    observation_section = observation_section.split("ALTER TABLE native_short_scope_status_v1", 1)[0]
    assert observation_section.count("SKIPPED_CONFIGURATION_UNAVAILABLE") >= 6

    status_section = sql.split("ALTER TABLE native_short_scope_status_v1", 1)[1]
    assert status_section.count("CONFIGURATION_UNAVAILABLE") >= 7


def test_migration_introduces_no_forbidden_layer_references() -> None:
    sql = _sql().lower()
    for forbidden in (
        "sys" + "temd",
        " ti" + "mer",
        " ser" + "vice",
        "sub" + "process",
        "bro" + "ker",
        "acc" + "ount",
        "wal" + "let",
        "exec" + "utor",
        "exec" + "ution_planner",
        "decision" + "_gate",
    ):
        assert forbidden not in sql


def test_updated_type_module_still_imports_no_forbidden_layers() -> None:
    source = Path("src/market_data/native_short_scope_status_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        for forbidden in (
            "src.bro" + "ker",
            "src.acc" + "ount",
            "src.exec" + "utor",
            "src.exec" + "ution",
            "src.exec" + "ution_planner",
            "src.decision" + "_gate",
            "src.reporting",
        ):
            assert not module_name.startswith(forbidden), module_name


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_migration_executes_in_disposable_mariadb_schema() -> None:
    from pymysql.err import IntegrityError, OperationalError

    from src.common.db import get_connection

    temp_db_name = _temp_db_name()
    schema_conn = None
    try:
        admin_conn = get_connection(database="information_schema")
        try:
            with admin_conn.cursor() as cur:
                try:
                    cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
                    cur.execute(
                        f"CREATE DATABASE `{temp_db_name}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                except OperationalError as exc:
                    if exc.args and exc.args[0] == 1044:
                        pytest.skip(
                            "Configured DB user lacks CREATE/DROP DATABASE privilege for disposable schema validation."
                        )
                    raise
            admin_conn.commit()
        finally:
            admin_conn.close()

        schema_conn = get_connection(database=temp_db_name)
        with schema_conn.cursor() as cur:
            for statement in _split_sql_statements(PREREQUISITE_MIGRATION_PATH.read_text(encoding="utf-8")):
                cur.execute(statement)
            for statement in _split_sql_statements(A1_MIGRATION_PATH.read_text(encoding="utf-8")):
                cur.execute(statement)
            for statement in _split_sql_statements(_sql()):
                cur.execute(statement)
            schema_conn.commit()

            cur.execute(
                """
                INSERT INTO native_short_materializer_run_v1 (
                    run_uuid, runner_name, runner_version, contract_version,
                    trigger_type, started_at_utc, requested_scope_count
                ) VALUES (
                    'aaaaaaaa-0000-0000-0000-000000000001',
                    'native_short_map_materializer_v1', '0.1',
                    'native_short_scope_status_contract_v1', 'MANUAL', %s, 1
                )
                """,
                (_ts(0),),
            )
            schema_conn.commit()
            cur.execute("SELECT run_id FROM native_short_materializer_run_v1")
            run_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO native_short_scope_observation_v1 (
                    run_id, run_uuid, venue, symbol, quote_currency, fib_trading_horizon,
                    primary_interval, supporting_interval, observed_at_utc,
                    cadence_contract_version, observation_status, observation_reason_code,
                    source_state, primary_source_freshness_limit_seconds,
                    supporting_source_freshness_limit_seconds, geometry_action,
                    evaluation_due_at_utc
                ) VALUES (
                    %s, 'aaaaaaaa-0000-0000-0000-000000000001', 'bitvavo', 'BTC', 'EUR',
                    'SHORT', '4h', '1h', %s,
                    NULL, 'SKIPPED_CONFIGURATION_UNAVAILABLE', 'NO_ELIGIBLE_CADENCE_CONFIG',
                    NULL, NULL, NULL, NULL, NULL
                )
                """,
                (run_id, _ts(1)),
            )
            schema_conn.commit()

            cur.execute(
                """
                INSERT INTO native_short_scope_status_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval,
                    supporting_interval, scope_support_state, scope_status_code,
                    scope_status_reason_code, map_lifecycle_state, observation_freshness_state,
                    source_freshness_state, actionability_state,
                    primary_source_freshness_limit_seconds, supporting_source_freshness_limit_seconds,
                    cadence_contract_version, projection_as_of_utc,
                    next_expected_evaluation_at_utc, observation_overdue_after_utc
                ) VALUES (
                    'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                    'CONFIGURATION_UNAVAILABLE', 'NO_ELIGIBLE_CADENCE_CONFIG', 'NO_CURRENT_MAP',
                    'OBSERVATION_CONFIGURATION_UNAVAILABLE', NULL, 'BLOCKED_CONFIGURATION',
                    NULL, NULL, NULL, %s, NULL, NULL
                )
                """,
                (_ts(1),),
            )
            schema_conn.commit()

            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_scope_observation_v1 (
                        run_id, run_uuid, venue, symbol, quote_currency, fib_trading_horizon,
                        primary_interval, supporting_interval, observed_at_utc,
                        cadence_contract_version, observation_status, observation_reason_code,
                        source_state, primary_source_freshness_limit_seconds,
                        supporting_source_freshness_limit_seconds, geometry_action
                    ) VALUES (
                        %s, 'aaaaaaaa-0000-0000-0000-000000000001', 'bitvavo', 'ETH', 'EUR',
                        'SHORT', '4h', '1h', %s,
                        'v1', 'SKIPPED_CONFIGURATION_UNAVAILABLE', 'NO_ELIGIBLE_CADENCE_CONFIG',
                        NULL, NULL, NULL, NULL
                    )
                    """,
                    (run_id, _ts(2)),
                )
            schema_conn.rollback()

            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_scope_observation_v1 (
                        run_id, run_uuid, venue, symbol, quote_currency, fib_trading_horizon,
                        primary_interval, supporting_interval, observed_at_utc,
                        cadence_contract_version, observation_status, source_state,
                        primary_source_freshness_limit_seconds,
                        supporting_source_freshness_limit_seconds, geometry_action
                    ) VALUES (
                        %s, 'aaaaaaaa-0000-0000-0000-000000000001', 'bitvavo', 'XRP', 'EUR',
                        'SHORT', '4h', '1h', %s,
                        NULL, 'EVALUATED', 'SOURCE_CURRENT', 43200, 10800, 'UNCHANGED_GEOMETRY'
                    )
                    """,
                    (run_id, _ts(3)),
                )
            schema_conn.rollback()

            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_scope_status_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon, primary_interval,
                        supporting_interval, scope_support_state, scope_status_code,
                        map_lifecycle_state, observation_freshness_state, source_freshness_state,
                        actionability_state, primary_source_freshness_limit_seconds,
                        supporting_source_freshness_limit_seconds, cadence_contract_version,
                        projection_as_of_utc
                    ) VALUES (
                        'bitvavo', 'DOGE', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                        'CURRENT_EVALUATION', 'MAP_ACTIVE', 'OBSERVATION_CURRENT', NULL,
                        'ACTIONABLE_ACTIVE_MAP', 43200, 10800, 'v1', %s
                    )
                    """,
                    (_ts(4),),
                )
            schema_conn.rollback()

            status_ddl_row = None
            cur.execute("SHOW CREATE TABLE native_short_scope_status_v1")
            status_ddl_row = cur.fetchone()
            observation_ddl_row = None
            cur.execute("SHOW CREATE TABLE native_short_scope_observation_v1")
            observation_ddl_row = cur.fetchone()

        status_ddl = status_ddl_row[1]
        observation_ddl = observation_ddl_row[1]
        assert "CONFIGURATION_UNAVAILABLE" in status_ddl
        assert "BLOCKED_CONFIGURATION" in status_ddl
        assert "OBSERVATION_CONFIGURATION_UNAVAILABLE" in status_ddl
        assert "chk_native_short_scope_status_v1_config_reason" in status_ddl
        assert "SKIPPED_CONFIGURATION_UNAVAILABLE" in observation_ddl
        assert "chk_native_short_scope_observation_v1_config_reason" in observation_ddl
    finally:
        if schema_conn is not None:
            schema_conn.close()
        cleanup_conn = get_connection(database="information_schema")
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()
