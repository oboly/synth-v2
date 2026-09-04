from __future__ import annotations

"""Regression tests for the forward-only, idempotent AUTO_ONBOARD_SCOPE
operation_type CHECK-constraint fix
(db/migrations/20260904_native_short_scope_admin_operation_auto_onboard_type_v1.sql).

Boundary: pure migration-file assertions plus an explicit disposable MariaDB
constraint test. No production database is touched; the disposable-schema test
only runs when the operator explicitly opts in via RUN_MARIADB_DDL_TEST=1 and
explicit SYNTH_TEST_MARIADB_* settings, matching the existing
test_native_short_scope_administration_migration_v1.py convention.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""

import hashlib
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pymysql
import pytest
from pymysql.cursors import DictCursor
from pymysql.err import IntegrityError, OperationalError


BASE_MIGRATION = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
STATUS_MIGRATION = Path("db/migrations/20260706_native_short_scope_status_persistence_v1.sql")
ADMIN_MIGRATION = Path("db/migrations/20260718_native_short_scope_administration_v1.sql")
FIX_MIGRATION = Path(
    "db/migrations/20260904_native_short_scope_admin_operation_auto_onboard_type_v1.sql"
)
TEMP_DB_PREFIX = "synth_native_short_scope_admin_auto_onboard_type_tmp"

_REQUIRED_ENV = (
    "SYNTH_TEST_MARIADB_HOST",
    "SYNTH_TEST_MARIADB_PORT",
    "SYNTH_TEST_MARIADB_USER",
    "SYNTH_TEST_MARIADB_PASSWORD",
    "SYNTH_TEST_MARIADB_ADMIN_DATABASE",
)


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
def _disposable_schema(label: str) -> Iterator[Any]:
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
        yield connection
    finally:
        if connection is not None:
            connection.close()
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
        admin.commit()
        admin.close()


def _apply(connection: Any, path: Path) -> None:
    with connection.cursor() as cursor:
        for statement in _split_sql_statements(_sql(path)):
            cursor.execute(statement)
    connection.commit()


def _apply_prerequisites(connection: Any) -> None:
    _apply(connection, BASE_MIGRATION)
    _apply(connection, STATUS_MIGRATION)
    _apply(connection, ADMIN_MIGRATION)


def _insert_operation_row(connection: Any, *, operation_type: str, symbol: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO native_short_scope_admin_operation_v1 (
                operation_uuid, operation_type,
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval,
                actor_type, actor_id, trigger_type, request_source, reason,
                requested_at_utc, repository_sha, schema_version,
                metadata_digest, started_at_utc
            ) VALUES (
                %s, %s,
                'bitvavo', %s, 'EUR', 'SHORT', '4h', '1h',
                'SERVICE_PRINCIPAL', 'native_short_auto_onboarding_v1', 'AUTOMATION',
                'native_short_auto_onboarding_v1',
                'canonical market-data readiness satisfied',
                '2026-09-04 10:00:00.000000', %s,
                'native_short_auto_onboarding_v1', %s,
                '2026-09-04 10:00:00.000000'
            )
            """,
            (
                str(uuid.uuid4()),
                operation_type,
                symbol,
                "0" * 40,
                hashlib.sha256(operation_type.encode("utf-8")).hexdigest(),
            ),
        )
    connection.commit()


def test_fix_migration_is_forward_only_idempotent_and_scoped_to_the_type_constraint() -> None:
    sql = _sql(FIX_MIGRATION)
    assert FIX_MIGRATION.name.startswith("20260904_")
    assert "DROP CONSTRAINT IF EXISTS chk_native_short_scope_admin_operation_v1_type" in sql
    assert "ADD CONSTRAINT chk_native_short_scope_admin_operation_v1_type" in sql
    for operation_type in (
        "ADOPT_LEGACY_SCOPE",
        "PROMOTE_SCOPE",
        "AUTO_ONBOARD_SCOPE",
        "REMOVE_SCOPE",
    ):
        assert f"'{operation_type}'" in sql
    # Scoped to exactly one constraint: no other CHECK/ALTER touched. Strip
    # comment lines first so the prose describing the sibling idempotent
    # convention does not inflate the count of actual executed statements.
    executable_sql = "\n".join(
        line
        for line in sql.splitlines()
        if not line.strip().startswith("--")
    )
    assert executable_sql.count("ALTER TABLE") == 2
    assert executable_sql.count("DROP CONSTRAINT IF EXISTS") == 1
    assert executable_sql.count("ADD CONSTRAINT") == 1
    assert "CREATE TABLE" not in sql
    assert "UPDATE " not in sql.upper()
    assert "DELETE FROM" not in sql.upper()
    assert "INSERT INTO" not in sql.upper()


def test_historical_migration_is_untouched() -> None:
    sql = _sql(ADMIN_MIGRATION)
    # The original 20260718 CHECK constraint must still declare only the
    # original three operation types -- this migration is not edited.
    assert (
        "CONSTRAINT chk_native_short_scope_admin_operation_v1_type\n"
        "        CHECK (operation_type IN (\n"
        "            'ADOPT_LEGACY_SCOPE',\n"
        "            'PROMOTE_SCOPE',\n"
        "            'REMOVE_SCOPE'\n"
        "        ))"
    ) in sql
    assert "AUTO_ONBOARD_SCOPE" not in sql


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 with explicit disposable MariaDB settings.",
)
def test_auto_onboard_scope_accepted_others_preserved_unknown_rejected() -> None:
    with _disposable_schema("type_fix") as connection:
        _apply_prerequisites(connection)

        # Before the fix, the exact AUTO_ONBOARD_SCOPE row production emits is
        # rejected by the stale constraint (reproduces MariaDB error 4025).
        with pytest.raises((IntegrityError, OperationalError)):
            _insert_operation_row(
                connection, operation_type="AUTO_ONBOARD_SCOPE", symbol="AAA"
            )
        connection.rollback()

        _apply(connection, FIX_MIGRATION)

        # All four canonical operation types are now accepted, including the
        # three original ones.
        for index, operation_type in enumerate(
            (
                "ADOPT_LEGACY_SCOPE",
                "PROMOTE_SCOPE",
                "AUTO_ONBOARD_SCOPE",
                "REMOVE_SCOPE",
            )
        ):
            _insert_operation_row(
                connection, operation_type=operation_type, symbol=f"SYM{index}"
            )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM native_short_scope_admin_operation_v1"
            )
            assert cursor.fetchone()["n"] == 4

        # An unknown operation type remains fail-closed after the fix.
        with pytest.raises((IntegrityError, OperationalError)):
            _insert_operation_row(
                connection, operation_type="NOT_A_REAL_OPERATION", symbol="ZZZ"
            )
        connection.rollback()

        # Reapplying the fix migration is idempotent (DROP CONSTRAINT IF
        # EXISTS + ADD CONSTRAINT with the same name and definition, matching
        # the labeled-idempotent sibling convention): a second application
        # succeeds and leaves the accepted set unchanged.
        _apply(connection, FIX_MIGRATION)
        _insert_operation_row(
            connection, operation_type="AUTO_ONBOARD_SCOPE", symbol="REPLAY"
        )
        with pytest.raises((IntegrityError, OperationalError)):
            _insert_operation_row(
                connection, operation_type="NOT_A_REAL_OPERATION", symbol="REPLAY2"
            )
        connection.rollback()
