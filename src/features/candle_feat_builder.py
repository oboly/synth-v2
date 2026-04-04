from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


REQUIRED_COLUMNS: tuple[str, ...] = (
    "market",
    "interval",
    "start_ts",
    "end_ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "is_final",
)


@dataclass(frozen=True)
class CandleFeatureConfig:
    group_cols: Sequence[str] = ("market", "interval")
    sma_windows: Sequence[int] = (20, 50)
    ema_windows: Sequence[int] = (20, 50)
    atr_window: int = 14
    volume_sma_window: int = 20
    momentum_fast_window: int = 20
    momentum_slow_window: int = 50
    final_only: bool = True


def build_candle_features(
    df: pd.DataFrame,
    config: CandleFeatureConfig | None = None,
) -> pd.DataFrame:
    """
    Build V1.1 candle features for Synth v2.

    Input columns:
    - market, interval, start_ts, end_ts, open, high, low, close, volume, is_final

    Output:
    - Same DataFrame with additional feature columns.

    Notes:
    - If config.final_only is True, rolling features are computed from final candles only.
    - The returned DataFrame still preserves the full row set.
    """
    cfg = config or CandleFeatureConfig()

    out = df.copy()
    _validate_required_columns(out)
    out = _normalize_dtypes(out)
    out = _sort_for_rolling(out, cfg)

    out = _add_structure_features(out)
    out = _add_trend_features(out, cfg)
    out = _add_volatility_features(out, cfg)
    out = _add_volume_features(out, cfg)
    out = _add_breakout_features(out, cfg)

    return out


def _validate_required_columns(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _normalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["market"] = out["market"].astype("string").str.strip()
    out["interval"] = out["interval"].astype("string").str.strip()

    out["start_ts"] = pd.to_datetime(out["start_ts"], utc=True, errors="raise")
    out["end_ts"] = pd.to_datetime(out["end_ts"], utc=True, errors="raise")

    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="raise").astype(float)

    out["is_final"] = out["is_final"].astype(bool)

    if (out["start_ts"] >= out["end_ts"]).any():
        raise ValueError("Invalid rows found where start_ts >= end_ts")

    return out


def _sort_for_rolling(df: pd.DataFrame, cfg: CandleFeatureConfig) -> pd.DataFrame:
    return df.sort_values(list(cfg.group_cols) + ["start_ts"], kind="mergesort").reset_index(drop=True)


def _groupby(df: pd.DataFrame, cfg: CandleFeatureConfig):
    return df.groupby(list(cfg.group_cols), sort=False, group_keys=False)


def _feature_source_frame(df: pd.DataFrame, cfg: CandleFeatureConfig) -> pd.DataFrame:
    if not cfg.final_only:
        return df.copy()
    return df.loc[df["is_final"]].copy()


def _merge_features_back(
    base_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    cfg: CandleFeatureConfig,
    feature_cols: Sequence[str],
) -> pd.DataFrame:
    join_cols = list(cfg.group_cols) + ["start_ts"]

    merged = base_df.merge(
        feature_df[join_cols + list(feature_cols)],
        on=join_cols,
        how="left",
        sort=False,
    )
    return merged


def _add_structure_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["body_size"] = (out["close"] - out["open"]).abs()
    out["upper_wick"] = out["high"] - np.maximum(out["open"], out["close"])
    out["lower_wick"] = np.minimum(out["open"], out["close"]) - out["low"]
    out["is_bullish"] = out["close"] > out["open"]
    out["is_bearish"] = out["close"] < out["open"]

    return out


def _add_trend_features(df: pd.DataFrame, cfg: CandleFeatureConfig) -> pd.DataFrame:
    source = _feature_source_frame(df, cfg)
    g = _groupby(source, cfg)

    feature_cols: list[str] = []

    for window in cfg.sma_windows:
        col = f"sma_{window}"
        source[col] = g["close"].transform(
            lambda s: s.rolling(window=window, min_periods=window).mean()
        )
        feature_cols.append(col)

    for window in cfg.ema_windows:
        col = f"ema_{window}"
        source[col] = g["close"].transform(
            lambda s: s.ewm(span=window, adjust=False, min_periods=window).mean()
        )
        feature_cols.append(col)

    return _merge_features_back(df, source, cfg, feature_cols)


def _add_volatility_features(df: pd.DataFrame, cfg: CandleFeatureConfig) -> pd.DataFrame:
    source = _feature_source_frame(df, cfg)
    g = _groupby(source, cfg)

    prev_close = g["close"].shift(1)

    tr_hl = (source["high"] - source["low"]).abs()
    tr_hc = (source["high"] - prev_close).abs()
    tr_lc = (source["low"] - prev_close).abs()

    source["true_range"] = pd.concat([tr_hl, tr_hc, tr_lc], axis=1).max(axis=1)

    atr_col = f"atr_{cfg.atr_window}"
    source[atr_col] = g["true_range"].transform(
        lambda s: s.rolling(window=cfg.atr_window, min_periods=cfg.atr_window).mean()
    )

    close_safe = source["close"].replace(0.0, np.nan)
    source["range_pct"] = ((source["high"] - source["low"]) / close_safe).replace(
        [np.inf, -np.inf],
        np.nan,
    )

    source = source.drop(columns=["true_range"])

    return _merge_features_back(df, source, cfg, [atr_col, "range_pct"])


def _add_volume_features(df: pd.DataFrame, cfg: CandleFeatureConfig) -> pd.DataFrame:
    source = _feature_source_frame(df, cfg)
    g = _groupby(source, cfg)

    volume_sma_col = f"volume_sma_{cfg.volume_sma_window}"
    volume_ratio_col = f"volume_ratio_{cfg.volume_sma_window}"

    source[volume_sma_col] = g["volume"].transform(
        lambda s: s.rolling(
            window=cfg.volume_sma_window,
            min_periods=cfg.volume_sma_window,
        ).mean()
    )

    denom = source[volume_sma_col].replace(0.0, np.nan)
    source[volume_ratio_col] = (source["volume"] / denom).replace(
        [np.inf, -np.inf],
        np.nan,
    )

    return _merge_features_back(df, source, cfg, [volume_sma_col, volume_ratio_col])


def _add_breakout_features(df: pd.DataFrame, cfg: CandleFeatureConfig) -> pd.DataFrame:
    out = df.copy()

    out["close_above_sma20"] = out["close"] > out["sma_20"]
    out["close_above_sma50"] = out["close"] > out["sma_50"]

    sma_fast_col = f"sma_{cfg.momentum_fast_window}"
    sma_slow_col = f"sma_{cfg.momentum_slow_window}"

    slow_safe = out[sma_slow_col].replace(0.0, np.nan)
    out["momentum_score"] = ((out[sma_fast_col] - out[sma_slow_col]) / slow_safe).replace(
        [np.inf, -np.inf],
        np.nan,
    )

    return out
