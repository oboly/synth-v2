from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data.native_short_fib_context_v1 import Candle
from src.market_data.native_short_map_level_status_v1 import (
    NativeShortMapLevelRole,
    NativeShortMapLevelSide,
    NativeShortMapLevelState,
    REASON_PRIMARY_CLOSE_PASSED_LEVEL,
    REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
)
from src.market_data.native_short_map_level_target_event_v1 import (
    LEGACY_UNAVAILABLE,
    NativeShortMapLevelTargetEvent,
    NativeShortMapLevelTargetEventPersistenceError,
    NativeShortMapLevelTargetEventType,
    find_first_causal_passed_candle,
    find_first_causal_reached_candle,
    is_map_target_event_coverage_eligible,
    project_level_target_state_from_event_types,
    project_level_target_state_from_events,
    serialize_native_short_map_level_target_event,
    validate_native_short_map_level_target_event,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapRecord, NativeShortMapScopeKey

MODULE_PATH = Path("src/market_data/native_short_map_level_target_event_v1.py")
MIGRATION_PATH = Path("db/migrations/20260731_native_short_map_level_target_event_v1.sql")
_AS_OF = datetime(2026, 7, 31, 4, 0, tzinfo=UTC)


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


def _map_record(*, map_id: int = 42, published_at_utc: datetime | None = None) -> NativeShortMapRecord:
    return NativeShortMapRecord(
        map_id=map_id,
        key=_key(),
        published_at_utc=published_at_utc or (_AS_OF - timedelta(days=2)),
        structure_hash="a" * 64,
        generator_name="native_short_map_materializer_v1",
        generator_version="0.1",
        fib_model_name="fib_v1",
        fib_model_version="0.1",
        published_generation_attempt_id="attempt-1",
        map_cycle_id="cycle-A",
        anchor_high_ts_utc=_AS_OF - timedelta(days=1),
        anchor_high_price=Decimal("10.0"),
        fib_ratios_json='{"ext_1_272": "10.5", "ext_1_618": "11.2", "ext_2_000": "12.0"}',
    )


def _event(
    *,
    event_type: NativeShortMapLevelTargetEventType = NativeShortMapLevelTargetEventType.REACHED,
    causal_ts: datetime = _AS_OF,
    high: str | None = "10.6",
    close: str | None = None,
    reason_code: str | None = None,
) -> NativeShortMapLevelTargetEvent:
    if reason_code is None:
        reason_code = (
            REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE
            if event_type == NativeShortMapLevelTargetEventType.REACHED
            else REASON_PRIMARY_CLOSE_PASSED_LEVEL
        )
    return NativeShortMapLevelTargetEvent(
        key=_key(),
        map_id=42,
        map_cycle_id="cycle-A",
        canonical_map_level_role=NativeShortMapLevelRole.SELL_EXT_1_272,
        side=NativeShortMapLevelSide.SELL,
        canonical_unrounded_price=Decimal("10.5"),
        target_event_type=event_type,
        causal_candle_close_ts_utc=causal_ts,
        causal_candle_high_price=Decimal(high) if high is not None else None,
        causal_candle_close_price=Decimal(close) if close is not None else None,
        effective_at_utc=causal_ts,
        reason_code=reason_code,
        writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
        writer_name="test-writer",
        writer_version="0.1",
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_reached_event_requires_high_price_and_matching_reason() -> None:
    with pytest.raises(NativeShortMapLevelTargetEventPersistenceError):
        _event(event_type=NativeShortMapLevelTargetEventType.REACHED, high=None)


def test_passed_event_requires_close_price_and_matching_reason() -> None:
    with pytest.raises(NativeShortMapLevelTargetEventPersistenceError):
        NativeShortMapLevelTargetEvent(
            key=_key(),
            map_id=42,
            map_cycle_id="cycle-A",
            canonical_map_level_role=NativeShortMapLevelRole.SELL_EXT_1_272,
            side=NativeShortMapLevelSide.SELL,
            canonical_unrounded_price=Decimal("10.5"),
            target_event_type=NativeShortMapLevelTargetEventType.PASSED,
            causal_candle_close_ts_utc=_AS_OF,
            causal_candle_high_price=None,
            causal_candle_close_price=None,
            effective_at_utc=_AS_OF,
            reason_code=REASON_PRIMARY_CLOSE_PASSED_LEVEL,
            writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
            writer_name="w",
            writer_version="0.1",
        )


def test_reason_code_must_match_event_type() -> None:
    with pytest.raises(NativeShortMapLevelTargetEventPersistenceError):
        _event(
            event_type=NativeShortMapLevelTargetEventType.REACHED,
            reason_code=REASON_PRIMARY_CLOSE_PASSED_LEVEL,
        )


def test_effective_at_must_equal_causal_candle_close() -> None:
    event = _event()
    with pytest.raises(NativeShortMapLevelTargetEventPersistenceError):
        validate_native_short_map_level_target_event(
            NativeShortMapLevelTargetEvent(
                **{**event.__dict__, "effective_at_utc": event.effective_at_utc + timedelta(minutes=1)}
            )
        )


def test_effective_at_naive_datetime_rejected() -> None:
    event = _event()
    with pytest.raises(NativeShortMapLevelTargetEventPersistenceError):
        validate_native_short_map_level_target_event(
            NativeShortMapLevelTargetEvent(
                **{
                    **event.__dict__,
                    "effective_at_utc": event.effective_at_utc.replace(tzinfo=None),
                    "causal_candle_close_ts_utc": event.causal_candle_close_ts_utc.replace(tzinfo=None),
                }
            )
        )


def test_non_sell_side_is_rejected() -> None:
    with pytest.raises(NativeShortMapLevelTargetEventPersistenceError):
        NativeShortMapLevelTargetEvent(
            key=_key(),
            map_id=42,
            map_cycle_id="cycle-A",
            canonical_map_level_role=NativeShortMapLevelRole.SELL_EXT_1_272,
            side="BUY",
            canonical_unrounded_price=Decimal("10.5"),
            target_event_type=NativeShortMapLevelTargetEventType.REACHED,
            causal_candle_close_ts_utc=_AS_OF,
            causal_candle_high_price=Decimal("10.6"),
            causal_candle_close_price=None,
            effective_at_utc=_AS_OF,
            reason_code=REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
            writer_invocation_uuid="00000000-0000-4000-8000-000000000001",
            writer_name="w",
            writer_version="0.1",
        )


def test_serialize_produces_db_ready_dict() -> None:
    event = _event()
    payload = serialize_native_short_map_level_target_event(event)
    assert payload["target_event_type"] == "REACHED"
    assert payload["canonical_unrounded_price"] == "10.5"
    assert payload["reason_code"] == REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE
    assert payload["same_candle_reached_skipped"] == 0


# ---------------------------------------------------------------------------
# Causal candle discovery
# ---------------------------------------------------------------------------


def test_find_first_causal_reached_candle_picks_earliest_touch() -> None:
    candles = [
        _candle(close_ts_utc=_AS_OF, high="9.0", close="9.0"),
        _candle(close_ts_utc=_AS_OF + timedelta(hours=4), high="10.6", close="10.0"),
        _candle(close_ts_utc=_AS_OF + timedelta(hours=8), high="11.0", close="10.7"),
    ]
    found = find_first_causal_reached_candle(Decimal("10.5"), candles)
    assert found is not None
    assert found.close_ts_utc == _AS_OF + timedelta(hours=4)


def test_find_first_causal_passed_candle_picks_earliest_close_above() -> None:
    candles = [
        _candle(close_ts_utc=_AS_OF, high="10.6", close="10.0"),
        _candle(close_ts_utc=_AS_OF + timedelta(hours=4), high="10.7", close="10.55"),
        _candle(close_ts_utc=_AS_OF + timedelta(hours=8), high="10.9", close="10.4"),
    ]
    found = find_first_causal_passed_candle(Decimal("10.5"), candles)
    assert found is not None
    assert found.close_ts_utc == _AS_OF + timedelta(hours=4)


def test_find_first_causal_candle_returns_none_when_absent() -> None:
    candles = [_candle(close_ts_utc=_AS_OF, high="9.0", close="8.0")]
    assert find_first_causal_reached_candle(Decimal("10.5"), candles) is None
    assert find_first_causal_passed_candle(Decimal("10.5"), candles) is None


# ---------------------------------------------------------------------------
# Coverage watermark boundary
# ---------------------------------------------------------------------------


def test_map_published_before_watermark_is_not_covered() -> None:
    record = _map_record(published_at_utc=_AS_OF - timedelta(days=10))
    assert not is_map_target_event_coverage_eligible(record, coverage_watermark_utc=_AS_OF)


def test_map_published_at_or_after_watermark_is_covered() -> None:
    record = _map_record(published_at_utc=_AS_OF)
    assert is_map_target_event_coverage_eligible(record, coverage_watermark_utc=_AS_OF)
    later = _map_record(published_at_utc=_AS_OF + timedelta(seconds=1))
    assert is_map_target_event_coverage_eligible(later, coverage_watermark_utc=_AS_OF)


# ---------------------------------------------------------------------------
# Reducer determinism / fail-closed semantics
# ---------------------------------------------------------------------------


def test_reducer_uncovered_level_is_legacy_unavailable_never_active() -> None:
    state = project_level_target_state_from_event_types([], covered=False)
    assert state == LEGACY_UNAVAILABLE


def test_reducer_covered_no_events_is_active() -> None:
    state = project_level_target_state_from_event_types([], covered=True)
    assert state == NativeShortMapLevelState.ACTIVE


def test_reducer_covered_with_reached_only_is_reached() -> None:
    state = project_level_target_state_from_event_types(
        [NativeShortMapLevelTargetEventType.REACHED], covered=True
    )
    assert state == NativeShortMapLevelState.REACHED


def test_reducer_covered_with_passed_is_passed_even_with_reached() -> None:
    state = project_level_target_state_from_event_types(
        [NativeShortMapLevelTargetEventType.REACHED, NativeShortMapLevelTargetEventType.PASSED],
        covered=True,
    )
    assert state == NativeShortMapLevelState.PASSED


def test_reducer_from_events_matches_reducer_from_types() -> None:
    events = [
        _event(event_type=NativeShortMapLevelTargetEventType.REACHED),
        _event(
            event_type=NativeShortMapLevelTargetEventType.PASSED,
            causal_ts=_AS_OF + timedelta(hours=4),
            high=None,
            close="10.7",
        ),
    ]
    assert project_level_target_state_from_events(events, covered=True) == NativeShortMapLevelState.PASSED
    assert project_level_target_state_from_events((), covered=True) == NativeShortMapLevelState.ACTIVE


# ---------------------------------------------------------------------------
# Migration static checks
# ---------------------------------------------------------------------------


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_creates_append_only_event_table_and_view() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_v1" in sql
    assert "CREATE OR REPLACE VIEW native_short_map_level_target_event_current_state_v1" in sql


def test_migration_identity_excludes_free_text_symbol_matching() -> None:
    sql = _sql()
    identity_block = sql.split("UNIQUE KEY uq_native_short_map_level_target_event_v1_identity", 1)[1].split(
        ")", 1
    )[0]
    assert "map_id" in identity_block
    assert "canonical_map_level_role" in identity_block
    assert "canonical_unrounded_price" in identity_block
    assert "target_event_type" in identity_block
    assert "symbol" not in identity_block


def test_migration_enforces_effective_at_equals_causal_candle() -> None:
    sql = _sql()
    assert "CHECK (effective_at_utc = causal_candle_close_ts_utc)" in sql


def test_migration_has_map_foreign_key_scoping_events_to_exact_map() -> None:
    sql = _sql()
    assert "CONSTRAINT fk_native_short_map_level_target_event_v1_map" in sql
    assert "REFERENCES native_short_map_v1 (map_id)" in sql


def test_migration_no_update_trigger_or_on_update_for_recorded_at() -> None:
    sql = _sql()
    table_block = sql.split(
        "CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_v1", 1
    )[1].split("CREATE OR REPLACE VIEW", 1)[0]
    assert "recorded_at_utc" in table_block
    assert "ON UPDATE" not in table_block


def test_market_data_contract_module_stays_market_only() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
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
