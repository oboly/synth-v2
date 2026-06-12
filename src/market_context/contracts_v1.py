from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "FibMapState",
    "FibMapConfidence",
    "NavigationRegime",
    "BreathlineState",
    "ImpulseHealthState",
    "TimingState",
    "FreshnessState",
    "MarketNavigationState",
]


class FibMapState(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    EXHAUSTED = "EXHAUSTED"
    FALLBACK = "FALLBACK"
    EMERGENCY_REBUILT = "EMERGENCY_REBUILT"
    NO_DATA = "NO_DATA"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class FibMapConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class NavigationRegime(StrEnum):
    NO_DATA = "NO_DATA"
    STALE = "STALE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"
    TRANSITION = "TRANSITION"


class BreathlineState(StrEnum):
    NO_DATA = "NO_DATA"
    STALE = "STALE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    ABOVE_BREATHLINE = "ABOVE_BREATHLINE"
    TESTING_BREATHLINE = "TESTING_BREATHLINE"
    BELOW_BREATHLINE = "BELOW_BREATHLINE"
    RECLAIMING_BREATHLINE = "RECLAIMING_BREATHLINE"
    EXTENDED_ABOVE_BREATHLINE = "EXTENDED_ABOVE_BREATHLINE"
    SPIKE_COOLING = "SPIKE_COOLING"


class ImpulseHealthState(StrEnum):
    NO_DATA = "NO_DATA"
    STALE = "STALE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    HEALTHY_IMPULSE = "HEALTHY_IMPULSE"
    EARLY_IMPULSE = "EARLY_IMPULSE"
    EXTENDED_IMPULSE = "EXTENDED_IMPULSE"
    BLOW_OFF_SPIKE = "BLOW_OFF_SPIKE"
    DISTRIBUTION_RISK = "DISTRIBUTION_RISK"
    COOLING_PULLBACK = "COOLING_PULLBACK"
    SECOND_BUMP_POSSIBLE = "SECOND_BUMP_POSSIBLE"
    FAILED_RECLAIM = "FAILED_RECLAIM"


class TimingState(StrEnum):
    NO_DATA = "NO_DATA"
    STALE = "STALE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    WAIT_FOR_BREAKOUT = "WAIT_FOR_BREAKOUT"
    WAIT_FOR_RECLAIM = "WAIT_FOR_RECLAIM"
    RECLAIM_CONFIRMED = "RECLAIM_CONFIRMED"
    BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
    PULLBACK_ENTRY_ZONE = "PULLBACK_ENTRY_ZONE"
    NO_CHASE_EXTENDED = "NO_CHASE_EXTENDED"
    TOO_LATE = "TOO_LATE"
    FAILED_RECLAIM = "FAILED_RECLAIM"


class FreshnessState(StrEnum):
    NO_DATA = "NO_DATA"
    STALE = "STALE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    FRESH = "FRESH"


@dataclass(frozen=True)
class MarketNavigationState:
    symbol: str
    navigation_regime: NavigationRegime
    fib_map_state: FibMapState
    fib_map_confidence: FibMapConfidence
    breathline_state: BreathlineState
    impulse_health_state: ImpulseHealthState
    timing_state: TimingState
    freshness_state: FreshnessState
    warnings: tuple[str, ...]
    computed_at_utc: str        # ISO-8601 UTC string — JSON-safe without custom serializer
