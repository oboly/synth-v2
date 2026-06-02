from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from src.advice_route.interfaces_v1 import (
    FORBIDDEN_FIELD_SUBSTRINGS,
    Action,
    ConfidenceBucket,
    ConfirmationState,
    FrameworkContext,
    FreshnessState,
    Horizon,
    StrategyInterpretation,
    StrategyProposal,
    StrengthBucket,
    SynthConfirmationContext,
)


def _reject_forbidden_payload_keys(payload: dict[str, Any]) -> None:
    for key in payload:
        normalized = str(key).lower()
        for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
            if forbidden in normalized:
                raise ValueError(f"Forbidden payload field detected: {key}")


def _assert_known_keys(payload: dict[str, Any], dataclass_type: type[object]) -> None:
    allowed = {dataclass_field.name for dataclass_field in fields(dataclass_type)}
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise ValueError(
            f"Unknown payload fields for {dataclass_type.__name__}: {', '.join(unknown)}"
        )


def _serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return to_dict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    return value


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise TypeError(f"Expected datetime string, got {type(value).__name__}")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _parse_tuple_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"Expected list/tuple of strings, got {type(value).__name__}")
    return tuple(str(item) for item in value)


def _parse_enum(value: Any, enum_type: type[Enum]) -> Enum:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"Expected enum string for {enum_type.__name__}, got {type(value).__name__}")
    return enum_type(value)


def to_dict(obj: Any) -> dict[str, Any]:
    if not is_dataclass(obj):
        raise TypeError("to_dict expects a dataclass instance")
    return {
        dataclass_field.name: _serialize_value(getattr(obj, dataclass_field.name))
        for dataclass_field in fields(obj)
    }


def from_dict_framework_context(payload: dict[str, Any]) -> FrameworkContext:
    _reject_forbidden_payload_keys(payload)
    _assert_known_keys(payload, FrameworkContext)
    return FrameworkContext(
        symbol=str(payload["symbol"]),
        created_at_utc=_parse_datetime(payload["created_at_utc"]),
        framework_bias=str(payload["framework_bias"]),
        framework_horizon=_parse_enum(payload["framework_horizon"], Horizon),  # type: ignore[arg-type]
        map_horizon=_parse_enum(payload["map_horizon"], Horizon),  # type: ignore[arg-type]
        source_interval=str(payload["source_interval"]),
        anchor_interval=str(payload["anchor_interval"]),
        target_zone_low=_parse_decimal(payload.get("target_zone_low")),
        target_zone_high=_parse_decimal(payload.get("target_zone_high")),
        invalidation_level=_parse_decimal(payload.get("invalidation_level")),
        framework_confidence_bucket=_parse_enum(
            payload.get("framework_confidence_bucket", ConfidenceBucket.NONE.value),
            ConfidenceBucket,
        ),  # type: ignore[arg-type]
        research_context_flags=_parse_tuple_str(payload.get("research_context_flags")),
        source_refs=_parse_tuple_str(payload.get("source_refs")),
    )


def from_dict_synth_confirmation_context(payload: dict[str, Any]) -> SynthConfirmationContext:
    _reject_forbidden_payload_keys(payload)
    _assert_known_keys(payload, SynthConfirmationContext)
    return SynthConfirmationContext(
        symbol=str(payload["symbol"]),
        created_at_utc=_parse_datetime(payload["created_at_utc"]),
        confirmation_state=_parse_enum(payload["confirmation_state"], ConfirmationState),  # type: ignore[arg-type]
        confirmation_strength_bucket=_parse_enum(
            payload["confirmation_strength_bucket"],
            StrengthBucket,
        ),  # type: ignore[arg-type]
        freshness_state=_parse_enum(payload["freshness_state"], FreshnessState),  # type: ignore[arg-type]
        conflict_flags=_parse_tuple_str(payload.get("conflict_flags")),
        quality_flags=_parse_tuple_str(payload.get("quality_flags")),
        runtime_source_flags=_parse_tuple_str(payload.get("runtime_source_flags")),
        source_refs=_parse_tuple_str(payload.get("source_refs")),
    )


def from_dict_strategy_interpretation(payload: dict[str, Any]) -> StrategyInterpretation:
    _reject_forbidden_payload_keys(payload)
    _assert_known_keys(payload, StrategyInterpretation)
    return StrategyInterpretation(
        symbol=str(payload["symbol"]),
        created_at_utc=_parse_datetime(payload["created_at_utc"]),
        action=_parse_enum(payload["action"], Action),  # type: ignore[arg-type]
        horizon=_parse_enum(payload["horizon"], Horizon),  # type: ignore[arg-type]
        setup_id=str(payload["setup_id"]),
        framework_bias=str(payload["framework_bias"]),
        confirmation_state=_parse_enum(payload["confirmation_state"], ConfirmationState),  # type: ignore[arg-type]
        confirmation_strength_bucket=_parse_enum(
            payload["confirmation_strength_bucket"],
            StrengthBucket,
        ),  # type: ignore[arg-type]
        confidence_bucket=_parse_enum(payload["confidence_bucket"], ConfidenceBucket),  # type: ignore[arg-type]
        notes=_parse_tuple_str(payload.get("notes")),
        source_refs=_parse_tuple_str(payload.get("source_refs")),
    )


def from_dict_strategy_proposal(payload: dict[str, Any]) -> StrategyProposal:
    _reject_forbidden_payload_keys(payload)
    _assert_known_keys(payload, StrategyProposal)
    return StrategyProposal(
        proposal_id=str(payload["proposal_id"]),
        symbol=str(payload["symbol"]),
        created_at_utc=_parse_datetime(payload["created_at_utc"]),
        route_version=str(payload["route_version"]),
        action=_parse_enum(payload["action"], Action),  # type: ignore[arg-type]
        horizon=_parse_enum(payload["horizon"], Horizon),  # type: ignore[arg-type]
        setup_id=str(payload["setup_id"]),
        framework_bias=str(payload["framework_bias"]),
        framework_horizon=_parse_enum(payload["framework_horizon"], Horizon),  # type: ignore[arg-type]
        confirmation_state=_parse_enum(payload["confirmation_state"], ConfirmationState),  # type: ignore[arg-type]
        confirmation_strength_bucket=_parse_enum(
            payload["confirmation_strength_bucket"],
            StrengthBucket,
        ),  # type: ignore[arg-type]
        confidence_bucket=_parse_enum(payload["confidence_bucket"], ConfidenceBucket),  # type: ignore[arg-type]
        entry_zone_low=_parse_decimal(payload.get("entry_zone_low")),
        entry_zone_high=_parse_decimal(payload.get("entry_zone_high")),
        target_zone_low=_parse_decimal(payload.get("target_zone_low")),
        target_zone_high=_parse_decimal(payload.get("target_zone_high")),
        invalidation_level=_parse_decimal(payload.get("invalidation_level")),
        source_interval=str(payload.get("source_interval", "")),
        anchor_interval=str(payload.get("anchor_interval", "")),
        map_horizon=_parse_enum(payload.get("map_horizon", Horizon.UNKNOWN.value), Horizon),  # type: ignore[arg-type]
        wave_degree=None if payload.get("wave_degree") is None else str(payload.get("wave_degree")),
        freshness_state=_parse_enum(
            payload.get("freshness_state", FreshnessState.UNKNOWN.value),
            FreshnessState,
        ),  # type: ignore[arg-type]
        quality_flags=_parse_tuple_str(payload.get("quality_flags")),
        conflict_flags=_parse_tuple_str(payload.get("conflict_flags")),
        research_context_flags=_parse_tuple_str(payload.get("research_context_flags")),
        source_refs=_parse_tuple_str(payload.get("source_refs")),
        account_awareness=bool(payload.get("account_awareness", False)),
        broker_write_allowed=bool(payload.get("broker_write_allowed", False)),
        order_submission=bool(payload.get("order_submission", False)),
        decision_required=bool(payload.get("decision_required", True)),
    )
