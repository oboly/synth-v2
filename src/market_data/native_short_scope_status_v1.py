from __future__ import annotations

"""Pure native SHORT scope-status persistence contracts.

This module defines validation-only types for PR A1/A1b persistence rows. It
does not open database connections, execute SQL, read wall-clock time, or
integrate with runtime writers.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    NativeShortMapScopeKey,
)
from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterProvenance,
    validate_native_short_writer_provenance,
)

__all__ = [
    "NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE",
    "NativeShortMaterializerRunRecord",
    "NativeShortObservationFreshnessState",
    "NativeShortRunTerminalStatus",
    "NativeShortScopeActionabilityState",
    "NativeShortScopeCadenceConfig",
    "NativeShortScopeGeometryAction",
    "NativeShortScopeMapLifecycleState",
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


# Reason code for the PR A1b (Amendment 1) configuration-unavailable state:
# no exact full-key native_short_scope_cadence_config_v1 version is eligible
# at as_of_utc. This is configuration state, never candle/source state.
NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE = "NO_ELIGIBLE_CADENCE_CONFIG"


class NativeShortRunTerminalStatus(StrEnum):
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class NativeShortScopeObservationStatus(StrEnum):
    EVALUATED = "EVALUATED"
    FAILED = "FAILED"
    SKIPPED_SOURCE_UNAVAILABLE = "SKIPPED_SOURCE_UNAVAILABLE"
    SKIPPED_CONFIGURATION_UNAVAILABLE = "SKIPPED_CONFIGURATION_UNAVAILABLE"


class NativeShortScopeSourceState(StrEnum):
    SOURCE_CURRENT = "SOURCE_CURRENT"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class NativeShortScopeGeometryAction(StrEnum):
    PUBLISHED_NEW_MAP = "PUBLISHED_NEW_MAP"
    UNCHANGED_GEOMETRY = "UNCHANGED_GEOMETRY"
    REJECTED_CONTEXT = "REJECTED_CONTEXT"
    NO_MAP_AVAILABLE = "NO_MAP_AVAILABLE"


class NativeShortScopeMapLifecycleState(StrEnum):
    MAP_ACTIVE = "MAP_ACTIVE"
    MAP_INVALIDATED = "MAP_INVALIDATED"
    MAP_COMPLETED = "MAP_COMPLETED"
    MAP_EXPIRED = "MAP_EXPIRED"
    NO_CURRENT_MAP = "NO_CURRENT_MAP"


class NativeShortScopeStatusCode(StrEnum):
    CONFIGURATION_UNAVAILABLE = "CONFIGURATION_UNAVAILABLE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_STALE = "SOURCE_STALE"
    MAP_INVALIDATED = "MAP_INVALIDATED"
    MAP_COMPLETED = "MAP_COMPLETED"
    SCOPE_RECENTLY_ADDED = "SCOPE_RECENTLY_ADDED"
    OBSERVATION_OVERDUE = "OBSERVATION_OVERDUE"
    CURRENT_EVALUATION = "CURRENT_EVALUATION"


class NativeShortScopeActionabilityState(StrEnum):
    BLOCKED_CONFIGURATION = "BLOCKED_CONFIGURATION"
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
    OBSERVATION_CONFIGURATION_UNAVAILABLE = "OBSERVATION_CONFIGURATION_UNAVAILABLE"


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


def _require_enum(value: StrEnum | str | None, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if value is None:
        raise NativeShortScopeStatusValidationError(f"REQUIRED_FIELD_MISSING field={field_name}")
    return _coerce_enum(value, enum_type, field_name)


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


def _require_positive_int(value: int | None, field_name: str) -> int:
    if value is None or value <= 0:
        raise NativeShortScopeStatusValidationError(f"COUNT_NOT_POSITIVE field={field_name}")
    return value


def _require_null(value: object, field_name: str) -> None:
    if value is not None:
        raise NativeShortScopeStatusValidationError(
            f"CONFIGURATION_UNAVAILABLE_FIELD_MUST_BE_NULL field={field_name}"
        )


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
    provenance: NativeShortWriterProvenance
    contract_version: str
    started_at_utc: datetime
    requested_scope_count: int
    terminal_status: NativeShortRunTerminalStatus | str | None = None
    finished_at_utc: datetime | None = None
    observed_scope_count: int | None = None
    published_map_count: int | None = None
    lifecycle_event_count: int | None = None
    failed_scope_count: int | None = None
    failure_reason_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        validate_native_short_writer_provenance(self.provenance)
        _require_text(self.contract_version, "contract_version")
        _require_utc(self.started_at_utc, "started_at_utc")
        _optional_utc(self.finished_at_utc, "finished_at_utc")
        if self.requested_scope_count < 0:
            raise NativeShortScopeStatusValidationError("COUNT_NEGATIVE field=requested_scope_count")
        if self.terminal_status is not None:
            _coerce_enum(self.terminal_status, NativeShortRunTerminalStatus, "terminal_status")
        for field_name in (
            "observed_scope_count",
            "published_map_count",
            "lifecycle_event_count",
            "failed_scope_count",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise NativeShortScopeStatusValidationError(f"COUNT_NEGATIVE field={field_name}")

    @property
    def run_uuid(self) -> str:
        return self.provenance.invocation_uuid

    @property
    def runner_name(self) -> str:
        return self.provenance.runner_name

    @property
    def runner_version(self) -> str:
        return self.provenance.runner_version

    @property
    def trigger_type(self) -> str:
        return self.provenance.trigger_type

    @property
    def trigger_ref(self) -> str:
        return self.provenance.trigger_ref

    @property
    def host_name(self) -> str:
        return self.provenance.host_name

    @property
    def process_id(self) -> int:
        return self.provenance.process_id


@dataclass(frozen=True)
class NativeShortScopeObservationRecord:
    key: NativeShortMapScopeKey
    run_id: int
    run_uuid: str
    observed_at_utc: datetime
    observation_status: NativeShortScopeObservationStatus | str
    cadence_contract_version: str | None = None
    source_state: NativeShortScopeSourceState | str | None = None
    primary_source_freshness_limit_seconds: int | None = None
    supporting_source_freshness_limit_seconds: int | None = None
    geometry_action: NativeShortScopeGeometryAction | str | None = None
    evaluation_due_at_utc: datetime | None = None
    observation_reason_code: str | None = None
    observation_detail: str | None = None
    primary_latest_candle_ts_utc: datetime | None = None
    supporting_latest_candle_ts_utc: datetime | None = None
    primary_source_age_seconds: int | None = None
    supporting_source_age_seconds: int | None = None
    context_status: str | None = None
    current_map_id_before: int | None = None
    current_map_id_after: int | None = None
    published_map_id: int | None = None
    generation_attempt_id: str | None = None
    generation_event_id: int | None = None
    lifecycle_event_id: int | None = None
    lifecycle_state_before: str | None = None
    lifecycle_state_after: str | None = None
    structure_hash: str | None = None
    source_primary_candle_count: int | None = None
    source_support_candle_count: int | None = None

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        if self.run_id <= 0:
            raise NativeShortScopeStatusValidationError("COUNT_NOT_POSITIVE field=run_id")
        _require_text(self.run_uuid, "run_uuid")
        _require_utc(self.observed_at_utc, "observed_at_utc")
        observation_status = _coerce_enum(
            self.observation_status, NativeShortScopeObservationStatus, "observation_status"
        )

        if observation_status == NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE:
            if self.observation_reason_code != NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE:
                raise NativeShortScopeStatusValidationError(
                    "CONFIGURATION_UNAVAILABLE_REQUIRES_REASON_CODE field=observation_reason_code"
                )
            _require_null(self.cadence_contract_version, "cadence_contract_version")
            _require_null(self.source_state, "source_state")
            _require_null(self.primary_source_freshness_limit_seconds, "primary_source_freshness_limit_seconds")
            _require_null(self.supporting_source_freshness_limit_seconds, "supporting_source_freshness_limit_seconds")
            _require_null(self.geometry_action, "geometry_action")
            _require_null(self.evaluation_due_at_utc, "evaluation_due_at_utc")
            return

        _optional_utc(self.evaluation_due_at_utc, "evaluation_due_at_utc")
        _require_text(self.cadence_contract_version, "cadence_contract_version")
        _require_enum(self.source_state, NativeShortScopeSourceState, "source_state")
        _require_enum(self.geometry_action, NativeShortScopeGeometryAction, "geometry_action")
        _require_positive_int(
            self.primary_source_freshness_limit_seconds, "primary_source_freshness_limit_seconds"
        )
        _require_positive_int(
            self.supporting_source_freshness_limit_seconds, "supporting_source_freshness_limit_seconds"
        )


@dataclass(frozen=True)
class NativeShortScopeStatusRecord:
    key: NativeShortMapScopeKey
    scope_support_state: NativeShortScopeSupportEventState | str
    scope_status_code: NativeShortScopeStatusCode | str
    map_lifecycle_state: NativeShortScopeMapLifecycleState | str
    observation_freshness_state: NativeShortObservationFreshnessState | str
    actionability_state: NativeShortScopeActionabilityState | str
    projection_as_of_utc: datetime
    rebuilt_at_utc: datetime
    source_freshness_state: NativeShortScopeSourceState | str | None = None
    primary_source_freshness_limit_seconds: int | None = None
    supporting_source_freshness_limit_seconds: int | None = None
    cadence_contract_version: str | None = None
    scope_status_reason_code: str | None = None
    current_map_id: int | None = None
    current_map_cycle_id: str | None = None
    current_map_published_at_utc: datetime | None = None
    current_map_structure_hash: str | None = None
    latest_generation_event_id: int | None = None
    latest_lifecycle_event_id: int | None = None
    latest_observation_id: int | None = None
    latest_run_id: int | None = None
    latest_observed_at_utc: datetime | None = None
    next_expected_evaluation_at_utc: datetime | None = None
    observation_overdue_after_utc: datetime | None = None
    primary_latest_candle_ts_utc: datetime | None = None
    supporting_latest_candle_ts_utc: datetime | None = None
    status_payload_json: str | None = None

    def __post_init__(self) -> None:
        validate_native_short_scope_key(self.key)
        scope_support_state = _coerce_enum(
            self.scope_support_state,
            NativeShortScopeSupportEventState,
            "scope_support_state",
        )
        if scope_support_state != NativeShortScopeSupportEventState.SUPPORTED:
            raise NativeShortScopeStatusValidationError(
                f"INVALID_SCOPE_SUPPORT_STATE_FOR_STATUS value={self.scope_support_state}"
            )
        scope_status_code = _coerce_enum(self.scope_status_code, NativeShortScopeStatusCode, "scope_status_code")
        _coerce_enum(self.map_lifecycle_state, NativeShortScopeMapLifecycleState, "map_lifecycle_state")
        observation_freshness_state = _coerce_enum(
            self.observation_freshness_state,
            NativeShortObservationFreshnessState,
            "observation_freshness_state",
        )
        actionability_state = _coerce_enum(
            self.actionability_state, NativeShortScopeActionabilityState, "actionability_state"
        )
        _require_utc(self.projection_as_of_utc, "projection_as_of_utc")
        _require_utc(self.rebuilt_at_utc, "rebuilt_at_utc")

        if scope_status_code == NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE:
            if self.scope_status_reason_code != NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE:
                raise NativeShortScopeStatusValidationError(
                    "CONFIGURATION_UNAVAILABLE_REQUIRES_REASON_CODE field=scope_status_reason_code"
                )
            if actionability_state != NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION:
                raise NativeShortScopeStatusValidationError(
                    "CONFIGURATION_UNAVAILABLE_REQUIRES_ACTIONABILITY field=actionability_state"
                )
            if observation_freshness_state != NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE:
                raise NativeShortScopeStatusValidationError(
                    "CONFIGURATION_UNAVAILABLE_REQUIRES_OBSERVATION_FRESHNESS field=observation_freshness_state"
                )
            _require_null(self.cadence_contract_version, "cadence_contract_version")
            _require_null(self.primary_source_freshness_limit_seconds, "primary_source_freshness_limit_seconds")
            _require_null(self.supporting_source_freshness_limit_seconds, "supporting_source_freshness_limit_seconds")
            _require_null(self.source_freshness_state, "source_freshness_state")
            _require_null(self.next_expected_evaluation_at_utc, "next_expected_evaluation_at_utc")
            _require_null(self.observation_overdue_after_utc, "observation_overdue_after_utc")
            return

        _require_text(self.cadence_contract_version, "cadence_contract_version")
        _require_enum(self.source_freshness_state, NativeShortScopeSourceState, "source_freshness_state")
        _require_positive_int(
            self.primary_source_freshness_limit_seconds, "primary_source_freshness_limit_seconds"
        )
        _require_positive_int(
            self.supporting_source_freshness_limit_seconds, "supporting_source_freshness_limit_seconds"
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
