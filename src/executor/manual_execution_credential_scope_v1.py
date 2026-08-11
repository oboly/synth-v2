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

Credential identity match: the referenced trading_account_credential row
must itself agree with the binding on trading_account_id, venue, and
permission_scope. A binding pointing at a credential for a different
account/venue/scope must never resolve — this is enforced twice: primarily
in the SELECT/JOIN predicate below (so a mismatched row is never even
fetched), and again as Python defense-in-depth on the fetched row. The DB
schema additionally enforces this with a composite foreign key from
executor_credential_binding to trading_account_credential covering
(trading_account_credential_id, trading_account_id, venue, permission_scope)
— see db/migrations/20260812_manual_execution_executor_handoff_v1.sql.

Order-write authority: a TRADE_EXECUTION-scoped credential is not
sufficient on its own — trading_account_credential.allowed_order_write must
also be 1. The existing capability CHECK constraint
(chk_tac_capability_flags_v1) only forbids order-write under
READ_ONLY_PRIVATE; it does not require order-write under TRADE_EXECUTION,
so this module enforces it explicitly.

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
        credential.trading_account_id AS credential_trading_account_id,
        credential.venue AS credential_venue,
        credential.permission_scope AS credential_permission_scope,
        credential.credential_status,
        credential.credential_source,
        credential.allowed_order_write,
        credential.allowed_withdrawal
    FROM executor_credential_binding AS binding
    INNER JOIN trading_account_credential AS credential
        ON credential.trading_account_credential_id = binding.trading_account_credential_id
        AND credential.trading_account_id = binding.trading_account_id
        AND credential.venue = binding.venue
        AND credential.permission_scope = binding.permission_scope
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


def _assert_credential_identity_match(row: Any, *, binding: CredentialScopeBinding) -> None:
    """Defense-in-depth: the SELECT/JOIN predicate is the primary control,
    but a fetched row must still agree with the credential's own identity
    columns before it is trusted."""
    credential_trading_account_id = int(row["credential_trading_account_id"])
    credential_venue = str(row["credential_venue"])
    credential_permission_scope = str(row["credential_permission_scope"])
    if credential_trading_account_id != binding.trading_account_id:
        raise CredentialScopeDeniedError(
            "CREDENTIAL_SCOPE_ACCOUNT_MISMATCH: binding trading_account_id="
            f"{binding.trading_account_id} credential trading_account_id={credential_trading_account_id}"
        )
    if credential_venue != binding.venue:
        raise CredentialScopeDeniedError(
            f"CREDENTIAL_SCOPE_VENUE_MISMATCH: binding venue={binding.venue} credential venue={credential_venue}"
        )
    if credential_permission_scope != binding.permission_scope:
        raise CredentialScopeDeniedError(
            "CREDENTIAL_SCOPE_PERMISSION_SCOPE_MISMATCH: binding permission_scope="
            f"{binding.permission_scope} credential permission_scope={credential_permission_scope}"
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
        row = rows[0]
        binding = _row_to_binding(row)
        _assert_credential_identity_match(row, binding=binding)
        if binding.permission_scope != TRADE_EXECUTION_SCOPE:
            raise CredentialScopeDeniedError(
                f"CREDENTIAL_SCOPE_NOT_TRADE_EXECUTION: permission_scope={binding.permission_scope}"
            )
        if binding.credential_status != CREDENTIAL_STATUS_ACTIVE:
            raise CredentialScopeDeniedError(
                f"CREDENTIAL_SCOPE_CREDENTIAL_NOT_ACTIVE: credential_status={binding.credential_status}"
            )
        if not binding.allowed_order_write:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_ORDER_WRITE_NOT_PERMITTED")
        if binding.allowed_withdrawal:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_WITHDRAWAL_CAPABLE_CREDENTIAL_DENIED")
        return binding
