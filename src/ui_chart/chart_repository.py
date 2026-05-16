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


def table_columns(table_name: str) -> set[str]:
    rows = _fetch_all(
        "SELECT column_name "
        "FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        "AND table_name = %s",
        (table_name,),
    )
    return {str(row["column_name"]) for row in rows}


def _clean_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None

    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            cleaned[key] = float(value)
        else:
            cleaned[key] = value
    return cleaned


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

    return _clean_row(row)


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


def fetch_display_context(
    asset_id: int,
    venue: str,
    interval_code: str,
) -> dict[str, Any]:
    return {
        "latest_candle": fetch_latest_candle_context(asset_id, venue, interval_code),
        "latest_signal": fetch_latest_signal_context(asset_id, venue, interval_code),
        "latest_selection": fetch_latest_selection_context(asset_id, venue),
        "latest_advice": fetch_latest_advice_context(asset_id, venue, interval_code),
        "latest_execution_zone": fetch_latest_execution_zone_context(asset_id, venue, interval_code),
        "latest_strategy_runtime_snapshot": fetch_latest_strategy_runtime_snapshot_context(
            venue=venue,
            interval_code=interval_code,
            chain_name="run_chain_4h",
        ),
    }


def fetch_latest_candle_context(
    asset_id: int,
    venue: str,
    interval_code: str,
) -> dict[str, Any] | None:
    row = _fetch_one(
        "SELECT "
        "asset_id, "
        "venue, "
        "interval_code, "
        "close_ts_utc, "
        "close_price "
        "FROM obs_market_candle "
        "WHERE asset_id = %s "
        "AND venue = %s "
        "AND interval_code = %s "
        "ORDER BY close_ts_utc DESC "
        "LIMIT 1",
        (asset_id, venue, interval_code),
    )
    return _clean_row(row)


def fetch_latest_signal_context(
    asset_id: int,
    venue: str,
    interval_code: str,
) -> dict[str, Any] | None:
    if not table_exists("signal_engine_state"):
        return None

    row = _fetch_one(
        "SELECT "
        "asset_id, "
        "venue, "
        "interval_code, "
        "signal_ts_utc, "
        "trend_signal, "
        "volume_signal, "
        "phase_signal, "
        "setup_signal, "
        "risk_signal, "
        "signal_confidence, "
        "reason_code "
        "FROM signal_engine_state "
        "WHERE asset_id = %s "
        "AND venue = %s "
        "AND interval_code = %s "
        "ORDER BY signal_ts_utc DESC "
        "LIMIT 1",
        (asset_id, venue, interval_code),
    )
    return _clean_row(row)


def fetch_latest_selection_context(
    asset_id: int,
    venue: str,
) -> dict[str, Any] | None:
    if not table_exists("selection_state"):
        return None

    row = _fetch_one(
        "SELECT "
        "asset_id, "
        "venue, "
        "asof_ts_utc, "
        "selection_state, "
        "selection_bias, "
        "selection_score, "
        "priority_rank, "
        "advice_state_1h, "
        "advice_state_4h "
        "FROM selection_state "
        "WHERE asset_id = %s "
        "AND venue = %s "
        "ORDER BY asof_ts_utc DESC "
        "LIMIT 1",
        (asset_id, venue),
    )
    return _clean_row(row)


def fetch_latest_advice_context(
    asset_id: int,
    venue: str,
    interval_code: str,
) -> dict[str, Any] | None:
    if table_exists("paper_advice_observation"):
        row = _fetch_one(
            "SELECT "
            "asset_id, "
            "symbol, "
            "venue, "
            "interval_code, "
            "asof_ts_utc, "
            "context_ts_utc, "
            "advice_state, "
            "advice_action, "
            "confidence_score, "
            "risk_label, "
            "policy_decision, "
            "allowed_now "
            "FROM paper_advice_observation "
            "WHERE asset_id = %s "
            "AND venue = %s "
            "AND interval_code = %s "
            "ORDER BY asof_ts_utc DESC "
            "LIMIT 1",
            (asset_id, venue, interval_code),
        )
        return _clean_row(row)

    if not table_exists("advice_state"):
        return None

    columns = table_columns("advice_state")
    if not {"asset_id", "venue", "interval_code", "asof_ts_utc"}.issubset(columns):
        return None

    selected_columns = [
        "asset_id",
        "venue",
        "interval_code",
        "asof_ts_utc",
    ]
    for column in ["advice_state", "horizon_hint", "confidence_score", "reason_text"]:
        if column in columns:
            selected_columns.append(column)

    sql = (
        "SELECT "
        + ", ".join(selected_columns)
        + " FROM advice_state "
        + "WHERE asset_id = %s "
        + "AND venue = %s "
        + "AND interval_code = %s "
        + "ORDER BY asof_ts_utc DESC "
        + "LIMIT 1"
    )
    row = _fetch_one(sql, (asset_id, venue, interval_code))
    return _clean_row(row)


def fetch_latest_execution_zone_context(
    asset_id: int,
    venue: str,
    interval_code: str,
) -> dict[str, Any] | None:
    if table_exists("vw_paper_advice_execution_zone_context_v1"):
        row = _fetch_one(
            "SELECT "
            "asset_id, "
            "venue, "
            "interval_code, "
            "asof_ts_utc, "
            "leg_direction, "
            "entry_zone_low, "
            "entry_zone_high, "
            "entry_zone_type, "
            "tp_zone_low, "
            "tp_zone_high, "
            "tp_zone_type, "
            "invalidation_price, "
            "zone_confidence_score, "
            "zone_alignment_score "
            "FROM vw_paper_advice_execution_zone_context_v1 "
            "WHERE asset_id = %s "
            "AND venue = %s "
            "AND interval_code = %s "
            "ORDER BY asof_ts_utc DESC "
            "LIMIT 1",
            (asset_id, venue, interval_code),
        )
        return _clean_row(row)

    if not table_exists("execution_zone_context"):
        return None

    row = _fetch_one(
        "SELECT "
        "asset_id, "
        "venue, "
        "interval_code, "
        "asof_ts_utc, "
        "expected_entry_zone_low AS entry_zone_low, "
        "expected_entry_zone_high AS entry_zone_high, "
        "expected_entry_zone_type AS entry_zone_type, "
        "expected_take_profit_zone_low AS tp_zone_low, "
        "expected_take_profit_zone_high AS tp_zone_high, "
        "expected_take_profit_zone_type AS tp_zone_type, "
        "invalidation_price, "
        "zone_confidence_score, "
        "zone_alignment_score "
        "FROM execution_zone_context "
        "WHERE asset_id = %s "
        "AND venue = %s "
        "AND interval_code = %s "
        "ORDER BY asof_ts_utc DESC "
        "LIMIT 1",
        (asset_id, venue, interval_code),
    )
    return _clean_row(row)


def fetch_latest_strategy_runtime_snapshot_context(
    *,
    venue: str,
    interval_code: str,
    chain_name: str,
) -> dict[str, Any] | None:
    if not table_exists("strategy_runtime_snapshot"):
        return None

    columns = table_columns("strategy_runtime_snapshot")
    if not {"strategy_runtime_snapshot_id", "snapshot_ts_utc"}.issubset(columns):
        return None

    where_parts = []
    params: list[Any] = []

    if "venue" in columns:
        where_parts.append("venue = %s")
        params.append(venue)
    if "interval_code" in columns:
        where_parts.append("interval_code = %s")
        params.append(interval_code)
    if "chain_name" in columns:
        where_parts.append("chain_name = %s")
        params.append(chain_name)

    selected_columns = [
        "strategy_runtime_snapshot_id",
        "snapshot_ts_utc",
    ]
    for column in [
        "git_commit",
        "runtime_scope",
        "venue",
        "interval_code",
        "chain_name",
        "live_trading_enabled",
        "decision_gate_enabled",
        "execution_enabled",
        "notes",
    ]:
        if column in columns:
            selected_columns.append(column)

    sql = "SELECT " + ", ".join(selected_columns) + " FROM strategy_runtime_snapshot"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += " ORDER BY strategy_runtime_snapshot_id DESC LIMIT 1"

    row = _fetch_one(sql, tuple(params))
    return _clean_row(row)
