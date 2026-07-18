from __future__ import annotations

"""Pure contracts for Native SHORT single-scope administration.

This module normalizes and validates request identity only. It has no database,
broker, account, selection, planning, execution, or reporting dependency.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, TypeAlias


CANONICAL_VENUE = "bitvavo"
CANONICAL_QUOTE_CURRENCY = "EUR"
CANONICAL_FIB_TRADING_HORIZON = "SHORT"
CANONICAL_PRIMARY_INTERVAL = "4h"
CANONICAL_SUPPORTING_INTERVAL = "1h"

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+$")

JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | tuple["JsonValue", ...]


class NativeShortScopeAdministrationValidationError(ValueError):
    pass


class NativeShortScopeAdministrationOperationType(StrEnum):
    ADOPT_LEGACY_SCOPE = "ADOPT_LEGACY_SCOPE"
    PROMOTE_SCOPE = "PROMOTE_SCOPE"
    REMOVE_SCOPE = "REMOVE_SCOPE"


class NativeShortScopeAdministrationActorType(StrEnum):
    HUMAN_OPERATOR = "HUMAN_OPERATOR"
    SERVICE_PRINCIPAL = "SERVICE_PRINCIPAL"
    TEST = "TEST"


class NativeShortScopeAdministrationTriggerType(StrEnum):
    MANUAL_CLI = "MANUAL_CLI"
    AUTOMATION = "AUTOMATION"
    TEST = "TEST"


class NativeShortScopeAdministrationResultClass(StrEnum):
    SUCCESS = "SUCCESS"
    IDEMPOTENT_SUCCESS = "IDEMPOTENT_SUCCESS"
    CONFLICT = "CONFLICT"
    BLOCKED = "BLOCKED"
    CORRUPT_STATE = "CORRUPT_STATE"
    RETRYABLE = "RETRYABLE"


class NativeShortScopeAdministrationResultCode(StrEnum):
    ADOPTED_LEGACY_SCOPE = "ADOPTED_LEGACY_SCOPE"
    PROMOTED_NEW_SCOPE = "PROMOTED_NEW_SCOPE"
    PROMOTED_FROM_PRIOR_WITHDRAWAL = "PROMOTED_FROM_PRIOR_WITHDRAWAL"
    REMOVED_SCOPE = "REMOVED_SCOPE"

    OPERATION_ALREADY_COMPLETED = "OPERATION_ALREADY_COMPLETED"
    SCOPE_ALREADY_ADOPTED = "SCOPE_ALREADY_ADOPTED"
    SCOPE_ALREADY_SUPPORTED = "SCOPE_ALREADY_SUPPORTED"
    SCOPE_ALREADY_REMOVED = "SCOPE_ALREADY_REMOVED"
    ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED = (
        "ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED"
    )

    OPERATION_METADATA_MISMATCH = "OPERATION_METADATA_MISMATCH"
    LEGACY_SCOPE_REQUIRES_ADOPTION = "LEGACY_SCOPE_REQUIRES_ADOPTION"
    CADENCE_PROFILE_CONFLICT = "CADENCE_PROFILE_CONFLICT"

    LEGACY_ADOPTION_NOT_AUTHORIZED = "LEGACY_ADOPTION_NOT_AUTHORIZED"
    GLOBAL_BLOCKERS_ACTIVE = "GLOBAL_BLOCKERS_ACTIVE"

    LEGACY_STATE_INCOHERENT = "LEGACY_STATE_INCOHERENT"
    PARTIAL_SCOPE_STATE = "PARTIAL_SCOPE_STATE"
    AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT = (
        "AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT"
    )
    MULTIPLE_ACTIVE_CADENCE_ROWS = "MULTIPLE_ACTIVE_CADENCE_ROWS"
    SUPPORT_GENERATION_MISMATCH = "SUPPORT_GENERATION_MISMATCH"

    DEADLOCK = "DEADLOCK"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    COMMIT_STATUS_UNKNOWN = "COMMIT_STATUS_UNKNOWN"


_RESULT_CODE_CLASS = {
    NativeShortScopeAdministrationResultCode.ADOPTED_LEGACY_SCOPE: (
        NativeShortScopeAdministrationResultClass.SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.PROMOTED_NEW_SCOPE: (
        NativeShortScopeAdministrationResultClass.SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.PROMOTED_FROM_PRIOR_WITHDRAWAL: (
        NativeShortScopeAdministrationResultClass.SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.REMOVED_SCOPE: (
        NativeShortScopeAdministrationResultClass.SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.OPERATION_ALREADY_COMPLETED: (
        NativeShortScopeAdministrationResultClass.IDEMPOTENT_SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.SCOPE_ALREADY_ADOPTED: (
        NativeShortScopeAdministrationResultClass.IDEMPOTENT_SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.SCOPE_ALREADY_SUPPORTED: (
        NativeShortScopeAdministrationResultClass.IDEMPOTENT_SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.SCOPE_ALREADY_REMOVED: (
        NativeShortScopeAdministrationResultClass.IDEMPOTENT_SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED: (
        NativeShortScopeAdministrationResultClass.IDEMPOTENT_SUCCESS
    ),
    NativeShortScopeAdministrationResultCode.OPERATION_METADATA_MISMATCH: (
        NativeShortScopeAdministrationResultClass.CONFLICT
    ),
    NativeShortScopeAdministrationResultCode.LEGACY_SCOPE_REQUIRES_ADOPTION: (
        NativeShortScopeAdministrationResultClass.CONFLICT
    ),
    NativeShortScopeAdministrationResultCode.CADENCE_PROFILE_CONFLICT: (
        NativeShortScopeAdministrationResultClass.CONFLICT
    ),
    NativeShortScopeAdministrationResultCode.LEGACY_ADOPTION_NOT_AUTHORIZED: (
        NativeShortScopeAdministrationResultClass.BLOCKED
    ),
    NativeShortScopeAdministrationResultCode.GLOBAL_BLOCKERS_ACTIVE: (
        NativeShortScopeAdministrationResultClass.BLOCKED
    ),
    NativeShortScopeAdministrationResultCode.LEGACY_STATE_INCOHERENT: (
        NativeShortScopeAdministrationResultClass.CORRUPT_STATE
    ),
    NativeShortScopeAdministrationResultCode.PARTIAL_SCOPE_STATE: (
        NativeShortScopeAdministrationResultClass.CORRUPT_STATE
    ),
    NativeShortScopeAdministrationResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT: (
        NativeShortScopeAdministrationResultClass.CORRUPT_STATE
    ),
    NativeShortScopeAdministrationResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS: (
        NativeShortScopeAdministrationResultClass.CORRUPT_STATE
    ),
    NativeShortScopeAdministrationResultCode.SUPPORT_GENERATION_MISMATCH: (
        NativeShortScopeAdministrationResultClass.CORRUPT_STATE
    ),
    NativeShortScopeAdministrationResultCode.DEADLOCK: (
        NativeShortScopeAdministrationResultClass.RETRYABLE
    ),
    NativeShortScopeAdministrationResultCode.LOCK_TIMEOUT: (
        NativeShortScopeAdministrationResultClass.RETRYABLE
    ),
    NativeShortScopeAdministrationResultCode.COMMIT_STATUS_UNKNOWN: (
        NativeShortScopeAdministrationResultClass.RETRYABLE
    ),
}


def _required_text(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise NativeShortScopeAdministrationValidationError(
            f"TEXT_REQUIRED field={field_name}"
        )
    normalized = value.strip()
    if not normalized:
        raise NativeShortScopeAdministrationValidationError(
            f"REQUIRED_FIELD_MISSING field={field_name}"
        )
    if len(normalized) > maximum:
        raise NativeShortScopeAdministrationValidationError(
            f"FIELD_TOO_LONG field={field_name} maximum={maximum}"
        )
    return normalized


def _coerce_enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        raise NativeShortScopeAdministrationValidationError(
            f"INVALID_ENUM field={field_name} value={value}"
        ) from exc


def _require_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise NativeShortScopeAdministrationValidationError(
            f"TIMESTAMP_REQUIRED field={field_name}"
        )
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise NativeShortScopeAdministrationValidationError(
            f"TIMESTAMP_NOT_UTC field={field_name}"
        )
    return value.astimezone(UTC)


def _freeze_json(value: object, path: str = "metadata") -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise NativeShortScopeAdministrationValidationError(
                    f"METADATA_KEY_NOT_STRING path={path}"
                )
            normalized[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(normalized)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{path}[]") for item in value)
    raise NativeShortScopeAdministrationValidationError(
        f"METADATA_VALUE_UNSUPPORTED path={path} type={type(value).__name__}"
    )


def _thaw_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class NativeShortScopeAdministrationKey:
    venue: str
    symbol: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str

    def __post_init__(self) -> None:
        venue = _required_text(self.venue, "venue", maximum=32).lower()
        symbol = _required_text(self.symbol, "symbol", maximum=32).upper()
        quote_currency = _required_text(
            self.quote_currency, "quote_currency", maximum=16
        ).upper()
        horizon = _required_text(
            self.fib_trading_horizon, "fib_trading_horizon", maximum=32
        ).upper()
        primary = _required_text(
            self.primary_interval, "primary_interval", maximum=16
        ).lower()
        supporting = _required_text(
            self.supporting_interval, "supporting_interval", maximum=16
        ).lower()

        if _SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise NativeShortScopeAdministrationValidationError(
                f"SYMBOL_NOT_SINGLE_CANONICAL value={symbol}"
            )
        expected = (
            ("venue", venue, CANONICAL_VENUE),
            ("quote_currency", quote_currency, CANONICAL_QUOTE_CURRENCY),
            (
                "fib_trading_horizon",
                horizon,
                CANONICAL_FIB_TRADING_HORIZON,
            ),
            ("primary_interval", primary, CANONICAL_PRIMARY_INTERVAL),
            (
                "supporting_interval",
                supporting,
                CANONICAL_SUPPORTING_INTERVAL,
            ),
        )
        for field_name, actual, canonical in expected:
            if actual != canonical:
                raise NativeShortScopeAdministrationValidationError(
                    f"NONCANONICAL_SCOPE_FIELD field={field_name} "
                    f"value={actual} expected={canonical}"
                )

        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "quote_currency", quote_currency)
        object.__setattr__(self, "fib_trading_horizon", horizon)
        object.__setattr__(self, "primary_interval", primary)
        object.__setattr__(self, "supporting_interval", supporting)

    def as_dict(self) -> dict[str, str]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "quote_currency": self.quote_currency,
            "fib_trading_horizon": self.fib_trading_horizon,
            "primary_interval": self.primary_interval,
            "supporting_interval": self.supporting_interval,
        }


@dataclass(frozen=True)
class NativeShortScopeAdministrationProvenance:
    operation_uuid: str
    actor_type: NativeShortScopeAdministrationActorType | str
    actor_id: str
    trigger_type: NativeShortScopeAdministrationTriggerType | str
    request_source: str
    reason: str
    requested_at_utc: datetime
    repository_sha: str
    schema_version: str

    def __post_init__(self) -> None:
        operation_uuid = _required_text(
            self.operation_uuid, "operation_uuid", maximum=36
        )
        try:
            parsed_uuid = uuid.UUID(operation_uuid)
        except (ValueError, AttributeError) as exc:
            raise NativeShortScopeAdministrationValidationError(
                "OPERATION_UUID_INVALID"
            ) from exc
        if str(parsed_uuid) != operation_uuid:
            raise NativeShortScopeAdministrationValidationError(
                "OPERATION_UUID_NOT_CANONICAL"
            )

        actor_type = _coerce_enum(
            self.actor_type,
            NativeShortScopeAdministrationActorType,
            "actor_type",
        )
        trigger_type = _coerce_enum(
            self.trigger_type,
            NativeShortScopeAdministrationTriggerType,
            "trigger_type",
        )
        actor_id = _required_text(self.actor_id, "actor_id", maximum=128)
        request_source = _required_text(
            self.request_source, "request_source", maximum=160
        )
        reason = _required_text(self.reason, "reason", maximum=255)
        requested_at_utc = _require_utc(self.requested_at_utc, "requested_at_utc")
        repository_sha = _required_text(
            self.repository_sha, "repository_sha", maximum=40
        )
        if _SHA_PATTERN.fullmatch(repository_sha) is None:
            raise NativeShortScopeAdministrationValidationError(
                "REPOSITORY_SHA_INVALID"
            )
        schema_version = _required_text(
            self.schema_version, "schema_version", maximum=64
        )

        if (
            actor_type == NativeShortScopeAdministrationActorType.TEST
            or trigger_type == NativeShortScopeAdministrationTriggerType.TEST
        ) and not (
            actor_type == NativeShortScopeAdministrationActorType.TEST
            and trigger_type == NativeShortScopeAdministrationTriggerType.TEST
        ):
            raise NativeShortScopeAdministrationValidationError(
                "TEST_PROVENANCE_MUST_BE_EXPLICIT"
            )

        object.__setattr__(self, "operation_uuid", operation_uuid)
        object.__setattr__(self, "actor_type", actor_type)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "trigger_type", trigger_type)
        object.__setattr__(self, "request_source", request_source)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "requested_at_utc", requested_at_utc)
        object.__setattr__(self, "repository_sha", repository_sha)
        object.__setattr__(self, "schema_version", schema_version)

    def as_dict(self) -> dict[str, object]:
        return {
            "operation_uuid": self.operation_uuid,
            "actor_type": str(self.actor_type),
            "actor_id": self.actor_id,
            "trigger_type": str(self.trigger_type),
            "request_source": self.request_source,
            "reason": self.reason,
            "requested_at_utc": self.requested_at_utc.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            "repository_sha": self.repository_sha,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class NativeShortScopeAdministrationRequest:
    operation_type: NativeShortScopeAdministrationOperationType | str
    scope_key: NativeShortScopeAdministrationKey
    provenance: NativeShortScopeAdministrationProvenance
    canonical_metadata: Mapping[str, object]
    canonical_metadata_json: str = field(init=False)
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        operation_type = _coerce_enum(
            self.operation_type,
            NativeShortScopeAdministrationOperationType,
            "operation_type",
        )
        if not isinstance(self.scope_key, NativeShortScopeAdministrationKey):
            raise NativeShortScopeAdministrationValidationError("SCOPE_KEY_REQUIRED")
        if not isinstance(
            self.provenance, NativeShortScopeAdministrationProvenance
        ):
            raise NativeShortScopeAdministrationValidationError("PROVENANCE_REQUIRED")
        if not isinstance(self.canonical_metadata, Mapping):
            raise NativeShortScopeAdministrationValidationError(
                "CANONICAL_METADATA_MAPPING_REQUIRED"
            )

        frozen_metadata = _freeze_json(self.canonical_metadata)
        if not isinstance(frozen_metadata, Mapping):
            raise NativeShortScopeAdministrationValidationError(
                "CANONICAL_METADATA_MAPPING_REQUIRED"
            )
        metadata_json = _canonical_json(_thaw_json(frozen_metadata))
        identity = {
            "operation_type": str(operation_type),
            "scope_key": self.scope_key.as_dict(),
            "provenance": self.provenance.as_dict(),
            "canonical_metadata": json.loads(metadata_json),
        }
        canonical_request_json = _canonical_json(identity)

        object.__setattr__(self, "operation_type", operation_type)
        object.__setattr__(self, "canonical_metadata", frozen_metadata)
        object.__setattr__(self, "canonical_metadata_json", metadata_json)
        object.__setattr__(
            self,
            "request_digest",
            hashlib.sha256(canonical_request_json.encode("utf-8")).hexdigest(),
        )

    def canonical_request_json(self) -> str:
        return _canonical_json(
            {
                "operation_type": str(self.operation_type),
                "scope_key": self.scope_key.as_dict(),
                "provenance": self.provenance.as_dict(),
                "canonical_metadata": json.loads(self.canonical_metadata_json),
            }
        )


@dataclass(frozen=True)
class NativeShortScopeAdministrationResult:
    result_class: NativeShortScopeAdministrationResultClass | str
    result_code: NativeShortScopeAdministrationResultCode | str
    support_generation_before: int | None
    support_generation_after: int | None

    def __post_init__(self) -> None:
        result_class = _coerce_enum(
            self.result_class,
            NativeShortScopeAdministrationResultClass,
            "result_class",
        )
        result_code = _coerce_enum(
            self.result_code,
            NativeShortScopeAdministrationResultCode,
            "result_code",
        )
        if _RESULT_CODE_CLASS[result_code] != result_class:
            raise NativeShortScopeAdministrationValidationError(
                "RESULT_CLASS_CODE_MISMATCH"
            )
        for field_name, value in (
            ("support_generation_before", self.support_generation_before),
            ("support_generation_after", self.support_generation_after),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise NativeShortScopeAdministrationValidationError(
                    f"SUPPORT_GENERATION_INVALID field={field_name}"
                )
        if (
            self.support_generation_before is not None
            and self.support_generation_after is not None
            and self.support_generation_after < self.support_generation_before
        ):
            raise NativeShortScopeAdministrationValidationError(
                "SUPPORT_GENERATION_REGRESSION"
            )
        object.__setattr__(self, "result_class", result_class)
        object.__setattr__(self, "result_code", result_code)


__all__ = [
    "CANONICAL_FIB_TRADING_HORIZON",
    "CANONICAL_PRIMARY_INTERVAL",
    "CANONICAL_QUOTE_CURRENCY",
    "CANONICAL_SUPPORTING_INTERVAL",
    "CANONICAL_VENUE",
    "NativeShortScopeAdministrationActorType",
    "NativeShortScopeAdministrationKey",
    "NativeShortScopeAdministrationOperationType",
    "NativeShortScopeAdministrationProvenance",
    "NativeShortScopeAdministrationRequest",
    "NativeShortScopeAdministrationResult",
    "NativeShortScopeAdministrationResultClass",
    "NativeShortScopeAdministrationResultCode",
    "NativeShortScopeAdministrationTriggerType",
    "NativeShortScopeAdministrationValidationError",
]
