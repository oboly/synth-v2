"""Append-only persistence boundary for P2 account-protection facts.

No broker, executor, planner, or policy decision is imported here. Callers
append immutable lifecycle events and readers load account-scoped history for
the pure P2 evaluator or read-only reporting.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.decision_gate.account_protection_contract_v1 import (
    AccountProtectionContractError,
    ProtectionLockFactV1,
    validate_protection_lock_fact_v1,
)


class AccountProtectionRepositoryError(RuntimeError):
    """Persisted protection fact is unavailable or contradictory."""


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _row_to_fact(row: dict[str, Any]) -> ProtectionLockFactV1:
    try:
        refs = json.loads(str(row["evidence_refs_json"]))
        if not isinstance(refs, list) or not all(isinstance(value, str) for value in refs):
            raise ValueError
        fact = ProtectionLockFactV1(
            lifecycle_id=str(row["lifecycle_id"]),
            event_id=str(row["event_id"]),
            protection_code=str(row["protection_code"]),
            protection_version=str(row["protection_version"]),
            trading_account_id=int(row["trading_account_id"]),
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            observed_from_ts_utc=_aware(row["observed_from_ts_utc"]),
            observed_to_ts_utc=_aware(row["observed_to_ts_utc"]),
            triggered_ts_utc=_aware(row["triggered_ts_utc"]),
            expires_ts_utc=None if row["expires_ts_utc"] is None else _aware(row["expires_ts_utc"]),
            reason_code=str(row["reason_code"]),
            evidence_refs=tuple(refs),
            configuration_version=str(row["configuration_version"]),
            lock_state=str(row["lock_state"]),
        )
        validate_protection_lock_fact_v1(fact)
        return fact
    except (AccountProtectionContractError, KeyError, TypeError, ValueError) as exc:
        raise AccountProtectionRepositoryError("INVALID_PERSISTED_PROTECTION_FACT") from exc


def append_protection_lock_fact_v1(conn: Any, *, fact: ProtectionLockFactV1) -> None:
    """Append exactly one immutable event; duplicate event identity is rejected."""
    try:
        validate_protection_lock_fact_v1(fact)
    except AccountProtectionContractError as exc:
        raise AccountProtectionRepositoryError("INVALID_PROTECTION_LOCK_FACT") from exc
    sql = """
    INSERT INTO account_protection_lock_fact_v1 (
        lifecycle_id, event_id, protection_code, protection_version,
        trading_account_id, scope_type, scope_id, observed_from_ts_utc,
        observed_to_ts_utc, triggered_ts_utc, expires_ts_utc, reason_code,
        evidence_refs_json, configuration_version, lock_state
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                fact.lifecycle_id, fact.event_id, fact.protection_code, fact.protection_version,
                fact.trading_account_id, fact.scope_type, fact.scope_id,
                fact.observed_from_ts_utc, fact.observed_to_ts_utc, fact.triggered_ts_utc,
                fact.expires_ts_utc, fact.reason_code, json.dumps(fact.evidence_refs),
                fact.configuration_version, fact.lock_state,
            ))
    except Exception as exc:  # DB driver variants do not share a duplicate-key type.
        raise AccountProtectionRepositoryError("PROTECTION_LOCK_EVENT_APPEND_FAILED") from exc


def load_protection_lock_facts_for_account_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[ProtectionLockFactV1, ...]:
    """Read complete immutable history for exactly one account, deterministically."""
    if trading_account_id <= 0:
        raise AccountProtectionRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT lifecycle_id, event_id, protection_code, protection_version,
           trading_account_id, scope_type, scope_id, observed_from_ts_utc,
           observed_to_ts_utc, triggered_ts_utc, expires_ts_utc, reason_code,
           evidence_refs_json, configuration_version, lock_state
    FROM account_protection_lock_fact_v1
    WHERE trading_account_id = %s
    ORDER BY triggered_ts_utc, event_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_fact(row) for row in rows)
