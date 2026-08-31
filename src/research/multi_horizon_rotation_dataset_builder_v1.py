from __future__ import annotations

"""Pure dataset-builder primitives for Issue #593 validation artifacts.

This module contains only deterministic source-span, PIT baseline and exact-boundary
return logic. Database access and artifact I/O live in the bounded runner.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import log
from typing import Iterable, Mapping, Sequence

from src.research.multi_horizon_rotation_replay_v1 import CandidateSpec
from src.research.multi_horizon_rotation_validation_v1 import derive_chronological_split, ensure_utc


SAMPLE_INTERVAL = timedelta(minutes=15)
MAX_CANDIDATE_LOOKBACK = timedelta(hours=36)
MINIMUM_COHORT = 20
ROTATION_V1_MODEL_VERSION = "1.0"


@dataclass(frozen=True)
class AssetCoverage:
    asset_id: int
    first_close_ts: datetime
    last_close_ts: datetime


@dataclass(frozen=True)
class SourceSpan:
    start: datetime
    end: datetime
    minimum_cohort: int
    coverage_asset_count: int
    rotation_v1_first_ts: datetime


@dataclass(frozen=True)
class RotationV1Point:
    asof_ts: datetime
    score_total: float
    pressure_state: str


class RotationV1PitIndex:
    def __init__(self, points_by_asset: Mapping[int, Sequence[RotationV1Point]]) -> None:
        self._timestamps: dict[int, tuple[datetime, ...]] = {}
        self._points: dict[int, tuple[RotationV1Point, ...]] = {}
        for asset_id, raw_points in points_by_asset.items():
            points = tuple(sorted(raw_points, key=lambda item: ensure_utc(item.asof_ts)))
            timestamps = tuple(ensure_utc(item.asof_ts) for item in points)
            if len(set(timestamps)) != len(timestamps):
                raise ValueError(f"duplicate Rotation V1 PIT timestamp for asset_id={asset_id}")
            self._timestamps[int(asset_id)] = timestamps
            self._points[int(asset_id)] = points

    def latest_at_or_before(self, *, asset_id: int, asof_ts: datetime) -> RotationV1Point | None:
        timestamps = self._timestamps.get(int(asset_id))
        if not timestamps:
            return None
        target = ensure_utc(asof_ts)
        index = bisect_right(timestamps, target) - 1
        if index < 0:
            return None
        return self._points[int(asset_id)][index]


def ceil_to_15m(value: datetime) -> datetime:
    value = ensure_utc(value)
    seconds = int(value.timestamp())
    step = int(SAMPLE_INTERVAL.total_seconds())
    rounded = ((seconds + step - 1) // step) * step
    return datetime.fromtimestamp(rounded, tz=UTC)


def floor_to_15m(value: datetime) -> datetime:
    value = ensure_utc(value)
    seconds = int(value.timestamp())
    step = int(SAMPLE_INTERVAL.total_seconds())
    rounded = (seconds // step) * step
    return datetime.fromtimestamp(rounded, tz=UTC)


def _nth_smallest(values: Sequence[datetime], n: int) -> datetime:
    if n < 1 or len(values) < n:
        raise ValueError("insufficient source coverage for minimum cohort")
    return sorted(values)[n - 1]


def _nth_largest(values: Sequence[datetime], n: int) -> datetime:
    if n < 1 or len(values) < n:
        raise ValueError("insufficient source coverage for minimum cohort")
    return sorted(values, reverse=True)[n - 1]


def derive_common_source_span(
    *,
    coverage: Iterable[AssetCoverage],
    rotation_v1_first_ts: datetime,
    minimum_cohort: int = MINIMUM_COHORT,
    max_candidate_lookback: timedelta = MAX_CANDIDATE_LOOKBACK,
) -> SourceSpan:
    rows = list(coverage)
    if minimum_cohort < 1:
        raise ValueError("minimum_cohort must be positive")
    if len(rows) < minimum_cohort:
        raise ValueError("insufficient assets for minimum cohort")

    eligible_starts: list[datetime] = []
    eligible_ends: list[datetime] = []
    seen_assets: set[int] = set()
    for row in rows:
        if row.asset_id in seen_assets:
            raise ValueError(f"duplicate coverage row for asset_id={row.asset_id}")
        seen_assets.add(row.asset_id)
        first = ensure_utc(row.first_close_ts)
        last = ensure_utc(row.last_close_ts)
        if last < first:
            raise ValueError(f"invalid coverage interval for asset_id={row.asset_id}")
        eligible_starts.append(first + max_candidate_lookback)
        eligible_ends.append(last)

    candidate_start = _nth_smallest(eligible_starts, minimum_cohort)
    candidate_end = _nth_largest(eligible_ends, minimum_cohort)
    start = ceil_to_15m(max(candidate_start, ensure_utc(rotation_v1_first_ts)))
    end = floor_to_15m(candidate_end)
    if end <= start:
        raise ValueError("common source span is empty after coverage constraints")

    # Freeze the split here as a validation of span sufficiency. The caller may
    # serialize the returned boundaries, but cannot choose alternate proportions.
    derive_chronological_split(start=start, end=end)
    return SourceSpan(
        start=start,
        end=end,
        minimum_cohort=minimum_cohort,
        coverage_asset_count=len(rows),
        rotation_v1_first_ts=ensure_utc(rotation_v1_first_ts),
    )


def split_manifest_payload(span: SourceSpan) -> dict[str, object]:
    splits = derive_chronological_split(start=span.start, end=span.end)

    def iso(value: datetime) -> str:
        return ensure_utc(value).isoformat().replace("+00:00", "Z")

    return {
        "manifest_version": "1.0.0",
        "source_span_method": "minimum_cohort_coverage_envelope_plus_rotation_v1_first_pit",
        "minimum_cohort": span.minimum_cohort,
        "coverage_asset_count": span.coverage_asset_count,
        "source_span": {"start": iso(span.start), "end": iso(span.end)},
        "rotation_v1_first_ts": iso(span.rotation_v1_first_ts),
        "final_holdout_inspected": False,
        "splits": {
            phase: {"start": iso(bounds[0]), "end": iso(bounds[1])}
            for phase, bounds in splits.items()
        },
    }


def exact_log_return(
    *,
    close_by_ts: Mapping[datetime, Decimal],
    start_ts: datetime,
    end_ts: datetime,
) -> float | None:
    start = ensure_utc(start_ts)
    end = ensure_utc(end_ts)
    start_close = close_by_ts.get(start)
    end_close = close_by_ts.get(end)
    if start_close is None or end_close is None or start_close <= 0 or end_close <= 0:
        return None
    return log(float(end_close / start_close))


def comparable_horizon_return(
    *,
    close_by_ts: Mapping[datetime, Decimal],
    asof_ts: datetime,
    spec: CandidateSpec,
) -> float | None:
    asof = ensure_utc(asof_ts)
    return exact_log_return(
        close_by_ts=close_by_ts,
        start_ts=asof - spec.horizon,
        end_ts=asof,
    )


def forward_response(
    *,
    close_by_ts: Mapping[datetime, Decimal],
    asof_ts: datetime,
    horizon: timedelta,
    phase_end: datetime,
) -> float | None:
    asof = ensure_utc(asof_ts)
    endpoint = asof + horizon
    if endpoint >= ensure_utc(phase_end):
        return None
    return exact_log_return(
        close_by_ts=close_by_ts,
        start_ts=asof,
        end_ts=endpoint,
    )
