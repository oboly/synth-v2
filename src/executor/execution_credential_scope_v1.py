"""Deny-by-default, non-secret TRADE_EXECUTION credential scope resolver."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Final

from src.account_provisioning.contracts_v1 import CredentialValidationState

TRADE_EXECUTION_SCOPE: Final[str] = "TRADE_EXECUTION"
CREDENTIAL_STATUS_ACTIVE: Final[str] = "ACTIVE"
CREDENTIAL_SOURCE_DB_ENCRYPTED: Final[str] = "db_encrypted"
BINDING_STATUS_ACTIVE: Final[str] = "ACTIVE"
VALID_TRADE_EXECUTION_STATE: Final[str] = CredentialValidationState.VALID_TRADE_EXECUTION.value


class CredentialScopeDeniedError(PermissionError):
    """No exact active validated order-writing, withdrawal-disabled binding exists."""


@dataclass(frozen=True)
class CredentialScopeBinding:
    executor_credential_binding_id: int
    trading_account_credential_id: int
    trading_account_id: int
    venue: str
    permission_scope: str
    executor_identity: str
    runtime_owner: str
    credential_status: str
    credential_source: str
    allowed_order_write: bool
    allowed_withdrawal: bool
    allowed_private_read: bool = False
    validation_state: str = CredentialValidationState.UNVALIDATED.value
    validated_ts_utc: Any | None = None
    binding_status: str = BINDING_STATUS_ACTIVE


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


_SCOPE_SELECT: Final[str] = '''
SELECT binding.executor_credential_binding_id, binding.trading_account_credential_id,
 binding.trading_account_id, binding.venue, binding.permission_scope,
 binding.executor_identity, binding.runtime_owner, binding.binding_status,
 credential.trading_account_id AS credential_trading_account_id,
 credential.venue AS credential_venue, credential.permission_scope AS credential_permission_scope,
 credential.credential_status, credential.credential_source,
 credential.allowed_private_read, credential.allowed_order_write, credential.allowed_withdrawal,
 credential.validation_state, credential.validated_ts_utc
FROM executor_credential_binding AS binding
INNER JOIN trading_account_credential AS credential
 ON credential.trading_account_credential_id=binding.trading_account_credential_id
 AND credential.trading_account_id=binding.trading_account_id
 AND credential.venue=binding.venue
 AND credential.permission_scope=binding.permission_scope
WHERE binding.trading_account_id=%s AND binding.venue=%s
 AND binding.executor_identity=%s AND binding.runtime_owner=%s
 AND binding.binding_status=%s
'''


def _row_to_binding(row: Any) -> CredentialScopeBinding:
    bool_fields = {"allowed_private_read", "allowed_order_write", "allowed_withdrawal"}
    values: dict[str, Any] = {}
    for key in CredentialScopeBinding.__dataclass_fields__:
        if key == "validated_ts_utc":
            values[key] = row[key]
        elif key in bool_fields:
            values[key] = bool(row[key])
        elif key.endswith("_id"):
            values[key] = int(row[key])
        else:
            values[key] = str(row[key])
    return CredentialScopeBinding(**values)


def _assert_credential_identity_match(row: Any, *, binding: CredentialScopeBinding) -> None:
    if int(row["credential_trading_account_id"]) != binding.trading_account_id:
        raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_ACCOUNT_MISMATCH")
    if str(row["credential_venue"]) != binding.venue:
        raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_VENUE_MISMATCH")
    if str(row["credential_permission_scope"]) != binding.permission_scope:
        raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_PERMISSION_SCOPE_MISMATCH")


@dataclass
class ExecutorCredentialScopeRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def resolve(
        self,
        *,
        trading_account_id: int,
        venue: str,
        executor_identity: str,
        runtime_owner: str,
        cursor: Any | None = None,
    ) -> CredentialScopeBinding:
        if cursor is not None:
            return self._resolve(
                cursor,
                trading_account_id=trading_account_id,
                venue=venue,
                executor_identity=executor_identity,
                runtime_owner=runtime_owner,
            )
        with self.cursor_factory() as db_obj:
            return self._resolve(
                _unwrap_cursor(db_obj),
                trading_account_id=trading_account_id,
                venue=venue,
                executor_identity=executor_identity,
                runtime_owner=runtime_owner,
            )

    @staticmethod
    def _resolve(
        cursor: Any,
        *,
        trading_account_id: int,
        venue: str,
        executor_identity: str,
        runtime_owner: str,
    ) -> CredentialScopeBinding:
        cursor.execute(
            _SCOPE_SELECT,
            [
                trading_account_id,
                venue,
                executor_identity,
                runtime_owner,
                BINDING_STATUS_ACTIVE,
            ],
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise CredentialScopeDeniedError(
                "CREDENTIAL_SCOPE_NOT_BOUND" if not rows else "CREDENTIAL_SCOPE_AMBIGUOUS"
            )
        binding = _row_to_binding(rows[0])
        _assert_credential_identity_match(rows[0], binding=binding)
        if binding.permission_scope != TRADE_EXECUTION_SCOPE:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_TRADE_EXECUTION")
        if binding.credential_status != CREDENTIAL_STATUS_ACTIVE:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_CREDENTIAL_NOT_ACTIVE")
        if binding.credential_source != CREDENTIAL_SOURCE_DB_ENCRYPTED:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_CREDENTIAL_SOURCE_NOT_DB_ENCRYPTED")
        if not binding.allowed_private_read:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_PRIVATE_READ_NOT_PERMITTED")
        if not binding.allowed_order_write:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_ORDER_WRITE_NOT_PERMITTED")
        if binding.allowed_withdrawal:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_WITHDRAWAL_CAPABLE_CREDENTIAL_DENIED")
        if binding.validation_state != VALID_TRADE_EXECUTION_STATE:
            raise CredentialScopeDeniedError(
                "CREDENTIAL_SCOPE_CREDENTIAL_NOT_VALIDATED_FOR_TRADE_EXECUTION"
            )
        if binding.validated_ts_utc is None:
            raise CredentialScopeDeniedError(
                "CREDENTIAL_SCOPE_CREDENTIAL_VALIDATION_TIMESTAMP_MISSING"
            )
        return binding
