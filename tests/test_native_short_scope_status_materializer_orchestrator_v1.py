from __future__ import annotations

"""Orchestrator-level tests for native_short_scope_status_materializer_v1.

These tests exercise `evaluate_scope` / `run_native_short_scope_status_materializer`
against a small hand-rolled in-memory fake connection (the same style already
used by tests/test_native_short_map_materializer_v1.py), verifying the DB
*wiring* contract: one run row, terminal-once, one observation per scope,
config-unavailable end-to-end, unsupported/unknown skip, no duplicate map on
unchanged geometry, lifecycle-transition-once, and that projection rebuild
never writes to a source ledger.

`materialize_scope_symbol` itself is injected as a stub returning canned
`ScopeMaterializationResult` objects: its own correctness is already covered
by the existing 1272-line tests/test_native_short_map_materializer_v1.py
suite, so these tests focus only on this module's own new orchestration
logic, not on re-verifying the existing geometry materializer's internals.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.market_data.native_short_fib_context_v1 import (
    PRIMARY_LIFECYCLE_INVALIDATED,
    STATUS_AVAILABLE,
    STATUS_SYMBOL_MISSING,
    NativeShortContextRow,
)
from src.market_data.native_short_map_lifecycle_v1 import (
    NativeShortMapLifecycleEvent,
    NativeShortMapLifecycleEventType,
    NativeShortMapRecord,
    NativeShortMapScopeKey,
)
from src.market_data.native_short_map_materializer_v1 import (
    REASON_STRUCTURE_UNCHANGED,
    ScopeMaterializationResult,
)
from src.market_data.native_short_scope_status_materializer_v1 import (
    evaluate_scope,
    run_native_short_scope_status_materializer,
)

_AS_OF = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _key(symbol: str = "BTC") -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(venue="bitvavo", symbol=symbol, quote_currency="EUR")


def _context_row(*, lifecycle_state: str = "TARGET_ACTIVE", map_cycle_id: str = "cyc1") -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol="BTC",
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=STATUS_AVAILABLE,
        map_cycle_id=map_cycle_id,
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
        primary_4h_lifecycle_state=lifecycle_state,
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


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self._last_sql = ""
        self._result: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        stripped = sql.strip()
        self._last_sql = stripped
        params = params or ()

        if "INSERT INTO native_short_materializer_run_v1" in stripped:
            row = dict(
                run_id=len(self._conn.runs) + 1,
                run_uuid=params[0],
                runner_name=params[1],
                runner_version=params[2],
                contract_version=params[3],
                trigger_type=params[4],
                started_at_utc=params[5],
                requested_scope_count=params[6],
                finished_at_utc=None,
                terminal_status=None,
            )
            self._conn.runs.append(row)
            self._conn.last_id = row["run_id"]
            return

        if "UPDATE native_short_materializer_run_v1" in stripped:
            run_id = params[-1]
            run = next(r for r in self._conn.runs if r["run_id"] == run_id)
            if run["terminal_status"] is not None:
                self._conn.finalize_calls_after_terminal += 1
            run["finished_at_utc"] = params[0]
            run["terminal_status"] = params[1]
            run["observed_scope_count"] = params[2]
            run["published_map_count"] = params[3]
            run["lifecycle_event_count"] = params[4]
            run["failed_scope_count"] = params[5]
            run["failure_reason_code"] = params[6]
            run["failure_detail"] = params[7]
            return

        if "INSERT INTO native_short_scope_observation_v1" in stripped:
            columns = (
                "run_id", "run_uuid", "venue", "symbol", "quote_currency", "fib_trading_horizon",
                "primary_interval", "supporting_interval", "observed_at_utc",
                "evaluation_due_at_utc", "cadence_contract_version",
                "observation_status", "observation_reason_code", "observation_detail",
                "source_state", "primary_latest_candle_ts_utc", "supporting_latest_candle_ts_utc",
                "primary_source_freshness_limit_seconds", "supporting_source_freshness_limit_seconds",
                "context_status", "current_map_id_before", "current_map_id_after",
                "published_map_id", "generation_attempt_id", "generation_event_id", "lifecycle_event_id",
                "lifecycle_state_before", "lifecycle_state_after", "geometry_action", "structure_hash",
                "source_primary_candle_count", "source_support_candle_count",
            )
            row = dict(zip(columns, params))
            row["scope_observation_id"] = len(self._conn.observations) + 1
            self._conn.observations.append(row)
            self._conn.last_id = row["scope_observation_id"]
            return

        if "FROM native_short_scope_observation_v1" in stripped:
            venue, symbol, quote, horizon, primary, supporting = params
            self._result = sorted(
                (
                    row
                    for row in self._conn.observations
                    if (row["venue"], row["symbol"], row["quote_currency"], row["fib_trading_horizon"],
                        row["primary_interval"], row["supporting_interval"])
                    == (venue, symbol, quote, horizon, primary, supporting)
                ),
                key=lambda row: (row["observed_at_utc"], row["scope_observation_id"]),
            )
            return

        if "FROM native_short_scope_support_event_v1" in stripped:
            venue, symbol, quote, horizon, primary, supporting = params
            self._result = sorted(
                (
                    row
                    for row in self._conn.support_events
                    if (row["venue"], row["symbol"], row["quote_currency"], row["fib_trading_horizon"],
                        row["primary_interval"], row["supporting_interval"])
                    == (venue, symbol, quote, horizon, primary, supporting)
                ),
                key=lambda row: (row["event_ts_utc"], row["scope_support_event_id"]),
            )
            return

        if "FROM native_short_scope_cadence_config_v1" in stripped:
            venue, symbol, quote, horizon, primary, supporting = params
            self._result = [
                row
                for row in self._conn.cadence_configs
                if (row["venue"], row["symbol"], row["quote_currency"], row["fib_trading_horizon"],
                    row["primary_interval"], row["supporting_interval"])
                == (venue, symbol, quote, horizon, primary, supporting)
            ]
            return

        if "INSERT INTO native_short_scope_status_v1" in stripped:
            key_tuple = tuple(params[0:6])
            columns = (
                "venue", "symbol", "quote_currency", "fib_trading_horizon", "primary_interval", "supporting_interval",
                "scope_support_state", "scope_status_code", "scope_status_reason_code",
                "map_lifecycle_state", "observation_freshness_state", "source_freshness_state", "actionability_state",
                "current_map_id", "current_map_cycle_id", "current_map_published_at_utc", "current_map_structure_hash",
                "latest_generation_event_id", "latest_lifecycle_event_id",
                "latest_observation_id", "latest_run_id", "latest_observed_at_utc",
                "next_expected_evaluation_at_utc", "observation_overdue_after_utc",
                "primary_latest_candle_ts_utc", "supporting_latest_candle_ts_utc",
                "primary_source_freshness_limit_seconds", "supporting_source_freshness_limit_seconds",
                "cadence_contract_version", "projection_as_of_utc", "status_payload_json",
            )
            self._conn.status_rows[key_tuple] = dict(zip(columns, params))
            self._conn.status_upsert_count += 1
            return

        if "INSERT INTO native_short_map_lifecycle_event_v1" in stripped:
            row = dict(
                lifecycle_event_id=len(self._conn.lifecycle_events) + 1,
                map_id=params[0],
                lifecycle_event_type=params[1],
                event_ts_utc=params[2],
            )
            self._conn.lifecycle_events.append(row)
            self._conn.last_id = row["lifecycle_event_id"]
            return

        raise AssertionError(f"FakeCursor received unsupported SQL: {stripped[:120]}")

    def fetchall(self) -> list[dict[str, Any]]:
        return self._result

    @property
    def lastrowid(self) -> int:
        return self._conn.last_id

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _FakeConn:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.support_events: list[dict[str, Any]] = []
        self.cadence_configs: list[dict[str, Any]] = []
        self.status_rows: dict[tuple, dict[str, Any]] = {}
        self.lifecycle_events: list[dict[str, Any]] = []
        self.last_id = 0
        self.status_upsert_count = 0
        self.finalize_calls_after_terminal = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def seed_support_event(self, key: NativeShortMapScopeKey, *, state: str, event_ts_utc: datetime) -> None:
        self.support_events.append(
            dict(
                scope_support_event_id=len(self.support_events) + 1,
                venue=key.venue,
                symbol=key.symbol,
                quote_currency=key.quote_currency,
                fib_trading_horizon=key.fib_trading_horizon,
                primary_interval=key.primary_interval,
                supporting_interval=key.supporting_interval,
                scope_support_state=state,
                event_ts_utc=event_ts_utc,
            )
        )

    def seed_cadence_config(self, key: NativeShortMapScopeKey, **overrides: Any) -> None:
        row = dict(
            venue=key.venue,
            symbol=key.symbol,
            quote_currency=key.quote_currency,
            fib_trading_horizon=key.fib_trading_horizon,
            primary_interval=key.primary_interval,
            supporting_interval=key.supporting_interval,
            cadence_contract_version="v1",
            target_evaluation_interval="1h",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            evaluation_grace_seconds=900,
            recent_scope_grace_seconds=3600,
            effective_from_utc=_AS_OF - timedelta(days=60),
            effective_to_utc=None,
        )
        row.update(overrides)
        self.cadence_configs.append(row)


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


def _fixed_clock(ts: datetime):
    return lambda: ts


def _sequential_clock(*timestamps: datetime):
    """Returns a distinct timestamp on each call, in order; raises if called
    more times than timestamps were supplied. Used to prove started_at_utc
    and finished_at_utc are independent operational reads, not the same
    wall-clock instant, and that finished_at_utc >= started_at_utc."""
    remaining = list(timestamps)

    def _next() -> datetime:
        if not remaining:
            raise AssertionError("operational clock called more times than expected")
        return remaining.pop(0)

    return _next


def _unchanged_geometry_result(*, map_id: int = 1) -> ScopeMaterializationResult:
    return ScopeMaterializationResult(
        symbol="BTC",
        attempted=True,
        status="skipped",
        dry_run=False,
        map_id=map_id,
        reason_code=REASON_STRUCTURE_UNCHANGED,
        generation_event_type="PUBLISHED",
    )


# --- one run row per invocation; terminal fields set once ------------------


def test_one_run_row_inserted_and_finalized_once() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
        materialize_scope_symbol_fn=lambda *a, **k: _unchanged_geometry_result(),
    )

    assert len(conn.runs) == 1
    run = conn.runs[0]
    assert run["terminal_status"] == "FINISHED"
    assert run["finished_at_utc"] == _AS_OF
    assert run["requested_scope_count"] == 1
    assert conn.finalize_calls_after_terminal == 0


# --- one observation per supported/evaluable scope/run ----------------------


def test_one_observation_written_per_supported_scope_per_run() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
        materialize_scope_symbol_fn=lambda *a, **k: _unchanged_geometry_result(),
    )

    assert len(conn.observations) == 1
    assert conn.observations[0]["observation_status"] == "EVALUATED"
    assert conn.status_upsert_count == 1


# --- unsupported / unknown-at-as-of: no observation, no projection row -----


def test_not_applicable_scope_writes_no_observation_and_no_status_row() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="NOT_APPLICABLE", event_ts_utc=_AS_OF - timedelta(days=30))

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
    )

    assert conn.observations == []
    assert conn.status_upsert_count == 0
    assert conn.runs[0]["observed_scope_count"] == 0


def test_unknown_at_as_of_scope_writes_no_observation_and_no_status_row() -> None:
    conn = _FakeConn()
    key = _key()
    # No support event at all -> UNKNOWN_AT_AS_OF.

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
    )

    assert conn.observations == []
    assert conn.status_upsert_count == 0


# --- configuration-unavailable path, end to end ------------------------------


def test_configuration_unavailable_scope_writes_blocked_observation_and_status_row() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    # No cadence config seeded at all.

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
    )

    assert len(conn.observations) == 1
    observation = conn.observations[0]
    assert observation["observation_status"] == "SKIPPED_CONFIGURATION_UNAVAILABLE"
    assert observation["observation_reason_code"] == "NO_ELIGIBLE_CADENCE_CONFIG"
    assert observation["cadence_contract_version"] is None

    assert conn.status_upsert_count == 1
    status_row = next(iter(conn.status_rows.values()))
    assert status_row["scope_status_code"] == "CONFIGURATION_UNAVAILABLE"
    assert status_row["scope_status_reason_code"] == "NO_ELIGIBLE_CADENCE_CONFIG"


# --- unchanged geometry: no duplicate map/generation heartbeat --------------


def test_unchanged_geometry_across_two_runs_does_not_duplicate_map(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    call_count = {"n": 0}

    def stub_materialize(*args: Any, **kwargs: Any) -> ScopeMaterializationResult:
        call_count["n"] += 1
        # Every call reports unchanged geometry against the same pre-existing
        # map_id=1: the existing materialize_scope_symbol guarantees this
        # (existing_same_hash short-circuit); this stub asserts the
        # orchestrator never tries to treat repeated "skipped" results as new
        # publications.
        return _unchanged_geometry_result(map_id=1)

    for _ in range(2):
        run_native_short_scope_status_materializer(
            conn,
            scopes=[key],
            as_of_utc=_AS_OF,
            trigger_type="MANUAL",
            operational_clock=_fixed_clock(_AS_OF),
            fetch_context_row=lambda k, t: _context_row(),
            fetch_existing_maps=_no_maps,
            fetch_existing_generation_events=_no_generation_events,
            fetch_existing_lifecycle_events=_no_lifecycle_events,
            fetch_primary_candle_close_timestamps=_fresh_candles,
            fetch_supporting_candle_close_timestamps=_fresh_candles,
            materialize_scope_symbol_fn=stub_materialize,
        )

    assert call_count["n"] == 2
    assert len(conn.observations) == 2
    assert all(row["published_map_id"] is None for row in conn.observations)
    assert all(row["geometry_action"] == "UNCHANGED_GEOMETRY" for row in conn.observations)
    assert conn.runs[0]["published_map_count"] == 0
    assert conn.runs[1]["published_map_count"] == 0


# --- genuine lifecycle transition appended once ------------------------------


def test_genuine_lifecycle_transition_appended_once_across_repeated_runs() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    existing_map = NativeShortMapRecord(
        map_id=1,
        key=key,
        published_at_utc=_AS_OF - timedelta(hours=5),
        structure_hash="hash-1",
        generator_name="native_short_map_materializer_v1",
        generator_version="0.1",
        fib_model_name="native_short_fib_context_v1",
        fib_model_version="0.1",
        published_generation_attempt_id="attempt-1",
        map_cycle_id="cyc1",
    )

    def fetch_maps(conn: Any, k: NativeShortMapScopeKey) -> list[Any]:
        return [existing_map]

    lifecycle_state: dict[str, list[Any]] = {"events": []}

    def fetch_lifecycle(conn: Any, map_ids: list[int]) -> list[Any]:
        return list(lifecycle_state["events"])

    def stub_materialize(*args: Any, **kwargs: Any) -> ScopeMaterializationResult:
        return _unchanged_geometry_result(map_id=1)

    invalidated_row = _context_row(lifecycle_state=PRIMARY_LIFECYCLE_INVALIDATED, map_cycle_id="cyc1")

    for _ in range(2):
        run_native_short_scope_status_materializer(
            conn,
            scopes=[key],
            as_of_utc=_AS_OF,
            trigger_type="MANUAL",
            operational_clock=_fixed_clock(_AS_OF),
            fetch_context_row=lambda k, t: invalidated_row,
            fetch_existing_maps=fetch_maps,
            fetch_existing_generation_events=_no_generation_events,
            fetch_existing_lifecycle_events=fetch_lifecycle,
            fetch_primary_candle_close_timestamps=_fresh_candles,
            fetch_supporting_candle_close_timestamps=_fresh_candles,
            materialize_scope_symbol_fn=stub_materialize,
        )
        # Simulate the lifecycle event actually being persisted so the second
        # run sees it as already-recorded (mirrors what a real DB would do).
        if conn.lifecycle_events and not lifecycle_state["events"]:
            lifecycle_state["events"] = [
                NativeShortMapLifecycleEvent(
                    lifecycle_event_id=row["lifecycle_event_id"],
                    map_id=row["map_id"],
                    event_type=NativeShortMapLifecycleEventType(row["lifecycle_event_type"]),
                    event_ts_utc=row["event_ts_utc"],
                )
                for row in conn.lifecycle_events
            ]

    assert len(conn.lifecycle_events) == 1
    assert conn.lifecycle_events[0]["lifecycle_event_type"] == "INVALIDATED"
    assert conn.runs[0]["lifecycle_event_count"] == 1
    assert conn.runs[1]["lifecycle_event_count"] == 0
    assert conn.observations[0]["lifecycle_event_id"] == conn.lifecycle_events[0]["lifecycle_event_id"]
    assert conn.observations[1]["lifecycle_event_id"] is None


# --- projection rebuild writes only the projection table --------------------


def test_projection_upsert_writes_only_status_table_not_source_ledgers() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
        materialize_scope_symbol_fn=lambda *a, **k: _unchanged_geometry_result(),
    )

    # Only one status upsert; support-event/cadence-config source tables are
    # read-only across this run (never appended to).
    assert conn.status_upsert_count == 1
    assert len(conn.support_events) == 1
    assert len(conn.cadence_configs) == 1


# --- source-unavailable path: candles totally missing ------------------------


def test_source_unavailable_when_context_symbol_missing() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    def missing_context_row(k: NativeShortMapScopeKey, as_of: datetime) -> NativeShortContextRow:
        row = _context_row()
        return NativeShortContextRow(**{**row.__dict__, "context_status": STATUS_SYMBOL_MISSING})

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=missing_context_row,
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_no_candles,
        fetch_supporting_candle_close_timestamps=_no_candles,
    )

    assert len(conn.observations) == 1
    observation = conn.observations[0]
    assert observation["observation_status"] == "SKIPPED_SOURCE_UNAVAILABLE"
    assert observation["source_state"] == "SOURCE_UNAVAILABLE"


# --- failure terminalization: run must never be left non-terminal ----------


def test_failure_before_materialization_terminalizes_run_as_failed() -> None:
    """fetch_context_row raises before materialize_scope_symbol_fn is ever
    reached (the "context/candle callback before materialization" case)."""
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    op_start = _AS_OF + timedelta(days=3)
    op_finish = _AS_OF + timedelta(days=3, minutes=5)

    def raising_context_row(k: NativeShortMapScopeKey, as_of: datetime) -> NativeShortContextRow:
        raise RuntimeError("candle fetch exploded before materialization")

    with pytest.raises(RuntimeError, match="candle fetch exploded before materialization"):
        run_native_short_scope_status_materializer(
            conn,
            scopes=[key],
            as_of_utc=_AS_OF,
            trigger_type="MANUAL",
            operational_clock=_sequential_clock(op_start, op_finish),
            fetch_context_row=raising_context_row,
            fetch_existing_maps=_no_maps,
            fetch_existing_generation_events=_no_generation_events,
            fetch_existing_lifecycle_events=_no_lifecycle_events,
            fetch_primary_candle_close_timestamps=_fresh_candles,
            fetch_supporting_candle_close_timestamps=_fresh_candles,
        )

    assert len(conn.runs) == 1
    run = conn.runs[0]
    assert run["terminal_status"] == "FAILED"
    assert run["failure_reason_code"] == "RuntimeError"
    assert "candle fetch exploded before materialization" in run["failure_detail"]
    # No scope could be evaluated to completion before the raise.
    assert run["observed_scope_count"] == 0
    assert conn.observations == []
    assert conn.status_upsert_count == 0
    # Terminal timestamps come from the operational clock, not as_of_utc.
    assert run["started_at_utc"] == op_start
    assert run["finished_at_utc"] == op_finish
    assert run["finished_at_utc"] >= run["started_at_utc"]
    # Exactly one terminal UPDATE: no second terminalization occurred.
    assert conn.finalize_calls_after_terminal == 0


def test_failure_in_projection_rebuild_after_scope_outcome_terminalizes_as_failed() -> None:
    """A failure in the candle-timestamp fetch feeding projection rebuild,
    occurring only for the second of two scopes, after both scopes'
    evaluate_scope outcomes (including the first scope's full projection
    upsert) already completed."""
    conn = _FakeConn()
    btc = _key("BTC")
    eth = _key("ETH")
    for key in (btc, eth):
        conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
        conn.seed_cadence_config(key)

    op_start = _AS_OF + timedelta(hours=6)
    op_finish = _AS_OF + timedelta(hours=6, minutes=2)

    def candles_raising_for_eth(key: NativeShortMapScopeKey, as_of_utc: datetime) -> list[datetime]:
        if key.symbol == "ETH":
            raise RuntimeError("candle timestamp fetch exploded during projection rebuild")
        return [as_of_utc - timedelta(hours=1)]

    with pytest.raises(RuntimeError, match="candle timestamp fetch exploded during projection rebuild"):
        run_native_short_scope_status_materializer(
            conn,
            scopes=[btc, eth],
            as_of_utc=_AS_OF,
            trigger_type="MANUAL",
            operational_clock=_sequential_clock(op_start, op_finish),
            fetch_context_row=lambda k, t: _context_row(),
            fetch_existing_maps=_no_maps,
            fetch_existing_generation_events=_no_generation_events,
            fetch_existing_lifecycle_events=_no_lifecycle_events,
            fetch_primary_candle_close_timestamps=candles_raising_for_eth,
            fetch_supporting_candle_close_timestamps=_fresh_candles,
            materialize_scope_symbol_fn=lambda *a, **k: _unchanged_geometry_result(),
        )

    assert len(conn.runs) == 1
    run = conn.runs[0]
    assert run["terminal_status"] == "FAILED"
    assert run["failure_reason_code"] == "RuntimeError"
    # Both scopes' evaluate_scope outcomes were recorded before the raise;
    # counters accumulated before failure must be preserved, not reset.
    assert run["observed_scope_count"] == 2
    assert len(conn.observations) == 2
    # Only BTC's projection rebuild completed before ETH's candle fetch raised.
    assert conn.status_upsert_count == 1
    assert run["started_at_utc"] == op_start
    assert run["finished_at_utc"] == op_finish
    assert conn.finalize_calls_after_terminal == 0


def test_success_path_still_terminalizes_exactly_once_with_finished() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_fixed_clock(_AS_OF),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
        materialize_scope_symbol_fn=lambda *a, **k: _unchanged_geometry_result(),
    )

    assert len(conn.runs) == 1
    assert conn.runs[0]["terminal_status"] == "FINISHED"
    assert conn.finalize_calls_after_terminal == 0


# --- semantic time (as_of_utc) vs operational timestamps --------------------


def test_projection_as_of_utc_is_independent_of_operational_clock() -> None:
    conn = _FakeConn()
    key = _key()
    conn.seed_support_event(key, state="SUPPORTED", event_ts_utc=_AS_OF - timedelta(days=30))
    conn.seed_cadence_config(key)

    op_start = _AS_OF + timedelta(days=3)
    op_finish = _AS_OF + timedelta(days=3, minutes=5)

    run_native_short_scope_status_materializer(
        conn,
        scopes=[key],
        as_of_utc=_AS_OF,
        trigger_type="MANUAL",
        operational_clock=_sequential_clock(op_start, op_finish),
        fetch_context_row=lambda k, t: _context_row(),
        fetch_existing_maps=_no_maps,
        fetch_existing_generation_events=_no_generation_events,
        fetch_existing_lifecycle_events=_no_lifecycle_events,
        fetch_primary_candle_close_timestamps=_fresh_candles,
        fetch_supporting_candle_close_timestamps=_fresh_candles,
        materialize_scope_symbol_fn=lambda *a, **k: _unchanged_geometry_result(),
    )

    # The semantic cutoff written into the projection is exactly the supplied
    # as_of_utc, wholly unaffected by the operational clock.
    status_row = next(iter(conn.status_rows.values()))
    assert status_row["projection_as_of_utc"] == _AS_OF

    # The run's own operational timestamps come from operational_clock, not
    # as_of_utc, and the terminal timestamp is not earlier than the start.
    run = conn.runs[0]
    assert run["started_at_utc"] == op_start
    assert run["finished_at_utc"] == op_finish
    assert run["started_at_utc"] != _AS_OF
    assert run["finished_at_utc"] != _AS_OF
    assert run["finished_at_utc"] >= run["started_at_utc"]
    assert run["finished_at_utc"] != run["started_at_utc"]
