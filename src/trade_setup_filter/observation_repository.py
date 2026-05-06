from __future__ import annotations

"""
Synth v2 - Trade Setup Filter V1 observation repository.

LAYER:
paper/research observation logging for market-only setup filter

BOUNDARY:
Allowed:
- persist market-only filter observations
- persist filter context and reason codes
- verify required observation table exists

Forbidden:
- runtime DDL/schema creation
- account state
- balances
- positions
- open orders
- execution plans
- broker/order actions
"""

from dataclasses import asdict
from typing import Any

from src.common.db import get_connection
from src.trade_setup_filter.models import TradeSetupDecision


OPERATIONAL_DB = "synth"
TABLE_NAME = "trade_setup_filter_observation"


def assert_observation_table_exists() -> None:
    sql = """
    SELECT COUNT(*) AS table_count
    FROM information_schema.tables
    WHERE table_schema = %s
      AND table_name = %s
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [OPERATIONAL_DB, TABLE_NAME])
            row = cur.fetchone()

        table_count = int(row["table_count"]) if row else 0
        if table_count != 1:
            raise RuntimeError(
                f"Required table {OPERATIONAL_DB}.{TABLE_NAME} is missing. "
                "Apply db/migrations/20260507_trade_setup_filter_observation_v1.sql manually first."
            )
    finally:
        conn.close()


def _serialize_decision(
    decision: TradeSetupDecision,
    *,
    filter_name: str,
    filter_version: str,
    asset_suitability_mode: str,
) -> dict[str, Any]:
    row = asdict(decision)
    row["filter_name"] = filter_name
    row["filter_version"] = filter_version
    row["asset_suitability_mode"] = asset_suitability_mode
    return row


def write_observations(
    decisions: list[TradeSetupDecision],
    *,
    filter_name: str,
    filter_version: str,
    asset_suitability_mode: str,
) -> int:
    if not decisions:
        return 0

    assert_observation_table_exists()

    rows = [
        _serialize_decision(
            decision,
            filter_name=filter_name,
            filter_version=filter_version,
            asset_suitability_mode=asset_suitability_mode,
        )
        for decision in decisions
    ]

    sql = f"""
    INSERT INTO {OPERATIONAL_DB}.{TABLE_NAME} (
        asset_id,
        symbol,
        venue,
        asof_ts_utc,
        context_ts_utc,
        filter_name,
        filter_version,
        asset_suitability_mode,
        selection_state,
        selection_bias,
        selection_score,
        priority_rank,
        btc_prior_24h,
        setup_filter_state,
        setup_filter_reason,
        target_horizon,
        notes
    ) VALUES (
        %(asset_id)s,
        %(symbol)s,
        %(venue)s,
        %(asof_ts_utc)s,
        %(context_ts_utc)s,
        %(filter_name)s,
        %(filter_version)s,
        %(asset_suitability_mode)s,
        %(selection_state)s,
        %(selection_bias)s,
        %(selection_score)s,
        %(priority_rank)s,
        %(btc_prior_24h)s,
        %(setup_filter_state)s,
        %(setup_filter_reason)s,
        %(target_horizon)s,
        %(notes)s
    )
    ON DUPLICATE KEY UPDATE
        context_ts_utc = VALUES(context_ts_utc),
        selection_state = VALUES(selection_state),
        selection_bias = VALUES(selection_bias),
        selection_score = VALUES(selection_score),
        priority_rank = VALUES(priority_rank),
        btc_prior_24h = VALUES(btc_prior_24h),
        setup_filter_state = VALUES(setup_filter_state),
        setup_filter_reason = VALUES(setup_filter_reason),
        target_horizon = VALUES(target_horizon),
        notes = VALUES(notes)
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
