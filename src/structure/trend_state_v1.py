from __future__ import annotations

"""Canonical deterministic trend-state classification from candle features."""

from decimal import Decimal
from typing import Any, Mapping


ENGINE_NAME = "structure_state_engine"
ENGINE_VERSION = "1.2"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def compute_trend_state(row: Mapping[str, Any]) -> tuple[str, Decimal]:
    """Classify the adopted structure trend from persisted EMA feature inputs."""
    p20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0
    p50 = float(row["price_vs_ema50"]) if row["price_vs_ema50"] is not None else 0.0
    spread = float(row["ema_spread_pct"]) if row["ema_spread_pct"] is not None else 0.0

    bullish_score = (
        0.40 * _clamp((spread + 0.02) / 0.04)
        + 0.30 * _clamp((p20 + 0.03) / 0.06)
        + 0.30 * _clamp((p50 + 0.05) / 0.10)
    )

    if p20 > 0 and p50 > 0 and spread >= 0.01:
        return "UPTREND_STRONG", Decimal(str(round(bullish_score, 6)))

    if p50 > 0:
        return "UPTREND_WEAK", Decimal(str(round(bullish_score, 6)))

    if abs(p20) < 0.01 and abs(spread) < 0.005:
        return "RANGE", Decimal(str(round(bullish_score, 6)))

    if p20 < 0 and p50 < 0 and spread <= -0.01:
        return "DOWNTREND_STRONG", Decimal(str(round(1.0 - bullish_score, 6)))

    if p50 < 0:
        return "DOWNTREND_WEAK", Decimal(str(round(1.0 - bullish_score, 6)))

    return "RANGE", Decimal(str(round(bullish_score, 6)))
