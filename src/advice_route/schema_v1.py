from __future__ import annotations

from typing import Any

from src.advice_route.interfaces_v1 import FORBIDDEN_FIELD_SUBSTRINGS


ROUTE_VERSION: str = "v1"
SCHEMA_VERSION: str = "v1"

SUPPORTED_ROUTE_VERSIONS: frozenset[str] = frozenset({"v1"})
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"v1"})
SUPPORTED_PAYLOAD_TYPES: frozenset[str] = frozenset({
    "framework_context",
    "synth_confirmation_context",
    "strategy_interpretation",
    "strategy_proposal",
})

ENVELOPE_REQUIRED_KEYS: frozenset[str] = frozenset({
    "payload_type",
    "route_version",
    "schema_version",
    "payload",
})


def validate_envelope(envelope: dict[str, Any]) -> None:
    if not isinstance(envelope, dict):
        raise TypeError(f"Envelope must be a dict, got {type(envelope).__name__}")

    for key in envelope:
        normalized = str(key).lower()
        for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
            if forbidden in normalized:
                raise ValueError(f"Forbidden field in envelope: {key!r}")

    missing = ENVELOPE_REQUIRED_KEYS - set(envelope.keys())
    if missing:
        raise ValueError(f"Envelope missing required keys: {sorted(missing)}")

    route_version = envelope["route_version"]
    if route_version not in SUPPORTED_ROUTE_VERSIONS:
        raise ValueError(
            f"Unsupported route_version={route_version!r}; supported: {sorted(SUPPORTED_ROUTE_VERSIONS)}"
        )

    schema_version = envelope["schema_version"]
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported schema_version={schema_version!r}; supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    payload_type = envelope["payload_type"]
    if payload_type not in SUPPORTED_PAYLOAD_TYPES:
        raise ValueError(
            f"Unknown payload_type={payload_type!r}; supported: {sorted(SUPPORTED_PAYLOAD_TYPES)}"
        )

    if not isinstance(envelope["payload"], dict):
        raise ValueError(
            f"Envelope payload must be a dict, got {type(envelope['payload']).__name__}"
        )
