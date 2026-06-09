"""
credential_validator_v1 — Bitvavo credential validation protocol and mock implementation.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.account_provisioning.contracts_v1 import CredentialValidationState, PlainBitvavoCredential

VALIDATION_STATE_UNAVAILABLE = "VALIDATION_UNAVAILABLE"

_MOCK_VALID_READ_ONLY_PREFIX = "mock-valid-read-only"
_MOCK_UNAVAILABLE_PREFIX = "mock-unavailable"


@dataclass(frozen=True)
class CredentialValidationResult:
    success: bool
    validation_state: str
    capabilities: list[str] = field(default_factory=list)
    safe_error_code: str | None = None


class BitvavoCredentialValidator(Protocol):
    def validate(self, credential: PlainBitvavoCredential) -> CredentialValidationResult:
        ...


@dataclass(frozen=True)
class MockBitvavoCredentialValidator:
    """
    Mock validator for Batch 2. No broker calls, no HTTP.

    Key routing:
      mock-valid-read-only-*  → VALID_READ_ONLY
      mock-unavailable-*      → VALIDATION_UNAVAILABLE
      anything else           → INVALID_CREDENTIALS
    """

    def validate(self, credential: PlainBitvavoCredential) -> CredentialValidationResult:
        key = credential.api_key
        if key.startswith(_MOCK_VALID_READ_ONLY_PREFIX):
            return CredentialValidationResult(
                success=True,
                validation_state=CredentialValidationState.VALID_READ_ONLY.value,
                capabilities=["read_balance", "read_orders"],
            )
        if key.startswith(_MOCK_UNAVAILABLE_PREFIX):
            return CredentialValidationResult(
                success=False,
                validation_state=VALIDATION_STATE_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
            )
        return CredentialValidationResult(
            success=False,
            validation_state=CredentialValidationState.INVALID_CREDENTIALS.value,
            safe_error_code="INVALID_CREDENTIALS",
        )
