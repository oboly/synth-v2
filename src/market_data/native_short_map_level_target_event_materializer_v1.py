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
  (classify_level_state, extract_v1_sell_geometry,
  fetch_eligible_primary_candles). This module does not introduce a second
  independent lifecycle-decision function; it only durably records that same
  decision -- restricted to the immutable per-map causal cutoff -- as an
  append-only event.
- ``append_native_short_map_level_target_events_for_map`` is the single,
  shared write authority for target events. It is invoked from two call
  sites: the standalone per-symbol wrapper below (used by the manual runner,
  gated to ACTIVE_EVALUATION only), and the integrated scope-status
  materializer's terminal-transition hook
  (native_short_scope_status_materializer_v1._append_terminal_target_events),
  which calls it directly for a map about to be marked COMPLETED, in the same
  transaction and before the terminal lifecycle event is recorded. There is
  no third, independently-computed target-event authority anywhere.
- A map's target-event coverage is durable, persisted, per-map state (see
  native_short_map_level_target_event_v1.establish_or_fetch_target_event_coverage_for_map).
  Coverage is established at most once per map_id; its immutable
  ``coverage_cutoff_utc`` (>= both the map's publication boundary and the
  approved watermark in effect at establishment) is read on every subsequent
  run and never recomputed. A candle before that cutoff can never create a
  target event, regardless of what a later run's watermark parameter is.
  A map for which coverage was never established (e.g. it went terminal
  before this feature was ever invoked against it) remains uncovered forever
  -- LEGACY_UNAVAILABLE, never a silent ACTIVE default.
- Caller owns the transaction boundary. This module performs no independent
  commit/rollback so it can be invoked in the same transaction as the
  existing native_short_map_level_status_v1 row rebuild, or as part of the
  scope-status materializer's terminal-transition transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.market_data.native_short_fib_context_v1 import Candle
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapRecord, NativeShortMapScopeKey
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
    LEGACY_UNAVAILABLE,
    NativeShortMapLevelTargetEvent,
    NativeShortMapLevelTargetEventType,
    establish_or_fetch_target_event_coverage_for_map,
    fetch_native_short_map_level_target_events_for_map,
    fetch_target_event_coverage_for_map,
    filter_candles_from_cutoff,
    find_first_causal_passed_candle,
    find_first_causal_reached_candle,
    insert_native_short_map_level_target_events,
    project_level_target_state_from_event_types,
)
from src.market_data.native_short_scope_status_v1 import validate_native_short_scope_key
from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterProvenance,
    validate_native_short_writer_provenance,
)
from src.operations.writer_capability_authorization_v1 import WriterMutationAuthorization

__all__ = [
    "NO_WATERMARK_SUPPLIED",
    "NOT_ACTIVE_EVALUATION",
    "NativeShortMapLevelTargetEventMaterializationOutcome",
    "append_native_short_map_level_target_events_for_map",
    "build_new_target_events_for_role",
    "materialize_native_short_map_level_target_events_for_scope",
]

NO_WATERMARK_SUPPLIED = "NO_WATERMARK_SUPPLIED"
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
    requested_watermark_utc: datetime | None = None
    publication_boundary_utc: datetime | None = None
    persisted_coverage_cutoff_utc: datetime | None = None


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

    ``eligible_candles`` must already be restricted to the immutable per-map
    causal cutoff (see ``filter_candles_from_cutoff``) by the caller -- this
    function has no notion of a cutoff itself; it only ever looks at the
    candles it is given.

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


def append_native_short_map_level_target_events_for_map(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    map_record: NativeShortMapRecord,
    event_candle_window_until_utc: datetime,
    requested_watermark_utc: datetime | None,
    provenance: NativeShortWriterProvenance,
    authorization: WriterMutationAuthorization,
) -> NativeShortMapLevelTargetEventMaterializationOutcome:
    """Shared core: get-or-establish coverage, then append eligible events.

    This is the sole place target events are computed and appended anywhere
    in the codebase. Both the standalone per-symbol wrapper below and the
    scope-status materializer's terminal-transition hook call this function
    directly with an already-fetched, exact ``map_record`` -- neither
    re-derives the REACHED/PASSED decision independently.

    If no coverage row exists yet for this exact map_id and
    ``requested_watermark_utc`` is ``None``, this is a no-op: no coverage row
    is created and no events are appended (byte-for-byte the same as if this
    function were never called). If a coverage row already exists, the
    persisted ``coverage_cutoff_utc`` is used and ``requested_watermark_utc``
    is ignored for cutoff purposes (it can never rewrite an established
    cutoff).
    """
    validate_native_short_writer_provenance(provenance)
    validate_native_short_scope_key(key)

    existing_coverage = fetch_target_event_coverage_for_map(conn, map_id=map_record.map_id)
    if existing_coverage is None:
        if requested_watermark_utc is None:
            return NativeShortMapLevelTargetEventMaterializationOutcome(
                key=key,
                map_id=map_record.map_id,
                map_cycle_id=map_record.map_cycle_id,
                coverage_eligible=False,
                skip_reason=NO_WATERMARK_SUPPLIED,
                events_appended=0,
                events_already_present=0,
                level_state_by_role={
                    role.value: LEGACY_UNAVAILABLE for role in V1_NATIVE_SHORT_SELL_LEVEL_ROLES
                },
                requested_watermark_utc=None,
                publication_boundary_utc=map_record.published_at_utc,
                persisted_coverage_cutoff_utc=None,
            )
        coverage = establish_or_fetch_target_event_coverage_for_map(
            conn,
            key=key,
            map_record=map_record,
            requested_watermark_utc=requested_watermark_utc,
            provenance=provenance,
            authorization=authorization,
        )
    else:
        coverage = existing_coverage

    geometry = extract_v1_sell_geometry(map_record)
    full_eligible_candles = fetch_eligible_primary_candles(
        conn,
        key,
        since_utc=map_record.anchor_high_ts_utc,
        until_utc=event_candle_window_until_utc,
    )
    event_eligible_candles = filter_candles_from_cutoff(
        full_eligible_candles, cutoff_utc=coverage.coverage_cutoff_utc
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
        events_already_present += len(already_recorded)
        new_events = build_new_target_events_for_role(
            key=key,
            map_id=map_record.map_id,
            map_cycle_id=map_record.map_cycle_id or "",
            role=role,
            level_price=level_price,
            eligible_candles=event_eligible_candles,
            already_recorded_types=already_recorded,
            writer_invocation_uuid=provenance.invocation_uuid,
        )
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
        requested_watermark_utc=requested_watermark_utc,
        publication_boundary_utc=map_record.published_at_utc,
        persisted_coverage_cutoff_utc=coverage.coverage_cutoff_utc,
    )


def materialize_native_short_map_level_target_events_for_scope(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    target_event_coverage_watermark_utc: datetime | None,
    provenance: NativeShortWriterProvenance,
    authorization: WriterMutationAuthorization,
) -> NativeShortMapLevelTargetEventMaterializationOutcome:
    """Bounded, single-scope target-event append. Caller owns the transaction.

    Reads the same scope-status projection and immutable map geometry as
    native_short_map_level_status_materializer_v1 (no independent map
    selection), then delegates to ``append_native_short_map_level_target_events_for_map``
    -- the single shared write authority -- for any map currently in
    ACTIVE_EVALUATION. Fails closed to NOT_ACTIVE_EVALUATION for any
    non-active-evaluation branch (terminal or blocked), appending no events.
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

    # This lane only asks whether the gate is ACTIVE_EVALUATION; every other
    # branch is treated identically (NOT_ACTIVE_EVALUATION, no events). The
    # #298 bootstrap/BLOCKED split is therefore immaterial here, and passing
    # False preserves the pre-#298 classification exactly with no extra query.
    branch, _reason = select_gate_decision(projection, never_published_any_map=False)
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

    return append_native_short_map_level_target_events_for_map(
        conn,
        key=key,
        map_record=map_record,
        event_candle_window_until_utc=projection.projection_as_of_utc,
        requested_watermark_utc=target_event_coverage_watermark_utc,
        provenance=provenance,
        authorization=authorization,
    )
