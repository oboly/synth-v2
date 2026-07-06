from __future__ import annotations

"""Pure native SHORT scope-status persistence contracts.

This module defines validation-only types for PR A1 persistence rows. It does
not open database connections, execute SQL, read wall-clock time, or integrate
with runtime writers.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    NativeShortMapScopeKey,
)

__all__ = [
    "NativeShortMaterializerRunRecord",
    "NativeShortObservationFreshnessState",
    "NativeShortRunTerminalStatus",
    "NativeShortScopeActionabilityState",
    "NativeShortScopeCadenceConfig",
    "NativeShortScopeObservationRecord",
    "NativeShortScopeObservationStatus",
    "NativeShortScopeSourceState",
    "NativeShortScopeStatusCode",
    "NativeShortScopeStatusRecord",
    "NativeShortScopeStatusValidationError",
    "NativeShortScopeSupportEvent",
    "NativeShortScopeSupportEventState",
    "native_short_scope_key_from_parts",
    "validate_native_short_scope_key",
]


class NativeShortScopeStatusValidationError(ValueError):
    pass


class NativeShortRunTerminalStatus(StrEnum):
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class NativeShortScopeObservationStatus(StrEnum):
    EVALUATED = "EVALUATED"
    FAILED = "FAILED"
    SKIPPED_SOURCE_UNAVAILABLE = "SKIPPED_SOURCE_UNAVAILABLE"


class NativeShortScopeSourceState(StrEnum):
    SOURCE_CURRENT = "SOURCE_CURRENT"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class NativeShortScopeStatusCode(StrEnum):
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_STALE = "SOURCE_STALE"
    MAP_INVALIDATED = "MAP_INVALIDATED"
    MAP_COMPLETED = "MAP_COMPLETED"
    SCOPE_RECENTLY_ADDED = "SCOPE_RECENTLY_ADDED"
    OBSERVATION_OVERDUE = "OBSERVATION_OVERDUE"
    CURRENT_EVALUATION = "CURRENT_EVALUATION"


class NativeShortScopeActionabilityState(StrEnum):
    ACTIONABLE_ACTIVE_MAP = "ACTIONABLE_ACTIVE_MAP"
    NO_ACTIONABLE_MAP = "NO_ACTIONABLE_MAP"
    TERMINAL_MAP = "TERMINAL_MAP"
    BLOCKED_SOURCE = "BLOCKED_SOURCE"
    BLOCKED_OBSERVATION = "BLOCKED_OBSERVATION"
    BLOCKED_SCOPE = "BLOCKED_SCOPE"


class NativeShortObservationFreshnessState(StrEnum):
    OBSERVATION_CURRENT = "OBSERVATION_CURRENT"
    OBSERVATION_OVERDUE = "OBSERVATION_OVERDUE"
    NO_OBSERVATION = "NO_OBSERVATION"


class NativeShortScopeSupportEventState(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _coerce_enum(value: StrEnum | str, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        raise NativeShortScopeStatusValidationError(
            f"INVALID_ENUM field={field_name} value={value}"
        ) from exc


def _require_text(value: str | None, field_name: str) -> str:
    if value is None or not str(value).strip():
        raise NativeShortScopeStatusValidationError(f"REQUIRED_FIELD_MISSING field={field_name}")
    return str(value)


def _require_utc(value: datetime | None, field_name: str) -> datetime:
    if value is None:
        raise NativeShortScopeStatusValidationError(f"REQUIRED_TIMESTAMP_MISSING field={field_name}")
    offset = value.utcoffset()
    if value.tzinfo is None or offset != timedelta(0):
        raise NativeShortScopeStatusValidationError(f"TIMESTAMP_NOT_UTC field={field_name}")
    return value


def _optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _require_utc(value, field_name)


def validate_native_short_scope_key(key: NativeShortMapScopeKey) -> NativeShortMapScopeKey:
    if not isinstance(key, NativeShortMapScopeKey):
        raise NativeShortScopeStatusValidationError("SCOPE_KEY_REQUIRED")
    for field_name in (
        "venue",
        "symbol",
        "quote_currency",
        "fib_trading_horizon",
        "primary_interval",
        "supporting_interval",
    ):
        _require_text(getattr(key, field_name), field_name)
    if key.fib_trading_horizon != DEFAULT_FIB_TRADING_HORIZON:
        raise NativeShortScopeStatusValidationError(
            f"INVALID_FIB_TRADING_HORIZON value={key.fib_trading_horizon}"
        )
    return key


def native_short_scope_key_from_parts(
    *,
    venue: str,
    symbol: str,
    quote_currency: str,
    fib_trading_horizon: str,
    primary_interval: str,
    supporting_interval: str,
) -> NativeShortMapScopeKey:
    return validate_native_short_scope_key(
        NativeShortMapScopeKey(
            venue=venue,
            symbol=symbol,
            quote_currency=quote_currency,
            fib_trading_horizon=fib_trading_horizon,
            primary_interval=primary_interval,
            supporting_interval=supporting_interval,
        )
    )


@dataclass(frozen=True)
class NativeShortMaterializerRunRecord:
    run_uuid: str
    runner_name: str
    runner_version: str
    contract_version: str
    trigger_type: str
    started_at_utc: datetime
    requested_scope_count: int
    terminal_status: NativeShortRunTerminalStatus | str | None = None
    finished_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_uuid, "run_uuid")
        _require_text(self.runner_name, "runner_name")
        _require_text(self.runner_version, "runner_version")
        _require_text(self.contract_version, "contract_version")
        _require_text(self.trigger_type, "trigger_type")
        _require_utc(self.started_at_utc, "started_at_utc")
        _optional_utc(self.finished_at_utc, "finished_at_utc")
        if self.requested_scope_count < 0:
            raise NativeShortScopeStatusValidationError("COUNT_NEGATIVE field=requested_scope_count")
        if self.terminal_status is not None:
            _coerce_enum(self.terminal_status, NativeShortRunTerminalStatus, "terminal_status")


@dataclass(frozen=True)
class NativeShortScopeObservationRecord:
    key: NativeShortMapScopeKey
    run_uuid: str
    observed_at_utc: datetime
    cadence_contract_version: str
    observation_status: NativeShortScopeObservationStatus | str
    source_state: NativeShortScopeSourceState | str
    primary_source_freshness_limit_seconds: int
    supporting_source_freshness_limit_seconds: int
    geometry_action: str
    evaluation_due_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        _require_text(self.run_uuid, "run_uuid")
        _require_utc(self.observed_at_utc, "observed_at_utc")
        _optional_utc(self.evaluation_due_at_utc, "evaluation_due_at_utc")
        _require_text(self.cadence_contract_version, "cadence_contract_version")
        _coerce_enum(self.observation_status, NativeShortScopeObservationStatus, "observation_status")
        _coerce_enum(self.source_state, NativeShortScopeSourceState, "source_state")
        _require_text(self.geometry_action, "geometry_action")
        if self.primary_source_freshness_limit_seconds <= 0:
            raise NativeShortScopeStatusValidationError(
                "COUNT_NOT_POSITIVE field=primary_source_freshness_limit_seconds"
            )
        if self.supporting_source_freshness_limit_seconds <= 0:
            raise NativeShortScopeStatusValidationError(
                "COUNT_NOT_POSITIVE field=supporting_source_freshness_limit_seconds"
            )


@dataclass(frozen=True)
class NativeShortScopeStatusRecord:
    key: NativeShortMapScopeKey
    scope_status_code: NativeShortScopeStatusCode | str
    map_lifecycle_state: str
    observation_freshness_state: NativeShortObservationFreshnessState | str
    source_freshness_state: NativeShortScopeSourceState | str
    actionability_state: NativeShortScopeActionabilityState | str
    primary_source_freshness_limit_seconds: int
    supporting_source_freshness_limit_seconds: int
    cadence_contract_version: str
    projection_as_of_utc: datetime
    rebuilt_at_utc: datetime

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        _coerce_enum(self.scope_status_code, NativeShortScopeStatusCode, "scope_status_code")
        _require_text(self.map_lifecycle_state, "map_lifecycle_state")
        _coerce_enum(
            self.observation_freshness_state,
            NativeShortObservationFreshnessState,
            "observation_freshness_state",
        )
        _coerce_enum(self.source_freshness_state, NativeShortScopeSourceState, "source_freshness_state")
        _coerce_enum(self.actionability_state, NativeShortScopeActionabilityState, "actionability_state")
        _require_text(self.cadence_contract_version, "cadence_contract_version")
        _require_utc(self.projection_as_of_utc, "projection_as_of_utc")
        _require_utc(self.rebuilt_at_utc, "rebuilt_at_utc")
        if self.primary_source_freshness_limit_seconds <= 0:
            raise NativeShortScopeStatusValidationError(
                "COUNT_NOT_POSITIVE field=primary_source_freshness_limit_seconds"
            )
        if self.supporting_source_freshness_limit_seconds <= 0:
            raise NativeShortScopeStatusValidationError(
                "COUNT_NOT_POSITIVE field=supporting_source_freshness_limit_seconds"
            )


@dataclass(frozen=True)
class NativeShortScopeCadenceConfig:
    key: NativeShortMapScopeKey
    cadence_contract_version: str
    target_evaluation_interval: str
    primary_source_freshness_limit_seconds: int
    supporting_source_freshness_limit_seconds: int
    evaluation_grace_seconds: int
    recent_scope_grace_seconds: int
    effective_from_utc: datetime
    effective_to_utc: datetime | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        _require_text(self.cadence_contract_version, "cadence_contract_version")
        _require_text(self.target_evaluation_interval, "target_evaluation_interval")
        if self.target_evaluation_interval != "1h":
            raise NativeShortScopeStatusValidationError(
                f"INVALID_TARGET_EVALUATION_INTERVAL value={self.target_evaluation_interval}"
            )
        _require_utc(self.effective_from_utc, "effective_from_utc")
        _optional_utc(self.effective_to_utc, "effective_to_utc")
        if self.effective_to_utc is not None and self.effective_to_utc <= self.effective_from_utc:
            raise NativeShortScopeStatusValidationError("INVALID_EFFECTIVE_RANGE")
        for field_name in (
            "primary_source_freshness_limit_seconds",
            "supporting_source_freshness_limit_seconds",
            "evaluation_grace_seconds",
            "recent_scope_grace_seconds",
        ):
            if getattr(self, field_name) <= 0:
                raise NativeShortScopeStatusValidationError(f"COUNT_NOT_POSITIVE field={field_name}")


@dataclass(frozen=True)
class NativeShortScopeSupportEvent:
    key: NativeShortMapScopeKey
    scope_support_state: NativeShortScopeSupportEventState | str
    event_ts_utc: datetime
    source_name: str
    source_version: str
    created_at_utc: datetime

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        _coerce_enum(self.scope_support_state, NativeShortScopeSupportEventState, "scope_support_state")
        _require_utc(self.event_ts_utc, "event_ts_utc")
        _require_text(self.source_name, "source_name")
        _require_text(self.source_version, "source_version")
        _require_utc(self.created_at_utc, "created_at_utc")
