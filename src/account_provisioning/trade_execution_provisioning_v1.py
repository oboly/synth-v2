"""Operator-only provisioning of the non-live manual execution credential.

This module has no broker-client imports and does not decrypt credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Final

from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import compute_fingerprint, encrypt_credential
from src.account_provisioning.credential_repository_v1 import CREDENTIAL_KIND_API_KEY_SECRET
from src.executor.manual_execution_identity_v1 import (
    MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
    MANUAL_EXECUTION_RUNTIME_OWNER,
)

TRADE_EXECUTION_SCOPE: Final[str] = "TRADE_EXECUTION"
BITVAVO_VENUE: Final[str] = "bitvavo"


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, dict) else row[index]


@dataclass(frozen=True)
class TradeExecutionProvisioningResult:
    trading_account_credential_id: int
    executor_credential_binding_id: int
    created_credential: bool
    created_binding: bool


class TradeExecutionProvisioningRepository:
    """Non-secret metadata queries and inserts; caller owns the transaction."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _one(self, sql: str, params: tuple[Any, ...]) -> Any | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        if len(rows) > 1:
            raise ValueError("AMBIGUOUS_EXACT_IDENTITY")
        return rows[0] if rows else None

    @staticmethod
    def _value(row: Any, key: str, index: int) -> Any:
        return row[key] if isinstance(row, dict) else row[index]

    def require_account(self, *, trading_account_id: int, venue: str) -> None:
        row = self._one(
            "SELECT trading_account_id, venue FROM trading_account "
            "WHERE trading_account_id = %s AND venue = %s",
            (trading_account_id, venue),
        )
        if row is None:
            raise ValueError("TRADING_ACCOUNT_VENUE_NOT_FOUND")

    def find_active_credential(self, *, trading_account_id: int, venue: str) -> Any | None:
        return self._one(
            "SELECT trading_account_credential_id, credential_status, permission_scope, "
            "allowed_order_write, allowed_withdrawal, credential_fingerprint FROM trading_account_credential "
            "WHERE trading_account_id = %s AND venue = %s AND permission_scope = %s "
            "AND credential_status = 'ACTIVE' ORDER BY trading_account_credential_id LIMIT 2",
            (trading_account_id, venue, TRADE_EXECUTION_SCOPE),
        )

    def insert_credential(self, *, trading_account_id: int, venue: str, encrypted_envelope: str,
                          encryption_algorithm: str, key_version: str, credential_fingerprint: str,
                          now_utc: datetime) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trading_account_credential (trading_account_id, venue, credential_kind, "
                "encrypted_envelope, encryption_algorithm, key_version, credential_fingerprint, credential_status, "
                "validation_state, credential_source, permission_scope, allowed_private_read, allowed_order_write, "
                "allowed_withdrawal, created_ts_utc) VALUES (%s,%s,%s,%s,%s,%s,%s,'ACTIVE','UNVALIDATED',"
                "'db_encrypted','TRADE_EXECUTION',1,1,0,%s)",
                (trading_account_id, venue, CREDENTIAL_KIND_API_KEY_SECRET, encrypted_envelope,
                 encryption_algorithm, key_version, credential_fingerprint,
                 now_utc.astimezone(UTC).replace(tzinfo=None)),
            )
            return int(cur.lastrowid)

    def find_active_binding(self, *, trading_account_id: int, venue: str) -> Any | None:
        return self._one(
            "SELECT executor_credential_binding_id, trading_account_credential_id, executor_identity, runtime_owner "
            "FROM executor_credential_binding WHERE trading_account_id=%s AND venue=%s "
            "AND permission_scope='TRADE_EXECUTION' AND binding_status='ACTIVE' "
            "ORDER BY executor_credential_binding_id LIMIT 2",
            (trading_account_id, venue),
        )

    def insert_binding(self, *, credential_id: int, trading_account_id: int, venue: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO executor_credential_binding (trading_account_credential_id, trading_account_id, venue, "
                "permission_scope, executor_identity, runtime_owner, binding_status) VALUES (%s,%s,%s,'TRADE_EXECUTION',%s,%s,'ACTIVE')",
                (credential_id, trading_account_id, venue, MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
                 MANUAL_EXECUTION_RUNTIME_OWNER),
            )
            return int(cur.lastrowid)


def provision_trade_execution_credential(*, trading_account_id: int, venue: str, api_key: str,
                                         api_secret: str, master_key_version: str, master_key_bytes: bytes,
                                         conn_factory: Callable[[], Any], repository_factory=TradeExecutionProvisioningRepository,
                                         now_utc: datetime | None = None) -> TradeExecutionProvisioningResult:
    if venue != BITVAVO_VENUE:
        raise ValueError("UNSUPPORTED_TRADE_EXECUTION_VENUE")
    credential = PlainBitvavoCredential(venue=venue, api_key=api_key, api_secret=api_secret)
    conn = conn_factory()
    try:
        repo = repository_factory(conn)
        repo.require_account(trading_account_id=trading_account_id, venue=venue)
        existing = repo.find_active_credential(trading_account_id=trading_account_id, venue=venue)
        fingerprint = compute_fingerprint(venue, api_key, master_key_bytes)
        created = False
        if existing is None:
            envelope = encrypt_credential(credential, trading_account_id, master_key_version, master_key_bytes)
            credential_id = repo.insert_credential(
                trading_account_id=trading_account_id, venue=venue, encrypted_envelope=envelope.to_json(),
                encryption_algorithm=envelope.alg, key_version=envelope.kv,
                credential_fingerprint=fingerprint,
                now_utc=now_utc or datetime.now(UTC),
            )
            created = True
        else:
            credential_id = int(_value(existing, "trading_account_credential_id", 0))
            if not (_value(existing, "credential_status", 1) == "ACTIVE"
                    and _value(existing, "permission_scope", 2) == TRADE_EXECUTION_SCOPE
                    and bool(_value(existing, "allowed_order_write", 3))
                    and not bool(_value(existing, "allowed_withdrawal", 4))
                    and _value(existing, "credential_fingerprint", 5) == fingerprint):
                raise ValueError("ACTIVE_TRADE_EXECUTION_CREDENTIAL_CONFLICT")
        binding = repo.find_active_binding(trading_account_id=trading_account_id, venue=venue)
        created_binding = False
        if binding is None:
            binding_id = repo.insert_binding(credential_id=credential_id, trading_account_id=trading_account_id, venue=venue)
            created_binding = True
        else:
            binding_id = int(_value(binding, "executor_credential_binding_id", 0))
            if not (int(_value(binding, "trading_account_credential_id", 1)) == credential_id
                    and _value(binding, "executor_identity", 2) == MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY
                    and _value(binding, "runtime_owner", 3) == MANUAL_EXECUTION_RUNTIME_OWNER):
                raise ValueError("ACTIVE_EXECUTOR_CREDENTIAL_BINDING_CONFLICT")
        conn.commit()
        return TradeExecutionProvisioningResult(credential_id, binding_id, created, created_binding)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def readiness_report(*, trading_account_id: int, venue: str, conn_factory: Callable[[], Any],
                     repository_factory=TradeExecutionProvisioningRepository) -> dict[str, object]:
    conn = conn_factory()
    try:
        repo = repository_factory(conn)
        repo.require_account(trading_account_id=trading_account_id, venue=venue)
        credential = repo.find_active_credential(trading_account_id=trading_account_id, venue=venue)
        credential_id = None if credential is None else int(_value(credential, "trading_account_credential_id", 0))
        credential_ready = credential is not None and bool(_value(credential, "allowed_order_write", 3)) and not bool(_value(credential, "allowed_withdrawal", 4))
        binding = repo.find_active_binding(trading_account_id=trading_account_id, venue=venue)
        binding_ready = binding is not None and credential_id is not None and int(_value(binding, "trading_account_credential_id", 1)) == credential_id and _value(binding, "executor_identity", 2) == MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY and _value(binding, "runtime_owner", 3) == MANUAL_EXECUTION_RUNTIME_OWNER
        return {"TRADE_EXECUTION_CREDENTIAL_READY": credential_ready, "TRADE_EXECUTION_CREDENTIAL_ID": credential_id,
                "EXECUTOR_IDENTITY": MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, "RUNTIME_OWNER": MANUAL_EXECUTION_RUNTIME_OWNER,
                "EXECUTOR_CREDENTIAL_BINDING_READY": binding_ready,
                "EXECUTOR_CREDENTIAL_BINDING_ID": None if binding is None else int(_value(binding, "executor_credential_binding_id", 0))}
    finally:
        conn.close()
