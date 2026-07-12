from __future__ import annotations

import ast
import importlib
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.market_data.native_short_fib_context_v1 import (
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT_4H,
    STATUS_INSUFFICIENT_1H,
    STATUS_STALE_OR_INVALID,
    STATUS_SYMBOL_MISSING,
    NativeShortContextRow,
)
from src.market_data.native_short_map_lifecycle_v1 import (
    DATA_UNAVAILABLE_REASON_CODES,
    NativeShortMapGenerationEvent,
    NativeShortMapGenerationEventType,
    NativeShortMapLifecycleEvent,
    NativeShortMapLifecycleEventType,
    NativeShortMapRecord,
    NativeShortMapScopeKey,
    NativeShortMapScopeSupport,
    NativeShortMapScopeSupportState,
)
from src.market_data.native_short_map_materializer_v1 import (
    FIB_MODEL_NAME,
    FIB_MODEL_VERSION,
    GENERATOR_NAME,
    GENERATOR_VERSION,
    REASON_PRIOR_REJECTION_UNCHANGED,
    REASON_STRUCTURE_UNCHANGED,
    compute_structure_hash,
    context_status_to_rejection_reason,
    materialize_scope_symbol,
)
from src.market_data.run_native_short_map_materializer_v1 import parse_args, parse_symbols
from src.market_data import native_short_map_materializer_v1 as materializer
from src.market_data import run_native_short_map_materializer_v1 as runner

_NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=UTC)
_LOW_TS = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)
_HIGH_TS = datetime(2026, 6, 28, 16, 0, 0, tzinfo=UTC)


def _scope(symbol: str = "BTC") -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(
        venue="bitvavo",
        symbol=symbol,
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def _supported(symbol: str = "BTC") -> NativeShortMapScopeSupport:
    return NativeShortMapScopeSupport(
        key=_scope(symbol),
        support_state=NativeShortMapScopeSupportState.SUPPORTED,
    )


def _available_row(symbol: str = "BTC", *, high_price: Decimal = Decimal("0.120")) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol,
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=STATUS_AVAILABLE,
        map_cycle_id=f"{symbol}|SHORT|4h|{_LOW_TS.isoformat()}|{_HIGH_TS.isoformat()}",
        anchor_start_ts_utc=_LOW_TS,
        anchor_end_ts_utc=_HIGH_TS,
        anchor_low_price=Decimal("0.080"),
        anchor_high_price=high_price,
        breakout_gate_price=Decimal("0.118"),
        latest_primary_close_ts_utc=_NOW - timedelta(hours=1),
        latest_support_close_ts_utc=_NOW - timedelta(hours=1),
        latest_primary_close_price=Decimal("0.115"),
        ext_1_272_price=Decimal("0.153"),
        ext_1_618_price=Decimal("0.185"),
        ext_2_000_price=Decimal("0.200"),
        active_target_levels=(Decimal("0.153"), Decimal("0.185")),
        previous_target_levels=(),
        reload_r382_price=Decimal("0.104"),
        reload_r500_price=Decimal("0.100"),
        reload_r618_price=Decimal("0.095"),
        reload_r786_price=Decimal("0.089"),
        invalidation_price=Decimal("0.080"),
        primary_4h_lifecycle_state="TARGET_ACTIVE",
        supporting_1h_state="ALIGNED_WITH_4H",
        context_freshness_status="FRESH",
        max_primary_high_since_anchor=Decimal("0.118"),
        min_primary_low_since_anchor=Decimal("0.082"),
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


def _unavailable_row(symbol: str = "BTC", status: str = STATUS_INSUFFICIENT_4H) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol,
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=status,
        map_cycle_id="",
        anchor_start_ts_utc=None,
        anchor_end_ts_utc=None,
        anchor_low_price=None,
        anchor_high_price=None,
        breakout_gate_price=None,
        latest_primary_close_ts_utc=None,
        latest_support_close_ts_utc=None,
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
        primary_4h_lifecycle_state="UNKNOWN",
        supporting_1h_state="UNKNOWN",
        context_freshness_status="FRESH",
        max_primary_high_since_anchor=None,
        min_primary_low_since_anchor=None,
        source_name="native_short_fib_context_v1",
        source_version="0.1",
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
        current_map_status="NO_VALID_MAP",
        previous_map_cycle_id="",
        previous_map_lifecycle_state="",
        rollover_state="NO_VALID_MAP",
        selection_reason="",
        source_primary_candle_count=12,
        source_support_candle_count=144,
    )


def _structure_hash(row: NativeShortContextRow) -> str:
    assert row.anchor_low_price is not None
    assert row.anchor_high_price is not None
    return compute_structure_hash(
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        fib_model_name=FIB_MODEL_NAME,
        fib_model_version=FIB_MODEL_VERSION,
        map_cycle_id=row.map_cycle_id,
        anchor_low_price=row.anchor_low_price,
        anchor_high_price=row.anchor_high_price,
    )


def _map_record(map_id: int, row: NativeShortContextRow, *, attempt_id: str = "attempt-1") -> NativeShortMapRecord:
    return NativeShortMapRecord(
        map_id=map_id,
        key=_scope(row.symbol),
        published_at_utc=_NOW - timedelta(hours=1),
        structure_hash=_structure_hash(row),
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        fib_model_name=FIB_MODEL_NAME,
        fib_model_version=FIB_MODEL_VERSION,
        published_generation_attempt_id=attempt_id,
        map_cycle_id=row.map_cycle_id,
        anchor_low_ts_utc=row.anchor_start_ts_utc,
        anchor_low_price=row.anchor_low_price,
        anchor_high_ts_utc=row.anchor_end_ts_utc,
        anchor_high_price=row.anchor_high_price,
    )


def _generation_event(
    event_id: int,
    event_type: NativeShortMapGenerationEventType,
    *,
    attempt_id: str = "attempt-1",
    map_id: int | None = None,
    reason_code: str | None = None,
) -> NativeShortMapGenerationEvent:
    return NativeShortMapGenerationEvent(
        generation_event_id=event_id,
        key=_scope(),
        attempt_id=attempt_id,
        event_type=event_type,
        event_ts_utc=_NOW - timedelta(minutes=event_id),
        reason_code=reason_code,
        map_id=map_id,
    )


class _RecordingCursor:
    def __init__(self, conn: "_RecordingConn") -> None:
        self._conn = conn
        self._last_sql = ""

    def execute(self, sql: str, params: Any = None) -> None:
        self._last_sql = sql.strip()
        self._conn.next_id += 1
        self._conn.log.append((self._last_sql, params, self._conn.next_id))

    @property
    def lastrowid(self) -> int:
        return self._conn.next_id

    def fetchall(self) -> list[dict[str, Any]]:
        if "FROM native_short_map_scope_v1" in self._last_sql:
            return [{"scope_id": 1, "scope_support_state": "SUPPORTED"}]
        return []

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _RecordingConn:
    def __init__(self) -> None:
        self.next_id = 0
        self.log: list[tuple[str, Any, int]] = []
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.tx_log: list[str] = []

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self)

    def insert_log(self, table: str) -> list[tuple[str, Any, int]]:
        return [(sql, params, row_id) for sql, params, row_id in self.log if f"INSERT INTO {table}" in sql]

    def begin(self) -> None:
        self.begin_count += 1
        self.tx_log.append("begin")

    def commit(self) -> None:
        self.commit_count += 1
        self.tx_log.append("commit")

    def rollback(self) -> None:
        self.rollback_count += 1
        self.tx_log.append("rollback")

    def close(self) -> None:
        self.close_count += 1
        self.tx_log.append("close")


def _scope_row(symbol: str = "BTC") -> dict[str, Any]:
    return {
        "venue": "bitvavo",
        "symbol": symbol,
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "scope_support_state": "SUPPORTED",
        "scope_reason_code": None,
    }


class _RunnerCursor:
    def __init__(self, conn: "_RunnerConn") -> None:
        self._conn = conn
        self._last_sql = ""

    def execute(self, sql: str, params: Any = None) -> None:
        self._last_sql = sql.strip()
        self._conn.log.append((self._last_sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        if "FROM native_short_map_scope_v1" in self._last_sql:
            if "FOR UPDATE" in self._last_sql and self._conn.lock_scope_rows is not None:
                return self._conn.lock_scope_rows
            return self._conn.scope_rows
        return []

    @property
    def lastrowid(self) -> int:
        self._conn.next_id += 1
        return self._conn.next_id

    def __enter__(self) -> "_RunnerCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _RunnerConn:
    def __init__(
        self,
        *,
        scope_rows: list[dict[str, Any]] | None = None,
        lock_scope_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.scope_rows = scope_rows or []
        self.lock_scope_rows = lock_scope_rows
        self.log: list[tuple[str, Any]] = []
        self.next_id = 0
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.tx_log: list[str] = []

    def cursor(self) -> _RunnerCursor:
        return _RunnerCursor(self)

    def begin(self) -> None:
        self.begin_count += 1
        self.tx_log.append("begin")

    def commit(self) -> None:
        self.commit_count += 1
        self.tx_log.append("commit")

    def rollback(self) -> None:
        self.rollback_count += 1
        self.tx_log.append("rollback")

    def close(self) -> None:
        self.close_count += 1
        self.tx_log.append("close")


class _LedgerReadCursor:
    def __init__(self, conn: "_LedgerReadConn") -> None:
        self._conn = conn

    def execute(self, sql: str, params: Any = None) -> None:
        self._conn.log.append((sql.strip(), params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self._conn.rows

    def __enter__(self) -> "_LedgerReadCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _LedgerReadConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.log: list[tuple[str, Any]] = []

    def cursor(self) -> _LedgerReadCursor:
        return _LedgerReadCursor(self)


def _map_ledger_row(**overrides: Any) -> dict[str, Any]:
    row = _available_row()
    values: dict[str, Any] = {
        "map_id": 7,
        "venue": "bitvavo",
        "symbol": "BTC",
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "structure_hash": _structure_hash(row),
        "generator_name": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "fib_model_name": FIB_MODEL_NAME,
        "fib_model_version": FIB_MODEL_VERSION,
        "published_generation_attempt_id": "attempt-1",
        "previous_map_id": None,
        "previous_map_cycle_id": None,
        "map_cycle_id": row.map_cycle_id,
        "market_snapshot_ts_utc": None,
        "published_at_utc": datetime(2026, 7, 4, 10, 30, 0),
        "anchor_low_ts_utc": row.anchor_start_ts_utc,
        "anchor_low_price": row.anchor_low_price,
        "anchor_high_ts_utc": row.anchor_end_ts_utc,
        "anchor_high_price": row.anchor_high_price,
        "retrace_ratio": None,
        "retrace_price": None,
        "fib_ratios_json": None,
        "target_levels_json": None,
        "invalidation_price": row.invalidation_price,
        "invalidation_rule": None,
        "source_primary_candle_ts_utc": None,
        "source_support_candle_ts_utc": None,
        "source_primary_ref": None,
        "source_support_ref": None,
        "source_primary_candle_count": 73,
        "source_support_candle_count": 219,
        "map_payload_json": None,
    }
    values.update(overrides)
    return values


def _generation_ledger_row(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "generation_event_id": 11,
        "venue": "bitvavo",
        "symbol": "BTC",
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "generation_attempt_id": "attempt-1",
        "event_type": "PUBLISHED",
        "event_ts_utc": datetime(2026, 7, 4, 10, 31, 0),
        "reason_code": None,
        "map_id": 7,
        "trigger_type": None,
        "candidate_map_cycle_id": None,
        "candidate_previous_map_id": None,
        "candidate_primary_lifecycle_state": None,
        "candidate_current_map_status": None,
        "latest_primary_close_ts_utc": None,
        "latest_support_close_ts_utc": None,
        "latest_primary_close_price": None,
        "source_primary_ref": None,
        "source_support_ref": None,
        "source_primary_candle_count": None,
        "source_support_candle_count": None,
    }
    values.update(overrides)
    return values


def _lifecycle_ledger_row(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "lifecycle_event_id": 13,
        "map_id": 7,
        "lifecycle_event_type": "ACTIVATED",
        "event_ts_utc": datetime(2026, 7, 4, 10, 32, 0),
        "reason_code": None,
        "successor_map_id": None,
        "observed_current_price": None,
        "observed_max_high_since_anchor": None,
        "observed_min_low_since_anchor": None,
        "latest_primary_close_ts_utc": None,
        "latest_support_close_ts_utc": None,
        "observer_name": None,
        "observer_version": None,
    }
    values.update(overrides)
    return values


def test_fetch_map_missing_published_at_fails_closed() -> None:
    conn = _LedgerReadConn([_map_ledger_row(published_at_utc=None)])

    with pytest.raises(ValueError) as exc:
        materializer._fetch_maps_for_scope(conn, _scope())

    assert str(exc.value) == (
        "REQUIRED_LEDGER_TIMESTAMP_MISSING "
        "table=native_short_map_v1 field=published_at_utc map_id=7"
    )


def test_fetch_generation_event_missing_event_ts_fails_closed() -> None:
    conn = _LedgerReadConn([_generation_ledger_row(event_ts_utc=None)])

    with pytest.raises(ValueError) as exc:
        materializer._fetch_generation_events_for_scope(conn, _scope())

    assert str(exc.value) == (
        "REQUIRED_LEDGER_TIMESTAMP_MISSING "
        "table=native_short_map_generation_event_v1 "
        "field=event_ts_utc generation_event_id=11"
    )


def test_fetch_lifecycle_event_missing_event_ts_fails_closed() -> None:
    conn = _LedgerReadConn([_lifecycle_ledger_row(event_ts_utc=None)])

    with pytest.raises(ValueError) as exc:
        materializer._fetch_lifecycle_events_for_map_ids(conn, [7])

    assert str(exc.value) == (
        "REQUIRED_LEDGER_TIMESTAMP_MISSING "
        "table=native_short_map_lifecycle_event_v1 "
        "field=event_ts_utc lifecycle_event_id=13"
    )


def test_valid_ledger_timestamps_normalize_naive_values_and_keep_optional_fields_optional() -> None:
    map_row = _map_ledger_row(published_at_utc=datetime(2026, 7, 4, 10, 30, 0))
    generation_row = _generation_ledger_row(event_ts_utc=datetime(2026, 7, 4, 10, 31, 0))
    lifecycle_row = _lifecycle_ledger_row(event_ts_utc=datetime(2026, 7, 4, 10, 32, 0))

    maps = materializer._fetch_maps_for_scope(_LedgerReadConn([map_row]), _scope())
    generation_events = materializer._fetch_generation_events_for_scope(
        _LedgerReadConn([generation_row]),
        _scope(),
    )
    lifecycle_events = materializer._fetch_lifecycle_events_for_map_ids(
        _LedgerReadConn([lifecycle_row]),
        [7],
    )

    assert maps[0].published_at_utc == datetime(2026, 7, 4, 10, 30, 0, tzinfo=UTC)
    assert maps[0].market_snapshot_ts_utc is None
    assert generation_events[0].event_ts_utc == datetime(2026, 7, 4, 10, 31, 0, tzinfo=UTC)
    assert generation_events[0].latest_primary_close_ts_utc is None
    assert lifecycle_events[0].event_ts_utc == datetime(2026, 7, 4, 10, 32, 0, tzinfo=UTC)
    assert lifecycle_events[0].latest_support_close_ts_utc is None


def test_runner_defaults_to_dry_run_and_requires_explicit_write() -> None:
    args = parse_args(["--symbols", "BTC"])
    assert args.write is False
    assert parse_symbols("btc,ETH") == ["BTC", "ETH"]


def test_write_rejects_multi_symbol_before_db(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get_connection() -> Any:
        raise AssertionError("DB connection must not be opened")

    monkeypatch.setattr(runner, "get_connection", fail_get_connection)

    assert runner.main(["--symbols", "BTC,ETH", "--write"]) == 2


def test_write_rejects_zero_symbol_before_db(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get_connection() -> Any:
        raise AssertionError("DB connection must not be opened")

    monkeypatch.setattr(runner, "get_connection", fail_get_connection)

    assert runner.main(["--symbols", "", "--write"]) == 2


def test_dry_run_accepts_multi_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    scope_conn = _RunnerConn(scope_rows=[_scope_row("BTC"), _scope_row("ETH")])
    run_conns = [_RunnerConn(), _RunnerConn()]
    opened = [scope_conn, *run_conns]

    def fake_get_connection() -> _RunnerConn:
        return opened.pop(0)

    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        runner,
        "build_rows_for_symbols",
        lambda *, venue, symbols, now_utc: [_available_row(symbol) for symbol in symbols],
    )

    assert runner.main(["--symbols", "BTC,ETH", "--output", "summary"]) == 0
    assert run_conns[0].commit_count == 0
    assert run_conns[1].commit_count == 0
    assert run_conns[0].rollback_count == 1
    assert run_conns[1].rollback_count == 1


def test_canonical_scope_zero_match_is_explicit_skip() -> None:
    resolved, results = runner._canonical_scope_by_symbol(symbols=["BTC"], scopes=[], write=True)

    assert resolved == {}
    assert len(results) == 1
    assert results[0].status == "skipped"
    assert results[0].reason_code == "SCOPE_NOT_FOUND_OR_NOT_SUPPORTED"


def test_canonical_scope_one_match_resolves() -> None:
    scope = _supported("BTC")
    resolved, results = runner._canonical_scope_by_symbol(symbols=["BTC"], scopes=[scope], write=True)

    assert resolved == {"BTC": scope}
    assert results == []


def test_canonical_scope_duplicate_match_fails_closed() -> None:
    scope = _supported("BTC")
    resolved, results = runner._canonical_scope_by_symbol(
        symbols=["BTC"],
        scopes=[scope, scope],
        write=True,
    )

    assert resolved == {}
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].reason_code == "AMBIGUOUS_SCOPE"


def test_fetch_supported_scopes_uses_full_canonical_key() -> None:
    conn = _RunnerConn(scope_rows=[_scope_row("BTC")])

    result = runner.fetch_supported_scopes(
        conn,
        venue="bitvavo",
        symbols=["BTC"],
    )

    assert len(result) == 1
    sql, params = conn.log[0]
    assert "quote_currency = %s" in sql
    assert "fib_trading_horizon = %s" in sql
    assert "primary_interval = %s" in sql
    assert "supporting_interval = %s" in sql
    assert params[:5] == ("bitvavo", "EUR", "SHORT", "4h", "1h")


def test_runner_dry_run_invokes_no_insert_and_no_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    scope_conn = _RunnerConn(scope_rows=[_scope_row("BTC")])
    run_conn = _RunnerConn()
    opened = [scope_conn, run_conn]

    def fake_get_connection() -> _RunnerConn:
        return opened.pop(0)

    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        runner,
        "build_rows_for_symbols",
        lambda *, venue, symbols, now_utc: [_available_row("BTC")],
    )

    assert runner.main(["--symbols", "BTC", "--output", "summary"]) == 0
    assert run_conn.commit_count == 0
    assert run_conn.rollback_count == 1
    assert all("INSERT INTO" not in sql for sql, _ in run_conn.log)


def test_runner_failure_after_map_insert_rolls_back_no_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_conn = _RunnerConn(scope_rows=[_scope_row("BTC")])
    run_conn = _RunnerConn()
    opened = [scope_conn, run_conn]

    def fake_get_connection() -> _RunnerConn:
        return opened.pop(0)

    def fail_after_map_insert(conn: Any, **kwargs: Any) -> Any:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO native_short_map_v1 (...) VALUES (...)", ())
        raise RuntimeError("map insert failure")

    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        runner,
        "build_rows_for_symbols",
        lambda *, venue, symbols, now_utc: [_available_row("BTC")],
    )
    monkeypatch.setattr(runner, "materialize_scope_symbol", fail_after_map_insert)

    assert runner.main(["--symbols", "BTC", "--write", "--output", "summary"]) == 1
    assert run_conn.begin_count == 1
    assert run_conn.commit_count == 0
    assert run_conn.rollback_count == 1
    assert any("INSERT INTO native_short_map_v1" in sql for sql, _ in run_conn.log)


def test_runner_failure_after_generation_event_insert_rolls_back_no_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_conn = _RunnerConn(scope_rows=[_scope_row("BTC")])
    run_conn = _RunnerConn()
    opened = [scope_conn, run_conn]

    def fake_get_connection() -> _RunnerConn:
        return opened.pop(0)

    def fail_after_generation_insert(conn: Any, **kwargs: Any) -> Any:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO native_short_map_generation_event_v1 (...) VALUES (...)", ())
        raise RuntimeError("generation insert failure")

    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        runner,
        "build_rows_for_symbols",
        lambda *, venue, symbols, now_utc: [_available_row("BTC")],
    )
    monkeypatch.setattr(runner, "materialize_scope_symbol", fail_after_generation_insert)

    assert runner.main(["--symbols", "BTC", "--write", "--output", "summary"]) == 1
    assert run_conn.begin_count == 1
    assert run_conn.commit_count == 0
    assert run_conn.rollback_count == 1
    assert any("INSERT INTO native_short_map_generation_event_v1" in sql for sql, _ in run_conn.log)


def test_runner_write_commits_once_after_materializer_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_conn = _RunnerConn(scope_rows=[_scope_row("BTC")])
    run_conn = _RunnerConn()
    opened = [scope_conn, run_conn]

    def fake_get_connection() -> _RunnerConn:
        return opened.pop(0)

    def complete_materialization(conn: Any, **kwargs: Any) -> Any:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO native_short_map_generation_event_v1 (...) VALUES (...)", ())
            cur.execute("INSERT INTO native_short_map_v1 (...) VALUES (...)", ())
            cur.execute("INSERT INTO native_short_map_generation_event_v1 (...) VALUES (...)", ())
            cur.execute("INSERT INTO native_short_map_lifecycle_event_v1 (...) VALUES (...)", ())
        return runner.ScopeMaterializationResult(
            symbol="BTC",
            attempted=True,
            status="published",
            dry_run=False,
            map_id=1,
            generation_attempt_id="attempt-1",
            generation_event_ids=[1, 3],
            lifecycle_event_ids=[4],
        )

    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        runner,
        "build_rows_for_symbols",
        lambda *, venue, symbols, now_utc: [_available_row("BTC")],
    )
    monkeypatch.setattr(runner, "materialize_scope_symbol", complete_materialization)

    assert runner.main(["--symbols", "BTC", "--write", "--output", "summary"]) == 0
    assert run_conn.begin_count == 1
    assert run_conn.commit_count == 1
    assert run_conn.rollback_count == 0
    assert run_conn.tx_log == ["begin", "commit", "close"]


def test_runner_write_rejects_scope_state_drift_under_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_conn = _RunnerConn(scope_rows=[_scope_row("BTC")])
    run_conn = _RunnerConn(
        lock_scope_rows=[{"scope_id": 1, "scope_support_state": "NOT_APPLICABLE"}]
    )
    opened = [scope_conn, run_conn]

    def fake_get_connection() -> _RunnerConn:
        return opened.pop(0)

    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        runner,
        "build_rows_for_symbols",
        lambda *, venue, symbols, now_utc: [_available_row("BTC")],
    )

    assert runner.main(["--symbols", "BTC", "--write", "--output", "summary"]) == 1
    assert run_conn.begin_count == 1
    assert run_conn.commit_count == 0
    assert run_conn.rollback_count == 1
    assert all("INSERT INTO" not in sql for sql, _ in run_conn.log)
    assert any("FOR UPDATE" in sql for sql, _ in run_conn.log)


def test_structure_hash_is_deterministic() -> None:
    row = _available_row()
    assert _structure_hash(row) == _structure_hash(row)
    assert len(_structure_hash(row)) == 64


def test_unavailable_statuses_map_to_schema_reason_codes() -> None:
    for status in (
        STATUS_INSUFFICIENT_4H,
        STATUS_INSUFFICIENT_1H,
        STATUS_STALE_OR_INVALID,
        STATUS_SYMBOL_MISSING,
    ):
        reason = context_status_to_rejection_reason(status)
        assert reason in DATA_UNAVAILABLE_REASON_CODES


def test_available_dry_run_does_not_insert_rows() -> None:
    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_available_row(),
        now_utc=_NOW,
        write=False,
    )

    assert result.status == "skipped"
    assert result.reason_code == "DRY_RUN_WRITE_DISABLED"
    assert result.planned_status == "published"
    assert conn.insert_log("native_short_map_v1") == []
    assert conn.insert_log("native_short_map_generation_event_v1") == []
    assert conn.insert_log("native_short_map_lifecycle_event_v1") == []


def test_context_symbol_mismatch_fails_before_lock_or_ledger_reads() -> None:
    conn = _RecordingConn()
    with pytest.raises(ValueError, match="CONTEXT_SCOPE_MISMATCH field=symbol"):
        materialize_scope_symbol(
            conn,
            scope_support=_supported("BTC"),
            context_row=_available_row("ETH"),
            now_utc=_NOW,
            write=True,
        )

    assert conn.log == []


def test_context_interval_mismatch_fails_before_lock_or_ledger_reads() -> None:
    conn = _RecordingConn()
    row = NativeShortContextRow(**{**_available_row().__dict__, "primary_interval": "1h"})
    with pytest.raises(ValueError, match="CONTEXT_SCOPE_MISMATCH field=primary_interval"):
        materialize_scope_symbol(
            conn,
            scope_support=_supported("BTC"),
            context_row=row,
            now_utc=_NOW,
            write=True,
        )

    assert conn.log == []


def test_missing_source_candle_count_fails_before_lock_or_ledger_reads() -> None:
    conn = _RecordingConn()
    row = NativeShortContextRow(
        **{**_available_row().__dict__, "source_primary_candle_count": None}
    )
    with pytest.raises(ValueError, match="SOURCE_CANDLE_COUNT_UNAVAILABLE"):
        materialize_scope_symbol(
            conn,
            scope_support=_supported(),
            context_row=row,
            now_utc=_NOW,
            write=True,
        )

    assert conn.log == []


def test_locked_scope_duplicate_rows_fail_before_ledger_insert() -> None:
    conn = _RunnerConn(
        lock_scope_rows=[
            {"scope_id": 1, "scope_support_state": "SUPPORTED"},
            {"scope_id": 2, "scope_support_state": "SUPPORTED"},
        ]
    )
    with pytest.raises(ValueError, match="LOCKED_SCOPE_ROW_COUNT_INVALID"):
        materialize_scope_symbol(
            conn,
            scope_support=_supported(),
            context_row=_available_row(),
            now_utc=_NOW,
            write=True,
        )

    assert all("INSERT INTO" not in sql for sql, _ in conn.log)


def test_locked_scope_zero_rows_fail_before_ledger_insert() -> None:
    conn = _RunnerConn(lock_scope_rows=[])
    with pytest.raises(ValueError, match="LOCKED_SCOPE_ROW_COUNT_INVALID"):
        materialize_scope_symbol(
            conn,
            scope_support=_supported(),
            context_row=_available_row(),
            now_utc=_NOW,
            write=True,
        )

    assert all("INSERT INTO" not in sql for sql, _ in conn.log)


def test_write_available_first_map_publishes_map_generation_and_lifecycle() -> None:
    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_available_row(),
        now_utc=_NOW,
        write=True,
    )

    assert result.status == "published"
    assert result.map_id is not None
    assert len(result.generation_event_ids) == 2
    assert len(result.lifecycle_event_ids) == 1
    assert len(conn.insert_log("native_short_map_v1")) == 1
    assert len(conn.insert_log("native_short_map_generation_event_v1")) == 2
    assert len(conn.insert_log("native_short_map_lifecycle_event_v1")) == 1
    map_params = conn.insert_log("native_short_map_v1")[0][1]
    generation_params = [entry[1] for entry in conn.insert_log("native_short_map_generation_event_v1")]
    assert map_params[29] == 73
    assert map_params[30] == 219
    assert [params[21] for params in generation_params] == [73, 73]
    assert [params[22] for params in generation_params] == [219, 219]


def test_write_available_first_map_defaults_trigger_type_to_manual_canary() -> None:
    """Callers that omit trigger_type (e.g. the manual canary runner) must
    keep getting the existing MANUAL_NATIVE_SHORT_MAP_LEDGER_CANARY label on
    both the ATTEMPT_STARTED and PUBLISHED events, not NULL provenance on
    the published row."""
    from src.market_data.native_short_map_materializer_v1 import TRIGGER_TYPE

    conn = _RecordingConn()
    materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_available_row(),
        now_utc=_NOW,
        write=True,
    )

    generation_params = [entry[1] for entry in conn.insert_log("native_short_map_generation_event_v1")]
    assert len(generation_params) == 2
    assert [params[11] for params in generation_params] == [TRIGGER_TYPE, TRIGGER_TYPE]


def test_write_available_first_map_propagates_explicit_scheduled_trigger_type() -> None:
    """An explicit runtime trigger_type (e.g. the scheduled 4h chain) must
    reach both the ATTEMPT_STARTED and PUBLISHED generation events instead
    of the hardcoded manual-canary constant or NULL."""
    conn = _RecordingConn()
    materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_available_row(),
        now_utc=_NOW,
        write=True,
        trigger_type="SCHEDULED_4H_MARKET_CHAIN",
    )

    generation_params = [entry[1] for entry in conn.insert_log("native_short_map_generation_event_v1")]
    assert len(generation_params) == 2
    assert [params[11] for params in generation_params] == [
        "SCHEDULED_4H_MARKET_CHAIN",
        "SCHEDULED_4H_MARKET_CHAIN",
    ]


def test_same_structure_hash_is_idempotent_without_skip_event(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _available_row()
    existing_map = _map_record(7, row)
    existing_generation_events = [
        _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED),
        _generation_event(2, NativeShortMapGenerationEventType.PUBLISHED, map_id=7),
    ]
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_maps_for_scope",
        lambda conn, key: [existing_map],
    )
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_generation_events_for_scope",
        lambda conn, key: existing_generation_events,
    )
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_lifecycle_events_for_map_ids",
        lambda conn, map_ids: [],
    )

    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=row,
        now_utc=_NOW,
        write=True,
    )

    assert result.status == "skipped"
    assert result.map_id == 7
    assert result.generation_event_ids == [2]
    assert result.reason_code == REASON_STRUCTURE_UNCHANGED
    assert conn.insert_log("native_short_map_v1") == []
    assert conn.insert_log("native_short_map_generation_event_v1") == []
    assert conn.insert_log("native_short_map_lifecycle_event_v1") == []


def test_duplicate_conflict_without_matching_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_duplicate(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("duplicate key")

    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._insert_map_row",
        raise_duplicate,
    )

    conn = _RecordingConn()
    with pytest.raises(RuntimeError, match="duplicate key"):
        materialize_scope_symbol(
            conn,
            scope_support=_supported(),
            context_row=_available_row(),
            now_utc=_NOW,
            write=True,
        )

    assert conn.insert_log("native_short_map_v1") == []
    assert len(conn.insert_log("native_short_map_generation_event_v1")) == 1
    assert conn.insert_log("native_short_map_lifecycle_event_v1") == []


def test_prior_same_rejection_is_idempotent_without_new_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_generation_events = [
        _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED),
        _generation_event(
            2,
            NativeShortMapGenerationEventType.REJECTED,
            reason_code="CANDLES_INSUFFICIENT",
        ),
    ]
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_generation_events_for_scope",
        lambda conn, key: existing_generation_events,
    )

    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_unavailable_row(status=STATUS_INSUFFICIENT_4H),
        now_utc=_NOW,
        write=True,
    )

    assert result.status == "skipped"
    assert result.reason_code == REASON_PRIOR_REJECTION_UNCHANGED
    assert result.generation_event_ids == [2]
    assert conn.insert_log("native_short_map_generation_event_v1") == []
    assert conn.insert_log("native_short_map_lifecycle_event_v1") == []


def test_old_rejection_behind_newer_failure_does_not_suppress_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_generation_events = [
        _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED, attempt_id="old"),
        _generation_event(
            2,
            NativeShortMapGenerationEventType.REJECTED,
            attempt_id="old",
            reason_code="CANDLES_INSUFFICIENT",
        ),
        _generation_event(3, NativeShortMapGenerationEventType.ATTEMPT_STARTED, attempt_id="newer"),
        _generation_event(
            4,
            NativeShortMapGenerationEventType.FAILED,
            attempt_id="newer",
            reason_code="UNHANDLED_EXCEPTION",
        ),
    ]
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_generation_events_for_scope",
        lambda conn, key: existing_generation_events,
    )

    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_unavailable_row(status=STATUS_INSUFFICIENT_4H),
        now_utc=_NOW,
        write=True,
    )

    assert result.status == "skipped"
    assert result.reason_code == "CANDLES_INSUFFICIENT"
    assert len(conn.insert_log("native_short_map_generation_event_v1")) == 2


def test_new_unavailable_write_records_rejected_attempt_without_lifecycle() -> None:
    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_unavailable_row(status=STATUS_STALE_OR_INVALID),
        now_utc=_NOW,
        write=True,
    )

    assert result.status == "skipped"
    assert result.reason_code == "CANDLE_SNAPSHOT_STALE"
    assert result.generation_event_type == "REJECTED"
    assert len(conn.insert_log("native_short_map_generation_event_v1")) == 2
    assert conn.insert_log("native_short_map_v1") == []
    assert conn.insert_log("native_short_map_lifecycle_event_v1") == []


def test_new_unavailable_write_propagates_explicit_trigger_type_to_rejected_event() -> None:
    """The REJECTED event on the insufficient-context path must also carry
    the caller's runtime trigger_type, not just the ATTEMPT_STARTED event."""
    conn = _RecordingConn()
    materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=_unavailable_row(status=STATUS_STALE_OR_INVALID),
        now_utc=_NOW,
        write=True,
        trigger_type="SCHEDULED_4H_MARKET_CHAIN",
    )

    generation_params = [entry[1] for entry in conn.insert_log("native_short_map_generation_event_v1")]
    assert len(generation_params) == 2
    assert [params[11] for params in generation_params] == [
        "SCHEDULED_4H_MARKET_CHAIN",
        "SCHEDULED_4H_MARKET_CHAIN",
    ]


def test_supersedes_previous_active_map_without_duplicate_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_row = _available_row()
    new_row = _available_row(high_price=Decimal("0.121"))
    existing_map = _map_record(7, old_row)
    existing_generation_events = [
        _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED),
        _generation_event(2, NativeShortMapGenerationEventType.PUBLISHED, map_id=7),
    ]
    existing_lifecycle_events = [
        NativeShortMapLifecycleEvent(
            lifecycle_event_id=3,
            map_id=7,
            event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            event_ts_utc=_NOW - timedelta(hours=1),
        )
    ]
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_maps_for_scope",
        lambda conn, key: [existing_map],
    )
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_generation_events_for_scope",
        lambda conn, key: existing_generation_events,
    )
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_lifecycle_events_for_map_ids",
        lambda conn, map_ids: existing_lifecycle_events,
    )

    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=new_row,
        now_utc=_NOW,
        write=True,
    )

    lifecycle_inserts = conn.insert_log("native_short_map_lifecycle_event_v1")
    lifecycle_types = [params[1] for _, params, _ in lifecycle_inserts]
    assert result.status == "published"
    assert lifecycle_types == ["ACTIVATED", "SUPERSEDED"]


def test_terminal_map_is_not_reopened_or_superseded(monkeypatch: pytest.MonkeyPatch) -> None:
    old_row = _available_row()
    new_row = _available_row(high_price=Decimal("0.121"))
    terminal_map = _map_record(7, old_row)
    existing_generation_events = [
        _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED),
        _generation_event(2, NativeShortMapGenerationEventType.PUBLISHED, map_id=7),
    ]
    existing_lifecycle_events = [
        NativeShortMapLifecycleEvent(
            lifecycle_event_id=3,
            map_id=7,
            event_type=NativeShortMapLifecycleEventType.COMPLETED,
            event_ts_utc=_NOW - timedelta(hours=1),
        )
    ]
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_maps_for_scope",
        lambda conn, key: [terminal_map],
    )
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_generation_events_for_scope",
        lambda conn, key: existing_generation_events,
    )
    monkeypatch.setattr(
        "src.market_data.native_short_map_materializer_v1._fetch_lifecycle_events_for_map_ids",
        lambda conn, map_ids: existing_lifecycle_events,
    )

    conn = _RecordingConn()
    result = materialize_scope_symbol(
        conn,
        scope_support=_supported(),
        context_row=new_row,
        now_utc=_NOW,
        write=True,
    )

    lifecycle_inserts = conn.insert_log("native_short_map_lifecycle_event_v1")
    lifecycle_types = [params[1] for _, params, _ in lifecycle_inserts]
    assert result.status == "published"
    assert lifecycle_types == ["ACTIVATED"]


FORBIDDEN_IMPORTS = {
    "src.account",
    "src.account_provisioning",
    "src.broker",
    "src.decision_gate",
    "src.execution",
    "src.execution_planner",
    "src.executor",
    "src.portfolio",
    "src.reporting",
    "src.research",
    "src.selection",
    "src.market_data.run_native_short_fib_context_v1",
}


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/market_data/native_short_map_materializer_v1.py",
        "src/market_data/run_native_short_map_materializer_v1.py",
    ],
)
def test_canary_does_not_import_forbidden_layers(rel_path: str) -> None:
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
            for forbidden in FORBIDDEN_IMPORTS:
                assert not name.startswith(forbidden), f"{rel_path} imports {name}"


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


def test_canary_reachable_import_graph_excludes_forbidden_layers() -> None:
    root = Path(__file__).parent.parent
    start_paths = [
        root / "src/market_data/native_short_map_materializer_v1.py",
        root / "src/market_data/run_native_short_map_materializer_v1.py",
    ]
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
            for forbidden in FORBIDDEN_IMPORTS:
                assert not module.startswith(forbidden), f"{path} reaches forbidden import {module}"
            module_path = _local_module_path(root, module)
            if module_path is not None:
                stack.append(module_path)

    assert "src.market_data.run_native_short_fib_context_v1" not in reachable_modules


def test_canary_modules_import_without_forbidden_runtime_modules() -> None:
    before_import = set(sys.modules)
    materializer_module = importlib.import_module("src.market_data.native_short_map_materializer_v1")
    runner_module = importlib.import_module("src.market_data.run_native_short_map_materializer_v1")
    newly_imported = set(sys.modules) - before_import

    assert materializer_module.GENERATOR_NAME == GENERATOR_NAME
    assert runner_module.RUNNER_NAME == "run_native_short_map_materializer_v1"
    assert "src.market_data.run_native_short_fib_context_v1" not in newly_imported


def test_canary_sources_include_safety_markers() -> None:
    root = Path(__file__).parent.parent
    combined = (
        root / "src/market_data/native_short_map_materializer_v1.py"
    ).read_text() + (root / "src/market_data/run_native_short_map_materializer_v1.py").read_text()
    for marker in (
        "broker_private_calls=0",
        "broker_writes=0",
        "order_submission=0",
        "live_orders=0",
        "decision_gate=none",
        "execution_planner=none",
        "executor=none",
    ):
        assert marker in combined
