from __future__ import annotations

"""Research-only deterministic replay engine for Issue #593.

Implements the frozen C1/C2/C3 candidate definitions from
``docs/research/multi_horizon_rotation_candidate_definition_v1.md``.

This module is market-only and account-agnostic. It does not write production
state and does not emit trading permission or execution intent.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from typing import Iterable, Mapping


INPUT_INTERVAL = timedelta(minutes=15)
MINIMUM_COHORT = 20
MAD_SCALE = Decimal("1.4826")
ROBUST_Z_DIVISOR = Decimal("3")
EPSILON = Decimal("1e-12")
DEGENERATE_MAD_THRESHOLD = Decimal("1e-12")
SCORE_QUANTUM = Decimal("0.000001")
MODEL_ID = "multi_horizon_rotation_relative_flow"
OBSERVED_LIFECYCLE = "UNMEASURED"
PROVENANCE = "obs_market_candle:15m:close_price+volume_base;owner=public_candle_freshness_writer"
DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    model_version: str
    horizon_minutes: int
    effective_horizon: str

    @property
    def horizon(self) -> timedelta:
        return timedelta(minutes=self.horizon_minutes)

    @property
    def candles_per_window(self) -> int:
        return self.horizon_minutes // 15

    @property
    def lookback_horizon(self) -> str:
        return f"current_{self.horizon_minutes}m_plus_previous_8_completed_{self.horizon_minutes}m_windows"


CANDIDATE_SPECS = (
    CandidateSpec("C1", "1.0.0-c1", 15, "VERY_SHORT"),
    CandidateSpec("C2", "1.0.0-c2", 60, "SHORT"),
    CandidateSpec("C3", "1.0.0-c3", 240, "MID"),
)


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    close_price: Decimal
    volume_base: Decimal


@dataclass(frozen=True)
class CandidateResult:
    venue: str
    asset_id: int
    candidate_id: str
    model_id: str
    model_version: str
    input_interval: str
    lookback_horizon: str
    effective_horizon: str
    observed_lifecycle: str
    asof_ts: datetime
    freshness: str
    provenance: str
    cohort_size: int
    relative_return_unit: Decimal | None
    signed_flow_unit: Decimal | None
    relative_acceleration_unit: Decimal | None
    rotation_score: Decimal | None
    data_quality: str
    reason: str


@dataclass(frozen=True)
class _AssetPrimitives:
    asset_id: int
    returns: tuple[Decimal, ...]
    volumes: tuple[Decimal, ...]


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_on_15m_close_grid(value: datetime) -> bool:
    value = ensure_utc(value)
    return value.second == 0 and value.microsecond == 0 and value.minute % 15 == 0


def median(values: Iterable[Decimal]) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def robust_normalize(values_by_asset: Mapping[int, Decimal]) -> dict[int, Decimal] | None:
    if not values_by_asset:
        return None
    center = median(values_by_asset.values())
    mad = median(abs(value - center) for value in values_by_asset.values())
    if mad <= DEGENERATE_MAD_THRESHOLD:
        return None
    scale = MAD_SCALE * mad
    return {
        asset_id: max(
            Decimal("-1"),
            min(Decimal("1"), ((value - center) / scale) / ROBUST_Z_DIVISOR),
        )
        for asset_id, value in values_by_asset.items()
    }


def _expected_boundary_times(asof_ts: datetime, spec: CandidateSpec) -> tuple[datetime, ...]:
    asof = ensure_utc(asof_ts)
    if not is_on_15m_close_grid(asof):
        raise ValueError("ASOF_NOT_ON_15M_CLOSE_GRID")
    boundaries = tuple(asof - spec.horizon * offset for offset in range(10))
    if any(not is_on_15m_close_grid(value) for value in boundaries):
        raise ValueError("WINDOW_BOUNDARY_NOT_ON_15M_CLOSE_GRID")
    return boundaries


def _build_asset_primitives(
    *, asset_id: int, candles: Iterable[Candle], asof_ts: datetime, spec: CandidateSpec
) -> _AssetPrimitives | None:
    boundaries = _expected_boundary_times(asof_ts, spec)
    candle_map: dict[datetime, Candle] = {}
    for candle in candles:
        ts = ensure_utc(candle.close_ts_utc)
        if ts > ensure_utc(asof_ts):
            continue
        if not is_on_15m_close_grid(ts) or candle.close_price <= 0 or candle.volume_base < 0:
            return None
        if ts in candle_map:
            return None
        candle_map[ts] = candle

    returns: list[Decimal] = []
    volumes: list[Decimal] = []
    for window_index in range(9):
        end = boundaries[window_index]
        start = boundaries[window_index + 1]
        start_candle = candle_map.get(start)
        end_candle = candle_map.get(end)
        if start_candle is None or end_candle is None:
            return None
        expected_close_times = tuple(
            start + INPUT_INTERVAL * step for step in range(1, spec.candles_per_window + 1)
        )
        if expected_close_times[-1] != end or any(ts not in candle_map for ts in expected_close_times):
            return None
        volumes.append(sum((candle_map[ts].volume_base for ts in expected_close_times), Decimal("0")))
        returns.append((end_candle.close_price / start_candle.close_price).ln())
    return _AssetPrimitives(asset_id=asset_id, returns=tuple(returns), volumes=tuple(volumes))


def _result(
    *, venue: str, asset_id: int, spec: CandidateSpec, asof: datetime, cohort_size: int,
    data_quality: str, reason: str, relative_return_unit: Decimal | None = None,
    signed_flow_unit: Decimal | None = None, relative_acceleration_unit: Decimal | None = None,
    rotation_score: Decimal | None = None,
) -> CandidateResult:
    freshness = "FRESH" if data_quality == "COMPLETE" else "INSUFFICIENT_DATA"
    return CandidateResult(
        venue=venue,
        asset_id=asset_id,
        candidate_id=spec.candidate_id,
        model_id=MODEL_ID,
        model_version=spec.model_version,
        input_interval="15m",
        lookback_horizon=spec.lookback_horizon,
        effective_horizon=spec.effective_horizon,
        observed_lifecycle=OBSERVED_LIFECYCLE,
        asof_ts=asof,
        freshness=freshness,
        provenance=PROVENANCE,
        cohort_size=cohort_size,
        relative_return_unit=relative_return_unit,
        signed_flow_unit=signed_flow_unit,
        relative_acceleration_unit=relative_acceleration_unit,
        rotation_score=rotation_score,
        data_quality=data_quality,
        reason=reason,
    )


def evaluate_candidate(
    *, candles_by_asset: Mapping[int, Iterable[Candle]], asof_ts: datetime,
    spec: CandidateSpec, venue: str = "bitvavo", minimum_cohort: int = MINIMUM_COHORT,
) -> list[CandidateResult]:
    with localcontext(DECIMAL_CONTEXT):
        asof = ensure_utc(asof_ts)
        try:
            _expected_boundary_times(asof, spec)
        except ValueError as exc:
            return [
                _result(venue=venue, asset_id=asset_id, spec=spec, asof=asof, cohort_size=0,
                        data_quality="INSUFFICIENT_DATA", reason=str(exc))
                for asset_id in sorted(candles_by_asset)
            ]

        primitives: dict[int, _AssetPrimitives] = {}
        for asset_id, candles in candles_by_asset.items():
            built = _build_asset_primitives(asset_id=asset_id, candles=candles, asof_ts=asof, spec=spec)
            if built is not None:
                primitives[asset_id] = built

        cohort_size = len(primitives)
        if cohort_size < minimum_cohort:
            return [
                _result(venue=venue, asset_id=asset_id, spec=spec, asof=asof, cohort_size=cohort_size,
                        data_quality="INSUFFICIENT_DATA", reason="COHORT_BELOW_MINIMUM")
                for asset_id in sorted(candles_by_asset)
            ]

        median_return_w0 = median(item.returns[0] for item in primitives.values())
        median_return_w1 = median(item.returns[1] for item in primitives.values())
        rr0 = {asset_id: item.returns[0] - median_return_w0 for asset_id, item in primitives.items()}
        rr1 = {asset_id: item.returns[1] - median_return_w1 for asset_id, item in primitives.items()}
        relative_return_unit = robust_normalize(rr0)

        volume_log_ratio: dict[int, Decimal] = {}
        for asset_id, item in primitives.items():
            volume_ref = median(item.volumes[1:9])
            if volume_ref > 0:
                volume_log_ratio[asset_id] = ((item.volumes[0] + EPSILON) / (volume_ref + EPSILON)).ln()
        volume_surprise_unit = robust_normalize(volume_log_ratio)
        accel_raw = {asset_id: rr0[asset_id] - rr1[asset_id] for asset_id in primitives}
        relative_acceleration_unit = robust_normalize(accel_raw)

        normalized_available = all(
            component is not None
            for component in (relative_return_unit, volume_surprise_unit, relative_acceleration_unit)
        )

        results: list[CandidateResult] = []
        for asset_id in sorted(candles_by_asset):
            if asset_id not in primitives or not normalized_available or asset_id not in volume_log_ratio:
                results.append(_result(
                    venue=venue, asset_id=asset_id, spec=spec, asof=asof, cohort_size=cohort_size,
                    data_quality="INSUFFICIENT_DATA", reason="MISSING_OR_DEGENERATE_COMPONENT",
                ))
                continue
            rr_unit = relative_return_unit[asset_id]  # type: ignore[index]
            flow_surprise = volume_surprise_unit[asset_id]  # type: ignore[index]
            sign = Decimal("1") if rr0[asset_id] > 0 else Decimal("-1") if rr0[asset_id] < 0 else Decimal("0")
            signed_flow = sign * flow_surprise
            accel_unit = relative_acceleration_unit[asset_id]  # type: ignore[index]
            score = (Decimal("100") * (rr_unit + signed_flow + accel_unit) / Decimal("3")).quantize(
                SCORE_QUANTUM, rounding=ROUND_HALF_UP
            )
            results.append(_result(
                venue=venue, asset_id=asset_id, spec=spec, asof=asof, cohort_size=cohort_size,
                data_quality="COMPLETE", reason="OK", relative_return_unit=rr_unit,
                signed_flow_unit=signed_flow, relative_acceleration_unit=accel_unit, rotation_score=score,
            ))
        return results
