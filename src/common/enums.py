from __future__ import annotations

from enum import StrEnum


class PhaseLabel(StrEnum):
    EXPANSION = "expansion"
    COMPRESSION = "compression"
    DISTRIBUTION = "distribution"
    REVERSAL_RISK = "reversal_risk"
    ACCUMULATION = "accumulation"
    MARKUP = "markup"
    MARKDOWN = "markdown"
    UNCLEAR = "unclear"


class DirectionLabel(StrEnum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


class MagnitudeLabel(StrEnum):
    MODEST = "modest"
    STRONG = "strong"
    EXPLOSIVE = "explosive"
    NONE = "none"
    UNCLEAR = "unclear"


class ConfidenceLabel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PredictionStatus(StrEnum):
    OPEN = "open"
    EXPIRED = "expired"
    SCORED = "scored"
    CANCELLED = "cancelled"
