from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


MIGRATION_PATH = Path(
    "db/migrations/20260828_trading_account_account_mode_live_readonly_v1.sql"
)

TEMP_DB_NAME = "synth_account_mode_live_readonly_migration_tmp"

# Minimal replica of the production trading_account table (per SHOW CREATE
# TABLE trading_account against the `synth` database prior to this
# migration), sufficient to prove the constraint-only migration behavior
# without depending on any other migration file.
BASE_TABLE_DDL = """
CREATE TABLE trading_account (
    trading_account_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    account_code VARCHAR(64) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    account_mode VARCHAR(32) NOT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    live_trading_enabled TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY (trading_account_id),
    UNIQUE KEY uq_trading_account_code (account_code),
    CONSTRAINT chk_trading_account_mode CHECK (account_mode IN ('paper','live')),
    CONSTRAINT chk_trading_account_live_requires_enabled
        CHECK (live_trading_enabled IN (0,1) AND enabled IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


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


def test_migration_is_created_not_applied() -> None:
    assert "MIGRATION_STATE=CREATED_NOT_APPLIED" in _sql()


def test_migration_only_touches_trading_account_and_only_the_mode_constraint() -> None:
    sql = _sql()
    statements = "\n".join(_split_sql_statements(sql))

    assert statements.count("ALTER TABLE") == 2
    assert "ALTER TABLE trading_account" in statements
    for forbidden_table in ("trading_account_credential", "trading_account_balance_snapshot"):
        assert f"ALTER TABLE {forbidden_table}" not in statements

    assert statements.count("DROP CONSTRAINT IF EXISTS chk_trading_account_mode") == 1
    assert statements.count("ADD CONSTRAINT chk_trading_account_mode") == 1

    # The unrelated live_trading_enabled/enabled constraint must not be touched
    # by any executable statement (comments may still explain the boundary).
    assert "chk_trading_account_live_requires_enabled" not in statements
    assert "live_trading_enabled" not in statements


def test_migration_has_no_data_manipulation_statements() -> None:
    sql = _sql()
    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE FROM" not in sql
    assert "CREATE TABLE" not in sql
    assert "DROP TABLE" not in sql


def test_migration_targets_exactly_the_canonical_three_value_vocabulary() -> None:
    sql = _sql()
    check_clause = sql.split("ADD CONSTRAINT chk_trading_account_mode", 1)[1]
    assert "CHECK (account_mode IN ('paper', 'live_readonly', 'live'))" in check_clause
    # No broader/looser vocabulary than the canonical three values.
    assert "'%'" not in check_clause


def test_mariadb_identifiers_fit_64_character_limit() -> None:
    identifiers = re.findall(r"CONSTRAINT\s+([A-Za-z0-9_]+)", _sql())
    assert identifiers
    assert all(len(identifier) <= 64 for identifier in identifiers)


def test_data_migration_doc_now_depends_on_this_schema_migration() -> None:
    doc = Path(
        "docs/ops/trading_account_live_readonly_mode_migration_v1.md"
    ).read_text(encoding="utf-8")
    assert MIGRATION_PATH.name in doc
    assert "chk_trading_account_mode" in doc


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
                            "Configured DB user lacks CREATE/DROP DATABASE "
                            "privilege for disposable schema validation."
                        )
                    raise
            admin_conn.commit()
        finally:
            admin_conn.close()

        schema_conn = get_connection(database=temp_db_name)
        with schema_conn.cursor() as cur:
            for statement in _split_sql_statements(BASE_TABLE_DDL):
                cur.execute(statement)
            schema_conn.commit()

            # Seed a pre-migration row using the original ('paper','live')
            # vocabulary, to prove the migration is non-destructive.
            cur.execute(
                "INSERT INTO trading_account "
                "(account_code, venue, account_mode, enabled, live_trading_enabled) "
                "VALUES ('bitvavo_synth_read', 'bitvavo', 'live', 1, 0)"
            )
            schema_conn.commit()
            cur.execute(
                "SELECT trading_account_id FROM trading_account WHERE account_code = 'bitvavo_synth_read'"
            )
            seeded_id = cur.fetchone()[0]

            for statement in _split_sql_statements(_sql()):
                cur.execute(statement)
            schema_conn.commit()

            # Existing row survives the migration completely unchanged.
            cur.execute(
                "SELECT account_code, venue, account_mode, enabled, live_trading_enabled "
                "FROM trading_account WHERE trading_account_id = %s",
                (seeded_id,),
            )
            row = cur.fetchone()
            assert row == ("bitvavo_synth_read", "bitvavo", "live", 1, 0)

            # 'paper' still accepted.
            cur.execute(
                "INSERT INTO trading_account "
                "(account_code, venue, account_mode, enabled, live_trading_enabled) "
                "VALUES ('paper_probe', 'bitvavo', 'paper', 1, 0)"
            )
            schema_conn.commit()

            # 'live' still accepted.
            cur.execute(
                "INSERT INTO trading_account "
                "(account_code, venue, account_mode, enabled, live_trading_enabled) "
                "VALUES ('live_probe', 'bitvavo', 'live', 1, 0)"
            )
            schema_conn.commit()

            # 'live_readonly' now accepted -- the canonical new value.
            cur.execute(
                "INSERT INTO trading_account "
                "(account_code, venue, account_mode, enabled, live_trading_enabled) "
                "VALUES ('live_readonly_probe', 'bitvavo', 'live_readonly', 1, 0)"
            )
            schema_conn.commit()

            # An unknown account_mode value is still rejected.
            with pytest.raises(IntegrityError):
                cur.execute(
                    "INSERT INTO trading_account "
                    "(account_code, venue, account_mode, enabled, live_trading_enabled) "
                    "VALUES ('unknown_probe', 'bitvavo', 'shadow', 1, 0)"
                )
            schema_conn.rollback()

            cur.execute("SHOW CREATE TABLE trading_account")
            ddl_row = cur.fetchone()
            ddl = ddl_row[1]
            assert "'paper'" in ddl and "'live_readonly'" in ddl and "'live'" in ddl
            assert "chk_trading_account_mode" in ddl
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
