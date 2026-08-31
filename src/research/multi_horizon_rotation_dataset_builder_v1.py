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
            self._timestamps[int(asset_id)] = tuple(ensure_utc(item.asof_ts) for item in points)
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


def observed_asset_ids_at_asof(coverage: Iterable[AssetCoverage], *, asof_ts: datetime) -> tuple[int, ...]:
    """Assets first observed by as-of, without future-listing or current-universe backfill."""
    target = ensure_utc(asof_ts)
    seen: set[int] = set()
    out: list[int] = []
    for row in coverage:
        if row.asset_id in seen:
            raise ValueError(f"duplicate coverage row for asset_id={row.asset_id}")
        seen.add(row.asset_id)
        if ensure_utc(row.first_close_ts) <= target:
            out.append(row.asset_id)
    return tuple(sorted(out))


def _longest_minimum_cohort_region(
    *, intervals: Sequence[tuple[datetime, datetime]], minimum_cohort: int
) -> tuple[datetime, datetime]:
    """Return longest half-open 15m-grid region with >= minimum_cohort intervals active."""
    events: dict[datetime, int] = {}
    for start, last_inclusive in intervals:
        start = ceil_to_15m(start)
        last_inclusive = floor_to_15m(last_inclusive)
        if last_inclusive < start:
            continue
        end_exclusive = last_inclusive + SAMPLE_INTERVAL
        events[start] = events.get(start, 0) + 1
        events[end_exclusive] = events.get(end_exclusive, 0) - 1
    if not events:
        raise ValueError("no eligible source coverage intervals")

    times = sorted(events)
    active = 0
    region_start: datetime | None = None
    regions: list[tuple[datetime, datetime]] = []
    for index, ts in enumerate(times):
        active += events[ts]
        next_ts = times[index + 1] if index + 1 < len(times) else None
        if active >= minimum_cohort and next_ts is not None and next_ts > ts:
            if region_start is None:
                region_start = ts
        elif region_start is not None:
            regions.append((region_start, ts))
            region_start = None
    if region_start is not None:
        regions.append((region_start, times[-1]))

    valid = [region for region in regions if region[1] > region[0]]
    if not valid:
        raise ValueError("no contiguous source span satisfies minimum cohort")
    return max(valid, key=lambda item: (item[1] - item[0], -item[0].timestamp()))


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

    rotation_floor = ceil_to_15m(rotation_v1_first_ts)
    intervals: list[tuple[datetime, datetime]] = []
    seen_assets: set[int] = set()
    for row in rows:
        if row.asset_id in seen_assets:
            raise ValueError(f"duplicate coverage row for asset_id={row.asset_id}")
        seen_assets.add(row.asset_id)
        first = ensure_utc(row.first_close_ts)
        last = ensure_utc(row.last_close_ts)
        if last < first:
            raise ValueError(f"invalid coverage interval for asset_id={row.asset_id}")
        eligible_start = max(first + max_candidate_lookback, rotation_floor)
        intervals.append((eligible_start, last))

    start, end = _longest_minimum_cohort_region(intervals=intervals, minimum_cohort=minimum_cohort)

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
        "source_span_method": "longest_contiguous_minimum_cohort_coverage_plus_rotation_v1_first_pit",
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
