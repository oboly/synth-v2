"""DB-local read boundary for the durable account-protection policy config
and its immutable revocation/supersession lifecycle facts.

No protection-policy semantics live here; resolution of which row is
effective (accounting for revocations) is owned by
``account_protection_policy_contract_v1.resolve_account_protection_policy_v1``.
No broker, executor, planner, or execution import.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.decision_gate.account_protection_policy_contract_v1 import (
    AccountProtectionPolicyConfigRevocationV1,
    AccountProtectionPolicyConfigRowV1,
)


class AccountProtectionPolicyRepositoryError(RuntimeError):
    """Persisted protection policy config or revocation data is unavailable or malformed."""


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _row_to_config(row: dict[str, Any]) -> AccountProtectionPolicyConfigRowV1:
    try:
        return AccountProtectionPolicyConfigRowV1(
            account_protection_policy_config_id=int(row["account_protection_policy_config_id"]),
            trading_account_id=int(row["trading_account_id"]),
            config_version=str(row["config_version"]),
            configuration_version=str(row["configuration_version"]),
            max_account_drawdown=(
                Decimal(str(row["max_account_drawdown"])) if row["max_account_drawdown"] is not None else None
            ),
            max_daily_realized_loss=(
                Decimal(str(row["max_daily_realized_loss"])) if row["max_daily_realized_loss"] is not None else None
            ),
            max_repeated_stoploss_streak=(
                int(row["max_repeated_stoploss_streak"]) if row["max_repeated_stoploss_streak"] is not None else None
            ),
            max_metric_age_seconds=int(row["max_metric_age_seconds"]),
            effective_from_ts_utc=_aware(row["effective_from_ts_utc"]),
            effective_until_ts_utc=(
                _aware(row["effective_until_ts_utc"]) if row["effective_until_ts_utc"] is not None else None
            ),
            source_provenance=str(row["source_provenance"]),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise AccountProtectionPolicyRepositoryError("INVALID_PERSISTED_PROTECTION_CONFIG_ROW") from exc


def _row_to_revocation(row: dict[str, Any]) -> AccountProtectionPolicyConfigRevocationV1:
    try:
        return AccountProtectionPolicyConfigRevocationV1(
            account_protection_policy_config_revocation_id=int(
                row["account_protection_policy_config_revocation_id"]
            ),
            account_protection_policy_config_id=int(row["account_protection_policy_config_id"]),
            trading_account_id=int(row["trading_account_id"]),
            revocation_version=str(row["revocation_version"]),
            effective_ts_utc=_aware(row["effective_ts_utc"]),
            actor=str(row["actor"]),
            reason=str(row["reason"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AccountProtectionPolicyRepositoryError("INVALID_PERSISTED_PROTECTION_CONFIG_REVOCATION_ROW") from exc


def load_account_protection_policy_config_rows_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[AccountProtectionPolicyConfigRowV1, ...]:
    """Read the complete immutable configuration history for exactly one account.

    Resolution of which row (if any) applies at a given timestamp, accounting
    for revocations, stays in ``resolve_account_protection_policy_v1``; this
    function loads raw rows only.
    """
    if trading_account_id <= 0:
        raise AccountProtectionPolicyRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT account_protection_policy_config_id, trading_account_id, config_version,
           configuration_version, max_account_drawdown, max_daily_realized_loss,
           max_repeated_stoploss_streak, max_metric_age_seconds,
           effective_from_ts_utc, effective_until_ts_utc, source_provenance
    FROM account_protection_policy_config_v1
    WHERE trading_account_id = %s
    ORDER BY effective_from_ts_utc, account_protection_policy_config_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_config(row) for row in rows)


def load_account_protection_policy_config_revocations_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[AccountProtectionPolicyConfigRevocationV1, ...]:
    """Read every revocation/supersession fact recorded for one account.

    Multiple revocation facts per config row are expected and valid; the
    resolver, not this function, decides which are authoritative at a given
    evaluation timestamp.
    """
    if trading_account_id <= 0:
        raise AccountProtectionPolicyRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT account_protection_policy_config_revocation_id, account_protection_policy_config_id,
           trading_account_id, revocation_version, effective_ts_utc, actor, reason
    FROM account_protection_policy_config_revocation_v1
    WHERE trading_account_id = %s
    ORDER BY effective_ts_utc, account_protection_policy_config_revocation_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_revocation(row) for row in rows)
