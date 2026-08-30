"""Bind an existing validated TRADE_EXECUTION credential to one reviewed executor tuple.

This path never decrypts, prompts for, or persists credential secret material and never
mutates the trading_account_credential row. Read-only checks and explicit apply share
the same fail-closed eligibility validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Final

from src.account_provisioning.credential_binding_contract_v1 import (
    CREDENTIAL_SOURCE_DB_ENCRYPTED,
    VALIDATED_TRADE_EXECUTION_STATES,
)
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
    binding_exists: bool
    created_binding: bool


class BindExistingTradeExecutionCredentialRepository:
    """Non-secret metadata queries and binding insert; caller owns transaction."""

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
            "permission_scope, credential_status, allowed_order_write, allowed_withdrawal, "
            "credential_source, validation_state, validated_ts_utc, allowed_private_read "
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

    def find_active_binding(
        self,
        *,
        trading_account_id: int,
        venue: str,
        executor_identity: str,
        runtime_owner: str,
    ) -> Any | None:
        return self._one(
            "SELECT executor_credential_binding_id, trading_account_credential_id, "
            "executor_identity, runtime_owner FROM executor_credential_binding "
            "WHERE trading_account_id=%s AND venue=%s AND permission_scope='TRADE_EXECUTION' "
            "AND executor_identity=%s AND runtime_owner=%s AND binding_status='ACTIVE' "
            "ORDER BY executor_credential_binding_id LIMIT 2",
            (trading_account_id, venue, executor_identity, runtime_owner),
        )

    def insert_binding(
        self,
        *,
        credential_id: int,
        trading_account_id: int,
        venue: str,
        executor_identity: str,
        runtime_owner: str,
    ) -> int:
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
    apply: bool = False,
) -> BindExistingCredentialResult:
    """Check or append/reuse one executor binding for an existing credential.

    ``apply=False`` is strictly read-only and is the safe default: it validates
    eligibility and existing binding state, rolls the transaction back, and never
    calls ``insert_binding``. Mutation requires explicit ``apply=True``.
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

        if int(_value(credential, "trading_account_id", 1)) != trading_account_id:
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
        if str(_value(credential, "credential_source", 7)) != CREDENTIAL_SOURCE_DB_ENCRYPTED:
            raise ValueError("CREDENTIAL_SOURCE_MISMATCH")
        if str(_value(credential, "validation_state", 8)) not in VALIDATED_TRADE_EXECUTION_STATES:
            raise ValueError("CREDENTIAL_NOT_VALID_TRADE_EXECUTION")
        if _value(credential, "validated_ts_utc", 9) is None:
            raise ValueError("CREDENTIAL_VALIDATION_TIMESTAMP_MISSING")
        if not bool(_value(credential, "allowed_private_read", 10)):
            raise ValueError("CREDENTIAL_MISSING_PRIVATE_READ_SCOPE")

        repo.require_account(trading_account_id=trading_account_id, venue=venue)

        binding = repo.find_active_binding(
            trading_account_id=trading_account_id,
            venue=venue,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
        )
        binding_exists = binding is not None
        created_binding = False

        if binding is None:
            if apply:
                binding_id = repo.insert_binding(
                    credential_id=trading_account_credential_id,
                    trading_account_id=trading_account_id,
                    venue=venue,
                    executor_identity=executor_identity,
                    runtime_owner=runtime_owner,
                )
                binding_exists = True
                created_binding = True
            else:
                binding_id = 0
        else:
            binding_id = int(_value(binding, "executor_credential_binding_id", 0))
            if not (
                int(_value(binding, "trading_account_credential_id", 1))
                == trading_account_credential_id
                and _value(binding, "executor_identity", 2) == executor_identity
                and _value(binding, "runtime_owner", 3) == runtime_owner
            ):
                raise ValueError("ACTIVE_EXECUTOR_CREDENTIAL_BINDING_CONFLICT")

        if apply:
            conn.commit()
        else:
            conn.rollback()

        return BindExistingCredentialResult(
            trading_account_credential_id=trading_account_credential_id,
            executor_credential_binding_id=binding_id,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
            venue=venue,
            binding_exists=binding_exists,
            created_binding=created_binding,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
