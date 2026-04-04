from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpansionRotationInput:
    trend_signal: str
    volume_signal: str
    phase_signal: str
    compass_signal: str
    relative_signal: str
    setup_signal: str
    risk_signal: str
    alt_market_phase: str | None = None


@dataclass(frozen=True)
class ExpansionRotationOutput:
    expansion_delay_state: bool
    expansion_delay_score: float
    rotation_trigger_state: bool
    rotation_trigger_score: float


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _score_expansion_delay(inp: ExpansionRotationInput) -> tuple[bool, float]:
    score = 0.0

    # Structural support from compass / phase
    if inp.compass_signal in {"COMPASS_EXPANSION_SUPPORT", "COMPASS_ALIGNMENT_STRONG"}:
        score += 0.35
    elif inp.compass_signal in {"COMPASS_PATIENCE_MODE", "COMPASS_MIRROR_PHASE"}:
        score += 0.25
    elif inp.compass_signal == "COMPASS_ALIGNMENT_WEAK":
        score += 0.10

    if inp.phase_signal in {"PHASE_EXPANSION_COHERENT", "PHASE_ANCHOR"}:
        score += 0.20
    elif inp.phase_signal in {"PHASE_INTEGRATION", "PHASE_COMPRESSION", "PHASE_MIRROR"}:
        score += 0.15
    elif inp.phase_signal == "PHASE_REACTIVE":
        score += 0.05

    # Timing lag / not yet active


    if inp.trend_signal in {"TREND_SIDEWAYS", "TREND_DOWN_WEAK", "TREND_RECOVERING"}:
        score += 0.15
    elif inp.trend_signal == "TREND_UP_WEAK":
        score += 0.08
    elif inp.trend_signal == "TREND_DOWN_STRONG":
        score -= 0.18

    if inp.relative_signal in {"RELSTR_STABLE", "RELSTR_LAGGING"}:
        score += 0.08
    elif inp.relative_signal == "RELSTR_IMPROVING":
        score += 0.05

    # Negative modifiers
    if inp.risk_signal == "RISK_HIGH":
        score -= 0.35
    elif inp.risk_signal == "RISK_CONFLICTING_SIGNALS":
        score -= 0.20


    if (
        inp.setup_signal == "SETUP_WATCH_ONLY"
        and inp.trend_signal == "TREND_DOWN_STRONG"
    ):
        score -= 0.12


    if inp.volume_signal in {"VOLUME_DISTRIBUTION", "VOLUME_SPIKE_DOWN"}:
        score -= 0.20
    elif inp.volume_signal == "VOLUME_EXHAUSTION":
        score -= 0.10

    if inp.compass_signal in {"COMPASS_NOISE_WARNING", "COMPASS_CONTRACTION_WARNING"}:
        score -= 0.30

    score = _clamp(score)

    delay_state = (
        score >= 0.50
        and inp.risk_signal != "RISK_HIGH"
        and inp.compass_signal not in {"COMPASS_NOISE_WARNING", "COMPASS_CONTRACTION_WARNING"}
        and inp.volume_signal not in {"VOLUME_DISTRIBUTION", "VOLUME_SPIKE_DOWN"}
    )

    return delay_state, score


def _score_rotation_trigger(inp: ExpansionRotationInput) -> tuple[bool, float]:
    score = 0.0

    # Market context must allow rotation
    if inp.alt_market_phase in {"LEADER_PHASE", "SECTOR_EXPANSION", "FULL_ALT_EXPANSION"}:
        score += 0.20
    elif inp.alt_market_phase == "COMPRESSION":
        score += 0.05

    # Trend improving / active
    if inp.trend_signal == "TREND_UP_STRONG":
        score += 0.24
    elif inp.trend_signal == "TREND_UP_WEAK":
        score += 0.18
    elif inp.trend_signal == "TREND_RECOVERING":
        score += 0.16

    # Volume confirmation
    if inp.volume_signal == "VOLUME_CONFIRMED_BREAKOUT":
        score += 0.24
    elif inp.volume_signal == "VOLUME_ACCUMULATION":
        score += 0.18
    elif inp.volume_signal == "VOLUME_WEAK_BREAKOUT":
        score += 0.14
    elif inp.volume_signal == "VOLUME_NEUTRAL":
        score += 0.04

    # Relative strength
    if inp.relative_signal == "RELSTR_LEADING":
        score += 0.16
    elif inp.relative_signal == "RELSTR_CATCHING_UP":
        score += 0.16
    elif inp.relative_signal == "RELSTR_IMPROVING":
        score += 0.14
    elif inp.relative_signal == "RELSTR_STABLE":
        score += 0.04

    # Setup quality
    if inp.setup_signal == "SETUP_ARMED":
        score += 0.20
    elif inp.setup_signal == "SETUP_BUILDING":
        score += 0.12
    elif inp.setup_signal == "SETUP_EARLY":
        score += 0.08
    elif inp.setup_signal == "SETUP_WATCH_ONLY":
        score += 0.03

    # Compass support / contradiction
    if inp.compass_signal in {"COMPASS_EXPANSION_SUPPORT", "COMPASS_ALIGNMENT_STRONG"}:
        score += 0.12
    elif inp.compass_signal == "COMPASS_PATIENCE_MODE":
        score += 0.04
    elif inp.compass_signal in {"COMPASS_NOISE_WARNING", "COMPASS_CONTRACTION_WARNING"}:
        score -= 0.30

    # Risk adjustments
    if inp.risk_signal == "RISK_OK":
        score += 0.08
    elif inp.risk_signal == "RISK_WAIT_CONFIRMATION":
        score += 0.02
    elif inp.risk_signal == "RISK_CONFLICTING_SIGNALS":
        score -= 0.15
    elif inp.risk_signal == "RISK_HIGH":
        score -= 0.35

    raw_score = _clamp(score)

    trigger_state = (
        inp.alt_market_phase in {"LEADER_PHASE", "SECTOR_EXPANSION", "FULL_ALT_EXPANSION"}
        and inp.trend_signal in {"TREND_RECOVERING", "TREND_UP_WEAK", "TREND_UP_STRONG"}
        and inp.volume_signal in {
            "VOLUME_ACCUMULATION",
            "VOLUME_CONFIRMED_BREAKOUT",
            "VOLUME_WEAK_BREAKOUT",
        }
        and inp.relative_signal in {"RELSTR_IMPROVING", "RELSTR_CATCHING_UP", "RELSTR_LEADING"}
        and inp.setup_signal in {"SETUP_BUILDING", "SETUP_ARMED"}
        and inp.compass_signal not in {"COMPASS_NOISE_WARNING", "COMPASS_CONTRACTION_WARNING"}
        and inp.risk_signal != "RISK_HIGH"
        and raw_score >= 0.58
    )

    # Important tuning:
    # If not triggered yet, keep score informative but not too optimistic.
    if not trigger_state:
        raw_score = min(raw_score * 0.72, 0.35)

    return trigger_state, _clamp(raw_score)


def evaluate_expansion_rotation(inp: ExpansionRotationInput) -> ExpansionRotationOutput:
    expansion_delay_state, expansion_delay_score = _score_expansion_delay(inp)
    rotation_trigger_state, rotation_trigger_score = _score_rotation_trigger(inp)

    return ExpansionRotationOutput(
        expansion_delay_state=expansion_delay_state,
        expansion_delay_score=expansion_delay_score,
        rotation_trigger_state=rotation_trigger_state,
        rotation_trigger_score=rotation_trigger_score,
    )
