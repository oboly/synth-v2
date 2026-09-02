from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_projection_v1 import (
    CadenceConfigFact,
    GenerationEventFact,
    LifecycleEventFact,
    MapFact,
    ObservationFact,
    ScopeSupportEventFact,
    classify_source_freshness,
    project_native_short_scope_status,
    resolve_scope_support_state_at_cutoff,
    select_current_map,
    select_eligible_cadence_config,
)

_AS_OF = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _key(symbol: str = "BTC") -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(venue="bitvavo", symbol=symbol, quote_currency="EUR")


def _cadence(
    *,
    version: str = "v1",
    effective_from: datetime = _AS_OF - timedelta(days=30),
    effective_to: datetime | None = None,
    primary_limit: int = 43200,
    supporting_limit: int = 10800,
    grace: int = 900,
    recent_scope_grace: int = 3600,
) -> CadenceConfigFact:
    return CadenceConfigFact(
        cadence_contract_version=version,
        target_evaluation_interval="1h",
        primary_source_freshness_limit_seconds=primary_limit,
        supporting_source_freshness_limit_seconds=supporting_limit,
        evaluation_grace_seconds=grace,
        recent_scope_grace_seconds=recent_scope_grace,
        effective_from_utc=effective_from,
        effective_to_utc=effective_to,
    )


def _support_event(
    event_id: int, state: str = "SUPPORTED", ts: datetime = _AS_OF - timedelta(days=30)
) -> ScopeSupportEventFact:
    return ScopeSupportEventFact(scope_support_event_id=event_id, scope_support_state=state, event_ts_utc=ts)


def _project(**overrides):
    base = dict(
        key=_key(),
        as_of_utc=_AS_OF,
        support_events=[_support_event(1)],
        cadence_configs=[_cadence()],
        maps=[],
        generation_events=[],
        lifecycle_events=[],
        observations=[],
        primary_candle_close_timestamps=[_AS_OF - timedelta(hours=1)],
        supporting_candle_close_timestamps=[_AS_OF - timedelta(minutes=20)],
        rebuilt_at_utc=_AS_OF,
    )
    base.update(overrides)
    return project_native_short_scope_status(**base)


# --- scope support / cadence cutoff selection ------------------------------


def test_no_projection_row_for_unknown_at_as_of_scope() -> None:
    record = _project(support_events=[])
    assert record is None


def test_no_projection_row_for_not_applicable_scope() -> None:
    record = _project(support_events=[_support_event(1, state="NOT_APPLICABLE")])
    assert record is None


def test_support_event_cutoff_excludes_future_event() -> None:
    # A future SUPPORTED->NOT_APPLICABLE flip must not affect a projection at
    # an earlier as_of_utc.
    events = [
        _support_event(1, state="SUPPORTED", ts=_AS_OF - timedelta(days=30)),
        _support_event(2, state="NOT_APPLICABLE", ts=_AS_OF + timedelta(days=1)),
    ]
    assert resolve_scope_support_state_at_cutoff(events, _AS_OF) == "SUPPORTED"
    record = _project(support_events=events)
    assert record is not None


def test_support_event_same_timestamp_tie_breaks_by_event_id() -> None:
    ts = _AS_OF - timedelta(days=1)
    events = [
        _support_event(5, state="SUPPORTED", ts=ts),
        _support_event(3, state="NOT_APPLICABLE", ts=ts),
    ]
    # Higher scope_support_event_id wins the tie, per contract.
    assert resolve_scope_support_state_at_cutoff(events, _AS_OF) == "SUPPORTED"


def test_cadence_effective_window_cutoff_excludes_future_version() -> None:
    old = _cadence(version="v1", effective_from=_AS_OF - timedelta(days=60), effective_to=_AS_OF - timedelta(days=1))
    future = _cadence(version="v2", effective_from=_AS_OF + timedelta(days=1), effective_to=None)
    selected = select_eligible_cadence_config([old, future], _AS_OF)
    assert selected is None  # old expired, new not yet effective


def test_cadence_effective_window_selects_currently_active_version() -> None:
    old = _cadence(version="v1", effective_from=_AS_OF - timedelta(days=60), effective_to=_AS_OF - timedelta(days=10))
    current = _cadence(version="v2", effective_from=_AS_OF - timedelta(days=5), effective_to=None)
    selected = select_eligible_cadence_config([old, current], _AS_OF)
    assert selected is not None
    assert selected.cadence_contract_version == "v2"


# --- configuration-unavailable path -----------------------------------------


def test_no_eligible_cadence_config_yields_configuration_unavailable() -> None:
    # _project's defaults pass non-empty primary/supporting candle
    # timestamps: this deliberately proves the config-unavailable branch
    # nulls the persisted candle timestamps itself (defense in depth) even
    # when real candle evidence was supplied, not merely when the caller
    # happens to pass empty lists.
    record = _project(cadence_configs=[])
    assert record is not None
    assert record.scope_status_code == "CONFIGURATION_UNAVAILABLE"
    assert record.scope_status_reason_code == "NO_ELIGIBLE_CADENCE_CONFIG"
    assert record.actionability_state == "BLOCKED_CONFIGURATION"
    assert record.observation_freshness_state == "OBSERVATION_CONFIGURATION_UNAVAILABLE"
    assert record.cadence_contract_version is None
    assert record.primary_source_freshness_limit_seconds is None
    assert record.supporting_source_freshness_limit_seconds is None
    assert record.source_freshness_state is None
    assert record.next_expected_evaluation_at_utc is None
    assert record.observation_overdue_after_utc is None
    assert record.primary_latest_candle_ts_utc is None
    assert record.supporting_latest_candle_ts_utc is None
    assert record.status_payload_json is not None


def test_configuration_unavailable_never_reported_as_source_or_observation_codes() -> None:
    record = _project(cadence_configs=[])
    assert record.scope_status_code not in ("SOURCE_UNAVAILABLE", "SOURCE_STALE", "OBSERVATION_OVERDUE")


def test_configuration_unavailable_preserves_independently_known_map_lifecycle() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5), map_cycle_id="c1")]
    lifecycle = [LifecycleEventFact(1, 1, "ACTIVATED", _AS_OF - timedelta(hours=5))]
    record = _project(cadence_configs=[], maps=maps, lifecycle_events=lifecycle)
    assert record.scope_status_code == "CONFIGURATION_UNAVAILABLE"
    assert record.map_lifecycle_state == "MAP_ACTIVE"
    assert record.current_map_id == 1


def test_once_config_becomes_eligible_normal_evaluation_resumes() -> None:
    later_as_of = _AS_OF + timedelta(days=1)
    config = _cadence(effective_from=_AS_OF - timedelta(days=1))
    record = _project(
        as_of_utc=later_as_of,
        cadence_configs=[config],
        support_events=[_support_event(1, ts=_AS_OF - timedelta(days=30))],
        primary_candle_close_timestamps=[later_as_of - timedelta(hours=1)],
        supporting_candle_close_timestamps=[later_as_of - timedelta(minutes=20)],
        observations=[ObservationFact(1, 1, later_as_of - timedelta(minutes=30))],
        rebuilt_at_utc=later_as_of,
    )
    assert record.scope_status_code == "CURRENT_EVALUATION"


# --- future-fact exclusion ---------------------------------------------------


def test_future_map_is_excluded_from_current_map_selection() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF + timedelta(hours=1), map_cycle_id="c1")]
    selected, state, _ = select_current_map(maps, [], _AS_OF)
    assert selected is None
    assert state == "NO_CURRENT_MAP"


def test_future_lifecycle_event_does_not_affect_selected_map_state() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5), map_cycle_id="c1")]
    lifecycle = [LifecycleEventFact(1, 1, "INVALIDATED", _AS_OF + timedelta(hours=1))]
    selected, state, event = select_current_map(maps, lifecycle, _AS_OF)
    assert selected is not None
    assert state == "MAP_ACTIVE"  # future INVALIDATED not yet eligible
    assert event is None


def test_future_generation_event_excluded() -> None:
    from src.market_data.native_short_scope_status_projection_v1 import _select_latest_generation_event

    events = [GenerationEventFact(1, _AS_OF - timedelta(hours=1)), GenerationEventFact(2, _AS_OF + timedelta(hours=1))]
    latest = _select_latest_generation_event(events, _AS_OF)
    assert latest.generation_event_id == 1


def test_future_observation_excluded() -> None:
    from src.market_data.native_short_scope_status_projection_v1 import _select_latest_observation

    observations = [
        ObservationFact(1, 1, _AS_OF - timedelta(hours=1)),
        ObservationFact(2, 1, _AS_OF + timedelta(hours=1)),
    ]
    latest = _select_latest_observation(observations, _AS_OF)
    assert latest.scope_observation_id == 1


def test_future_candle_excluded_from_source_freshness() -> None:
    from src.market_data.native_short_scope_status_projection_v1 import _latest_candle_ts

    timestamps = [_AS_OF - timedelta(hours=1), _AS_OF + timedelta(hours=2)]
    assert _latest_candle_ts(timestamps, _AS_OF) == _AS_OF - timedelta(hours=1)


# --- source stale vs unavailable vs overdue ---------------------------------


def test_source_unavailable_when_no_candles_at_all() -> None:
    record = _project(primary_candle_close_timestamps=[], supporting_candle_close_timestamps=[])
    assert record.scope_status_code == "SOURCE_UNAVAILABLE"
    assert record.actionability_state == "BLOCKED_SOURCE"


def test_source_stale_when_candle_too_old() -> None:
    record = _project(
        primary_candle_close_timestamps=[_AS_OF - timedelta(hours=13)],  # > 43200s (12h) limit
        supporting_candle_close_timestamps=[_AS_OF - timedelta(minutes=20)],
    )
    assert record.scope_status_code == "SOURCE_STALE"


def test_source_current_and_observation_overdue_precedence() -> None:
    """Contract example: source stale AND observation overdue -> SOURCE_STALE
    wins at top level, but observation_freshness_state preserves OVERDUE."""
    record = _project(
        primary_candle_close_timestamps=[_AS_OF - timedelta(hours=13)],
        supporting_candle_close_timestamps=[_AS_OF - timedelta(minutes=20)],
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(hours=10))],
        support_events=[_support_event(1, ts=_AS_OF - timedelta(days=30))],
    )
    assert record.scope_status_code == "SOURCE_STALE"
    assert record.observation_freshness_state == "OBSERVATION_OVERDUE"


def test_observation_overdue_when_source_current_but_stale_observation() -> None:
    record = _project(
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(hours=5))],
    )
    assert record.scope_status_code == "OBSERVATION_OVERDUE"
    assert record.actionability_state == "BLOCKED_OBSERVATION"


def test_current_evaluation_when_everything_fresh() -> None:
    record = _project(observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=10))])
    assert record.scope_status_code == "CURRENT_EVALUATION"
    assert record.actionability_state == "NO_ACTIONABLE_MAP"


# --- recently-added scope grace ----------------------------------------------


def test_recently_added_scope_with_no_observation_is_recently_added() -> None:
    added_at = _AS_OF - timedelta(minutes=30)
    record = _project(support_events=[_support_event(1, ts=added_at)], observations=[])
    assert record.scope_status_code == "SCOPE_RECENTLY_ADDED"
    assert record.actionability_state == "BLOCKED_SCOPE"
    assert record.observation_freshness_state == "NO_OBSERVATION"


def test_after_grace_expires_with_no_observation_becomes_overdue() -> None:
    added_at = _AS_OF - timedelta(hours=2)  # recent_scope_grace_seconds=3600 (1h)
    record = _project(support_events=[_support_event(1, ts=added_at)], observations=[])
    assert record.scope_status_code == "OBSERVATION_OVERDUE"


# --- deterministic current-map selection ------------------------------------


def test_selects_latest_map_by_published_at_then_map_id() -> None:
    maps = [
        MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5)),
        MapFact(map_id=3, published_at_utc=_AS_OF - timedelta(hours=1)),
        MapFact(map_id=2, published_at_utc=_AS_OF - timedelta(hours=1)),  # tie on ts, lower id
    ]
    selected, _, _ = select_current_map(maps, [], _AS_OF)
    assert selected.map_id == 3


def test_older_terminal_map_never_overrides_newer_active_map() -> None:
    maps = [
        MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(days=5)),
        MapFact(map_id=2, published_at_utc=_AS_OF - timedelta(hours=1)),
    ]
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(days=4))]
    selected, state, _ = select_current_map(maps, lifecycle, _AS_OF)
    assert selected.map_id == 2
    assert state == "MAP_ACTIVE"


def test_all_superseded_maps_yields_no_current_map() -> None:
    maps = [
        MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(days=5)),
        MapFact(map_id=2, published_at_utc=_AS_OF - timedelta(hours=1)),
    ]
    lifecycle = [
        LifecycleEventFact(1, 1, "SUPERSEDED", _AS_OF - timedelta(hours=2), successor_map_id=2),
        LifecycleEventFact(2, 2, "SUPERSEDED", _AS_OF - timedelta(minutes=30), successor_map_id=3),
    ]
    selected, state, _ = select_current_map(maps, lifecycle, _AS_OF)
    assert selected is None
    assert state == "NO_CURRENT_MAP"


def test_lifecycle_tie_break_by_event_id_at_same_timestamp() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    ts = _AS_OF - timedelta(hours=1)
    lifecycle = [
        LifecycleEventFact(5, 1, "COMPLETED", ts),
        LifecycleEventFact(3, 1, "INVALIDATED", ts),
    ]
    selected, state, event = select_current_map(maps, lifecycle, _AS_OF)
    assert selected.map_id == 1
    assert state == "MAP_COMPLETED"  # event_id=5 wins tie
    assert event.lifecycle_event_id == 5


# --- MAP_EXPIRED fall-through -------------------------------------------------


def test_map_expired_falls_through_to_current_evaluation_not_its_own_code() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    lifecycle = [LifecycleEventFact(1, 1, "EXPIRED", _AS_OF - timedelta(hours=1))]
    record = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=10))],
    )
    assert record.map_lifecycle_state == "MAP_EXPIRED"
    assert record.actionability_state == "TERMINAL_MAP"
    assert record.scope_status_code == "CURRENT_EVALUATION"  # falls through, not MAP_EXPIRED


def test_configuration_unavailable_overrides_map_expired_fallthrough() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    lifecycle = [LifecycleEventFact(1, 1, "EXPIRED", _AS_OF - timedelta(hours=1))]
    record = _project(cadence_configs=[], maps=maps, lifecycle_events=lifecycle)
    assert record.scope_status_code == "CONFIGURATION_UNAVAILABLE"
    assert record.map_lifecycle_state == "MAP_EXPIRED"


def test_map_invalidated_and_completed_do_win_top_level_precedence() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    invalidated = [LifecycleEventFact(1, 1, "INVALIDATED", _AS_OF - timedelta(hours=1))]
    record = _project(
        maps=maps,
        lifecycle_events=invalidated,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=10))],
    )
    assert record.scope_status_code == "MAP_INVALIDATED"
    assert record.actionability_state == "TERMINAL_MAP"

    completed = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(hours=1))]
    record2 = _project(
        maps=maps,
        lifecycle_events=completed,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=10))],
    )
    assert record2.scope_status_code == "MAP_COMPLETED"


# --- idempotency --------------------------------------------------------------


# --- Issue #681: recompute_transition_state (healthy wait vs overdue) ------
#
# The terminal selected map itself may be perfectly correct (the market
# genuinely completed/expired/invalidated its swing). The gap traced for
# #681 is that, once terminal, `actionability_state=TERMINAL_MAP` alone gives
# no truthful, persisted evidence of whether the materializer already
# attempted recompute this cadence cycle and found current structure
# insufficient (healthy, bounded wait) versus recompute simply not having run
# recently at all (overdue, eligible for #688 operator Attention). These
# tests cover the additive `recompute_transition_state` field that carries
# that evidence without changing `scope_status_code` or `actionability_state`
# precedence/values (native_short_map_level_status_* still gates on the
# unchanged `TERMINAL_MAP` value).


def test_terminal_completed_map_with_fresh_evaluated_observation_is_waiting_for_new_structure() -> None:
    """Regression case 2: map completes, no new confirmed structure exists
    yet, but the materializer *successfully evaluated* current structure
    this cycle (fresh observation, observation_status=EVALUATED). This must
    be a truthful, healthy, bounded wait -- not an unexplained/
    indistinguishable NEEDS_RECOMPUTE, and not a fabricated fresh map or
    level. Freshness (OBSERVATION_CURRENT) alone is not enough evidence: it
    must also be an actual successful evaluation, not merely a fresh
    attempt that failed (see the FAILED-observation test below)."""
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5), structure_hash="h1")]
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(minutes=30))]
    record = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=5), "EVALUATED")],
    )
    assert record.map_lifecycle_state == "MAP_COMPLETED"
    assert record.observation_freshness_state == "OBSERVATION_CURRENT"
    # actionability_state (and its downstream map-level-status gating meaning)
    # is unchanged by this fix.
    assert record.actionability_state == "TERMINAL_MAP"
    assert record.recompute_transition_state == "WAITING_FOR_NEW_STRUCTURE"
    # Old terminal map/levels never regain current authority (regression
    # case 8): the terminal map stays selected, not replaced by anything.
    assert record.current_map_id == 1
    assert record.current_map_structure_hash == "h1"


def test_terminal_completed_map_with_evaluated_observation_at_terminal_event_is_waiting_for_new_structure() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    terminal_at = _AS_OF - timedelta(hours=1)
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", terminal_at)]
    record = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=[ObservationFact(1, 1, terminal_at, "EVALUATED")],
    )
    assert record.recompute_transition_state == "WAITING_FOR_NEW_STRUCTURE"


def test_terminal_completed_map_with_evaluated_observation_before_terminal_event_is_overdue() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    terminal_at = _AS_OF - timedelta(hours=1)
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", terminal_at)]
    record = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=[ObservationFact(1, 1, terminal_at - timedelta(minutes=1), "EVALUATED")],
    )
    assert record.observation_freshness_state == "OBSERVATION_CURRENT"
    assert record.recompute_transition_state == "RECOMPUTE_OVERDUE"


def test_terminal_completed_map_with_fresh_failed_observation_after_terminal_event_is_overdue() -> None:
    """Codex-flagged correction: a fresh (OBSERVATION_CURRENT) but FAILED
    observation must never be classified WAITING_FOR_NEW_STRUCTURE -- that
    would falsely present a recompute failure as healthy waiting. It must
    fail closed to RECOMPUTE_OVERDUE instead."""
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5), structure_hash="h1")]
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(minutes=30))]
    record = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=5), "FAILED")],
    )
    assert record.map_lifecycle_state == "MAP_COMPLETED"
    # Freshness alone (OBSERVATION_CURRENT) is not sufficient proof of a
    # successful recompute evaluation.
    assert record.observation_freshness_state == "OBSERVATION_CURRENT"
    assert record.actionability_state == "TERMINAL_MAP"
    assert record.recompute_transition_state != "WAITING_FOR_NEW_STRUCTURE"
    assert record.recompute_transition_state == "RECOMPUTE_OVERDUE"


def test_terminal_invalidated_map_with_overdue_observation_is_recompute_overdue() -> None:
    """Regression case 10 (ARB-like fixture): a terminal map whose most
    recent observation is stale under the cadence/grace contract must not
    remain indistinguishable healthy waiting forever -- it must surface as
    overdue/eligible for operator Attention (#688), distinct from the
    healthy-wait case above."""
    maps = [MapFact(map_id=7, published_at_utc=_AS_OF - timedelta(days=2))]
    lifecycle = [LifecycleEventFact(1, 7, "INVALIDATED", _AS_OF - timedelta(days=1))]
    # cadence: interval=1h + grace=900s => overdue after 75 minutes.
    record = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(hours=3))],
    )
    assert record.map_lifecycle_state == "MAP_INVALIDATED"
    assert record.actionability_state == "TERMINAL_MAP"
    assert record.observation_freshness_state == "OBSERVATION_OVERDUE"
    assert record.recompute_transition_state == "RECOMPUTE_OVERDUE"


def test_terminal_map_never_observed_fails_closed_to_recompute_overdue() -> None:
    """Regression case 6 (fail closed): a terminal map with no observation
    evidence at all must never be silently treated as a healthy wait."""
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(hours=4))]
    record = _project(maps=maps, lifecycle_events=lifecycle, observations=[])
    assert record.observation_freshness_state == "NO_OBSERVATION"
    assert record.recompute_transition_state == "RECOMPUTE_OVERDUE"


def test_recompute_transition_state_not_applicable_when_map_not_terminal() -> None:
    """A non-terminal (or absent) selected map carries no recompute-transition
    evidence: the field is orthogonal and must not fire outside the terminal
    case (regression case 4: a genuinely new active map is unaffected)."""
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=1))]
    record = _project(maps=maps, lifecycle_events=[], observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=5))])
    assert record.map_lifecycle_state == "MAP_ACTIVE"
    assert record.recompute_transition_state == "NOT_APPLICABLE"

    record_no_map = _project(observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=5))])
    assert record_no_map.map_lifecycle_state == "NO_CURRENT_MAP"
    assert record_no_map.recompute_transition_state == "NOT_APPLICABLE"


def test_recompute_transition_state_not_applicable_when_configuration_unavailable() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(hours=4))]
    record = _project(cadence_configs=[], maps=maps, lifecycle_events=lifecycle)
    assert record.scope_status_code == "CONFIGURATION_UNAVAILABLE"
    assert record.recompute_transition_state == "NOT_APPLICABLE"


def test_recompute_transition_state_not_applicable_when_source_blocks_precedence() -> None:
    """Regression case 6: stale/missing source data must fail closed at its
    own precedence level, never fabricating a waiting-for-structure state."""
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(hours=4))]
    record = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=5))],
        primary_candle_close_timestamps=[],
        supporting_candle_close_timestamps=[],
    )
    assert record.scope_status_code == "SOURCE_UNAVAILABLE"
    assert record.recompute_transition_state == "NOT_APPLICABLE"


def test_recompute_transition_state_is_per_scope_independent() -> None:
    """Regression case 7 (per-symbol isolation): the pure projection function
    carries no shared state between two independently evaluated scopes."""
    terminal_maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    terminal_lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(hours=4))]

    scope_a = _project(
        key=_key("AAA"),
        maps=terminal_maps,
        lifecycle_events=terminal_lifecycle,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(hours=3), "EVALUATED")],
    )
    scope_b = _project(
        key=_key("BBB"),
        maps=terminal_maps,
        lifecycle_events=terminal_lifecycle,
        observations=[ObservationFact(1, 1, _AS_OF - timedelta(minutes=5), "EVALUATED")],
    )
    assert scope_a.recompute_transition_state == "RECOMPUTE_OVERDUE"
    assert scope_b.recompute_transition_state == "WAITING_FOR_NEW_STRUCTURE"


def test_recompute_transition_state_idempotent_across_repeated_cycles() -> None:
    """Regression cases 3 and 5: repeated evaluation cycles (and, since the
    projection is a pure function of persisted facts, a process restart
    between cycles) reproduce the identical recompute_transition_state from
    identical inputs -- no duplicate/oscillating classification."""
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5))]
    lifecycle = [LifecycleEventFact(1, 1, "COMPLETED", _AS_OF - timedelta(minutes=30))]
    observations = [ObservationFact(1, 1, _AS_OF - timedelta(minutes=5), "EVALUATED")]

    first = _project(maps=maps, lifecycle_events=lifecycle, observations=observations)
    second = _project(
        maps=maps,
        lifecycle_events=lifecycle,
        observations=observations,
        rebuilt_at_utc=_AS_OF + timedelta(seconds=5),
    )
    assert first.recompute_transition_state == second.recompute_transition_state == "WAITING_FOR_NEW_STRUCTURE"


def test_rebuild_idempotent_for_identical_facts_and_as_of_utc() -> None:
    maps = [MapFact(map_id=1, published_at_utc=_AS_OF - timedelta(hours=5), map_cycle_id="c1")]
    lifecycle = [LifecycleEventFact(1, 1, "ACTIVATED", _AS_OF - timedelta(hours=5))]
    observations = [ObservationFact(1, 1, _AS_OF - timedelta(minutes=10))]
    kwargs = dict(maps=maps, lifecycle_events=lifecycle, observations=observations)

    first = _project(**kwargs)
    second = _project(**kwargs, rebuilt_at_utc=_AS_OF + timedelta(seconds=5))

    # Every semantic field must match; only rebuilt_at_utc may differ.
    for field_name in (
        "scope_status_code",
        "scope_status_reason_code",
        "map_lifecycle_state",
        "observation_freshness_state",
        "source_freshness_state",
        "actionability_state",
        "current_map_id",
        "cadence_contract_version",
        "next_expected_evaluation_at_utc",
        "observation_overdue_after_utc",
        "recompute_transition_state",
    ):
        assert getattr(first, field_name) == getattr(second, field_name), field_name
    assert first.rebuilt_at_utc != second.rebuilt_at_utc


def test_classify_source_freshness_is_pure_and_deterministic() -> None:
    config = _cadence()
    result_a = classify_source_freshness(
        primary_latest_ts=_AS_OF - timedelta(hours=1),
        supporting_latest_ts=_AS_OF - timedelta(minutes=20),
        as_of_utc=_AS_OF,
        cadence_config=config,
    )
    result_b = classify_source_freshness(
        primary_latest_ts=_AS_OF - timedelta(hours=1),
        supporting_latest_ts=_AS_OF - timedelta(minutes=20),
        as_of_utc=_AS_OF,
        cadence_config=config,
    )
    assert result_a == result_b == "SOURCE_CURRENT"


# --- boundary scan -------------------------------------------------------------


def test_projection_module_imports_no_forbidden_layers() -> None:
    source = Path("src/market_data/native_short_scope_status_projection_v1.py").read_text(encoding="utf-8")
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


def test_projection_module_has_no_db_or_wallclock_calls() -> None:
    source = Path("src/market_data/native_short_scope_status_projection_v1.py").read_text(encoding="utf-8")
    assert "datetime.now(" not in source
    assert "utcnow(" not in source
    assert ".cursor(" not in source
    assert "conn." not in source
