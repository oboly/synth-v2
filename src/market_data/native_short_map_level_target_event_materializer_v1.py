from __future__ import annotations

"""Native SHORT map-level target-event materializer (V1).

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none

Authorization boundary: see native_short_map_level_target_event_v1.py module
docstring. This is prospective outcome-evidence work, not a response to any
canonical BTC/IOST lifecycle regression -- none was found.

Boundary:
- Reuses the existing, unchanged native_short_map_level_status_materializer_v1
  pure/DB helpers as the single source of the REACHED/PASSED/ACTIVE decision
  (select_gate_decision, extract_v1_sell_geometry, fetch_eligible_primary_candles,
  classify_level_state). This module does not introduce a second independent
  lifecycle-decision function; it only durably records the same decision, for
  target-event-covered maps only, as an immutable append-only event.
- Only ever appends REACHED/PASSED events for the projection-selected current
  map while it is in ACTIVE_EVALUATION. Terminal (COMPLETED/HISTORICAL)
  branches append no new events; already-persisted events for a superseded,
  completed, or invalidated map remain exactly as recorded.
- A map is eligible for target-event coverage only when published at or after
  an explicit, caller-supplied coverage watermark (see
  is_map_target_event_coverage_eligible). Maps published before the watermark
  are never backfilled; this module does not fabricate events for pre-coverage
  history.
- Caller owns the transaction boundary. This module performs no independent
  commit/rollback so it can be invoked in the same transaction as the existing
  native_short_map_level_status_v1 row rebuild.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.market_data.native_short_fib_context_v1 import Candle
from src.market_data.native_short_map_level_status_materializer_v1 import (
    ACTIVE_EVALUATION,
    classify_level_state,
    extract_v1_sell_geometry,
    fetch_eligible_primary_candles,
    fetch_map_geometry_by_id,
    fetch_scope_status_projection,
    select_gate_decision,
)
from src.market_data.native_short_map_level_status_v1 import (
    NativeShortMapLevelState,
    V1_NATIVE_SHORT_SELL_LEVEL_ROLES,
)
from src.market_data.native_short_map_level_target_event_v1 import (
    NativeShortMapLevelTargetEvent,
    NativeShortMapLevelTargetEventType,
    fetch_native_short_map_level_target_events_for_map,
    find_first_causal_passed_candle,
    find_first_causal_reached_candle,
    insert_native_short_map_level_target_events,
    is_map_target_event_coverage_eligible,
    project_level_target_state_from_event_types,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import validate_native_short_scope_key
from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterProvenance,
    validate_native_short_writer_provenance,
)
from src.operations.writer_capability_authorization_v1 import WriterMutationAuthorization

__all__ = [
    "MAP_NOT_COVERED",
    "NOT_ACTIVE_EVALUATION",
    "NativeShortMapLevelTargetEventMaterializationOutcome",
    "build_new_target_events_for_role",
    "materialize_native_short_map_level_target_events_for_scope",
]

MAP_NOT_COVERED = "MAP_NOT_COVERED"
NOT_ACTIVE_EVALUATION = "NOT_ACTIVE_EVALUATION"

WRITER_NAME = "native_short_map_level_target_event_materializer_v1"
WRITER_VERSION = "0.1"


@dataclass(frozen=True)
class NativeShortMapLevelTargetEventMaterializationOutcome:
    key: NativeShortMapScopeKey
    map_id: int | None
    map_cycle_id: str | None
    coverage_eligible: bool
    skip_reason: str | None
    events_appended: int
    events_already_present: int
    level_state_by_role: dict[str, str]


def build_new_target_events_for_role(
    *,
    key: NativeShortMapScopeKey,
    map_id: int,
    map_cycle_id: str,
    role: Any,
    level_price: Decimal,
    eligible_candles: tuple[Candle, ...],
    already_recorded_types: set[NativeShortMapLevelTargetEventType],
    writer_invocation_uuid: str,
) -> tuple[NativeShortMapLevelTargetEvent, ...]:
    """Pure: determine which new (REACHED/PASSED) events this role now needs.

    Deterministic and idempotent: given the same map, geometry, eligible
    candle set, and already-recorded event types, this always returns the
    same result, including an empty tuple once every applicable event has
    already been recorded.
    """
    state, _reason = classify_level_state(level_price, eligible_candles)
    events: list[NativeShortMapLevelTargetEvent] = []

    if state == NativeShortMapLevelState.ACTIVE:
        return ()

    passed_candle = find_first_causal_passed_candle(level_price, eligible_candles)
    reached_candle = find_first_causal_reached_candle(level_price, eligible_candles)

    if state == NativeShortMapLevelState.REACHED:
        if (
            NativeShortMapLevelTargetEventType.REACHED not in already_recorded_types
            and reached_candle is not None
        ):
            events.append(
                NativeShortMapLevelTargetEvent(
                    key=key,
                    map_id=map_id,
                    map_cycle_id=map_cycle_id,
                    canonical_map_level_role=role,
                    side="SELL",
                    canonical_unrounded_price=level_price,
                    target_event_type=NativeShortMapLevelTargetEventType.REACHED,
                    causal_candle_close_ts_utc=reached_candle.close_ts_utc,
                    causal_candle_high_price=reached_candle.high_price,
                    causal_candle_close_price=None,
                    effective_at_utc=reached_candle.close_ts_utc,
                    reason_code="PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE",
                    writer_invocation_uuid=writer_invocation_uuid,
                    writer_name=WRITER_NAME,
                    writer_version=WRITER_VERSION,
                )
            )
        return tuple(events)

    # state == PASSED
    if passed_candle is None:
        return ()

    same_candle = reached_candle is not None and reached_candle.close_ts_utc == passed_candle.close_ts_utc
    reached_before_passed = (
        reached_candle is not None and reached_candle.close_ts_utc < passed_candle.close_ts_utc
    )

    if (
        NativeShortMapLevelTargetEventType.REACHED not in already_recorded_types
        and reached_before_passed
    ):
        events.append(
            NativeShortMapLevelTargetEvent(
                key=key,
                map_id=map_id,
                map_cycle_id=map_cycle_id,
                canonical_map_level_role=role,
                side="SELL",
                canonical_unrounded_price=level_price,
                target_event_type=NativeShortMapLevelTargetEventType.REACHED,
                causal_candle_close_ts_utc=reached_candle.close_ts_utc,
                causal_candle_high_price=reached_candle.high_price,
                causal_candle_close_price=None,
                effective_at_utc=reached_candle.close_ts_utc,
                reason_code="PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE",
                writer_invocation_uuid=writer_invocation_uuid,
                writer_name=WRITER_NAME,
                writer_version=WRITER_VERSION,
            )
        )

    if NativeShortMapLevelTargetEventType.PASSED not in already_recorded_types:
        events.append(
            NativeShortMapLevelTargetEvent(
                key=key,
                map_id=map_id,
                map_cycle_id=map_cycle_id,
                canonical_map_level_role=role,
                side="SELL",
                canonical_unrounded_price=level_price,
                target_event_type=NativeShortMapLevelTargetEventType.PASSED,
                causal_candle_close_ts_utc=passed_candle.close_ts_utc,
                causal_candle_high_price=None,
                causal_candle_close_price=passed_candle.close_price,
                effective_at_utc=passed_candle.close_ts_utc,
                reason_code="PRIMARY_CLOSE_PASSED_LEVEL",
                writer_invocation_uuid=writer_invocation_uuid,
                writer_name=WRITER_NAME,
                writer_version=WRITER_VERSION,
                same_candle_reached_skipped=same_candle,
            )
        )

    return tuple(events)


def materialize_native_short_map_level_target_events_for_scope(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    target_event_coverage_watermark_utc: datetime,
    provenance: NativeShortWriterProvenance,
    authorization: WriterMutationAuthorization,
) -> NativeShortMapLevelTargetEventMaterializationOutcome:
    """Bounded, single-scope target-event append. Caller owns the transaction.

    Reads the same scope-status projection and immutable map geometry as
    native_short_map_level_status_materializer_v1 (no independent map
    selection), computes the same classify_level_state decision from the same
    persisted closed 4h candles, and appends only the REACHED/PASSED events
    not already recorded for the exact map-level identity. Fails closed to
    MAP_NOT_COVERED for any map published before the explicit watermark, and
    to NOT_ACTIVE_EVALUATION for any non-active-evaluation branch (terminal or
    blocked), appending no events in either case.
    """
    validate_native_short_writer_provenance(provenance)
    validate_native_short_scope_key(key)

    projection = fetch_scope_status_projection(conn, key)
    if projection is None:
        return NativeShortMapLevelTargetEventMaterializationOutcome(
            key=key,
            map_id=None,
            map_cycle_id=None,
            coverage_eligible=False,
            skip_reason="PROJECTION_MISSING",
            events_appended=0,
            events_already_present=0,
            level_state_by_role={},
        )

    branch, _reason = select_gate_decision(projection)
    if branch != ACTIVE_EVALUATION:
        return NativeShortMapLevelTargetEventMaterializationOutcome(
            key=key,
            map_id=projection.current_map_id,
            map_cycle_id=projection.current_map_cycle_id,
            coverage_eligible=False,
            skip_reason=NOT_ACTIVE_EVALUATION,
            events_appended=0,
            events_already_present=0,
            level_state_by_role={},
        )

    map_record = fetch_map_geometry_by_id(conn, key, projection.current_map_id)
    if map_record is None or map_record.map_cycle_id != projection.current_map_cycle_id:
        return NativeShortMapLevelTargetEventMaterializationOutcome(
            key=key,
            map_id=projection.current_map_id,
            map_cycle_id=projection.current_map_cycle_id,
            coverage_eligible=False,
            skip_reason="PROJECTION_INVALID",
            events_appended=0,
            events_already_present=0,
            level_state_by_role={},
        )

    coverage_eligible = is_map_target_event_coverage_eligible(
        map_record, coverage_watermark_utc=target_event_coverage_watermark_utc
    )
    if not coverage_eligible:
        return NativeShortMapLevelTargetEventMaterializationOutcome(
            key=key,
            map_id=map_record.map_id,
            map_cycle_id=map_record.map_cycle_id,
            coverage_eligible=False,
            skip_reason=MAP_NOT_COVERED,
            events_appended=0,
            events_already_present=0,
            level_state_by_role={
                role.value: "LEGACY_UNAVAILABLE" for role in V1_NATIVE_SHORT_SELL_LEVEL_ROLES
            },
        )

    geometry = extract_v1_sell_geometry(map_record)
    eligible_candles = fetch_eligible_primary_candles(
        conn,
        key,
        since_utc=map_record.anchor_high_ts_utc,
        until_utc=projection.projection_as_of_utc,
    )

    existing_rows = fetch_native_short_map_level_target_events_for_map(conn, map_id=map_record.map_id)
    existing_by_role: dict[str, set[NativeShortMapLevelTargetEventType]] = {}
    for row in existing_rows:
        role_key = str(row["canonical_map_level_role"])
        existing_by_role.setdefault(role_key, set()).add(
            NativeShortMapLevelTargetEventType(str(row["target_event_type"]))
        )

    events_appended = 0
    events_already_present = 0
    level_state_by_role: dict[str, str] = {}

    for role in V1_NATIVE_SHORT_SELL_LEVEL_ROLES:
        level_price = geometry[role]
        already_recorded = existing_by_role.get(role.value, set())
        new_events = build_new_target_events_for_role(
            key=key,
            map_id=map_record.map_id,
            map_cycle_id=map_record.map_cycle_id or "",
            role=role,
            level_price=level_price,
            eligible_candles=eligible_candles,
            already_recorded_types=already_recorded,
            writer_invocation_uuid=provenance.invocation_uuid,
        )
        events_already_present += len(existing_by_role.get(role.value, set()))
        if new_events:
            written = insert_native_short_map_level_target_events(
                conn,
                events=new_events,
                provenance=provenance,
                authorization=authorization,
            )
            events_appended += written
            already_recorded = already_recorded | {
                NativeShortMapLevelTargetEventType(_ev.target_event_type)
                for _ev in new_events
            }
        level_state_by_role[role.value] = str(
            project_level_target_state_from_event_types(already_recorded, covered=True)
        )

    return NativeShortMapLevelTargetEventMaterializationOutcome(
        key=key,
        map_id=map_record.map_id,
        map_cycle_id=map_record.map_cycle_id,
        coverage_eligible=True,
        skip_reason=None,
        events_appended=events_appended,
        events_already_present=events_already_present,
        level_state_by_role=level_state_by_role,
    )
