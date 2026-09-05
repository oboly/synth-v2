"""Research-only point-in-time MA/volume candidate features for Issue #310.

This module prepares raw numeric/categorical-free candidate measurements for
historical validation. It deliberately does not classify trend state, set
thresholds, assign colors, rank assets, or create trading authority.

Existing canonical primitives are reused through ``candle_feat_builder``.
SMA150/SMA200 are requested through its generic ``sma_windows`` contract and
``volume_ratio_20`` is consumed directly. No parallel MA or volume-ratio
implementation is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import numpy as np
import pandas as pd

from src.features.candle_feat_builder import CandleFeatureConfig, build_candle_features

MODEL_ID: Final[str] = "ma_volume_candidate_features"
MODEL_VERSION: Final[str] = "1.0"
INPUT_INTERVAL: Final[str] = "4h"
SMA_WINDOWS: Final[tuple[int, ...]] = (20, 50, 150, 200)
VOLUME_WINDOW: Final[int] = 20
DEFAULT_SLOPE_BARS: Final[int] = 6


class MAVolumeCandidateInputError(ValueError):
    """Raised when candidate feature inputs cannot be interpreted safely."""


@dataclass(frozen=True)
class MAVolumeCandidateContractV1:
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION
    input_interval: str = INPUT_INTERVAL
    sma_windows: tuple[int, ...] = SMA_WINDOWS
    volume_window: int = VOLUME_WINDOW
    slope_bars: int = DEFAULT_SLOPE_BARS


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _validate_scope(frame: pd.DataFrame, *, interval_code: str) -> None:
    if interval_code != INPUT_INTERVAL:
        raise MAVolumeCandidateInputError(f"unsupported input interval: {interval_code}")
    if frame.empty:
        return
    if "market" not in frame.columns or "interval" not in frame.columns:
        raise MAVolumeCandidateInputError("input must contain market and interval")
    markets = set(frame["market"].astype(str))
    intervals = set(frame["interval"].astype(str))
    if len(markets) != 1:
        raise MAVolumeCandidateInputError("candidate frame must contain exactly one market")
    if intervals != {INPUT_INTERVAL}:
        raise MAVolumeCandidateInputError("candidate frame contains wrong interval")


def build_candidate_frame(
    candles: pd.DataFrame,
    *,
    asof_ts_utc: datetime,
    interval_code: str = INPUT_INTERVAL,
    slope_bars: int = DEFAULT_SLOPE_BARS,
) -> pd.DataFrame:
    """Build replay-safe raw candidate measurements at or before ``asof``.

    The caller supplies the evaluation boundary explicitly. Future candles are
    removed before any rolling feature is calculated, preventing future-data
    leakage. The function returns the full point-in-time feature frame up to the
    boundary so downstream research can construct labels without recomputing the
    feature family.
    """
    if slope_bars <= 0:
        raise MAVolumeCandidateInputError("slope_bars must be positive")
    _validate_scope(candles, interval_code=interval_code)
    if candles.empty:
        return pd.DataFrame()

    asof = pd.Timestamp(_utc(asof_ts_utc))
    source = candles.copy()
    source["start_ts"] = pd.to_datetime(source["start_ts"], utc=True, errors="raise")
    source["end_ts"] = pd.to_datetime(source["end_ts"], utc=True, errors="raise")
    source = source.loc[source["end_ts"] <= asof].copy()
    if source.empty:
        return pd.DataFrame()

    featured = build_candle_features(
        source,
        CandleFeatureConfig(
            group_cols=("market", "interval"),
            sma_windows=SMA_WINDOWS,
            ema_windows=(20, 50),
            volume_sma_window=VOLUME_WINDOW,
            final_only=True,
        ),
    )

    close_safe = featured["close"].replace(0.0, np.nan)
    for window in (50, 150, 200):
        sma_col = f"sma_{window}"
        featured[f"close_vs_sma{window}_pct"] = (
            (featured["close"] - featured[sma_col]) / close_safe * 100.0
        ).replace([np.inf, -np.inf], np.nan)
        featured[f"sma{window}_slope_pct_{slope_bars}b"] = (
            featured[sma_col] / featured[sma_col].shift(slope_bars) - 1.0
        ).replace([np.inf, -np.inf], np.nan) * 100.0

    featured["bullish_ma_stack"] = (
        (featured["sma_50"] > featured["sma_150"])
        & (featured["sma_150"] > featured["sma_200"])
    ).where(
        featured[["sma_50", "sma_150", "sma_200"]].notna().all(axis=1)
    )

    featured["candidate_model_id"] = MODEL_ID
    featured["candidate_model_version"] = MODEL_VERSION
    featured["candidate_slope_bars"] = int(slope_bars)
    featured["candidate_asof_ts_utc"] = asof

    keep = [
        "market",
        "interval",
        "start_ts",
        "end_ts",
        "close",
        "sma_50",
        "sma_150",
        "sma_200",
        "close_vs_sma50_pct",
        "close_vs_sma150_pct",
        "close_vs_sma200_pct",
        f"sma50_slope_pct_{slope_bars}b",
        f"sma150_slope_pct_{slope_bars}b",
        f"sma200_slope_pct_{slope_bars}b",
        "bullish_ma_stack",
        f"volume_ratio_{VOLUME_WINDOW}",
        "candidate_model_id",
        "candidate_model_version",
        "candidate_slope_bars",
        "candidate_asof_ts_utc",
    ]
    return featured.loc[:, keep].reset_index(drop=True)
