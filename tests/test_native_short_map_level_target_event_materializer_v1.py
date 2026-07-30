from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.market_data.native_short_fib_context_v1 import Candle
from src.market_data.native_short_map_level_status_v1 import NativeShortMapLevelRole
from src.market_data.native_short_map_level_target_event_materializer_v1 import (
    MAP_NOT_COVERED,
    NOT_ACTIVE_EVALUATION,
    build_new_target_events_for_role,
    materialize_native_short_map_level_target_events_for_scope,
)
from src.market_data.native_short_map_level_target_event_v1 import NativeShortMapLevelTargetEventType
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_writer_provenance_v1 import build_explicit_test_provenance
from tests.writer_auth_support import make_test_authorization

_AS_OF = datetime(2026, 7, 31, 4, 0, tzinfo=UTC)
_PROVENANCE = build_explicit_test_provenance()
_NS_AUTH = make_test_authorization("native_short_4h_chain")


def _key() -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(
        venue="bitvavo",
        symbol="BTC",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def _candle(*, close_ts_utc: datetime, high: str, close: str) -> Candle:
    return Candle(
        close_ts_utc=close_ts_utc,
        open_price=Decimal(close),
        high_price=Decimal(high),
        low_price=Decimal(close),
        close_price=Decimal(close),
    )


# ---------------------------------------------------------------------------
# Pure: build_new_target_events_for_role
# ---------------------------------------------------------------------------


def test_first_reached_transition_appends_exactly_one_event() -> None:
    candles = [_candle(close_ts_utc=_AS_OF, high="10.6", close="10.0")]
    events = build_new_target_events_for_role(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        role=NativeShortMapLevelRole.SELL_EXT_1_272,
        level_price=Decimal("10.5"),
        eligible_candles=tuple(candles),
        already_recorded_types=set(),
        writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
    )
    assert len(events) == 1
    assert events[0].target_event_type == NativeShortMapLevelTargetEventType.REACHED
    assert events[0].causal_candle_close_ts_utc == _AS_OF
    assert events[0].effective_at_utc == _AS_OF


def test_first_passed_transition_after_reached_appends_exactly_one_event() -> None:
    reached_ts = _AS_OF
    passed_ts = _AS_OF + timedelta(hours=4)
    candles = [
        _candle(close_ts_utc=reached_ts, high="10.6", close="10.0"),
        _candle(close_ts_utc=passed_ts, high="10.8", close="10.7"),
    ]
    events = build_new_target_events_for_role(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        role=NativeShortMapLevelRole.SELL_EXT_1_272,
        level_price=Decimal("10.5"),
        eligible_candles=tuple(candles),
        already_recorded_types={NativeShortMapLevelTargetEventType.REACHED},
        writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
    )
    assert len(events) == 1
    assert events[0].target_event_type == NativeShortMapLevelTargetEventType.PASSED
    assert events[0].causal_candle_close_ts_utc == passed_ts
    assert events[0].same_candle_reached_skipped is False


def test_same_candle_reach_and_pass_appends_only_passed_with_flag() -> None:
    candle_ts = _AS_OF
    candles = [_candle(close_ts_utc=candle_ts, high="10.8", close="10.7")]
    events = build_new_target_events_for_role(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        role=NativeShortMapLevelRole.SELL_EXT_1_272,
        level_price=Decimal("10.5"),
        eligible_candles=tuple(candles),
        already_recorded_types=set(),
        writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
    )
    assert len(events) == 1
    assert events[0].target_event_type == NativeShortMapLevelTargetEventType.PASSED
    assert events[0].same_candle_reached_skipped is True


def test_reprocessing_identical_candles_is_idempotent_no_new_events() -> None:
    candles = [_candle(close_ts_utc=_AS_OF, high="10.6", close="10.0")]
    first_pass = build_new_target_events_for_role(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        role=NativeShortMapLevelRole.SELL_EXT_1_272,
        level_price=Decimal("10.5"),
        eligible_candles=tuple(candles),
        already_recorded_types=set(),
        writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
    )
    assert len(first_pass) == 1
    already_recorded = {NativeShortMapLevelTargetEventType.REACHED}
    second_pass = build_new_target_events_for_role(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        role=NativeShortMapLevelRole.SELL_EXT_1_272,
        level_price=Decimal("10.5"),
        eligible_candles=tuple(candles),
        already_recorded_types=already_recorded,
        writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
    )
    assert second_pass == ()


def test_active_state_produces_no_events() -> None:
    candles = [_candle(close_ts_utc=_AS_OF, high="9.0", close="8.0")]
    events = build_new_target_events_for_role(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        role=NativeShortMapLevelRole.SELL_EXT_1_272,
        level_price=Decimal("10.5"),
        eligible_candles=tuple(candles),
        already_recorded_types=set(),
        writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
    )
    assert events == ()


# ---------------------------------------------------------------------------
# Orchestrator (fake DB connection)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, script: dict) -> None:
        self._script = script
        self._result: object = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple = ()) -> None:
        if "FROM native_short_scope_status_v1" in sql:
            self._result = self._script.get("scope_status")
        elif "FROM native_short_map_v1" in sql:
            self._result = self._script.get("map")
        elif "FROM obs_market_candle" in sql:
            self._result = self._script.get("candles", [])
        elif "FROM venue_market" in sql:
            self._result = []
        elif "FROM native_short_map_level_target_event_v1" in sql:
            self._result = self._script.get("existing_events", [])
        elif sql.strip().startswith("INSERT INTO native_short_map_level_target_event_v1"):
            identity = (
                params["map_id"],
                params["canonical_map_level_role"],
                params["side"],
                params["canonical_unrounded_price"],
                params["target_event_type"],
            )
            inserted = self._script.setdefault("inserted_identities", set())
            if identity in inserted:
                from pymysql.err import IntegrityError

                raise IntegrityError(1062, "Duplicate entry")
            inserted.add(identity)
            self._script.setdefault("inserted_rows", []).append(params)
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql[:80]}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []

    @property
    def rowcount(self) -> int:
        return 1


class _FakeConn:
    def __init__(self, script: dict) -> None:
        self.script = script

    def cursor(self):
        return _FakeCursor(self.script)


def _scope_status_row(**overrides) -> dict:
    row = {
        "scope_support_state": "SUPPORTED",
        "scope_status_code": "CURRENT_EVALUATION",
        "scope_status_reason_code": None,
        "map_lifecycle_state": "MAP_ACTIVE",
        "observation_freshness_state": "OBSERVATION_CURRENT",
        "source_freshness_state": "SOURCE_CURRENT",
        "actionability_state": "ACTIONABLE_ACTIVE_MAP",
        "current_map_id": 42,
        "current_map_cycle_id": "cycle-A",
        "current_map_published_at_utc": _AS_OF - timedelta(days=2),
        "current_map_structure_hash": "a" * 64,
        "latest_generation_event_id": None,
        "latest_lifecycle_event_id": None,
        "latest_observation_id": None,
        "latest_run_id": None,
        "latest_observed_at_utc": None,
        "next_expected_evaluation_at_utc": None,
        "observation_overdue_after_utc": None,
        "primary_latest_candle_ts_utc": None,
        "supporting_latest_candle_ts_utc": None,
        "primary_source_freshness_limit_seconds": 43200,
        "supporting_source_freshness_limit_seconds": 10800,
        "cadence_contract_version": "native_short_cadence_v1",
        "projection_as_of_utc": _AS_OF,
        "status_payload_json": None,
        "rebuilt_at_utc": _AS_OF,
    }
    row.update(overrides)
    return row


def _map_row(**overrides) -> dict:
    row = {
        "map_id": 42,
        "structure_hash": "a" * 64,
        "generator_name": "native_short_map_materializer_v1",
        "generator_version": "0.1",
        "fib_model_name": "fib_v1",
        "fib_model_version": "0.1",
        "published_generation_attempt_id": "attempt-1",
        "previous_map_id": None,
        "previous_map_cycle_id": None,
        "map_cycle_id": "cycle-A",
        "market_snapshot_ts_utc": None,
        "published_at_utc": _AS_OF - timedelta(days=2),
        "anchor_low_ts_utc": None,
        "anchor_low_price": None,
        "anchor_high_ts_utc": _AS_OF - timedelta(days=1),
        "anchor_high_price": Decimal("10.0"),
        "retrace_ratio": None,
        "retrace_price": None,
        "fib_ratios_json": '{"ext_1_272": "10.5", "ext_1_618": "11.2", "ext_2_000": "12.0"}',
        "target_levels_json": "[]",
        "invalidation_price": None,
        "invalidation_rule": "",
        "source_primary_candle_ts_utc": None,
        "source_support_candle_ts_utc": None,
        "source_primary_ref": "",
        "source_support_ref": "",
        "source_primary_candle_count": 1,
        "source_support_candle_count": 1,
        "map_payload_json": "{}",
    }
    row.update(overrides)
    return row


def _candle_row(*, close_ts_utc: datetime, high: str, close: str) -> dict:
    return {
        "close_ts_utc": close_ts_utc,
        "open_price": close,
        "high_price": high,
        "low_price": close,
        "close_price": close,
    }


def test_orchestrator_appends_reached_event_for_covered_map() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(),
            "map": _map_row(),
            "candles": [_candle_row(close_ts_utc=_AS_OF - timedelta(hours=4), high="10.6", close="10.0")],
            "existing_events": [],
        }
    )
    outcome = materialize_native_short_map_level_target_events_for_scope(
        conn,
        key=_key(),
        target_event_coverage_watermark_utc=_AS_OF - timedelta(days=3),
        provenance=_PROVENANCE,
        authorization=_NS_AUTH,
    )
    assert outcome.coverage_eligible is True
    assert outcome.skip_reason is None
    assert outcome.events_appended == 1
    assert outcome.level_state_by_role["SELL_EXT_1_272"] == "REACHED"
    assert outcome.level_state_by_role["SELL_EXT_1_618"] == "ACTIVE"


def test_orchestrator_blocks_map_published_before_watermark() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(),
            "map": _map_row(),
            "candles": [_candle_row(close_ts_utc=_AS_OF - timedelta(hours=4), high="10.6", close="10.0")],
            "existing_events": [],
        }
    )
    outcome = materialize_native_short_map_level_target_events_for_scope(
        conn,
        key=_key(),
        target_event_coverage_watermark_utc=_AS_OF + timedelta(days=1),
        provenance=_PROVENANCE,
        authorization=_NS_AUTH,
    )
    assert outcome.coverage_eligible is False
    assert outcome.skip_reason == MAP_NOT_COVERED
    assert outcome.events_appended == 0
    assert all(state == "LEGACY_UNAVAILABLE" for state in outcome.level_state_by_role.values())


def test_orchestrator_skips_non_active_evaluation_branch() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(
                scope_status_code="MAP_COMPLETED",
                map_lifecycle_state="MAP_COMPLETED",
                actionability_state="TERMINAL_MAP",
            ),
        }
    )
    outcome = materialize_native_short_map_level_target_events_for_scope(
        conn,
        key=_key(),
        target_event_coverage_watermark_utc=_AS_OF - timedelta(days=3),
        provenance=_PROVENANCE,
        authorization=_NS_AUTH,
    )
    assert outcome.skip_reason == NOT_ACTIVE_EVALUATION
    assert outcome.events_appended == 0


def test_orchestrator_reprocessing_identical_input_is_idempotent() -> None:
    script = {
        "scope_status": _scope_status_row(),
        "map": _map_row(),
        "candles": [_candle_row(close_ts_utc=_AS_OF - timedelta(hours=4), high="10.6", close="10.0")],
        "existing_events": [],
    }
    conn = _FakeConn(script)
    first = materialize_native_short_map_level_target_events_for_scope(
        conn,
        key=_key(),
        target_event_coverage_watermark_utc=_AS_OF - timedelta(days=3),
        provenance=_PROVENANCE,
        authorization=_NS_AUTH,
    )
    assert first.events_appended == 1

    # Simulate a second run reading back the row it just wrote.
    script["existing_events"] = [
        {
            "map_id": 42,
            "map_cycle_id": "cycle-A",
            "canonical_map_level_role": "SELL_EXT_1_272",
            "side": "SELL",
            "canonical_unrounded_price": Decimal("10.5"),
            "target_event_type": "REACHED",
            "causal_candle_close_ts_utc": _AS_OF - timedelta(hours=4),
            "causal_candle_high_price": Decimal("10.6"),
            "causal_candle_close_price": None,
            "effective_at_utc": _AS_OF - timedelta(hours=4),
            "recorded_at_utc": _AS_OF,
            "reason_code": "PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE",
            "writer_name": "native_short_map_level_target_event_materializer_v1",
            "writer_version": "0.1",
            "writer_invocation_uuid": _PROVENANCE.invocation_uuid,
            "same_candle_reached_skipped": 0,
            "target_event_id": 1,
        }
    ]
    second = materialize_native_short_map_level_target_events_for_scope(
        conn,
        key=_key(),
        target_event_coverage_watermark_utc=_AS_OF - timedelta(days=3),
        provenance=_PROVENANCE,
        authorization=_NS_AUTH,
    )
    assert second.events_appended == 0
    assert second.level_state_by_role["SELL_EXT_1_272"] == "REACHED"


def test_orchestrator_successor_map_does_not_inherit_predecessor_events() -> None:
    script = {
        "scope_status": _scope_status_row(current_map_id=99, current_map_cycle_id="cycle-B"),
        "map": _map_row(map_id=99, map_cycle_id="cycle-B", published_at_utc=_AS_OF - timedelta(hours=1)),
        "candles": [],
        "existing_events": [],
    }
    conn = _FakeConn(script)
    outcome = materialize_native_short_map_level_target_events_for_scope(
        conn,
        key=_key(),
        target_event_coverage_watermark_utc=_AS_OF - timedelta(days=3),
        provenance=_PROVENANCE,
        authorization=_NS_AUTH,
    )
    # Fresh successor map with no candles yet: every level ACTIVE, no events,
    # regardless of any predecessor map's history (map_id=42 above never
    # appears in this scope's query at all -- events are always looked up by
    # the exact current map_id).
    assert outcome.map_id == 99
    assert outcome.events_appended == 0
    assert all(state == "ACTIVE" for state in outcome.level_state_by_role.values())


def test_insert_duplicate_identity_is_idempotent_and_never_updates() -> None:
    from src.market_data.native_short_map_level_target_event_v1 import (
        NativeShortMapLevelTargetEvent,
        NativeShortMapLevelTargetEventType,
        insert_native_short_map_level_target_events,
    )
    from src.market_data.native_short_map_level_status_v1 import NativeShortMapLevelRole, NativeShortMapLevelSide

    conn = _FakeConn({})
    event = NativeShortMapLevelTargetEvent(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        canonical_map_level_role=NativeShortMapLevelRole.SELL_EXT_1_272,
        side=NativeShortMapLevelSide.SELL,
        canonical_unrounded_price=Decimal("10.5"),
        target_event_type=NativeShortMapLevelTargetEventType.REACHED,
        causal_candle_close_ts_utc=_AS_OF,
        causal_candle_high_price=Decimal("10.6"),
        causal_candle_close_price=None,
        effective_at_utc=_AS_OF,
        reason_code="PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE",
        writer_invocation_uuid=_PROVENANCE.invocation_uuid,
        writer_name="w",
        writer_version="0.1",
    )
    first = insert_native_short_map_level_target_events(
        conn, events=[event], provenance=_PROVENANCE, authorization=_NS_AUTH
    )
    assert first == 1
    # A later attempt to insert the identical canonical identity is rejected
    # by the database unique constraint and treated as an idempotent no-op --
    # never a mutation, and never raised as an error to the caller.
    second = insert_native_short_map_level_target_events(
        conn, events=[event], provenance=_PROVENANCE, authorization=_NS_AUTH
    )
    assert second == 0
    assert len(conn.script["inserted_rows"]) == 1
