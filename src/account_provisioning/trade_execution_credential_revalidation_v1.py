"""Canonical revalidation for one existing TRADE_EXECUTION credential.

Issue #584. This account-provisioning service proves that an existing ACTIVE,
db-encrypted Bitvavo TRADE_EXECUTION credential has the exact static safety
metadata Synth requires, then reuses the existing least-privilege credential
validator (balance + open-orders private reads only). A successful full probe
is persisted as ``VALID_TRADE_EXECUTION``.

This module never creates credentials or executor bindings and never grants
LIVE authority. It performs no broker write, order placement/cancel, or
withdrawal call.

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

import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Final, Mapping

from src.account_provisioning.contracts_v1 import (
    CREDENTIAL_SCHEMA_VERSION,
    ENCRYPTION_ALGORITHM,
    CredentialValidationState,
    EncryptedCredentialEnvelope,
    PlainBitvavoCredential,
)
from src.account_provisioning.credential_binding_contract_v1 import (
    PERMISSION_SCOPE_TRADE_EXECUTION,
    CredentialBindingProfile,
    CredentialBindingValidationError,
    validate_credential_binding,
)
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    decrypt_credential,
)
from src.account_provisioning.credential_validator_v1 import (
    BitvavoCredentialValidator,
    CredentialValidationResult,
    VALIDATION_STATE_UNAVAILABLE,
)

SUPPORTED_VENUE: Final[str] = "bitvavo"
CREDENTIAL_KIND_API_KEY_SECRET: Final[str] = "API_KEY_SECRET"
CREDENTIAL_SOURCE_DB_ENCRYPTED: Final[str] = "db_encrypted"
CREDENTIAL_STATUS_ACTIVE: Final[str] = "ACTIVE"

CHECK_READY_TO_VALIDATE: Final[str] = "READY_TO_VALIDATE"
CHECK_ALREADY_VALIDATED: Final[str] = "ALREADY_VALIDATED"
CHECK_BLOCKED: Final[str] = "BLOCKED"

RESULT_VALIDATED: Final[str] = "VALIDATED"
RESULT_ALREADY_VALIDATED: Final[str] = "ALREADY_VALIDATED"
RESULT_INVALID: Final[str] = "INVALID"
RESULT_BLOCKED: Final[str] = "BLOCKED"

_REQUIRED_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"read_balance", "read_orders"}
)
_DEFINITIVE_INVALID_CODES: Final[frozenset[str]] = frozenset(
    {
        "INVALID_CREDENTIALS",
        "INVALID_CREDENTIALS_OR_READ_PERMISSION",
        "TRADE_PERMISSION_REQUIRED",
    }
)


class TradeExecutionCredentialValidationError(RuntimeError):
    """Fail-closed validation service/repository error with safe code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class EncryptedTradeExecutionCredentialRecordV1:
    trading_account_credential_id: int
    trading_account_id: int
    venue: str
    credential_kind: str
    encrypted_envelope: str = field(repr=False)
    encryption_algorithm: str
    key_version: str
    credential_fingerprint: str


@dataclass(frozen=True)
class TradeExecutionCredentialValidationCheckV1:
    check_state: str
    trading_account_id: int
    venue: str
    trading_account_credential_id: int | None = None
    account_code: str | None = None
    previous_validation_state: str | None = None
    validated_ts_utc_present: bool = False
    safe_error_code: str | None = None
    broker_private_calls: int = 0
    broker_writes: int = 0
    order_submission: int = 0
    live_orders: int = 0


@dataclass(frozen=True)
class TradeExecutionCredentialRevalidationResultV1:
    result: str
    trading_account_id: int
    venue: str
    trading_account_credential_id: int | None = None
    account_code: str | None = None
    previous_validation_state: str | None = None
    new_validation_state: str | None = None
    validated_ts_utc_present: bool = False
    safe_error_code: str | None = None
    broker_private_calls: int = 0
    broker_writes: int = 0
    order_submission: int = 0
    live_orders: int = 0


class TradeExecutionCredentialValidationRepositoryV1:
    """Exact metadata/envelope reads plus one exact validation-state update."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def load_metadata_rows(
        self, *, trading_account_id: int, venue: str
    ) -> list[Mapping[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ta.trading_account_id,
                    ta.account_code,
                    tac.venue,
                    ta.enabled AS trading_account_enabled,
                    ta.live_trading_enabled,
                    tac.trading_account_credential_id,
                    tac.credential_source,
                    tac.credential_status,
                    tac.permission_scope,
                    tac.allowed_private_read,
                    tac.allowed_order_write,
                    tac.allowed_withdrawal,
                    tac.credential_fingerprint,
                    tac.key_version,
                    tac.validation_state,
                    tac.validated_ts_utc,
                    tac.last_validation_error_code
                FROM trading_account AS ta
                INNER JOIN trading_account_credential AS tac
                  ON tac.trading_account_id = ta.trading_account_id
                 AND tac.venue = ta.venue
                WHERE ta.trading_account_id = %s
                  AND ta.venue = %s
                  AND tac.permission_scope = 'TRADE_EXECUTION'
                ORDER BY tac.trading_account_credential_id
                """,
                (trading_account_id, venue),
            )
            return list(cur.fetchall())

    def load_encrypted_record(
        self,
        *,
        trading_account_credential_id: int,
        trading_account_id: int,
        venue: str,
    ) -> EncryptedTradeExecutionCredentialRecordV1 | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    trading_account_credential_id,
                    trading_account_id,
                    venue,
                    credential_kind,
                    encrypted_envelope,
                    encryption_algorithm,
                    key_version,
                    credential_fingerprint
                FROM trading_account_credential
                WHERE trading_account_credential_id = %s
                  AND trading_account_id = %s
                  AND venue = %s
                  AND permission_scope = 'TRADE_EXECUTION'
                  AND credential_status = 'ACTIVE'
                """,
                (trading_account_credential_id, trading_account_id, venue),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return EncryptedTradeExecutionCredentialRecordV1(
            trading_account_credential_id=int(row["trading_account_credential_id"]),
            trading_account_id=int(row["trading_account_id"]),
            venue=str(row["venue"]),
            credential_kind=str(row["credential_kind"]),
            encrypted_envelope=str(row["encrypted_envelope"]),
            encryption_algorithm=str(row["encryption_algorithm"]),
            key_version=str(row["key_version"]),
            credential_fingerprint=str(row["credential_fingerprint"]),
        )

    def update_validation_state(
        self,
        *,
        profile: CredentialBindingProfile,
        validation_state: str,
        validated_ts_utc: datetime | None,
        safe_error_code: str | None,
    ) -> None:
        if validation_state == CredentialValidationState.VALID_TRADE_EXECUTION.value:
            if validated_ts_utc is None or safe_error_code is not None:
                raise TradeExecutionCredentialValidationError(
                    "INVALID_SUCCESS_VALIDATION_UPDATE"
                )
            validated_db = _utc_db_text(validated_ts_utc)
        elif validation_state == CredentialValidationState.INVALID_CREDENTIALS.value:
            if validated_ts_utc is not None or safe_error_code not in _DEFINITIVE_INVALID_CODES:
                raise TradeExecutionCredentialValidationError(
                    "INVALID_FAILURE_VALIDATION_UPDATE"
                )
            validated_db = None
        else:
            raise TradeExecutionCredentialValidationError(
                "UNSUPPORTED_TRADE_EXECUTION_VALIDATION_STATE"
            )

        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trading_account_credential
                SET validation_state = %s,
                    validated_ts_utc = %s,
                    last_validation_error_code = %s
                WHERE trading_account_credential_id = %s
                  AND trading_account_id = %s
                  AND venue = %s
                  AND credential_status = 'ACTIVE'
                  AND credential_source = 'db_encrypted'
                  AND permission_scope = 'TRADE_EXECUTION'
                  AND allowed_private_read = 1
                  AND allowed_order_write = 1
                  AND allowed_withdrawal = 0
                  AND credential_fingerprint = %s
                  AND key_version = %s
                """,
                (
                    validation_state,
                    validated_db,
                    safe_error_code,
                    profile.trading_account_credential_id,
                    profile.trading_account_id,
                    profile.venue,
                    profile.credential_fingerprint,
                    profile.key_version,
                ),
            )
            affected = int(cur.rowcount)
        if affected != 1:
            raise TradeExecutionCredentialValidationError(
                "EXACT_ACTIVE_TRADE_EXECUTION_CREDENTIAL_UPDATE_REQUIRED"
            )


def check_trade_execution_credential_validation_v1(
    *,
    trading_account_id: int,
    venue: str,
    conn_factory: Callable[[], Any],
    repository_factory: Callable[[Any], Any] = TradeExecutionCredentialValidationRepositoryV1,
) -> TradeExecutionCredentialValidationCheckV1:
    """Read-only metadata readiness for the explicit private-read validation step."""
    if trading_account_id <= 0:
        return _check_blocked(trading_account_id, venue, "INVALID_TRADING_ACCOUNT_ID")
    if venue != SUPPORTED_VENUE:
        return _check_blocked(trading_account_id, venue, "UNSUPPORTED_VENUE")
    try:
        conn = conn_factory()
    except Exception:
        return _check_blocked(trading_account_id, venue, "DATABASE_UNAVAILABLE")
    try:
        repo = repository_factory(conn)
        try:
            profile = _load_validation_profile(
                repo,
                trading_account_id=trading_account_id,
                venue=venue,
            )
        except TradeExecutionCredentialValidationError as exc:
            return _check_blocked(trading_account_id, venue, exc.code)
        if (
            profile.validation_state
            == CredentialValidationState.VALID_TRADE_EXECUTION.value
        ):
            if profile.validated_ts_utc is None:
                return _check_blocked(
                    trading_account_id,
                    venue,
                    "CREDENTIAL_VALIDATION_TIMESTAMP_MISSING",
                    profile=profile,
                )
            return TradeExecutionCredentialValidationCheckV1(
                check_state=CHECK_ALREADY_VALIDATED,
                trading_account_id=trading_account_id,
                venue=venue,
                trading_account_credential_id=profile.trading_account_credential_id,
                account_code=profile.account_code,
                previous_validation_state=profile.validation_state,
                validated_ts_utc_present=True,
            )
        return TradeExecutionCredentialValidationCheckV1(
            check_state=CHECK_READY_TO_VALIDATE,
            trading_account_id=trading_account_id,
            venue=venue,
            trading_account_credential_id=profile.trading_account_credential_id,
            account_code=profile.account_code,
            previous_validation_state=profile.validation_state,
            validated_ts_utc_present=profile.validated_ts_utc is not None,
        )
    finally:
        conn.close()


class TradeExecutionCredentialRevalidationServiceV1:
    """Revalidate one exact TRADE_EXECUTION credential and own transaction boundaries."""

    def __init__(
        self,
        *,
        master_key_bytes: bytes,
        validator: BitvavoCredentialValidator,
        conn_factory: Callable[[], Any],
        repository_factory: Callable[[Any], Any] = TradeExecutionCredentialValidationRepositoryV1,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._master_key_bytes = master_key_bytes
        self._validator = validator
        self._conn_factory = conn_factory
        self._repository_factory = repository_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def revalidate(
        self, *, trading_account_id: int, venue: str = SUPPORTED_VENUE
    ) -> TradeExecutionCredentialRevalidationResultV1:
        if trading_account_id <= 0:
            return _result_blocked(trading_account_id, venue, "INVALID_TRADING_ACCOUNT_ID")
        if venue != SUPPORTED_VENUE:
            return _result_blocked(trading_account_id, venue, "UNSUPPORTED_VENUE")
        try:
            conn = self._conn_factory()
        except Exception:
            return _result_blocked(trading_account_id, venue, "DATABASE_UNAVAILABLE")

        try:
            repo = self._repository_factory(conn)
            try:
                profile = _load_validation_profile(
                    repo,
                    trading_account_id=trading_account_id,
                    venue=venue,
                )
            except TradeExecutionCredentialValidationError as exc:
                conn.rollback()
                return _result_blocked(trading_account_id, venue, exc.code)

            context = dict(
                trading_account_id=trading_account_id,
                venue=venue,
                trading_account_credential_id=profile.trading_account_credential_id,
                account_code=profile.account_code,
                previous_validation_state=profile.validation_state,
                new_validation_state=profile.validation_state,
                validated_ts_utc_present=profile.validated_ts_utc is not None,
            )
            if (
                profile.validation_state
                == CredentialValidationState.VALID_TRADE_EXECUTION.value
            ):
                if profile.validated_ts_utc is None:
                    conn.rollback()
                    return _result_blocked(
                        **context,
                        safe_error_code="CREDENTIAL_VALIDATION_TIMESTAMP_MISSING",
                    )
                conn.rollback()
                return TradeExecutionCredentialRevalidationResultV1(
                    **context,
                    result=RESULT_ALREADY_VALIDATED,
                )

            try:
                record = repo.load_encrypted_record(
                    trading_account_credential_id=profile.trading_account_credential_id,
                    trading_account_id=profile.trading_account_id,
                    venue=profile.venue,
                )
                credential = _resolve_plain_credential(
                    profile=profile,
                    record=record,
                    master_key_bytes=self._master_key_bytes,
                )
            except TradeExecutionCredentialValidationError as exc:
                conn.rollback()
                return _result_blocked(**context, safe_error_code=exc.code)

            try:
                validation = self._validator.validate(credential)
            except Exception:
                del credential
                conn.rollback()
                return _result_blocked(
                    **context,
                    safe_error_code="VALIDATION_UNAVAILABLE",
                )
            del credential

            broker_private_calls = _broker_private_call_count(validation)
            if _is_unavailable(validation):
                conn.rollback()
                return _result_blocked(
                    **context,
                    safe_error_code="VALIDATION_UNAVAILABLE",
                    broker_private_calls=broker_private_calls,
                )

            if _is_success(validation):
                new_state = CredentialValidationState.VALID_TRADE_EXECUTION.value
                validated_at = self._now_factory()
                safe_error_code = None
                result_code = RESULT_VALIDATED
            elif _is_definitive_invalid(validation):
                new_state = CredentialValidationState.INVALID_CREDENTIALS.value
                validated_at = None
                safe_error_code = validation.safe_error_code
                result_code = RESULT_INVALID
            else:
                conn.rollback()
                return _result_blocked(
                    **context,
                    safe_error_code="INVALID_VALIDATOR_RESULT",
                    broker_private_calls=broker_private_calls,
                )

            try:
                repo.update_validation_state(
                    profile=profile,
                    validation_state=new_state,
                    validated_ts_utc=validated_at,
                    safe_error_code=safe_error_code,
                )
                conn.commit()
            except TradeExecutionCredentialValidationError as exc:
                conn.rollback()
                return _result_blocked(
                    **context,
                    safe_error_code=exc.code,
                    broker_private_calls=broker_private_calls,
                )
            except Exception:
                conn.rollback()
                return _result_blocked(
                    **context,
                    safe_error_code="PERSISTENCE_FAILED",
                    broker_private_calls=broker_private_calls,
                )

            return TradeExecutionCredentialRevalidationResultV1(
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


def _load_validation_profile(
    repo: Any, *, trading_account_id: int, venue: str
) -> CredentialBindingProfile:
    try:
        rows = repo.load_metadata_rows(
            trading_account_id=trading_account_id,
            venue=venue,
        )
        return validate_credential_binding(
            rows,
            trading_account_id=trading_account_id,
            venue=venue,
            required_permission_scope=PERMISSION_SCOPE_TRADE_EXECUTION,
            require_validated=False,
            allow_legacy_source=False,
        )
    except CredentialBindingValidationError as exc:
        raise TradeExecutionCredentialValidationError(exc.code) from None
    except TradeExecutionCredentialValidationError:
        raise
    except Exception:
        raise TradeExecutionCredentialValidationError(
            "STRUCTURAL_VALIDATION_FAILED"
        ) from None


def _resolve_plain_credential(
    *,
    profile: CredentialBindingProfile,
    record: EncryptedTradeExecutionCredentialRecordV1 | None,
    master_key_bytes: bytes,
) -> PlainBitvavoCredential:
    if record is None:
        raise TradeExecutionCredentialValidationError(
            "ENCRYPTED_CREDENTIAL_RECORD_NOT_FOUND"
        )
    if record.credential_kind != CREDENTIAL_KIND_API_KEY_SECRET:
        raise TradeExecutionCredentialValidationError("UNSUPPORTED_CREDENTIAL_KIND")
    if record.encryption_algorithm != ENCRYPTION_ALGORITHM:
        raise TradeExecutionCredentialValidationError(
            "UNSUPPORTED_CREDENTIAL_ENCRYPTION_ALGORITHM"
        )
    if record.key_version != profile.key_version:
        raise TradeExecutionCredentialValidationError("CREDENTIAL_KEY_VERSION_MISMATCH")
    if record.credential_fingerprint != profile.credential_fingerprint:
        raise TradeExecutionCredentialValidationError(
            "CREDENTIAL_FINGERPRINT_METADATA_MISMATCH"
        )
    try:
        envelope = EncryptedCredentialEnvelope.from_json(record.encrypted_envelope)
    except (KeyError, TypeError, ValueError):
        raise TradeExecutionCredentialValidationError("INVALID_CREDENTIAL_ENVELOPE") from None
    if envelope.alg != ENCRYPTION_ALGORITHM or envelope.alg != record.encryption_algorithm:
        raise TradeExecutionCredentialValidationError("CREDENTIAL_ENVELOPE_ALGORITHM_MISMATCH")
    if envelope.kv != record.key_version or envelope.sv != CREDENTIAL_SCHEMA_VERSION:
        raise TradeExecutionCredentialValidationError("CREDENTIAL_ENVELOPE_VERSION_MISMATCH")
    if envelope.venue != profile.venue:
        raise TradeExecutionCredentialValidationError("CREDENTIAL_ENVELOPE_VENUE_MISMATCH")
    if envelope.trading_account_id != profile.trading_account_id:
        raise TradeExecutionCredentialValidationError("CREDENTIAL_ENVELOPE_ACCOUNT_MISMATCH")
    try:
        credential = decrypt_credential(envelope, master_key_bytes)
    except ValueError:
        raise TradeExecutionCredentialValidationError("CREDENTIAL_DECRYPTION_FAILED") from None
    expected_fingerprint = compute_fingerprint(
        profile.venue,
        credential.api_key,
        master_key_bytes,
    )
    if not hmac.compare_digest(expected_fingerprint, profile.credential_fingerprint):
        raise TradeExecutionCredentialValidationError("CREDENTIAL_FINGERPRINT_MISMATCH")
    return credential


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
        and validation.safe_error_code is None
        and _REQUIRED_CAPABILITIES.issubset(validation.capabilities)
    )


def _is_definitive_invalid(validation: CredentialValidationResult) -> bool:
    return (
        validation.success is False
        and validation.validation_state
        == CredentialValidationState.INVALID_CREDENTIALS.value
        and validation.safe_error_code in _DEFINITIVE_INVALID_CODES
    )


def _utc_db_text(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _check_blocked(
    trading_account_id: int,
    venue: str,
    safe_error_code: str,
    *,
    profile: CredentialBindingProfile | None = None,
) -> TradeExecutionCredentialValidationCheckV1:
    return TradeExecutionCredentialValidationCheckV1(
        check_state=CHECK_BLOCKED,
        trading_account_id=trading_account_id,
        venue=venue,
        trading_account_credential_id=(
            None if profile is None else profile.trading_account_credential_id
        ),
        account_code=None if profile is None else profile.account_code,
        previous_validation_state=None if profile is None else profile.validation_state,
        validated_ts_utc_present=(
            False if profile is None else profile.validated_ts_utc is not None
        ),
        safe_error_code=safe_error_code,
    )


def _result_blocked(
    trading_account_id: int,
    venue: str,
    safe_error_code: str,
    *,
    broker_private_calls: int = 0,
    **context: Any,
) -> TradeExecutionCredentialRevalidationResultV1:
    return TradeExecutionCredentialRevalidationResultV1(
        **context,
        result=RESULT_BLOCKED,
        trading_account_id=trading_account_id,
        venue=venue,
        safe_error_code=safe_error_code,
        broker_private_calls=broker_private_calls,
    )
