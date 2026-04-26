from __future__ import annotations

"""
Synth v2 - Trade Setup Filter V1 repository.

LAYER:
market-only setup/context filter

BOUNDARY:
Read-only repository for latest selection_state + BTC context.
No writes.
No account state.
No execution state.

IMPORTANT:
BTC context must be snapshot-global, not per-asset. Some assets can have stale
advice_ts_1h_utc because of sparse candles or quality blocking. Using per-asset
context timestamps would mix market regimes inside one filter run.
"""

from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.trade_setup_filter.models import TradeSetupCandidate


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def fetch_latest_candidates(
    *,
    venue: str,
    engine_name: str,
    engine_version: str,
    limit: int,
) -> list[TradeSetupCandidate]:
    sql = """
    WITH latest AS (
        SELECT MAX(asof_ts_utc) AS latest_asof_ts_utc
        FROM selection_state
        WHERE venue = %s
          AND engine_name = %s
          AND engine_version = %s
    ),
    context AS (
        SELECT MAX(ss.advice_ts_1h_utc) AS context_ts_utc
        FROM selection_state ss
        JOIN latest l
          ON l.latest_asof_ts_utc = ss.asof_ts_utc
        WHERE ss.venue = %s
          AND ss.engine_name = %s
          AND ss.engine_version = %s
    ),
    btc AS (
        SELECT asset_id
        FROM asset
        WHERE symbol = 'BTC'
        LIMIT 1
    )
    SELECT
        ss.asset_id,
        a.symbol,
        ss.venue,
        ss.asof_ts_utc,
        c.context_ts_utc,
        ss.selection_state,
        ss.selection_bias,
        ss.selection_score,
        ss.priority_rank,
        NULL AS allowed_sleeves,
        ss.summary_text,

        CASE
            WHEN btc_now.close_price IS NULL
              OR btc_prev24.close_price IS NULL
              OR btc_prev24.close_price = 0
            THEN NULL
            ELSE ((btc_now.close_price - btc_prev24.close_price) / btc_prev24.close_price)
        END AS btc_prior_24h

    FROM selection_state ss
    JOIN latest l
      ON l.latest_asof_ts_utc = ss.asof_ts_utc
    JOIN context c
    JOIN asset a
      ON a.asset_id = ss.asset_id
    JOIN btc

    LEFT JOIN obs_market_candle btc_now
      ON btc_now.asset_id = btc.asset_id
     AND btc_now.venue = ss.venue
     AND btc_now.interval_code = '1h'
     AND btc_now.close_ts_utc = c.context_ts_utc

    LEFT JOIN obs_market_candle btc_prev24
      ON btc_prev24.asset_id = btc.asset_id
     AND btc_prev24.venue = ss.venue
     AND btc_prev24.interval_code = '1h'
     AND btc_prev24.close_ts_utc = DATE_SUB(c.context_ts_utc, INTERVAL 24 HOUR)

    WHERE ss.venue = %s
      AND ss.engine_name = %s
      AND ss.engine_version = %s

    ORDER BY
        ss.priority_rank IS NULL ASC,
        ss.priority_rank ASC,
        ss.selection_score DESC,
        a.symbol ASC

    LIMIT %s
    """

    params = [
        venue,
        engine_name,
        engine_version,
        venue,
        engine_name,
        engine_version,
        venue,
        engine_name,
        engine_version,
        limit,
    ]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    candidates: list[TradeSetupCandidate] = []

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")

        candidates.append(
            TradeSetupCandidate(
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                asof_ts_utc=row["asof_ts_utc"],
                context_ts_utc=row["context_ts_utc"],
                selection_state=str(row["selection_state"]),
                selection_bias=row["selection_bias"],
                selection_score=_to_decimal(row["selection_score"]),
                priority_rank=_to_int(row["priority_rank"]),
                allowed_sleeves=row["allowed_sleeves"],
                btc_prior_24h=_to_decimal(row["btc_prior_24h"]),
                summary_text=row["summary_text"],
            )
        )

    return candidates
