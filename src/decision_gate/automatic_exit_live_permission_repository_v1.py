"""Issue #392 Phase 6 blocker B: DB-local reads for the decision-gate LIVE
automatic-exit permission fact and its immutable revocation lifecycle.

Loads persisted facts only; all resolution semantics (default-denied,
overlap-fails-closed, revocation handling, version validation) stay in
``automatic_exit_live_permission_contract_v1.py``. No broker, credential,
executor, or kill-switch import.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    AutomaticExitLiveDecisionGatePermissionRevocationV1,
    AutomaticExitLiveDecisionGatePermissionV1,
)


class AutomaticExitLivePermissionRepositoryError(RuntimeError):
    """Persisted LIVE permission or revocation data is unavailable or malformed."""


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
