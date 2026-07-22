"""
bitvavo_credential_validator_v1 — Real Bitvavo credential validator.

Uses BitvavoClient with explicit api_key + api_secret (not global env fallback).
Requires SYNTH_BROKER_PRIVATE_READ_PERMISSION env to be set.
Never falls back to global env credentials.

Bitvavo API key requirement: Read ON + Trade ON + Withdraw OFF.
Trade permission on the key does not enable trading in Synth.
Synth live_trading_enabled and broker_write_permission remain disabled separately.

Validation sequence:
  1. get_balance() — proves Read permission is active
  2. get_open_orders() — proves Trade permission is active (required for order visibility)

Error mapping:
  balance 401/403                      → INVALID_CREDENTIALS_OR_READ_PERMISSION
  balance ok, open-orders 401/403      → TRADE_PERMISSION_REQUIRED
  network/server failure (either call) → VALIDATION_UNAVAILABLE
  both calls succeed                   → VALID_PRIVATE_READ

Safety:
  broker_private_calls=2 (read-only: get_balance + get_open_orders)
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
    Validates Bitvavo credentials by calling get_balance() then get_open_orders().

    Both calls are required:
    - get_balance() proves Read permission is active.
    - get_open_orders() proves Trade permission is active (needed for order visibility).

    Trade permission on the Bitvavo key does not enable trading in Synth.
    Synth live_trading_enabled and broker_write_permission remain disabled separately.

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
                broker_private_calls=0,
            )

        client = BitvavoClient.for_private_read(
            api_key=credential.api_key,
            api_secret=credential.api_secret,
        )

        # Step 1: balance — proves Read permission.
        try:
            client.get_balance()
        except PermissionError:
            return CredentialValidationResult(
                success=False,
                validation_state=_VALIDATION_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
                broker_private_calls=1,
            )
        except Exception as exc:
            status_code = _http_status_from_exception(exc)
            if status_code is not None and status_code in _HTTP_AUTH_ERROR_CODES:
                return CredentialValidationResult(
                    success=False,
                    validation_state=_INVALID_CREDENTIALS,
                    safe_error_code="INVALID_CREDENTIALS_OR_READ_PERMISSION",
                    broker_private_calls=1,
                )
            return CredentialValidationResult(
                success=False,
                validation_state=_VALIDATION_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
                broker_private_calls=1,
            )

        # Step 2: open orders — proves Trade permission.
        try:
            client.get_open_orders()
        except PermissionError:
            return CredentialValidationResult(
                success=False,
                validation_state=_VALIDATION_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
                broker_private_calls=2,
            )
        except Exception as exc:
            status_code = _http_status_from_exception(exc)
            if status_code is not None and status_code in _HTTP_AUTH_ERROR_CODES:
                return CredentialValidationResult(
                    success=False,
                    validation_state=_INVALID_CREDENTIALS,
                    safe_error_code="TRADE_PERMISSION_REQUIRED",
                    broker_private_calls=2,
                )
            return CredentialValidationResult(
                success=False,
                validation_state=_VALIDATION_UNAVAILABLE,
                safe_error_code="VALIDATION_UNAVAILABLE",
                broker_private_calls=2,
            )

        return CredentialValidationResult(
            success=True,
            validation_state=_VALID_PRIVATE_READ,
            capabilities=["read_balance", "read_orders"],
            broker_private_calls=2,
        )


def _http_status_from_exception(exc: Exception) -> int | None:
    """Extract HTTP status code from requests.HTTPError if present."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return getattr(response, "status_code", None)
