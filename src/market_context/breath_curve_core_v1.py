from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


CORE_VERSION = "0.1"

MARKERS = [
    (0.236, "FIRST_LIFT_HIGH", "HIGH"),
    (0.382, "FIRST_DIP_LOW", "LOW"),
    (0.500, "SECOND_PEAK_RETEST_HIGH", "HIGH"),
    (0.618, "SECOND_DIP_HIGHER_LOW", "LOW"),
    (0.786, "IGNITION_PRE_SPIKE", "HIGH"),
    (1.000, "MAIN_PULSE_TP_HIGH", "HIGH"),
    (1.272, "OVERSHOOT_EXTENSION_TP", "HIGH"),
]


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class MarkerMatch:
    ratio: float
    code: str
    kind: str
    expected_ts_utc: str
    observed_ts_utc: str | None
    observed_price: float | None
    timing_error_hours: float | None
    timing_score: float
    matched: bool


@dataclass(frozen=True)
class MatchResult:
    symbol: str
    venue: str | None
    interval_code: str | None
    anchor_ts_utc: str
    cycle_days: float
    phase_offset_days: float
    tolerance_hours: float
    template_match_score: float
    shape_score: float
    timing_score: float
    flags: dict[str, bool]
    markers: list[MarkerMatch]


@dataclass(frozen=True)
class PartialResult:
    symbol: str
    venue: str
    interval_code: str
    anchor_ts_utc: str
    as_of_ts_utc: str
    cycle_days: float
    phase_offset_days: float
    tolerance_hours: float
    required_ratio: float | None
    partial_match_score: float
    partial_shape_score: float
    partial_timing_score: float
    marker_coverage_score: float
    observed_marker_count: int
    due_marker_count: int
    available_shape_rule_count: int
    passed_shape_rule_count: int
    flags: dict[str, bool | None]
    markers: list[dict[str, Any]]
    notes: list[str]


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_offsets(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def gt(a: float | None, b: float | None, tolerance_pct: float = 0.0) -> bool:
    return a is not None and b is not None and a > b * (1.0 - tolerance_pct)


def lt(a: float | None, b: float | None, tolerance_pct: float = 0.0) -> bool:
    return a is not None and b is not None and a < b * (1.0 + tolerance_pct)


def find_marker(
    candles: list[Candle],
    ratio: float,
    code: str,
    kind: str,
    expected: datetime,
    tolerance_hours: float,
) -> MarkerMatch:
    start = expected - timedelta(hours=tolerance_hours)
    end = expected + timedelta(hours=tolerance_hours)
    window = [c for c in candles if start <= c.ts <= end]

    if not window:
        return MarkerMatch(ratio, code, kind, iso(expected), None, None, None, 0.0, False)

    if kind == "LOW":
        chosen = min(window, key=lambda c: c.low)
        observed_price = chosen.low
    else:
        chosen = max(window, key=lambda c: c.high)
        observed_price = chosen.high

    err = abs((chosen.ts - expected).total_seconds()) / 3600.0
    score = max(0.0, 1.0 - (err / max(tolerance_hours, 1.0)))

    return MarkerMatch(
        ratio=ratio,
        code=code,
        kind=kind,
        expected_ts_utc=iso(expected),
        observed_ts_utc=iso(chosen.ts),
        observed_price=observed_price,
        timing_error_hours=round(err, 3),
        timing_score=round(score, 4),
        matched=True,
    )


def get_price(markers: list[MarkerMatch], code: str) -> float | None:
    for marker in markers:
        if marker.code == code and marker.matched:
            return marker.observed_price
    return None


def shape_score(candles: list[Candle], anchor: datetime, markers: list[MarkerMatch]) -> tuple[float, dict[str, bool]]:
    anchor_candles = [c for c in candles if c.ts <= anchor]
    anchor_price = anchor_candles[-1].close if anchor_candles else candles[0].close

    first_high = get_price(markers, "FIRST_LIFT_HIGH")
    first_low = get_price(markers, "FIRST_DIP_LOW")
    second_high = get_price(markers, "SECOND_PEAK_RETEST_HIGH")
    second_low = get_price(markers, "SECOND_DIP_HIGHER_LOW")
    ignition = get_price(markers, "IGNITION_PRE_SPIKE")
    pulse = get_price(markers, "MAIN_PULSE_TP_HIGH")
    overshoot = get_price(markers, "OVERSHOOT_EXTENSION_TP")

    flags = {
        "first_lift_above_anchor": gt(first_high, anchor_price),
        "first_dip_below_first_lift": lt(first_low, first_high),
        "second_peak_above_first_dip": gt(second_high, first_low),
        "second_peak_retests_first_lift": gt(second_high, first_high, 0.025),
        "second_dip_below_second_peak": lt(second_low, second_high),
        "second_dip_higher_than_first_dip": gt(second_low, first_low),
        "ignition_above_second_dip": gt(ignition, second_low),
        "pulse_above_ignition": gt(pulse, ignition),
        "pulse_above_second_peak": gt(pulse, second_high),
        "overshoot_above_pulse": gt(overshoot, pulse),
    }

    core = [
        "first_lift_above_anchor",
        "first_dip_below_first_lift",
        "second_peak_above_first_dip",
        "second_dip_below_second_peak",
        "second_dip_higher_than_first_dip",
        "ignition_above_second_dip",
        "pulse_above_ignition",
        "pulse_above_second_peak",
    ]

    return round(sum(1 for key in core if flags[key]) / len(core), 4), flags


def match(
    candles: list[Candle],
    symbol: str,
    venue: str | None,
    interval_code: str | None,
    anchor: datetime,
    cycle_days: float,
    offset_days: float,
    tolerance_hours: float,
) -> MatchResult:
    markers: list[MarkerMatch] = []

    for ratio, code, kind in MARKERS:
        expected = anchor + timedelta(days=(cycle_days * ratio) + offset_days)
        markers.append(find_marker(candles, ratio, code, kind, expected, tolerance_hours))

    s_score, flags = shape_score(candles, anchor, markers)
    t_score = round(sum(marker.timing_score for marker in markers) / len(markers), 4)
    total = round((0.60 * s_score) + (0.40 * t_score), 4)

    return MatchResult(
        symbol=symbol,
        venue=venue,
        interval_code=interval_code,
        anchor_ts_utc=iso(anchor),
        cycle_days=cycle_days,
        phase_offset_days=offset_days,
        tolerance_hours=tolerance_hours,
        template_match_score=total,
        shape_score=s_score,
        timing_score=t_score,
        flags=flags,
        markers=markers,
    )


def expected_marker_ts(anchor: datetime, cycle_days: float, ratio: float, offset_days: float) -> datetime:
    return anchor + timedelta(days=(cycle_days * ratio) + offset_days)


def anchor_price(candles: list[Candle], anchor: datetime) -> float:
    before = [c for c in candles if c.ts <= anchor]
    if before:
        return before[-1].close
    return candles[0].close


def find_partial_marker(
    candles: list[Candle],
    ratio: float,
    code: str,
    kind: str,
    expected: datetime,
    as_of: datetime,
    tolerance_hours: float,
) -> dict[str, Any]:
    if expected > as_of:
        return {
            "ratio": ratio,
            "code": code,
            "kind": kind,
            "status": "FUTURE",
            "expected_ts_utc": iso(expected),
            "observed_ts_utc": None,
            "observed_price": None,
            "timing_error_hours": None,
            "timing_score": 0.0,
            "matched": False,
        }

    window_start = expected - timedelta(hours=tolerance_hours)
    window_end = min(expected + timedelta(hours=tolerance_hours), as_of)
    window = [c for c in candles if window_start <= c.ts <= window_end]

    if not window:
        return {
            "ratio": ratio,
            "code": code,
            "kind": kind,
            "status": "DUE_MISSING",
            "expected_ts_utc": iso(expected),
            "observed_ts_utc": None,
            "observed_price": None,
            "timing_error_hours": None,
            "timing_score": 0.0,
            "matched": False,
        }

    if kind == "LOW":
        chosen = min(window, key=lambda c: c.low)
        observed_price = chosen.low
    else:
        chosen = max(window, key=lambda c: c.high)
        observed_price = chosen.high

    err = abs((chosen.ts - expected).total_seconds()) / 3600.0
    score = max(0.0, 1.0 - (err / max(tolerance_hours, 1.0)))

    if as_of < expected + timedelta(hours=tolerance_hours):
        status = "OBSERVED_PARTIAL_WINDOW"
    else:
        status = "OBSERVED_CLOSED_WINDOW"

    return {
        "ratio": ratio,
        "code": code,
        "kind": kind,
        "status": status,
        "expected_ts_utc": iso(expected),
        "observed_ts_utc": iso(chosen.ts),
        "observed_price": observed_price,
        "timing_error_hours": round(err, 3),
        "timing_score": round(score, 4),
        "matched": True,
    }


def marker_price(markers: list[dict[str, Any]], code: str) -> float | None:
    for marker in markers:
        if marker["code"] == code and marker["matched"]:
            return marker["observed_price"]
    return None


def _eval_rule(flags: dict[str, bool | None], key: str, value: bool | None) -> None:
    flags[key] = value


def partial_shape(
    candles: list[Candle],
    anchor: datetime,
    markers: list[dict[str, Any]],
) -> tuple[float, dict[str, bool | None], int, int]:
    ap = anchor_price(candles, anchor)

    first_high = marker_price(markers, "FIRST_LIFT_HIGH")
    first_low = marker_price(markers, "FIRST_DIP_LOW")
    second_high = marker_price(markers, "SECOND_PEAK_RETEST_HIGH")
    second_low = marker_price(markers, "SECOND_DIP_HIGHER_LOW")
    ignition = marker_price(markers, "IGNITION_PRE_SPIKE")
    pulse = marker_price(markers, "MAIN_PULSE_TP_HIGH")

    flags: dict[str, bool | None] = {}

    _eval_rule(flags, "first_lift_above_anchor", gt(first_high, ap) if first_high is not None else None)
    _eval_rule(flags, "first_dip_below_first_lift", lt(first_low, first_high) if first_low is not None and first_high is not None else None)
    _eval_rule(flags, "second_peak_above_first_dip", gt(second_high, first_low) if second_high is not None and first_low is not None else None)
    _eval_rule(flags, "second_peak_retests_first_lift", gt(second_high, first_high, 0.025) if second_high is not None and first_high is not None else None)
    _eval_rule(flags, "second_dip_below_second_peak", lt(second_low, second_high) if second_low is not None and second_high is not None else None)
    _eval_rule(flags, "second_dip_higher_than_first_dip", gt(second_low, first_low) if second_low is not None and first_low is not None else None)
    _eval_rule(flags, "ignition_above_second_dip", gt(ignition, second_low) if ignition is not None and second_low is not None else None)
    _eval_rule(flags, "pulse_above_ignition", gt(pulse, ignition) if pulse is not None and ignition is not None else None)
    _eval_rule(flags, "pulse_above_second_peak", gt(pulse, second_high) if pulse is not None and second_high is not None else None)

    core_keys = [
        "first_lift_above_anchor",
        "first_dip_below_first_lift",
        "second_peak_above_first_dip",
        "second_dip_below_second_peak",
        "second_dip_higher_than_first_dip",
        "ignition_above_second_dip",
        "pulse_above_ignition",
        "pulse_above_second_peak",
    ]

    available = [flags[key] for key in core_keys if flags[key] is not None]
    if not available:
        return 0.0, flags, 0, 0

    passed = sum(1 for value in available if value is True)
    return round(passed / len(available), 4), flags, len(available), passed


def partial_match(
    candles: list[Candle],
    symbol: str,
    venue: str,
    interval_code: str,
    anchor: datetime,
    as_of: datetime,
    cycle_days: float,
    offset_days: float,
    tolerance_hours: float,
    min_due_markers: int,
    required_ratio: float | None,
) -> PartialResult:
    markers: list[dict[str, Any]] = []

    for ratio, code, kind in MARKERS:
        expected = expected_marker_ts(anchor, cycle_days, ratio, offset_days)
        markers.append(
            find_partial_marker(
                candles=candles,
                ratio=ratio,
                code=code,
                kind=kind,
                expected=expected,
                as_of=as_of,
                tolerance_hours=tolerance_hours,
            )
        )

    due_markers = [marker for marker in markers if marker["status"] != "FUTURE"]
    observed_markers = [marker for marker in due_markers if marker["matched"]]

    if due_markers:
        coverage = len(observed_markers) / len(due_markers)
        timing = sum(float(marker["timing_score"]) for marker in observed_markers) / len(due_markers)
    else:
        coverage = 0.0
        timing = 0.0

    shape, flags, available_rule_count, passed_rule_count = partial_shape(candles, anchor, markers)

    notes: list[str] = []
    required_ratio_due = True

    if required_ratio is not None:
        required_marker = next(
            (marker for marker in markers if abs(float(marker["ratio"]) - required_ratio) < 1e-9),
            None,
        )

        if required_marker is None:
            required_ratio_due = False
            notes.append("UNKNOWN_REQUIRED_RATIO")
        elif required_marker["status"] == "FUTURE":
            required_ratio_due = False
            notes.append("REQUIRED_RATIO_NOT_DUE")
        elif not required_marker["matched"]:
            required_ratio_due = False
            notes.append("REQUIRED_RATIO_NOT_MATCHED")

    if len(due_markers) < min_due_markers:
        notes.append("INSUFFICIENT_DUE_MARKERS")
    if any(marker["status"] == "OBSERVED_PARTIAL_WINDOW" for marker in markers):
        notes.append("HAS_PARTIAL_MARKER_WINDOW")
    if any(marker["status"] == "FUTURE" for marker in markers):
        notes.append("FUTURE_MARKERS_NOT_SCORED")

    if len(due_markers) < min_due_markers or not required_ratio_due:
        score = 0.0
    else:
        score = (0.55 * shape) + (0.30 * timing) + (0.15 * coverage)

    return PartialResult(
        symbol=symbol,
        venue=venue,
        interval_code=interval_code,
        anchor_ts_utc=iso(anchor),
        as_of_ts_utc=iso(as_of),
        cycle_days=cycle_days,
        phase_offset_days=offset_days,
        tolerance_hours=tolerance_hours,
        required_ratio=required_ratio,
        partial_match_score=round(score, 4),
        partial_shape_score=round(shape, 4),
        partial_timing_score=round(timing, 4),
        marker_coverage_score=round(coverage, 4),
        observed_marker_count=len(observed_markers),
        due_marker_count=len(due_markers),
        available_shape_rule_count=available_rule_count,
        passed_shape_rule_count=passed_rule_count,
        flags=flags,
        markers=markers,
        notes=notes,
    )


def nearest_band(offset: float | None, bands: list[float], width: float) -> str:
    if offset is None:
        return "UNCLEAR"

    best = min(bands, key=lambda band: abs(offset - band))
    distance = abs(offset - best)

    if distance <= width:
        return f"{best:+g}"

    return "DRIFT"
