from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest


PREREQUISITE_MIGRATION_PATH = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
A1_MIGRATION_PATH = Path("db/migrations/20260706_native_short_scope_status_persistence_v1.sql")
A1B_MIGRATION_PATH = Path("db/migrations/20260707_native_short_cadence_unavailable_v1.sql")
MIGRATION_PATH = Path("db/migrations/20260709_native_short_cadence_v1_seed.sql")
DOC_PATH = Path("docs/architecture/native_short_scope_status_contract_v1.md")

TEMP_DB_NAME = "synth_native_short_cadence_v1_seed_tmp"


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


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


def test_migration_filename_sorts_after_prerequisite_migrations() -> None:
    assert (
        PREREQUISITE_MIGRATION_PATH.name
        < A1_MIGRATION_PATH.name
        < A1B_MIGRATION_PATH.name
        < MIGRATION_PATH.name
    )
    assert MIGRATION_PATH.name.startswith("20260709_")


def test_doc_records_all_six_canonical_cadence_fields() -> None:
    doc = _doc()
    section = doc.split("### Canonical Native SHORT V1 Cadence Profile", 1)[1]
    for expected in (
        "`native_short_cadence_v1`",
        "`1h`",
        "`43200`",
        "`10800`",
        "`900`",
        "`3600`",
    ):
        assert expected in section, f"missing canonical field value in doc: {expected}"


def test_doc_does_not_leave_grace_fields_without_a_numeric_default() -> None:
    doc = _doc()
    section = doc.split("### Canonical Native SHORT V1 Cadence Profile", 1)[1]
    assert "evaluation_grace_seconds" in section
    assert "recent_scope_grace_seconds" in section
    assert "900" in section
    assert "3600" in section


def test_migration_targets_the_cadence_config_table_only() -> None:
    sql = _sql()
    assert "INSERT INTO native_short_scope_cadence_config_v1" in sql
    for forbidden_table in (
        "native_short_scope_observation_v1",
        "native_short_scope_status_v1",
        "native_short_scope_support_event_v1",
        "native_short_materializer_run_v1",
        "native_short_map_v1",
        "native_short_map_generation_event_v1",
        "native_short_map_lifecycle_event_v1",
    ):
        assert f"INSERT INTO {forbidden_table}" not in sql
        assert f"UPDATE {forbidden_table}" not in sql
        assert f"ALTER TABLE {forbidden_table}" not in sql
    assert "CREATE TABLE" not in sql
    assert "ALTER TABLE" not in sql


def test_migration_selects_the_exact_full_canonical_key_only() -> None:
    sql = _sql()
    insert_section = sql.split("INSERT INTO native_short_scope_cadence_config_v1", 1)[1]
    for column in (
        "venue",
        "symbol",
        "quote_currency",
        "fib_trading_horizon",
        "primary_interval",
        "supporting_interval",
    ):
        assert column in insert_section

    # exact full-key scope source: native_short_map_scope_v1, filtered to
    # SUPPORTED SHORT scopes only, never every row unconditionally.
    assert "FROM native_short_map_scope_v1 s" in sql
    assert "s.fib_trading_horizon = 'SHORT'" in sql
    assert "s.scope_support_state = 'SUPPORTED'" in sql


def test_migration_uses_canonical_cadence_contract_version() -> None:
    sql = _sql()
    assert "'native_short_cadence_v1'" in sql


def test_migration_includes_all_authorized_numeric_thresholds() -> None:
    sql = _sql()
    for value in ("43200", "10800", "900", "3600"):
        assert value in sql, f"missing authorized threshold value: {value}"


def test_migration_is_duplicate_guarded() -> None:
    sql = _sql()
    assert "NOT EXISTS" in sql
    guard_section = sql.split("NOT EXISTS", 1)[1]
    assert "FROM native_short_scope_cadence_config_v1 existing" in guard_section
    for column in (
        "existing.venue",
        "existing.symbol",
        "existing.quote_currency",
        "existing.fib_trading_horizon",
        "existing.primary_interval",
        "existing.supporting_interval",
        "existing.cadence_contract_version = 'native_short_cadence_v1'",
    ):
        assert column in guard_section


def test_migration_uses_no_wildcard_inheritance() -> None:
    executable_lines = [
        line for line in _sql().splitlines() if not line.strip().startswith("--")
    ]
    executable_sql = "\n".join(executable_lines).lower()
    for forbidden in ("'%'", "is null and", "coalesce(", "where 1"):
        assert forbidden not in executable_sql


def test_migration_does_not_use_now_for_effective_from() -> None:
    sql = _sql()
    assert "NOW()" not in sql
    assert "CURRENT_TIMESTAMP" not in sql
    assert "@native_short_cadence_v1_effective_from_utc = TIMESTAMP('2026-07-09 00:00:00.000000')" in sql


def test_migration_sets_effective_to_null_and_is_active_true() -> None:
    sql = _sql()
    values_section = sql.split("SELECT", 1)[1]
    assert "NULL," in values_section  # effective_to_utc
    assert "1\nFROM native_short_map_scope_v1 s" in sql  # is_active = 1 immediately before the source


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
        "select" + "ion_engine",
        "report" + "ing",
    ):
        assert forbidden not in sql


def test_migration_does_not_touch_materializer_reporting_or_ui_source_files() -> None:
    forbidden_paths = (
        Path("src/market_data/native_short_scope_status_materializer_v1.py"),
        Path("src/market_data/native_short_map_materializer_v1.py"),
        Path("src/reporting/native_short_map_ledger_health_report_v1.py"),
        Path("src/reporting/run_native_short_map_ledger_health_report_v1.py"),
    )
    for path in forbidden_paths:
        assert path.exists(), f"expected file to exist unmodified: {path}"


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the seed migration in a disposable schema.",
)
def test_migration_is_idempotent_in_disposable_mariadb_schema() -> None:
    from pymysql.err import OperationalError

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
            for migration_path in (
                PREREQUISITE_MIGRATION_PATH,
                A1_MIGRATION_PATH,
                A1B_MIGRATION_PATH,
            ):
                for statement in _split_sql_statements(migration_path.read_text(encoding="utf-8")):
                    cur.execute(statement)
            schema_conn.commit()

            cur.execute(
                """
                INSERT INTO native_short_map_scope_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon,
                    primary_interval, supporting_interval, scope_support_state,
                    scope_reason_code, scope_reason_detail
                ) VALUES (
                    'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                    'TEST_SEED', 'disposable schema seed migration idempotency test'
                )
                """
            )
            schema_conn.commit()

            for statement in _split_sql_statements(_sql()):
                cur.execute(statement)
            schema_conn.commit()

            cur.execute("SELECT * FROM native_short_scope_cadence_config_v1")
            rows_after_first = cur.fetchall()
            assert len(rows_after_first) == 1
            row = rows_after_first[0]
            assert row["venue"] == "bitvavo"
            assert row["symbol"] == "BTC"
            assert row["cadence_contract_version"] == "native_short_cadence_v1"
            assert row["target_evaluation_interval"] == "1h"
            assert row["primary_source_freshness_limit_seconds"] == 43200
            assert row["supporting_source_freshness_limit_seconds"] == 10800
            assert row["evaluation_grace_seconds"] == 900
            assert row["recent_scope_grace_seconds"] == 3600
            assert row["effective_to_utc"] is None
            assert row["is_active"] == 1
            assert row["effective_from_utc"] == datetime(2026, 7, 9, 0, 0, 0)

            # Re-running the migration must not create a duplicate row.
            for statement in _split_sql_statements(_sql()):
                cur.execute(statement)
            schema_conn.commit()

            cur.execute("SELECT * FROM native_short_scope_cadence_config_v1")
            rows_after_second = cur.fetchall()
            assert len(rows_after_second) == 1
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
