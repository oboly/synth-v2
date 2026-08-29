"""Bind an existing ACTIVE TRADE_EXECUTION credential to one reviewed
executor identity/runtime-owner tuple, without re-entering or rotating
broker secrets.

This is the canonical path for adding a second (or later) executor binding
to a credential that was already provisioned by
`run_provision_trade_execution_credential_v1.py`. It never decrypts, prompts
for, or persists credential secret material, and it never mutates the
`trading_account_credential` row -- it only reads it to verify the exact
tuple-scoped identity, then appends/reuses one `executor_credential_binding`
row.

Only canonical, reviewed (executor_identity, runtime_owner) tuples from
`trade_execution_provisioning_v1.SUPPORTED_EXECUTOR_BINDING_TUPLES` are
accepted. An unreviewed pair fails closed.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Final

from src.account_provisioning.trade_execution_provisioning_v1 import (
    SUPPORTED_EXECUTOR_BINDING_TUPLES,
    TRADE_EXECUTION_SCOPE,
)

_CREDENTIAL_STATUS_ACTIVE: Final[str] = "ACTIVE"


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, dict) else row[index]


@dataclass(frozen=True)
class BindExistingCredentialResult:
    trading_account_credential_id: int
    executor_credential_binding_id: int
    executor_identity: str
    runtime_owner: str
    venue: str
    created_binding: bool


class BindExistingTradeExecutionCredentialRepository:
    """Non-secret metadata queries and inserts; caller owns the transaction.

    Reads only credential metadata columns -- no encrypted_envelope,
    key_version, or fingerprint -- so secret material never passes through
    this path.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _one(self, sql: str, params: tuple[Any, ...]) -> Any | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        if len(rows) > 1:
            raise ValueError("AMBIGUOUS_EXACT_IDENTITY")
        return rows[0] if rows else None

    def find_credential_by_id(self, *, trading_account_credential_id: int) -> Any | None:
        return self._one(
            "SELECT trading_account_credential_id, trading_account_id, venue, "
            "permission_scope, credential_status, allowed_order_write, allowed_withdrawal "
            "FROM trading_account_credential WHERE trading_account_credential_id = %s",
            (trading_account_credential_id,),
        )

    def require_account(self, *, trading_account_id: int, venue: str) -> None:
        row = self._one(
            "SELECT trading_account_id, venue FROM trading_account "
            "WHERE trading_account_id = %s AND venue = %s",
            (trading_account_id, venue),
        )
        if row is None:
            raise ValueError("TRADING_ACCOUNT_VENUE_NOT_FOUND")

    def find_active_binding(self, *, trading_account_id: int, venue: str,
                             executor_identity: str, runtime_owner: str) -> Any | None:
        """Look up the ACTIVE binding for one exact identity tuple only.

        Scoped by the full uniqueness grain (account, venue, permission
        scope, executor_identity, runtime_owner) so another executor's
        ACTIVE binding for the same account/venue is never observed here.
        """
        return self._one(
            "SELECT executor_credential_binding_id, trading_account_credential_id, "
            "executor_identity, runtime_owner FROM executor_credential_binding "
            "WHERE trading_account_id=%s AND venue=%s AND permission_scope='TRADE_EXECUTION' "
            "AND executor_identity=%s AND runtime_owner=%s AND binding_status='ACTIVE' "
            "ORDER BY executor_credential_binding_id LIMIT 2",
            (trading_account_id, venue, executor_identity, runtime_owner),
        )

    def insert_binding(self, *, credential_id: int, trading_account_id: int, venue: str,
                        executor_identity: str, runtime_owner: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO executor_credential_binding (trading_account_credential_id, "
                "trading_account_id, venue, permission_scope, executor_identity, runtime_owner, "
                "binding_status) VALUES (%s,%s,%s,'TRADE_EXECUTION',%s,%s,'ACTIVE')",
                (credential_id, trading_account_id, venue, executor_identity, runtime_owner),
            )
            return int(cur.lastrowid)


def bind_existing_trade_execution_credential(
    *,
    trading_account_id: int,
    trading_account_credential_id: int,
    executor_identity: str,
    runtime_owner: str,
    conn_factory: Callable[[], Any],
    repository_factory: Callable[[Any], Any] = BindExistingTradeExecutionCredentialRepository,
) -> BindExistingCredentialResult:
    """Append/reuse one executor binding for an existing TRADE_EXECUTION
    credential. Never creates, rotates, or mutates the credential row.

    Fails closed if the credential does not match the account, is not an
    ACTIVE TRADE_EXECUTION, non-withdrawal-capable credential, if the
    (executor_identity, runtime_owner) pair is not a reviewed tuple, or if
    an existing ACTIVE binding for the exact tuple already points at a
    different credential.
    """
    if (executor_identity, runtime_owner) not in SUPPORTED_EXECUTOR_BINDING_TUPLES:
        raise ValueError("UNSUPPORTED_EXECUTOR_BINDING_TUPLE")

    conn = conn_factory()
    try:
        repo = repository_factory(conn)
        credential = repo.find_credential_by_id(
            trading_account_credential_id=trading_account_credential_id
        )
        if credential is None:
            raise ValueError("TRADE_EXECUTION_CREDENTIAL_NOT_FOUND")

        credential_trading_account_id = int(_value(credential, "trading_account_id", 1))
        if credential_trading_account_id != trading_account_id:
            raise ValueError("CREDENTIAL_ACCOUNT_ID_MISMATCH")

        venue = str(_value(credential, "venue", 2))
        if str(_value(credential, "permission_scope", 3)) != TRADE_EXECUTION_SCOPE:
            raise ValueError("CREDENTIAL_PERMISSION_SCOPE_MISMATCH")
        if str(_value(credential, "credential_status", 4)) != _CREDENTIAL_STATUS_ACTIVE:
            raise ValueError("CREDENTIAL_NOT_ACTIVE")
        if not bool(_value(credential, "allowed_order_write", 5)):
            raise ValueError("CREDENTIAL_MISSING_ORDER_WRITE_SCOPE")
        if bool(_value(credential, "allowed_withdrawal", 6)):
            raise ValueError("CREDENTIAL_WITHDRAWAL_CAPABILITY_NOT_ALLOWED")

        # Cross-validate venue against the trading_account row itself, not
        # only against the credential's own venue column.
        repo.require_account(trading_account_id=trading_account_id, venue=venue)

        binding = repo.find_active_binding(
            trading_account_id=trading_account_id, venue=venue,
            executor_identity=executor_identity, runtime_owner=runtime_owner,
        )
        created_binding = False
        if binding is None:
            binding_id = repo.insert_binding(
                credential_id=trading_account_credential_id, trading_account_id=trading_account_id,
                venue=venue, executor_identity=executor_identity, runtime_owner=runtime_owner,
            )
            created_binding = True
        else:
            binding_id = int(_value(binding, "executor_credential_binding_id", 0))
            if not (int(_value(binding, "trading_account_credential_id", 1)) == trading_account_credential_id
                    and _value(binding, "executor_identity", 2) == executor_identity
                    and _value(binding, "runtime_owner", 3) == runtime_owner):
                raise ValueError("ACTIVE_EXECUTOR_CREDENTIAL_BINDING_CONFLICT")

        conn.commit()
        return BindExistingCredentialResult(
            trading_account_credential_id=trading_account_credential_id,
            executor_credential_binding_id=binding_id,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
            venue=venue,
            created_binding=created_binding,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
