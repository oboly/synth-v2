from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import pymysql

from src.common.db import get_connection
from src.ui_chart.chart_config import MAX_CANDLES_DEFAULT


@dataclass(frozen=True)
class AssetRef:
    asset_id: int
    symbol: str
    name: str | None


def _rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    for column in frame.columns:
        if frame[column].map(lambda value: isinstance(value, Decimal)).any():
            frame[column] = frame[column].astype(float)

    return frame


def _fetch_all(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    finally:
        conn.close()


def _fetch_one(sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    rows = _fetch_all(sql, params)
    if not rows:
        return None
    return rows[0]


def table_exists(table_name: str) -> bool:
    row = _fetch_one(
        "SELECT COUNT(*) AS n "
        "FROM information_schema.tables "
        "WHERE table_schema = DATABASE() "
        "AND table_name = %s",
        (table_name,),
    )
    return bool(row and int(row["n"]) > 0)


def fetch_assets() -> list[AssetRef]:
    rows = _fetch_all(
        "SELECT asset_id, symbol, name "
        "FROM asset "
        "WHERE is_enabled = 1 "
        "ORDER BY symbol",
        (),
    )
    return [
        AssetRef(
            asset_id=int(row["asset_id"]),
            symbol=str(row["symbol"]),
            name=row.get("name"),
        )
        for row in rows
    ]


def resolve_asset(symbol: str) -> AssetRef | None:
    row = _fetch_one(
        "SELECT asset_id, symbol, name "
        "FROM asset "
        "WHERE UPPER(symbol) = UPPER(%s) "
        "ORDER BY asset_id "
        "LIMIT 1",
        (symbol,),
    )
    if not row:
        return None

    return AssetRef(
        asset_id=int(row["asset_id"]),
        symbol=str(row["symbol"]),
        name=row.get("name"),
    )


def fetch_chart_frame(
    asset_id: int,
    venue: str,
    interval_code: str,
    start_ts_utc: datetime,
    end_ts_utc: datetime,
    max_candles: int = MAX_CANDLES_DEFAULT,
) -> pd.DataFrame:
    sql = (
        "SELECT "
        "c.asset_id, "
        "c.venue, "
        "c.interval_code, "
        "c.open_ts_utc AS ts_utc, "
        "c.open_ts_utc, "
        "c.close_ts_utc, "
        "c.open_price, "
        "c.high_price, "
        "c.low_price, "
        "c.close_price, "
        "c.volume_base, "
        "c.volume_quote_eur, "
        "f.ema_20, "
        "f.ema_50, "
        "f.rsi_14, "
        "f.atr_14, "
        "f.volume_ratio_20, "
        "f.volume_zscore_20, "
        "f.obv, "
        "f.obv_slope_5, "
        "f.dollar_volume_ratio_20, "
        "f.price_vs_ema20, "
        "f.price_vs_ema50, "
        "f.atr_pct, "
        "f.ema_spread_pct, "
        "f.wick_reversal_score, "
        "s.trend_signal, "
        "s.volume_signal, "
        "s.phase_signal, "
        "s.compass_signal, "
        "s.rotation_signal, "
        "s.relative_signal, "
        "s.setup_signal, "
        "s.risk_signal, "
        "s.signal_confidence, "
        "s.reason_code, "
        "s.reason_text, "
        "s.expansion_position_score, "
        "s.pullback_quality_score, "
        "s.late_trend_flag "
        "FROM obs_market_candle c "
        "LEFT JOIN feat_candle f "
        "ON f.asset_id = c.asset_id "
        "AND f.venue = %s "
        "AND f.interval_code = %s "
        "AND f.close_ts_utc = c.close_ts_utc "
        "LEFT JOIN signal_engine_state s "
        "ON s.asset_id = c.asset_id "
        "AND s.venue = %s "
        "AND s.interval_code = %s "
        "AND s.signal_ts_utc = c.open_ts_utc "
        "WHERE c.asset_id = %s "
        "AND c.venue = %s "
        "AND c.interval_code = %s "
        "AND c.open_ts_utc >= %s "
        "AND c.open_ts_utc < %s "
        "ORDER BY c.open_ts_utc "
        "LIMIT %s"
    )
    rows = _fetch_all(
        sql,
        (
            venue,
            interval_code,
            venue,
            interval_code,
            asset_id,
            venue,
            interval_code,
            start_ts_utc,
            end_ts_utc,
            max_candles,
        ),
    )
    return _rows_to_dataframe(rows)


def fetch_selection_frame(
    asset_id: int,
    venue: str,
    start_ts_utc: datetime,
    end_ts_utc: datetime,
    max_rows: int = 1000,
) -> pd.DataFrame:
    sql = (
        "SELECT "
        "asset_id, "
        "venue, "
        "asof_ts_utc, "
        "selection_state, "
        "selection_bias, "
        "selection_score, "
        "priority_rank, "
        "regime_label_1h, "
        "regime_label_4h, "
        "advice_state_1h, "
        "advice_state_4h, "
        "summary_text "
        "FROM selection_state "
        "WHERE asset_id = %s "
        "AND venue = %s "
        "AND asof_ts_utc >= %s "
        "AND asof_ts_utc < %s "
        "ORDER BY asof_ts_utc "
        "LIMIT %s"
    )
    rows = _fetch_all(
        sql,
        (
            asset_id,
            venue,
            start_ts_utc,
            end_ts_utc,
            max_rows,
        ),
    )
    return _rows_to_dataframe(rows)


def fetch_point_in_time_profile(
    asset_id: int,
    venue: str,
    interval_code: str,
    asof_ts_utc: datetime,
) -> dict[str, Any] | None:
    row = _fetch_one(
        "SELECT "
        "asset_id, "
        "venue, "
        "interval_code, "
        "asof_ts_utc, "
        "lookback_days, "
        "profile_version, "
        "liquidity_score, "
        "liquidity_class, "
        "beta_to_market, "
        "beta_profile, "
        "realized_volatility, "
        "sector_group_code, "
        "sector_confidence, "
        "coverage_ratio, "
        "benchmark_symbols, "
        "notes "
        "FROM asset_profile_snapshot "
        "WHERE asset_id = %s "
        "AND venue = %s "
        "AND interval_code = %s "
        "AND asof_ts_utc <= %s "
        "ORDER BY asof_ts_utc DESC "
        "LIMIT 1",
        (
            asset_id,
            venue,
            interval_code,
            asof_ts_utc,
        ),
    )
    if not row:
        return None

    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            cleaned[key] = float(value)
        else:
            cleaned[key] = value
    return cleaned


def fetch_paper_candidate_frame(
    asset_id: int,
    venue: str,
    start_ts_utc: datetime,
    end_ts_utc: datetime,
    batch_id: str | None = None,
    policy_name: str | None = None,
    max_rows: int = 1000,
) -> pd.DataFrame:
    if not table_exists("research_paper_candidate_signal"):
        return pd.DataFrame()

    where_parts = [
        "asset_id = %s",
        "venue = %s",
        "created_ts_utc >= %s",
        "created_ts_utc < %s",
    ]
    params: list[Any] = [asset_id, venue, start_ts_utc, end_ts_utc]

    if batch_id:
        where_parts.append("batch_id = %s")
        params.append(batch_id)

    if policy_name:
        where_parts.append("policy_name = %s")
        params.append(policy_name)

    sql = (
        "SELECT * "
        "FROM research_paper_candidate_signal "
        "WHERE "
        + " AND ".join(where_parts)
        + " ORDER BY created_ts_utc "
        + "LIMIT %s"
    )
    params.append(max_rows)

    rows = _fetch_all(sql, tuple(params))
    return _rows_to_dataframe(rows)
