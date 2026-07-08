from __future__ import annotations

"""Pure native SHORT map-level status persistence contracts.

This module defines validation-only types for the rebuildable
`native_short_map_level_status_v1` current collection. It does not open database
connections, execute SQL, read wall-clock time, evaluate candles, rebuild
projections, or integrate with any presentation or order-handling layer.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    DEFAULT_PRIMARY_INTERVAL,
    DEFAULT_SUPPORTING_INTERVAL,
    NativeShortMapScopeKey,
)
from src.market_data.native_short_scope_status_v1 import (
    NativeShortScopeActionabilityState,
    NativeShortScopeMapLifecycleState,
    NativeShortScopeStatusCode,
    validate_native_short_scope_key,
)

__all__ = [
    "REASON_MAP_COMPLETED",
    "REASON_MAP_EXPIRED",
    "REASON_MAP_INVALIDATED",
    "REASON_NO_PRIMARY_HIGH_REACHED_LEVEL",
    "REASON_PRIMARY_CLOSE_PASSED_LEVEL",
    "REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE",
    "NativeShortMapLevelEvaluationReference",
    "NativeShortMapLevelLifecycleState",
    "NativeShortMapLevelRole",
    "NativeShortMapLevelSide",
    "NativeShortMapLevelStatusRecord",
    "NativeShortMapLevelStatusValidationError",
    "NativeShortMapLevelTickRuleSource",
    "NativeShortMapLevelTickRuleStatus",
    "canonical_v1_sell_level_roles",
]


REASON_NO_PRIMARY_HIGH_REACHED_LEVEL = "NO_PRIMARY_HIGH_REACHED_LEVEL"
REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE = "PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE"
REASON_PRIMARY_CLOSE_PASSED_LEVEL = "PRIMARY_CLOSE_PASSED_LEVEL"
REASON_MAP_COMPLETED = "MAP_COMPLETED"
REASON_MAP_INVALIDATED = "MAP_INVALIDATED"
REASON_MAP_EXPIRED = "MAP_EXPIRED"


class NativeShortMapLevelStatusValidationError(ValueError):
    pass


class NativeShortMapLevelRole(StrEnum):
    SELL_EXT_1_272 = "SELL_EXT_1_272"
    SELL_EXT_1_618 = "SELL_EXT_1_618"
    SELL_EXT_2_000 = "SELL_EXT_2_000"


class NativeShortMapLevelSide(StrEnum):
    SELL = "SELL"


class NativeShortMapLevelLifecycleState(StrEnum):
    ACTIVE = "ACTIVE"
    REACHED = "REACHED"
    PASSED = "PASSED"
    COMPLETED = "COMPLETED"
    HISTORICAL = "HISTORICAL"


class NativeShortMapLevelEvaluationReference(StrEnum):
    PRIMARY_4H_CLOSED_CANDLES = "PRIMARY_4H_CLOSED_CANDLES"
    MAP_LIFECYCLE_EVENT = "MAP_LIFECYCLE_EVENT"


class NativeShortMapLevelTickRuleStatus(StrEnum):
    TICK_RULE_APPLIED = "TICK_RULE_APPLIED"
    MISSING_TICK_RULE = "MISSING_TICK_RULE"


class NativeShortMapLevelTickRuleSource(StrEnum):
    TICK_RULE_FROM_DB = "TICK_RULE_FROM_DB"
    TICK_RULE_FROM_STATIC = "TICK_RULE_FROM_STATIC"
    MISSING_TICK_RULE = "MISSING_TICK_RULE"


def canonical_v1_sell_level_roles() -> tuple[NativeShortMapLevelRole, ...]:
    return (
        NativeShortMapLevelRole.SELL_EXT_1_272,
        NativeShortMapLevelRole.SELL_EXT_1_618,
        NativeShortMapLevelRole.SELL_EXT_2_000,
    )


def _coerce_enum(value: StrEnum | str, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        raise NativeShortMapLevelStatusValidationError(
            f"INVALID_ENUM field={field_name} value={value}"
        ) from exc


def _require_text(value: str | None, field_name: str) -> str:
    if value is None or not str(value).strip():
        raise NativeShortMapLevelStatusValidationError(f"REQUIRED_FIELD_MISSING field={field_name}")
    return str(value)


def _require_utc(value: datetime | None, field_name: str) -> datetime:
    if value is None:
        raise NativeShortMapLevelStatusValidationError(f"REQUIRED_TIMESTAMP_MISSING field={field_name}")
    offset = value.utcoffset()
    if value.tzinfo is None or offset != timedelta(0):
        raise NativeShortMapLevelStatusValidationError(f"TIMESTAMP_NOT_UTC field={field_name}")
    return value


def _require_positive_int(value: int | None, field_name: str) -> int:
    if value is None or value <= 0:
        raise NativeShortMapLevelStatusValidationError(f"COUNT_NOT_POSITIVE field={field_name}")
    return value


def _require_positive_decimal(value: Decimal | None, field_name: str) -> Decimal:
    if value is None or value <= Decimal("0"):
        raise NativeShortMapLevelStatusValidationError(f"PRICE_NOT_POSITIVE field={field_name}")
    return value


def _optional_positive_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _require_positive_decimal(value, field_name)


@dataclass(frozen=True)
class NativeShortMapLevelStatusRecord:
    key: NativeShortMapScopeKey
    current_map_id: int
    map_cycle_id: str
    canonical_map_level_role: NativeShortMapLevelRole | str
    side: NativeShortMapLevelSide | str
    canonical_unrounded_price: Decimal
    canonical_tick_rounded_price: Decimal | None
    tick_rule_status: NativeShortMapLevelTickRuleStatus | str
    tick_rule_source: NativeShortMapLevelTickRuleSource | str
    level_lifecycle_state: NativeShortMapLevelLifecycleState | str
    level_status_as_of_utc: datetime
    evaluation_reference: NativeShortMapLevelEvaluationReference | str
    reason_code: str
    projection_scope_status_code: NativeShortScopeStatusCode | str
    projection_map_lifecycle_state: NativeShortScopeMapLifecycleState | str
    projection_actionability_state: NativeShortScopeActionabilityState | str
    rebuilt_at_utc: datetime

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        if self.key.fib_trading_horizon != DEFAULT_FIB_TRADING_HORIZON:
            raise NativeShortMapLevelStatusValidationError(
                f"INVALID_FIB_TRADING_HORIZON value={self.key.fib_trading_horizon}"
            )
        if self.key.primary_interval != DEFAULT_PRIMARY_INTERVAL:
            raise NativeShortMapLevelStatusValidationError(
                f"INVALID_PRIMARY_INTERVAL value={self.key.primary_interval}"
            )
        if self.key.supporting_interval != DEFAULT_SUPPORTING_INTERVAL:
            raise NativeShortMapLevelStatusValidationError(
                f"INVALID_SUPPORTING_INTERVAL value={self.key.supporting_interval}"
            )

        _require_positive_int(self.current_map_id, "current_map_id")
        _require_text(self.map_cycle_id, "map_cycle_id")
        role = _coerce_enum(
            self.canonical_map_level_role,
            NativeShortMapLevelRole,
            "canonical_map_level_role",
        )
        side = _coerce_enum(self.side, NativeShortMapLevelSide, "side")
        lifecycle_state = _coerce_enum(
            self.level_lifecycle_state,
            NativeShortMapLevelLifecycleState,
            "level_lifecycle_state",
        )
        evaluation_reference = _coerce_enum(
            self.evaluation_reference,
            NativeShortMapLevelEvaluationReference,
            "evaluation_reference",
        )
        tick_rule_status = _coerce_enum(
            self.tick_rule_status,
            NativeShortMapLevelTickRuleStatus,
            "tick_rule_status",
        )
        tick_rule_source = _coerce_enum(
            self.tick_rule_source,
            NativeShortMapLevelTickRuleSource,
            "tick_rule_source",
        )
        projection_scope_status_code = _coerce_enum(
            self.projection_scope_status_code,
            NativeShortScopeStatusCode,
            "projection_scope_status_code",
        )
        projection_map_lifecycle_state = _coerce_enum(
            self.projection_map_lifecycle_state,
            NativeShortScopeMapLifecycleState,
            "projection_map_lifecycle_state",
        )
        projection_actionability_state = _coerce_enum(
            self.projection_actionability_state,
            NativeShortScopeActionabilityState,
            "projection_actionability_state",
        )

        if role not in canonical_v1_sell_level_roles():
            raise NativeShortMapLevelStatusValidationError(
                f"UNSUPPORTED_CANONICAL_MAP_LEVEL_ROLE value={role}"
            )
        if side != NativeShortMapLevelSide.SELL:
            raise NativeShortMapLevelStatusValidationError(f"UNSUPPORTED_SIDE value={side}")

        _require_positive_decimal(self.canonical_unrounded_price, "canonical_unrounded_price")
        _optional_positive_decimal(self.canonical_tick_rounded_price, "canonical_tick_rounded_price")
        _require_utc(self.level_status_as_of_utc, "level_status_as_of_utc")
        _require_utc(self.rebuilt_at_utc, "rebuilt_at_utc")
        _require_text(self.reason_code, "reason_code")

        if tick_rule_status == NativeShortMapLevelTickRuleStatus.MISSING_TICK_RULE:
            if tick_rule_source != NativeShortMapLevelTickRuleSource.MISSING_TICK_RULE:
                raise NativeShortMapLevelStatusValidationError(
                    "MISSING_TICK_RULE_REQUIRES_MISSING_SOURCE field=tick_rule_source"
                )
            if self.canonical_tick_rounded_price is not None:
                raise NativeShortMapLevelStatusValidationError(
                    "MISSING_TICK_RULE_REQUIRES_NULL_ROUNDED_PRICE field=canonical_tick_rounded_price"
                )
        else:
            if tick_rule_source == NativeShortMapLevelTickRuleSource.MISSING_TICK_RULE:
                raise NativeShortMapLevelStatusValidationError(
                    "APPLIED_TICK_RULE_REQUIRES_CONCRETE_SOURCE field=tick_rule_source"
                )
            if self.canonical_tick_rounded_price is None:
                raise NativeShortMapLevelStatusValidationError(
                    "APPLIED_TICK_RULE_REQUIRES_ROUNDED_PRICE field=canonical_tick_rounded_price"
                )

        active_states = {
            NativeShortMapLevelLifecycleState.ACTIVE,
            NativeShortMapLevelLifecycleState.REACHED,
            NativeShortMapLevelLifecycleState.PASSED,
        }
        if lifecycle_state in active_states:
            if evaluation_reference != NativeShortMapLevelEvaluationReference.PRIMARY_4H_CLOSED_CANDLES:
                raise NativeShortMapLevelStatusValidationError(
                    "DYNAMIC_LEVEL_STATE_REQUIRES_PRIMARY_EVALUATION field=evaluation_reference"
                )
            if projection_scope_status_code != NativeShortScopeStatusCode.CURRENT_EVALUATION:
                raise NativeShortMapLevelStatusValidationError(
                    "DYNAMIC_LEVEL_STATE_REQUIRES_CURRENT_EVALUATION field=projection_scope_status_code"
                )
            if projection_map_lifecycle_state != NativeShortScopeMapLifecycleState.MAP_ACTIVE:
                raise NativeShortMapLevelStatusValidationError(
                    "DYNAMIC_LEVEL_STATE_REQUIRES_ACTIVE_MAP field=projection_map_lifecycle_state"
                )
            if projection_actionability_state != NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP:
                raise NativeShortMapLevelStatusValidationError(
                    "DYNAMIC_LEVEL_STATE_REQUIRES_ACTIONABLE_ACTIVE_MAP field=projection_actionability_state"
                )

        if lifecycle_state == NativeShortMapLevelLifecycleState.COMPLETED:
            if evaluation_reference != NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT:
                raise NativeShortMapLevelStatusValidationError(
                    "COMPLETED_REQUIRES_MAP_LIFECYCLE_EVENT field=evaluation_reference"
                )
            if projection_map_lifecycle_state != NativeShortScopeMapLifecycleState.MAP_COMPLETED:
                raise NativeShortMapLevelStatusValidationError(
                    "COMPLETED_REQUIRES_MAP_COMPLETED field=projection_map_lifecycle_state"
                )
            if self.reason_code != REASON_MAP_COMPLETED:
                raise NativeShortMapLevelStatusValidationError(
                    "COMPLETED_REQUIRES_MAP_COMPLETED_REASON field=reason_code"
                )

        if lifecycle_state == NativeShortMapLevelLifecycleState.HISTORICAL:
            if evaluation_reference != NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT:
                raise NativeShortMapLevelStatusValidationError(
                    "HISTORICAL_REQUIRES_MAP_LIFECYCLE_EVENT field=evaluation_reference"
                )
            allowed = {
                NativeShortScopeMapLifecycleState.MAP_INVALIDATED: REASON_MAP_INVALIDATED,
                NativeShortScopeMapLifecycleState.MAP_EXPIRED: REASON_MAP_EXPIRED,
            }
            expected_reason = allowed.get(projection_map_lifecycle_state)
            if expected_reason is None:
                raise NativeShortMapLevelStatusValidationError(
                    "HISTORICAL_REQUIRES_TERMINAL_HISTORICAL_MAP field=projection_map_lifecycle_state"
                )
            if self.reason_code != expected_reason:
                raise NativeShortMapLevelStatusValidationError(
                    "HISTORICAL_REQUIRES_TERMINAL_REASON field=reason_code"
                )

    def map_level_identity_key(self) -> str:
        """Canonical identity within the projection-selected map."""
        return "|".join(
            (
                str(self.current_map_id),
                str(_coerce_enum(self.canonical_map_level_role, NativeShortMapLevelRole, "canonical_map_level_role")),
                str(_coerce_enum(self.side, NativeShortMapLevelSide, "side")),
                format(self.canonical_unrounded_price, "f"),
            )
        )

    def scope_level_identity_key(self) -> str:
        """Canonical current-row identity including the full native SHORT scope key."""
        return "|".join(
            (
                self.key.venue,
                self.key.symbol,
                self.key.quote_currency,
                self.key.fib_trading_horizon,
                self.key.primary_interval,
                self.key.supporting_interval,
                self.map_level_identity_key(),
            )
        )
