from __future__ import annotations

import ast
from pathlib import Path


MIGRATION_PATH = Path("db/migrations/20260706_native_short_scope_status_persistence_v1.sql")


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_creates_only_required_new_tables() -> None:
    sql = _sql()
    expected_tables = {
        "native_short_materializer_run_v1",
        "native_short_scope_observation_v1",
        "native_short_scope_status_v1",
        "native_short_scope_cadence_config_v1",
        "native_short_scope_support_event_v1",
    }
    for table in expected_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert sql.count("CREATE TABLE IF NOT EXISTS") == len(expected_tables)


def test_migration_uses_full_canonical_scope_key_without_symbol_only_identity() -> None:
    sql = _sql()
    full_key = "venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval"
    assert full_key in sql
    assert "UNIQUE KEY uq_native_short_scope_status_v1_scope" in sql
    assert "UNIQUE KEY uq_native_short_scope_cadence_config_v1_scope_version" in sql
    assert "KEY idx_native_short_scope_support_event_v1_scope_event" in sql
    assert "KEY idx_native_short_scope_support_event_v1_scope_state_event" in sql
    assert "UNIQUE KEY uq_symbol" not in sql
    assert "KEY idx_symbol" not in sql


def test_migration_contains_required_indexes_and_projection_clock() -> None:
    sql = _sql()
    for required in (
        "UNIQUE KEY uq_native_short_materializer_run_v1_uuid",
        "KEY idx_native_short_materializer_run_v1_started",
        "UNIQUE KEY uq_native_short_scope_observation_v1_run_scope",
        "KEY idx_native_short_scope_status_v1_code",
        "KEY idx_native_short_scope_status_v1_actionability",
        "KEY idx_native_short_scope_status_v1_observed",
        "KEY idx_native_short_scope_status_v1_map",
        "projection_as_of_utc DATETIME(6) NOT NULL",
    ):
        assert required in sql


def test_migration_has_closed_selected_map_lifecycle_constraint() -> None:
    sql = _sql()
    status_section = sql.split("CREATE TABLE IF NOT EXISTS native_short_scope_status_v1", 1)[1]
    status_section = status_section.split("CREATE TABLE IF NOT EXISTS native_short_scope_cadence_config_v1", 1)[0]
    assert "CONSTRAINT chk_native_short_scope_status_v1_map_lifecycle" in status_section
    for value in (
        "MAP_ACTIVE",
        "MAP_INVALIDATED",
        "MAP_COMPLETED",
        "MAP_EXPIRED",
        "NO_CURRENT_MAP",
    ):
        assert value in status_section
    assert "MAP_SUPERSEDED" not in status_section


def test_migration_support_event_contract_and_tie_break_indexes() -> None:
    sql = _sql()
    support_section = sql.split("CREATE TABLE IF NOT EXISTS native_short_scope_support_event_v1", 1)[1]
    for required in (
        "scope_support_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY",
        "scope_support_state VARCHAR(32) NOT NULL",
        "event_ts_utc DATETIME(6) NOT NULL",
        "source_name VARCHAR(96) NOT NULL",
        "source_version VARCHAR(32) NOT NULL",
        "event_metadata_json LONGTEXT NULL",
        "created_at_utc DATETIME(6) NOT NULL",
        "event_ts_utc, scope_support_event_id",
        "scope_support_state, event_ts_utc",
        "CHECK (scope_support_state IN ('SUPPORTED', 'NOT_APPLICABLE'))",
    ):
        assert required in support_section


def test_migration_backfill_uses_current_registry_without_updated_at_history() -> None:
    sql = _sql()
    backfill = sql.split("INSERT INTO native_short_scope_support_event_v1", 1)[1]
    assert "FROM native_short_map_scope_v1 s" in backfill
    assert "s.scope_support_state" in backfill
    assert "UTC_TIMESTAMP(6)" in sql
    assert "UNKNOWN_AT_AS_OF" in backfill
    assert "updated_at_utc" not in backfill


def test_migration_backfill_is_duplicate_guarded() -> None:
    sql = _sql()
    backfill = sql.split("INSERT INTO native_short_scope_support_event_v1", 1)[1]
    assert "WHERE NOT EXISTS" in backfill
    for key_part in (
        "existing.venue               = s.venue",
        "existing.symbol              = s.symbol",
        "existing.quote_currency      = s.quote_currency",
        "existing.fib_trading_horizon = s.fib_trading_horizon",
        "existing.primary_interval    = s.primary_interval",
        "existing.supporting_interval = s.supporting_interval",
        "existing.source_name         = 'native_short_scope_status_persistence_v1_migration'",
        "existing.source_version      = '20260706'",
    ):
        assert key_part in backfill


def test_migration_has_closed_domain_checks() -> None:
    sql = _sql()
    for value in (
        "FINISHED",
        "INTERRUPTED",
        "SKIPPED_SOURCE_UNAVAILABLE",
        "SOURCE_UNAVAILABLE",
        "MAP_INVALIDATED",
        "CURRENT_EVALUATION",
        "ACTIONABLE_ACTIVE_MAP",
        "OBSERVATION_OVERDUE",
        "SUPPORTED",
        "NOT_APPLICABLE",
    ):
        assert value in sql


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


def test_new_type_module_imports_no_forbidden_layers() -> None:
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
