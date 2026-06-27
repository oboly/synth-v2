from __future__ import annotations

import ast
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


MIGRATION_PATH = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
TEMP_DB_NAME = "synth_pr1a_native_short_map_lifecycle_tmp"

DISPOSABLE_MARIADB_VALIDATION_COMMANDS = f"""python - <<'PY'
import os
from src.common.db import get_connection
TEMP_DB = "{TEMP_DB_NAME}_" + str(os.getpid())
conn = get_connection(database="information_schema")
try:
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{{TEMP_DB}}`")
        cur.execute(
            f"CREATE DATABASE `{{TEMP_DB}}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.commit()
finally:
    conn.close()
PY

python - <<'PY'
import os
from pathlib import Path
from src.common.db import get_connection
TEMP_DB = "{TEMP_DB_NAME}_" + str(os.getpid())
sql_text = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql").read_text(encoding="utf-8")

def split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\\n".join(buffer).strip()
            if statement.endswith(";"):
                statement = statement[:-1]
            if statement:
                statements.append(statement)
            buffer = []
    trailing = "\\n".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements

conn = get_connection(database=TEMP_DB)
try:
    with conn.cursor() as cur:
        for statement in split_sql_statements(sql_text):
            cur.execute(statement)
    conn.commit()
finally:
    conn.close()
PY

python - <<'PY'
import os
from src.common.db import get_connection
TEMP_DB = "{TEMP_DB_NAME}_" + str(os.getpid())
conn = get_connection(database=TEMP_DB)
try:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        print(cur.fetchall())
        cur.execute("SHOW FULL TABLES WHERE Table_type = 'VIEW'")
        print(cur.fetchall())
        cur.execute("SHOW CREATE TABLE native_short_map_v1")
        print(cur.fetchone())
        cur.execute("SHOW CREATE TABLE native_short_map_generation_event_v1")
        print(cur.fetchone())
        cur.execute("SHOW CREATE TABLE native_short_map_lifecycle_event_v1")
        print(cur.fetchone())
        cur.execute("SHOW CREATE VIEW native_short_map_current_lifecycle_v1")
        print(cur.fetchone())
finally:
    conn.close()
PY

python - <<'PY'
import os
from src.common.db import get_connection
TEMP_DB = "{TEMP_DB_NAME}_" + str(os.getpid())
conn = get_connection(database="information_schema")
try:
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{{TEMP_DB}}`")
    conn.commit()
finally:
    conn.close()
PY
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


def _ts(minutes: int) -> datetime:
    return datetime(2026, 6, 26, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes)


def _temp_db_name() -> str:
    return f"{TEMP_DB_NAME}_{os.getpid()}"


def test_migration_creates_required_tables() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS native_short_map_scope_v1" in sql
    assert "CREATE TABLE IF NOT EXISTS native_short_map_v1" in sql
    assert "CREATE TABLE IF NOT EXISTS native_short_map_generation_event_v1" in sql
    assert "CREATE TABLE IF NOT EXISTS native_short_map_lifecycle_event_v1" in sql


def test_migration_scope_identity_includes_quote_currency_everywhere() -> None:
    sql = _sql()
    assert "quote_currency" in sql
    assert "venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval" in sql
    assert "active_map.quote_currency      = s.quote_currency" in sql
    assert "authoritative_generation.quote_currency      = s.quote_currency" in sql
    assert "terminal_map.quote_currency      = s.quote_currency" in sql


def test_migration_exposes_first_class_immutable_map_provenance_fields() -> None:
    sql = _sql()
    for required_column in (
        "generator_name",
        "generator_version",
        "fib_model_name",
        "fib_model_version",
        "published_generation_attempt_id",
        "previous_map_id",
        "previous_map_cycle_id",
        "anchor_low_ts_utc",
        "anchor_low_price",
        "anchor_high_ts_utc",
        "anchor_high_price",
        "retrace_ratio",
        "retrace_price",
        "fib_ratios_json",
        "target_levels_json",
        "invalidation_price",
        "invalidation_rule",
        "source_primary_candle_ts_utc",
        "source_support_candle_ts_utc",
        "source_primary_ref",
        "source_support_ref",
        "source_primary_candle_count",
        "source_support_candle_count",
    ):
        assert required_column in sql


def test_migration_duplicate_definition_identity_excludes_market_snapshot_timestamp() -> None:
    sql = _sql()
    assert "UNIQUE KEY uq_native_short_map_v1_definition" in sql
    assert "generator_name" in sql
    assert "generator_version" in sql
    assert "structure_hash" in sql
    identity_tail = sql.split("UNIQUE KEY uq_native_short_map_v1_definition", 1)[1].split(")", 1)[0]
    assert "market_snapshot_ts_utc" not in identity_tail


def test_migration_contains_cross_scope_fk_for_published_maps() -> None:
    sql = _sql()
    assert "UNIQUE KEY uq_native_short_map_v1_map_scope" in sql
    assert "CONSTRAINT fk_native_short_map_generation_event_v1_map_scope" in sql
    assert "FOREIGN KEY (" in sql
    assert "REFERENCES native_short_map_v1 (" in sql
    assert "quote_currency" in sql.split("CONSTRAINT fk_native_short_map_generation_event_v1_map_scope", 1)[1]


def test_migration_uses_final_primary_states() -> None:
    sql = _sql()
    for state in (
        "MAP_ACTIVE",
        "MAP_REBUILD_REQUIRED",
        "MAP_GENERATING",
        "MAP_REBUILD_REJECTED",
        "MAP_DATA_UNAVAILABLE",
        "MAP_GENERATION_FAILED",
        "MAP_NOT_APPLICABLE",
    ):
        assert state in sql


def test_migration_does_not_use_forbidden_primary_state() -> None:
    sql = _sql()
    assert "NO_PUBLISHED_MAP" not in sql


def test_migration_contains_required_generation_and_lifecycle_events() -> None:
    sql = _sql()
    for event_type in ("ATTEMPT_STARTED", "PUBLISHED", "REJECTED", "SKIPPED", "FAILED"):
        assert event_type in sql


def test_migration_exposes_first_class_generation_audit_fields() -> None:
    sql = _sql()
    for required_column in (
        "trigger_type",
        "candidate_map_cycle_id",
        "candidate_previous_map_id",
        "candidate_primary_lifecycle_state",
        "candidate_current_map_status",
        "latest_primary_close_ts_utc",
        "latest_support_close_ts_utc",
        "latest_primary_close_price",
        "source_primary_ref",
        "source_support_ref",
        "source_primary_candle_count",
        "source_support_candle_count",
    ):
        assert required_column in sql


def test_migration_exposes_lifecycle_market_provenance_and_self_references() -> None:
    sql = _sql()
    for required_column in (
        "observed_current_price",
        "observed_max_high_since_anchor",
        "observed_min_low_since_anchor",
        "latest_primary_close_ts_utc",
        "latest_support_close_ts_utc",
        "observer_name",
        "observer_version",
        "CONSTRAINT fk_native_short_map_lifecycle_event_v1_successor_map",
        "CONSTRAINT fk_native_short_map_v1_previous_map",
    ):
        assert required_column in sql
    for event_type in ("ACTIVATED", "COMPLETED", "EXPIRED", "INVALIDATED", "SUPERSEDED"):
        assert event_type in sql


def test_migration_contains_data_unavailable_reason_codes() -> None:
    sql = _sql()
    for reason_code in (
        "CANDLES_INSUFFICIENT",
        "CANDLE_GAPS_DETECTED",
        "CANDLE_SNAPSHOT_STALE",
        "ASSET_HISTORY_TOO_SHORT",
        "INGEST_LOOKBACK_LIMIT",
        "NO_CLOSED_DAILY_CANDLES",
    ):
        assert reason_code in sql


def test_migration_orders_events_by_ids_and_maps_by_published_at_then_map_id() -> None:
    sql = _sql()
    assert "MAX(lifecycle_event_id) AS max_lifecycle_event_id" in sql
    assert "MAX(generation_event_id) AS max_generation_event_id" in sql
    assert "other_m.published_at_utc > m.published_at_utc" in sql
    assert "other_m.published_at_utc = m.published_at_utc" in sql
    assert "other_m.map_id > m.map_id" in sql


def test_migration_enforces_terminal_exclusivity_and_append_only_shape() -> None:
    sql = _sql()
    assert "terminal_attempt_guard" in sql
    assert "terminal_map_guard" in sql
    assert "UNIQUE KEY uq_native_short_map_generation_event_v1_terminal_guard" in sql
    assert "UNIQUE KEY uq_native_short_map_lifecycle_event_v1_terminal_guard" in sql
    map_table = sql.split("CREATE TABLE IF NOT EXISTS native_short_map_v1", 1)[1].split(
        "CREATE TABLE IF NOT EXISTS native_short_map_generation_event_v1",
        1,
    )[0]
    assert "updated_at_utc" not in map_table


def test_market_data_contract_module_stays_market_only() -> None:
    source = Path("src/market_data/native_short_map_lifecycle_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
            imports.extend(f"{node.module}.{alias.name}" for alias in node.names)
    for forbidden in ("decision_gate", "execution_planner", "executor", "account", "broker", "wallet", "zone"):
        for imported in imports:
            assert forbidden not in imported


def test_disposable_mariadb_validation_harness_uses_temp_schema_and_repo_helper() -> None:
    assert f'{TEMP_DB_NAME}_' in DISPOSABLE_MARIADB_VALIDATION_COMMANDS
    assert "os.getpid()" in DISPOSABLE_MARIADB_VALIDATION_COMMANDS
    assert "from src.common.db import get_connection" in DISPOSABLE_MARIADB_VALIDATION_COMMANDS
    assert "DROP DATABASE IF EXISTS" in DISPOSABLE_MARIADB_VALIDATION_COMMANDS
    assert "CREATE DATABASE" in DISPOSABLE_MARIADB_VALIDATION_COMMANDS
    assert "SHOW CREATE VIEW native_short_map_current_lifecycle_v1" in DISPOSABLE_MARIADB_VALIDATION_COMMANDS


def test_migration_view_lifecycle_state_source_terminal_map_precedes_published_path() -> None:
    sql = _sql()
    # Extract the lifecycle_state_source CASE block from the view definition.
    after_state_col = sql.split("END AS lifecycle_state,", 1)[1]
    source_case = after_state_col.split("END AS lifecycle_state_source", 1)[0]
    # FAILED and REJECTED must be named explicitly — not the old broad IS NOT NULL check.
    assert "event_type IN ('FAILED', 'REJECTED')" in source_case
    # Terminal map outcome must emit the constant 'TERMINAL_MAP'.
    assert "THEN 'TERMINAL_MAP'" in source_case
    # The old broad authoritative check (which let PUBLISHED through) must be absent.
    assert "authoritative_generation.generation_event_id IS NOT NULL THEN" not in source_case
    # FAILED/REJECTED check must appear before TERMINAL_MAP in CASE evaluation order.
    assert source_case.index("IN ('FAILED', 'REJECTED')") < source_case.index("THEN 'TERMINAL_MAP'")


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_migration_executes_in_disposable_mariadb_schema() -> None:
    from src.common.db import get_connection
    from pymysql.err import IntegrityError
    from pymysql.err import OperationalError

    temp_db_name = _temp_db_name()
    schema_conn = None
    schema_created = False
    cleanup_confirmed = False
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
            schema_created = True
        finally:
            admin_conn.close()

        schema_conn = get_connection(database=temp_db_name)
        statements = _split_sql_statements(_sql())
        with schema_conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)

            cur.execute(
                """
                INSERT INTO native_short_map_scope_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    scope_support_state
                ) VALUES
                    ('BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED'),
                    ('BITVAVO', 'ETH', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED'),
                    ('BITVAVO', 'XRP', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED')
                """
            )
            schema_conn.commit()

            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'LTC', 'EUR', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'dup-hash',
                    'attempt-100', %s, %s, '[]', '[]', '{}'
                )
                """,
                (100, _ts(0), _ts(0)),
            )
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_v1 (
                        map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                        generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                        published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                        fib_ratios_json, target_levels_json, map_payload_json
                    ) VALUES (
                        %s, 'BITVAVO', 'LTC', 'EUR', 'SHORT', '4h', '1h',
                        'native_short_map_generator', 'v1', 'fib_model', 'v1', 'dup-hash',
                        'attempt-101', %s, %s, '[]', '[]', '{}'
                    )
                    """,
                    (101, _ts(1), _ts(1)),
                )
            schema_conn.rollback()

            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'ADA', 'USD', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'ada-usd-hash',
                    'attempt-110', %s, %s, '[]', '[]', '{}'
                )
                """,
                (110, _ts(2), _ts(2)),
            )
            cur.execute(
                """
                INSERT INTO native_short_map_generation_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generation_attempt_id, event_type, event_ts_utc
                ) VALUES (
                    'BITVAVO', 'ADA', 'EUR', 'SHORT', '4h', '1h',
                    'attempt-110', 'ATTEMPT_STARTED', %s
                )
                """,
                (_ts(2),),
            )
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_generation_event_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                        generation_attempt_id, event_type, event_ts_utc, map_id
                    ) VALUES (
                        'BITVAVO', 'ADA', 'EUR', 'SHORT', '4h', '1h',
                        'attempt-110', 'PUBLISHED', %s, %s
                    )
                    """,
                    (_ts(3), 110),
                )
            schema_conn.rollback()

            cur.execute(
                """
                INSERT INTO native_short_map_generation_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generation_attempt_id, event_type, event_ts_utc
                ) VALUES
                    ('BITVAVO', 'DOT', 'EUR', 'SHORT', '4h', '1h', 'attempt-120', 'ATTEMPT_STARTED', %s),
                    ('BITVAVO', 'DOT', 'EUR', 'SHORT', '4h', '1h', 'attempt-120', 'REJECTED', %s)
                """,
                (_ts(4), _ts(5)),
            )
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_generation_event_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                        generation_attempt_id, event_type, event_ts_utc
                    ) VALUES (
                        'BITVAVO', 'DOT', 'EUR', 'SHORT', '4h', '1h',
                        'attempt-120', 'FAILED', %s
                    )
                    """,
                    (_ts(6),),
                )
            schema_conn.rollback()

            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'SOL', 'EUR', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'sol-eur-hash',
                    'attempt-130', %s, %s, '[]', '[]', '{}'
                )
                """,
                (130, _ts(7), _ts(7)),
            )
            cur.execute(
                """
                INSERT INTO native_short_map_lifecycle_event_v1 (
                    map_id, lifecycle_event_type, event_ts_utc
                ) VALUES (%s, 'COMPLETED', %s)
                """,
                (130, _ts(8)),
            )
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_lifecycle_event_v1 (
                        map_id, lifecycle_event_type, event_ts_utc
                    ) VALUES (%s, 'INVALIDATED', %s)
                    """,
                    (130, _ts(9)),
                )
            schema_conn.rollback()

            cur.execute(
                """
                INSERT INTO native_short_map_generation_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generation_attempt_id, event_type, event_ts_utc, reason_code
                ) VALUES
                    ('BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'attempt-btc', 'ATTEMPT_STARTED', %s, NULL),
                    ('BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'attempt-btc', 'REJECTED', %s, 'CANDLES_INSUFFICIENT')
                """,
                (_ts(10), _ts(11)),
            )

            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'ETH', 'EUR', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'eth-eur-hash',
                    'attempt-200', %s, %s, '[]', '[]', '{}'
                )
                """,
                (200, _ts(12), _ts(12)),
            )
            cur.execute(
                """
                INSERT INTO native_short_map_generation_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generation_attempt_id, event_type, event_ts_utc, map_id
                ) VALUES
                    ('BITVAVO', 'ETH', 'EUR', 'SHORT', '4h', '1h', 'attempt-200', 'ATTEMPT_STARTED', %s, NULL),
                    ('BITVAVO', 'ETH', 'EUR', 'SHORT', '4h', '1h', 'attempt-200', 'PUBLISHED', %s, %s)
                """,
                (_ts(12), _ts(13), 200),
            )
            cur.execute(
                """
                INSERT INTO native_short_map_lifecycle_event_v1 (
                    map_id, lifecycle_event_type, event_ts_utc
                ) VALUES (%s, 'COMPLETED', %s)
                """,
                (200, _ts(14)),
            )

            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'XRP', 'EUR', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'xrp-eur-old',
                    'attempt-300', %s, %s, '[]', '[]', '{}'
                )
                """,
                (300, _ts(15), _ts(15)),
            )
            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    previous_map_id,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'XRP', 'EUR', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'xrp-eur-new',
                    'attempt-301', %s, %s, %s, '[]', '[]', '{}'
                )
                """,
                (301, _ts(16), _ts(16), 300),
            )
            cur.execute(
                """
                INSERT INTO native_short_map_generation_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generation_attempt_id, event_type, event_ts_utc, map_id
                ) VALUES
                    ('BITVAVO', 'XRP', 'EUR', 'SHORT', '4h', '1h', 'attempt-300', 'ATTEMPT_STARTED', %s, NULL),
                    ('BITVAVO', 'XRP', 'EUR', 'SHORT', '4h', '1h', 'attempt-300', 'PUBLISHED', %s, %s),
                    ('BITVAVO', 'XRP', 'EUR', 'SHORT', '4h', '1h', 'attempt-301', 'ATTEMPT_STARTED', %s, NULL),
                    ('BITVAVO', 'XRP', 'EUR', 'SHORT', '4h', '1h', 'attempt-301', 'PUBLISHED', %s, %s)
                """,
                (_ts(15), _ts(15), 300, _ts(16), _ts(16), 301),
            )
            cur.execute(
                """
                INSERT INTO native_short_map_lifecycle_event_v1 (
                    map_id, lifecycle_event_type, successor_map_id, event_ts_utc
                ) VALUES
                    (%s, 'SUPERSEDED', %s, %s),
                    (%s, 'ACTIVATED', NULL, %s)
                """,
                (300, 301, _ts(17), 301, _ts(18)),
            )

            cur.execute(
                """
                SELECT symbol, quote_currency, lifecycle_state, lifecycle_state_source,
                       active_map_id, latest_terminal_map_id
                FROM native_short_map_current_lifecycle_v1
                WHERE symbol IN ('BTC', 'ETH', 'XRP')
                ORDER BY symbol
                """
            )
            rows = cur.fetchall()

        schema_conn.commit()

        projection_by_symbol = {row["symbol"]: row for row in rows}
        assert projection_by_symbol["BTC"]["lifecycle_state"] == "MAP_DATA_UNAVAILABLE"
        assert projection_by_symbol["ETH"]["lifecycle_state"] == "MAP_REBUILD_REQUIRED"
        assert projection_by_symbol["ETH"]["lifecycle_state_source"] == "TERMINAL_MAP"
        assert projection_by_symbol["ETH"]["latest_terminal_map_id"] == 200
        assert projection_by_symbol["XRP"]["lifecycle_state"] == "MAP_ACTIVE"
        assert projection_by_symbol["XRP"]["active_map_id"] == 301
    finally:
        if schema_conn is not None:
            schema_conn.close()
        if schema_created:
            cleanup_conn = get_connection(database="information_schema")
            try:
                with cleanup_conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
                    cur.execute("SHOW DATABASES LIKE %s", (temp_db_name,))
                    cleanup_confirmed = cur.fetchone() is None
                cleanup_conn.commit()
            finally:
                cleanup_conn.close()
    assert cleanup_confirmed
