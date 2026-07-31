from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

MIGRATION_PATH = Path("db/migrations/20260731_native_short_map_level_target_event_v1.sql")
LIFECYCLE_MIGRATION_PATH = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
LEVEL_STATUS_MIGRATION_PATH = Path("db/migrations/20260708_native_short_map_level_status_v1.sql")
TEMP_DB_NAME = "synth_native_short_target_event_tmp"


def _sql(path: Path = MIGRATION_PATH) -> str:
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
            if statement.endswith(";"):
                statement = statement[:-1]
            if statement:
                statements.append(statement)
            buffer = []
    trailing = "\n".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _ts(hours: int) -> datetime:
    return datetime(2026, 7, 31, 0, 0, tzinfo=UTC) + timedelta(hours=hours)


def _temp_db_name() -> str:
    return f"{TEMP_DB_NAME}_{os.getpid()}"


def test_migration_scope_identity_and_map_fk() -> None:
    sql = _sql()
    assert "quote_currency" in sql
    assert "CONSTRAINT fk_native_short_map_level_target_event_v1_map" in sql
    assert "FOREIGN KEY (map_id) REFERENCES native_short_map_v1 (map_id)" in sql


def test_migration_uses_only_reached_and_passed_event_types() -> None:
    sql = _sql()
    assert "REACHED" in sql
    assert "PASSED" in sql
    assert "'REACHED', 'PASSED'" in sql
    # No ACTIVE event type exists in this ledger by design.
    type_check = sql.split("CONSTRAINT chk_native_short_map_level_target_event_v1_type", 1)[1].split(
        ")", 1
    )[0]
    assert "ACTIVE" not in type_check


def test_migration_recorded_at_distinct_from_effective_at_and_never_updated() -> None:
    sql = _sql()
    table_block = sql.split(
        "CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_v1", 1
    )[1].split("CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_coverage_v1", 1)[0]
    assert "effective_at_utc" in table_block
    assert "recorded_at_utc" in table_block
    assert "ON UPDATE" not in table_block


def test_migration_creates_immutable_per_map_coverage_table() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_coverage_v1" in sql
    coverage_block = sql.split(
        "CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_coverage_v1", 1
    )[1].split("CREATE OR REPLACE VIEW", 1)[0]
    assert "map_id BIGINT UNSIGNED NOT NULL PRIMARY KEY" in coverage_block
    assert "coverage_cutoff_utc" in coverage_block
    assert "publication_boundary_utc" in coverage_block
    assert "requested_watermark_utc_at_establishment" in coverage_block
    assert "ON UPDATE" not in coverage_block


def test_migration_coverage_cutoff_bounded_below_by_both_boundaries() -> None:
    sql = _sql()
    coverage_block = sql.split(
        "CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_coverage_v1", 1
    )[1].split("CREATE OR REPLACE VIEW", 1)[0]
    assert "coverage_cutoff_utc >= publication_boundary_utc" in coverage_block
    assert "coverage_cutoff_utc >= requested_watermark_utc_at_establishment" in coverage_block


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to validate the migration in a disposable schema.",
)
def test_migration_executes_and_enforces_append_only_identity_in_disposable_schema() -> None:
    from src.common.db import get_connection
    from pymysql.err import IntegrityError, OperationalError

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
                            "Configured DB user lacks CREATE/DROP DATABASE privilege "
                            "for disposable schema validation."
                        )
                    raise
            admin_conn.commit()
            schema_created = True
        finally:
            admin_conn.close()

        schema_conn = get_connection(database=temp_db_name)
        with schema_conn.cursor() as cur:
            for statement in _split_sql_statements(_sql(LIFECYCLE_MIGRATION_PATH)):
                cur.execute(statement)
            for statement in _split_sql_statements(_sql(LEVEL_STATUS_MIGRATION_PATH)):
                cur.execute(statement)
            for statement in _split_sql_statements(_sql()):
                cur.execute(statement)
            schema_conn.commit()

            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    map_cycle_id, anchor_high_ts_utc, anchor_high_price,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'target-event-hash',
                    'attempt-500', %s, %s,
                    'cycle-A', %s, 10.0,
                    '{"ext_1_272": "10.5", "ext_1_618": "11.2", "ext_2_000": "12.0"}', '[]', '{}'
                )
                """,
                (500, _ts(0), _ts(0), _ts(-4)),
            )
            schema_conn.commit()

            cur.execute(
                """
                INSERT INTO native_short_map_level_target_event_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    map_id, map_cycle_id, canonical_map_level_role, side, canonical_unrounded_price,
                    target_event_type, causal_candle_close_ts_utc, causal_candle_high_price,
                    effective_at_utc, reason_code, writer_name, writer_version, writer_invocation_uuid
                ) VALUES (
                    'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                    %s, 'cycle-A', 'SELL_EXT_1_272', 'SELL', 10.5,
                    'REACHED', %s, 10.6,
                    %s, 'PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE', 'test-writer', '0.1',
                    '00000000-0000-4000-8000-000000000001'
                )
                """,
                (500, _ts(4), _ts(4)),
            )
            schema_conn.commit()

            # Duplicate canonical identity (same map/role/side/price/type) must be rejected.
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_level_target_event_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                        map_id, map_cycle_id, canonical_map_level_role, side, canonical_unrounded_price,
                        target_event_type, causal_candle_close_ts_utc, causal_candle_high_price,
                        effective_at_utc, reason_code, writer_name, writer_version, writer_invocation_uuid
                    ) VALUES (
                        'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                        %s, 'cycle-A', 'SELL_EXT_1_272', 'SELL', 10.5,
                        'REACHED', %s, 10.7,
                        %s, 'PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE', 'test-writer', '0.1',
                        '00000000-0000-4000-8000-000000000002'
                    )
                    """,
                    (500, _ts(8), _ts(8)),
                )
            schema_conn.rollback()

            # effective_at_utc must match causal_candle_close_ts_utc exactly.
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_level_target_event_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                        map_id, map_cycle_id, canonical_map_level_role, side, canonical_unrounded_price,
                        target_event_type, causal_candle_close_ts_utc, causal_candle_high_price,
                        effective_at_utc, reason_code, writer_name, writer_version, writer_invocation_uuid
                    ) VALUES (
                        'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                        %s, 'cycle-A', 'SELL_EXT_1_618', 'SELL', 11.2,
                        'REACHED', %s, 11.3,
                        %s, 'PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE', 'test-writer', '0.1',
                        '00000000-0000-4000-8000-000000000003'
                    )
                    """,
                    (500, _ts(8), _ts(9)),
                )
            schema_conn.rollback()

            cur.execute(
                "SELECT target_event_type, effective_at_utc FROM native_short_map_level_target_event_v1 WHERE map_id = %s",
                (500,),
            )
            rows = cur.fetchall()
            schema_conn.commit()

            # Immutable per-map coverage: exactly one row per map_id.
            cur.execute(
                """
                INSERT INTO native_short_map_level_target_event_coverage_v1 (
                    venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    map_id, map_cycle_id, publication_boundary_utc,
                    requested_watermark_utc_at_establishment, coverage_cutoff_utc,
                    writer_name, writer_version, writer_invocation_uuid
                ) VALUES (
                    'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                    %s, 'cycle-A', %s, %s, %s,
                    'test-writer', '0.1', '00000000-0000-4000-8000-000000000001'
                )
                """,
                (500, _ts(0), _ts(0), _ts(0)),
            )
            schema_conn.commit()

            # A second coverage row for the same map_id must be rejected (PK).
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_level_target_event_coverage_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                        map_id, map_cycle_id, publication_boundary_utc,
                        requested_watermark_utc_at_establishment, coverage_cutoff_utc,
                        writer_name, writer_version, writer_invocation_uuid
                    ) VALUES (
                        'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                        %s, 'cycle-A', %s, %s, %s,
                        'test-writer', '0.1', '00000000-0000-4000-8000-000000000009'
                    )
                    """,
                    (500, _ts(1), _ts(1), _ts(1)),
                )
            schema_conn.rollback()

            # A cutoff below either boundary must be rejected (needs a second
            # valid map row so the FK constraint alone doesn't explain it).
            cur.execute(
                """
                INSERT INTO native_short_map_v1 (
                    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                    generator_name, generator_version, fib_model_name, fib_model_version, structure_hash,
                    published_generation_attempt_id, market_snapshot_ts_utc, published_at_utc,
                    map_cycle_id, anchor_high_ts_utc, anchor_high_price,
                    fib_ratios_json, target_levels_json, map_payload_json
                ) VALUES (
                    %s, 'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                    'native_short_map_generator', 'v1', 'fib_model', 'v1', 'target-event-hash-2',
                    'attempt-501', %s, %s,
                    'cycle-B', %s, 10.0,
                    '{"ext_1_272": "10.5", "ext_1_618": "11.2", "ext_2_000": "12.0"}', '[]', '{}'
                )
                """,
                (501, _ts(5), _ts(5), _ts(1)),
            )
            schema_conn.commit()
            with pytest.raises(IntegrityError):
                cur.execute(
                    """
                    INSERT INTO native_short_map_level_target_event_coverage_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                        map_id, map_cycle_id, publication_boundary_utc,
                        requested_watermark_utc_at_establishment, coverage_cutoff_utc,
                        writer_name, writer_version, writer_invocation_uuid
                    ) VALUES (
                        'BITVAVO', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                        %s, 'cycle-B', %s, %s, %s,
                        'test-writer', '0.1', '00000000-0000-4000-8000-000000000010'
                    )
                    """,
                    (501, _ts(5), _ts(5), _ts(0)),
                )
            schema_conn.rollback()

            cur.execute(
                "SELECT map_id, coverage_cutoff_utc FROM native_short_map_level_target_event_coverage_v1 WHERE map_id = %s",
                (500,),
            )
            coverage_rows = cur.fetchall()
        schema_conn.commit()
        assert len(coverage_rows) == 1
        assert len(rows) == 1
        assert rows[0]["target_event_type"] == "REACHED"
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
