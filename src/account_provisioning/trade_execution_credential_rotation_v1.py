"""Explicit in-place rotation for one ACTIVE db-encrypted TRADE_EXECUTION credential.

Issue #589.

This module belongs to account_provisioning only. Rotation changes the encrypted
broker credential payload for one exact existing credential row while
preserving the credential id and every executor binding. It performs no broker
calls and grants no LIVE authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Final, Mapping

from src.account_provisioning.contracts_v1 import (
    ENCRYPTION_ALGORITHM,
    PlainBitvavoCredential,
)
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
)

SUPPORTED_VENUE: Final[str] = "bitvavo"
PERMISSION_SCOPE: Final[str] = "TRADE_EXECUTION"
CREDENTIAL_SOURCE: Final[str] = "db_encrypted"
CREDENTIAL_STATUS: Final[str] = "ACTIVE"
CREDENTIAL_KIND: Final[str] = "API_KEY_SECRET"

CHECK_READY: Final[str] = "READY_TO_ROTATE"
CHECK_BLOCKED: Final[str] = "BLOCKED"
RESULT_ROTATED: Final[str] = "ROTATED"
RESULT_BLOCKED: Final[str] = "BLOCKED"


class TradeExecutionCredentialRotationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TradeExecutionCredentialRotationCheckV1:
    check_state: str
    trading_account_id: int
    trading_account_credential_id: int
    venue: str
    binding_count: int = 0
    previous_validation_state: str | None = None
    safe_error_code: str | None = None
    credential_mutations: int = 0
    binding_mutations: int = 0
    broker_private_calls: int = 0
    broker_writes: int = 0
    order_submission: int = 0
    live_orders: int = 0


@dataclass(frozen=True)
class TradeExecutionCredentialRotationResultV1:
    result: str
    trading_account_id: int
    trading_account_credential_id: int
    venue: str
    binding_count: int = 0
    previous_validation_state: str | None = None
    new_validation_state: str | None = None
    safe_error_code: str | None = None
    credential_mutations: int = 0
    binding_mutations: int = 0
    broker_private_calls: int = 0
    broker_writes: int = 0
    order_submission: int = 0
    live_orders: int = 0


class TradeExecutionCredentialRotationRepositoryV1:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def load_credential(self, *, trading_account_credential_id: int) -> Mapping[str, Any] | None:
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
                    credential_fingerprint,
                    credential_status,
                    validation_state,
                    credential_source,
                    permission_scope,
                    allowed_private_read,
                    allowed_order_write,
                    allowed_withdrawal,
                    validated_ts_utc,
                    last_validation_error_code
                FROM trading_account_credential
                WHERE trading_account_credential_id = %s
                """,
                (trading_account_credential_id,),
            )
            return cur.fetchone()

    def count_bindings(self, *, trading_account_credential_id: int) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS binding_count
                FROM executor_credential_binding
                WHERE trading_account_credential_id = %s
                """,
                (trading_account_credential_id,),
            )
            row = cur.fetchone()
        if row is None:
            return 0
        return int(row["binding_count"])

    def rotate_exact(
        self,
        *,
        row: Mapping[str, Any],
        encrypted_envelope: str,
        encryption_algorithm: str,
        key_version: str,
        credential_fingerprint: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trading_account_credential
                SET encrypted_envelope = %s,
                    encryption_algorithm = %s,
                    key_version = %s,
                    credential_fingerprint = %s,
                    validation_state = 'UNVALIDATED',
                    validated_ts_utc = NULL,
                    last_validation_error_code = NULL
                WHERE trading_account_credential_id = %s
                  AND trading_account_id = %s
                  AND venue = %s
                  AND credential_kind = 'API_KEY_SECRET'
                  AND credential_status = 'ACTIVE'
                  AND credential_source = 'db_encrypted'
                  AND permission_scope = 'TRADE_EXECUTION'
                  AND allowed_private_read = 1
                  AND allowed_order_write = 1
                  AND allowed_withdrawal = 0
                  AND encrypted_envelope = %s
                  AND encryption_algorithm = %s
                  AND credential_fingerprint = %s
                  AND key_version = %s
                """,
                (
                    encrypted_envelope,
                    encryption_algorithm,
                    key_version,
                    credential_fingerprint,
                    int(row["trading_account_credential_id"]),
                    int(row["trading_account_id"]),
                    str(row["venue"]),
                    str(row["encrypted_envelope"]),
                    str(row["encryption_algorithm"]),
                    str(row["credential_fingerprint"]),
                    str(row["key_version"]),
                ),
            )
            if int(cur.rowcount) != 1:
                raise TradeExecutionCredentialRotationError(
                    "EXACT_ACTIVE_TRADE_EXECUTION_CREDENTIAL_UPDATE_REQUIRED"
                )


def _validate_row(
    row: Mapping[str, Any] | None,
    *,
    trading_account_id: int,
    trading_account_credential_id: int,
    venue: str,
) -> Mapping[str, Any]:
    if trading_account_id <= 0:
        raise TradeExecutionCredentialRotationError("INVALID_TRADING_ACCOUNT_ID")
    if trading_account_credential_id <= 0:
        raise TradeExecutionCredentialRotationError("INVALID_CREDENTIAL_ID")
    if venue != SUPPORTED_VENUE:
        raise TradeExecutionCredentialRotationError("UNSUPPORTED_VENUE")
    if row is None:
        raise TradeExecutionCredentialRotationError("TRADE_EXECUTION_CREDENTIAL_NOT_FOUND")
    if int(row["trading_account_id"]) != trading_account_id:
        raise TradeExecutionCredentialRotationError("CREDENTIAL_ACCOUNT_ID_MISMATCH")
    if str(row["venue"]) != venue:
        raise TradeExecutionCredentialRotationError("CREDENTIAL_VENUE_MISMATCH")
    if str(row["credential_kind"]) != CREDENTIAL_KIND:
        raise TradeExecutionCredentialRotationError("CREDENTIAL_KIND_MISMATCH")
    if str(row["credential_status"]) != CREDENTIAL_STATUS:
        raise TradeExecutionCredentialRotationError("CREDENTIAL_NOT_ACTIVE")
    if str(row["credential_source"]) != CREDENTIAL_SOURCE:
        raise TradeExecutionCredentialRotationError("CREDENTIAL_SOURCE_MISMATCH")
    if str(row["permission_scope"]) != PERMISSION_SCOPE:
        raise TradeExecutionCredentialRotationError("CREDENTIAL_PERMISSION_SCOPE_MISMATCH")
    if not bool(row["allowed_private_read"]):
        raise TradeExecutionCredentialRotationError("CREDENTIAL_MISSING_PRIVATE_READ_SCOPE")
    if not bool(row["allowed_order_write"]):
        raise TradeExecutionCredentialRotationError("CREDENTIAL_MISSING_ORDER_WRITE_SCOPE")
    if bool(row["allowed_withdrawal"]):
        raise TradeExecutionCredentialRotationError("CREDENTIAL_WITHDRAWAL_CAPABILITY_NOT_ALLOWED")
    if not str(row["encrypted_envelope"]):
        raise TradeExecutionCredentialRotationError("CREDENTIAL_ENCRYPTED_ENVELOPE_MISSING")
    if str(row["encryption_algorithm"]) != ENCRYPTION_ALGORITHM:
        raise TradeExecutionCredentialRotationError("UNSUPPORTED_CREDENTIAL_ENCRYPTION_ALGORITHM")
    if not str(row["credential_fingerprint"]):
        raise TradeExecutionCredentialRotationError("CREDENTIAL_FINGERPRINT_MISSING")
    if not str(row["key_version"]):
        raise TradeExecutionCredentialRotationError("CREDENTIAL_KEY_VERSION_MISSING")
    return row


def _blocked_check(
    *, trading_account_id: int,
    trading_account_credential_id: int,
    venue: str,
    code: str,
) -> TradeExecutionCredentialRotationCheckV1:
    return TradeExecutionCredentialRotationCheckV1(
        check_state=CHECK_BLOCKED,
        trading_account_id=trading_account_id,
        trading_account_credential_id=trading_account_credential_id,
        venue=venue,
        safe_error_code=code,
    )


def check_trade_execution_credential_rotation_v1(
    *,
    trading_account_id: int,
    trading_account_credential_id: int,
    venue: str,
    conn_factory: Callable[[], Any],
    repository_factory: Callable[[Any], Any] = TradeExecutionCredentialRotationRepositoryV1,
) -> TradeExecutionCredentialRotationCheckV1:
    try:
        conn = conn_factory()
    except Exception:
        return _blocked_check(
            trading_account_id=trading_account_id,
            trading_account_credential_id=trading_account_credential_id,
            venue=venue,
            code="DATABASE_UNAVAILABLE",
        )
    try:
        repo = repository_factory(conn)
        try:
            row = _validate_row(
                repo.load_credential(
                    trading_account_credential_id=trading_account_credential_id
                ),
                trading_account_id=trading_account_id,
                trading_account_credential_id=trading_account_credential_id,
                venue=venue,
            )
            binding_count = repo.count_bindings(
                trading_account_credential_id=trading_account_credential_id
            )
        except TradeExecutionCredentialRotationError as exc:
            conn.rollback()
            return _blocked_check(
                trading_account_id=trading_account_id,
                trading_account_credential_id=trading_account_credential_id,
                venue=venue,
                code=exc.code,
            )
        except Exception:
            conn.rollback()
            return _blocked_check(
                trading_account_id=trading_account_id,
                trading_account_credential_id=trading_account_credential_id,
                venue=venue,
                code="CHECK_FAILED",
            )
        conn.rollback()
        return TradeExecutionCredentialRotationCheckV1(
            check_state=CHECK_READY,
            trading_account_id=trading_account_id,
            trading_account_credential_id=trading_account_credential_id,
            venue=venue,
            binding_count=binding_count,
            previous_validation_state=str(row["validation_state"]),
        )
    finally:
        conn.close()


def rotate_trade_execution_credential_v1(
    *,
    trading_account_id: int,
    trading_account_credential_id: int,
    venue: str,
    api_key: str,
    api_secret: str,
    master_key_version: str,
    master_key_bytes: bytes,
    conn_factory: Callable[[], Any],
    repository_factory: Callable[[Any], Any] = TradeExecutionCredentialRotationRepositoryV1,
) -> TradeExecutionCredentialRotationResultV1:
    if not api_key.strip() or not api_secret.strip():
        return TradeExecutionCredentialRotationResultV1(
            result=RESULT_BLOCKED,
            trading_account_id=trading_account_id,
            trading_account_credential_id=trading_account_credential_id,
            venue=venue,
            safe_error_code="BLANK_SECRET_INPUT",
        )
    try:
        conn = conn_factory()
    except Exception:
        return TradeExecutionCredentialRotationResultV1(
            result=RESULT_BLOCKED,
            trading_account_id=trading_account_id,
            trading_account_credential_id=trading_account_credential_id,
            venue=venue,
            safe_error_code="DATABASE_UNAVAILABLE",
        )

    try:
        repo = repository_factory(conn)
        try:
            row = _validate_row(
                repo.load_credential(
                    trading_account_credential_id=trading_account_credential_id
                ),
                trading_account_id=trading_account_id,
                trading_account_credential_id=trading_account_credential_id,
                venue=venue,
            )
            binding_count = repo.count_bindings(
                trading_account_credential_id=trading_account_credential_id
            )
            new_fingerprint = compute_fingerprint(venue, api_key, master_key_bytes)
            if new_fingerprint == str(row["credential_fingerprint"]):
                raise TradeExecutionCredentialRotationError(
                    "NEW_CREDENTIAL_MATCHES_CURRENT_API_KEY"
                )
            credential = PlainBitvavoCredential(
                venue=venue,
                api_key=api_key,
                api_secret=api_secret,
            )
            envelope = encrypt_credential(
                credential,
                trading_account_id,
                master_key_version,
                master_key_bytes,
            )
            repo.rotate_exact(
                row=row,
                encrypted_envelope=envelope.to_json(),
                encryption_algorithm=envelope.alg,
                key_version=envelope.kv,
                credential_fingerprint=new_fingerprint,
            )
            conn.commit()
        except TradeExecutionCredentialRotationError as exc:
            conn.rollback()
            return TradeExecutionCredentialRotationResultV1(
                result=RESULT_BLOCKED,
                trading_account_id=trading_account_id,
                trading_account_credential_id=trading_account_credential_id,
                venue=venue,
                safe_error_code=exc.code,
            )
        except Exception:
            conn.rollback()
            return TradeExecutionCredentialRotationResultV1(
                result=RESULT_BLOCKED,
                trading_account_id=trading_account_id,
                trading_account_credential_id=trading_account_credential_id,
                venue=venue,
                safe_error_code="ROTATION_FAILED",
            )

        return TradeExecutionCredentialRotationResultV1(
            result=RESULT_ROTATED,
            trading_account_id=trading_account_id,
            trading_account_credential_id=trading_account_credential_id,
            venue=venue,
            binding_count=binding_count,
            previous_validation_state=str(row["validation_state"]),
            new_validation_state="UNVALIDATED",
            credential_mutations=1,
        )
    finally:
        conn.close()
