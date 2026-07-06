from __future__ import annotations

"""Opt-in live-MariaDB integration coverage for PR A2's actual SQL writers.

Extends the existing disposable-schema testing convention (see
tests/test_native_short_map_lifecycle_migration_v1.py and
tests/test_native_short_cadence_unavailable_migration_v1.py): applies the
existing, unmodified A1 + A1b migrations to a disposable schema, then runs
`run_native_short_scope_status_materializer` for real against that schema —
no fakes, no mocks — and verifies the persisted rows.

No new migrations are written or applied here; only the three that already
exist are re-executed against the disposable schema:
- db/migrations/20260626_native_short_map_lifecycle_v1.sql (prerequisite)
- db/migrations/20260706_native_short_scope_status_persistence_v1.sql (A1)
- db/migrations/20260707_native_short_cadence_unavailable_v1.sql (A1b)

`materialize_scope_symbol_fn` and the map/generation/lifecycle fetch
callbacks are injected stubs returning empty/canned results: scenario B
deliberately avoids seeding native_short_map_scope_v1 / native_short_map_v1 /
generation-event data, since that geometry-materializer machinery is already
covered by its own existing test suite and is not this module's concern.

Test isolation boundary (important):
This test must never reach any configured/project database. It does not
import src.common.db or dotenv, and does not read a .env file. It connects
only via `pymysql.connect(...)` using explicit, test-only
`SYNTH_TEST_MARIADB_*` environment variables that a caller (GitHub Actions,
or a developer who deliberately opts in) must supply in full. If any of them
is absent, or if `SYNTH_TEST_MARIADB_DISPOSABLE` is not exactly "1", the test
skips before ever constructing a database connection.

Gated behind RUN_MARIADB_DDL_TEST=1, matching the existing convention, so it
is opt-in locally and runs for real in the hosted GitHub Actions workflow.
"""

import ast
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pymysql
import pytest
from pymysql.cursors import DictCursor

from src.market_data.native_short_fib_context_v1 import STATUS_AVAILABLE, NativeShortContextRow
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_map_materializer_v1 import ScopeMaterializationResult
from src.market_data.native_short_scope_status_materializer_v1 import (
    NativeShortRunTerminalizationConflictError,
    _finalize_run,
    run_native_short_scope_status_materializer,
)
from src.market_data.native_short_scope_status_v1 import NativeShortMaterializerRunRecord

PREREQUISITE_MIGRATION_PATH = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
A1_MIGRATION_PATH = Path("db/migrations/20260706_native_short_scope_status_persistence_v1.sql")
A1B_MIGRATION_PATH = Path("db/migrations/20260707_native_short_cadence_unavailable_v1.sql")

TEMP_DB_NAME = "synth_a2_native_short_scope_status_materializer_tmp"

_AS_OF = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)

_REQUIRED_ENV_VARS = (
    "SYNTH_TEST_MARIADB_HOST",
    "SYNTH_TEST_MARIADB_PORT",
    "SYNTH_TEST_MARIADB_USER",
    "SYNTH_TEST_MARIADB_PASSWORD",
    "SYNTH_TEST_MARIADB_ADMIN_DATABASE",
)


def _require_test_mariadb_config() -> dict[str, str]:
    """Returns the complete explicit test-only MariaDB connection config, or
    calls pytest.skip() before returning if any required
    SYNTH_TEST_MARIADB_* variable is absent.

    Reads only these five explicit variables. Never reads DB_HOST/DB_USER/
    DB_PASSWORD/DB_NAME, never loads a .env file, and never falls back to
    project configuration, localhost defaults, or production-like
    credentials.
    """
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in _REQUIRED_ENV_VARS:
        value = os.environ.get(name)
        if value is None or value == "":
            missing.append(name)
        else:
            values[name] = value
    if missing:
        pytest.skip(
            "No disposable test MariaDB configuration was supplied; missing: "
            f"{', '.join(missing)}. This test connects only via explicit "
            "SYNTH_TEST_MARIADB_* variables and never falls back to project "
            "configuration, .env, or default credentials."
        )
    return values


def _require_disposable_flag() -> None:
    """Refuses to let the test proceed to a connection attempt unless the
    caller has explicitly asserted the target database is disposable."""
    if os.environ.get("SYNTH_TEST_MARIADB_DISPOSABLE") != "1":
        pytest.skip(
            "SYNTH_TEST_MARIADB_DISPOSABLE=1 is required before this test may "
            "CREATE/DROP a database; refusing to open a connection without it."
        )


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


def _key(symbol: str) -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(venue="bitvavo", symbol=symbol, quote_currency="EUR")


def _seed_support_event(conn: Any, key: NativeShortMapScopeKey, *, event_ts_utc: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_scope_support_event_v1 (
                venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                scope_support_state, event_ts_utc, source_name, source_version
            ) VALUES (%s, %s, %s, %s, %s, %s, 'SUPPORTED', %s, 'test_seed', 'v1')
            """,
            (key.venue, key.symbol, key.quote_currency, key.fib_trading_horizon,
             key.primary_interval, key.supporting_interval, event_ts_utc),
        )
    conn.commit()


def _seed_cadence_config(conn: Any, key: NativeShortMapScopeKey) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_scope_cadence_config_v1 (
                venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
                cadence_contract_version, target_evaluation_interval,
                primary_source_freshness_limit_seconds, supporting_source_freshness_limit_seconds,
                evaluation_grace_seconds, recent_scope_grace_seconds, effective_from_utc
            ) VALUES (%s, %s, %s, %s, %s, %s, 'v1', '1h', 43200, 10800, 900, 3600, %s)
            """,
            (key.venue, key.symbol, key.quote_currency, key.fib_trading_horizon,
             key.primary_interval, key.supporting_interval, _AS_OF - timedelta(days=60)),
        )
    conn.commit()


def _context_row(symbol: str) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol,
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=STATUS_AVAILABLE,
        map_cycle_id=f"{symbol}|SHORT|4h|cycle",
        anchor_start_ts_utc=_AS_OF - timedelta(days=10),
        anchor_end_ts_utc=_AS_OF - timedelta(days=5),
        anchor_low_price=None,
        anchor_high_price=None,
        breakout_gate_price=None,
        latest_primary_close_ts_utc=_AS_OF - timedelta(hours=1),
        latest_support_close_ts_utc=_AS_OF - timedelta(minutes=20),
        latest_primary_close_price=None,
        ext_1_272_price=None,
        ext_1_618_price=None,
        ext_2_000_price=None,
        active_target_levels=(),
        previous_target_levels=(),
        reload_r382_price=None,
        reload_r500_price=None,
        reload_r618_price=None,
        reload_r786_price=None,
        invalidation_price=None,
        primary_4h_lifecycle_state="TARGET_ACTIVE",
        supporting_1h_state="ALIGNED_WITH_4H",
        context_freshness_status="FRESH",
        max_primary_high_since_anchor=None,
        min_primary_low_since_anchor=None,
        source_name="native_short_fib_context_v1",
        source_version="0.1",
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
        current_map_status="CURRENT_ACTIVE_MAP",
        previous_map_cycle_id="",
        previous_map_lifecycle_state="",
        rollover_state="SINGLE_MAP",
        selection_reason="Single active map selected",
        source_primary_candle_count=73,
        source_support_candle_count=219,
    )


def _no_maps(conn: Any, key: NativeShortMapScopeKey) -> list[Any]:
    return []


def _no_generation_events(conn: Any, key: NativeShortMapScopeKey) -> list[Any]:
    return []


def _no_lifecycle_events(conn: Any, map_ids: list[int]) -> list[Any]:
    return []


def _no_candles(key: NativeShortMapScopeKey, as_of_utc: datetime) -> list[datetime]:
    return []


def _fresh_candles(key: NativeShortMapScopeKey, as_of_utc: datetime) -> list[datetime]:
    return [as_of_utc - timedelta(hours=1)]


def _unreachable_context_row(key: NativeShortMapScopeKey, as_of_utc: datetime) -> NativeShortContextRow:
    raise AssertionError(
        "fetch_context_row must not be called for a CONFIGURATION_UNAVAILABLE scope: "
        "no candle freshness/geometry evaluation may occur before cadence config eligibility."
    )


def _stub_materialize(*args: Any, **kwargs: Any) -> ScopeMaterializationResult:
    return ScopeMaterializationResult(
        symbol=kwargs.get("scope_support").key.symbol if "scope_support" in kwargs else "UNKNOWN",
        attempted=True,
        status="skipped",
        dry_run=False,
        reason_code="NO_MAP_AVAILABLE_TEST_STUB",
    )


@pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 to run A2 orchestrator integration against a disposable MariaDB schema.",
)
def test_a2_orchestrator_executes_against_disposable_mariadb_schema() -> None:
    config = _require_test_mariadb_config()
    _require_disposable_flag()

    admin_database = config["SYNTH_TEST_MARIADB_ADMIN_DATABASE"]
    temp_db_name = _temp_db_name()
    schema_conn = None
    try:
        admin_conn = _connect(config, database=admin_database)
        try:
            with admin_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
                cur.execute(
                    f"CREATE DATABASE `{temp_db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            admin_conn.commit()
        finally:
            admin_conn.close()

        schema_conn = _connect(config, database=temp_db_name)
        with schema_conn.cursor() as cur:
            for migration_path in (PREREQUISITE_MIGRATION_PATH, A1_MIGRATION_PATH, A1B_MIGRATION_PATH):
                for statement in _split_sql_statements(migration_path.read_text(encoding="utf-8")):
                    cur.execute(statement)
        schema_conn.commit()

        # --- Scenario A: SUPPORTED scope, no eligible cadence config --------
        btc = _key("BTC")
        _seed_support_event(schema_conn, btc, event_ts_utc=_AS_OF - timedelta(days=30))

        run_a = run_native_short_scope_status_materializer(
            schema_conn,
            scopes=[btc],
            as_of_utc=_AS_OF,
            trigger_type="MANUAL_MARIADB_INTEGRATION_TEST",
            operational_clock=lambda: _AS_OF,
            fetch_context_row=_unreachable_context_row,
            fetch_existing_maps=_no_maps,
            fetch_existing_generation_events=_no_generation_events,
            fetch_existing_lifecycle_events=_no_lifecycle_events,
            fetch_primary_candle_close_timestamps=_no_candles,
            fetch_supporting_candle_close_timestamps=_no_candles,
        )
        schema_conn.commit()

        with schema_conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM native_short_materializer_run_v1 WHERE run_uuid = %s",
                (run_a.run_uuid,),
            )
            run_rows = cur.fetchall()
            assert len(run_rows) == 1
            assert run_rows[0]["terminal_status"] == "FINISHED"

            cur.execute(
                "SELECT * FROM native_short_scope_observation_v1 WHERE venue = %s AND symbol = %s",
                (btc.venue, btc.symbol),
            )
            observation_rows = cur.fetchall()
            assert len(observation_rows) == 1
            observation = observation_rows[0]
            assert observation["observation_status"] == "SKIPPED_CONFIGURATION_UNAVAILABLE"
            assert observation["observation_reason_code"] == "NO_ELIGIBLE_CADENCE_CONFIG"
            assert observation["cadence_contract_version"] is None
            assert observation["source_state"] is None
            assert observation["geometry_action"] is None
            assert observation["primary_source_freshness_limit_seconds"] is None
            assert observation["supporting_source_freshness_limit_seconds"] is None

            cur.execute(
                "SELECT * FROM native_short_scope_status_v1 WHERE venue = %s AND symbol = %s",
                (btc.venue, btc.symbol),
            )
            status_rows = cur.fetchall()
            assert len(status_rows) == 1
            status = status_rows[0]
            assert status["scope_status_code"] == "CONFIGURATION_UNAVAILABLE"
            assert status["scope_status_reason_code"] == "NO_ELIGIBLE_CADENCE_CONFIG"
            assert status["actionability_state"] == "BLOCKED_CONFIGURATION"
            assert status["observation_freshness_state"] == "OBSERVATION_CONFIGURATION_UNAVAILABLE"
            assert status["cadence_contract_version"] is None
            assert status["primary_source_freshness_limit_seconds"] is None
            assert status["supporting_source_freshness_limit_seconds"] is None
            assert status["source_freshness_state"] is None
            assert status["next_expected_evaluation_at_utc"] is None
            assert status["observation_overdue_after_utc"] is None

        # --- Scenario B: SUPPORTED scope, eligible cadence config -----------
        eth = _key("ETH")
        _seed_support_event(schema_conn, eth, event_ts_utc=_AS_OF - timedelta(days=30))
        _seed_cadence_config(schema_conn, eth)

        run_b = run_native_short_scope_status_materializer(
            schema_conn,
            scopes=[eth],
            as_of_utc=_AS_OF,
            trigger_type="MANUAL_MARIADB_INTEGRATION_TEST",
            operational_clock=lambda: _AS_OF,
            fetch_context_row=lambda k, t: _context_row(k.symbol),
            fetch_existing_maps=_no_maps,
            fetch_existing_generation_events=_no_generation_events,
            fetch_existing_lifecycle_events=_no_lifecycle_events,
            fetch_primary_candle_close_timestamps=_fresh_candles,
            fetch_supporting_candle_close_timestamps=_fresh_candles,
            materialize_scope_symbol_fn=_stub_materialize,
        )
        schema_conn.commit()

        run_b_id: int | None = None
        with schema_conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM native_short_materializer_run_v1 WHERE run_uuid = %s",
                (run_b.run_uuid,),
            )
            run_rows = cur.fetchall()
            assert len(run_rows) == 1
            assert run_rows[0]["terminal_status"] == "FINISHED"
            run_b_id = run_rows[0]["run_id"]

            cur.execute(
                "SELECT * FROM native_short_scope_observation_v1 WHERE venue = %s AND symbol = %s",
                (eth.venue, eth.symbol),
            )
            observation_rows = cur.fetchall()
            assert len(observation_rows) == 1
            observation = observation_rows[0]
            assert observation["observation_status"] == "EVALUATED"
            assert observation["cadence_contract_version"] == "v1"
            assert observation["source_state"] == "SOURCE_CURRENT"
            assert observation["geometry_action"] == "NO_MAP_AVAILABLE"
            assert observation["primary_source_freshness_limit_seconds"] == 43200
            assert observation["supporting_source_freshness_limit_seconds"] == 10800

            cur.execute(
                "SELECT * FROM native_short_scope_status_v1 WHERE venue = %s AND symbol = %s",
                (eth.venue, eth.symbol),
            )
            status_rows = cur.fetchall()
            assert len(status_rows) == 1
            status = status_rows[0]
            assert status["scope_status_code"] == "CURRENT_EVALUATION"
            assert status["cadence_contract_version"] == "v1"
            assert status["primary_source_freshness_limit_seconds"] == 43200
            assert status["supporting_source_freshness_limit_seconds"] == 10800
            assert status["source_freshness_state"] == "SOURCE_CURRENT"

        # --- Scenario C: terminal compare-and-set ----------------------------
        assert run_b_id is not None
        conflicting = NativeShortMaterializerRunRecord(
            run_uuid=run_b.run_uuid,
            runner_name=run_b.runner_name,
            runner_version=run_b.runner_version,
            contract_version=run_b.contract_version,
            trigger_type=run_b.trigger_type,
            started_at_utc=run_b.started_at_utc,
            requested_scope_count=run_b.requested_scope_count,
            terminal_status="FAILED",
            finished_at_utc=_AS_OF + timedelta(days=1),
            observed_scope_count=999,
            published_map_count=999,
            lifecycle_event_count=999,
            failed_scope_count=999,
            failure_reason_code="SHOULD_NOT_PERSIST",
            failure_detail="SHOULD_NOT_PERSIST",
        )
        with pytest.raises(NativeShortRunTerminalizationConflictError):
            _finalize_run(schema_conn, run_b_id, conflicting)
        schema_conn.commit()

        with schema_conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM native_short_materializer_run_v1 WHERE run_id = %s",
                (run_b_id,),
            )
            row = cur.fetchone()
            assert row["terminal_status"] == "FINISHED"
            assert row["failure_reason_code"] is None
            assert row["failure_detail"] is None
            assert row["finished_at_utc"] != conflicting.finished_at_utc
    finally:
        if schema_conn is not None:
            schema_conn.close()
        cleanup_conn = _connect(config, database=admin_database)
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()


# --- test isolation regression coverage -------------------------------------


def test_missing_test_mariadb_config_skips_before_any_connection_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With RUN_MARIADB_DDL_TEST=1 but no explicit SYNTH_TEST_MARIADB_*
    variables at all, the config gate must skip before ever constructing a
    connection: pymysql.connect must never be called."""
    monkeypatch.setenv("RUN_MARIADB_DDL_TEST", "1")
    for name in _REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SYNTH_TEST_MARIADB_DISPOSABLE", raising=False)

    def _forbidden_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "pymysql.connect must not be called when explicit test MariaDB config is absent"
        )

    monkeypatch.setattr(pymysql, "connect", _forbidden_connect)

    with pytest.raises(pytest.skip.Exception):
        _require_test_mariadb_config()


def test_partial_test_mariadb_config_skips_before_any_connection_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partially supplied configuration (e.g. host present but password
    missing) must still skip rather than attempt to connect with an
    incomplete/implicit value."""
    monkeypatch.setenv("RUN_MARIADB_DDL_TEST", "1")
    monkeypatch.setenv("SYNTH_TEST_MARIADB_HOST", "127.0.0.1")
    monkeypatch.setenv("SYNTH_TEST_MARIADB_PORT", "3306")
    monkeypatch.setenv("SYNTH_TEST_MARIADB_USER", "root")
    monkeypatch.delenv("SYNTH_TEST_MARIADB_PASSWORD", raising=False)
    monkeypatch.delenv("SYNTH_TEST_MARIADB_ADMIN_DATABASE", raising=False)

    def _forbidden_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("pymysql.connect must not be called with a partial test MariaDB config")

    monkeypatch.setattr(pymysql, "connect", _forbidden_connect)

    with pytest.raises(pytest.skip.Exception):
        _require_test_mariadb_config()


def test_missing_disposable_flag_skips_before_any_connection_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with a fully populated connection configuration, the disposable
    flag gate must skip before a connection is opened unless it is exactly
    "1"."""
    monkeypatch.setenv("SYNTH_TEST_MARIADB_DISPOSABLE", "0")

    def _forbidden_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "pymysql.connect must not be called when SYNTH_TEST_MARIADB_DISPOSABLE != '1'"
        )

    monkeypatch.setattr(pymysql, "connect", _forbidden_connect)

    with pytest.raises(pytest.skip.Exception):
        _require_disposable_flag()


def test_integration_test_module_never_imports_project_db_config() -> None:
    """This file must connect only through explicit SYNTH_TEST_MARIADB_*
    variables: it must never import src.common.db (which loads .env and
    falls back to configured Synth DB defaults) or dotenv directly."""
    source = Path("tests/test_native_short_scope_status_materializer_mariadb_v1.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_prefixes = ("src.common.db", "dotenv")
    for module_name in imported_modules:
        for forbidden in forbidden_prefixes:
            assert not module_name.startswith(forbidden), (
                f"forbidden import found: {module_name} (matches {forbidden})"
            )
