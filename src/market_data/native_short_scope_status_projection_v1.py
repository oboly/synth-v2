from __future__ import annotations

"""Pure, deterministic native SHORT scope-status projection engine (PR A2).

Implements the "Projection Rebuild Contract" and "Status Precedence" sections
of docs/architecture/native_short_scope_status_contract_v1.md: cutoff-aware
scope/cadence/map/lifecycle/generation/observation/candle selection, the
current-map selection rule, and top-level status precedence, including the
CONFIGURATION_UNAVAILABLE short-circuit and the MAP_EXPIRED fall-through rule
from Amendment 1.

This module is pure. It takes already-fetched fact sequences plus an explicit
as_of_utc and returns a validated NativeShortScopeStatusRecord or None. It
never opens a DB connection, never reads wall-clock time, and never mutates
its inputs. Callers own fetching facts from MariaDB and upserting the
returned record into native_short_scope_status_v1.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import (
    NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    NativeShortObservationFreshnessState,
    NativeShortScopeActionabilityState,
    NativeShortScopeMapLifecycleState,
    NativeShortScopeSourceState,
    NativeShortScopeStatusCode,
    NativeShortScopeStatusRecord,
    NativeShortScopeSupportEventState,
)

__all__ = [
    "CadenceConfigFact",
    "GenerationEventFact",
    "LifecycleEventFact",
    "MapFact",
    "ObservationFact",
    "ScopeSupportEventFact",
    "classify_source_freshness",
    "project_native_short_scope_status",
    "resolve_scope_support_state_at_cutoff",
    "select_current_map",
    "select_eligible_cadence_config",
]

_LIFECYCLE_EVENT_TYPE_TO_MAP_STATE = {
    "ACTIVATED": NativeShortScopeMapLifecycleState.MAP_ACTIVE,
    "COMPLETED": NativeShortScopeMapLifecycleState.MAP_COMPLETED,
    "INVALIDATED": NativeShortScopeMapLifecycleState.MAP_INVALIDATED,
    "EXPIRED": NativeShortScopeMapLifecycleState.MAP_EXPIRED,
}


@dataclass(frozen=True)
class ScopeSupportEventFact:
    scope_support_event_id: int
    scope_support_state: str  # "SUPPORTED" | "NOT_APPLICABLE"
    event_ts_utc: datetime


@dataclass(frozen=True)
class CadenceConfigFact:
    cadence_contract_version: str
    target_evaluation_interval: str
    primary_source_freshness_limit_seconds: int
    supporting_source_freshness_limit_seconds: int
    evaluation_grace_seconds: int
    recent_scope_grace_seconds: int
    effective_from_utc: datetime
    effective_to_utc: datetime | None = None


@dataclass(frozen=True)
class MapFact:
    map_id: int
    published_at_utc: datetime
    map_cycle_id: str | None = None
    structure_hash: str | None = None


@dataclass(frozen=True)
class GenerationEventFact:
    generation_event_id: int
    event_ts_utc: datetime


@dataclass(frozen=True)
class LifecycleEventFact:
    lifecycle_event_id: int
    map_id: int
    event_type: str
    event_ts_utc: datetime
    successor_map_id: int | None = None


@dataclass(frozen=True)
class ObservationFact:
    scope_observation_id: int
    run_id: int
    observed_at_utc: datetime
    observation_status: str | None = None
    observation_reason_code: str | None = None


def _parse_interval_seconds(interval: str) -> int:
    """Parse a native SHORT interval string ("1h", "4h") into seconds.

    Pure data-shape parsing, not a strategy predicate: every interval in this
    contract (primary_interval, supporting_interval, target_evaluation_interval)
    is an integer count of hours.
    """
    text = interval.strip().lower()
    if not text.endswith("h") or not text[:-1].isdigit():
        raise ValueError(f"UNSUPPORTED_INTERVAL_FORMAT value={interval}")
    return int(text[:-1]) * 3600


def resolve_scope_support_state_at_cutoff(
    support_events: Sequence[ScopeSupportEventFact],
    as_of_utc: datetime,
) -> NativeShortScopeSupportEventState | None:
    """Latest eligible support event at/before as_of_utc, tie-broken by id.

    Returns None for UNKNOWN_AT_AS_OF (no eligible event exists at all).
    """
    eligible = [event for event in support_events if event.event_ts_utc <= as_of_utc]
    if not eligible:
        return None
    latest = max(eligible, key=lambda event: (event.event_ts_utc, event.scope_support_event_id))
    return NativeShortScopeSupportEventState(latest.scope_support_state)


def _earliest_supported_at(
    support_events: Sequence[ScopeSupportEventFact],
    as_of_utc: datetime,
) -> datetime | None:
    """First time this scope was recorded SUPPORTED at/before as_of_utc.

    Used only to bound SCOPE_RECENTLY_ADDED grace; not a market/lifecycle
    predicate.
    """
    supported_ts = [
        event.event_ts_utc
        for event in support_events
        if event.event_ts_utc <= as_of_utc and event.scope_support_state == "SUPPORTED"
    ]
    return min(supported_ts) if supported_ts else None


def select_eligible_cadence_config(
    cadence_configs: Sequence[CadenceConfigFact],
    as_of_utc: datetime,
) -> CadenceConfigFact | None:
    """Exact full-key config version effective at as_of_utc.

    effective_from_utc <= as_of_utc AND (effective_to_utc IS NULL OR
    effective_to_utc > as_of_utc). Never falls back to a future or merely
    current config.
    """
    eligible = [
        config
        for config in cadence_configs
        if config.effective_from_utc <= as_of_utc
        and (config.effective_to_utc is None or config.effective_to_utc > as_of_utc)
    ]
    if not eligible:
        return None
    # V1 config versions do not overlap in their effective windows for one
    # exact scope key; if more than one is eligible, the most recently
    # activated version is authoritative.
    return max(eligible, key=lambda config: config.effective_from_utc)


def select_current_map(
    maps: Sequence[MapFact],
    lifecycle_events: Sequence[LifecycleEventFact],
    as_of_utc: datetime,
) -> tuple[MapFact | None, NativeShortScopeMapLifecycleState, LifecycleEventFact | None]:
    """Contract "Current-map selection rule":

    1. Exclude maps superseded by an eligible SUPERSEDED lifecycle event.
    2. Among the remainder, select latest by (published_at_utc, map_id).
    3. Resolve lifecycle state from that map's latest eligible lifecycle
       event by (event_ts_utc, lifecycle_event_id).
    4. All maps superseded (or none eligible): NO_CURRENT_MAP / None.
    """
    eligible_maps = [item for item in maps if item.published_at_utc <= as_of_utc]
    eligible_events = [event for event in lifecycle_events if event.event_ts_utc <= as_of_utc]

    superseded_map_ids = {event.map_id for event in eligible_events if event.event_type == "SUPERSEDED"}
    candidates = [item for item in eligible_maps if item.map_id not in superseded_map_ids]
    if not candidates:
        return None, NativeShortScopeMapLifecycleState.NO_CURRENT_MAP, None

    selected = max(candidates, key=lambda item: (item.published_at_utc, item.map_id))
    events_for_map = [event for event in eligible_events if event.map_id == selected.map_id]
    if not events_for_map:
        return selected, NativeShortScopeMapLifecycleState.MAP_ACTIVE, None

    latest_event = max(events_for_map, key=lambda event: (event.event_ts_utc, event.lifecycle_event_id))
    map_state = _LIFECYCLE_EVENT_TYPE_TO_MAP_STATE.get(
        latest_event.event_type, NativeShortScopeMapLifecycleState.MAP_ACTIVE
    )
    return selected, map_state, latest_event


def _select_latest_generation_event(
    generation_events: Sequence[GenerationEventFact],
    as_of_utc: datetime,
) -> GenerationEventFact | None:
    eligible = [event for event in generation_events if event.event_ts_utc <= as_of_utc]
    if not eligible:
        return None
    return max(eligible, key=lambda event: (event.event_ts_utc, event.generation_event_id))


def _select_latest_observation(
    observations: Sequence[ObservationFact],
    as_of_utc: datetime,
) -> ObservationFact | None:
    eligible = [item for item in observations if item.observed_at_utc <= as_of_utc]
    if not eligible:
        return None
    return max(eligible, key=lambda item: (item.observed_at_utc, item.scope_observation_id))


def _latest_candle_ts(
    candle_close_timestamps: Sequence[datetime],
    as_of_utc: datetime,
) -> datetime | None:
    eligible = [ts for ts in candle_close_timestamps if ts <= as_of_utc]
    return max(eligible) if eligible else None


def classify_source_freshness(
    *,
    primary_latest_ts: datetime | None,
    supporting_latest_ts: datetime | None,
    as_of_utc: datetime,
    cadence_config: CadenceConfigFact,
) -> NativeShortScopeSourceState:
    if primary_latest_ts is None or supporting_latest_ts is None:
        return NativeShortScopeSourceState.SOURCE_UNAVAILABLE
    primary_age_seconds = (as_of_utc - primary_latest_ts).total_seconds()
    supporting_age_seconds = (as_of_utc - supporting_latest_ts).total_seconds()
    if (
        primary_age_seconds > cadence_config.primary_source_freshness_limit_seconds
        or supporting_age_seconds > cadence_config.supporting_source_freshness_limit_seconds
    ):
        return NativeShortScopeSourceState.SOURCE_STALE
    return NativeShortScopeSourceState.SOURCE_CURRENT


def _classify_observation_freshness(
    *,
    latest_observation: ObservationFact | None,
    scope_added_at_utc: datetime | None,
    as_of_utc: datetime,
    cadence_config: CadenceConfigFact,
) -> tuple[NativeShortObservationFreshnessState, bool, datetime | None, datetime | None]:
    """Returns (observation_freshness_state, scope_recently_added,
    next_expected_evaluation_at_utc, observation_overdue_after_utc).

    NO_OBSERVATION means the scope has never been observed at/before
    as_of_utc. OBSERVATION_OVERDUE means at least one observation exists but
    it (or the recent-scope-grace baseline) is older than the configured
    cadence plus grace. scope_recently_added is True only while the scope has
    no observation evidence and is still inside recent_scope_grace_seconds of
    its first recorded SUPPORTED event.
    """
    interval_seconds = _parse_interval_seconds(cadence_config.target_evaluation_interval)
    grace_seconds = cadence_config.evaluation_grace_seconds

    if latest_observation is None:
        if (
            scope_added_at_utc is not None
            and (as_of_utc - scope_added_at_utc).total_seconds() < cadence_config.recent_scope_grace_seconds
        ):
            return NativeShortObservationFreshnessState.NO_OBSERVATION, True, None, None
        baseline = scope_added_at_utc if scope_added_at_utc is not None else as_of_utc
        next_expected = baseline + timedelta(seconds=interval_seconds)
        overdue_after = next_expected + timedelta(seconds=grace_seconds)
        return NativeShortObservationFreshnessState.NO_OBSERVATION, False, next_expected, overdue_after

    next_expected = latest_observation.observed_at_utc + timedelta(seconds=interval_seconds)
    overdue_after = next_expected + timedelta(seconds=grace_seconds)
    if as_of_utc > overdue_after:
        return NativeShortObservationFreshnessState.OBSERVATION_OVERDUE, False, next_expected, overdue_after
    return NativeShortObservationFreshnessState.OBSERVATION_CURRENT, False, next_expected, overdue_after


def _compute_scope_status_code(
    *,
    source_state: NativeShortScopeSourceState,
    map_lifecycle_state: NativeShortScopeMapLifecycleState,
    scope_recently_added: bool,
    observation_freshness_state: NativeShortObservationFreshnessState,
) -> NativeShortScopeStatusCode:
    """Precedence (Amendment 1 already applied by the caller for
    CONFIGURATION_UNAVAILABLE, which never reaches this function):

    SOURCE_UNAVAILABLE > SOURCE_STALE > MAP_INVALIDATED > MAP_COMPLETED >
    SCOPE_RECENTLY_ADDED > OBSERVATION_OVERDUE > CURRENT_EVALUATION.

    MAP_EXPIRED deliberately has no branch here: per contract it falls
    through to source/observation precedence, never overriding as its own
    top-level code.
    """
    if source_state == NativeShortScopeSourceState.SOURCE_UNAVAILABLE:
        return NativeShortScopeStatusCode.SOURCE_UNAVAILABLE
    if source_state == NativeShortScopeSourceState.SOURCE_STALE:
        return NativeShortScopeStatusCode.SOURCE_STALE
    if map_lifecycle_state == NativeShortScopeMapLifecycleState.MAP_INVALIDATED:
        return NativeShortScopeStatusCode.MAP_INVALIDATED
    if map_lifecycle_state == NativeShortScopeMapLifecycleState.MAP_COMPLETED:
        return NativeShortScopeStatusCode.MAP_COMPLETED
    if scope_recently_added:
        return NativeShortScopeStatusCode.SCOPE_RECENTLY_ADDED
    if observation_freshness_state in (
        NativeShortObservationFreshnessState.OBSERVATION_OVERDUE,
        NativeShortObservationFreshnessState.NO_OBSERVATION,
    ):
        return NativeShortScopeStatusCode.OBSERVATION_OVERDUE
    return NativeShortScopeStatusCode.CURRENT_EVALUATION


def _compute_actionability_state(
    *,
    scope_status_code: NativeShortScopeStatusCode,
    map_lifecycle_state: NativeShortScopeMapLifecycleState,
    current_map_id: int | None,
) -> NativeShortScopeActionabilityState:
    if scope_status_code == NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE:
        return NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION
    if scope_status_code in (
        NativeShortScopeStatusCode.SOURCE_UNAVAILABLE,
        NativeShortScopeStatusCode.SOURCE_STALE,
    ):
        return NativeShortScopeActionabilityState.BLOCKED_SOURCE
    if map_lifecycle_state in (
        NativeShortScopeMapLifecycleState.MAP_INVALIDATED,
        NativeShortScopeMapLifecycleState.MAP_COMPLETED,
        NativeShortScopeMapLifecycleState.MAP_EXPIRED,
    ):
        return NativeShortScopeActionabilityState.TERMINAL_MAP
    if scope_status_code == NativeShortScopeStatusCode.SCOPE_RECENTLY_ADDED:
        return NativeShortScopeActionabilityState.BLOCKED_SCOPE
    if scope_status_code == NativeShortScopeStatusCode.OBSERVATION_OVERDUE:
        return NativeShortScopeActionabilityState.BLOCKED_OBSERVATION
    if current_map_id is not None:
        return NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP
    return NativeShortScopeActionabilityState.NO_ACTIONABLE_MAP


def _configuration_unavailable_payload(key: NativeShortMapScopeKey, as_of_utc: datetime) -> str:
    return json.dumps(
        {
            "reason_code": NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            "venue": key.venue,
            "symbol": key.symbol,
            "quote_currency": key.quote_currency,
            "fib_trading_horizon": key.fib_trading_horizon,
            "primary_interval": key.primary_interval,
            "supporting_interval": key.supporting_interval,
            "as_of_utc": as_of_utc.isoformat(),
            "detail": "No exact full-key native_short_scope_cadence_config_v1 version is eligible at as_of_utc.",
        },
        sort_keys=True,
    )


def project_native_short_scope_status(
    *,
    key: NativeShortMapScopeKey,
    as_of_utc: datetime,
    support_events: Sequence[ScopeSupportEventFact],
    cadence_configs: Sequence[CadenceConfigFact],
    maps: Sequence[MapFact],
    generation_events: Sequence[GenerationEventFact],
    lifecycle_events: Sequence[LifecycleEventFact],
    observations: Sequence[ObservationFact],
    primary_candle_close_timestamps: Sequence[datetime],
    supporting_candle_close_timestamps: Sequence[datetime],
    rebuilt_at_utc: datetime,
) -> NativeShortScopeStatusRecord | None:
    """Deterministic rebuild for one canonical scope at one as_of_utc.

    Returns None when the scope is not SUPPORTED at as_of_utc (covers both
    NOT_APPLICABLE and UNKNOWN_AT_AS_OF; contract: no projection row for a
    non-SUPPORTED or UNKNOWN_AT_AS_OF scope). Otherwise returns exactly one
    validated NativeShortScopeStatusRecord; construction itself enforces the
    A1b conditional-nullability rules.
    """
    support_state = resolve_scope_support_state_at_cutoff(support_events, as_of_utc)
    if support_state != NativeShortScopeSupportEventState.SUPPORTED:
        return None

    selected_map, map_lifecycle_state, latest_lifecycle_event = select_current_map(
        maps, lifecycle_events, as_of_utc
    )
    latest_generation_event = _select_latest_generation_event(generation_events, as_of_utc)
    latest_observation = _select_latest_observation(observations, as_of_utc)
    primary_latest_ts = _latest_candle_ts(primary_candle_close_timestamps, as_of_utc)
    supporting_latest_ts = _latest_candle_ts(supporting_candle_close_timestamps, as_of_utc)

    common_fields: dict[str, object] = dict(
        key=key,
        scope_support_state=support_state,
        map_lifecycle_state=map_lifecycle_state,
        current_map_id=selected_map.map_id if selected_map is not None else None,
        current_map_cycle_id=selected_map.map_cycle_id if selected_map is not None else None,
        current_map_published_at_utc=selected_map.published_at_utc if selected_map is not None else None,
        current_map_structure_hash=selected_map.structure_hash if selected_map is not None else None,
        latest_generation_event_id=(
            latest_generation_event.generation_event_id if latest_generation_event is not None else None
        ),
        latest_lifecycle_event_id=(
            latest_lifecycle_event.lifecycle_event_id if latest_lifecycle_event is not None else None
        ),
        latest_observation_id=(
            latest_observation.scope_observation_id if latest_observation is not None else None
        ),
        latest_run_id=latest_observation.run_id if latest_observation is not None else None,
        latest_observed_at_utc=(
            latest_observation.observed_at_utc if latest_observation is not None else None
        ),
        primary_latest_candle_ts_utc=primary_latest_ts,
        supporting_latest_candle_ts_utc=supporting_latest_ts,
        projection_as_of_utc=as_of_utc,
        rebuilt_at_utc=rebuilt_at_utc,
    )

    cadence_config = select_eligible_cadence_config(cadence_configs, as_of_utc)
    if cadence_config is None:
        return NativeShortScopeStatusRecord(
            **common_fields,
            scope_status_code=NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE,
            scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
            actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
            source_freshness_state=None,
            primary_source_freshness_limit_seconds=None,
            supporting_source_freshness_limit_seconds=None,
            cadence_contract_version=None,
            next_expected_evaluation_at_utc=None,
            observation_overdue_after_utc=None,
            status_payload_json=_configuration_unavailable_payload(key, as_of_utc),
        )

    source_state = classify_source_freshness(
        primary_latest_ts=primary_latest_ts,
        supporting_latest_ts=supporting_latest_ts,
        as_of_utc=as_of_utc,
        cadence_config=cadence_config,
    )
    scope_added_at_utc = _earliest_supported_at(support_events, as_of_utc)
    (
        observation_freshness_state,
        scope_recently_added,
        next_expected_evaluation_at_utc,
        observation_overdue_after_utc,
    ) = _classify_observation_freshness(
        latest_observation=latest_observation,
        scope_added_at_utc=scope_added_at_utc,
        as_of_utc=as_of_utc,
        cadence_config=cadence_config,
    )
    scope_status_code = _compute_scope_status_code(
        source_state=source_state,
        map_lifecycle_state=map_lifecycle_state,
        scope_recently_added=scope_recently_added,
        observation_freshness_state=observation_freshness_state,
    )
    actionability_state = _compute_actionability_state(
        scope_status_code=scope_status_code,
        map_lifecycle_state=map_lifecycle_state,
        current_map_id=selected_map.map_id if selected_map is not None else None,
    )
    scope_status_reason_code = (
        latest_observation.observation_reason_code
        if latest_observation is not None and latest_observation.observation_status == "FAILED"
        else None
    )

    return NativeShortScopeStatusRecord(
        **common_fields,
        scope_status_code=scope_status_code,
        scope_status_reason_code=scope_status_reason_code,
        observation_freshness_state=observation_freshness_state,
        actionability_state=actionability_state,
        source_freshness_state=source_state,
        primary_source_freshness_limit_seconds=cadence_config.primary_source_freshness_limit_seconds,
        supporting_source_freshness_limit_seconds=cadence_config.supporting_source_freshness_limit_seconds,
        cadence_contract_version=cadence_config.cadence_contract_version,
        next_expected_evaluation_at_utc=next_expected_evaluation_at_utc,
        observation_overdue_after_utc=observation_overdue_after_utc,
        status_payload_json=None,
    )
