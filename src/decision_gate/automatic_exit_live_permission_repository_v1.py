"""Issue #392 Phase 6 blocker B / Issue #588: DB-local reads and the single
canonical append-only write for the decision-gate LIVE automatic-exit
permission fact and its immutable revocation lifecycle.

Loads persisted facts only; all resolution semantics (default-denied,
overlap-fails-closed, revocation handling, version validation) stay in
``automatic_exit_live_permission_contract_v1.py``. The one write function in
this module (``insert_automatic_exit_live_decision_gate_permission_v1``)
performs a single append-only ``INSERT`` and nothing else -- it never
``UPDATE``s or ``DELETE``s a permission or revocation row (the DB triggers in
``db/migrations/20260818_automatic_exit_live_decision_gate_permission_v1.sql``
reject both unconditionally regardless of caller). All grant
eligibility/idempotency/conflict semantics live in
``automatic_exit_live_permission_grant_v1.py``, which is the only intended
caller of the write function; this module performs no validation of grant
semantics itself. No broker, credential, executor, or kill-switch import.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    AutomaticExitLiveDecisionGatePermissionRevocationV1,
    AutomaticExitLiveDecisionGatePermissionV1,
)


class AutomaticExitLivePermissionRepositoryError(RuntimeError):
    """Persisted LIVE permission or revocation data is unavailable or malformed."""


@dataclass(frozen=True)
class TradingAccountLiveReadinessV1:
    """Minimal account-identity/readiness facts needed to gate a LIVE grant.

    Read-only projection of ``trading_account``; carries no balance,
    position, order, or credential data.
    """

    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: bool
    live_trading_enabled: bool


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def load_automatic_exit_live_permission_history_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[AutomaticExitLiveDecisionGatePermissionV1, ...]:
    """Full LIVE-permission history for one account; resolution stays in the contract module."""
    if trading_account_id <= 0:
        raise AutomaticExitLivePermissionRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT automatic_exit_live_decision_gate_permission_id, trading_account_id,
           live_execution_permitted, effective_from_ts_utc, effective_until_ts_utc,
           permission_version, source_provenance
    FROM automatic_exit_live_decision_gate_permission_v1
    WHERE trading_account_id = %s
    ORDER BY effective_from_ts_utc, automatic_exit_live_decision_gate_permission_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(
        AutomaticExitLiveDecisionGatePermissionV1(
            permission_id=int(row["automatic_exit_live_decision_gate_permission_id"]),
            trading_account_id=int(row["trading_account_id"]),
            live_execution_permitted=bool(row["live_execution_permitted"]),
            effective_from_ts_utc=_ensure_aware(row["effective_from_ts_utc"]),
            effective_until_ts_utc=(
                _ensure_aware(row["effective_until_ts_utc"]) if row["effective_until_ts_utc"] is not None else None
            ),
            permission_version=str(row["permission_version"]),
            source_provenance=str(row["source_provenance"]),
        )
        for row in rows
    )


def load_trading_account_live_readiness_v1(
    conn: Any, *, trading_account_id: int, for_update: bool = False,
) -> TradingAccountLiveReadinessV1 | None:
    """Load the identity/readiness facts for one account, or ``None`` if unknown.

    ``for_update`` takes an exclusive row lock on the matched row for the
    lifetime of the caller's transaction, serializing concurrent grant calls
    for the same account (mirrors
    ``account_protection_policy_provisioning_v1._resolve_trading_account_id``).
    Never uses ``LIMIT 1``; a duplicate primary-key row is treated as
    malformed persisted data rather than silently picking one.
    """
    if trading_account_id <= 0:
        raise AutomaticExitLivePermissionRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled
    FROM trading_account
    WHERE trading_account_id = %s
    """
    if for_update:
        sql += " FOR UPDATE"
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    if len(rows) == 0:
        return None
    if len(rows) != 1:
        raise AutomaticExitLivePermissionRepositoryError("AMBIGUOUS_TRADING_ACCOUNT_IDENTITY")
    row = rows[0]
    return TradingAccountLiveReadinessV1(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=bool(row["enabled"]),
        live_trading_enabled=bool(row["live_trading_enabled"]),
    )


def insert_automatic_exit_live_decision_gate_permission_v1(
    conn: Any,
    *,
    trading_account_id: int,
    live_execution_permitted: bool,
    effective_from_ts_utc: datetime,
    effective_until_ts_utc: datetime | None,
    permission_version: str,
    source_provenance: str,
) -> int:
    """Append exactly one new LIVE permission fact and return its new id.

    This is a bare, single-row ``INSERT`` with no read-modify-write and no
    eligibility/idempotency/conflict checking of its own -- the caller
    (``automatic_exit_live_permission_grant_v1``) owns every such decision
    and must have already fully validated the candidate row before calling
    this function. Never issues ``UPDATE`` or ``DELETE`` against this table;
    the DB triggers reject both unconditionally as a second, independent
    enforcement layer.
    """
    if trading_account_id <= 0:
        raise AutomaticExitLivePermissionRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    INSERT INTO automatic_exit_live_decision_gate_permission_v1 (
        trading_account_id, live_execution_permitted, effective_from_ts_utc,
        effective_until_ts_utc, permission_version, source_provenance
    ) VALUES (%s, %s, %s, %s, %s, %s)
    """
    params = (
        trading_account_id, live_execution_permitted, effective_from_ts_utc,
        effective_until_ts_utc, permission_version, source_provenance,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.lastrowid)


def load_automatic_exit_live_permission_revocation_history_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[AutomaticExitLiveDecisionGatePermissionRevocationV1, ...]:
    """Every revocation/supersession fact recorded for one account.

    Multiple revocation facts per permission row are expected and valid; the
    resolver, not this function, decides which are authoritative at a given
    evaluation timestamp.
    """
    if trading_account_id <= 0:
        raise AutomaticExitLivePermissionRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT automatic_exit_live_decision_gate_permission_revocation_id,
           automatic_exit_live_decision_gate_permission_id, trading_account_id,
           revocation_version, effective_ts_utc, actor, reason
    FROM automatic_exit_live_decision_gate_permission_revocation_v1
    WHERE trading_account_id = %s
    ORDER BY effective_ts_utc, automatic_exit_live_decision_gate_permission_revocation_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(
        AutomaticExitLiveDecisionGatePermissionRevocationV1(
            revocation_id=int(row["automatic_exit_live_decision_gate_permission_revocation_id"]),
            permission_id=int(row["automatic_exit_live_decision_gate_permission_id"]),
            trading_account_id=int(row["trading_account_id"]),
            revocation_version=str(row["revocation_version"]),
            effective_ts_utc=_ensure_aware(row["effective_ts_utc"]),
            actor=str(row["actor"]),
            reason=str(row["reason"]),
        )
        for row in rows
    )
