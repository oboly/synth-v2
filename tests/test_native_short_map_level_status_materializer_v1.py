from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data.native_short_fib_context_v1 import Candle
from src.market_data.native_short_map_level_status_materializer_v1 import (
    ACTIVE_EVALUATION,
    BLOCKED,
    GEOMETRY_INVALID,
    NO_CURRENT_MAP,
    PROJECTION_INVALID,
    PROJECTION_MISSING,
    TERMINAL_COMPLETED,
    TERMINAL_HISTORICAL,
    NativeShortMapLevelStatusMaterializerError,
    build_level_status_rows,
    classify_level_state,
    extract_v1_sell_geometry,
    materialize_native_short_map_level_status_for_scope,
    select_eligible_primary_candles,
    select_gate_decision,
)
from src.market_data.native_short_map_level_status_v1 import (
    NativeShortMapLevelEvaluationReference,
    NativeShortMapLevelRole,
    NativeShortMapLevelState,
    REASON_MAP_COMPLETED,
    REASON_MAP_EXPIRED,
    REASON_MAP_INVALIDATED,
    REASON_NO_PRIMARY_HIGH_REACHED_LEVEL,
    REASON_PRIMARY_CLOSE_PASSED_LEVEL,
    REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapRecord, NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import (
    NativeShortObservationFreshnessState,
    NativeShortScopeActionabilityState,
    NativeShortScopeMapLifecycleState,
    NativeShortScopeSourceState,
    NativeShortScopeStatusCode,
    NativeShortScopeStatusRecord,
)
from src.market_rules.price_tick_normalization_v1 import (
    NORM_STATUS_APPLIED,
    NORM_STATUS_MISSING,
    TICK_RULE_SOURCE_MISSING,
)

MODULE_PATH = Path("src/market_data/native_short_map_level_status_materializer_v1.py")

_AS_OF = datetime(2026, 7, 10, 4, 0, tzinfo=UTC)
_REBUILT_AT = datetime(2026, 7, 10, 4, 0, 5, tzinfo=UTC)


def _source(path: Path = MODULE_PATH) -> str:
    return path.read_text(encoding="utf-8")


def _key(symbol: str = "NEAR") -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(
        venue="bitvavo",
        symbol=symbol,
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def _projection(
    *,
    scope_status_code: NativeShortScopeStatusCode = NativeShortScopeStatusCode.CURRENT_EVALUATION,
    map_lifecycle_state: NativeShortScopeMapLifecycleState = NativeShortScopeMapLifecycleState.MAP_ACTIVE,
    actionability_state: NativeShortScopeActionabilityState = NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP,
    observation_freshness_state: NativeShortObservationFreshnessState = NativeShortObservationFreshnessState.OBSERVATION_CURRENT,
    source_freshness_state: NativeShortScopeSourceState | None = NativeShortScopeSourceState.SOURCE_CURRENT,
    current_map_id: int | None = 42,
    current_map_cycle_id: str | None = "NEAR|SHORT|4h|2026-07-01T00:00:00+00:00|2026-07-02T00:00:00+00:00",
    cadence_contract_version: str | None = "native_short_cadence_v1",
    primary_source_freshness_limit_seconds: int | None = 43200,
    supporting_source_freshness_limit_seconds: int | None = 10800,
    scope_status_reason_code: str | None = None,
) -> NativeShortScopeStatusRecord:
    return NativeShortScopeStatusRecord(
        key=_key(),
        scope_support_state="SUPPORTED",
        scope_status_code=scope_status_code,
        map_lifecycle_state=map_lifecycle_state,
        observation_freshness_state=observation_freshness_state,
        actionability_state=actionability_state,
        projection_as_of_utc=_AS_OF,
        rebuilt_at_utc=_AS_OF,
        source_freshness_state=source_freshness_state,
        primary_source_freshness_limit_seconds=primary_source_freshness_limit_seconds,
        supporting_source_freshness_limit_seconds=supporting_source_freshness_limit_seconds,
        cadence_contract_version=cadence_contract_version,
        scope_status_reason_code=scope_status_reason_code,
        current_map_id=current_map_id,
        current_map_cycle_id=current_map_cycle_id,
    )


def _config_unavailable_projection() -> NativeShortScopeStatusRecord:
    return NativeShortScopeStatusRecord(
        key=_key(),
        scope_support_state="SUPPORTED",
        scope_status_code=NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_ACTIVE,
        observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
        actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
        projection_as_of_utc=_AS_OF,
        rebuilt_at_utc=_AS_OF,
        source_freshness_state=None,
        cadence_contract_version=None,
        primary_source_freshness_limit_seconds=None,
        supporting_source_freshness_limit_seconds=None,
        scope_status_reason_code="NO_ELIGIBLE_CADENCE_CONFIG",
        current_map_id=42,
        current_map_cycle_id="NEAR|SHORT|4h|2026-07-01T00:00:00+00:00|2026-07-02T00:00:00+00:00",
    )


def _map_record(
    *,
    map_id: int = 42,
    map_cycle_id: str = "NEAR|SHORT|4h|2026-07-01T00:00:00+00:00|2026-07-02T00:00:00+00:00",
    anchor_high_ts_utc: datetime | None = _AS_OF - timedelta(days=1),
    fib_ratios_json: str | None = None,
) -> NativeShortMapRecord:
    if fib_ratios_json is None:
        fib_ratios_json = (
            '{"breakout_gate": "9.0", "ext_1_272": "10.5", "ext_1_618": "11.2", '
            '"ext_2_000": "12.0", "reload_r382": "8.0", "reload_r500": "7.5", '
            '"reload_r618": "7.0", "reload_r786": "6.5"}'
        )
    return NativeShortMapRecord(
        map_id=map_id,
        key=_key(),
        published_at_utc=_AS_OF - timedelta(days=2),
        structure_hash="a" * 64,
        generator_name="native_short_map_materializer_v1",
        generator_version="0.1",
        fib_model_name="fib_v1",
        fib_model_version="0.1",
        published_generation_attempt_id="attempt-1",
        map_cycle_id=map_cycle_id,
        anchor_high_ts_utc=anchor_high_ts_utc,
        anchor_high_price=Decimal("10.0"),
        fib_ratios_json=fib_ratios_json,
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
# select_gate_decision
# ---------------------------------------------------------------------------


def test_gate_active_evaluation_requires_all_five_conditions() -> None:
    branch, reason = select_gate_decision(_projection())
    assert branch == ACTIVE_EVALUATION
    assert reason is None


def test_gate_no_current_map_when_current_map_id_missing() -> None:
    branch, reason = select_gate_decision(_projection(current_map_id=None, current_map_cycle_id=None))
    assert (branch, reason) == (BLOCKED, NO_CURRENT_MAP)


def test_gate_no_current_map_when_cycle_id_empty() -> None:
    branch, reason = select_gate_decision(_projection(current_map_cycle_id=""))
    assert (branch, reason) == (BLOCKED, NO_CURRENT_MAP)


def test_gate_terminal_completed_requires_full_triple() -> None:
    projection = _projection(
        scope_status_code=NativeShortScopeStatusCode.MAP_COMPLETED,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_COMPLETED,
        actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
        observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CURRENT,
        source_freshness_state=NativeShortScopeSourceState.SOURCE_CURRENT,
        cadence_contract_version="native_short_cadence_v1",
    )
    assert select_gate_decision(projection) == (TERMINAL_COMPLETED, REASON_MAP_COMPLETED)


def test_gate_terminal_historical_invalidated_requires_full_triple() -> None:
    projection = _projection(
        scope_status_code=NativeShortScopeStatusCode.MAP_INVALIDATED,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_INVALIDATED,
        actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    assert select_gate_decision(projection) == (TERMINAL_HISTORICAL, REASON_MAP_INVALIDATED)


def test_gate_terminal_historical_expired_has_no_matching_scope_status_code() -> None:
    # MAP_EXPIRED has no native_short_scope_status_v1 scope_status_code
    # counterpart today, so only map_lifecycle_state + actionability gate it.
    projection = _projection(
        scope_status_code=NativeShortScopeStatusCode.OBSERVATION_OVERDUE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_EXPIRED,
        actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    assert select_gate_decision(projection) == (TERMINAL_HISTORICAL, REASON_MAP_EXPIRED)


def test_gate_inconsistent_completed_triple_fails_closed_not_fabricated() -> None:
    # map_lifecycle says COMPLETED but scope_status disagrees: must not fabricate COMPLETED.
    projection = _projection(
        scope_status_code=NativeShortScopeStatusCode.OBSERVATION_OVERDUE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_COMPLETED,
        actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    branch, reason = select_gate_decision(projection)
    assert branch == BLOCKED
    assert reason == NativeShortScopeStatusCode.OBSERVATION_OVERDUE.value


@pytest.mark.parametrize(
    "scope_status_code,actionability_state,observation_freshness_state,source_freshness_state",
    [
        (
            NativeShortScopeStatusCode.SOURCE_UNAVAILABLE,
            NativeShortScopeActionabilityState.BLOCKED_SOURCE,
            NativeShortObservationFreshnessState.OBSERVATION_CURRENT,
            NativeShortScopeSourceState.SOURCE_UNAVAILABLE,
        ),
        (
            NativeShortScopeStatusCode.SOURCE_STALE,
            NativeShortScopeActionabilityState.BLOCKED_SOURCE,
            NativeShortObservationFreshnessState.OBSERVATION_CURRENT,
            NativeShortScopeSourceState.SOURCE_STALE,
        ),
        (
            NativeShortScopeStatusCode.SCOPE_RECENTLY_ADDED,
            NativeShortScopeActionabilityState.BLOCKED_SCOPE,
            NativeShortObservationFreshnessState.NO_OBSERVATION,
            NativeShortScopeSourceState.SOURCE_CURRENT,
        ),
        (
            NativeShortScopeStatusCode.OBSERVATION_OVERDUE,
            NativeShortScopeActionabilityState.BLOCKED_OBSERVATION,
            NativeShortObservationFreshnessState.OBSERVATION_OVERDUE,
            NativeShortScopeSourceState.SOURCE_CURRENT,
        ),
    ],
)
def test_gate_blocked_scope_status_codes_emit_no_rows(
    scope_status_code, actionability_state, observation_freshness_state, source_freshness_state
) -> None:
    projection = _projection(
        scope_status_code=scope_status_code,
        actionability_state=actionability_state,
        observation_freshness_state=observation_freshness_state,
        source_freshness_state=source_freshness_state,
    )
    branch, reason = select_gate_decision(projection)
    assert branch == BLOCKED
    assert reason == scope_status_code.value


def test_gate_configuration_unavailable_is_distinguishable_from_source_states() -> None:
    branch, reason = select_gate_decision(_config_unavailable_projection())
    assert branch == BLOCKED
    assert reason == NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE.value
    assert reason not in {
        NativeShortScopeStatusCode.SOURCE_UNAVAILABLE.value,
        NativeShortScopeStatusCode.SOURCE_STALE.value,
        NativeShortScopeStatusCode.OBSERVATION_OVERDUE.value,
    }


# ---------------------------------------------------------------------------
# extract_v1_sell_geometry
# ---------------------------------------------------------------------------


def test_extract_geometry_returns_three_positive_decimals() -> None:
    geometry = extract_v1_sell_geometry(_map_record())
    assert geometry[NativeShortMapLevelRole.SELL_EXT_1_272] == Decimal("10.5")
    assert geometry[NativeShortMapLevelRole.SELL_EXT_1_618] == Decimal("11.2")
    assert geometry[NativeShortMapLevelRole.SELL_EXT_2_000] == Decimal("12.0")


def test_extract_geometry_fails_closed_on_missing_level() -> None:
    record = _map_record(fib_ratios_json='{"ext_1_272": "10.5", "ext_1_618": "11.2"}')
    with pytest.raises(NativeShortMapLevelStatusMaterializerError):
        extract_v1_sell_geometry(record)


def test_extract_geometry_fails_closed_on_non_positive_level() -> None:
    record = _map_record(
        fib_ratios_json='{"ext_1_272": "0", "ext_1_618": "11.2", "ext_2_000": "12.0"}'
    )
    with pytest.raises(NativeShortMapLevelStatusMaterializerError):
        extract_v1_sell_geometry(record)


def test_extract_geometry_fails_closed_on_malformed_json() -> None:
    record = _map_record(fib_ratios_json="{not json")
    with pytest.raises(NativeShortMapLevelStatusMaterializerError):
        extract_v1_sell_geometry(record)


def test_extract_geometry_fails_closed_on_missing_anchor() -> None:
    record = _map_record(anchor_high_ts_utc=None)
    with pytest.raises(NativeShortMapLevelStatusMaterializerError):
        extract_v1_sell_geometry(record)


# ---------------------------------------------------------------------------
# select_eligible_primary_candles / classify_level_state
# ---------------------------------------------------------------------------


def test_select_eligible_candles_uses_inclusive_anchor_and_as_of_bounds() -> None:
    anchor = _AS_OF - timedelta(hours=8)
    candles = [
        _candle(close_ts_utc=anchor - timedelta(hours=4), high="1", close="1"),  # before anchor
        _candle(close_ts_utc=anchor, high="1", close="1"),  # exactly at anchor
        _candle(close_ts_utc=_AS_OF, high="1", close="1"),  # exactly at as_of
        _candle(close_ts_utc=_AS_OF + timedelta(hours=4), high="1", close="1"),  # after as_of
    ]
    eligible = select_eligible_primary_candles(candles, anchor_high_ts_utc=anchor, projection_as_of_utc=_AS_OF)
    assert [c.close_ts_utc for c in eligible] == [anchor, _AS_OF]


def test_classify_active_when_no_high_reaches_level() -> None:
    candles = [_candle(close_ts_utc=_AS_OF, high="9.0", close="8.5")]
    state, reason = classify_level_state(Decimal("10.5"), candles)
    assert (state, reason) == (NativeShortMapLevelState.ACTIVE, REASON_NO_PRIMARY_HIGH_REACHED_LEVEL)


def test_classify_reached_on_touch_without_close_above() -> None:
    candles = [_candle(close_ts_utc=_AS_OF, high="10.6", close="10.4")]
    state, reason = classify_level_state(Decimal("10.5"), candles)
    assert (state, reason) == (
        NativeShortMapLevelState.REACHED,
        REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
    )


def test_classify_passed_on_closed_continuation_above() -> None:
    candles = [_candle(close_ts_utc=_AS_OF, high="10.6", close="10.6")]
    state, reason = classify_level_state(Decimal("10.5"), candles)
    assert (state, reason) == (NativeShortMapLevelState.PASSED, REASON_PRIMARY_CLOSE_PASSED_LEVEL)


def test_classify_is_monotonic_price_revert_does_not_undo_passed() -> None:
    candles = [
        _candle(close_ts_utc=_AS_OF - timedelta(hours=4), high="10.6", close="10.6"),
        _candle(close_ts_utc=_AS_OF, high="9.0", close="8.5"),  # later candle drops back below
    ]
    state, _ = classify_level_state(Decimal("10.5"), candles)
    assert state == NativeShortMapLevelState.PASSED


# ---------------------------------------------------------------------------
# build_level_status_rows
# ---------------------------------------------------------------------------


def _applied_tick_rule():
    from src.market_rules.price_tick_normalization_v1 import resolve_tick_rule_from_static

    return resolve_tick_rule_from_static("bitvavo", "BTC-EUR")


def _missing_tick_rule():
    from src.market_rules.price_tick_normalization_v1 import TickRule

    return TickRule(venue="bitvavo", market="ZZZ-EUR", tick_size=Decimal("0"), decimal_places=0, source=TICK_RULE_SOURCE_MISSING)


def test_build_active_rows_produces_exactly_three_v1_roles_once_each() -> None:
    projection = _projection()
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    candles: list[Candle] = []
    rows = build_level_status_rows(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_applied_tick_rule(),
        branch=ACTIVE_EVALUATION,
        terminal_reason_code=None,
        eligible_candles=candles,
        rebuilt_at_utc=_REBUILT_AT,
    )
    assert len(rows) == 3
    assert {row.canonical_map_level_role for row in rows} == set(NativeShortMapLevelRole)
    assert all(row.level_lifecycle_state == NativeShortMapLevelState.ACTIVE for row in rows)
    assert all(row.level_status_as_of_utc == projection.projection_as_of_utc for row in rows)


def test_build_active_rows_distinguish_reached_and_passed_per_level() -> None:
    projection = _projection()
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    # ext_1_272=10.5 passed, ext_1_618=11.2 reached (touch only), ext_2_000=12.0 active
    candles = [_candle(close_ts_utc=_AS_OF, high="11.3", close="10.6")]
    rows = build_level_status_rows(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_applied_tick_rule(),
        branch=ACTIVE_EVALUATION,
        terminal_reason_code=None,
        eligible_candles=candles,
        rebuilt_at_utc=_REBUILT_AT,
    )
    by_role = {row.canonical_map_level_role: row for row in rows}
    assert by_role[NativeShortMapLevelRole.SELL_EXT_1_272].level_lifecycle_state == NativeShortMapLevelState.PASSED
    assert by_role[NativeShortMapLevelRole.SELL_EXT_1_618].level_lifecycle_state == NativeShortMapLevelState.REACHED
    assert by_role[NativeShortMapLevelRole.SELL_EXT_2_000].level_lifecycle_state == NativeShortMapLevelState.ACTIVE


def test_build_terminal_completed_rows_are_completed_not_touch_based() -> None:
    projection = _projection(
        scope_status_code=NativeShortScopeStatusCode.MAP_COMPLETED,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_COMPLETED,
        actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    # Even with zero eligible candles (no touch evidence at all), completion
    # must still be reported: COMPLETED is a map-terminal fact, not a synonym
    # for a price touch.
    rows = build_level_status_rows(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_applied_tick_rule(),
        branch=TERMINAL_COMPLETED,
        terminal_reason_code=REASON_MAP_COMPLETED,
        eligible_candles=(),
        rebuilt_at_utc=_REBUILT_AT,
    )
    assert len(rows) == 3
    assert all(row.level_lifecycle_state == NativeShortMapLevelState.COMPLETED for row in rows)
    assert all(row.reason_code == REASON_MAP_COMPLETED for row in rows)
    assert all(
        row.evaluation_reference == NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT for row in rows
    )


def test_build_terminal_historical_rows_preserve_invalidated_reason() -> None:
    projection = _projection(
        scope_status_code=NativeShortScopeStatusCode.MAP_INVALIDATED,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_INVALIDATED,
        actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    rows = build_level_status_rows(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_applied_tick_rule(),
        branch=TERMINAL_HISTORICAL,
        terminal_reason_code=REASON_MAP_INVALIDATED,
        eligible_candles=(),
        rebuilt_at_utc=_REBUILT_AT,
    )
    assert all(row.level_lifecycle_state == NativeShortMapLevelState.HISTORICAL for row in rows)
    assert all(row.reason_code == REASON_MAP_INVALIDATED for row in rows)


def test_build_terminal_historical_rows_preserve_expired_reason() -> None:
    projection = _projection(
        scope_status_code=NativeShortScopeStatusCode.OBSERVATION_OVERDUE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_EXPIRED,
        actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    rows = build_level_status_rows(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_applied_tick_rule(),
        branch=TERMINAL_HISTORICAL,
        terminal_reason_code=REASON_MAP_EXPIRED,
        eligible_candles=(),
        rebuilt_at_utc=_REBUILT_AT,
    )
    assert all(row.reason_code == REASON_MAP_EXPIRED for row in rows)


def test_build_rows_with_missing_tick_rule_preserves_unrounded_lifecycle_semantics() -> None:
    projection = _projection()
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    candles = [_candle(close_ts_utc=_AS_OF, high="10.6", close="10.6")]  # passes ext_1_272
    rows = build_level_status_rows(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_missing_tick_rule(),
        branch=ACTIVE_EVALUATION,
        terminal_reason_code=None,
        eligible_candles=candles,
        rebuilt_at_utc=_REBUILT_AT,
    )
    by_role = {row.canonical_map_level_role: row for row in rows}
    passed_row = by_role[NativeShortMapLevelRole.SELL_EXT_1_272]
    assert passed_row.level_lifecycle_state == NativeShortMapLevelState.PASSED  # unrounded price still classifies
    assert passed_row.canonical_tick_rounded_price is None
    assert passed_row.tick_rule_status == NORM_STATUS_MISSING
    assert passed_row.tick_rule_source == TICK_RULE_SOURCE_MISSING


def test_build_rows_with_applied_tick_rule_rounds_up_for_sell() -> None:
    projection = _projection()
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    rows = build_level_status_rows(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_applied_tick_rule(),
        branch=ACTIVE_EVALUATION,
        terminal_reason_code=None,
        eligible_candles=(),
        rebuilt_at_utc=_REBUILT_AT,
    )
    by_role = {row.canonical_map_level_role: row for row in rows}
    row = by_role[NativeShortMapLevelRole.SELL_EXT_1_272]
    assert row.tick_rule_status == NORM_STATUS_APPLIED
    # BTC-EUR static precision is 1 decimal place; TARGET_SELL rounds up.
    assert row.canonical_tick_rounded_price == Decimal("10.5")


def test_build_rows_is_deterministic_for_identical_inputs() -> None:
    projection = _projection()
    map_record = _map_record()
    geometry = extract_v1_sell_geometry(map_record)
    candles = [_candle(close_ts_utc=_AS_OF, high="10.6", close="10.6")]
    kwargs = dict(
        key=_key(),
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=_applied_tick_rule(),
        branch=ACTIVE_EVALUATION,
        terminal_reason_code=None,
        eligible_candles=candles,
        rebuilt_at_utc=_REBUILT_AT,
    )
    rows_a = build_level_status_rows(**kwargs)
    rows_b = build_level_status_rows(**kwargs)
    assert rows_a == rows_b


def test_build_rows_reflects_changed_selected_map_cycle() -> None:
    projection = _projection()
    map_record_a = _map_record(map_id=42, map_cycle_id="cycle-A")
    map_record_b = _map_record(map_id=99, map_cycle_id="cycle-B")
    geometry = extract_v1_sell_geometry(map_record_a)
    rows_a = build_level_status_rows(
        key=_key(), projection=projection, map_record=map_record_a, geometry=geometry,
        tick_rule=_applied_tick_rule(), branch=ACTIVE_EVALUATION, terminal_reason_code=None,
        eligible_candles=(), rebuilt_at_utc=_REBUILT_AT,
    )
    rows_b = build_level_status_rows(
        key=_key(), projection=projection, map_record=map_record_b, geometry=geometry,
        tick_rule=_applied_tick_rule(), branch=ACTIVE_EVALUATION, terminal_reason_code=None,
        eligible_candles=(), rebuilt_at_utc=_REBUILT_AT,
    )
    assert {row.current_map_id for row in rows_a} == {42}
    assert {row.map_cycle_id for row in rows_a} == {"cycle-A"}
    assert {row.current_map_id for row in rows_b} == {99}
    assert {row.map_cycle_id for row in rows_b} == {"cycle-B"}


def test_map_record_geometry_is_never_mutated_by_row_building() -> None:
    map_record = _map_record()
    original_fib_ratios_json = map_record.fib_ratios_json
    geometry = extract_v1_sell_geometry(map_record)
    build_level_status_rows(
        key=_key(), projection=_projection(), map_record=map_record, geometry=geometry,
        tick_rule=_applied_tick_rule(), branch=ACTIVE_EVALUATION, terminal_reason_code=None,
        eligible_candles=(), rebuilt_at_utc=_REBUILT_AT,
    )
    assert map_record.fib_ratios_json == original_fib_ratios_json


# ---------------------------------------------------------------------------
# Orchestrator (fake connection, no real DB)
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
        elif sql.strip().startswith("DELETE FROM native_short_map_level_status_v1"):
            self._script.setdefault("delete_calls", 0)
            self._script["delete_calls"] += 1
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql[:80]}")

    def executemany(self, sql: str, seq) -> None:
        self._script["inserted_rows"] = list(seq)

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []

    @property
    def rowcount(self) -> int:
        return len(self._script.get("inserted_rows", []))


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
        "fib_ratios_json": (
            '{"ext_1_272": "10.5", "ext_1_618": "11.2", "ext_2_000": "12.0"}'
        ),
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


def test_orchestrator_missing_projection_deletes_and_blocks() -> None:
    conn = _FakeConn({"scope_status": None})
    outcome = materialize_native_short_map_level_status_for_scope(
        conn, key=_key(), operational_clock=lambda: _REBUILT_AT
    )
    assert outcome.branch == BLOCKED
    assert outcome.reason_code == PROJECTION_MISSING
    assert outcome.row_count == 0
    assert conn.script["delete_calls"] == 1
    assert "inserted_rows" not in conn.script


def test_orchestrator_configuration_unavailable_deletes_and_blocks() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(
                scope_status_code="CONFIGURATION_UNAVAILABLE",
                observation_freshness_state="OBSERVATION_CONFIGURATION_UNAVAILABLE",
                actionability_state="BLOCKED_CONFIGURATION",
                source_freshness_state=None,
                cadence_contract_version=None,
                primary_source_freshness_limit_seconds=None,
                supporting_source_freshness_limit_seconds=None,
                scope_status_reason_code="NO_ELIGIBLE_CADENCE_CONFIG",
            )
        }
    )
    outcome = materialize_native_short_map_level_status_for_scope(
        conn, key=_key(), operational_clock=lambda: _REBUILT_AT
    )
    assert outcome.branch == BLOCKED
    assert outcome.reason_code == "CONFIGURATION_UNAVAILABLE"
    assert outcome.row_count == 0
    assert conn.script["delete_calls"] == 1


def test_orchestrator_identity_mismatch_is_projection_invalid() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(current_map_cycle_id="cycle-A"),
            "map": _map_row(map_cycle_id="cycle-DIFFERENT"),
        }
    )
    outcome = materialize_native_short_map_level_status_for_scope(
        conn, key=_key(), operational_clock=lambda: _REBUILT_AT
    )
    assert outcome.branch == BLOCKED
    assert outcome.reason_code == PROJECTION_INVALID
    assert conn.script["delete_calls"] == 1


def test_orchestrator_missing_map_row_is_projection_invalid() -> None:
    conn = _FakeConn({"scope_status": _scope_status_row(), "map": None})
    outcome = materialize_native_short_map_level_status_for_scope(
        conn, key=_key(), operational_clock=lambda: _REBUILT_AT
    )
    assert outcome.branch == BLOCKED
    assert outcome.reason_code == PROJECTION_INVALID


def test_orchestrator_malformed_geometry_is_geometry_invalid() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(),
            "map": _map_row(fib_ratios_json='{"ext_1_272": "10.5"}'),
        }
    )
    outcome = materialize_native_short_map_level_status_for_scope(
        conn, key=_key(), operational_clock=lambda: _REBUILT_AT
    )
    assert outcome.branch == BLOCKED
    assert outcome.reason_code == GEOMETRY_INVALID
    assert conn.script["delete_calls"] == 1


def test_orchestrator_active_evaluation_writes_three_rows() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(),
            "map": _map_row(),
            "candles": [
                {
                    "close_ts_utc": _AS_OF,
                    "open_price": Decimal("10.6"),
                    "high_price": Decimal("10.6"),
                    "low_price": Decimal("10.6"),
                    "close_price": Decimal("10.6"),
                }
            ],
        }
    )
    outcome = materialize_native_short_map_level_status_for_scope(
        conn, key=_key(), operational_clock=lambda: _REBUILT_AT
    )
    assert outcome.branch == ACTIVE_EVALUATION
    assert outcome.row_count == 3
    assert outcome.current_map_id == 42
    assert outcome.level_status_as_of_utc == _AS_OF
    assert len(conn.script["inserted_rows"]) == 3
    # replace_native_short_map_level_status_for_scope always deletes-then-inserts
    # atomically, so exactly one delete accompanies the three inserted rows.
    assert conn.script["delete_calls"] == 1


def test_orchestrator_terminal_completed_writes_three_completed_rows() -> None:
    conn = _FakeConn(
        {
            "scope_status": _scope_status_row(
                scope_status_code="MAP_COMPLETED",
                map_lifecycle_state="MAP_COMPLETED",
                actionability_state="TERMINAL_MAP",
            ),
            "map": _map_row(),
        }
    )
    outcome = materialize_native_short_map_level_status_for_scope(
        conn, key=_key(), operational_clock=lambda: _REBUILT_AT
    )
    assert outcome.branch == TERMINAL_COMPLETED
    assert outcome.row_count == 3
    inserted_states = {row["level_lifecycle_state"] for row in conn.script["inserted_rows"]}
    assert inserted_states == {"COMPLETED"}


# ---------------------------------------------------------------------------
# Import boundary / no heartbeat writes
# ---------------------------------------------------------------------------


def test_module_imports_no_forbidden_layers() -> None:
    tree = ast.parse(_source())
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
            "src.exec" + "ution_planner",
            "src.decision" + "_gate",
            "src.select" + "ion_engine",
            "src.reporting",
        ):
            assert not module_name.startswith(forbidden), module_name


def test_module_writes_no_map_generation_or_lifecycle_heartbeat_rows() -> None:
    source = _source()
    for forbidden in (
        "INSERT INTO native_short_map_v1",
        "INSERT INTO native_short_map_generation_event_v1",
        "INSERT INTO native_short_map_lifecycle_event_v1",
        "INSERT INTO native_short_materializer_run_v1",
        "materialize_scope_symbol",
        "subprocess",
        "systemd",
    ):
        assert forbidden not in source


def test_module_only_writes_the_level_status_table() -> None:
    source = _source()
    assert "INSERT INTO native_short_map_level_status_v1" not in source  # writes go through the persistence layer
    assert "replace_native_short_map_level_status_for_scope" in source
    assert "delete_native_short_map_level_status_for_scope" in source
