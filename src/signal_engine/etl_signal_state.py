from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SignalStateRow:
    asset_id: int
    venue: str
    interval_code: str
    candle_id: int
    close_ts_utc: datetime

    trend_signal: str | None
    momentum_signal: str | None
    volume_signal: str | None
    volatility_signal: str | None
    setup_signal: str | None
    risk_signal: str | None

    trend_score: Decimal | None
    momentum_score: Decimal | None
    volume_score: Decimal | None
    volatility_score: Decimal | None
    setup_score: Decimal | None
    risk_score: Decimal | None

    summary_bias: str | None
    summary_score: Decimal | None


def load_assets(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT asset_id, symbol
    FROM asset
    ORDER BY asset_id
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    assets: list[dict[str, Any]] = []

    for row in rows:
        if isinstance(row, dict):
            assets.append(
                {
                    "asset_id": int(row["asset_id"]),
                    "symbol": str(row["symbol"]).upper(),
                }
            )
        else:
            asset_id, symbol = row
            assets.append(
                {
                    "asset_id": int(asset_id),
                    "symbol": str(symbol).upper(),
                }
            )

    return assets


def load_latest_feat_row(
    conn,
    asset_id: int,
    venue: str,
    interval_code: str,
) -> pd.DataFrame:
    sql = """
    SELECT
        candle_id,
        asset_id,
        venue,
        interval_code,
        close_ts_utc,
        ema_20,
        ema_50,
        rsi_14,
        atr_14,
        volume_ratio_20,
        volume_zscore_20,
        obv,
        obv_slope_5,
        dollar_volume_ratio_20,
        price_vs_ema20,
        price_vs_ema50,
        atr_pct,
        ema_spread,
        ema_spread_pct
    FROM feat_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
    ORDER BY close_ts_utc DESC
    LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(sql, (asset_id, venue, interval_code))
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    if isinstance(rows[0], dict):
        df = pd.DataFrame(rows)
    else:
        columns = [
            "candle_id",
            "asset_id",
            "venue",
            "interval_code",
            "close_ts_utc",
            "ema_20",
            "ema_50",
            "rsi_14",
            "atr_14",
            "volume_ratio_20",
            "volume_zscore_20",
            "obv",
            "obv_slope_5",
            "dollar_volume_ratio_20",
            "price_vs_ema20",
            "price_vs_ema50",
            "atr_pct",
            "ema_spread",
            "ema_spread_pct",
        ]
        df = pd.DataFrame(rows, columns=columns)

    df["close_ts_utc"] = pd.to_datetime(df["close_ts_utc"], utc=True, errors="raise")

    numeric_cols = [
        "ema_20",
        "ema_50",
        "rsi_14",
        "atr_14",
        "volume_ratio_20",
        "volume_zscore_20",
        "obv",
        "obv_slope_5",
        "dollar_volume_ratio_20",
        "price_vs_ema20",
        "price_vs_ema50",
        "atr_pct",
        "ema_spread",
        "ema_spread_pct",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def to_decimal_or_none(value: Any, scale: int = 8) -> Decimal | None:
    if pd.isna(value):
        return None
    return Decimal(str(round(float(value), scale)))


def interpret_trend(row: pd.Series) -> tuple[str, float]:
    spread_pct = row["ema_spread_pct"]
    p20 = row["price_vs_ema20"]
    p50 = row["price_vs_ema50"]

    if pd.isna(spread_pct) or pd.isna(p20) or pd.isna(p50):
        return "unknown", 0.0

    raw = (spread_pct * 100.0 * 2.0) + (p20 * 100.0) + (p50 * 100.0)
    score = clamp(raw / 10.0, -1.0, 1.0)

    if score >= 0.35:
        return "bullish", score
    if score <= -0.35:
        return "bearish", score
    return "neutral", score


def interpret_momentum(row: pd.Series) -> tuple[str, float]:
    rsi = row["rsi_14"]

    if pd.isna(rsi):
        return "unknown", 0.0

    score = clamp((rsi - 50.0) / 20.0, -1.0, 1.0)

    if rsi >= 60:
        return "strong_up", score
    if rsi <= 40:
        return "strong_down", score
    return "balanced", score


def interpret_volume(row: pd.Series) -> tuple[str, float]:
    vr = row["volume_ratio_20"]
    vz = row["volume_zscore_20"]
    dvr = row["dollar_volume_ratio_20"]
    obv_slope = row["obv_slope_5"]

    if pd.isna(vr) or pd.isna(vz) or pd.isna(dvr):
        return "unknown", 0.0

    obv_component = 0.0 if pd.isna(obv_slope) else clamp(float(obv_slope) / 100000.0, -1.0, 1.0)
    raw = ((float(vr) - 1.0) * 0.8) + (float(vz) * 0.25) + ((float(dvr) - 1.0) * 0.8) + (obv_component * 0.5)
    score = clamp(raw, -1.0, 1.0)

    if score >= 0.4:
        return "expanding", score
    if score <= -0.4:
        return "dry", score
    return "normal", score


def interpret_volatility(row: pd.Series) -> tuple[str, float]:
    atr_pct = row["atr_pct"]

    if pd.isna(atr_pct):
        return "unknown", 0.0

    atr_pct = float(atr_pct)
    score = clamp((atr_pct - 0.02) / 0.03, -1.0, 1.0)

    if atr_pct >= 0.04:
        return "high", score
    if atr_pct <= 0.015:
        return "low", score
    return "medium", score


def interpret_setup(
    trend_signal: str,
    momentum_signal: str,
    volume_signal: str,
    row: pd.Series,
) -> tuple[str, float]:
    p20 = row["price_vs_ema20"]
    spread = row["ema_spread_pct"]

    if pd.isna(p20) or pd.isna(spread):
        return "unknown", 0.0

    score = 0.0

    if trend_signal == "bullish":
        score += 0.4
    elif trend_signal == "bearish":
        score -= 0.4

    if momentum_signal == "strong_up":
        score += 0.3
    elif momentum_signal == "strong_down":
        score -= 0.3

    if volume_signal == "expanding":
        score += 0.2
    elif volume_signal == "dry":
        score -= 0.2

    score += clamp(float(p20) * 10.0, -0.2, 0.2)
    score += clamp(float(spread) * 10.0, -0.2, 0.2)
    score = clamp(score, -1.0, 1.0)

    if score >= 0.45:
        return "long_ready", score
    if score <= -0.45:
        return "short_ready", score
    return "wait", score


def interpret_risk(
    volatility_signal: str,
    volume_signal: str,
    row: pd.Series,
) -> tuple[str, float]:
    atr_pct = row["atr_pct"]
    vz = row["volume_zscore_20"]

    if pd.isna(atr_pct):
        return "unknown", 0.0

    score = 0.0
    atr_pct = float(atr_pct)

    if volatility_signal == "high":
        score += 0.6
    elif volatility_signal == "medium":
        score += 0.2

    if volume_signal == "dry":
        score += 0.2

    if not pd.isna(vz) and float(vz) > 2.0:
        score += 0.2

    score = clamp(score, 0.0, 1.0)

    if score >= 0.7:
        return "high_risk", score
    if score >= 0.35:
        return "medium_risk", score
    return "low_risk", score


def summarize_bias(
    trend_score: float,
    momentum_score: float,
    volume_score: float,
    setup_score: float,
    risk_score: float,
) -> tuple[str, float]:
    raw = (
        (trend_score * 0.35) +
        (momentum_score * 0.25) +
        (volume_score * 0.15) +
        (setup_score * 0.25) -
        (risk_score * 0.15)
    )
    score = clamp(raw, -1.0, 1.0)

    if score >= 0.35:
        return "bullish", score
    if score <= -0.35:
        return "bearish", score
    return "neutral", score


def dataframe_to_signal_row(df: pd.DataFrame) -> SignalStateRow | None:
    if df.empty:
        return None

    row = df.iloc[0]

    trend_signal, trend_score = interpret_trend(row)
    momentum_signal, momentum_score = interpret_momentum(row)
    volume_signal, volume_score = interpret_volume(row)
    volatility_signal, volatility_score = interpret_volatility(row)
    setup_signal, setup_score = interpret_setup(
        trend_signal=trend_signal,
        momentum_signal=momentum_signal,
        volume_signal=volume_signal,
        row=row,
    )
    risk_signal, risk_score = interpret_risk(
        volatility_signal=volatility_signal,
        volume_signal=volume_signal,
        row=row,
    )
    summary_bias, summary_score = summarize_bias(
        trend_score=trend_score,
        momentum_score=momentum_score,
        volume_score=volume_score,
        setup_score=setup_score,
        risk_score=risk_score,
    )

    return SignalStateRow(
        asset_id=int(row["asset_id"]),
        venue=str(row["venue"]),
        interval_code=str(row["interval_code"]),
        candle_id=int(row["candle_id"]),
        close_ts_utc=row["close_ts_utc"].to_pydatetime(),
        trend_signal=trend_signal,
        momentum_signal=momentum_signal,
        volume_signal=volume_signal,
        volatility_signal=volatility_signal,
        setup_signal=setup_signal,
        risk_signal=risk_signal,
        trend_score=to_decimal_or_none(trend_score),
        momentum_score=to_decimal_or_none(momentum_score),
        volume_score=to_decimal_or_none(volume_score),
        volatility_score=to_decimal_or_none(volatility_score),
        setup_score=to_decimal_or_none(setup_score),
        risk_score=to_decimal_or_none(risk_score),
        summary_bias=summary_bias,
        summary_score=to_decimal_or_none(summary_score),
    )


def upsert_signal_state_row(conn, row: SignalStateRow) -> int:
    sql = """
    INSERT INTO signal_state (
        asset_id,
        venue,
        interval_code,
        candle_id,
        close_ts_utc,
        trend_signal,
        momentum_signal,
        volume_signal,
        volatility_signal,
        setup_signal,
        risk_signal,
        trend_score,
        momentum_score,
        volume_score,
        volatility_score,
        setup_score,
        risk_score,
        summary_bias,
        summary_score
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        candle_id = VALUES(candle_id),
        close_ts_utc = VALUES(close_ts_utc),
        trend_signal = VALUES(trend_signal),
        momentum_signal = VALUES(momentum_signal),
        volume_signal = VALUES(volume_signal),
        volatility_signal = VALUES(volatility_signal),
        setup_signal = VALUES(setup_signal),
        risk_signal = VALUES(risk_signal),
        trend_score = VALUES(trend_score),
        momentum_score = VALUES(momentum_score),
        volume_score = VALUES(volume_score),
        volatility_score = VALUES(volatility_score),
        setup_score = VALUES(setup_score),
        risk_score = VALUES(risk_score),
        summary_bias = VALUES(summary_bias),
        summary_score = VALUES(summary_score)
    """

    data = (
        row.asset_id,
        row.venue,
        row.interval_code,
        row.candle_id,
        row.close_ts_utc.replace(tzinfo=None),
        row.trend_signal,
        row.momentum_signal,
        row.volume_signal,
        row.volatility_signal,
        row.setup_signal,
        row.risk_signal,
        None if row.trend_score is None else str(row.trend_score),
        None if row.momentum_score is None else str(row.momentum_score),
        None if row.volume_score is None else str(row.volume_score),
        None if row.volatility_score is None else str(row.volatility_score),
        None if row.setup_score is None else str(row.setup_score),
        None if row.risk_score is None else str(row.risk_score),
        row.summary_bias,
        None if row.summary_score is None else str(row.summary_score),
    )

    with conn.cursor() as cur:
        cur.execute(sql, data)

    conn.commit()
    return 1


def run_signal_state_for_asset_interval(
    conn,
    asset_id: int,
    venue: str,
    interval_code: str,
) -> int:
    df = load_latest_feat_row(
        conn=conn,
        asset_id=asset_id,
        venue=venue,
        interval_code=interval_code,
    )

    if df.empty:
        return 0

    row = dataframe_to_signal_row(df)
    if row is None:
        return 0

    return upsert_signal_state_row(conn, row)
