from __future__ import annotations

import ast
import io
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.reporting import native_short_map_ledger_health_report_v1 as report_mod
from src.reporting import run_native_short_map_ledger_health_report_v1 as runner
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey

KEY = NativeShortMapScopeKey(venue="bitvavo", symbol="BTC")
T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
T3 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

# A deliberately ancient map-geometry vintage timestamp. Used to prove that
# immutable map publication timestamps no longer drive health freshness: a
# ten-year-old current_map_published_at_utc must not, by itself, make a
# CURRENT_EVALUATION projection row NEEDS_REVIEW.
ANCIENT_MAP_PUBLISHED_AT = datetime(2016, 1, 1, tzinfo=UTC)


def _scope_row(
    *,
    scope_id: int = 501,
    state: str = "SUPPORTED",
    reason_code: str | None = None,
    reason_detail: str | None = None,
) -> dict[str, Any]:
    return {
        "scope_id": scope_id,
        "venue": KEY.venue,
        "symbol": KEY.symbol,
        "quote_currency": KEY.quote_currency,
        "fib_trading_horizon": KEY.fib_trading_horizon,
        "primary_interval": KEY.primary_interval,
        "supporting_interval": KEY.supporting_interval,
        "scope_support_state": state,
        "scope_reason_code": reason_code,
        "scope_reason_detail": reason_detail,
    }


def _status_row(
    *,
    scope_status_code: str = "CURRENT_EVALUATION",
    scope_status_reason_code: str | None = None,
    map_lifecycle_state: str = "MAP_ACTIVE",
    observation_freshness_state: str = "OBSERVATION_CURRENT",
    source_freshness_state: str | None = "SOURCE_CURRENT",
    actionability_state: str = "ACTIONABLE_ACTIVE_MAP",
    current_map_id: int | None = 9001,
    current_map_cycle_id: str | None = "cycle-1",
    current_map_published_at_utc: datetime | None = ANCIENT_MAP_PUBLISHED_AT,
    current_map_structure_hash: str | None = "hash-a",
    latest_generation_event_id: int | None = 1,
    latest_lifecycle_event_id: int | None = 1,
    latest_observation_id: int | None = 42,
    latest_run_id: int | None = 7,
    latest_observed_at_utc: datetime | None = T3,
    next_expected_evaluation_at_utc: datetime | None = T3 + timedelta(hours=1),
    observation_overdue_after_utc: datetime | None = T3 + timedelta(hours=2),
    primary_latest_candle_ts_utc: datetime | None = T3,
    supporting_latest_candle_ts_utc: datetime | None = T3,
    primary_source_freshness_limit_seconds: int | None = 12 * 3600,
    supporting_source_freshness_limit_seconds: int | None = 3 * 3600,
    cadence_contract_version: str | None = "v1",
    projection_as_of_utc: datetime = T3,
    rebuilt_at_utc: datetime = T3,
    status_payload_json: str | None = None,
) -> dict[str, Any]:
    return {
        "scope_status_id": 1,
        "venue": KEY.venue,
        "symbol": KEY.symbol,
        "quote_currency": KEY.quote_currency,
        "fib_trading_horizon": KEY.fib_trading_horizon,
        "primary_interval": KEY.primary_interval,
        "supporting_interval": KEY.supporting_interval,
        "scope_support_state": "SUPPORTED",
        "scope_status_code": scope_status_code,
        "scope_status_reason_code": scope_status_reason_code,
        "map_lifecycle_state": map_lifecycle_state,
        "observation_freshness_state": observation_freshness_state,
        "source_freshness_state": source_freshness_state,
        "actionability_state": actionability_state,
        "current_map_id": current_map_id,
        "current_map_cycle_id": current_map_cycle_id,
        "current_map_published_at_utc": current_map_published_at_utc,
        "current_map_structure_hash": current_map_structure_hash,
        "latest_generation_event_id": latest_generation_event_id,
        "latest_lifecycle_event_id": latest_lifecycle_event_id,
        "latest_observation_id": latest_observation_id,
        "latest_run_id": latest_run_id,
        "latest_observed_at_utc": latest_observed_at_utc,
        "next_expected_evaluation_at_utc": next_expected_evaluation_at_utc,
        "observation_overdue_after_utc": observation_overdue_after_utc,
        "primary_latest_candle_ts_utc": primary_latest_candle_ts_utc,
        "supporting_latest_candle_ts_utc": supporting_latest_candle_ts_utc,
        "primary_source_freshness_limit_seconds": primary_source_freshness_limit_seconds,
        "supporting_source_freshness_limit_seconds": supporting_source_freshness_limit_seconds,
        "cadence_contract_version": cadence_contract_version,
        "projection_as_of_utc": projection_as_of_utc,
        "status_payload_json": status_payload_json,
        "rebuilt_at_utc": rebuilt_at_utc,
    }


def _configuration_unavailable_row(**overrides: Any) -> dict[str, Any]:
    base = _status_row(
        scope_status_code="CONFIGURATION_UNAVAILABLE",
        scope_status_reason_code="NO_ELIGIBLE_CADENCE_CONFIG",
        observation_freshness_state="OBSERVATION_CONFIGURATION_UNAVAILABLE",
        source_freshness_state=None,
        actionability_state="BLOCKED_CONFIGURATION",
        next_expected_evaluation_at_utc=None,
        observation_overdue_after_utc=None,
        primary_source_freshness_limit_seconds=None,
        supporting_source_freshness_limit_seconds=None,
        cadence_contract_version=None,
        status_payload_json='{"reason_code": "NO_ELIGIBLE_CADENCE_CONFIG"}',
    )
    base.update(overrides)
    return base


def _build(
    *,
    scope_rows: list[dict[str, Any]],
    scope_status_row: dict[str, Any] | None,
):
    return report_mod.build_ledger_health_report(
        venue=KEY.venue,
        symbol=KEY.symbol,
        quote_currency=KEY.quote_currency,
        fib_trading_horizon=KEY.fib_trading_horizon,
        primary_interval=KEY.primary_interval,
        supporting_interval=KEY.supporting_interval,
        generated_at_utc=T3,
        scope_rows=scope_rows,
        scope_status_row=scope_status_row,
    )


# ---------------------------------------------------------------------------
# Scope registration states (unchanged: scope-inventory concern, not the
# projection's job per contract)
# ---------------------------------------------------------------------------


def test_missing_scope() -> None:
    report = _build(scope_rows=[], scope_status_row=None)
    assert report.scope_status == report_mod.SCOPE_STATUS_MISSING
    assert report.scope_row_count == 0
    assert report.projection_status == report_mod.PROJECTION_STATUS_NOT_EVALUATED
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert "SCOPE_MISSING" in report.overall_health_reason_codes


def test_not_applicable_scope() -> None:
    report = _build(
        scope_rows=[_scope_row(state="NOT_APPLICABLE", reason_code="ASSET_NOT_ENABLED")],
        scope_status_row=None,
    )
    assert report.scope_status == report_mod.SCOPE_STATUS_NOT_APPLICABLE
    assert report.projection_status == report_mod.PROJECTION_STATUS_NOT_EVALUATED
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NOT_APPLICABLE
    assert report.overall_health_reason_codes == []


def test_duplicate_canonical_scope_same_state_is_ambiguous() -> None:
    report = _build(
        scope_rows=[_scope_row(scope_id=1), _scope_row(scope_id=2)],
        scope_status_row=None,
    )
    assert report.scope_row_count == 2
    assert report.scope_status == report_mod.SCOPE_STATUS_AMBIGUOUS
    assert "SCOPE_AMBIGUOUS" in report.overall_health_reason_codes


def test_duplicate_canonical_scope_conflicting_states() -> None:
    report = _build(
        scope_rows=[
            _scope_row(scope_id=1, state="SUPPORTED"),
            _scope_row(scope_id=2, state="NOT_APPLICABLE"),
        ],
        scope_status_row=None,
    )
    assert report.scope_status == report_mod.SCOPE_STATUS_CONFLICTING
    assert "SCOPE_CONFLICTING" in report.overall_health_reason_codes


# ---------------------------------------------------------------------------
# Required PR A3 projection-consumption scenarios
# ---------------------------------------------------------------------------


def test_current_evaluation_is_healthy() -> None:
    report = _build(scope_rows=[_scope_row()], scope_status_row=_status_row())
    assert report.projection_status == report_mod.PROJECTION_STATUS_FOUND
    assert report.scope_status_code == "CURRENT_EVALUATION"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_HEALTHY
    assert report.overall_health_reason_codes == []


def test_configuration_unavailable_is_distinct_from_source_and_observation_states() -> None:
    report = _build(scope_rows=[_scope_row()], scope_status_row=_configuration_unavailable_row())
    assert report.scope_status_code == "CONFIGURATION_UNAVAILABLE"
    assert report.actionability_state == "BLOCKED_CONFIGURATION"
    assert report.observation_freshness_state == "OBSERVATION_CONFIGURATION_UNAVAILABLE"
    assert report.source_freshness_state is None
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["SCOPE_STATUS_CONFIGURATION_UNAVAILABLE"]
    # Never reported as source-unavailable, source-stale, or observation-overdue.
    assert "SCOPE_STATUS_SOURCE_UNAVAILABLE" not in report.overall_health_reason_codes
    assert "SCOPE_STATUS_SOURCE_STALE" not in report.overall_health_reason_codes
    assert "SCOPE_STATUS_OBSERVATION_OVERDUE" not in report.overall_health_reason_codes
    # Independently known map/lifecycle facts are still retained.
    assert report.current_map_id == 9001
    assert report.map_lifecycle_state == "MAP_ACTIVE"


def test_source_stale() -> None:
    report = _build(
        scope_rows=[_scope_row()],
        scope_status_row=_status_row(
            scope_status_code="SOURCE_STALE",
            source_freshness_state="SOURCE_STALE",
        ),
    )
    assert report.scope_status_code == "SOURCE_STALE"
    assert report.source_freshness_state == "SOURCE_STALE"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["SCOPE_STATUS_SOURCE_STALE"]


def test_source_unavailable() -> None:
    report = _build(
        scope_rows=[_scope_row()],
        scope_status_row=_status_row(
            scope_status_code="SOURCE_UNAVAILABLE",
            source_freshness_state="SOURCE_UNAVAILABLE",
            primary_latest_candle_ts_utc=None,
            supporting_latest_candle_ts_utc=None,
        ),
    )
    assert report.scope_status_code == "SOURCE_UNAVAILABLE"
    assert report.source_freshness_state == "SOURCE_UNAVAILABLE"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["SCOPE_STATUS_SOURCE_UNAVAILABLE"]


def test_observation_overdue() -> None:
    report = _build(
        scope_rows=[_scope_row()],
        scope_status_row=_status_row(
            scope_status_code="OBSERVATION_OVERDUE",
            observation_freshness_state="OBSERVATION_OVERDUE",
        ),
    )
    assert report.scope_status_code == "OBSERVATION_OVERDUE"
    assert report.observation_freshness_state == "OBSERVATION_OVERDUE"
    # Source can still be current even while observation is overdue -- these
    # are stored separately, never conflated.
    assert report.source_freshness_state == "SOURCE_CURRENT"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["SCOPE_STATUS_OBSERVATION_OVERDUE"]


def test_map_invalidated() -> None:
    report = _build(
        scope_rows=[_scope_row()],
        scope_status_row=_status_row(
            scope_status_code="MAP_INVALIDATED",
            map_lifecycle_state="MAP_INVALIDATED",
            actionability_state="TERMINAL_MAP",
        ),
    )
    assert report.scope_status_code == "MAP_INVALIDATED"
    assert report.map_lifecycle_state == "MAP_INVALIDATED"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["SCOPE_STATUS_MAP_INVALIDATED"]


def test_map_completed() -> None:
    report = _build(
        scope_rows=[_scope_row()],
        scope_status_row=_status_row(
            scope_status_code="MAP_COMPLETED",
            map_lifecycle_state="MAP_COMPLETED",
            actionability_state="TERMINAL_MAP",
        ),
    )
    assert report.scope_status_code == "MAP_COMPLETED"
    assert report.map_lifecycle_state == "MAP_COMPLETED"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["SCOPE_STATUS_MAP_COMPLETED"]


def test_missing_projection_row_is_not_fabricated_healthy() -> None:
    """A SUPPORTED scope with no native_short_scope_status_v1 row must be an
    explicit, observable report state -- never defaulted to healthy."""
    report = _build(scope_rows=[_scope_row()], scope_status_row=None)
    assert report.projection_status == report_mod.PROJECTION_STATUS_MISSING
    assert report.scope_status_code is None
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["PROJECTION_ROW_MISSING"]


def test_invalid_projection_row_is_not_fabricated_healthy() -> None:
    """A row that fails contract validation must also never present as
    healthy -- surfaced distinctly from a missing row."""
    bad_row = _status_row()
    bad_row["scope_status_code"] = "NOT_A_REAL_CODE"
    report = _build(scope_rows=[_scope_row()], scope_status_row=bad_row)
    assert report.projection_status == report_mod.PROJECTION_STATUS_INVALID
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert report.overall_health_reason_codes == ["PROJECTION_ROW_INVALID"]


def test_immutable_map_published_at_does_not_drive_health_freshness() -> None:
    """Proof: an ancient current_map_published_at_utc (map geometry vintage)
    must not, by itself, make a CURRENT_EVALUATION projection NEEDS_REVIEW.
    The field is reported for identity/context only."""
    report = _build(
        scope_rows=[_scope_row()],
        scope_status_row=_status_row(current_map_published_at_utc=ANCIENT_MAP_PUBLISHED_AT),
    )
    assert report.current_map_published_at_utc == ANCIENT_MAP_PUBLISHED_AT
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_HEALTHY


def test_report_source_no_longer_reads_map_or_ledger_join_tables() -> None:
    """Static proof that the ad-hoc ledger joins this PR removes are gone.

    Checks for an actual SQL FROM-reference, not incidental prose mentions
    (the module docstring explains the PR A3 correction and legitimately
    names the removed tables in that historical-context sentence)."""
    root = Path(__file__).parent.parent
    src = (root / "src/reporting/native_short_map_ledger_health_report_v1.py").read_text()
    for forbidden_table in (
        "native_short_map_v1",
        "native_short_map_generation_event_v1",
        "native_short_map_lifecycle_event_v1",
        "obs_market_candle",
    ):
        assert f"FROM {forbidden_table}" not in src, f"health report still queries {forbidden_table}"
    assert "FROM native_short_scope_status_v1" in src


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


def test_parse_symbols_is_deterministic_and_deduped() -> None:
    assert runner.parse_symbols("eth,BTC,btc, eth") == ["BTC", "ETH"]


# ---------------------------------------------------------------------------
# Fetch-layer fakes (list-backed, preserve duplicates)
# ---------------------------------------------------------------------------


class _FakeCursor:
    """List-backed fake that preserves duplicate rows and only supports fetchall."""

    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self._rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        normalized = " ".join(sql.split())
        self._conn.executions.append((normalized, params))
        if "FROM native_short_map_scope_v1" in sql:
            venue, symbol, quote_currency, horizon, primary, support = params
            self._rows = [
                dict(row)
                for row in self._conn.scope_rows
                if row["venue"] == venue
                and row["symbol"] == symbol
                and row["quote_currency"] == quote_currency
                and row["fib_trading_horizon"] == horizon
                and row["primary_interval"] == primary
                and row["supporting_interval"] == support
            ]
            return
        if "FROM native_short_scope_status_v1" in sql:
            venue, symbol, quote_currency, horizon, primary, support = params
            self._rows = [
                dict(row)
                for row in self._conn.scope_status_rows
                if row["venue"] == venue
                and row["symbol"] == symbol
                and row["quote_currency"] == quote_currency
                and row["fib_trading_horizon"] == horizon
                and row["primary_interval"] == primary
                and row["supporting_interval"] == support
            ]
            return
        raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _FakeConn:
    def __init__(
        self,
        *,
        scope_rows: list[dict[str, Any]] | None = None,
        scope_status_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.scope_rows = list(scope_rows or [])
        self.scope_status_rows = list(scope_status_rows or [])
        self.executions: list[tuple[str, Any]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


def test_fetch_scope_rows_preserves_duplicates() -> None:
    conn = _FakeConn(scope_rows=[_scope_row(scope_id=1), _scope_row(scope_id=2)])
    rows = report_mod.fetch_scope_rows(conn, KEY)
    assert len(rows) == 2
    assert not any(sql.startswith("INSERT") or sql.startswith("UPDATE") or sql.startswith("DELETE") for sql, _ in conn.executions)


def test_fetch_scope_status_row_returns_none_when_absent() -> None:
    conn = _FakeConn(scope_status_rows=[])
    assert report_mod.fetch_scope_status_row(conn, KEY) is None


def test_fetch_scope_status_row_returns_the_row() -> None:
    conn = _FakeConn(scope_status_rows=[_status_row()])
    row = report_mod.fetch_scope_status_row(conn, KEY)
    assert row is not None
    assert row["scope_status_code"] == "CURRENT_EVALUATION"


def test_generate_report_for_symbol_full_healthy_wiring() -> None:
    conn = _FakeConn(
        scope_rows=[_scope_row()],
        scope_status_rows=[_status_row()],
    )
    report = report_mod.generate_report_for_symbol(
        conn, venue=KEY.venue, symbol=KEY.symbol, generated_at_utc=T3
    )
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_HEALTHY
    assert conn.commit_count == 0
    assert not any(
        sql.startswith("INSERT") or sql.startswith("UPDATE") or sql.startswith("DELETE")
        for sql, _ in conn.executions
    )


def test_generate_report_for_symbol_does_not_query_projection_when_not_applicable() -> None:
    """No scope_status lookup should be attempted for a non-SUPPORTED scope."""
    conn = _FakeConn(
        scope_rows=[_scope_row(state="NOT_APPLICABLE")],
        scope_status_rows=[_status_row()],  # present in DB but must not be read
    )
    report = report_mod.generate_report_for_symbol(
        conn, venue=KEY.venue, symbol=KEY.symbol, generated_at_utc=T3
    )
    assert report.projection_status == report_mod.PROJECTION_STATUS_NOT_EVALUATED
    assert not any("native_short_scope_status_v1" in sql for sql, _ in conn.executions)


# ---------------------------------------------------------------------------
# CLI: STARTED/RESULT/FINISHED, ordering, no writes
# ---------------------------------------------------------------------------


def test_cli_emits_started_result_finished_in_sorted_order(monkeypatch: pytest.MonkeyPatch) -> None:
    btc_conn = _FakeConn(scope_rows=[_scope_row()], scope_status_rows=[_status_row()])
    eth_key_row = _scope_row()
    eth_key_row["symbol"] = "ETH"
    eth_status_row = _status_row()
    eth_status_row["symbol"] = "ETH"
    eth_conn = _FakeConn(scope_rows=[eth_key_row], scope_status_rows=[eth_status_row])

    order = ["BTC", "ETH"]
    conns = {"BTC": btc_conn, "ETH": eth_conn}
    monkeypatch.setattr(runner, "get_connection", lambda: conns[order.pop(0)])

    stdout = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout
    try:
        code = runner.main(["--symbols", "ETH,BTC", "--output", "jsonl"])
    finally:
        sys.stdout = old_stdout

    lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
    events = [__import__("json").loads(line)["event"] for line in lines]
    assert events[0] == "STARTED"
    assert events[-1] == "FINISHED"
    assert events[1:-1] == ["RESULT", "RESULT"]
    symbols_in_order = [__import__("json").loads(line)["symbol"] for line in lines[1:-1]]
    assert symbols_in_order == ["BTC", "ETH"]
    assert code == 0


def test_cli_never_writes_and_always_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(scope_rows=[_scope_row()], scope_status_rows=[_status_row()])
    monkeypatch.setattr(runner, "get_connection", lambda: conn)

    stdout = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout
    try:
        runner.main(["--symbols", "BTC", "--output", "summary"])
    finally:
        sys.stdout = old_stdout

    assert conn.rollback_count == 1
    assert conn.commit_count == 0
    assert conn.close_count == 1
    assert not any(
        sql.startswith("INSERT") or sql.startswith("UPDATE") or sql.startswith("DELETE")
        for sql, _ in conn.executions
    )


# ---------------------------------------------------------------------------
# Static safety checks
# ---------------------------------------------------------------------------

# This lane now lives in src/reporting itself, so bare "src.reporting" cannot
# be forbidden outright (the runner legitimately imports its sibling core
# module). Same-lane imports are checked precisely in
# test_reporting_imports_are_limited_to_this_lane instead.
FORBIDDEN_IMPORT_PREFIXES = (
    "src.account",
    "src.account_provisioning",
    "src.broker",
    "src.decision_gate",
    "src.execution",
    "src.execution_planner",
    "src.executor",
    "src.portfolio",
    "src.selection",
    "src.research",
    "src.breathline",
    "src.aplus",
    "src.market_data.native_short_map_materializer_v1",
    "src.market_data.run_native_short_map_materializer_v1",
    "src.market_data.run_native_short_map_scope_seed_canary_v1",
    "src.market_data.native_short_fib_context_v1",
    "src.market_data.run_native_short_fib_context_v1",
    "src.market_data.native_short_scope_status_materializer_v1",
    "src.market_data.native_short_scope_status_projection_v1",
)

# The only market_data dependencies this lane may take: shared, DB-free
# contract modules (dataclasses/enums, no I/O). Neither is a market-data
# producer/acquisition module.
ALLOWED_MARKET_DATA_IMPORTS = {
    "src.market_data.native_short_map_lifecycle_v1",
    "src.market_data.native_short_scope_status_v1",
}

THIS_LANE_MODULES = {
    "src.reporting.native_short_map_ledger_health_report_v1",
    "src.reporting.run_native_short_map_ledger_health_report_v1",
}

MODULE_PATHS = [
    "src/reporting/native_short_map_ledger_health_report_v1.py",
    "src/reporting/run_native_short_map_ledger_health_report_v1.py",
]


def test_lifecycle_contract_module_has_no_db_access() -> None:
    """The one shared market_data dependency must stay a pure, DB-free contract."""
    root = Path(__file__).parent.parent
    src = (root / "src/market_data/native_short_map_lifecycle_v1.py").read_text()
    for token in ("cur.execute", "pymysql", "get_connection", "INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert token not in src


def test_scope_status_contract_module_has_no_db_access() -> None:
    """The projection contract module this PR newly depends on must also stay
    a pure, DB-free validation-only type module."""
    root = Path(__file__).parent.parent
    src = (root / "src/market_data/native_short_scope_status_v1.py").read_text()
    for token in ("cur.execute", "pymysql", "get_connection", "INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert token not in src


def test_no_market_data_producer_imports_this_reporting_lane() -> None:
    """Reverse-direction check: no market_data producer may import this lane."""
    root = Path(__file__).parent.parent
    producer_paths = [
        "src/market_data/native_short_map_materializer_v1.py",
        "src/market_data/run_native_short_map_materializer_v1.py",
        "src/market_data/run_native_short_map_scope_seed_canary_v1.py",
        "src/market_data/native_short_fib_context_v1.py",
        "src/market_data/native_short_map_lifecycle_v1.py",
        "src/market_data/native_short_scope_status_v1.py",
        "src/market_data/native_short_scope_status_projection_v1.py",
        "src/market_data/native_short_scope_status_materializer_v1.py",
    ]
    for rel_path in producer_paths:
        path = root / rel_path
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.startswith("src.reporting"), (
                    f"{rel_path} (market_data producer) imports src.reporting module {name}"
                )


def test_no_report_lane_files_remain_under_market_data() -> None:
    root = Path(__file__).parent.parent
    assert not (root / "src/market_data/native_short_map_ledger_health_report_v1.py").exists()
    assert not (root / "src/market_data/run_native_short_map_ledger_health_report_v1.py").exists()


@pytest.mark.parametrize("rel_path", MODULE_PATHS)
def test_no_write_sql_in_module_source(rel_path: str) -> None:
    root = Path(__file__).parent.parent
    src = (root / rel_path).read_text()
    for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", " DDL", "CREATE TABLE", "DROP TABLE"):
        assert token not in src, f"{rel_path} contains forbidden write token {token!r}"


@pytest.mark.parametrize("rel_path", MODULE_PATHS)
def test_no_forbidden_direct_imports(rel_path: str) -> None:
    root = Path(__file__).parent.parent
    tree = ast.parse((root / rel_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            for forbidden in FORBIDDEN_IMPORT_PREFIXES:
                assert not name.startswith(forbidden), f"{rel_path} imports {name}"


@pytest.mark.parametrize("rel_path", MODULE_PATHS)
def test_reporting_imports_are_limited_to_this_lane(rel_path: str) -> None:
    """Only this lane's own two modules may be imported under src.reporting."""
    root = Path(__file__).parent.parent
    tree = ast.parse((root / rel_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            if name.startswith("src.reporting"):
                assert name in THIS_LANE_MODULES, (
                    f"{rel_path} imports unrelated reporting module {name}"
                )


@pytest.mark.parametrize("rel_path", MODULE_PATHS)
def test_market_data_dependency_is_limited_to_pure_contract_modules(rel_path: str) -> None:
    """Only the two shared, DB-free contract modules may be imported from
    src.market_data -- never a materializer, canary, runner, or projection
    rebuild module."""
    root = Path(__file__).parent.parent
    tree = ast.parse((root / rel_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            if name.startswith("src.market_data"):
                assert name in ALLOWED_MARKET_DATA_IMPORTS, (
                    f"{rel_path} imports disallowed market_data module {name}"
                )


def _local_module_path(root: Path, module: str) -> Path | None:
    if not module.startswith("src."):
        return None
    rel_parts = module.split(".")
    module_path = root / Path(*rel_parts).with_suffix(".py")
    if module_path.exists():
        return module_path
    package_path = root / Path(*rel_parts) / "__init__.py"
    if package_path.exists():
        return package_path
    return None


def _src_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("src."))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("src."):
                imports.add(module)
    return imports


def test_reachable_import_graph_excludes_forbidden_layers() -> None:
    root = Path(__file__).parent.parent
    start_paths = [root / rel_path for rel_path in MODULE_PATHS]
    seen_paths: set[Path] = set()
    stack = start_paths[:]
    reachable_modules: set[str] = set()
    while stack:
        path = stack.pop()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        for module in _src_imports(path):
            reachable_modules.add(module)
            for forbidden in FORBIDDEN_IMPORT_PREFIXES:
                assert not module.startswith(forbidden), f"{path} reaches forbidden import {module}"
            module_path = _local_module_path(root, module)
            if module_path is not None:
                stack.append(module_path)

    assert not any("breathline" in module.lower() for module in reachable_modules)
    assert not any("aplus" in module.lower() for module in reachable_modules)
    assert "materialize_scope_symbol" not in (root / MODULE_PATHS[0]).read_text()
    assert "materialize_scope_symbol" not in (root / MODULE_PATHS[1]).read_text()
