from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FeatureRow:
    candle_id: int
    asset_id: int
    venue: str
    interval_code: str
    close_ts_utc: datetime
    ema_20: Decimal | None
    ema_50: Decimal | None
    rsi_14: Decimal | None
    atr_14: Decimal | None
    volume_ratio_20: Decimal | None
    volume_zscore_20: Decimal | None
    obv: Decimal | None
    obv_slope_5: Decimal | None
    dollar_volume_ratio_20: Decimal | None
    price_vs_ema20: Decimal | None
    price_vs_ema50: Decimal | None
    atr_pct: Decimal | None
    ema_spread: Decimal | None
    ema_spread_pct: Decimal | None


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_ts(value: datetime) -> datetime:
    return _normalize_utc(value).replace(tzinfo=None)


def _interval_delta(interval_code: str) -> timedelta:
    interval = interval_code.strip().lower()

    if interval.endswith("m"):
        return timedelta(minutes=int(interval[:-1]))
    if interval.endswith("h"):
        return timedelta(hours=int(interval[:-1]))
    if interval.endswith("d"):
        return timedelta(days=int(interval[:-1]))

    raise ValueError(f"Unsupported interval_code for warmup calculation: {interval_code}")


def load_assets(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT asset_id, symbol
    FROM asset
    WHERE is_enabled = 1
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


def load_candles(
    conn,
    asset_id: int,
    venue: str,
    interval_code: str,
    *,
    source_start_ts_utc: datetime | None = None,
    source_end_ts_utc: datetime | None = None,
) -> pd.DataFrame:
    where_parts = [
        "asset_id = %s",
        "venue = %s",
        "interval_code = %s",
    ]
    params: list[Any] = [asset_id, venue, interval_code]

    if source_start_ts_utc is not None:
        where_parts.append("close_ts_utc >= %s")
        params.append(_db_ts(source_start_ts_utc))

    if source_end_ts_utc is not None:
        where_parts.append("close_ts_utc < %s")
        params.append(_db_ts(source_end_ts_utc))

    sql = f"""
    SELECT
        candle_id,
        asset_id,
        venue,
        interval_code,
        open_ts_utc,
        close_ts_utc,
        open_price,
        high_price,
        low_price,
        close_price,
        volume_base
    FROM obs_market_candle
    WHERE {" AND ".join(where_parts)}
    ORDER BY open_ts_utc
    """

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
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
            "open_ts_utc",
            "close_ts_utc",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume_base",
        ]
        df = pd.DataFrame(rows, columns=columns)

    df["open_ts_utc"] = pd.to_datetime(df["open_ts_utc"], utc=True, errors="raise")
    df["close_ts_utc"] = pd.to_datetime(df["close_ts_utc"], utc=True, errors="raise")

    numeric_cols = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume_base",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()

    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    prev_close = close.shift(1)

    tr_1 = high - low
    tr_2 = (high - prev_close).abs()
    tr_3 = (low - prev_close).abs()

    tr = pd.concat([tr_1, tr_2, tr_3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return atr


def to_decimal_or_none(value: Any, scale: int = 10) -> Decimal | None:
    if pd.isna(value):
        return None
    return Decimal(str(round(float(value), scale)))


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    close = out["close_price"]
    volume = out["volume_base"]

    out["ema_20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    out["ema_50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()

    out["rsi_14"] = compute_rsi(close, period=14)
    out["atr_14"] = compute_atr(
        high=out["high_price"],
        low=out["low_price"],
        close=close,
        period=14,
    )

    vol_sma_20 = volume.rolling(20, min_periods=20).mean()
    vol_std_20 = volume.rolling(20, min_periods=20).std(ddof=0)

    out["volume_ratio_20"] = volume / vol_sma_20
    out["volume_zscore_20"] = (volume - vol_sma_20) / vol_std_20

    close_delta_sign = close.diff().fillna(0.0)
    direction = close_delta_sign.apply(
        lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)
    )

    out["obv"] = (direction * volume.fillna(0.0)).cumsum()
    out["obv_slope_5"] = out["obv"] - out["obv"].shift(5)

    dollar_volume = close * volume
    dollar_volume_sma_20 = dollar_volume.rolling(20, min_periods=20).mean()
    out["dollar_volume_ratio_20"] = dollar_volume / dollar_volume_sma_20

    out["price_vs_ema20"] = (close / out["ema_20"]) - 1.0
    out["price_vs_ema50"] = (close / out["ema_50"]) - 1.0
    out["atr_pct"] = out["atr_14"] / close
    out["ema_spread"] = out["ema_20"] - out["ema_50"]
    out["ema_spread_pct"] = (out["ema_20"] / out["ema_50"]) - 1.0

    return out


def filter_write_window(
    df: pd.DataFrame,
    *,
    write_start_ts_utc: datetime | None,
    write_end_ts_utc: datetime | None,
) -> pd.DataFrame:
    if df.empty:
        return df

    out = df

    if write_start_ts_utc is not None:
        start_ts = pd.Timestamp(_normalize_utc(write_start_ts_utc))
        out = out[out["close_ts_utc"] >= start_ts]

    if write_end_ts_utc is not None:
        end_ts = pd.Timestamp(_normalize_utc(write_end_ts_utc))
        out = out[out["close_ts_utc"] < end_ts]

    return out.copy()


def dataframe_to_feature_rows(df: pd.DataFrame) -> list[FeatureRow]:
    if df.empty:
        return []

    rows: list[FeatureRow] = []

    for _, row in df.iterrows():
        close_ts = row["close_ts_utc"].to_pydatetime()

        rows.append(
            FeatureRow(
                candle_id=int(row["candle_id"]),
                asset_id=int(row["asset_id"]),
                venue=str(row["venue"]),
                interval_code=str(row["interval_code"]),
                close_ts_utc=close_ts,
                ema_20=to_decimal_or_none(row["ema_20"]),
                ema_50=to_decimal_or_none(row["ema_50"]),
                rsi_14=to_decimal_or_none(row["rsi_14"], scale=8),
                atr_14=to_decimal_or_none(row["atr_14"]),
                volume_ratio_20=to_decimal_or_none(row["volume_ratio_20"], scale=8),
                volume_zscore_20=to_decimal_or_none(row["volume_zscore_20"], scale=8),
                obv=to_decimal_or_none(row["obv"]),
                obv_slope_5=to_decimal_or_none(row["obv_slope_5"], scale=8),
                dollar_volume_ratio_20=to_decimal_or_none(
                    row["dollar_volume_ratio_20"],
                    scale=8,
                ),
                price_vs_ema20=to_decimal_or_none(row["price_vs_ema20"], scale=8),
                price_vs_ema50=to_decimal_or_none(row["price_vs_ema50"], scale=8),
                atr_pct=to_decimal_or_none(row["atr_pct"], scale=8),
                ema_spread=to_decimal_or_none(row["ema_spread"]),
                ema_spread_pct=to_decimal_or_none(row["ema_spread_pct"], scale=8),
            )
        )

    return rows


def upsert_feature_rows(conn, rows: list[FeatureRow]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO feat_candle (
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
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        asset_id = VALUES(asset_id),
        venue = VALUES(venue),
        interval_code = VALUES(interval_code),
        close_ts_utc = VALUES(close_ts_utc),
        ema_20 = VALUES(ema_20),
        ema_50 = VALUES(ema_50),
        rsi_14 = VALUES(rsi_14),
        atr_14 = VALUES(atr_14),
        volume_ratio_20 = VALUES(volume_ratio_20),
        volume_zscore_20 = VALUES(volume_zscore_20),
        obv = VALUES(obv),
        obv_slope_5 = VALUES(obv_slope_5),
        dollar_volume_ratio_20 = VALUES(dollar_volume_ratio_20),
        price_vs_ema20 = VALUES(price_vs_ema20),
        price_vs_ema50 = VALUES(price_vs_ema50),
        atr_pct = VALUES(atr_pct),
        ema_spread = VALUES(ema_spread),
        ema_spread_pct = VALUES(ema_spread_pct)
    """

    data = [
        (
            row.candle_id,
            row.asset_id,
            row.venue,
            row.interval_code,
            _db_ts(row.close_ts_utc),
            None if row.ema_20 is None else str(row.ema_20),
            None if row.ema_50 is None else str(row.ema_50),
            None if row.rsi_14 is None else str(row.rsi_14),
            None if row.atr_14 is None else str(row.atr_14),
            None if row.volume_ratio_20 is None else str(row.volume_ratio_20),
            None if row.volume_zscore_20 is None else str(row.volume_zscore_20),
            None if row.obv is None else str(row.obv),
            None if row.obv_slope_5 is None else str(row.obv_slope_5),
            None if row.dollar_volume_ratio_20 is None else str(row.dollar_volume_ratio_20),
            None if row.price_vs_ema20 is None else str(row.price_vs_ema20),
            None if row.price_vs_ema50 is None else str(row.price_vs_ema50),
            None if row.atr_pct is None else str(row.atr_pct),
            None if row.ema_spread is None else str(row.ema_spread),
            None if row.ema_spread_pct is None else str(row.ema_spread_pct),
        )
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, data)

    conn.commit()
    return len(rows)


def run_feat_candle_for_asset_interval(
    conn,
    asset_id: int,
    venue: str,
    interval_code: str,
    *,
    write_start_ts_utc: datetime | None = None,
    write_end_ts_utc: datetime | None = None,
    warmup_bars: int = 300,
) -> int:
    source_start_ts_utc = None

    if write_start_ts_utc is not None:
        source_start_ts_utc = _normalize_utc(write_start_ts_utc) - (
            _interval_delta(interval_code) * warmup_bars
        )

    df = load_candles(
        conn=conn,
        asset_id=asset_id,
        venue=venue,
        interval_code=interval_code,
        source_start_ts_utc=source_start_ts_utc,
        source_end_ts_utc=write_end_ts_utc,
    )

    if df.empty:
        return 0

    feat_df = compute_features(df)
    write_df = filter_write_window(
        feat_df,
        write_start_ts_utc=write_start_ts_utc,
        write_end_ts_utc=write_end_ts_utc,
    )

    rows = dataframe_to_feature_rows(write_df)
    return upsert_feature_rows(conn, rows)
