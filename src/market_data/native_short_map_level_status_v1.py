from __future__ import annotations

"""Native SHORT current map-level status persistence contract.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none

Boundary:
- Market-only, account-agnostic, rebuildable current read model.
- Defines V1 row types, validation, row serialization, and thin MariaDB
  persistence helpers for ``native_short_map_level_status_v1``.
- Does not select maps, evaluate candles, read wall-clock time, mutate immutable
  map geometry, or integrate with reporting/runtime runners.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable

from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterProvenance,
    validate_native_short_writer_provenance,
)
from src.market_data.native_short_scope_status_v1 import (
    NativeShortScopeActionabilityState,
    NativeShortScopeMapLifecycleState,
    NativeShortScopeStatusCode,
    validate_native_short_scope_key,
)
from src.market_rules.price_tick_normalization_v1 import (
    NORM_STATUS_APPLIED,
    NORM_STATUS_MISSING,
    TICK_RULE_SOURCE_DB,
    TICK_RULE_SOURCE_MISSING,
    TICK_RULE_SOURCE_STATIC,
)
from src.operations.writer_capability_authorization_v1 import (
    WriterMutationAuthorization,
    require_writer_mutation_authorization,
)

__all__ = [
    "ACTIVE_EVALUATION_REFERENCE",
    "MAP_LIFECYCLE_EVALUATION_REFERENCE",
    "NativeShortMapLevelRole",
    "NativeShortMapLevelSide",
    "NativeShortMapLevelStatusPersistenceError",
    "NativeShortMapLevelStatusRecord",
    "NativeShortMapLevelState",
    "NativeShortMapLevelEvaluationReference",
    "REASON_MAP_COMPLETED",
    "REASON_MAP_EXPIRED",
    "REASON_MAP_INVALIDATED",
    "REASON_NO_PRIMARY_HIGH_REACHED_LEVEL",
    "REASON_PRIMARY_CLOSE_PASSED_LEVEL",
    "REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE",
    "V1_NATIVE_SHORT_SELL_LEVEL_ROLES",
    "delete_native_short_map_level_status_for_scope",
    "replace_native_short_map_level_status_for_scope",
    "serialize_native_short_map_level_status_record",
    "validate_native_short_map_level_status_collection",
]

REASON_NO_PRIMARY_HIGH_REACHED_LEVEL = "NO_PRIMARY_HIGH_REACHED_LEVEL"
REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE = "PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE"
REASON_PRIMARY_CLOSE_PASSED_LEVEL = "PRIMARY_CLOSE_PASSED_LEVEL"
REASON_MAP_COMPLETED = "MAP_COMPLETED"
REASON_MAP_INVALIDATED = "MAP_INVALIDATED"
REASON_MAP_EXPIRED = "MAP_EXPIRED"

ACTIVE_EVALUATION_REFERENCE = "PRIMARY_4H_CLOSED_CANDLES"
MAP_LIFECYCLE_EVALUATION_REFERENCE = "MAP_LIFECYCLE_EVENT"

_ALLOWED_TICK_RULE_STATUSES = frozenset({NORM_STATUS_APPLIED, NORM_STATUS_MISSING})
_ALLOWED_TICK_RULE_SOURCES = frozenset(
    {TICK_RULE_SOURCE_DB, TICK_RULE_SOURCE_STATIC, TICK_RULE_SOURCE_MISSING}
)
_ALLOWED_REASON_CODES = frozenset(
    {
        REASON_NO_PRIMARY_HIGH_REACHED_LEVEL,
        REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
        REASON_PRIMARY_CLOSE_PASSED_LEVEL,
        REASON_MAP_COMPLETED,
        REASON_MAP_INVALIDATED,
        REASON_MAP_EXPIRED,
    }
)


class NativeShortMapLevelStatusPersistenceError(ValueError):
    pass


class NativeShortMapLevelRole(StrEnum):
    SELL_EXT_1_272 = "SELL_EXT_1_272"
    SELL_EXT_1_618 = "SELL_EXT_1_618"
    SELL_EXT_2_000 = "SELL_EXT_2_000"


class NativeShortMapLevelSide(StrEnum):
    SELL = "SELL"


class NativeShortMapLevelState(StrEnum):
    ACTIVE = "ACTIVE"
    REACHED = "REACHED"
    PASSED = "PASSED"
    COMPLETED = "COMPLETED"
    HISTORICAL = "HISTORICAL"


class NativeShortMapLevelEvaluationReference(StrEnum):
    PRIMARY_4H_CLOSED_CANDLES = ACTIVE_EVALUATION_REFERENCE
    MAP_LIFECYCLE_EVENT = MAP_LIFECYCLE_EVALUATION_REFERENCE


V1_NATIVE_SHORT_SELL_LEVEL_ROLES: tuple[NativeShortMapLevelRole, ...] = (
    NativeShortMapLevelRole.SELL_EXT_1_272,
    NativeShortMapLevelRole.SELL_EXT_1_618,
    NativeShortMapLevelRole.SELL_EXT_2_000,
)


def _coerce_enum(value: StrEnum | str, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        raise NativeShortMapLevelStatusPersistenceError(
            f"INVALID_ENUM field={field_name} value={value}"
        ) from exc


def _require_text(value: str | None, field_name: str) -> str:
    if value is None or not str(value).strip():
        raise NativeShortMapLevelStatusPersistenceError(f"REQUIRED_FIELD_MISSING field={field_name}")
    return str(value)


def _require_utc(value: datetime | None, field_name: str) -> datetime:
    if value is None:
        raise NativeShortMapLevelStatusPersistenceError(f"REQUIRED_TIMESTAMP_MISSING field={field_name}")
    offset = value.utcoffset()
    if value.tzinfo is None or offset != timedelta(0):
        raise NativeShortMapLevelStatusPersistenceError(f"TIMESTAMP_NOT_UTC field={field_name}")
    return value


def _require_positive_decimal(value: Decimal | str | int | None, field_name: str) -> Decimal:
    if value is None:
        raise NativeShortMapLevelStatusPersistenceError(f"REQUIRED_DECIMAL_MISSING field={field_name}")
    coerced = value if isinstance(value, Decimal) else Decimal(str(value))
    if coerced <= 0:
        raise NativeShortMapLevelStatusPersistenceError(f"DECIMAL_NOT_POSITIVE field={field_name}")
    return coerced


def _optional_positive_decimal(value: Decimal | str | int | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _require_positive_decimal(value, field_name)


def _enum_value(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


@dataclass(frozen=True)
class NativeShortMapLevelStatusRecord:
    key: NativeShortMapScopeKey
    current_map_id: int
    map_cycle_id: str
    canonical_map_level_role: NativeShortMapLevelRole | str
    side: NativeShortMapLevelSide | str
    canonical_unrounded_price: Decimal
    canonical_tick_rounded_price: Decimal | None
    tick_rule_status: str
    tick_rule_source: str
    level_lifecycle_state: NativeShortMapLevelState | str
    level_status_as_of_utc: datetime
    evaluation_reference: NativeShortMapLevelEvaluationReference | str
    reason_code: str
    projection_scope_status_code: NativeShortScopeStatusCode | str
    projection_map_lifecycle_state: NativeShortScopeMapLifecycleState | str
    projection_actionability_state: NativeShortScopeActionabilityState | str
    rebuilt_at_utc: datetime

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        if self.key.primary_interval != "4h":
            raise NativeShortMapLevelStatusPersistenceError(
                f"INVALID_PRIMARY_INTERVAL value={self.key.primary_interval}"
            )
        if self.key.supporting_interval != "1h":
            raise NativeShortMapLevelStatusPersistenceError(
                f"INVALID_SUPPORTING_INTERVAL value={self.key.supporting_interval}"
            )
        if self.current_map_id <= 0:
            raise NativeShortMapLevelStatusPersistenceError("COUNT_NOT_POSITIVE field=current_map_id")
        _require_text(self.map_cycle_id, "map_cycle_id")
        _coerce_enum(
            self.canonical_map_level_role,
            NativeShortMapLevelRole,
            "canonical_map_level_role",
        )
        side = _coerce_enum(self.side, NativeShortMapLevelSide, "side")
        if side != NativeShortMapLevelSide.SELL:
            raise NativeShortMapLevelStatusPersistenceError(f"INVALID_SIDE value={side}")
        _require_positive_decimal(self.canonical_unrounded_price, "canonical_unrounded_price")
        _optional_positive_decimal(
            self.canonical_tick_rounded_price,
            "canonical_tick_rounded_price",
        )
        if self.tick_rule_status not in _ALLOWED_TICK_RULE_STATUSES:
            raise NativeShortMapLevelStatusPersistenceError(
                f"INVALID_TICK_RULE_STATUS value={self.tick_rule_status}"
            )
        if self.tick_rule_source not in _ALLOWED_TICK_RULE_SOURCES:
            raise NativeShortMapLevelStatusPersistenceError(
                f"INVALID_TICK_RULE_SOURCE value={self.tick_rule_source}"
            )
        if self.tick_rule_status == NORM_STATUS_MISSING:
            if self.canonical_tick_rounded_price is not None:
                raise NativeShortMapLevelStatusPersistenceError(
                    "MISSING_TICK_RULE_REQUIRES_NULL_ROUNDED_PRICE"
                )
            if self.tick_rule_source != TICK_RULE_SOURCE_MISSING:
                raise NativeShortMapLevelStatusPersistenceError(
                    "MISSING_TICK_RULE_REQUIRES_MISSING_SOURCE"
                )
        else:
            if self.canonical_tick_rounded_price is None:
                raise NativeShortMapLevelStatusPersistenceError(
                    "APPLIED_TICK_RULE_REQUIRES_ROUNDED_PRICE"
                )
            if self.tick_rule_source == TICK_RULE_SOURCE_MISSING:
                raise NativeShortMapLevelStatusPersistenceError(
                    "APPLIED_TICK_RULE_REQUIRES_NON_MISSING_SOURCE"
                )
        state = _coerce_enum(
            self.level_lifecycle_state,
            NativeShortMapLevelState,
            "level_lifecycle_state",
        )
        evaluation_reference = _coerce_enum(
            self.evaluation_reference,
            NativeShortMapLevelEvaluationReference,
            "evaluation_reference",
        )
        _require_utc(self.level_status_as_of_utc, "level_status_as_of_utc")
        _require_utc(self.rebuilt_at_utc, "rebuilt_at_utc")
        if self.reason_code not in _ALLOWED_REASON_CODES:
            raise NativeShortMapLevelStatusPersistenceError(
                f"INVALID_REASON_CODE value={self.reason_code}"
            )
        scope_status = _coerce_enum(
            self.projection_scope_status_code,
            NativeShortScopeStatusCode,
            "projection_scope_status_code",
        )
        map_lifecycle = _coerce_enum(
            self.projection_map_lifecycle_state,
            NativeShortScopeMapLifecycleState,
            "projection_map_lifecycle_state",
        )
        actionability = _coerce_enum(
            self.projection_actionability_state,
            NativeShortScopeActionabilityState,
            "projection_actionability_state",
        )
        if state in {
            NativeShortMapLevelState.ACTIVE,
            NativeShortMapLevelState.REACHED,
            NativeShortMapLevelState.PASSED,
        }:
            if evaluation_reference != NativeShortMapLevelEvaluationReference.PRIMARY_4H_CLOSED_CANDLES:
                raise NativeShortMapLevelStatusPersistenceError(
                    "NON_TERMINAL_LEVEL_STATE_REQUIRES_PRIMARY_CANDLE_REFERENCE"
                )
            if map_lifecycle != NativeShortScopeMapLifecycleState.MAP_ACTIVE:
                raise NativeShortMapLevelStatusPersistenceError(
                    "NON_TERMINAL_LEVEL_STATE_REQUIRES_ACTIVE_MAP_PROJECTION"
                )
            if scope_status != NativeShortScopeStatusCode.CURRENT_EVALUATION:
                raise NativeShortMapLevelStatusPersistenceError(
                    "NON_TERMINAL_LEVEL_STATE_REQUIRES_CURRENT_EVALUATION"
                )
            if actionability != NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP:
                raise NativeShortMapLevelStatusPersistenceError(
                    "NON_TERMINAL_LEVEL_STATE_REQUIRES_ACTIONABLE_ACTIVE_MAP"
                )
        if state == NativeShortMapLevelState.COMPLETED:
            if evaluation_reference != NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT:
                raise NativeShortMapLevelStatusPersistenceError(
                    "TERMINAL_LEVEL_STATE_REQUIRES_MAP_LIFECYCLE_REFERENCE"
                )
            if map_lifecycle != NativeShortScopeMapLifecycleState.MAP_COMPLETED:
                raise NativeShortMapLevelStatusPersistenceError("COMPLETED_LEVEL_REQUIRES_COMPLETED_MAP")
            if scope_status != NativeShortScopeStatusCode.MAP_COMPLETED:
                raise NativeShortMapLevelStatusPersistenceError("COMPLETED_LEVEL_REQUIRES_MAP_COMPLETED_STATUS")
            if actionability != NativeShortScopeActionabilityState.TERMINAL_MAP:
                raise NativeShortMapLevelStatusPersistenceError("TERMINAL_LEVEL_REQUIRES_TERMINAL_MAP_ACTIONABILITY")
            if self.reason_code != REASON_MAP_COMPLETED:
                raise NativeShortMapLevelStatusPersistenceError("COMPLETED_LEVEL_REQUIRES_MAP_COMPLETED_REASON")
        if state == NativeShortMapLevelState.HISTORICAL:
            if evaluation_reference != NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT:
                raise NativeShortMapLevelStatusPersistenceError(
                    "TERMINAL_LEVEL_STATE_REQUIRES_MAP_LIFECYCLE_REFERENCE"
                )
            if map_lifecycle not in {
                NativeShortScopeMapLifecycleState.MAP_INVALIDATED,
                NativeShortScopeMapLifecycleState.MAP_EXPIRED,
            }:
                raise NativeShortMapLevelStatusPersistenceError("HISTORICAL_LEVEL_REQUIRES_TERMINAL_HISTORICAL_MAP")
            if actionability != NativeShortScopeActionabilityState.TERMINAL_MAP:
                raise NativeShortMapLevelStatusPersistenceError("TERMINAL_LEVEL_REQUIRES_TERMINAL_MAP_ACTIONABILITY")
            if map_lifecycle == NativeShortScopeMapLifecycleState.MAP_INVALIDATED and self.reason_code != REASON_MAP_INVALIDATED:
                raise NativeShortMapLevelStatusPersistenceError("INVALIDATED_HISTORICAL_LEVEL_REQUIRES_INVALIDATED_REASON")
            if map_lifecycle == NativeShortScopeMapLifecycleState.MAP_EXPIRED and self.reason_code != REASON_MAP_EXPIRED:
                raise NativeShortMapLevelStatusPersistenceError("EXPIRED_HISTORICAL_LEVEL_REQUIRES_EXPIRED_REASON")


def serialize_native_short_map_level_status_record(
    record: NativeShortMapLevelStatusRecord,
) -> dict[str, Any]:
    """Return a DB-ready dict with enum values and Decimal strings.

    This function intentionally performs no lifecycle evaluation and reads no
    external state. It only validates and serializes a fully provided row.
    """
    NativeShortMapLevelStatusRecord(**record.__dict__)
    return {
        "venue": record.key.venue,
        "symbol": record.key.symbol,
        "quote_currency": record.key.quote_currency,
        "fib_trading_horizon": record.key.fib_trading_horizon,
        "primary_interval": record.key.primary_interval,
        "supporting_interval": record.key.supporting_interval,
        "current_map_id": record.current_map_id,
        "map_cycle_id": record.map_cycle_id,
        "canonical_map_level_role": _enum_value(record.canonical_map_level_role),
        "side": _enum_value(record.side),
        "canonical_unrounded_price": str(record.canonical_unrounded_price),
        "canonical_tick_rounded_price": (
            None
            if record.canonical_tick_rounded_price is None
            else str(record.canonical_tick_rounded_price)
        ),
        "tick_rule_status": record.tick_rule_status,
        "tick_rule_source": record.tick_rule_source,
        "level_lifecycle_state": _enum_value(record.level_lifecycle_state),
        "level_status_as_of_utc": record.level_status_as_of_utc,
        "evaluation_reference": _enum_value(record.evaluation_reference),
        "reason_code": record.reason_code,
        "projection_scope_status_code": _enum_value(record.projection_scope_status_code),
        "projection_map_lifecycle_state": _enum_value(record.projection_map_lifecycle_state),
        "projection_actionability_state": _enum_value(record.projection_actionability_state),
        "rebuilt_at_utc": record.rebuilt_at_utc,
    }


def validate_native_short_map_level_status_collection(
    *,
    key: NativeShortMapScopeKey,
    current_map_id: int,
    map_cycle_id: str,
    level_status_as_of_utc: datetime,
    rows: Iterable[NativeShortMapLevelStatusRecord],
) -> tuple[NativeShortMapLevelStatusRecord, ...]:
    validate_native_short_scope_key(key)
    if current_map_id <= 0:
        raise NativeShortMapLevelStatusPersistenceError("COUNT_NOT_POSITIVE field=current_map_id")
    _require_text(map_cycle_id, "map_cycle_id")
    _require_utc(level_status_as_of_utc, "level_status_as_of_utc")

    materialized = tuple(rows)
    seen_identities: set[tuple[int, str, str, str]] = set()
    seen_roles: set[NativeShortMapLevelRole] = set()
    for row in materialized:
        if row.key != key:
            raise NativeShortMapLevelStatusPersistenceError("COLLECTION_SCOPE_KEY_MISMATCH")
        if row.current_map_id != current_map_id:
            raise NativeShortMapLevelStatusPersistenceError("COLLECTION_CURRENT_MAP_ID_MISMATCH")
        if row.map_cycle_id != map_cycle_id:
            raise NativeShortMapLevelStatusPersistenceError("COLLECTION_MAP_CYCLE_ID_MISMATCH")
        if row.level_status_as_of_utc != level_status_as_of_utc:
            raise NativeShortMapLevelStatusPersistenceError("COLLECTION_AS_OF_MISMATCH")
        role = NativeShortMapLevelRole(_enum_value(row.canonical_map_level_role))
        if role in seen_roles:
            raise NativeShortMapLevelStatusPersistenceError(f"DUPLICATE_LEVEL_ROLE role={role.value}")
        seen_roles.add(role)
        identity = (
            row.current_map_id,
            role.value,
            _enum_value(row.side),
            str(row.canonical_unrounded_price),
        )
        if identity in seen_identities:
            raise NativeShortMapLevelStatusPersistenceError(
                f"DUPLICATE_LEVEL_IDENTITY role={role.value} price={row.canonical_unrounded_price}"
            )
        seen_identities.add(identity)
    if seen_roles and seen_roles != set(V1_NATIVE_SHORT_SELL_LEVEL_ROLES):
        missing = sorted(role.value for role in set(V1_NATIVE_SHORT_SELL_LEVEL_ROLES) - seen_roles)
        extra = sorted(role.value for role in seen_roles - set(V1_NATIVE_SHORT_SELL_LEVEL_ROLES))
        raise NativeShortMapLevelStatusPersistenceError(
            f"V1_ROLE_SET_INCOMPLETE missing={missing} extra={extra}"
        )
    return materialized


def delete_native_short_map_level_status_for_scope(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    provenance: NativeShortWriterProvenance,
    authorization: WriterMutationAuthorization,
) -> int:
    validate_native_short_writer_provenance(provenance)
    validate_native_short_scope_key(key)
    require_writer_mutation_authorization(authorization, "native_short_4h_chain")
    sql = """
    DELETE FROM native_short_map_level_status_v1
    WHERE venue = %s
      AND symbol = %s
      AND quote_currency = %s
      AND fib_trading_horizon = %s
      AND primary_interval = %s
      AND supporting_interval = %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
            ),
        )
        return int(getattr(cur, "rowcount", 0) or 0)


def replace_native_short_map_level_status_for_scope(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    current_map_id: int,
    map_cycle_id: str,
    level_status_as_of_utc: datetime,
    rows: Iterable[NativeShortMapLevelStatusRecord],
    provenance: NativeShortWriterProvenance,
    authorization: WriterMutationAuthorization,
) -> int:
    """Atomically replace current level-status rows for one exact scope.

    The caller owns the transaction boundary. This helper intentionally does not
    commit, rollback, select maps, evaluate candles, or call any external trading
    code. Passing an empty row collection is valid and represents a fail-closed
    blocked projection collection replacement.
    """
    validate_native_short_writer_provenance(provenance)
    require_writer_mutation_authorization(authorization, "native_short_4h_chain")
    materialized_rows = validate_native_short_map_level_status_collection(
        key=key,
        current_map_id=current_map_id,
        map_cycle_id=map_cycle_id,
        level_status_as_of_utc=level_status_as_of_utc,
        rows=rows,
    )
    delete_native_short_map_level_status_for_scope(
        conn,
        key=key,
        provenance=provenance,
        authorization=authorization,
    )
    if not materialized_rows:
        return 0

    sql = """
    INSERT INTO native_short_map_level_status_v1 (
        venue, symbol, quote_currency, fib_trading_horizon,
        primary_interval, supporting_interval,
        current_map_id, map_cycle_id, writer_invocation_uuid,
        canonical_map_level_role, side,
        canonical_unrounded_price, canonical_tick_rounded_price,
        tick_rule_status, tick_rule_source,
        level_lifecycle_state, level_status_as_of_utc,
        evaluation_reference, reason_code,
        projection_scope_status_code,
        projection_map_lifecycle_state,
        projection_actionability_state,
        rebuilt_at_utc
    ) VALUES (
        %(venue)s, %(symbol)s, %(quote_currency)s, %(fib_trading_horizon)s,
        %(primary_interval)s, %(supporting_interval)s,
        %(current_map_id)s, %(map_cycle_id)s, %(writer_invocation_uuid)s,
        %(canonical_map_level_role)s, %(side)s,
        %(canonical_unrounded_price)s, %(canonical_tick_rounded_price)s,
        %(tick_rule_status)s, %(tick_rule_source)s,
        %(level_lifecycle_state)s, %(level_status_as_of_utc)s,
        %(evaluation_reference)s, %(reason_code)s,
        %(projection_scope_status_code)s,
        %(projection_map_lifecycle_state)s,
        %(projection_actionability_state)s,
        %(rebuilt_at_utc)s
    )
    """
    serialized = [
        {
            **serialize_native_short_map_level_status_record(row),
            "writer_invocation_uuid": provenance.invocation_uuid,
        }
        for row in materialized_rows
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, serialized)
        return int(getattr(cur, "rowcount", 0) or len(serialized))
