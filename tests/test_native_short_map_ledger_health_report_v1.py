from __future__ import annotations

import ast
import io
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.reporting import native_short_map_ledger_health_report_v1 as report_mod
from src.reporting import run_native_short_map_ledger_health_report_v1 as runner
from src.market_data.native_short_map_lifecycle_v1 import (
    NativeShortMapGenerationEvent,
    NativeShortMapGenerationEventType,
    NativeShortMapLifecycleEvent,
    NativeShortMapLifecycleEventType,
    NativeShortMapRecord,
    NativeShortMapScopeKey,
)

KEY = NativeShortMapScopeKey(venue="bitvavo", symbol="BTC")
T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
T3 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


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


def _map_record(
    *,
    map_id: int = 9001,
    published_at_utc: datetime = T1,
    structure_hash: str = "hash-a",
    attempt_id: str = "attempt-1",
    previous_map_id: int | None = None,
    source_primary_candle_ts_utc: datetime | None = T1,
    source_support_candle_ts_utc: datetime | None = T1,
    invalidation_price: Decimal | None = Decimal("10000"),
) -> NativeShortMapRecord:
    return NativeShortMapRecord(
        map_id=map_id,
        key=KEY,
        published_at_utc=published_at_utc,
        structure_hash=structure_hash,
        generator_name="native_short_map_materializer_v1",
        generator_version="0.1",
        fib_model_name="native_short_fib_context_v1",
        fib_model_version="0.1",
        published_generation_attempt_id=attempt_id,
        previous_map_id=previous_map_id,
        anchor_low_ts_utc=T0,
        anchor_low_price=Decimal("9000"),
        anchor_high_ts_utc=T1,
        anchor_high_price=Decimal("11000"),
        target_levels_json="[]",
        invalidation_price=invalidation_price,
        invalidation_rule="CLOSE_BELOW_ANCHOR_LOW",
        source_primary_candle_ts_utc=source_primary_candle_ts_utc,
        source_support_candle_ts_utc=source_support_candle_ts_utc,
        source_primary_candle_count=100,
        source_support_candle_count=100,
    )


def _gen_event(
    *,
    generation_event_id: int,
    attempt_id: str = "attempt-1",
    event_type: NativeShortMapGenerationEventType,
    event_ts_utc: datetime = T1,
    map_id: int | None = None,
    reason_code: str | None = None,
) -> NativeShortMapGenerationEvent:
    return NativeShortMapGenerationEvent(
        generation_event_id=generation_event_id,
        key=KEY,
        attempt_id=attempt_id,
        event_type=event_type,
        event_ts_utc=event_ts_utc,
        map_id=map_id,
        reason_code=reason_code,
    )


def _lifecycle_event(
    *,
    lifecycle_event_id: int,
    map_id: int,
    event_type: NativeShortMapLifecycleEventType,
    event_ts_utc: datetime = T2,
    successor_map_id: int | None = None,
) -> NativeShortMapLifecycleEvent:
    return NativeShortMapLifecycleEvent(
        lifecycle_event_id=lifecycle_event_id,
        map_id=map_id,
        event_type=event_type,
        event_ts_utc=event_ts_utc,
        successor_map_id=successor_map_id,
    )


def _healthy_chain(map_id: int = 9001, attempt_id: str = "attempt-1") -> list[NativeShortMapGenerationEvent]:
    return [
        _gen_event(
            generation_event_id=1,
            attempt_id=attempt_id,
            event_type=NativeShortMapGenerationEventType.ATTEMPT_STARTED,
            event_ts_utc=T1,
        ),
        _gen_event(
            generation_event_id=2,
            attempt_id=attempt_id,
            event_type=NativeShortMapGenerationEventType.PUBLISHED,
            event_ts_utc=T1,
            map_id=map_id,
        ),
    ]


def _build(
    *,
    scope_rows: list[dict[str, Any]],
    maps: list[NativeShortMapRecord],
    generation_events: list[NativeShortMapGenerationEvent],
    lifecycle_events: list[NativeShortMapLifecycleEvent],
    latest_primary_candle_ts_utc: datetime | None = T1,
    latest_support_candle_ts_utc: datetime | None = T1,
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
        maps=maps,
        generation_events=generation_events,
        lifecycle_events=lifecycle_events,
        latest_primary_candle_ts_utc=latest_primary_candle_ts_utc,
        latest_support_candle_ts_utc=latest_support_candle_ts_utc,
    )


# ---------------------------------------------------------------------------
# Healthy canary state
# ---------------------------------------------------------------------------


def test_healthy_canonical_btc_like_state_is_healthy() -> None:
    map_record = _map_record()
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=_healthy_chain(),
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
    )
    assert report.scope_status == report_mod.SCOPE_STATUS_SUPPORTED
    assert report.lifecycle_state == "MAP_ACTIVE"
    assert report.active_map_id == map_record.map_id
    assert report.active_map_resolution_status == report_mod.ACTIVE_MAP_RESOLUTION_SINGLE
    assert report.generation_chain_integrity_status == report_mod.CHAIN_STATUS_OK
    assert report.source_freshness_state == report_mod.FRESHNESS_CURRENT
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_HEALTHY
    assert report.overall_health_reason_codes == []


# ---------------------------------------------------------------------------
# Scope states
# ---------------------------------------------------------------------------


def test_missing_scope() -> None:
    report = _build(scope_rows=[], maps=[], generation_events=[], lifecycle_events=[])
    assert report.scope_status == report_mod.SCOPE_STATUS_MISSING
    assert report.scope_row_count == 0
    assert report.lifecycle_evaluated is False
    assert report.lifecycle_state == "NOT_EVALUATED"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NEEDS_REVIEW
    assert "SCOPE_MISSING" in report.overall_health_reason_codes


def test_not_applicable_scope() -> None:
    report = _build(
        scope_rows=[_scope_row(state="NOT_APPLICABLE", reason_code="ASSET_NOT_ENABLED")],
        maps=[],
        generation_events=[],
        lifecycle_events=[],
    )
    assert report.scope_status == report_mod.SCOPE_STATUS_NOT_APPLICABLE
    assert report.lifecycle_evaluated is True
    assert report.lifecycle_state == "MAP_NOT_APPLICABLE"
    assert report.overall_health_status == report_mod.OVERALL_HEALTH_NOT_APPLICABLE
    assert report.overall_health_reason_codes == []


def test_duplicate_canonical_scope_same_state_is_ambiguous() -> None:
    report = _build(
        scope_rows=[_scope_row(scope_id=1), _scope_row(scope_id=2)],
        maps=[],
        generation_events=[],
        lifecycle_events=[],
    )
    assert report.scope_row_count == 2
    assert report.scope_status == report_mod.SCOPE_STATUS_AMBIGUOUS
    assert report.lifecycle_evaluated is False
    assert "SCOPE_AMBIGUOUS" in report.overall_health_reason_codes


def test_duplicate_canonical_scope_conflicting_states() -> None:
    report = _build(
        scope_rows=[
            _scope_row(scope_id=1, state="SUPPORTED"),
            _scope_row(scope_id=2, state="NOT_APPLICABLE"),
        ],
        maps=[],
        generation_events=[],
        lifecycle_events=[],
    )
    assert report.scope_status == report_mod.SCOPE_STATUS_CONFLICTING
    assert "SCOPE_CONFLICTING" in report.overall_health_reason_codes


# ---------------------------------------------------------------------------
# Active map resolution
# ---------------------------------------------------------------------------


def test_no_active_map() -> None:
    report = _build(scope_rows=[_scope_row()], maps=[], generation_events=[], lifecycle_events=[])
    assert report.lifecycle_state == "MAP_REBUILD_REQUIRED"
    assert report.active_map_resolution_status == report_mod.ACTIVE_MAP_RESOLUTION_NO_ACTIVE_MAP
    assert report.active_map_id is None
    assert report.generation_chain_integrity_status == report_mod.CHAIN_STATUS_NO_ACTIVE_MAP
    assert report.source_freshness_state == report_mod.FRESHNESS_NO_ACTIVE_MAP
    assert "LIFECYCLE_STATE_MAP_REBUILD_REQUIRED" in report.overall_health_reason_codes


def test_ambiguous_active_map_projection() -> None:
    map_a = _map_record(map_id=1, published_at_utc=T1, attempt_id="attempt-a")
    map_b = _map_record(map_id=2, published_at_utc=T2, attempt_id="attempt-b")
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_a, map_b],
        generation_events=_healthy_chain(map_id=1, attempt_id="attempt-a")
        + _healthy_chain(map_id=2, attempt_id="attempt-b"),
        lifecycle_events=[],
    )
    assert report.active_map_resolution_status == report_mod.ACTIVE_MAP_RESOLUTION_AMBIGUOUS
    assert report.active_map_candidate_ids == [1, 2]
    assert "AMBIGUOUS_ACTIVE_MAP_CANDIDATES" in report.overall_health_reason_codes


# ---------------------------------------------------------------------------
# Generation-chain integrity
# ---------------------------------------------------------------------------


def test_missing_attempt_started() -> None:
    map_record = _map_record()
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=[
            _gen_event(
                generation_event_id=1,
                event_type=NativeShortMapGenerationEventType.PUBLISHED,
                map_id=map_record.map_id,
            )
        ],
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
    )
    assert report.generation_chain_integrity_status == report_mod.CHAIN_STATUS_ATTEMPT_STARTED_MISSING
    assert "GENERATION_CHAIN_ATTEMPT_STARTED_MISSING" in report.overall_health_reason_codes


def test_missing_published() -> None:
    map_record = _map_record()
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=[
            _gen_event(
                generation_event_id=1,
                event_type=NativeShortMapGenerationEventType.ATTEMPT_STARTED,
            )
        ],
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
    )
    assert report.generation_chain_integrity_status == report_mod.CHAIN_STATUS_PUBLISHED_EVENT_MISSING
    assert "GENERATION_CHAIN_PUBLISHED_EVENT_MISSING" in report.overall_health_reason_codes


def test_published_map_id_mismatch() -> None:
    map_record = _map_record(map_id=9001)
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=[
            _gen_event(
                generation_event_id=1,
                event_type=NativeShortMapGenerationEventType.ATTEMPT_STARTED,
            ),
            _gen_event(
                generation_event_id=2,
                event_type=NativeShortMapGenerationEventType.PUBLISHED,
                map_id=4242,
            ),
        ],
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
    )
    assert report.generation_chain_integrity_status == report_mod.CHAIN_STATUS_PUBLISHED_MAP_ID_MISMATCH
    assert "GENERATION_CHAIN_PUBLISHED_MAP_ID_MISMATCH" in report.overall_health_reason_codes


# ---------------------------------------------------------------------------
# Source freshness
# ---------------------------------------------------------------------------


def test_missing_primary_source_timestamp() -> None:
    map_record = _map_record(source_primary_candle_ts_utc=None)
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=_healthy_chain(),
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
    )
    assert report.primary_source_freshness_state == report_mod.FRESHNESS_MISSING
    assert report.source_freshness_state == report_mod.FRESHNESS_MISSING
    assert "SOURCE_FRESHNESS_MISSING" in report.overall_health_reason_codes


def test_missing_supporting_source_timestamp() -> None:
    map_record = _map_record(source_support_candle_ts_utc=None)
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=_healthy_chain(),
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
    )
    assert report.supporting_source_freshness_state == report_mod.FRESHNESS_MISSING
    assert report.source_freshness_state == report_mod.FRESHNESS_MISSING


def test_stale_primary_source() -> None:
    map_record = _map_record(source_primary_candle_ts_utc=T1)
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=_healthy_chain(),
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
        latest_primary_candle_ts_utc=T2,
    )
    assert report.primary_source_freshness_state == report_mod.FRESHNESS_STALE
    assert report.source_freshness_state == report_mod.FRESHNESS_STALE
    assert "SOURCE_FRESHNESS_STALE" in report.overall_health_reason_codes


def test_stale_supporting_source() -> None:
    map_record = _map_record(source_support_candle_ts_utc=T1)
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=_healthy_chain(),
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
        latest_support_candle_ts_utc=T2,
    )
    assert report.supporting_source_freshness_state == report_mod.FRESHNESS_STALE
    assert report.source_freshness_state == report_mod.FRESHNESS_STALE


def test_unavailable_latest_candle_context() -> None:
    map_record = _map_record()
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=_healthy_chain(),
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
        latest_primary_candle_ts_utc=None,
        latest_support_candle_ts_utc=None,
    )
    assert report.primary_source_freshness_state == report_mod.FRESHNESS_UNAVAILABLE
    assert report.source_freshness_state == report_mod.FRESHNESS_UNAVAILABLE
    assert "SOURCE_FRESHNESS_UNAVAILABLE" in report.overall_health_reason_codes


def test_stored_source_ahead_of_available_context() -> None:
    map_record = _map_record(source_primary_candle_ts_utc=T2)
    report = _build(
        scope_rows=[_scope_row()],
        maps=[map_record],
        generation_events=_healthy_chain(),
        lifecycle_events=[
            _lifecycle_event(
                lifecycle_event_id=1,
                map_id=map_record.map_id,
                event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            )
        ],
        latest_primary_candle_ts_utc=T1,
    )
    assert report.primary_source_freshness_state == report_mod.FRESHNESS_AHEAD_OR_INCONSISTENT
    assert report.source_freshness_state == report_mod.FRESHNESS_AHEAD_OR_INCONSISTENT
    assert "SOURCE_FRESHNESS_AHEAD_OR_INCONSISTENT" in report.overall_health_reason_codes


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
        if "FROM native_short_map_generation_event_v1" in sql:
            venue, symbol, quote_currency, horizon, primary, support = params
            self._rows = [
                dict(row)
                for row in self._conn.generation_event_rows
                if row["venue"] == venue
                and row["symbol"] == symbol
                and row["quote_currency"] == quote_currency
                and row["fib_trading_horizon"] == horizon
                and row["primary_interval"] == primary
                and row["supporting_interval"] == support
            ]
            return
        if "FROM native_short_map_lifecycle_event_v1" in sql:
            map_ids = set(params)
            self._rows = [
                dict(row) for row in self._conn.lifecycle_event_rows if row["map_id"] in map_ids
            ]
            return
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
        if "FROM native_short_map_v1" in sql:
            venue, symbol, quote_currency, horizon, primary, support = params
            self._rows = [
                dict(row)
                for row in self._conn.map_rows
                if row["venue"] == venue
                and row["symbol"] == symbol
                and row["quote_currency"] == quote_currency
                and row["fib_trading_horizon"] == horizon
                and row["primary_interval"] == primary
                and row["supporting_interval"] == support
            ]
            return
        if "FROM obs_market_candle" in sql:
            venue, interval_code, symbol = params
            matches = [
                dict(row)
                for row in self._conn.candle_rows
                if row["venue"] == venue and row["interval_code"] == interval_code and row["symbol"] == symbol
            ]
            matches.sort(key=lambda row: row["close_ts_utc"], reverse=True)
            self._rows = matches[:1]
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
        map_rows: list[dict[str, Any]] | None = None,
        generation_event_rows: list[dict[str, Any]] | None = None,
        lifecycle_event_rows: list[dict[str, Any]] | None = None,
        candle_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.scope_rows = list(scope_rows or [])
        self.map_rows = list(map_rows or [])
        self.generation_event_rows = list(generation_event_rows or [])
        self.lifecycle_event_rows = list(lifecycle_event_rows or [])
        self.candle_rows = list(candle_rows or [])
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


def _map_row_dict(
    *,
    map_id: int = 9001,
    attempt_id: str = "attempt-1",
    published_at_utc: datetime = T1,
    source_primary_candle_ts_utc: datetime | None = T1,
    source_support_candle_ts_utc: datetime | None = T1,
) -> dict[str, Any]:
    return {
        "map_id": map_id,
        "venue": KEY.venue,
        "symbol": KEY.symbol,
        "quote_currency": KEY.quote_currency,
        "fib_trading_horizon": KEY.fib_trading_horizon,
        "primary_interval": KEY.primary_interval,
        "supporting_interval": KEY.supporting_interval,
        "structure_hash": "hash-a",
        "generator_name": "native_short_map_materializer_v1",
        "generator_version": "0.1",
        "fib_model_name": "native_short_fib_context_v1",
        "fib_model_version": "0.1",
        "published_generation_attempt_id": attempt_id,
        "previous_map_id": None,
        "previous_map_cycle_id": None,
        "map_cycle_id": None,
        "market_snapshot_ts_utc": None,
        "published_at_utc": published_at_utc,
        "anchor_low_ts_utc": T0,
        "anchor_low_price": Decimal("9000"),
        "anchor_high_ts_utc": T1,
        "anchor_high_price": Decimal("11000"),
        "retrace_ratio": None,
        "retrace_price": None,
        "fib_ratios_json": "[]",
        "target_levels_json": "[]",
        "invalidation_price": Decimal("8500"),
        "invalidation_rule": "CLOSE_BELOW_ANCHOR_LOW",
        "source_primary_candle_ts_utc": source_primary_candle_ts_utc,
        "source_support_candle_ts_utc": source_support_candle_ts_utc,
        "source_primary_ref": "ref",
        "source_support_ref": "ref",
        "source_primary_candle_count": 100,
        "source_support_candle_count": 100,
        "map_payload_json": "{}",
    }


def test_fetch_scope_rows_preserves_duplicates() -> None:
    conn = _FakeConn(scope_rows=[_scope_row(scope_id=1), _scope_row(scope_id=2)])
    rows = report_mod.fetch_scope_rows(conn, KEY)
    assert len(rows) == 2
    assert not any(sql.startswith("INSERT") or sql.startswith("UPDATE") or sql.startswith("DELETE") for sql, _ in conn.executions)


def test_fetch_maps_for_scope_tolerates_null_source_counts() -> None:
    row = _map_row_dict()
    row["source_primary_candle_count"] = None
    conn = _FakeConn(map_rows=[row])
    maps = report_mod.fetch_maps_for_scope(conn, KEY)
    assert len(maps) == 1
    assert maps[0].source_primary_candle_count is None


def test_fetch_latest_closed_candle_ts_returns_max() -> None:
    conn = _FakeConn(
        candle_rows=[
            {"venue": "bitvavo", "symbol": "BTC", "interval_code": "4h", "close_ts_utc": T1},
            {"venue": "bitvavo", "symbol": "BTC", "interval_code": "4h", "close_ts_utc": T2},
        ]
    )
    latest = report_mod.fetch_latest_closed_candle_ts(
        conn, venue="bitvavo", symbol="BTC", interval_code="4h"
    )
    assert latest == T2


def test_generate_report_for_symbol_full_healthy_wiring() -> None:
    conn = _FakeConn(
        scope_rows=[_scope_row()],
        map_rows=[_map_row_dict()],
        generation_event_rows=[
            {
                "generation_event_id": 1,
                "venue": KEY.venue,
                "symbol": KEY.symbol,
                "quote_currency": KEY.quote_currency,
                "fib_trading_horizon": KEY.fib_trading_horizon,
                "primary_interval": KEY.primary_interval,
                "supporting_interval": KEY.supporting_interval,
                "generation_attempt_id": "attempt-1",
                "event_type": "ATTEMPT_STARTED",
                "event_ts_utc": T1,
                "reason_code": None,
                "map_id": None,
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
            },
            {
                "generation_event_id": 2,
                "venue": KEY.venue,
                "symbol": KEY.symbol,
                "quote_currency": KEY.quote_currency,
                "fib_trading_horizon": KEY.fib_trading_horizon,
                "primary_interval": KEY.primary_interval,
                "supporting_interval": KEY.supporting_interval,
                "generation_attempt_id": "attempt-1",
                "event_type": "PUBLISHED",
                "event_ts_utc": T1,
                "reason_code": None,
                "map_id": 9001,
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
            },
        ],
        lifecycle_event_rows=[
            {
                "lifecycle_event_id": 1,
                "map_id": 9001,
                "lifecycle_event_type": "ACTIVATED",
                "event_ts_utc": T2,
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
        ],
        candle_rows=[
            {"venue": "bitvavo", "symbol": "BTC", "interval_code": "4h", "close_ts_utc": T1},
            {"venue": "bitvavo", "symbol": "BTC", "interval_code": "1h", "close_ts_utc": T1},
        ],
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


# ---------------------------------------------------------------------------
# CLI: STARTED/RESULT/FINISHED, ordering, no writes
# ---------------------------------------------------------------------------


def test_cli_emits_started_result_finished_in_sorted_order(monkeypatch: pytest.MonkeyPatch) -> None:
    btc_conn = _FakeConn(scope_rows=[_scope_row()])
    eth_key_row = _scope_row()
    eth_key_row["symbol"] = "ETH"
    eth_conn = _FakeConn(scope_rows=[eth_key_row])

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
    conn = _FakeConn(scope_rows=[_scope_row()])
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

MODULE_PATHS = [
    "src/reporting/native_short_map_ledger_health_report_v1.py",
    "src/reporting/run_native_short_map_ledger_health_report_v1.py",
]

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
)

# The only market_data dependency this lane may take: the shared, DB-free
# lifecycle contract (dataclasses/enums + the pure projection function). It
# is not a market-data producer/acquisition module.
ALLOWED_MARKET_DATA_IMPORT = "src.market_data.native_short_map_lifecycle_v1"

THIS_LANE_MODULES = {
    "src.reporting.native_short_map_ledger_health_report_v1",
    "src.reporting.run_native_short_map_ledger_health_report_v1",
}


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
def test_market_data_dependency_is_limited_to_lifecycle_contract(rel_path: str) -> None:
    """The only src.market_data import allowed is the DB-free lifecycle contract."""
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
                assert name == ALLOWED_MARKET_DATA_IMPORT, (
                    f"{rel_path} imports disallowed market_data module {name}"
                )


def test_lifecycle_contract_module_has_no_db_access() -> None:
    """The one shared market_data dependency must stay a pure, DB-free contract."""
    root = Path(__file__).parent.parent
    src = (root / "src/market_data/native_short_map_lifecycle_v1.py").read_text()
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
