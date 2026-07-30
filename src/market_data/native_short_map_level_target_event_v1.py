from __future__ import annotations

"""Native SHORT map-level target-event append-only persistence contract.

Authorization boundary (read before extending this module):

    This module implements *prospective* target-event lifecycle history,
    authorized under the Synth Outcome & Reliability Program as a required
    foundation for reproducible outcome attribution of *future* target
    transitions. It is explicitly NOT authorized as, and must never be
    treated as, evidence that:

        - the earlier IOST reporting-bridge case was a canonical lifecycle
          defect (it was proven NOT to be one);
        - BTC has exhibited a REACHED/PASSED-then-pullback regression (it has
          not, per the accepted forensic audit);
        - existing historical target transitions on already-active maps can
          be reconstructed losslessly.

    See docs/todo/profit_plan_target_lifecycle_history_truth_v1.md and
    docs/todo/native_short_map_level_status_v1.md for the retained,
    unmodified evidence-gate record this authorization sits alongside.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none

Boundary:
- Market-only, account-agnostic, append-only event ledger for native SHORT
  V1 SELL canonical target-level transitions (REACHED, PASSED only; no
  ACTIVE event -- ACTIVE is defined as the absence of a terminal event).
- Defines the event dataclass, closed enums, deterministic identity
  validation, a pure event-sourced projection reducer, and thin MariaDB
  persistence helpers.
- Does not select maps, does not evaluate candles, does not read wall-clock
  time as a lifecycle input, does not mutate immutable map geometry, and
  does not import reporting/account/broker/decision/execution/executor/
  selection_engine code.
- Every event is immutable once persisted: this module never issues an
  UPDATE against the event table. The database unique identity constraint
  (map_id, canonical_map_level_role, side, canonical_unrounded_price,
  target_event_type) is the sole duplicate-write fence; a duplicate insert
  attempt is rejected by the database and treated by callers as an
  idempotent no-op, never as a mutation of the original row.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable, Sequence

from src.market_data.native_short_fib_context_v1 import Candle
from src.market_data.native_short_map_level_status_v1 import (
    NativeShortMapLevelRole,
    NativeShortMapLevelSide,
    NativeShortMapLevelState,
    REASON_PRIMARY_CLOSE_PASSED_LEVEL,
    REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapRecord, NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import validate_native_short_scope_key
from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterProvenance,
    validate_native_short_writer_provenance,
)
from src.operations.writer_capability_authorization_v1 import (
    WriterMutationAuthorization,
    require_writer_mutation_authorization,
)

__all__ = [
    "EVALUATION_REFERENCE",
    "LEGACY_UNAVAILABLE",
    "NativeShortMapLevelTargetEvent",
    "NativeShortMapLevelTargetEventPersistenceError",
    "NativeShortMapLevelTargetEventType",
    "NativeShortMapLevelTargetIdentity",
    "find_first_causal_reached_candle",
    "find_first_causal_passed_candle",
    "insert_native_short_map_level_target_events",
    "is_map_target_event_coverage_eligible",
    "fetch_native_short_map_level_target_events_for_map",
    "project_level_target_state_from_event_types",
    "project_level_target_state_from_events",
    "serialize_native_short_map_level_target_event",
    "validate_native_short_map_level_target_event",
]

EVALUATION_REFERENCE = "PRIMARY_4H_CLOSED_CANDLES"
LEGACY_UNAVAILABLE = "LEGACY_UNAVAILABLE"

_ALLOWED_REASON_CODES = frozenset(
    {
        REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
        REASON_PRIMARY_CLOSE_PASSED_LEVEL,
    }
)


class NativeShortMapLevelTargetEventPersistenceError(ValueError):
    pass


class NativeShortMapLevelTargetEventType(StrEnum):
    REACHED = "REACHED"
    PASSED = "PASSED"


_REQUIRED_REASON_BY_TYPE = {
    NativeShortMapLevelTargetEventType.REACHED: REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
    NativeShortMapLevelTargetEventType.PASSED: REASON_PRIMARY_CLOSE_PASSED_LEVEL,
}


def _enum_value(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


def _coerce_enum(value: StrEnum | str, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        raise NativeShortMapLevelTargetEventPersistenceError(
            f"INVALID_ENUM field={field_name} value={value}"
        ) from exc


def _require_utc(value: datetime | None, field_name: str) -> datetime:
    if value is None:
        raise NativeShortMapLevelTargetEventPersistenceError(f"REQUIRED_TIMESTAMP_MISSING field={field_name}")
    offset = value.utcoffset()
    if value.tzinfo is None or offset != timedelta(0):
        raise NativeShortMapLevelTargetEventPersistenceError(f"TIMESTAMP_NOT_UTC field={field_name}")
    return value


def _require_positive_decimal(value: Decimal | str | int | None, field_name: str) -> Decimal:
    if value is None:
        raise NativeShortMapLevelTargetEventPersistenceError(f"REQUIRED_DECIMAL_MISSING field={field_name}")
    coerced = value if isinstance(value, Decimal) else Decimal(str(value))
    if coerced <= 0:
        raise NativeShortMapLevelTargetEventPersistenceError(f"DECIMAL_NOT_POSITIVE field={field_name}")
    return coerced


def _require_text(value: str | None, field_name: str, *, maximum: int = 255) -> str:
    if value is None or not str(value).strip():
        raise NativeShortMapLevelTargetEventPersistenceError(f"REQUIRED_FIELD_MISSING field={field_name}")
    normalized = str(value)
    if len(normalized) > maximum:
        raise NativeShortMapLevelTargetEventPersistenceError(f"FIELD_TOO_LONG field={field_name}")
    return normalized


@dataclass(frozen=True)
class NativeShortMapLevelTargetIdentity:
    """Deterministic structured target identity. No free-text symbol matching."""

    map_id: int
    canonical_map_level_role: NativeShortMapLevelRole | str
    side: NativeShortMapLevelSide | str
    canonical_unrounded_price: Decimal


@dataclass(frozen=True)
class NativeShortMapLevelTargetEvent:
    key: NativeShortMapScopeKey
    map_id: int
    map_cycle_id: str
    canonical_map_level_role: NativeShortMapLevelRole | str
    side: NativeShortMapLevelSide | str
    canonical_unrounded_price: Decimal
    target_event_type: NativeShortMapLevelTargetEventType | str
    causal_candle_close_ts_utc: datetime
    causal_candle_high_price: Decimal | None
    causal_candle_close_price: Decimal | None
    effective_at_utc: datetime
    reason_code: str
    writer_invocation_uuid: str
    writer_name: str
    writer_version: str
    same_candle_reached_skipped: bool = False
    recorded_at_utc: datetime | None = None
    event_metadata_json: str | None = None
    target_event_id: int | None = None

    def __post_init__(self) -> None:
        validate_native_short_map_level_target_event(self)


def validate_native_short_map_level_target_event(
    event: NativeShortMapLevelTargetEvent,
) -> NativeShortMapLevelTargetEvent:
    validate_native_short_scope_key(event.key)
    if event.map_id <= 0:
        raise NativeShortMapLevelTargetEventPersistenceError("COUNT_NOT_POSITIVE field=map_id")
    _require_text(event.map_cycle_id, "map_cycle_id")
    _coerce_enum(event.canonical_map_level_role, NativeShortMapLevelRole, "canonical_map_level_role")
    side = _coerce_enum(event.side, NativeShortMapLevelSide, "side")
    if side != NativeShortMapLevelSide.SELL:
        raise NativeShortMapLevelTargetEventPersistenceError(f"INVALID_SIDE value={side}")
    _require_positive_decimal(event.canonical_unrounded_price, "canonical_unrounded_price")
    event_type = _coerce_enum(event.target_event_type, NativeShortMapLevelTargetEventType, "target_event_type")
    _require_utc(event.causal_candle_close_ts_utc, "causal_candle_close_ts_utc")
    effective_at = _require_utc(event.effective_at_utc, "effective_at_utc")
    if effective_at != event.causal_candle_close_ts_utc:
        raise NativeShortMapLevelTargetEventPersistenceError(
            "EFFECTIVE_AT_MUST_EQUAL_CAUSAL_CANDLE_CLOSE"
        )
    if event.reason_code not in _ALLOWED_REASON_CODES:
        raise NativeShortMapLevelTargetEventPersistenceError(
            f"INVALID_REASON_CODE value={event.reason_code}"
        )
    required_reason = _REQUIRED_REASON_BY_TYPE[NativeShortMapLevelTargetEventType(_enum_value(event_type))]
    if event.reason_code != required_reason:
        raise NativeShortMapLevelTargetEventPersistenceError(
            f"REASON_CODE_MISMATCH_FOR_TYPE type={event_type} reason={event.reason_code}"
        )
    if event_type == NativeShortMapLevelTargetEventType.REACHED:
        if event.causal_candle_high_price is None:
            raise NativeShortMapLevelTargetEventPersistenceError("REACHED_REQUIRES_CAUSAL_HIGH_PRICE")
        _require_positive_decimal(event.causal_candle_high_price, "causal_candle_high_price")
        if event.same_candle_reached_skipped:
            raise NativeShortMapLevelTargetEventPersistenceError(
                "REACHED_EVENT_CANNOT_SET_SAME_CANDLE_REACHED_SKIPPED"
            )
    else:
        if event.causal_candle_close_price is None:
            raise NativeShortMapLevelTargetEventPersistenceError("PASSED_REQUIRES_CAUSAL_CLOSE_PRICE")
        _require_positive_decimal(event.causal_candle_close_price, "causal_candle_close_price")
    _require_text(event.writer_invocation_uuid, "writer_invocation_uuid", maximum=36)
    _require_text(event.writer_name, "writer_name", maximum=96)
    _require_text(event.writer_version, "writer_version", maximum=32)
    if event.recorded_at_utc is not None:
        _require_utc(event.recorded_at_utc, "recorded_at_utc")
    return event


def serialize_native_short_map_level_target_event(
    event: NativeShortMapLevelTargetEvent,
) -> dict[str, Any]:
    validate_native_short_map_level_target_event(event)
    return {
        "venue": event.key.venue,
        "symbol": event.key.symbol,
        "quote_currency": event.key.quote_currency,
        "fib_trading_horizon": event.key.fib_trading_horizon,
        "primary_interval": event.key.primary_interval,
        "supporting_interval": event.key.supporting_interval,
        "map_id": event.map_id,
        "map_cycle_id": event.map_cycle_id,
        "canonical_map_level_role": _enum_value(event.canonical_map_level_role),
        "side": _enum_value(event.side),
        "canonical_unrounded_price": str(event.canonical_unrounded_price),
        "target_event_type": _enum_value(event.target_event_type),
        "causal_candle_close_ts_utc": event.causal_candle_close_ts_utc,
        "causal_candle_high_price": (
            None if event.causal_candle_high_price is None else str(event.causal_candle_high_price)
        ),
        "causal_candle_close_price": (
            None if event.causal_candle_close_price is None else str(event.causal_candle_close_price)
        ),
        "effective_at_utc": event.effective_at_utc,
        "evaluation_reference": EVALUATION_REFERENCE,
        "reason_code": event.reason_code,
        "writer_name": event.writer_name,
        "writer_version": event.writer_version,
        "writer_invocation_uuid": event.writer_invocation_uuid,
        "same_candle_reached_skipped": 1 if event.same_candle_reached_skipped else 0,
        "event_metadata_json": event.event_metadata_json,
    }


# ---------------------------------------------------------------------------
# Pure causal-candle discovery and event-sourced reducer
# ---------------------------------------------------------------------------


def find_first_causal_reached_candle(
    level_price: Decimal,
    eligible_candles: Sequence[Candle],
) -> Candle | None:
    """Earliest eligible closed candle whose high touches/exceeds the level."""
    candidates = sorted(
        (c for c in eligible_candles if c.high_price >= level_price),
        key=lambda c: c.close_ts_utc,
    )
    return candidates[0] if candidates else None


def find_first_causal_passed_candle(
    level_price: Decimal,
    eligible_candles: Sequence[Candle],
) -> Candle | None:
    """Earliest eligible closed candle whose close is strictly above the level."""
    candidates = sorted(
        (c for c in eligible_candles if c.close_price > level_price),
        key=lambda c: c.close_ts_utc,
    )
    return candidates[0] if candidates else None


def is_map_target_event_coverage_eligible(
    map_record: NativeShortMapRecord,
    *,
    coverage_watermark_utc: datetime,
) -> bool:
    """A map is target-event-eligible only if published at/after the watermark.

    This is the explicit, conservative prospective activation boundary: maps
    published before the watermark remain LEGACY_UNAVAILABLE for target-event
    purposes even though their existing native_short_map_level_status_v1
    current-projection behavior is completely unchanged. The watermark must be
    supplied explicitly by the caller; there is no implicit default that would
    silently treat all history as covered.
    """
    _require_utc(coverage_watermark_utc, "coverage_watermark_utc")
    published_at_utc = map_record.published_at_utc
    if published_at_utc is None:
        return False
    published_at_utc = (
        published_at_utc if published_at_utc.tzinfo is not None else published_at_utc
    )
    return published_at_utc >= coverage_watermark_utc


def project_level_target_state_from_event_types(
    event_types: Iterable[NativeShortMapLevelTargetEventType | str],
    *,
    covered: bool,
) -> NativeShortMapLevelState | str:
    """Deterministic reducer core: current level state from a set of recorded
    target-event types only (no candle re-scan). Missing source data becomes
    LEGACY_UNAVAILABLE, never a silent ACTIVE default, whenever the level
    identity is not target-event-covered.
    """
    if not covered:
        return LEGACY_UNAVAILABLE
    types = {NativeShortMapLevelTargetEventType(_enum_value(t)) for t in event_types}
    if NativeShortMapLevelTargetEventType.PASSED in types:
        return NativeShortMapLevelState.PASSED
    if NativeShortMapLevelTargetEventType.REACHED in types:
        return NativeShortMapLevelState.REACHED
    return NativeShortMapLevelState.ACTIVE


def project_level_target_state_from_events(
    events: Iterable[NativeShortMapLevelTargetEvent],
    *,
    covered: bool,
) -> NativeShortMapLevelState | str:
    """Deterministic reducer: current level state from geometry-scoped events only.

    This is the reproducibility proof surface: for a covered map-level
    identity, this function applied to its persisted events must always equal
    the state most recently computed (and durably recorded as events) by the
    causal-candle evaluator in native_short_map_level_status_materializer_v1.
    """
    event_types = (e.target_event_type for e in events)
    return project_level_target_state_from_event_types(event_types, covered=covered)


# ---------------------------------------------------------------------------
# MariaDB persistence layer
# ---------------------------------------------------------------------------


def fetch_native_short_map_level_target_events_for_map(
    conn: Any,
    *,
    map_id: int,
) -> tuple[dict[str, Any], ...]:
    sql = """
    SELECT map_id, map_cycle_id, canonical_map_level_role, side,
           canonical_unrounded_price, target_event_type,
           causal_candle_close_ts_utc, causal_candle_high_price, causal_candle_close_price,
           effective_at_utc, recorded_at_utc, reason_code,
           writer_name, writer_version, writer_invocation_uuid,
           same_candle_reached_skipped, target_event_id
    FROM native_short_map_level_target_event_v1
    WHERE map_id = %s
    ORDER BY target_event_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (map_id,))
        rows = list(cur.fetchall())
    return tuple(dict(row) for row in rows)


def insert_native_short_map_level_target_events(
    conn: Any,
    *,
    events: Iterable[NativeShortMapLevelTargetEvent],
    provenance: NativeShortWriterProvenance,
    authorization: WriterMutationAuthorization,
) -> int:
    """Append-only insert. Never issues UPDATE. Duplicate identity is rejected
    by the database unique constraint; callers must treat an IntegrityError on
    this exact identity as an idempotent no-op, never as a retry-with-mutation.
    """
    validate_native_short_writer_provenance(provenance)
    require_writer_mutation_authorization(authorization, "native_short_4h_chain")

    materialized = [validate_native_short_map_level_target_event(event) for event in events]
    if not materialized:
        return 0

    sql = """
    INSERT INTO native_short_map_level_target_event_v1 (
        venue, symbol, quote_currency, fib_trading_horizon,
        primary_interval, supporting_interval,
        map_id, map_cycle_id,
        canonical_map_level_role, side, canonical_unrounded_price,
        target_event_type,
        causal_candle_close_ts_utc, causal_candle_high_price, causal_candle_close_price,
        effective_at_utc, evaluation_reference, reason_code,
        writer_name, writer_version, writer_invocation_uuid,
        same_candle_reached_skipped, event_metadata_json
    ) VALUES (
        %(venue)s, %(symbol)s, %(quote_currency)s, %(fib_trading_horizon)s,
        %(primary_interval)s, %(supporting_interval)s,
        %(map_id)s, %(map_cycle_id)s,
        %(canonical_map_level_role)s, %(side)s, %(canonical_unrounded_price)s,
        %(target_event_type)s,
        %(causal_candle_close_ts_utc)s, %(causal_candle_high_price)s, %(causal_candle_close_price)s,
        %(effective_at_utc)s, %(evaluation_reference)s, %(reason_code)s,
        %(writer_name)s, %(writer_version)s, %(writer_invocation_uuid)s,
        %(same_candle_reached_skipped)s, %(event_metadata_json)s
    )
    """
    written = 0
    for event in materialized:
        serialized = serialize_native_short_map_level_target_event(event)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, serialized)
                written += int(getattr(cur, "rowcount", 0) or 1)
        except Exception as exc:  # noqa: BLE001 - duplicate-identity idempotency guard
            if _is_duplicate_key_error(exc):
                continue
            raise
    return written


def _is_duplicate_key_error(exc: Exception) -> bool:
    try:
        from pymysql.err import IntegrityError

        if isinstance(exc, IntegrityError):
            args = exc.args
            return bool(args) and args[0] in (1062,)
    except ImportError:
        pass
    return False
