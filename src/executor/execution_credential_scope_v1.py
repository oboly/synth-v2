"""Deny-by-default, non-secret TRADE_EXECUTION credential scope resolver."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Final

TRADE_EXECUTION_SCOPE: Final[str] = "TRADE_EXECUTION"
CREDENTIAL_STATUS_ACTIVE: Final[str] = "ACTIVE"
BINDING_STATUS_ACTIVE: Final[str] = "ACTIVE"

class CredentialScopeDeniedError(PermissionError):
    """No exact active order-writing, withdrawal-disabled binding exists."""

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

def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)

def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj

_SCOPE_SELECT: Final[str] = '''
SELECT binding.executor_credential_binding_id, binding.trading_account_credential_id,
 binding.trading_account_id, binding.venue, binding.permission_scope,
 binding.executor_identity, binding.runtime_owner,
 credential.trading_account_id AS credential_trading_account_id,
 credential.venue AS credential_venue, credential.permission_scope AS credential_permission_scope,
 credential.credential_status, credential.credential_source,
 credential.allowed_order_write, credential.allowed_withdrawal
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
    return CredentialScopeBinding(**{key: (bool(row[key]) if key in {"allowed_order_write", "allowed_withdrawal"} else int(row[key]) if key.endswith("_id") else str(row[key])) for key in CredentialScopeBinding.__dataclass_fields__})

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

    def resolve(self, *, trading_account_id: int, venue: str, executor_identity: str, runtime_owner: str, cursor: Any | None = None) -> CredentialScopeBinding:
        if cursor is not None:
            return self._resolve(cursor, trading_account_id=trading_account_id, venue=venue, executor_identity=executor_identity, runtime_owner=runtime_owner)
        with self.cursor_factory() as db_obj:
            return self._resolve(_unwrap_cursor(db_obj), trading_account_id=trading_account_id, venue=venue, executor_identity=executor_identity, runtime_owner=runtime_owner)

    @staticmethod
    def _resolve(cursor: Any, *, trading_account_id: int, venue: str, executor_identity: str, runtime_owner: str) -> CredentialScopeBinding:
        cursor.execute(_SCOPE_SELECT, [trading_account_id, venue, executor_identity, runtime_owner, BINDING_STATUS_ACTIVE])
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND" if not rows else "CREDENTIAL_SCOPE_AMBIGUOUS")
        binding = _row_to_binding(rows[0])
        _assert_credential_identity_match(rows[0], binding=binding)
        if binding.permission_scope != TRADE_EXECUTION_SCOPE:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_TRADE_EXECUTION")
        if binding.credential_status != CREDENTIAL_STATUS_ACTIVE:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_CREDENTIAL_NOT_ACTIVE")
        if not binding.allowed_order_write:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_ORDER_WRITE_NOT_PERMITTED")
        if binding.allowed_withdrawal:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_WITHDRAWAL_CAPABLE_CREDENTIAL_DENIED")
        return binding
