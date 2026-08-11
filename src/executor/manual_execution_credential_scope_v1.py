"""
manual_execution_credential_scope_v1 — deny-by-default TRADE_EXECUTION
credential scope resolution for the executor handoff boundary (Issue #206).

Layer: executor-only. Resolves the non-secret binding row from
executor_credential_binding (db/migrations/20260812_manual_execution_executor_handoff_v1.sql)
that permits one explicit executor identity + runtime owner to use one
explicit trading_account_credential for TRADE_EXECUTION on one
trading_account_id + venue — see
docs/architecture/account_credential_binding_contract_v1.md.

This module never selects, decrypts, logs, or returns secret credential
material (encrypted_envelope, key_version, credential_fingerprint are never
selected here). It resolves identity/permission metadata only, and fails
closed on any missing, ambiguous, revoked, or scope-mismatched binding.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Final


TRADE_EXECUTION_SCOPE: Final[str] = "TRADE_EXECUTION"

CREDENTIAL_STATUS_ACTIVE: Final[str] = "ACTIVE"
BINDING_STATUS_ACTIVE: Final[str] = "ACTIVE"


class CredentialScopeDeniedError(PermissionError):
    """Deny-by-default: no valid TRADE_EXECUTION binding was resolved."""


@dataclass(frozen=True)
class CredentialScopeBinding:
    """Non-secret credential scope identity. Carries no key material."""

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


_SCOPE_SELECT: Final[str] = """
    SELECT
        binding.executor_credential_binding_id,
        binding.trading_account_credential_id,
        binding.trading_account_id,
        binding.venue,
        binding.permission_scope,
        binding.executor_identity,
        binding.runtime_owner,
        credential.credential_status,
        credential.credential_source,
        credential.allowed_order_write,
        credential.allowed_withdrawal
    FROM executor_credential_binding AS binding
    INNER JOIN trading_account_credential AS credential
        ON credential.trading_account_credential_id = binding.trading_account_credential_id
    WHERE binding.trading_account_id = %s
      AND binding.venue = %s
      AND binding.executor_identity = %s
      AND binding.runtime_owner = %s
      AND binding.binding_status = %s
"""


def _row_to_binding(row: Any) -> CredentialScopeBinding:
    return CredentialScopeBinding(
        executor_credential_binding_id=int(row["executor_credential_binding_id"]),
        trading_account_credential_id=int(row["trading_account_credential_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        permission_scope=str(row["permission_scope"]),
        executor_identity=str(row["executor_identity"]),
        runtime_owner=str(row["runtime_owner"]),
        credential_status=str(row["credential_status"]),
        credential_source=str(row["credential_source"]),
        allowed_order_write=bool(row["allowed_order_write"]),
        allowed_withdrawal=bool(row["allowed_withdrawal"]),
    )


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
        """Deny-by-default resolution. Raises CredentialScopeDeniedError on
        any missing, ambiguous, revoked, or scope-mismatched binding. Never
        returns secret credential material."""
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
            [trading_account_id, venue, executor_identity, runtime_owner, BINDING_STATUS_ACTIVE],
        )
        rows = cursor.fetchall()
        if not rows:
            raise CredentialScopeDeniedError(
                "CREDENTIAL_SCOPE_NOT_BOUND: no ACTIVE executor_credential_binding for "
                f"trading_account_id={trading_account_id} venue={venue} "
                f"executor_identity={executor_identity} runtime_owner={runtime_owner}"
            )
        if len(rows) > 1:
            raise CredentialScopeDeniedError(
                "CREDENTIAL_SCOPE_AMBIGUOUS: more than one ACTIVE executor_credential_binding "
                f"for trading_account_id={trading_account_id} venue={venue} "
                f"executor_identity={executor_identity} runtime_owner={runtime_owner}"
            )
        binding = _row_to_binding(rows[0])
        if binding.permission_scope != TRADE_EXECUTION_SCOPE:
            raise CredentialScopeDeniedError(
                f"CREDENTIAL_SCOPE_NOT_TRADE_EXECUTION: permission_scope={binding.permission_scope}"
            )
        if binding.credential_status != CREDENTIAL_STATUS_ACTIVE:
            raise CredentialScopeDeniedError(
                f"CREDENTIAL_SCOPE_CREDENTIAL_NOT_ACTIVE: credential_status={binding.credential_status}"
            )
        if binding.allowed_withdrawal:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_WITHDRAWAL_CAPABLE_CREDENTIAL_DENIED")
        return binding
