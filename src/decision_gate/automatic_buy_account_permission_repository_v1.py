"""DB-local reads for general automatic-BUY decision-gate execution permission facts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.decision_gate.automatic_buy_account_permission_contract_v1 import (
    AutomaticBuyAccountPermissionRevocationV1,
    AutomaticBuyAccountPermissionV1,
)


class AutomaticBuyAccountPermissionRepositoryError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def load_automatic_buy_account_permission_history_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[AutomaticBuyAccountPermissionV1, ...]:
    if trading_account_id <= 0:
        raise AutomaticBuyAccountPermissionRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT automatic_buy_account_permission_id, trading_account_id,
           execution_enabled, effective_from_ts_utc, effective_until_ts_utc,
           permission_version, source_provenance
    FROM automatic_buy_account_permission_v1
    WHERE trading_account_id = %s
    ORDER BY effective_from_ts_utc, automatic_buy_account_permission_id
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (trading_account_id,))
            rows = [dict(row) for row in cur.fetchall()]
        return tuple(
            AutomaticBuyAccountPermissionV1(
                permission_id=int(row["automatic_buy_account_permission_id"]),
                trading_account_id=int(row["trading_account_id"]),
                execution_enabled=bool(row["execution_enabled"]),
                effective_from_ts_utc=_aware(row["effective_from_ts_utc"]),
                effective_until_ts_utc=(
                    _aware(row["effective_until_ts_utc"]) if row["effective_until_ts_utc"] is not None else None
                ),
                permission_version=str(row["permission_version"]),
                source_provenance=str(row["source_provenance"]),
            )
            for row in rows
        )
    except Exception as exc:
        raise AutomaticBuyAccountPermissionRepositoryError("AUTOMATIC_BUY_ACCOUNT_PERMISSION_READ_FAILED") from exc


def load_automatic_buy_account_permission_revocation_history_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[AutomaticBuyAccountPermissionRevocationV1, ...]:
    if trading_account_id <= 0:
        raise AutomaticBuyAccountPermissionRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT automatic_buy_account_permission_revocation_id,
           automatic_buy_account_permission_id, trading_account_id,
           revocation_version, effective_ts_utc, actor, reason
    FROM automatic_buy_account_permission_revocation_v1
    WHERE trading_account_id = %s
    ORDER BY effective_ts_utc, automatic_buy_account_permission_revocation_id
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (trading_account_id,))
            rows = [dict(row) for row in cur.fetchall()]
        return tuple(
            AutomaticBuyAccountPermissionRevocationV1(
                revocation_id=int(row["automatic_buy_account_permission_revocation_id"]),
                permission_id=int(row["automatic_buy_account_permission_id"]),
                trading_account_id=int(row["trading_account_id"]),
                revocation_version=str(row["revocation_version"]),
                effective_ts_utc=_aware(row["effective_ts_utc"]),
                actor=str(row["actor"]),
                reason=str(row["reason"]),
            )
            for row in rows
        )
    except Exception as exc:
        raise AutomaticBuyAccountPermissionRepositoryError(
            "AUTOMATIC_BUY_ACCOUNT_PERMISSION_REVOCATION_READ_FAILED"
        ) from exc
