from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from typing import Iterable, Mapping, Sequence


MODEL_VERSION = "sector-rotation-v1.0.0"
SOURCE_INTERVAL_CODE = "1h"
WINDOW_HOURS = {"1h": 1, "4h": 4, "1d": 24, "7d": 168}
WINDOW_ORDER = tuple(WINDOW_HOURS)

SCORE_WEIGHTS = {
    "relative_strength": 0.30,
    "participation": 0.25,
    "volume_share_change": 0.20,
    "persistence": 0.15,
    "liquidity_quality": 0.10,
}
RETURN_COMPONENT_SCALE_PCT = {"1h": 0.50, "4h": 1.00, "1d": 2.00, "7d": 6.00}
PARTICIPATION_MOVE_THRESHOLD_PCT = {"1h": 0.10, "4h": 0.25, "1d": 0.50, "7d": 1.50}
VOLUME_SHARE_CHANGE_SCALE_PCT = 0.25
MAX_ASSET_CONTRIBUTION = 0.35
MAX_LIQUIDITY_WEIGHT = 1.25
MIN_ELIGIBLE_MEMBERS = 3
MIN_EFFECTIVE_MEMBERS = 2.50
MIN_COVERAGE_RATIO = 0.50
MIN_PARTICIPATION_RATIO = 0.50
PERSISTENCE_LOOKBACK = 3

LIQUIDITY_MULTIPLIERS = {
    "MAJOR": 1.25,
    "SEMI_MAJOR": 1.15,
    "LARGE_ALT": 1.10,
    "MID_ALT": 1.00,
    "SMALL_ALT": 0.85,
    "MICRO_ALT": 0.70,
    "UNCLASSIFIED": 0.60,
}
LIQUIDITY_QUALITY_SCORES = {
    "MAJOR": 100.0,
    "SEMI_MAJOR": 90.0,
    "LARGE_ALT": 80.0,
    "MID_ALT": 65.0,
    "SMALL_ALT": 45.0,
    "MICRO_ALT": 25.0,
    "UNCLASSIFIED": 10.0,
}

ROTATION_STATES = (
    "LEADING",
    "IMPROVING",
    "NEUTRAL",
    "WEAKENING",
    "LAGGING",
    "ROTATION_INFLOW_PROXY",
    "ROTATION_OUTFLOW_PROXY",
    "MARKET_ACTIVITY_RISING",
    "MARKET_ACTIVITY_COOLING",
    "NO_CONFIRMATION",
    "INSUFFICIENT_PARTICIPATION",
    "DATA_UNAVAILABLE",
)


@dataclass(frozen=True)
class TaxonomyMembership:
    asset_symbol: str
    asset_id: int | None
    sector_code: str
    membership_weight: float
    liquidity_market_cap_code: str
    membership_type: str = "PRIMARY"
    taxonomy_version: str = ""


@dataclass(frozen=True)
class NormalizedMembership:
    asset_symbol: str
    asset_id: int | None
    sector_code: str
    membership_weight: float
    normalized_membership_weight: float
    liquidity_market_cap_code: str
    membership_type: str
    taxonomy_version: str


@dataclass(frozen=True)
class AssetWindowObservation:
    asset_id: int
    asset_symbol: str
    current_return_pct: float | None
    baseline_return_pct: float | None
    current_quote_volume: float | None
    baseline_quote_volume: float | None
    current_coverage_ratio: float
    baseline_coverage_ratio: float
    latest_close_ts_utc: datetime | None
    eligible: bool
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class BenchmarkWindow:
    btc_return_pct: float | None
    eth_return_pct: float | None
    btc_asof_ts_utc: datetime | None
    eth_asof_ts_utc: datetime | None
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class SectorRotationSnapshot:
    sector_code: str
    venue: str
    source_interval_code: str
    window_code: str
    asof_ts_utc: datetime
    weighted_return: float | None
    median_return: float | None
    positive_participation_pct: float | None
    negative_participation_pct: float | None
    benchmark_outperformance_pct: float | None
    relative_strength_vs_btc: float | None
    relative_strength_vs_eth: float | None
    sector_volume_share: float | None
    sector_volume_share_change: float | None
    momentum_positive_pct: float | None
    dispersion: float | None
    member_count: int
    eligible_member_count: int
    effective_weighted_member_count: float
    participation_ratio: float
    coverage_ratio: float
    liquidity_quality: float | None
    dominant_member_weight_pct: float | None
    persistence_score: float
    persistence_history_count: int
    persistence_status: str
    rotation_score: float
    rotation_state: str
    confidence: float
    component_json: str
    supporting_flags_json: str
    taxonomy_versions_json: str
    input_hash: str
    model_version: str = MODEL_VERSION


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round(value: float | None, digits: int = 8) -> float | None:
    return None if value is None else round(float(value), digits)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def deterministic_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def membership_valid_at(
    valid_from_ts_utc: datetime,
    valid_to_ts_utc: datetime | None,
    asof_ts_utc: datetime,
) -> bool:
    return valid_from_ts_utc <= asof_ts_utc and (
        valid_to_ts_utc is None or asof_ts_utc < valid_to_ts_utc
    )


def normalize_multi_cluster_memberships(
    memberships: Iterable[TaxonomyMembership],
) -> tuple[NormalizedMembership, ...]:
    rows = sorted(
        memberships,
        key=lambda row: (row.asset_symbol, row.sector_code, row.membership_type),
    )
    totals: dict[str, float] = {}
    for row in rows:
        weight = _finite(row.membership_weight, "membership_weight")
        if weight < 0 or weight > 1:
            raise ValueError("membership_weight must be within [0, 1]")
        totals[row.asset_symbol] = totals.get(row.asset_symbol, 0.0) + weight

    result = []
    for row in rows:
        denominator = max(1.0, totals[row.asset_symbol])
        result.append(
            NormalizedMembership(
                asset_symbol=row.asset_symbol,
                asset_id=row.asset_id,
                sector_code=row.sector_code,
                membership_weight=row.membership_weight,
                normalized_membership_weight=_round(row.membership_weight / denominator) or 0.0,
                liquidity_market_cap_code=row.liquidity_market_cap_code,
                membership_type=row.membership_type,
                taxonomy_version=row.taxonomy_version,
            )
        )
    return tuple(result)


def _capped_normalized_weights(raw_weights: Sequence[float]) -> tuple[float, ...]:
    if not raw_weights:
        return ()
    clean = [_finite(max(0.0, value), "asset_weight") for value in raw_weights]
    total = sum(clean)
    if total <= 0:
        return tuple(1.0 / len(clean) for _ in clean)
    normalized = [value / total for value in clean]
    if len(clean) < math.ceil(1.0 / MAX_ASSET_CONTRIBUTION):
        return tuple(normalized)

    result = [0.0] * len(clean)
    remaining = set(range(len(clean)))
    remaining_mass = 1.0
    while remaining:
        remaining_total = sum(clean[index] for index in remaining)
        if remaining_total <= 0:
            equal = remaining_mass / len(remaining)
            for index in remaining:
                result[index] = equal
            break
        over_cap = [
            index
            for index in remaining
            if clean[index] / remaining_total * remaining_mass > MAX_ASSET_CONTRIBUTION
        ]
        if not over_cap:
            for index in remaining:
                result[index] = clean[index] / remaining_total * remaining_mass
            break
        for index in sorted(over_cap):
            result[index] = MAX_ASSET_CONTRIBUTION
            remaining.remove(index)
            remaining_mass -= MAX_ASSET_CONTRIBUTION
    return tuple(result)


def _weighted_std(values: Sequence[float], weights: Sequence[float], mean_value: float) -> float:
    variance = sum(weight * (value - mean_value) ** 2 for value, weight in zip(values, weights))
    return math.sqrt(max(0.0, variance))


def _score_component(value: float, scale: float) -> float:
    return _clamp(100.0 * math.tanh(value / scale), -100.0, 100.0)


def _classification(
    *,
    sector_code: str,
    member_count: int,
    eligible_member_count: int,
    effective_member_count: float,
    coverage_ratio: float,
    participation_ratio: float,
    score: float,
    relative_strength_component: float,
    participation_component: float,
    benchmark_available: bool,
) -> str:
    if not benchmark_available or member_count == 0 or coverage_ratio < MIN_COVERAGE_RATIO:
        return "DATA_UNAVAILABLE"
    if (
        sector_code == "UNCLASSIFIED"
        or eligible_member_count < MIN_ELIGIBLE_MEMBERS
        or effective_member_count < MIN_EFFECTIVE_MEMBERS
        or participation_ratio < MIN_PARTICIPATION_RATIO
    ):
        return "INSUFFICIENT_PARTICIPATION"
    if score >= 45 and relative_strength_component > 0 and participation_component > 0:
        return "LEADING"
    if score >= 15:
        return "IMPROVING"
    if score <= -45 and relative_strength_component < 0 and participation_component < 0:
        return "LAGGING"
    if score <= -15:
        return "WEAKENING"
    return "NEUTRAL"


def _empty_snapshot(
    *,
    sector_code: str,
    venue: str,
    window_code: str,
    asof_ts_utc: datetime,
    member_count: int,
    benchmark: BenchmarkWindow,
    taxonomy_versions: Sequence[str],
    member_evidence: list[dict[str, object]],
    reason: str,
) -> SectorRotationSnapshot:
    coverage_ratio = 0.0
    state = "DATA_UNAVAILABLE"
    components = {
        "model_version": MODEL_VERSION,
        "reason": reason,
        "score_weights": SCORE_WEIGHTS,
        "member_evidence": member_evidence,
        "benchmark_reason": benchmark.reason,
        "persistence_status": "INSUFFICIENT_HISTORY",
    }
    flags = {
        "rotation_inflow_proxy": False,
        "rotation_outflow_proxy": False,
        "market_activity_rising": False,
        "market_activity_cooling": False,
        "no_confirmation": True,
        "one_member_dominated": member_count == 1,
        "unclassified_excluded": sector_code == "UNCLASSIFIED",
    }
    input_payload = {
        "sector_code": sector_code,
        "venue": venue,
        "window_code": window_code,
        "asof_ts_utc": asof_ts_utc.isoformat(),
        "components": components,
        "flags": flags,
        "taxonomy_versions": sorted(set(taxonomy_versions)),
    }
    return SectorRotationSnapshot(
        sector_code=sector_code,
        venue=venue,
        source_interval_code=SOURCE_INTERVAL_CODE,
        window_code=window_code,
        asof_ts_utc=asof_ts_utc,
        weighted_return=None,
        median_return=None,
        positive_participation_pct=None,
        negative_participation_pct=None,
        benchmark_outperformance_pct=None,
        relative_strength_vs_btc=None,
        relative_strength_vs_eth=None,
        sector_volume_share=None,
        sector_volume_share_change=None,
        momentum_positive_pct=None,
        dispersion=None,
        member_count=member_count,
        eligible_member_count=0,
        effective_weighted_member_count=0.0,
        participation_ratio=0.0,
        coverage_ratio=coverage_ratio,
        liquidity_quality=None,
        dominant_member_weight_pct=None,
        persistence_score=0.0,
        persistence_history_count=0,
        persistence_status="INSUFFICIENT_HISTORY",
        rotation_score=0.0,
        rotation_state=state,
        confidence=0.0,
        component_json=canonical_json(components),
        supporting_flags_json=canonical_json(flags),
        taxonomy_versions_json=canonical_json(sorted(set(taxonomy_versions))),
        input_hash=deterministic_hash(input_payload),
    )


def compute_sector_snapshot(
    *,
    sector_code: str,
    venue: str,
    window_code: str,
    asof_ts_utc: datetime,
    memberships: Sequence[NormalizedMembership],
    observations_by_asset: Mapping[int, AssetWindowObservation],
    benchmark: BenchmarkWindow,
    universe_current_quote_volume: float,
    universe_baseline_quote_volume: float,
    prior_rotation_scores: Sequence[float],
) -> SectorRotationSnapshot:
    if window_code not in WINDOW_HOURS:
        raise ValueError(f"unsupported window_code={window_code}")
    sector_members = sorted(
        (row for row in memberships if row.sector_code == sector_code),
        key=lambda row: (row.asset_symbol, row.asset_id or -1),
    )
    taxonomy_versions = sorted({row.taxonomy_version for row in sector_members if row.taxonomy_version})
    member_evidence: list[dict[str, object]] = []
    eligible_rows: list[tuple[NormalizedMembership, AssetWindowObservation]] = []
    for member in sector_members:
        observation = observations_by_asset.get(member.asset_id) if member.asset_id is not None else None
        effective_eligible = bool(
            observation
            and observation.eligible
            and member.normalized_membership_weight > 0
        )
        evidence = {
            "asset_symbol": member.asset_symbol,
            "asset_id": member.asset_id,
            "membership_type": member.membership_type,
            "membership_weight": member.membership_weight,
            "normalized_membership_weight": member.normalized_membership_weight,
            "liquidity_market_cap_code": member.liquidity_market_cap_code,
            "eligible": effective_eligible,
            "exclusion_reason": None if effective_eligible else (
                "ZERO_MEMBERSHIP_WEIGHT"
                if observation and observation.eligible
                else (observation.exclusion_reason if observation else "NO_LOCAL_CANDLE_IDENTITY")
            ),
        }
        if observation is not None:
            evidence.update(
                current_return_pct=observation.current_return_pct,
                baseline_return_pct=observation.baseline_return_pct,
                current_quote_volume=observation.current_quote_volume,
                baseline_quote_volume=observation.baseline_quote_volume,
                latest_close_ts_utc=(
                    observation.latest_close_ts_utc.isoformat()
                    if observation.latest_close_ts_utc else None
                ),
            )
        member_evidence.append(evidence)
        if effective_eligible and observation is not None:
            eligible_rows.append((member, observation))

    if not benchmark.available:
        return _empty_snapshot(
            sector_code=sector_code,
            venue=venue,
            window_code=window_code,
            asof_ts_utc=asof_ts_utc,
            member_count=len(sector_members),
            benchmark=benchmark,
            taxonomy_versions=taxonomy_versions,
            member_evidence=member_evidence,
            reason="BENCHMARK_DATA_UNAVAILABLE",
        )
    if not sector_members or not eligible_rows:
        return _empty_snapshot(
            sector_code=sector_code,
            venue=venue,
            window_code=window_code,
            asof_ts_utc=asof_ts_utc,
            member_count=len(sector_members),
            benchmark=benchmark,
            taxonomy_versions=taxonomy_versions,
            member_evidence=member_evidence,
            reason="NO_ELIGIBLE_MEMBERS",
        )

    raw_weights = []
    for member, _ in eligible_rows:
        liquidity_multiplier = min(
            MAX_LIQUIDITY_WEIGHT,
            LIQUIDITY_MULTIPLIERS.get(member.liquidity_market_cap_code, 0.60),
        )
        raw_weights.append(member.normalized_membership_weight * liquidity_multiplier)
    weights = _capped_normalized_weights(raw_weights)
    returns = [float(row.current_return_pct) for _, row in eligible_rows if row.current_return_pct is not None]
    if len(returns) != len(eligible_rows):
        raise ValueError("eligible observation missing current_return_pct")

    weighted_return = sum(weight * value for weight, value in zip(weights, returns))
    median_return = float(median(returns))
    threshold = PARTICIPATION_MOVE_THRESHOLD_PCT[window_code]
    positive_count = sum(value > threshold for value in returns)
    negative_count = sum(value < -threshold for value in returns)
    eligible_count = len(eligible_rows)
    positive_pct = 100.0 * positive_count / eligible_count
    negative_pct = 100.0 * negative_count / eligible_count
    participation_ratio = (positive_count + negative_count) / eligible_count
    benchmark_outperformance_pct = 100.0 * sum(
        value > float(benchmark.btc_return_pct) for value in returns
    ) / eligible_count
    momentum_positive_pct = 100.0 * sum(
        row.baseline_return_pct is not None
        and float(row.current_return_pct) > float(row.baseline_return_pct)
        for _, row in eligible_rows
    ) / eligible_count
    relative_strength_vs_btc = weighted_return - float(benchmark.btc_return_pct)
    relative_strength_vs_eth = weighted_return - float(benchmark.eth_return_pct)
    dispersion = _weighted_std(returns, weights, weighted_return)
    coverage_ratio = eligible_count / len(sector_members)
    effective_member_count = 1.0 / sum(weight * weight for weight in weights)
    dominant_member_weight_pct = 100.0 * max(weights)
    liquidity_quality = sum(
        weight * LIQUIDITY_QUALITY_SCORES.get(member.liquidity_market_cap_code, 10.0)
        for weight, (member, _) in zip(weights, eligible_rows)
    )

    sector_current_volume = sum(
        float(row.current_quote_volume) * member.normalized_membership_weight
        for member, row in eligible_rows
        if row.current_quote_volume is not None
    )
    sector_baseline_volume = sum(
        float(row.baseline_quote_volume) * member.normalized_membership_weight
        for member, row in eligible_rows
        if row.baseline_quote_volume is not None
    )
    current_share = (
        100.0 * sector_current_volume / universe_current_quote_volume
        if universe_current_quote_volume > 0 else 0.0
    )
    baseline_share = (
        100.0 * sector_baseline_volume / universe_baseline_quote_volume
        if universe_baseline_quote_volume > 0 else 0.0
    )
    volume_share_change = current_share - baseline_share

    relative_strength_component = (
        0.60 * _score_component(relative_strength_vs_btc, RETURN_COMPONENT_SCALE_PCT[window_code])
        + 0.40 * _score_component(relative_strength_vs_eth, RETURN_COMPONENT_SCALE_PCT[window_code])
    )
    participation_component = (positive_pct - negative_pct) * participation_ratio
    volume_share_change_component = _score_component(
        volume_share_change, VOLUME_SHARE_CHANGE_SCALE_PCT
    )
    prior_scores = [
        _clamp(_finite(value, "prior_rotation_score"), -100.0, 100.0)
        for value in list(prior_rotation_scores)[:PERSISTENCE_LOOKBACK]
    ]
    persistence_score = 0.0 if not prior_scores else sum(prior_scores) / len(prior_scores)
    persistence_status = "INSUFFICIENT_HISTORY" if not prior_scores else (
        "PARTIAL_HISTORY" if len(prior_scores) < PERSISTENCE_LOOKBACK else "AVAILABLE"
    )
    liquidity_component = _clamp((liquidity_quality - 50.0) * 2.0, -100.0, 100.0)
    score_components = {
        "relative_strength": relative_strength_component,
        "participation": participation_component,
        "volume_share_change": volume_share_change_component,
        "persistence": persistence_score,
        "liquidity_quality": liquidity_component,
    }
    rotation_score = sum(
        score_components[name] * SCORE_WEIGHTS[name]
        for name in SCORE_WEIGHTS
    )
    rotation_score = _clamp(rotation_score, -100.0, 100.0)
    rotation_state = _classification(
        sector_code=sector_code,
        member_count=len(sector_members),
        eligible_member_count=eligible_count,
        effective_member_count=effective_member_count,
        coverage_ratio=coverage_ratio,
        participation_ratio=participation_ratio,
        score=rotation_score,
        relative_strength_component=relative_strength_component,
        participation_component=participation_component,
        benchmark_available=benchmark.available,
    )
    history_factor = min(1.0, len(prior_scores) / PERSISTENCE_LOOKBACK)
    confidence = _clamp(
        0.35 * coverage_ratio
        + 0.30 * min(1.0, effective_member_count / MIN_EFFECTIVE_MEMBERS)
        + 0.20 * participation_ratio
        + 0.15 * history_factor,
        0.0,
        1.0,
    )
    if rotation_state == "DATA_UNAVAILABLE":
        confidence = 0.0
    elif rotation_state == "INSUFFICIENT_PARTICIPATION":
        confidence = min(confidence, 0.49)

    flags = {
        "rotation_inflow_proxy": (
            rotation_state in {"LEADING", "IMPROVING"}
            and rotation_score >= 35
            and positive_pct >= 60
            and volume_share_change_component >= 15
        ),
        "rotation_outflow_proxy": (
            rotation_state in {"LAGGING", "WEAKENING"}
            and rotation_score <= -35
            and negative_pct >= 60
            and volume_share_change_component <= -15
        ),
        "market_activity_rising": volume_share_change > 0 and abs(weighted_return) > threshold,
        "market_activity_cooling": volume_share_change < 0,
        "no_confirmation": (
            relative_strength_component * participation_component < 0
            or relative_strength_component * volume_share_change_component < 0
        ),
        "one_member_dominated": dominant_member_weight_pct > MAX_ASSET_CONTRIBUTION * 100 + 1e-8,
        "asset_contribution_cap_applied": any(
            abs(weight - raw / sum(raw_weights)) > 1e-8
            for weight, raw in zip(weights, raw_weights)
        ) if sum(raw_weights) > 0 else False,
        "unclassified_excluded": sector_code == "UNCLASSIFIED",
        "persistence_history_insufficient": persistence_status != "AVAILABLE",
    }
    for evidence, effective_weight in zip(
        (item for item in member_evidence if item["eligible"]),
        weights,
    ):
        evidence["effective_sector_weight_pct"] = _round(100.0 * effective_weight)

    components = {
        "model_version": MODEL_VERSION,
        "score_weights": SCORE_WEIGHTS,
        "score_components": {key: _round(value) for key, value in score_components.items()},
        "normalization": {
            "return_component_scale_pct": RETURN_COMPONENT_SCALE_PCT[window_code],
            "participation_move_threshold_pct": threshold,
            "volume_share_change_scale_pct": VOLUME_SHARE_CHANGE_SCALE_PCT,
            "max_asset_contribution": MAX_ASSET_CONTRIBUTION,
            "max_liquidity_weight": MAX_LIQUIDITY_WEIGHT,
            "min_eligible_members": MIN_ELIGIBLE_MEMBERS,
            "min_effective_members": MIN_EFFECTIVE_MEMBERS,
            "min_coverage_ratio": MIN_COVERAGE_RATIO,
            "min_participation_ratio": MIN_PARTICIPATION_RATIO,
        },
        "benchmark": {
            "btc_return_pct": _round(benchmark.btc_return_pct),
            "eth_return_pct": _round(benchmark.eth_return_pct),
            "btc_asof_ts_utc": benchmark.btc_asof_ts_utc.isoformat() if benchmark.btc_asof_ts_utc else None,
            "eth_asof_ts_utc": benchmark.eth_asof_ts_utc.isoformat() if benchmark.eth_asof_ts_utc else None,
        },
        "sector_baseline_volume_share": _round(baseline_share),
        "member_evidence": member_evidence,
    }
    rounded_flags = canonical_json(flags)
    component_text = canonical_json(components)
    taxonomy_text = canonical_json(taxonomy_versions)
    input_payload = {
        "sector_code": sector_code,
        "venue": venue,
        "window_code": window_code,
        "asof_ts_utc": asof_ts_utc.isoformat(),
        "component_json": component_text,
        "supporting_flags_json": rounded_flags,
        "taxonomy_versions_json": taxonomy_text,
        "prior_rotation_scores": [_round(value) for value in prior_scores],
        "outputs": {
            "weighted_return": _round(weighted_return),
            "median_return": _round(median_return),
            "positive_participation_pct": _round(positive_pct),
            "negative_participation_pct": _round(negative_pct),
            "benchmark_outperformance_pct": _round(benchmark_outperformance_pct),
            "relative_strength_vs_btc": _round(relative_strength_vs_btc),
            "relative_strength_vs_eth": _round(relative_strength_vs_eth),
            "sector_volume_share": _round(current_share),
            "sector_volume_share_change": _round(volume_share_change),
            "momentum_positive_pct": _round(momentum_positive_pct),
            "dispersion": _round(dispersion),
            "member_count": len(sector_members),
            "eligible_member_count": eligible_count,
            "effective_weighted_member_count": _round(effective_member_count),
            "participation_ratio": _round(participation_ratio),
            "coverage_ratio": _round(coverage_ratio),
            "liquidity_quality": _round(liquidity_quality),
            "dominant_member_weight_pct": _round(dominant_member_weight_pct),
            "persistence_score": _round(persistence_score),
            "persistence_history_count": len(prior_scores),
            "persistence_status": persistence_status,
            "rotation_score": _round(rotation_score),
            "rotation_state": rotation_state,
            "confidence": _round(confidence),
        },
    }
    return SectorRotationSnapshot(
        sector_code=sector_code,
        venue=venue,
        source_interval_code=SOURCE_INTERVAL_CODE,
        window_code=window_code,
        asof_ts_utc=asof_ts_utc,
        weighted_return=_round(weighted_return),
        median_return=_round(median_return),
        positive_participation_pct=_round(positive_pct),
        negative_participation_pct=_round(negative_pct),
        benchmark_outperformance_pct=_round(benchmark_outperformance_pct),
        relative_strength_vs_btc=_round(relative_strength_vs_btc),
        relative_strength_vs_eth=_round(relative_strength_vs_eth),
        sector_volume_share=_round(current_share),
        sector_volume_share_change=_round(volume_share_change),
        momentum_positive_pct=_round(momentum_positive_pct),
        dispersion=_round(dispersion),
        member_count=len(sector_members),
        eligible_member_count=eligible_count,
        effective_weighted_member_count=_round(effective_member_count) or 0.0,
        participation_ratio=_round(participation_ratio) or 0.0,
        coverage_ratio=_round(coverage_ratio) or 0.0,
        liquidity_quality=_round(liquidity_quality),
        dominant_member_weight_pct=_round(dominant_member_weight_pct),
        persistence_score=_round(persistence_score) or 0.0,
        persistence_history_count=len(prior_scores),
        persistence_status=persistence_status,
        rotation_score=_round(rotation_score) or 0.0,
        rotation_state=rotation_state,
        confidence=_round(confidence) or 0.0,
        component_json=component_text,
        supporting_flags_json=rounded_flags,
        taxonomy_versions_json=taxonomy_text,
        input_hash=deterministic_hash(input_payload),
    )


def snapshot_persisted_values(snapshot: SectorRotationSnapshot) -> dict[str, object]:
    return asdict(snapshot)
