from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.research.breath_curve_template_matcher_v1 import (
    MARKERS,
    Candle,
    MarkerMatch,
    gt,
    iso,
    load_db,
    lt,
    parse_dt,
    parse_offsets,
)


VERSION = "0.1"


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


def eval_rule(flags: dict[str, bool | None], key: str, value: bool | None) -> None:
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

    eval_rule(flags, "first_lift_above_anchor", gt(first_high, ap) if first_high is not None else None)
    eval_rule(flags, "first_dip_below_first_lift", lt(first_low, first_high) if first_low is not None and first_high is not None else None)
    eval_rule(flags, "second_peak_above_first_dip", gt(second_high, first_low) if second_high is not None and first_low is not None else None)
    eval_rule(flags, "second_peak_retests_first_lift", gt(second_high, first_high, 0.025) if second_high is not None and first_high is not None else None)
    eval_rule(flags, "second_dip_below_second_peak", lt(second_low, second_high) if second_low is not None and second_high is not None else None)
    eval_rule(flags, "second_dip_higher_than_first_dip", gt(second_low, first_low) if second_low is not None and first_low is not None else None)
    eval_rule(flags, "ignition_above_second_dip", gt(ignition, second_low) if ignition is not None and second_low is not None else None)
    eval_rule(flags, "pulse_above_ignition", gt(pulse, ignition) if pulse is not None and ignition is not None else None)
    eval_rule(flags, "pulse_above_second_peak", gt(pulse, second_high) if pulse is not None and second_high is not None else None)

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

    available = [flags[k] for k in core_keys if flags[k] is not None]
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

    due_markers = [m for m in markers if m["status"] != "FUTURE"]
    observed_markers = [m for m in due_markers if m["matched"]]

    if due_markers:
        coverage = len(observed_markers) / len(due_markers)
        timing = sum(float(m["timing_score"]) for m in observed_markers) / len(due_markers)
    else:
        coverage = 0.0
        timing = 0.0

    shape, flags, available_rule_count, passed_rule_count = partial_shape(candles, anchor, markers)

    notes: list[str] = []
    required_ratio_due = True

    if required_ratio is not None:
        required_marker = next(
            (m for m in markers if abs(float(m["ratio"]) - required_ratio) < 1e-9),
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
    if any(m["status"] == "OBSERVED_PARTIAL_WINDOW" for m in markers):
        notes.append("HAS_PARTIAL_MARKER_WINDOW")
    if any(m["status"] == "FUTURE" for m in markers):
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


def print_result(result: PartialResult) -> None:
    print(f"partial_matcher=breath_curve_template_partial_v1 version={VERSION}")
    print(f"symbol={result.symbol} venue={result.venue} interval={result.interval_code}")
    print(f"anchor={result.anchor_ts_utc} as_of={result.as_of_ts_utc}")
    print(f"cycle_days={result.cycle_days} offset_days={result.phase_offset_days} required_ratio={result.required_ratio}")
    print(f"partial_match_score={result.partial_match_score:.4f}")
    print(f"shape={result.partial_shape_score:.4f} timing={result.partial_timing_score:.4f} coverage={result.marker_coverage_score:.4f}")
    print(f"observed_markers={result.observed_marker_count} due_markers={result.due_marker_count}")
    print(f"shape_rules={result.passed_shape_rule_count}/{result.available_shape_rule_count}")
    print(f"notes={','.join(result.notes) if result.notes else 'None'}")
    print("")
    print("flags:")
    for key, value in result.flags.items():
        print(f"  {key}={value}")
    print("")
    print("markers:")
    for marker in result.markers:
        price = "None" if marker["observed_price"] is None else f'{float(marker["observed_price"]):.8f}'
        print(
            f'  {marker["ratio"]:.3f} {marker["code"]:26s} '
            f'status={marker["status"]:23s} '
            f'expected={marker["expected_ts_utc"]} '
            f'observed={marker["observed_ts_utc"]} '
            f'price={price} '
            f'score={float(marker["timing_score"]):.4f}'
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Partial-cycle research-only breath curve matcher with as-of cutoff."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--anchor-date", required=True)
    parser.add_argument("--as-of-ts", required=True)
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument("--offsets", default="-10.5,-7,-5,-3,0,3,5,7,10.5")
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument("--min-due-markers", type=int, default=3)
    parser.add_argument("--required-ratio", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    anchor = parse_dt(args.anchor_date)
    as_of = parse_dt(args.as_of_ts)
    offsets = parse_offsets(args.offsets)

    if as_of < anchor + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours):
        raise RuntimeError("as-of timestamp is too early for the tested offset grid.")

    query_start = anchor + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours + 48)
    query_end = as_of

    candles = load_db(
        symbol=args.symbol,
        asset_id=None,
        venue=args.venue,
        interval_code=args.interval_code,
        start=query_start,
        end=query_end,
    )

    if len(candles) < 3:
        raise RuntimeError(f"Not enough candles loaded before as-of: {len(candles)}")

    results = [
        partial_match(
            candles=candles,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=args.interval_code,
            anchor=anchor,
            as_of=as_of,
            cycle_days=args.cycle_days,
            offset_days=offset,
            tolerance_hours=args.tolerance_hours,
            min_due_markers=args.min_due_markers,
            required_ratio=args.required_ratio,
        )
        for offset in offsets
    ]

    best = max(results, key=lambda r: r.partial_match_score)

    if args.json:
        print(json.dumps(
            {
                "matcher": "breath_curve_template_partial_v1",
                "version": VERSION,
                "best": asdict(best),
                "all_offsets": [asdict(r) for r in results],
            },
            indent=2,
            sort_keys=True,
        ))
    else:
        print_result(best)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
