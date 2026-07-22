"""Canonical revalidation for an existing encrypted private-read credential.

This service owns transaction boundaries around one exact existing ACTIVE
credential binding. Static binding/envelope/decryption/fingerprint checks run
before the injected validator may perform private account reads.

Safety:
  broker_private_calls=validator_result_only
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from src.account.private_read_credential_resolver_v1 import (
    PrivateReadCredentialResolutionError,
    resolve_existing_private_read_credential_for_revalidation,
)
from src.account_provisioning.contracts_v1 import CredentialValidationState
from src.account_provisioning.credential_repository_v1 import (
    CredentialRepository,
    CredentialValidationUpdateError,
    DEFINITIVE_PRIVATE_READ_VALIDATION_ERROR_CODES,
)
from src.account_provisioning.credential_validator_v1 import (
    BitvavoCredentialValidator,
    CredentialValidationResult,
    VALIDATION_STATE_UNAVAILABLE,
)

SUPPORTED_VENUE = "bitvavo"
RESULT_SUCCESS = "SUCCESS"
RESULT_INVALID = "INVALID"
RESULT_BLOCKED = "BLOCKED"

_REQUIRED_CAPABILITIES = frozenset({"read_balance", "read_orders"})


@dataclass(frozen=True)
class ExistingCredentialRevalidationResult:
    result: str
    trading_account_id: int | None = None
    account_code: str | None = None
    profile_code: str | None = None
    venue: str = SUPPORTED_VENUE
    trading_account_credential_id: int | None = None
    credential_source: str | None = None
    permission_scope: str | None = None
    previous_validation_state: str | None = None
    new_validation_state: str | None = None
    validated_ts_utc_present: bool = False
    safe_error_code: str | None = None
    broker_private_calls: int = 0
    broker_writes: int = 0
    order_submission: int = 0
    live_orders: int = 0


class ExistingCredentialRevalidationService:
    """Revalidate one existing binding and own commit/rollback/close."""

    def __init__(
        self,
        *,
        master_key_bytes: bytes,
        validator: BitvavoCredentialValidator,
        conn_factory: Callable[[], Any],
        repository_factory: Callable[[Any], Any] = CredentialRepository,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._master_key_bytes = master_key_bytes
        self._validator = validator
        self._conn_factory = conn_factory
        self._repository_factory = repository_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def revalidate(
        self,
        *,
        venue: str = SUPPORTED_VENUE,
        trading_account_id: int | None = None,
        account_code: str | None = None,
        profile_code: str | None = None,
    ) -> ExistingCredentialRevalidationResult:
        selector_count = sum(
            (
                trading_account_id is not None,
                bool((account_code or "").strip()),
                bool((profile_code or "").strip()),
            )
        )
        if selector_count != 1:
            return _blocked(
                venue=venue,
                profile_code=profile_code,
                safe_error_code="ACCOUNT_IDENTITY_NOT_EXACT",
            )
        if venue != SUPPORTED_VENUE:
            return _blocked(
                venue=venue,
                profile_code=profile_code,
                safe_error_code="UNSUPPORTED_VENUE",
            )

        try:
            conn = self._conn_factory()
        except Exception:
            return _blocked(
                venue=venue,
                profile_code=profile_code,
                safe_error_code="DATABASE_UNAVAILABLE",
            )

        context: dict[str, Any] = {
            "venue": venue,
            "profile_code": profile_code,
        }
        try:
            try:
                identity, resolved = (
                    resolve_existing_private_read_credential_for_revalidation(
                        conn,
                        master_key_bytes=self._master_key_bytes,
                        venue=venue,
                        trading_account_id=trading_account_id,
                        account_code=account_code,
                        profile_code=profile_code,
                    )
                )
            except PrivateReadCredentialResolutionError as exc:
                conn.rollback()
                return _blocked(
                    **context,
                    safe_error_code=exc.code,
                )
            except Exception:
                conn.rollback()
                return _blocked(
                    **context,
                    safe_error_code="STRUCTURAL_VALIDATION_FAILED",
                )

            profile = resolved.profile
            context.update(
                {
                    "trading_account_id": identity.trading_account_id,
                    "account_code": identity.account_code,
                    "trading_account_credential_id": (
                        profile.trading_account_credential_id
                    ),
                    "credential_source": profile.credential_source,
                    "permission_scope": profile.permission_scope,
                    "previous_validation_state": profile.validation_state,
                    "new_validation_state": profile.validation_state,
                    "validated_ts_utc_present": (
                        profile.validated_ts_utc is not None
                    ),
                }
            )

            try:
                validation = self._validator.validate(resolved.credential)
            except Exception:
                del resolved
                conn.rollback()
                return _blocked(
                    **context,
                    safe_error_code="VALIDATION_UNAVAILABLE",
                )
            del resolved

            broker_private_calls = _broker_private_call_count(validation)
            if _is_unavailable(validation):
                conn.rollback()
                return _blocked(
                    **context,
                    safe_error_code="VALIDATION_UNAVAILABLE",
                    broker_private_calls=broker_private_calls,
                )

            if _is_success(validation):
                new_state = CredentialValidationState.VALID_PRIVATE_READ.value
                validated_at = self._now_factory()
                safe_error_code = None
                result_code = RESULT_SUCCESS
            elif _is_definitive_invalid(validation):
                new_state = CredentialValidationState.INVALID_CREDENTIALS.value
                validated_at = None
                safe_error_code = validation.safe_error_code
                result_code = RESULT_INVALID
            else:
                conn.rollback()
                return _blocked(
                    **context,
                    safe_error_code="INVALID_VALIDATOR_RESULT",
                    broker_private_calls=broker_private_calls,
                )

            try:
                repository = self._repository_factory(conn)
                repository.update_existing_active_credential_validation(
                    trading_account_credential_id=(
                        profile.trading_account_credential_id
                    ),
                    trading_account_id=identity.trading_account_id,
                    venue=identity.venue,
                    validation_state=new_state,
                    validated_ts_utc=validated_at,
                    safe_error_code=safe_error_code,
                )
                conn.commit()
            except CredentialValidationUpdateError as exc:
                conn.rollback()
                return _blocked(
                    **context,
                    safe_error_code=exc.code,
                    broker_private_calls=broker_private_calls,
                )
            except Exception:
                conn.rollback()
                return _blocked(
                    **context,
                    safe_error_code="PERSISTENCE_FAILED",
                    broker_private_calls=broker_private_calls,
                )

            return ExistingCredentialRevalidationResult(
                **{
                    **context,
                    "result": result_code,
                    "new_validation_state": new_state,
                    "validated_ts_utc_present": validated_at is not None,
                    "safe_error_code": safe_error_code,
                    "broker_private_calls": broker_private_calls,
                }
            )
        finally:
            conn.close()


def _broker_private_call_count(validation: CredentialValidationResult) -> int:
    value = validation.broker_private_calls
    return value if isinstance(value, int) and value >= 0 else 0


def _is_unavailable(validation: CredentialValidationResult) -> bool:
    return (
        validation.validation_state == VALIDATION_STATE_UNAVAILABLE
        or validation.safe_error_code == "VALIDATION_UNAVAILABLE"
    )


def _is_success(validation: CredentialValidationResult) -> bool:
    return (
        validation.success is True
        and validation.validation_state
        == CredentialValidationState.VALID_PRIVATE_READ.value
        and _REQUIRED_CAPABILITIES.issubset(validation.capabilities)
    )


def _is_definitive_invalid(validation: CredentialValidationResult) -> bool:
    return (
        validation.success is False
        and validation.validation_state
        == CredentialValidationState.INVALID_CREDENTIALS.value
        and validation.safe_error_code
        in DEFINITIVE_PRIVATE_READ_VALIDATION_ERROR_CODES
    )


def _blocked(
    *,
    venue: str,
    profile_code: str | None,
    safe_error_code: str,
    broker_private_calls: int = 0,
    **context: Any,
) -> ExistingCredentialRevalidationResult:
    return ExistingCredentialRevalidationResult(
        **context,
        result=RESULT_BLOCKED,
        venue=venue,
        profile_code=profile_code,
        safe_error_code=safe_error_code,
        broker_private_calls=broker_private_calls,
    )
