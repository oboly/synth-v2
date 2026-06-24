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

_DIAGNOSTIC_REGIME_ORDER_V1 = (
    "EXHALE_EXPANSION",
    "INHALE_ACCUMULATION",
    "HOLD_COMPRESSION",
    "OVERBREATH_EXTENSION",
    "COLLAPSE_RESET",
)

_DIAGNOSTIC_REGIME_LABEL_V1 = {
    "EXHALE_EXPANSION": "EXHALE",
    "INHALE_ACCUMULATION": "INHALE",
    "HOLD_COMPRESSION": "HOLD",
    "OVERBREATH_EXTENSION": "OVERBREATH",
    "COLLAPSE_RESET": "COLLAPSE",
}


def _fmt_score_v1(value: float) -> str:
    return f"{value:.1f}"


def _diag_gte_v1(metric: str, value: float, threshold: float, regime: str) -> tuple[bool, str | None, float]:
    if value >= threshold:
        return True, None, 0.0
    label = _DIAGNOSTIC_REGIME_LABEL_V1[regime]
    return (
        False,
        f"{metric} below {label} threshold ({_fmt_score_v1(value)} < {_fmt_score_v1(threshold)})",
        threshold - value,
    )


def _diag_gt_v1(metric: str, value: float, threshold: float, regime: str) -> tuple[bool, str | None, float]:
    if value > threshold:
        return True, None, 0.0
    label = _DIAGNOSTIC_REGIME_LABEL_V1[regime]
    return (
        False,
        f"{metric} not above {label} threshold ({_fmt_score_v1(value)} <= {_fmt_score_v1(threshold)})",
        threshold - value,
    )


def _diag_lt_v1(metric: str, value: float, threshold: float, regime: str) -> tuple[bool, str | None, float]:
    if value < threshold:
        return True, None, 0.0
    label = _DIAGNOSTIC_REGIME_LABEL_V1[regime]
    return (
        False,
        f"{metric} not below {label} threshold ({_fmt_score_v1(value)} >= {_fmt_score_v1(threshold)})",
        value - threshold,
    )


def _diag_lte_v1(metric: str, value: float, threshold: float, regime: str) -> tuple[bool, str | None, float]:
    if value <= threshold:
        return True, None, 0.0
    label = _DIAGNOSTIC_REGIME_LABEL_V1[regime]
    return (
        False,
        f"{metric} above {label} ceiling ({_fmt_score_v1(value)} > {_fmt_score_v1(threshold)})",
        value - threshold,
    )


def _diag_between_v1(
    metric: str,
    value: float,
    lower: float,
    upper: float,
    regime: str,
) -> tuple[bool, str | None, float]:
    label = _DIAGNOSTIC_REGIME_LABEL_V1[regime]
    if value < lower:
        return (
            False,
            f"{metric} below {label} floor ({_fmt_score_v1(value)} < {_fmt_score_v1(lower)})",
            lower - value,
        )
    if value > upper:
        return (
            False,
            f"{metric} above {label} ceiling ({_fmt_score_v1(value)} > {_fmt_score_v1(upper)})",
            value - upper,
        )
    return True, None, 0.0


def _build_regime_diagnostic_v1(
    regime: str,
    checks: tuple[tuple[bool, str | None, float], ...],
) -> dict[str, object]:
    failed_conditions = tuple(message for ok, message, _gap in checks if not ok and message)
    total_gap = sum(float(gap) for ok, _message, gap in checks if not ok)
    return {
        "regime": regime,
        "matched": not failed_conditions,
        "condition_count": len(checks),
        "passed_count": sum(1 for ok, _message, _gap in checks if ok),
        "failed_conditions": failed_conditions,
        "total_gap": round(total_gap, 6),
    }


def _regime_diagnostics_v1(
    *,
    compression: float,
    expansion: float,
    momentum: float,
    reversal_pressure: float,
    relative_strength: float,
    profile: MarketBreathThresholdProfileV1,
) -> tuple[dict[str, object], ...]:
    return (
        _build_regime_diagnostic_v1(
            "COLLAPSE_RESET",
            (
                _diag_lt_v1("momentum", momentum, profile.collapse_reset_momentum_lt, "COLLAPSE_RESET"),
                _diag_gte_v1("reversal pressure", reversal_pressure, profile.collapse_reset_reversal_min, "COLLAPSE_RESET"),
            ),
        ),
        _build_regime_diagnostic_v1(
            "OVERBREATH_EXTENSION",
            (
                _diag_gte_v1("expansion", expansion, profile.overbreath_expansion_min, "OVERBREATH_EXTENSION"),
                _diag_gte_v1("momentum", momentum, profile.overbreath_momentum_min, "OVERBREATH_EXTENSION"),
                _diag_gte_v1("reversal pressure", reversal_pressure, profile.overbreath_reversal_min, "OVERBREATH_EXTENSION"),
            ),
        ),
        _build_regime_diagnostic_v1(
            "EXHALE_EXPANSION",
            (
                _diag_gte_v1("expansion", expansion, profile.exhale_expansion_min, "EXHALE_EXPANSION"),
                _diag_gt_v1("momentum", momentum, profile.exhale_momentum_gt, "EXHALE_EXPANSION"),
                _diag_gt_v1("relative strength", relative_strength, profile.exhale_relative_strength_gt, "EXHALE_EXPANSION"),
            ),
        ),
        _build_regime_diagnostic_v1(
            "HOLD_COMPRESSION",
            (
                _diag_gte_v1("compression", compression, profile.hold_compression_min, "HOLD_COMPRESSION"),
                _diag_lt_v1("expansion", expansion, profile.hold_expansion_lt, "HOLD_COMPRESSION"),
                _diag_lte_v1("absolute momentum", abs(momentum), profile.hold_abs_momentum_max, "HOLD_COMPRESSION"),
            ),
        ),
        _build_regime_diagnostic_v1(
            "INHALE_ACCUMULATION",
            (
                _diag_gte_v1("compression", compression, profile.inhale_compression_min, "INHALE_ACCUMULATION"),
                _diag_between_v1(
                    "momentum",
                    momentum,
                    profile.inhale_momentum_min,
                    profile.inhale_momentum_max,
                    "INHALE_ACCUMULATION",
                ),
                _diag_gt_v1("relative strength", relative_strength, profile.inhale_relative_strength_gt, "INHALE_ACCUMULATION"),
            ),
        ),
    )


def _closest_regime_context_v1(
    diagnostics: tuple[dict[str, object], ...],
) -> dict[str, object]:
    order_rank = {regime: idx for idx, regime in enumerate(_DIAGNOSTIC_REGIME_ORDER_V1)}
    return min(
        diagnostics,
        key=lambda item: (
            -int(item["passed_count"]),
            float(item["total_gap"]),
            order_rank.get(str(item["regime"]), len(order_rank)),
        ),
    )


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


def diagnose_market_breath_context_v1(
    *,
    compression: float,
    expansion: float,
    momentum: float,
    reversal_pressure: float,
    relative_strength: float,
    profile: MarketBreathThresholdProfileV1 = DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
) -> dict[str, object]:
    phase, state = classify_market_breath_phase_state_v1(
        compression=compression,
        expansion=expansion,
        momentum=momentum,
        reversal_pressure=reversal_pressure,
        relative_strength=relative_strength,
        profile=profile,
    )
    diagnostics = _regime_diagnostics_v1(
        compression=compression,
        expansion=expansion,
        momentum=momentum,
        reversal_pressure=reversal_pressure,
        relative_strength=relative_strength,
        profile=profile,
    )
    matched = next((item for item in diagnostics if bool(item["matched"])), None)
    closest = matched or _closest_regime_context_v1(diagnostics)
    neutral_reason = None
    if phase == "NEUTRAL_TRANSITION":
        failed = tuple(str(v) for v in closest["failed_conditions"])
        suffix = "; ".join(failed) if failed else "no regime conditions matched"
        neutral_reason = f"No classified phase — {suffix}"
    return {
        "market_breath_phase": phase,
        "market_breath_state": state,
        "closest_regime_context": str(closest["regime"]),
        "closest_regime_failed_conditions": list(str(v) for v in closest["failed_conditions"]),
        "neutral_reason": neutral_reason,
        "regime_diagnostics": {
            str(item["regime"]): {
                "matched": bool(item["matched"]),
                "condition_count": int(item["condition_count"]),
                "passed_count": int(item["passed_count"]),
                "failed_conditions": list(str(v) for v in item["failed_conditions"]),
                "total_gap": float(item["total_gap"]),
            }
            for item in diagnostics
        },
    }
