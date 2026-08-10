# Read-only, market-only, account-agnostic projection of the persisted
# market_rotation_pressure_v1 state into Profit Plan display shape. This
# module never recomputes and never derives any rotation score, direction,
# evidence-light, breadth, rank, or confirmation semantics -- it only reads,
# validates, and reshapes already persisted values from
# market_rotation_pressure_dashboard_v1. No DB access here; the runner owns
# the DB fetch.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from src.reporting.market_rotation_pressure_dashboard_v1 import (
    MODEL_VERSION,
    RotationPressureDashboard,
    RotationPressureHistoryPoint,
    build_dashboard,
)


NO_ROTATION_ROW_REASON = "NO_ROTATION_ROW"
PROJECTION_NOT_PROVIDED_REASON = "ROTATION_PROJECTION_NOT_PROVIDED"


@dataclass(frozen=True)
class RotationMarketProjection:
    market: str
    available: bool
    freshness: str
    score_total: float | None
    pressure_state: str | None
    phase_state: str | None
    source_ts_utc: datetime | None
    reason: str | None = None


@dataclass(frozen=True)
class RotationProfitPlanProjection:
    available: bool
    freshness: str
    source_ts_utc: datetime | None
    aggregate_direction: str | None
    aggregate_score: float | None
    evidence_light_count: int | None
    positive_count: int | None
    neutral_count: int | None
    negative_count: int | None
    positive_breadth_ratio: float | None
    negative_breadth_ratio: float | None
    acceleration_state: str | None
    confirmation_state: str | None
    concentration_state: str | None
    eligible_asset_count: int | None
    venue: str | None
    model_version: str | None
    history: tuple[RotationPressureHistoryPoint, ...]
    reason: str | None
    per_market: dict[str, RotationMarketProjection]


def unavailable_projection(*, reason: str = PROJECTION_NOT_PROVIDED_REASON) -> RotationProfitPlanProjection:
    """Explicit unavailable/fail-closed projection -- used when no rotation
    snapshot could be read at all (missing header row, schema not ready,
    or the caller has not wired rotation context in)."""
    return RotationProfitPlanProjection(
        available=False,
        freshness="DATA_UNAVAILABLE",
        source_ts_utc=None,
        aggregate_direction=None,
        aggregate_score=None,
        evidence_light_count=None,
        positive_count=None,
        neutral_count=None,
        negative_count=None,
        positive_breadth_ratio=None,
        negative_breadth_ratio=None,
        acceleration_state=None,
        confirmation_state=None,
        concentration_state=None,
        eligible_asset_count=None,
        venue=None,
        model_version=None,
        history=(),
        reason=reason,
        per_market={},
    )


def build_rotation_projection(
    header_row: dict[str, Any] | None,
    observation_rows: Iterable[dict[str, Any]],
    *,
    now_utc: datetime,
    history_rows: Iterable[dict[str, Any]] = (),
) -> RotationProfitPlanProjection:
    """Build a Profit Plan projection from raw persisted rotation rows.

    Fail-closed: any invalid/missing snapshot degrades to an unavailable or
    degraded projection via build_dashboard() -- never raises, never
    fabricates a score/direction/evidence-light value.
    """
    try:
        dashboard: RotationPressureDashboard = build_dashboard(
            header_row, observation_rows, now_utc=now_utc, history_rows=history_rows
        )
    except Exception as exc:  # defensive: invalid raw rows must never raise past this builder
        return unavailable_projection(reason=f"ROTATION_ROW_PARSE_FAILED:{exc}")

    if dashboard.header is None:
        return unavailable_projection(reason=dashboard.reason or "NO_PRESSURE_SNAPSHOT")

    header = dashboard.header
    available = dashboard.status in ("AVAILABLE", "DEGRADED")

    per_market: dict[str, RotationMarketProjection] = {}
    for row in dashboard.rows:
        per_market[row.market] = RotationMarketProjection(
            market=row.market,
            available=available,
            freshness=dashboard.freshness_state,
            score_total=row.score_total,
            pressure_state=row.pressure_state,
            phase_state=row.phase_state,
            source_ts_utc=header.as_of_ts_utc,
            reason=None,
        )

    return RotationProfitPlanProjection(
        available=available,
        freshness=dashboard.freshness_state,
        source_ts_utc=header.as_of_ts_utc,
        aggregate_direction=header.market_direction,
        aggregate_score=header.market_score,
        evidence_light_count=header.evidence_light_count,
        positive_count=header.positive_count,
        neutral_count=header.neutral_count,
        negative_count=header.negative_count,
        positive_breadth_ratio=header.positive_breadth_ratio,
        negative_breadth_ratio=header.negative_breadth_ratio,
        acceleration_state=header.acceleration_state,
        confirmation_state=header.confirmation_state,
        concentration_state=header.concentration_state,
        eligible_asset_count=header.eligible_asset_count,
        venue=header.venue,
        model_version=header.model_version,
        history=dashboard.history,
        reason=dashboard.reason,
        per_market=per_market,
    )


def get_market_projection(
    projection: RotationProfitPlanProjection, market: str
) -> RotationMarketProjection:
    """Look up the per-market rotation context for one Profit Plan card's
    market. A market with no matching persisted rotation row (or an
    unavailable aggregate snapshot) gets an explicit "no rotation row"
    entry -- never a fabricated neutral score, never a crash."""
    found = projection.per_market.get(market)
    if found is not None:
        return found
    reason = NO_ROTATION_ROW_REASON if projection.available else (projection.reason or PROJECTION_NOT_PROVIDED_REASON)
    return RotationMarketProjection(
        market=market,
        available=False,
        freshness=projection.freshness,
        score_total=None,
        pressure_state=None,
        phase_state=None,
        source_ts_utc=projection.source_ts_utc,
        reason=reason,
    )


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    naive = value.replace(tzinfo=None) if value.tzinfo is not None else value
    return naive.isoformat(timespec="seconds") + "Z"


def market_projection_to_json_dict(projection: RotationMarketProjection) -> dict[str, Any]:
    return {
        "market": projection.market,
        "available": projection.available,
        "freshness": projection.freshness,
        "score_total": projection.score_total,
        "pressure_state": projection.pressure_state,
        "phase_state": projection.phase_state,
        "source_ts_utc": _iso_z(projection.source_ts_utc),
        "reason": projection.reason,
    }


def to_json_dict(projection: RotationProfitPlanProjection) -> dict[str, Any]:
    """Explicit rotation JSON block per Issue #255: rotation.available,
    rotation.freshness, rotation.source_ts_utc, rotation.aggregate_direction,
    rotation.aggregate_score, rotation.evidence_light_count,
    rotation.per_market[...]."""
    return {
        "available": projection.available,
        "freshness": projection.freshness,
        "source_ts_utc": _iso_z(projection.source_ts_utc),
        "aggregate_direction": projection.aggregate_direction,
        "aggregate_score": projection.aggregate_score,
        "evidence_light_count": projection.evidence_light_count,
        "positive_count": projection.positive_count,
        "neutral_count": projection.neutral_count,
        "negative_count": projection.negative_count,
        "positive_breadth_ratio": projection.positive_breadth_ratio,
        "negative_breadth_ratio": projection.negative_breadth_ratio,
        "acceleration_state": projection.acceleration_state,
        "confirmation_state": projection.confirmation_state,
        "concentration_state": projection.concentration_state,
        "eligible_asset_count": projection.eligible_asset_count,
        "venue": projection.venue,
        "model_version": projection.model_version,
        "history": [
            {
                "pressure_snapshot_id": point.pressure_snapshot_id,
                "as_of_ts_utc": _iso_z(point.as_of_ts_utc),
                "market_score": point.market_score,
            }
            for point in projection.history
        ],
        "reason": projection.reason,
        "per_market": {
            market: market_projection_to_json_dict(mp)
            for market, mp in sorted(projection.per_market.items())
        },
    }
