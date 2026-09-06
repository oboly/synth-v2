"""Research-only OHLCV effort-vs-result exhaustion proxy for Issue #306.

The model is deliberately a candle/volume proxy. It does not represent true
aggressor flow, buy/sell delta, CVD, taker imbalance, or order-book absorption.
Candidate thresholds are provisional research thresholds for Phase C
validation only and carry no selection, permission, or execution authority.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import numpy as np
import pandas as pd

from src.features.candle_feat_builder import CandleFeatureConfig, build_candle_features

MODEL_ID: Final[str] = "momentum_flow_exhaustion_candidate"
MODEL_VERSION: Final[str] = "1.0-research"
ATR_WINDOW: Final[int] = 14
VOLUME_WINDOW: Final[int] = 20
PROGRESS_LOOKBACK: Final[int] = 5
MIN_WARMUP_BARS: Final[int] = 20
SUPPORTED_INTERVALS: Final[frozenset[str]] = frozenset({"15m", "1h", "4h", "1d", "1w"})
DEVELOPING_THRESHOLD: Final[float] = 45.0
CONFIRMED_THRESHOLD: Final[float] = 70.0
STATE_NONE: Final[str] = "NONE"
STATE_DEVELOPING: Final[str] = "DEVELOPING"
STATE_CONFIRMED: Final[str] = "CONFIRMED"
STATE_INSUFFICIENT: Final[str] = "INSUFFICIENT_DATA"


class ExhaustionCandidateInputError(ValueError):
    """Raised when market-candle input cannot be interpreted safely."""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _validate_scope(frame: pd.DataFrame) -> None:
    required = {"market", "interval", "start_ts", "end_ts", "open", "high", "low", "close", "volume", "is_final"}
    missing = required.difference(frame.columns)
    if missing:
        raise ExhaustionCandidateInputError(f"input missing columns: {sorted(missing)}")
    if frame.empty:
        return
    if len(set(frame["market"].astype(str))) != 1:
        raise ExhaustionCandidateInputError("candidate input must contain exactly one market")
    intervals = set(frame["interval"].astype(str))
    if len(intervals) != 1:
        raise ExhaustionCandidateInputError("candidate input must contain exactly one interval")
    interval = next(iter(intervals))
    if interval not in SUPPORTED_INTERVALS:
        raise ExhaustionCandidateInputError(f"unsupported interval: {interval}")


def _state(score: float) -> str:
    if score >= CONFIRMED_THRESHOLD:
        return STATE_CONFIRMED
    if score >= DEVELOPING_THRESHOLD:
        return STATE_DEVELOPING
    return STATE_NONE


def _reason_codes(
    *,
    side: str,
    effort: float,
    inefficiency: float,
    rejection: float,
    extension_failure: float,
) -> tuple[str, ...]:
    codes: list[str] = []
    prefix = side.upper()
    if effort >= 0.50:
        codes.append(f"{prefix}_HIGH_PARTICIPATION_PROXY")
    if inefficiency >= 0.60:
        codes.append(f"{prefix}_POOR_PRICE_EFFICIENCY")
    if rejection >= 0.50:
        codes.append(f"{prefix}_REJECTION_GEOMETRY")
    if extension_failure >= 0.60:
        codes.append(f"{prefix}_WEAK_EXTENSION_PROGRESS")
    return tuple(codes)


def build_exhaustion_candidate(
    candles: pd.DataFrame,
    *,
    asof_ts_utc: datetime,
) -> pd.DataFrame:
    """Build one deterministic point-in-time exhaustion candidate row.

    Future rows are removed before validation and rolling feature construction.
    Only finalized candles at or before ``asof_ts_utc`` participate.
    """
    if candles.empty:
        return pd.DataFrame()

    asof = pd.Timestamp(_utc(asof_ts_utc))
    source = candles.copy()
    if "end_ts" not in source.columns:
        raise ExhaustionCandidateInputError("input missing columns: ['end_ts']")
    source["end_ts"] = pd.to_datetime(source["end_ts"], utc=True, errors="raise")
    source = source.loc[source["end_ts"] <= asof].copy()
    if source.empty:
        return pd.DataFrame()
    _validate_scope(source)
    source = source.loc[source["is_final"].astype(bool)].copy()
    source = source.sort_values("start_ts", kind="mergesort").reset_index(drop=True)
    if source.empty:
        return pd.DataFrame()

    base = {
        "market": str(source.iloc[-1]["market"]),
        "interval": str(source.iloc[-1]["interval"]),
        "asof_ts_utc": asof,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "candidate_thresholds_version": "phase_b_v1_uncalibrated",
    }

    if len(source) < MIN_WARMUP_BARS:
        return pd.DataFrame([{**base, "exhaustion_state": STATE_INSUFFICIENT, "exhaustion_side": "NONE", "reason_codes": ("INSUFFICIENT_WARMUP",)}])

    featured = build_candle_features(
        source,
        CandleFeatureConfig(
            atr_window=ATR_WINDOW,
            volume_sma_window=VOLUME_WINDOW,
            final_only=True,
        ),
    )
    row = featured.iloc[-1]
    prev = featured.iloc[-2]
    atr = float(row[f"atr_{ATR_WINDOW}"])
    candle_range = float(row["high"] - row["low"])
    volume_ratio = float(row[f"volume_ratio_{VOLUME_WINDOW}"])

    if not np.isfinite(atr) or atr <= 0.0 or not np.isfinite(candle_range) or candle_range <= 0.0 or not np.isfinite(volume_ratio):
        return pd.DataFrame([{**base, "exhaustion_state": STATE_INSUFFICIENT, "exhaustion_side": "NONE", "reason_codes": ("INVALID_OR_INCOMPLETE_GEOMETRY",)}])

    close = float(row["close"])
    open_price = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    prev_close = float(prev["close"])

    directional_price_progress_atr = (close - prev_close) / atr
    range_efficiency = abs(close - open_price) / candle_range
    close_progress_fraction = (close - open_price) / candle_range
    close_position = (close - low) / candle_range
    upper_wick_fraction = max(0.0, high - max(open_price, close)) / candle_range
    lower_wick_fraction = max(0.0, min(open_price, close) - low) / candle_range

    prior = featured.iloc[max(0, len(featured) - 1 - PROGRESS_LOOKBACK):-1]
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    new_high_progress_atr = max(0.0, high - prior_high) / atr
    new_low_progress_atr = max(0.0, prior_low - low) / atr

    normalized_effort = _clip01((volume_ratio - 1.0) / 1.0)
    positive_progress = max(0.0, directional_price_progress_atr)
    negative_progress = max(0.0, -directional_price_progress_atr)
    buy_efficiency_proxy = positive_progress / max(volume_ratio, 1.0)
    sell_efficiency_proxy = negative_progress / max(volume_ratio, 1.0)

    buy_inefficiency = _clip01(1.0 - positive_progress / 0.75)
    sell_inefficiency = _clip01(1.0 - negative_progress / 0.75)
    buy_rejection = _clip01((upper_wick_fraction + (1.0 - close_position)) / 1.0)
    sell_rejection = _clip01((lower_wick_fraction + close_position) / 1.0)
    buy_extension_failure = _clip01(1.0 - new_high_progress_atr / 0.50)
    sell_extension_failure = _clip01(1.0 - new_low_progress_atr / 0.50)

    buy_attempt_proxy = max(
        upper_wick_fraction,
        _clip01(new_high_progress_atr / 0.50),
        _clip01(positive_progress / 0.75),
    )
    sell_attempt_proxy = max(
        lower_wick_fraction,
        _clip01(new_low_progress_atr / 0.50),
        _clip01(negative_progress / 0.75),
    )
    buyer_exhaustion_score = 100.0 * normalized_effort * buy_attempt_proxy * (
        0.45 * buy_inefficiency + 0.35 * buy_rejection + 0.20 * buy_extension_failure
    )
    seller_exhaustion_score = 100.0 * normalized_effort * sell_attempt_proxy * (
        0.45 * sell_inefficiency + 0.35 * sell_rejection + 0.20 * sell_extension_failure
    )
    absorption_score_proxy = 100.0 * normalized_effort * _clip01(1.0 - abs(directional_price_progress_atr) / 0.50)

    buyer_state = _state(buyer_exhaustion_score)
    seller_state = _state(seller_exhaustion_score)
    buyer_reasons = _reason_codes(
        side="BUYER", effort=normalized_effort, inefficiency=buy_inefficiency,
        rejection=buy_rejection, extension_failure=buy_extension_failure,
    )
    seller_reasons = _reason_codes(
        side="SELLER", effort=normalized_effort, inefficiency=sell_inefficiency,
        rejection=sell_rejection, extension_failure=sell_extension_failure,
    )
    if buyer_exhaustion_score >= seller_exhaustion_score:
        exhaustion_side = "BUYER"
        exhaustion_state = buyer_state
        reasons = buyer_reasons
    else:
        exhaustion_side = "SELLER"
        exhaustion_state = seller_state
        reasons = seller_reasons
    if exhaustion_state == STATE_NONE:
        exhaustion_side = "NONE"

    result = {
        **base,
        "directional_price_progress_atr": directional_price_progress_atr,
        "range_efficiency": range_efficiency,
        "close_progress_fraction": close_progress_fraction,
        "new_high_progress_atr": new_high_progress_atr,
        "new_low_progress_atr": new_low_progress_atr,
        "volume_ratio_20": volume_ratio,
        "upper_wick_fraction": upper_wick_fraction,
        "lower_wick_fraction": lower_wick_fraction,
        "close_position": close_position,
        "buy_efficiency_proxy": buy_efficiency_proxy,
        "sell_efficiency_proxy": sell_efficiency_proxy,
        "buy_attempt_proxy": buy_attempt_proxy,
        "sell_attempt_proxy": sell_attempt_proxy,
        "buyer_exhaustion_score": buyer_exhaustion_score,
        "seller_exhaustion_score": seller_exhaustion_score,
        "absorption_score_proxy": absorption_score_proxy,
        "buyer_exhaustion_state": buyer_state,
        "seller_exhaustion_state": seller_state,
        "exhaustion_state": exhaustion_state,
        "exhaustion_side": exhaustion_side,
        "buyer_reason_codes": buyer_reasons,
        "seller_reason_codes": seller_reasons,
        "reason_codes": reasons,
    }
    return pd.DataFrame([result])
