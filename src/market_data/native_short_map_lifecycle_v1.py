from __future__ import annotations

"""Market-only native SHORT map lifecycle contract.

PR1a owns the immutable map shape, append-only event shapes, lifecycle projection
rules, and write-intent validation only. No generator, scheduler, account,
decision, execution, or broker integration belongs here.

PR1b repository writes must call `validate_native_short_map_write_intent(...)`
before persisting generation or lifecycle rows.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Sequence, TypeVar

__all__ = [
    "DATA_UNAVAILABLE_REASON_CODES",
    "DEFAULT_FIB_TRADING_HORIZON",
    "DEFAULT_PRIMARY_INTERVAL",
    "DEFAULT_QUOTE_CURRENCY",
    "DEFAULT_SUPPORTING_INTERVAL",
    "NativeShortMapGenerationEvent",
    "NativeShortMapGenerationEventType",
    "NativeShortMapLifecycleEvent",
    "NativeShortMapLifecycleEventType",
    "NativeShortMapLifecycleProjection",
    "NativeShortMapLifecycleState",
    "NativeShortMapLifecycleValidationError",
    "NativeShortMapRecord",
    "NativeShortMapScopeKey",
    "NativeShortMapScopeSupport",
    "NativeShortMapScopeSupportState",
    "project_current_native_short_map_lifecycle",
    "validate_native_short_map_write_intent",
]


T = TypeVar("T")

DEFAULT_QUOTE_CURRENCY = "EUR"
DEFAULT_FIB_TRADING_HORIZON = "SHORT"
DEFAULT_PRIMARY_INTERVAL = "4h"
DEFAULT_SUPPORTING_INTERVAL = "1h"


class NativeShortMapLifecycleState(StrEnum):
    MAP_ACTIVE = "MAP_ACTIVE"
    MAP_REBUILD_REQUIRED = "MAP_REBUILD_REQUIRED"
    MAP_GENERATING = "MAP_GENERATING"
    MAP_REBUILD_REJECTED = "MAP_REBUILD_REJECTED"
    MAP_DATA_UNAVAILABLE = "MAP_DATA_UNAVAILABLE"
    MAP_GENERATION_FAILED = "MAP_GENERATION_FAILED"
    MAP_NOT_APPLICABLE = "MAP_NOT_APPLICABLE"


class NativeShortMapGenerationEventType(StrEnum):
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class NativeShortMapLifecycleEventType(StrEnum):
    ACTIVATED = "ACTIVATED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class NativeShortMapScopeSupportState(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


DATA_UNAVAILABLE_REASON_CODES = frozenset(
    {
        "CANDLES_INSUFFICIENT",
        "CANDLE_GAPS_DETECTED",
        "CANDLE_SNAPSHOT_STALE",
        "ASSET_HISTORY_TOO_SHORT",
        "INGEST_LOOKBACK_LIMIT",
        "NO_CLOSED_DAILY_CANDLES",
    }
)

_TERMINAL_GENERATION_EVENT_TYPES = frozenset(
    {
        NativeShortMapGenerationEventType.PUBLISHED,
        NativeShortMapGenerationEventType.REJECTED,
        NativeShortMapGenerationEventType.SKIPPED,
        NativeShortMapGenerationEventType.FAILED,
    }
)
_AUTHORITATIVE_GENERATION_EVENT_TYPES = frozenset(
    {
        NativeShortMapGenerationEventType.PUBLISHED,
        NativeShortMapGenerationEventType.REJECTED,
        NativeShortMapGenerationEventType.FAILED,
    }
)
_TERMINAL_LIFECYCLE_EVENT_TYPES = frozenset(
    {
        NativeShortMapLifecycleEventType.COMPLETED,
        NativeShortMapLifecycleEventType.EXPIRED,
        NativeShortMapLifecycleEventType.INVALIDATED,
        NativeShortMapLifecycleEventType.SUPERSEDED,
    }
)


@dataclass(frozen=True)
class NativeShortMapScopeKey:
    venue: str
    symbol: str
    quote_currency: str = DEFAULT_QUOTE_CURRENCY
    fib_trading_horizon: str = DEFAULT_FIB_TRADING_HORIZON
    primary_interval: str = DEFAULT_PRIMARY_INTERVAL
    supporting_interval: str = DEFAULT_SUPPORTING_INTERVAL


@dataclass(frozen=True)
class NativeShortMapScopeSupport:
    key: NativeShortMapScopeKey
    support_state: NativeShortMapScopeSupportState
    reason_code: str | None = None


@dataclass(frozen=True)
class NativeShortMapRecord:
    map_id: int
    key: NativeShortMapScopeKey
    published_at_utc: datetime
    structure_hash: str
    generator_name: str
    generator_version: str
    fib_model_name: str
    fib_model_version: str
    published_generation_attempt_id: str
    previous_map_id: int | None = None
    previous_map_cycle_id: str | None = None
    map_cycle_id: str | None = None
    market_snapshot_ts_utc: datetime | None = None
    anchor_low_ts_utc: datetime | None = None
    anchor_low_price: Decimal | None = None
    anchor_high_ts_utc: datetime | None = None
    anchor_high_price: Decimal | None = None
    retrace_ratio: Decimal | None = None
    retrace_price: Decimal | None = None
    fib_ratios_json: str = "[]"
    target_levels_json: str = "[]"
    invalidation_price: Decimal | None = None
    invalidation_rule: str = ""
    source_primary_candle_ts_utc: datetime | None = None
    source_support_candle_ts_utc: datetime | None = None
    source_primary_ref: str = ""
    source_support_ref: str = ""
    source_primary_candle_count: int = 0
    source_support_candle_count: int = 0
    map_payload_json: str = "{}"


@dataclass(frozen=True)
class NativeShortMapGenerationEvent:
    generation_event_id: int
    key: NativeShortMapScopeKey
    attempt_id: str
    event_type: NativeShortMapGenerationEventType
    event_ts_utc: datetime
    reason_code: str | None = None
    map_id: int | None = None
    trigger_type: str | None = None
    candidate_map_cycle_id: str | None = None
    candidate_previous_map_id: int | None = None
    candidate_primary_lifecycle_state: str | None = None
    candidate_current_map_status: str | None = None
    latest_primary_close_ts_utc: datetime | None = None
    latest_support_close_ts_utc: datetime | None = None
    latest_primary_close_price: Decimal | None = None
    source_primary_ref: str | None = None
    source_support_ref: str | None = None
    source_primary_candle_count: int | None = None
    source_support_candle_count: int | None = None


@dataclass(frozen=True)
class NativeShortMapLifecycleEvent:
    lifecycle_event_id: int
    map_id: int
    event_type: NativeShortMapLifecycleEventType
    event_ts_utc: datetime
    reason_code: str | None = None
    successor_map_id: int | None = None
    observed_current_price: Decimal | None = None
    observed_max_high_since_anchor: Decimal | None = None
    observed_min_low_since_anchor: Decimal | None = None
    latest_primary_close_ts_utc: datetime | None = None
    latest_support_close_ts_utc: datetime | None = None
    observer_name: str | None = None
    observer_version: str | None = None


@dataclass(frozen=True)
class NativeShortMapLifecycleProjection:
    key: NativeShortMapScopeKey
    lifecycle_state: NativeShortMapLifecycleState
    lifecycle_state_source: str
    active_map_id: int | None = None
    active_map_published_at_utc: datetime | None = None
    open_attempt_id: str | None = None
    open_attempt_started_at_utc: datetime | None = None
    authoritative_attempt_id: str | None = None
    authoritative_event_type: NativeShortMapGenerationEventType | None = None
    authoritative_event_ts_utc: datetime | None = None
    authoritative_reason_code: str | None = None
    terminal_map_id: int | None = None
    terminal_event_type: NativeShortMapLifecycleEventType | None = None
    terminal_event_ts_utc: datetime | None = None
    latest_skip_attempt_id: str | None = None
    latest_skip_reason_code: str | None = None
    latest_skip_event_ts_utc: datetime | None = None


class NativeShortMapLifecycleValidationError(ValueError):
    pass


def _latest(values: Iterable[T], *, key) -> T | None:
    indexed = list(enumerate(values))
    if not indexed:
        return None
    _, value = max(indexed, key=lambda item: (key(item[1]), item[0]))
    return value


def _filter_scope(values: Sequence[T], *, key_fn, scope_key: NativeShortMapScopeKey) -> list[T]:
    return [value for value in values if key_fn(value) == scope_key]


def _latest_lifecycle_by_map(
    lifecycle_events: Sequence[NativeShortMapLifecycleEvent],
) -> dict[int, NativeShortMapLifecycleEvent]:
    grouped: dict[int, list[NativeShortMapLifecycleEvent]] = {}
    for event in lifecycle_events:
        grouped.setdefault(event.map_id, []).append(event)
    return {
        map_id: _latest(events, key=lambda event: event.lifecycle_event_id)
        for map_id, events in grouped.items()
    }


def _events_by_attempt(
    generation_events: Sequence[NativeShortMapGenerationEvent],
) -> dict[str, list[NativeShortMapGenerationEvent]]:
    grouped: dict[str, list[NativeShortMapGenerationEvent]] = {}
    for event in generation_events:
        grouped.setdefault(event.attempt_id, []).append(event)
    return grouped


def _ordered_maps(maps: Sequence[NativeShortMapRecord]) -> list[NativeShortMapRecord]:
    return sorted(maps, key=lambda item: (item.published_at_utc, item.map_id))


def _is_newer_map(candidate: NativeShortMapRecord, reference: NativeShortMapRecord) -> bool:
    return (candidate.published_at_utc, candidate.map_id) > (reference.published_at_utc, reference.map_id)


def validate_native_short_map_write_intent(
    *,
    scope_support: NativeShortMapScopeSupport,
    maps: Sequence[NativeShortMapRecord],
    generation_events: Sequence[NativeShortMapGenerationEvent],
    lifecycle_events: Sequence[NativeShortMapLifecycleEvent],
) -> None:
    scope_key = scope_support.key
    all_maps_by_id = {item.map_id: item for item in maps}
    scoped_maps = _filter_scope(maps, key_fn=lambda item: item.key, scope_key=scope_key)
    maps_by_id = {item.map_id: item for item in scoped_maps}
    scoped_generation_events = _filter_scope(
        generation_events,
        key_fn=lambda item: item.key,
        scope_key=scope_key,
    )

    for event in generation_events:
        if event.key != scope_key:
            raise NativeShortMapLifecycleValidationError(
                f"GENERATION_EVENT_SCOPE_MISMATCH attempt_id={event.attempt_id}"
            )
        if event.event_type == NativeShortMapGenerationEventType.PUBLISHED:
            if event.map_id is None:
                raise NativeShortMapLifecycleValidationError(
                    f"PUBLISHED_REQUIRES_MAP_ID attempt_id={event.attempt_id}"
                )
            published_map = maps_by_id.get(event.map_id)
            if published_map is None:
                raise NativeShortMapLifecycleValidationError(
                    f"PUBLISHED_MAP_SCOPE_MISMATCH attempt_id={event.attempt_id} map_id={event.map_id}"
                )
        elif event.map_id is not None:
            raise NativeShortMapLifecycleValidationError(
                f"NON_PUBLISHED_GENERATION_EVENT_REQUIRES_NULL_MAP_ID attempt_id={event.attempt_id}"
            )

    for map_record in scoped_maps:
        if map_record.previous_map_id is not None:
            previous_map = all_maps_by_id.get(map_record.previous_map_id)
            if previous_map is None:
                raise NativeShortMapLifecycleValidationError(
                    f"PREVIOUS_MAP_ID_MISSING map_id={map_record.map_id} previous_map_id={map_record.previous_map_id}"
                )
            if previous_map.key != scope_key:
                raise NativeShortMapLifecycleValidationError(
                    f"PREVIOUS_MAP_SCOPE_MISMATCH map_id={map_record.map_id} previous_map_id={map_record.previous_map_id}"
                )

    attempts_by_id = _events_by_attempt(scoped_generation_events)
    for map_record in scoped_maps:
        attempt_events = attempts_by_id.get(map_record.published_generation_attempt_id, [])
        started = [
            event
            for event in attempt_events
            if event.event_type == NativeShortMapGenerationEventType.ATTEMPT_STARTED
        ]
        published = [
            event
            for event in attempt_events
            if event.event_type == NativeShortMapGenerationEventType.PUBLISHED and event.map_id == map_record.map_id
        ]
        if not started:
            raise NativeShortMapLifecycleValidationError(
                f"MAP_PUBLISHED_ATTEMPT_START_MISSING map_id={map_record.map_id} attempt_id={map_record.published_generation_attempt_id}"
            )
        if not published:
            raise NativeShortMapLifecycleValidationError(
                f"MAP_PUBLISHED_EVENT_MISSING map_id={map_record.map_id} attempt_id={map_record.published_generation_attempt_id}"
            )

    for attempt_id, attempt_events in _events_by_attempt(scoped_generation_events).items():
        ordered = sorted(attempt_events, key=lambda event: event.generation_event_id)
        started = [
            event
            for event in ordered
            if event.event_type == NativeShortMapGenerationEventType.ATTEMPT_STARTED
        ]
        if len(started) > 1:
            raise NativeShortMapLifecycleValidationError(
                f"DUPLICATE_ATTEMPT_STARTED attempt_id={attempt_id}"
            )
        terminals = [event for event in ordered if event.event_type in _TERMINAL_GENERATION_EVENT_TYPES]
        if len(terminals) > 1:
            raise NativeShortMapLifecycleValidationError(
                f"MULTIPLE_TERMINAL_GENERATION_EVENTS attempt_id={attempt_id}"
            )
        for event in ordered:
            if event.event_type in _TERMINAL_GENERATION_EVENT_TYPES:
                started_before = [
                    prior
                    for prior in ordered
                    if prior.generation_event_id < event.generation_event_id
                    and prior.event_type == NativeShortMapGenerationEventType.ATTEMPT_STARTED
                ]
                if not started_before:
                    raise NativeShortMapLifecycleValidationError(
                        f"TERMINAL_GENERATION_EVENT_WITHOUT_START attempt_id={attempt_id}"
                    )

    lifecycle_by_map: dict[int, list[NativeShortMapLifecycleEvent]] = {}
    for event in lifecycle_events:
        if event.map_id not in maps_by_id:
            raise NativeShortMapLifecycleValidationError(
                f"LIFECYCLE_EVENT_SCOPE_MISMATCH map_id={event.map_id}"
            )
        lifecycle_by_map.setdefault(event.map_id, []).append(event)

    for map_id, events in lifecycle_by_map.items():
        ordered = sorted(events, key=lambda event: event.lifecycle_event_id)
        terminal_seen = False
        seen_event_types: set[NativeShortMapLifecycleEventType] = set()
        for event in ordered:
            if terminal_seen:
                raise NativeShortMapLifecycleValidationError(
                    f"LIFECYCLE_EVENT_AFTER_TERMINAL map_id={map_id} event_type={event.event_type}"
                )
            if event.event_type in seen_event_types:
                raise NativeShortMapLifecycleValidationError(
                    f"DUPLICATE_LIFECYCLE_EVENT_TYPE map_id={map_id} event_type={event.event_type}"
                )
            seen_event_types.add(event.event_type)
            if event.event_type == NativeShortMapLifecycleEventType.ACTIVATED:
                continue
            if event.event_type == NativeShortMapLifecycleEventType.SUPERSEDED:
                if event.successor_map_id is None:
                    raise NativeShortMapLifecycleValidationError(
                        f"SUPERSEDED_REQUIRES_SUCCESSOR map_id={map_id}"
                    )
                successor_map = all_maps_by_id.get(event.successor_map_id)
                if successor_map is None:
                    raise NativeShortMapLifecycleValidationError(
                        f"SUPERSEDED_SUCCESSOR_MISSING map_id={map_id} successor_map_id={event.successor_map_id}"
                    )
                if successor_map.key != scope_key:
                    raise NativeShortMapLifecycleValidationError(
                        f"SUPERSEDED_SUCCESSOR_SCOPE_MISMATCH map_id={map_id} successor_map_id={event.successor_map_id}"
                    )
                if not _is_newer_map(successor_map, maps_by_id[map_id]):
                    raise NativeShortMapLifecycleValidationError(
                        f"SUPERSEDED_SUCCESSOR_NOT_NEWER map_id={map_id} successor_map_id={event.successor_map_id}"
                    )
            if event.event_type in _TERMINAL_LIFECYCLE_EVENT_TYPES:
                terminal_seen = True


def project_current_native_short_map_lifecycle(
    *,
    scope_support: NativeShortMapScopeSupport,
    maps: Sequence[NativeShortMapRecord],
    generation_events: Sequence[NativeShortMapGenerationEvent],
    lifecycle_events: Sequence[NativeShortMapLifecycleEvent],
) -> NativeShortMapLifecycleProjection:
    scope_key = scope_support.key
    scoped_maps = _filter_scope(maps, key_fn=lambda item: item.key, scope_key=scope_key)
    ordered_maps = _ordered_maps(scoped_maps)
    scoped_generation_events = _filter_scope(
        generation_events,
        key_fn=lambda item: item.key,
        scope_key=scope_key,
    )
    map_ids = {item.map_id for item in scoped_maps}
    scoped_lifecycle_events = [event for event in lifecycle_events if event.map_id in map_ids]
    latest_lifecycle_by_map = _latest_lifecycle_by_map(scoped_lifecycle_events)

    active_maps = [
        item
        for item in ordered_maps
        if latest_lifecycle_by_map.get(item.map_id) is None
        or latest_lifecycle_by_map[item.map_id].event_type
        == NativeShortMapLifecycleEventType.ACTIVATED
    ]
    latest_active_map = _latest(active_maps, key=lambda item: (item.published_at_utc, item.map_id))

    attempt_events = _events_by_attempt(scoped_generation_events)
    open_attempts: list[NativeShortMapGenerationEvent] = []
    for events in attempt_events.values():
        ordered = sorted(events, key=lambda event: event.generation_event_id)
        started = [event for event in ordered if event.event_type == NativeShortMapGenerationEventType.ATTEMPT_STARTED]
        if not started:
            continue
        terminals = [event for event in ordered if event.event_type in _TERMINAL_GENERATION_EVENT_TYPES]
        if terminals:
            continue
        latest_started = _latest(started, key=lambda event: event.generation_event_id)
        if latest_started is not None:
            open_attempts.append(latest_started)
    latest_open_attempt = _latest(open_attempts, key=lambda item: item.generation_event_id)

    authoritative_events = [
        event for event in scoped_generation_events if event.event_type in _AUTHORITATIVE_GENERATION_EVENT_TYPES
    ]
    latest_authoritative_event = _latest(authoritative_events, key=lambda item: item.generation_event_id)

    skipped_events = [
        event for event in scoped_generation_events if event.event_type == NativeShortMapGenerationEventType.SKIPPED
    ]
    latest_skip_event = _latest(skipped_events, key=lambda item: item.generation_event_id)

    terminal_map_events = [
        event for event in scoped_lifecycle_events if event.event_type in _TERMINAL_LIFECYCLE_EVENT_TYPES
    ]
    latest_terminal_map_event = _latest(terminal_map_events, key=lambda item: item.lifecycle_event_id)

    if latest_active_map is not None:
        return NativeShortMapLifecycleProjection(
            key=scope_key,
            lifecycle_state=NativeShortMapLifecycleState.MAP_ACTIVE,
            lifecycle_state_source="LATEST_ACTIVE_MAP",
            active_map_id=latest_active_map.map_id,
            active_map_published_at_utc=latest_active_map.published_at_utc,
            latest_skip_attempt_id=None if latest_skip_event is None else latest_skip_event.attempt_id,
            latest_skip_reason_code=None if latest_skip_event is None else latest_skip_event.reason_code,
            latest_skip_event_ts_utc=None if latest_skip_event is None else latest_skip_event.event_ts_utc,
        )

    if latest_open_attempt is not None:
        return NativeShortMapLifecycleProjection(
            key=scope_key,
            lifecycle_state=NativeShortMapLifecycleState.MAP_GENERATING,
            lifecycle_state_source="OPEN_ATTEMPT",
            open_attempt_id=latest_open_attempt.attempt_id,
            open_attempt_started_at_utc=latest_open_attempt.event_ts_utc,
            latest_skip_attempt_id=None if latest_skip_event is None else latest_skip_event.attempt_id,
            latest_skip_reason_code=None if latest_skip_event is None else latest_skip_event.reason_code,
            latest_skip_event_ts_utc=None if latest_skip_event is None else latest_skip_event.event_ts_utc,
        )

    if latest_authoritative_event is not None:
        if latest_authoritative_event.event_type == NativeShortMapGenerationEventType.FAILED:
            return NativeShortMapLifecycleProjection(
                key=scope_key,
                lifecycle_state=NativeShortMapLifecycleState.MAP_GENERATION_FAILED,
                lifecycle_state_source="AUTHORITATIVE_ATTEMPT",
                authoritative_attempt_id=latest_authoritative_event.attempt_id,
                authoritative_event_type=latest_authoritative_event.event_type,
                authoritative_event_ts_utc=latest_authoritative_event.event_ts_utc,
                authoritative_reason_code=latest_authoritative_event.reason_code,
                latest_skip_attempt_id=None if latest_skip_event is None else latest_skip_event.attempt_id,
                latest_skip_reason_code=None if latest_skip_event is None else latest_skip_event.reason_code,
                latest_skip_event_ts_utc=None if latest_skip_event is None else latest_skip_event.event_ts_utc,
            )
        if latest_authoritative_event.event_type == NativeShortMapGenerationEventType.REJECTED:
            rejected_state = (
                NativeShortMapLifecycleState.MAP_DATA_UNAVAILABLE
                if (latest_authoritative_event.reason_code or "") in DATA_UNAVAILABLE_REASON_CODES
                else NativeShortMapLifecycleState.MAP_REBUILD_REJECTED
            )
            return NativeShortMapLifecycleProjection(
                key=scope_key,
                lifecycle_state=rejected_state,
                lifecycle_state_source="AUTHORITATIVE_ATTEMPT",
                authoritative_attempt_id=latest_authoritative_event.attempt_id,
                authoritative_event_type=latest_authoritative_event.event_type,
                authoritative_event_ts_utc=latest_authoritative_event.event_ts_utc,
                authoritative_reason_code=latest_authoritative_event.reason_code,
                latest_skip_attempt_id=None if latest_skip_event is None else latest_skip_event.attempt_id,
                latest_skip_reason_code=None if latest_skip_event is None else latest_skip_event.reason_code,
                latest_skip_event_ts_utc=None if latest_skip_event is None else latest_skip_event.event_ts_utc,
            )
        # PUBLISHED: fall through to terminal map check

    if latest_terminal_map_event is not None:
        return NativeShortMapLifecycleProjection(
            key=scope_key,
            lifecycle_state=NativeShortMapLifecycleState.MAP_REBUILD_REQUIRED,
            lifecycle_state_source="TERMINAL_MAP",
            terminal_map_id=latest_terminal_map_event.map_id,
            terminal_event_type=latest_terminal_map_event.event_type,
            terminal_event_ts_utc=latest_terminal_map_event.event_ts_utc,
            latest_skip_attempt_id=None if latest_skip_event is None else latest_skip_event.attempt_id,
            latest_skip_reason_code=None if latest_skip_event is None else latest_skip_event.reason_code,
            latest_skip_event_ts_utc=None if latest_skip_event is None else latest_skip_event.event_ts_utc,
        )

    if scope_support.support_state == NativeShortMapScopeSupportState.SUPPORTED:
        return NativeShortMapLifecycleProjection(
            key=scope_key,
            lifecycle_state=NativeShortMapLifecycleState.MAP_REBUILD_REQUIRED,
            lifecycle_state_source="SUPPORTED_SCOPE_NO_AUTHORITATIVE_ATTEMPT",
            latest_skip_attempt_id=None if latest_skip_event is None else latest_skip_event.attempt_id,
            latest_skip_reason_code=None if latest_skip_event is None else latest_skip_event.reason_code,
            latest_skip_event_ts_utc=None if latest_skip_event is None else latest_skip_event.event_ts_utc,
        )

    return NativeShortMapLifecycleProjection(
        key=scope_key,
        lifecycle_state=NativeShortMapLifecycleState.MAP_NOT_APPLICABLE,
        lifecycle_state_source="EXPLICIT_SCOPE_POLICY",
        latest_skip_attempt_id=None if latest_skip_event is None else latest_skip_event.attempt_id,
        latest_skip_reason_code=None if latest_skip_event is None else latest_skip_event.reason_code,
        latest_skip_event_ts_utc=None if latest_skip_event is None else latest_skip_event.event_ts_utc,
    )
