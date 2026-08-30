from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

MODEL_FAMILY_VERSION = "1.0.0"
COVERAGE_ARTIFACT_SHA256 = "f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d"
MRP_MODEL_VERSION = "1.0"
MRP_SCALE_MIN = Decimal("-100")
MRP_SCALE_MAX = Decimal("100")
SCORE_QUANTUM = Decimal("0.000001")

AVAILABLE = "AVAILABLE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    version: str
    cq_v0_weight: Decimal
    mrp_market_weight: Decimal

    @property
    def weight_sum(self) -> Decimal:
        return self.cq_v0_weight + self.mrp_market_weight


CANDIDATES: tuple[CandidateSpec, ...] = (
    CandidateSpec(
        candidate_id="cq_v1_mrp_balanced_v1",
        version="1.0.0",
        cq_v0_weight=Decimal("0.500000"),
        mrp_market_weight=Decimal("0.500000"),
    ),
    CandidateSpec(
        candidate_id="cq_v1_mrp_anchor_v1",
        version="1.0.0",
        cq_v0_weight=Decimal("0.750000"),
        mrp_market_weight=Decimal("0.250000"),
    ),
)
CANDIDATES_BY_ID = {spec.candidate_id: spec for spec in CANDIDATES}


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    version: str
    state: str
    score: Decimal | None
    reason: str | None


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field}:INVALID_NUMERIC")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field}:INVALID_NUMERIC") from exc
    if not result.is_finite():
        raise ValueError(f"{field}:NON_FINITE")
    return result


def _round6(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def clamp01(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value))


def normalize_cq_v0(value: Any) -> Decimal:
    numeric = _decimal(value, "cq_v0")
    if numeric < 0 or numeric > 1:
        raise ValueError("cq_v0:OUT_OF_RANGE_0_1")
    return _round6(numeric)


def normalize_mrp_market_score(value: Any) -> Decimal:
    """Map canonical MRP -100..+100 pressure to 0..1; zero maps to 0.5."""
    numeric = _decimal(value, "mrp_aggregate.market_score")
    if numeric < MRP_SCALE_MIN or numeric > MRP_SCALE_MAX:
        raise ValueError("mrp_aggregate.market_score:OUT_OF_RANGE_MINUS100_100")
    return _round6((numeric - MRP_SCALE_MIN) / (MRP_SCALE_MAX - MRP_SCALE_MIN))


def _mrp_support_state(features: Mapping[str, Any]) -> tuple[str, str | None]:
    aggregate = features.get("mrp_aggregate")
    asset = features.get("mrp_asset")
    if aggregate is None:
        return INSUFFICIENT_DATA, "UNAVAILABLE_MRP_AGGREGATE"
    if asset is None:
        return INSUFFICIENT_DATA, "UNAVAILABLE_MRP_ASSET"
    if not isinstance(aggregate, Mapping):
        return BLOCKED, "INVALID_MRP_AGGREGATE_PAYLOAD"
    if not isinstance(asset, Mapping):
        return BLOCKED, "INVALID_MRP_ASSET_PAYLOAD"
    if str(aggregate.get("model_version")) != MRP_MODEL_VERSION:
        return BLOCKED, "MRP_AGGREGATE_MODEL_VERSION_MISMATCH"
    if str(asset.get("model_version")) != MRP_MODEL_VERSION:
        return BLOCKED, "MRP_ASSET_MODEL_VERSION_MISMATCH"
    if "market_score" not in aggregate:
        return BLOCKED, "MRP_MARKET_SCORE_MISSING"
    return AVAILABLE, None


def score_candidate(candidate_id: str, *, cq_v0: Any, features: Mapping[str, Any]) -> CandidateScore:
    spec = CANDIDATES_BY_ID.get(candidate_id)
    if spec is None:
        raise KeyError(f"unknown candidate_id: {candidate_id}")
    if spec.weight_sum != Decimal("1.000000"):
        raise RuntimeError(f"candidate weights must sum to 1: {candidate_id}")

    if cq_v0 is None:
        return CandidateScore(spec.candidate_id, spec.version, INSUFFICIENT_DATA, None, "CQ_V0_UNAVAILABLE")

    support_state, support_reason = _mrp_support_state(features)
    if support_state != AVAILABLE:
        return CandidateScore(spec.candidate_id, spec.version, support_state, None, support_reason)

    try:
        cq_component = normalize_cq_v0(cq_v0)
        mrp_component = normalize_mrp_market_score(features["mrp_aggregate"]["market_score"])
    except ValueError as exc:
        return CandidateScore(spec.candidate_id, spec.version, BLOCKED, None, str(exc))

    raw_score = spec.cq_v0_weight * cq_component + spec.mrp_market_weight * mrp_component
    score = _round6(clamp01(raw_score))
    return CandidateScore(spec.candidate_id, spec.version, AVAILABLE, score, None)


def score_all_candidates(*, cq_v0: Any, features: Mapping[str, Any]) -> tuple[CandidateScore, ...]:
    return tuple(score_candidate(spec.candidate_id, cq_v0=cq_v0, features=features) for spec in CANDIDATES)
