from __future__ import annotations

from dataclasses import dataclass


RUNTIME_MARKET_BREATH_PHASES_V1 = (
    "INHALE_ACCUMULATION",
    "HOLD_COMPRESSION",
    "EXHALE_EXPANSION",
    "OVERBREATH_EXTENSION",
    "COLLAPSE_RESET",
    "NEUTRAL_TRANSITION",
    "INSUFFICIENT_DATA",
)

RUNTIME_MARKET_BREATH_STATES_V1 = (
    "FORMING",
    "CONFIRMED",
    "LATE",
    "RESET",
    "UNKNOWN",
)


@dataclass(frozen=True)
class MarketBreathThresholdProfileV1:
    collapse_reset_momentum_lt: float = -25.0
    collapse_reset_reversal_min: float = 45.0
    overbreath_expansion_min: float = 65.0
    overbreath_momentum_min: float = 55.0
    overbreath_reversal_min: float = 45.0
    exhale_expansion_min: float = 55.0
    exhale_momentum_gt: float = 20.0
    exhale_relative_strength_gt: float = 0.0
    exhale_confirmed_expansion_min: float = 70.0
    exhale_confirmed_momentum_min: float = 35.0
    hold_compression_min: float = 60.0
    hold_expansion_lt: float = 35.0
    hold_abs_momentum_max: float = 20.0
    hold_confirmed_compression_min: float = 75.0
    inhale_compression_min: float = 45.0
    inhale_momentum_min: float = 5.0
    inhale_momentum_max: float = 35.0
    inhale_relative_strength_gt: float = 0.0
    inhale_confirmed_momentum_min: float = 20.0


DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1 = MarketBreathThresholdProfileV1()


def classify_market_breath_phase_state_v1(
    *,
    compression: float,
    expansion: float,
    momentum: float,
    reversal_pressure: float,
    relative_strength: float,
    profile: MarketBreathThresholdProfileV1 = DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
) -> tuple[str, str]:
    if (
        momentum < profile.collapse_reset_momentum_lt
        and reversal_pressure >= profile.collapse_reset_reversal_min
    ):
        return "COLLAPSE_RESET", "RESET"

    if (
        expansion >= profile.overbreath_expansion_min
        and momentum >= profile.overbreath_momentum_min
        and reversal_pressure >= profile.overbreath_reversal_min
    ):
        return "OVERBREATH_EXTENSION", "LATE"

    if (
        expansion >= profile.exhale_expansion_min
        and momentum > profile.exhale_momentum_gt
        and relative_strength > profile.exhale_relative_strength_gt
    ):
        state = (
            "CONFIRMED"
            if (
                expansion >= profile.exhale_confirmed_expansion_min
                and momentum >= profile.exhale_confirmed_momentum_min
            )
            else "FORMING"
        )
        return "EXHALE_EXPANSION", state

    if (
        compression >= profile.hold_compression_min
        and expansion < profile.hold_expansion_lt
        and abs(momentum) <= profile.hold_abs_momentum_max
    ):
        state = (
            "CONFIRMED"
            if compression >= profile.hold_confirmed_compression_min
            else "FORMING"
        )
        return "HOLD_COMPRESSION", state

    if (
        compression >= profile.inhale_compression_min
        and profile.inhale_momentum_min <= momentum <= profile.inhale_momentum_max
        and relative_strength > profile.inhale_relative_strength_gt
    ):
        state = (
            "FORMING"
            if momentum < profile.inhale_confirmed_momentum_min
            else "CONFIRMED"
        )
        return "INHALE_ACCUMULATION", state

    return "NEUTRAL_TRANSITION", "UNKNOWN"
