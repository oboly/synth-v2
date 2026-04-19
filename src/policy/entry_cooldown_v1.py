from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.common.db import get_connection


@dataclass(frozen=True)
class EntryCooldownResult:
    asset_id: int
    symbol: str
    cooldown_blocked: bool
    last_close_fill_ts_utc: datetime | None
    candles_since_close: int | None
    reason: str


def fetch_last_close_fill_ts(
    *,
    account_id: int,
    sleeve_code: str,
    asset_id: int,
) -> datetime | None:
    sql = """
    SELECT MAX(ee.created_ts_utc) AS last_close_fill_ts_utc
    FROM execution_event ee
    JOIN execution_plan ep
      ON ep.execution_plan_id = ee.execution_plan_id
    WHERE ee.account_id = %s
      AND ee.sleeve_code = %s
      AND ee.asset_id = %s
      AND ee.event_type = 'PAPER_FILL_CLOSE'
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [account_id, sleeve_code, asset_id])
            row = cur.fetchone()
            if not row:
                return None
            return row["last_close_fill_ts_utc"]
    finally:
        conn.close()


def fetch_closed_1h_candles_since(
    *,
    venue: str,
    asset_id: int,
    since_ts_utc: datetime,
) -> int:
    sql = """
    SELECT COUNT(*) AS n
    FROM obs_market_candle
    WHERE venue = %s
      AND asset_id = %s
      AND interval_code = '1h'
      AND close_ts_utc > %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [venue, asset_id, since_ts_utc])
            row = cur.fetchone()
            return int(row["n"]) if row else 0
    finally:
        conn.close()


def evaluate_entry_cooldown(
    *,
    account_id: int,
    sleeve_code: str,
    venue: str,
    asset_id: int,
    symbol: str,
    cooldown_candles_after_close: int,
) -> EntryCooldownResult:
    last_close_fill_ts_utc = fetch_last_close_fill_ts(
        account_id=account_id,
        sleeve_code=sleeve_code,
        asset_id=asset_id,
    )

    if last_close_fill_ts_utc is None:
        return EntryCooldownResult(
            asset_id=asset_id,
            symbol=symbol,
            cooldown_blocked=False,
            last_close_fill_ts_utc=None,
            candles_since_close=None,
            reason="NO_RECENT_CLOSE",
        )

    candles_since_close = fetch_closed_1h_candles_since(
        venue=venue,
        asset_id=asset_id,
        since_ts_utc=last_close_fill_ts_utc,
    )

    if candles_since_close < cooldown_candles_after_close:
        return EntryCooldownResult(
            asset_id=asset_id,
            symbol=symbol,
            cooldown_blocked=True,
            last_close_fill_ts_utc=last_close_fill_ts_utc,
            candles_since_close=candles_since_close,
            reason="ENTRY_COOLDOWN_ACTIVE",
        )

    return EntryCooldownResult(
        asset_id=asset_id,
        symbol=symbol,
        cooldown_blocked=False,
        last_close_fill_ts_utc=last_close_fill_ts_utc,
        candles_since_close=candles_since_close,
        reason="ENTRY_COOLDOWN_CLEARED",
    )
