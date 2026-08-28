from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class EntryQualityInput:
    trade_quality_score: Decimal
    timing_refinement_score: Decimal
    quality_penalty: Decimal
    quality_status_1d: str
    quality_status_4h: str
    quality_status_1h: str


@dataclass(frozen=True)
class EntryQualityShadow:
    entry_quality_score: Decimal | None
    entry_quality_state: str
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    model_version: str = "cq_shadow_v1"


def _clamp01(value: Decimal) -> Decimal:
    return max(ZERO, min(ONE, value))


def compute_entry_quality_shadow(inp: EntryQualityInput) -> EntryQualityShadow:
    """Derive CQ v0 from existing Selection Engine v2 outputs.

    This deliberately reconciles with the existing trade_quality_score rather
    than introducing a second independent symbol-local quality model.
    """

    blockers: list[str] = []
    reasons: list[str] = []

    if inp.quality_status_1d == "BLOCKED":
        blockers.append("BLOCKED_1D_QUALITY")
    if inp.quality_status_4h == "BLOCKED":
        blockers.append("BLOCKED_4H_QUALITY")

    if blockers:
        return EntryQualityShadow(
            entry_quality_score=None,
            entry_quality_state="BLOCKED",
            reasons=tuple(reasons),
            blockers=tuple(blockers),
        )

    score = inp.trade_quality_score + inp.timing_refinement_score - inp.quality_penalty
    score = _clamp01(score).quantize(Decimal("0.000001"))

    reasons.append("EVOLVED_FROM_TRADE_QUALITY_SCORE")
    if inp.timing_refinement_score > ZERO:
        reasons.append("POSITIVE_1H_TIMING_REFINEMENT")
    elif inp.timing_refinement_score < ZERO:
        reasons.append("NEGATIVE_1H_TIMING_REFINEMENT")

    if inp.quality_penalty > ZERO:
        reasons.append("DATA_QUALITY_PENALTY_APPLIED")
    if inp.quality_status_1h == "BLOCKED":
        reasons.append("1H_REFINEMENT_UNAVAILABLE")

    if score >= Decimal("0.75"):
        state = "STRONG"
    elif score >= Decimal("0.60"):
        state = "GOOD"
    elif score >= Decimal("0.45"):
        state = "WATCH"
    else:
        state = "WEAK"

    return EntryQualityShadow(
        entry_quality_score=score,
        entry_quality_state=state,
        reasons=tuple(reasons),
        blockers=tuple(blockers),
    )


def compute_entry_strength(
    *,
    ppp_pct: Decimal | None,
    entry_quality_score: Decimal | None,
) -> Decimal | None:
    """Return PPP * CQ without changing PPP semantics.

    PPP is expressed as percentage points (e.g. 20.0 for 20%). CQ is 0..1.
    Missing/non-canonical PPP or blocked CQ fails closed to None.
    """

    if ppp_pct is None or entry_quality_score is None:
        return None
    if ppp_pct < ZERO:
        return None
    if entry_quality_score < ZERO or entry_quality_score > ONE:
        return None
    return (ppp_pct * entry_quality_score).quantize(Decimal("0.000001"))
