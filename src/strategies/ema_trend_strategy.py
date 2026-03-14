# =============================================================================
# File: signals.py
# Project: The One Synthesizer
# Purpose: 4H signal layer (trend-follow long, bear rally short, reclaim long)
# Time standard: UTC only. All timestamps are expected to be tz-aware UTC.
# Interval convention: [start_ts, end_ts) where applicable.
# Boundary: PURE — no I/O, no network, no DB. Deterministic given inputs.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Literal

import pandas as pd

from regime import Regime, RegimeResult, ensure_utc_index


Side = Literal["LONG", "SHORT"]


class SignalType(str, Enum):
    TREND_LONG = "TREND_LONG"             # Setup A
    BEAR_RALLY_SHORT = "BEAR_RALLY_SHORT" # Setup B
    RECLAIM_LONG = "RECLAIM_LONG"         # Setup C


@dataclass(frozen=True)
class SignalConfig4H:
    # EMA lengths
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200

    # Volume confirmation
    vol_sma_len: int = 20
    vol_mult_trend: float = 1.2
    vol_mult_reclaim: float = 1.5

    # ATR for stops
    atr_len: int = 14
    atr_mult_stop: float = 1.0

    # Liquidity filter
    vol_min_mult: float = 0.5  # if vol < vol_min_mult * vol_sma => skip

    # Minimum bars
    min_bars: int = 300


@dataclass(frozen=True)
class Signal:
    ts: pd.Timestamp
    signal_type: SignalType
    side: Side
    entry: float
    stop: float
    reason: str


# ------------------------------- indicators ----------------------------------


def ema(series: pd.Series, length: int) -> pd.Series:
    if length <= 0:
        raise ValueError("length must be > 0")
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    if length <= 0:
        raise ValueError("length must be > 0")
    return series.rolling(window=length, min_periods=length).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def atr(ohlcv: pd.DataFrame, length: int) -> pd.Series:
    tr = true_range(ohlcv["high"], ohlcv["low"], ohlcv["close"])
    return tr.rolling(window=length, min_periods=length).mean()


def _required_cols_check(df: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")


# ------------------------------- candle utils --------------------------------


def is_bullish(df: pd.DataFrame, i: int) -> bool:
    return float(df["close"].iloc[i]) > float(df["open"].iloc[i])


def is_bearish(df: pd.DataFrame, i: int) -> bool:
    return float(df["close"].iloc[i]) < float(df["open"].iloc[i])


def upper_wick_ratio(df: pd.DataFrame, i: int) -> float:
    o = float(df["open"].iloc[i])
    c = float(df["close"].iloc[i])
    h = float(df["high"].iloc[i])
    body_top = max(o, c)
    candle_range = max(h - float(df["low"].iloc[i]), 1e-12)
    return (h - body_top) / candle_range


def lower_wick_ratio(df: pd.DataFrame, i: int) -> float:
    o = float(df["open"].iloc[i])
    c = float(df["close"].iloc[i])
    l = float(df["low"].iloc[i])
    body_bot = min(o, c)
    candle_range = max(float(df["high"].iloc[i]) - l, 1e-12)
    return (body_bot - l) / candle_range


# ------------------------------- core signals --------------------------------


def generate_signals_4h(
    ohlcv_4h: pd.DataFrame,
    daily_regime: RegimeResult,
    cfg: SignalConfig4H = SignalConfig4H(),
) -> list[Signal]:
    """
    Returns signals on the *latest* closed 4h bar only (one-shot).
    If you want a full backtest stream, call this in a loop or vectorize later.
    """
    _required_cols_check(ohlcv_4h)
    ensure_utc_index(ohlcv_4h)

    if len(ohlcv_4h) < cfg.min_bars:
        raise ValueError(f"Need at least {cfg.min_bars} 4h bars; got {len(ohlcv_4h)}")

    df = ohlcv_4h.copy()
    close = df["close"].astype("float64")
    vol = df["volume"].astype("float64")

    ema_fast = ema(close, cfg.ema_fast)
    ema_mid = ema(close, cfg.ema_mid)
    ema_slow = ema(close, cfg.ema_slow)

    vol_sma = sma(vol, cfg.vol_sma_len)
    atr14 = atr(df, cfg.atr_len)

    i = len(df) - 1
    ts = df.index[i]
    c = float(close.iloc[i])

    # Liquidity filter
    v = float(vol.iloc[i])
    v_avg = float(vol_sma.iloc[i])
    if pd.isna(v_avg) or v < cfg.vol_min_mult * v_avg:
        return []

    ef = float(ema_fast.iloc[i])
    em = float(ema_mid.iloc[i])
    es = float(ema_slow.iloc[i])
    a = float(atr14.iloc[i])

    signals: list[Signal] = []

    # ---- Setup A: Trend-follow long (allowed in RISK_ON, and in TRANSITION with stronger confirm) ----
    allow_trend_long = daily_regime.regime in (Regime.RISK_ON, Regime.TRANSITION)

    # "Break above ema_mid" on the latest candle
    prev_c = float(close.iloc[i - 1])
    prev_em = float(ema_mid.iloc[i - 1])

    broke_above_em = (prev_c <= prev_em) and (c > em)
    momentum_ok = ef > em

    vol_ok_trend = v > (cfg.vol_mult_trend * v_avg)
    vol_ok_trend_strict = v > (max(cfg.vol_mult_trend, cfg.vol_mult_reclaim) * v_avg)

    if allow_trend_long and broke_above_em and momentum_ok:
        vol_ok = vol_ok_trend if daily_regime.regime == Regime.RISK_ON else vol_ok_trend_strict
        if vol_ok:
            entry = c
            # stop: below ema_mid or swing low proxy (low of last 3 bars) minus ATR
            swing_low = float(df["low"].iloc[i - 2 : i + 1].min())
            stop = min(em, swing_low) - (cfg.atr_mult_stop * a)
            signals.append(
                Signal(
                    ts=ts,
                    signal_type=SignalType.TREND_LONG,
                    side="LONG",
                    entry=entry,
                    stop=stop,
                    reason="Trend long: break > EMA_mid with EMA_fast>EMA_mid and volume confirm.",
                )
            )

    # ---- Setup B: Bear-market rally short (only in RISK_OFF) ----
    if daily_regime.regime == Regime.RISK_OFF:
        # "rejection near ema_mid or ema_slow": upper wick + close below ema_mid after trading above it
        traded_above_em = float(df["high"].iloc[i]) > em
        reject = traded_above_em and (c < em) and (upper_wick_ratio(df, i) >= 0.35)
        bear_align = ef < em

        vol_ok_short = v > (cfg.vol_mult_trend * v_avg)

        if reject and bear_align and vol_ok_short and is_bearish(df, i):
            entry = c
            rejection_high = float(df["high"].iloc[i])
            stop = rejection_high + (cfg.atr_mult_stop * a)
            signals.append(
                Signal(
                    ts=ts,
                    signal_type=SignalType.BEAR_RALLY_SHORT,
                    side="SHORT",
                    entry=entry,
                    stop=stop,
                    reason="Bear rally short: rejection at EMA_mid with bearish alignment and volume.",
                )
            )

    # ---- Setup C: Reclaim long (TRANSITION only) ----
    if daily_regime.regime == Regime.TRANSITION:
        # close > ema_slow and bullish alignment
        reclaim = (c > es) and (ef > em)
        vol_ok_reclaim = v > (cfg.vol_mult_reclaim * v_avg)

        # Optional: require that previous bar was below ema_slow (actual reclaim)
        prev_es = float(ema_slow.iloc[i - 1])
        prev_below = prev_c <= prev_es

        if reclaim and prev_below and vol_ok_reclaim:
            entry = c
            swing_low = float(df["low"].iloc[i - 2 : i + 1].min())
            stop = min(em, swing_low) - (cfg.atr_mult_stop * a)
            signals.append(
                Signal(
                    ts=ts,
                    signal_type=SignalType.RECLAIM_LONG,
                    side="LONG",
                    entry=entry,
                    stop=stop,
                    reason="Reclaim long: close > EMA_slow with EMA_fast>EMA_mid and strong volume.",
                )
            )

    return signals
