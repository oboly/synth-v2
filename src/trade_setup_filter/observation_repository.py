from __future__ import annotations

"""
Synth v2 - Trade Setup Filter V1 observation repository.

LAYER:
paper/research observation logging for market-only setup filter

BOUNDARY:
Allowed:
- persist market-only filter observations
- persist filter context and reason codes

Forbidden:
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


def ensure_observation_table() -> None:
    sql = f"""
    CREATE TABLE IF NOT EXISTS {OPERATIONAL_DB}.{TABLE_NAME} (
        trade_setup_filter_observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        asset_id INT NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        venue VARCHAR(32) NOT NULL,
        asof_ts_utc DATETIME(6) NOT NULL,
        context_ts_utc DATETIME(6) DEFAULT NULL,

        filter_name VARCHAR(64) NOT NULL,
        filter_version VARCHAR(32) NOT NULL,
        asset_suitability_mode VARCHAR(64) NOT NULL,

        selection_state VARCHAR(32) NOT NULL,
        selection_bias VARCHAR(32) DEFAULT NULL,
        selection_score DECIMAL(18,8) DEFAULT NULL,
        priority_rank INT DEFAULT NULL,

        btc_prior_24h DECIMAL(18,8) DEFAULT NULL,

        setup_filter_state VARCHAR(32) NOT NULL,
        setup_filter_reason VARCHAR(128) NOT NULL,
        target_horizon VARCHAR(32) NOT NULL,
        notes VARCHAR(512) DEFAULT NULL,

        created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),

        PRIMARY KEY (trade_setup_filter_observation_id),
        UNIQUE KEY uq_trade_setup_filter_observation (
            asset_id,
            venue,
            asof_ts_utc,
            filter_name,
            filter_version,
            asset_suitability_mode
        ),
        KEY ix_trade_setup_filter_state (
            setup_filter_state,
            setup_filter_reason
        ),
        KEY ix_trade_setup_filter_ts (
            asof_ts_utc
        ),
        KEY ix_trade_setup_filter_symbol_ts (
            symbol,
            asof_ts_utc
        )
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
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

    ensure_observation_table()

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
    finally:
        conn.close()
