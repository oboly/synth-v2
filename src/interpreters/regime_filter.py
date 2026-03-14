# =============================================================================
# File: regime.py
# Project: The One Synthesizer
# Purpose: Daily (1D) regime filter (RISK_ON / RISK_OFF / TRANSITION)
# Time standard: UTC only. All timestamps are expected to be tz-aware UTC.
# Interval convention: [start_ts, end_ts) where applicable.
# Boundary: PURE — no I/O, no network, no DB. Deterministic given inputs.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Regime(str, Enum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    TRANSITION = "TRANSITION"


@dataclass(frozen=True)
class RegimeConfig:
    ma200_len: int = 200
    slope_lookback: int = 20          # approx 1 month of trading days on 1D
    min_bars: int = 260               # ensure enough data for MA200 + slope
    use_ma50: bool = False
    ma50_len: int = 50


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    close: float
    ma200: float
    slope200: float
    ma50: Optional[float] = None


# ------------------------------- indicators ----------------------------------


def sma(series: pd.Series, length: int) -> pd.Series:
    if length <= 0:
        raise ValueError("length must be > 0")
    return series.rolling(window=length, min_periods=length).mean()


def ensure_utc_index(df: pd.DataFrame) -> None:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame index must be a pandas DatetimeIndex")
    if df.index.tz is None:
        raise ValueError("DatetimeIndex must be tz-aware (UTC expected)")
    if str(df.index.tz) != "UTC":
        raise ValueError("DatetimeIndex must be UTC tz-aware")


# ------------------------------- core logic ----------------------------------


def compute_daily_regime(
    ohlcv_1d: pd.DataFrame,
    cfg: RegimeConfig = RegimeConfig(),
) -> RegimeResult:
    """
    Expects columns: ['open','high','low','close','volume'].
    Index: tz-aware UTC DatetimeIndex (candle close timestamps recommended).
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(ohlcv_1d.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    ensure_utc_index(ohlcv_1d)

    if len(ohlcv_1d) < cfg.min_bars:
        raise ValueError(f"Need at least {cfg.min_bars} 1D bars; got {len(ohlcv_1d)}")

    close = ohlcv_1d["close"].astype("float64")

    ma200 = sma(close, cfg.ma200_len)
    # slope defined as MA200_now - MA200_lookback
    slope200 = ma200 - ma200.shift(cfg.slope_lookback)

    if cfg.use_ma50:
        ma50 = sma(close, cfg.ma50_len)
        ma50_last = float(ma50.iloc[-1])
    else:
        ma50 = None
        ma50_last = None

    c_last = float(close.iloc[-1])
    ma200_last = float(ma200.iloc[-1])
    slope_last = float(slope200.iloc[-1])

    # Regime decision
    if (c_last > ma200_last) and (slope_last > 0):
        reg = Regime.RISK_ON
    elif (c_last < ma200_last) and (slope_last < 0):
        reg = Regime.RISK_OFF
    else:
        reg = Regime.TRANSITION

    return RegimeResult(
        regime=reg,
        close=c_last,
        ma200=ma200_last,
        slope200=slope_last,
        ma50=ma50_last,
    )
