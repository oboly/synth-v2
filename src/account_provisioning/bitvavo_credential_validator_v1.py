"""
bitvavo_credential_validator_v1 — Real Bitvavo credential validator.

Uses BitvavoClient with explicit api_key + api_secret (not global env fallback).
Requires SYNTH_BROKER_PRIVATE_READ_PERMISSION env to be set.
Never falls back to global env credentials.

Safety:
  broker_private_calls=1 (read-only: get_balance + get_open_orders)
  broker_writes=0
  order_submission=0
  executor=none

Tests must mock HTTP transport — do not make real API calls in automated tests.
"""
from __future__ import annotations

import os

from src.account_provisioning.contracts_v1 import CredentialValidationState, PlainBitvavoCredential
from src.account_provisioning.credential_validator_v1 import CredentialValidationResult
from src.execution.bitvavo_client import (
    BROKER_PRIVATE_READ_PERMISSION_ENV,
    BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
    BitvavoClient,
)

_VALID_PRIVATE_READ = CredentialValidationState.VALID_PRIVATE_READ.value
_INVALID_CREDENTIALS = CredentialValidationState.INVALID_CREDENTIALS.value
_VALIDATION_UNAVAILABLE = "VALIDATION_UNAVAILABLE"

_HTTP_AUTH_ERROR_CODES = frozenset({401, 403})
_HTTP_SERVER_ERROR_MIN = 500


class RealBitvavoCredentialValidator:
    """
    Validates Bitvavo credentials by calling get_balance() and get_open_orders().

    Uses explicit api_key/api_secret from the credential — never falls back to
    global env vars. This ensures Hugo's credentials are never confused with
    Joost's global-env credentials.

    Requires SYNTH_BROKER_PRIVATE_READ_PERMISSION env (fail-closed).
    """

    def validate(self, credential: PlainBitvavoCredential) -> CredentialValidationResult:
        if os.getenv(BROKER_PRIVATE_READ_PERMISSION_ENV) != BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE:
            return CredentialValidationResult(
                success=False,
                validation_state=_VALIDATION_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
            )

        client = BitvavoClient(
            api_key=credential.api_key,
            api_secret=credential.api_secret,
        )

        try:
            client.get_balance()
            client.get_open_orders()
        except PermissionError:
            return CredentialValidationResult(
                success=False,
                validation_state=_VALIDATION_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
            )
        except Exception as exc:
            status_code = _http_status_from_exception(exc)
            if status_code is not None and status_code in _HTTP_AUTH_ERROR_CODES:
                return CredentialValidationResult(
                    success=False,
                    validation_state=_INVALID_CREDENTIALS,
                    safe_error_code="INVALID_CREDENTIALS",
                )
            return CredentialValidationResult(
                success=False,
                validation_state=_VALIDATION_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
            )

        return CredentialValidationResult(
            success=True,
            validation_state=_VALID_PRIVATE_READ,
            capabilities=["read_balance", "read_orders"],
        )


def _http_status_from_exception(exc: Exception) -> int | None:
    """Extract HTTP status code from requests.HTTPError if present."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return getattr(response, "status_code", None)
