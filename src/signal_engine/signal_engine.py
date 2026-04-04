from __future__ import annotations

from dataclasses import dataclass

from src.signal_engine.expansion_rotation import (
    ExpansionRotationInput,
    evaluate_expansion_rotation,
)

ENGINE_NAME = "signal_engine"
ENGINE_VERSION = "1.0"


CONFIDENCE_WEIGHTS: dict[str, float] = {
    "trend": 0.15,
    "volume": 0.15,
    "phase": 0.10,
    "compass": 0.15,
    "rotation": 0.10,
    "relative": 0.10,
    "setup": 0.10,
    "risk": 0.10,
    "expansion_delay": 0.025,
    "rotation_trigger": 0.025,
}


TREND_SIGNAL_SCORES: dict[str, float] = {
    "TREND_UP_STRONG": 1.0,
    "TREND_UP_WEAK": 0.7,
    "TREND_SIDEWAYS": 0.4,
    "TREND_DOWN_WEAK": 0.25,
    "TREND_DOWN_STRONG": 0.0,
    "TREND_RECOVERING": 0.55,
    "TREND_LOSING_STRENGTH": 0.35,
}

VOLUME_SIGNAL_SCORES: dict[str, float] = {
    "VOLUME_CONFIRMED_BREAKOUT": 1.0,
    "VOLUME_WEAK_BREAKOUT": 0.65,
    "VOLUME_ACCUMULATION": 0.75,
    "VOLUME_DISTRIBUTION": 0.2,
    "VOLUME_EXHAUSTION": 0.25,
    "VOLUME_DEAD_BOUNCE": 0.15,
    "VOLUME_NEUTRAL": 0.5,
    "VOLUME_FADE": 0.4,
    "VOLUME_SPIKE_DOWN": 0.05,
}

PHASE_SIGNAL_SCORES: dict[str, float] = {
    "PHASE_CONVERGENCE": 0.5,
    "PHASE_COMPRESSION": 0.6,
    "PHASE_EXPANSION_COHERENT": 0.95,
    "PHASE_EXPANSION_CHAOTIC": 0.55,
    "PHASE_INTEGRATION": 0.65,
    "PHASE_RESET": 0.1,
    "PHASE_REACTIVE": 0.2,
    "PHASE_ANCHOR": 0.85,
    "PHASE_MIRROR": 0.7,
    "PHASE_COMPRESSION_LATE": 0.3,
}

COMPASS_SIGNAL_SCORES: dict[str, float] = {
    "COMPASS_ALIGNMENT_STRONG": 0.95,
    "COMPASS_ALIGNMENT_WEAK": 0.45,
    "COMPASS_ANCHOR_STATE": 0.85,
    "COMPASS_MIRROR_PHASE": 0.7,
    "COMPASS_EXPANSION_SUPPORT": 0.9,
    "COMPASS_CONTRACTION_WARNING": 0.1,
    "COMPASS_PATIENCE_MODE": 0.6,
    "COMPASS_NOISE_WARNING": 0.0,
}

ROTATION_SIGNAL_SCORES: dict[str, float] = {
    "ROTATION_LEADER_ACTIVE": 1.0,
    "ROTATION_GROUP2_OPENING": 0.8,
    "ROTATION_CATCHUP_ACTIVE": 0.75,
    "ROTATION_LAGGARD_WAKEUP": 0.7,
    "ROTATION_DELAYED": 0.35,
    "ROTATION_READY": 0.75,
    "ROTATION_NONE": 0.0,
    "ROTATION_INVALID": 0.0,
}

RELATIVE_SIGNAL_SCORES: dict[str, float] = {
    "RELSTR_LEADING": 1.0,
    "RELSTR_IMPROVING": 0.75,
    "RELSTR_STABLE": 0.45,
    "RELSTR_LAGGING": 0.2,
    "RELSTR_BREAKING_DOWN": 0.0,
    "RELSTR_CATCHING_UP": 0.8,
}

SETUP_SIGNAL_SCORES: dict[str, float] = {
    "SETUP_ARMED": 1.0,
    "SETUP_BUILDING": 0.65,
    "SETUP_EARLY": 0.45,
    "SETUP_LATE": 0.35,
    "SETUP_INVALIDATING": 0.0,
    "SETUP_WATCH_ONLY": 0.3,
    "SETUP_BLOCKED": 0.0,
    "SETUP_NEAR": 0.75,
}

RISK_SIGNAL_SCORES: dict[str, float] = {
    "RISK_OK": 1.0,
    "RISK_WAIT_CONFIRMATION": 0.55,
    "RISK_TOO_EXTENDED": 0.25,
    "RISK_LIQUIDITY_LOW": 0.2,
    "RISK_CONFLICTING_SIGNALS": 0.15,
    "RISK_HIGH": 0.0,
}


@dataclass(frozen=True)
class SignalEngineInput:
    asset_id: int
    ts_utc: str
    interval_code: str
    trend_signal: str
    volume_signal: str
    phase_signal: str
    compass_signal: str
    rotation_signal: str
    relative_signal: str
    setup_signal: str
    risk_signal: str
    alt_market_phase: str | None = None


@dataclass(frozen=True)
class SignalEngineOutput:
    asset_id: int
    ts_utc: str
    interval_code: str
    trend_signal: str
    volume_signal: str
    phase_signal: str
    compass_signal: str
    rotation_signal: str
    relative_signal: str
    setup_signal: str
    risk_signal: str
    expansion_delay_state: bool
    expansion_delay_score: float
    rotation_trigger_state: bool
    rotation_trigger_score: float
    trend_score: float
    volume_score: float
    phase_score: float
    compass_score: float
    rotation_score: float
    relative_score: float
    setup_score: float
    risk_score: float
    signal_confidence: float
    reason_code: str
    reason_text: str


def _score_from_map(value: str, mapping: dict[str, float]) -> float:
    return float(mapping.get(value, 0.0))


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def evaluate_signal_engine(inp: SignalEngineInput) -> SignalEngineOutput:
    trend_score = _score_from_map(inp.trend_signal, TREND_SIGNAL_SCORES)
    volume_score = _score_from_map(inp.volume_signal, VOLUME_SIGNAL_SCORES)
    phase_score = _score_from_map(inp.phase_signal, PHASE_SIGNAL_SCORES)
    compass_score = _score_from_map(inp.compass_signal, COMPASS_SIGNAL_SCORES)
    rotation_score = _score_from_map(inp.rotation_signal, ROTATION_SIGNAL_SCORES)
    relative_score = _score_from_map(inp.relative_signal, RELATIVE_SIGNAL_SCORES)
    setup_score = _score_from_map(inp.setup_signal, SETUP_SIGNAL_SCORES)
    risk_score = _score_from_map(inp.risk_signal, RISK_SIGNAL_SCORES)

    exp = evaluate_expansion_rotation(
        ExpansionRotationInput(
            trend_signal=inp.trend_signal,
            volume_signal=inp.volume_signal,
            phase_signal=inp.phase_signal,
            compass_signal=inp.compass_signal,
            relative_signal=inp.relative_signal,
            setup_signal=inp.setup_signal,
            risk_signal=inp.risk_signal,
            alt_market_phase=inp.alt_market_phase,
        )
    )

    signal_confidence = _clamp(
        trend_score * CONFIDENCE_WEIGHTS["trend"]
        + volume_score * CONFIDENCE_WEIGHTS["volume"]
        + phase_score * CONFIDENCE_WEIGHTS["phase"]
        + compass_score * CONFIDENCE_WEIGHTS["compass"]
        + rotation_score * CONFIDENCE_WEIGHTS["rotation"]
        + relative_score * CONFIDENCE_WEIGHTS["relative"]
        + setup_score * CONFIDENCE_WEIGHTS["setup"]
        + risk_score * CONFIDENCE_WEIGHTS["risk"]
        + exp.expansion_delay_score * CONFIDENCE_WEIGHTS["expansion_delay"]
        + exp.rotation_trigger_score * CONFIDENCE_WEIGHTS["rotation_trigger"]
    )

    if exp.rotation_trigger_state:
        reason_code = "ROTATION_TRIGGER_ACTIVE"
        reason_text = "Rotation trigger activated"
    elif exp.expansion_delay_state:
        reason_code = "EXPANSION_DELAY_ACTIVE"
        reason_text = "Expansion delayed"
    else:
        reason_code = "NEUTRAL"
        reason_text = "No dominant signal"

    return SignalEngineOutput(
        asset_id=inp.asset_id,
        ts_utc=inp.ts_utc,
        interval_code=inp.interval_code,
        trend_signal=inp.trend_signal,
        volume_signal=inp.volume_signal,
        phase_signal=inp.phase_signal,
        compass_signal=inp.compass_signal,
        rotation_signal=inp.rotation_signal,
        relative_signal=inp.relative_signal,
        setup_signal=inp.setup_signal,
        risk_signal=inp.risk_signal,
        expansion_delay_state=exp.expansion_delay_state,
        expansion_delay_score=exp.expansion_delay_score,
        rotation_trigger_state=exp.rotation_trigger_state,
        rotation_trigger_score=exp.rotation_trigger_score,
        trend_score=trend_score,
        volume_score=volume_score,
        phase_score=phase_score,
        compass_score=compass_score,
        rotation_score=rotation_score,
        relative_score=relative_score,
        setup_score=setup_score,
        risk_score=risk_score,
        signal_confidence=signal_confidence,
        reason_code=reason_code,
        reason_text=reason_text,
    )
