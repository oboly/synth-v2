"""DB-local read boundary for the durable strategy-bucket account
configuration and its immutable revocation/supersession lifecycle facts.

No strategy-bucket participation semantics live here; resolution of which
row is effective (accounting for revocations) is owned by
``strategy_bucket_account_config_contract_v1.resolve_strategy_bucket_account_config_v1``.
No broker, executor, planner, or execution import.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    StrategyBucketAccountConfigRevocationV1,
    StrategyBucketAccountConfigRowV1,
)


class StrategyBucketAccountConfigRepositoryError(RuntimeError):
    """Persisted strategy-bucket account config or revocation data is unavailable or malformed."""


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _row_to_config(row: dict[str, Any]) -> StrategyBucketAccountConfigRowV1:
    try:
        return StrategyBucketAccountConfigRowV1(
            strategy_bucket_account_config_id=int(row["strategy_bucket_account_config_id"]),
            trading_account_id=int(row["trading_account_id"]),
            strategy_bucket_id=str(row["strategy_bucket_id"]),
            config_version=str(row["config_version"]),
            is_enabled=bool(row["is_enabled"]),
            risk_profile=str(row["risk_profile"]),
            max_position_amount_eur=(
                Decimal(str(row["max_position_amount_eur"])) if row["max_position_amount_eur"] is not None else None
            ),
            max_bucket_amount_eur=(
                Decimal(str(row["max_bucket_amount_eur"])) if row["max_bucket_amount_eur"] is not None else None
            ),
            max_asset_exposure_pct=(
                Decimal(str(row["max_asset_exposure_pct"])) if row["max_asset_exposure_pct"] is not None else None
            ),
            max_open_positions=(
                int(row["max_open_positions"]) if row["max_open_positions"] is not None else None
            ),
            allow_new_entries=bool(row["allow_new_entries"]),
            allow_reduce_reviews=bool(row["allow_reduce_reviews"]),
            effective_from_ts_utc=_aware(row["effective_from_ts_utc"]),
            effective_until_ts_utc=(
                _aware(row["effective_until_ts_utc"]) if row["effective_until_ts_utc"] is not None else None
            ),
            source_provenance=str(row["source_provenance"]),
            # Issue #752: added columns; a pre-#752 SELECT result (or a row
            # dict missing the key entirely) resolves to NULL/None, which is
            # the documented backward-compatible "no percentage policy"
            # value -- never inferred, never a stand-in default ceiling.
            allocation_target_pct=(
                Decimal(str(row["allocation_target_pct"]))
                if row.get("allocation_target_pct") is not None
                else None
            ),
            allocation_max_pct=(
                Decimal(str(row["allocation_max_pct"])) if row.get("allocation_max_pct") is not None else None
            ),
            max_position_pct_of_bucket=(
                Decimal(str(row["max_position_pct_of_bucket"]))
                if row.get("max_position_pct_of_bucket") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise StrategyBucketAccountConfigRepositoryError("INVALID_PERSISTED_STRATEGY_BUCKET_CONFIG_ROW") from exc


def _row_to_revocation(row: dict[str, Any]) -> StrategyBucketAccountConfigRevocationV1:
    try:
        return StrategyBucketAccountConfigRevocationV1(
            strategy_bucket_account_config_revocation_id=int(
                row["strategy_bucket_account_config_revocation_id"]
            ),
            strategy_bucket_account_config_id=int(row["strategy_bucket_account_config_id"]),
            trading_account_id=int(row["trading_account_id"]),
            revocation_version=str(row["revocation_version"]),
            effective_ts_utc=_aware(row["effective_ts_utc"]),
            actor=str(row["actor"]),
            reason=str(row["reason"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StrategyBucketAccountConfigRepositoryError("INVALID_PERSISTED_STRATEGY_BUCKET_CONFIG_REVOCATION_ROW") from exc


def load_strategy_bucket_account_config_rows_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[StrategyBucketAccountConfigRowV1, ...]:
    """Read the complete immutable configuration history for exactly one account.

    Loads every strategy bucket configured for this account; resolution of
    which row (if any) applies to a given ``strategy_bucket_id`` at a given
    timestamp, accounting for revocations, stays in
    ``resolve_strategy_bucket_account_config_v1``. This function loads raw
    rows only.
    """
    if trading_account_id <= 0:
        raise StrategyBucketAccountConfigRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT strategy_bucket_account_config_id, trading_account_id, strategy_bucket_id,
           config_version, is_enabled, risk_profile, max_position_amount_eur,
           max_bucket_amount_eur, max_asset_exposure_pct, max_open_positions,
           allow_new_entries, allow_reduce_reviews,
           effective_from_ts_utc, effective_until_ts_utc, source_provenance,
           allocation_target_pct, allocation_max_pct, max_position_pct_of_bucket
    FROM strategy_bucket_account_config_v1
    WHERE trading_account_id = %s
    ORDER BY effective_from_ts_utc, strategy_bucket_account_config_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_config(row) for row in rows)


def load_strategy_bucket_account_config_revocations_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[StrategyBucketAccountConfigRevocationV1, ...]:
    """Read every revocation/supersession fact recorded for one account.

    Multiple revocation facts per config row are expected and valid; the
    resolver, not this function, decides which are authoritative at a given
    evaluation timestamp.
    """
    if trading_account_id <= 0:
        raise StrategyBucketAccountConfigRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT strategy_bucket_account_config_revocation_id, strategy_bucket_account_config_id,
           trading_account_id, revocation_version, effective_ts_utc, actor, reason
    FROM strategy_bucket_account_config_revocation_v1
    WHERE trading_account_id = %s
    ORDER BY effective_ts_utc, strategy_bucket_account_config_revocation_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_revocation(row) for row in rows)
