from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from src.research.breath_curve_template_matcher_v1 import (
    Candle,
    MarkerMatch,
    load_db,
    match,
    parse_dt,
    parse_offsets,
)
from src.research.run_breath_curve_template_partial_v1 import partial_match


REPORT_NAME = "breath_curve_random_anchor_baseline_v2"
VERSION = "0.1"

POLICY_NAMES = (
    "0618_selected_minus8_v1",
    "0618_selected_minus7_v1",
    "0618_selected_early_band_v1",
)


@dataclass(frozen=True)
class PolicySpec:
    policy_name: str
    purpose: str


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expected_ts(anchor: datetime, cycle_days: float, ratio: float, offset_days: float) -> datetime:
    return anchor + timedelta(days=(cycle_days * ratio) + offset_days)


def nearest_band(offset: float | None, bands: list[float], width: float) -> str:
    if offset is None:
        return "UNCLEAR"

    best = min(bands, key=lambda band: abs(offset - band))
    if abs(offset - best) <= width:
        return f"{best:+g}"

    return "DRIFT"


def distance_bucket(distance: float | None) -> str:
    if distance is None:
        return "UNCLEAR"
    if distance <= 0.25:
        return "D00_EXACT_OR_NEAR"
    if distance <= 0.50:
        return "D05_WITHIN_0_5D"
    if distance <= 1.00:
        return "D10_WITHIN_1D"
    if distance <= 1.50:
        return "D15_WITHIN_1_5D"
    if distance <= 3.00:
        return "D30_WITHIN_3D"
    return "D99_FAR"


def phase_drift_bucket(selected_offset: float | None, best_offset: float | None) -> str:
    if selected_offset is None or best_offset is None:
        return "DRIFT_UNKNOWN"

    drift = best_offset - selected_offset

    if abs(drift) <= 0.50:
        return "DRIFT_FLAT_0_5D"
    if drift > 0 and drift <= 3.00:
        return "DRIFT_FORWARD_0_3D"
    if drift > 3.00 and drift <= 7.00:
        return "DRIFT_FORWARD_3_7D"
    if drift > 7.00:
        return "DRIFT_FORWARD_7D_PLUS"
    if drift < 0 and abs(drift) <= 3.00:
        return "DRIFT_BACKWARD_0_3D"
    return "DRIFT_BACKWARD_3D_PLUS"


def marker_by_code(markers: list[MarkerMatch], code: str) -> MarkerMatch | None:
    for marker in markers:
        if marker.code == code:
            return marker
    return None


def last_close_at_or_before(candles: list[Candle], ts: datetime) -> float | None:
    prior = [c for c in candles if c.ts <= ts]
    if not prior:
        return None
    return prior[-1].close


def pct_return(from_price: float | None, to_price: float | None) -> float | None:
    if from_price is None or to_price is None or from_price == 0:
        return None
    return round(((to_price / from_price) - 1.0) * 100.0, 4)


def fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return ""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    text = f"{number:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(no rows)")
        return

    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def policy_specs() -> list[PolicySpec]:
    return [
        PolicySpec(
            policy_name="0618_selected_minus8_v1",
            purpose="0.618 selected -8 early recognition",
        ),
        PolicySpec(
            policy_name="0618_selected_minus7_v1",
            purpose="0.618 selected -7 early recognition",
        ),
        PolicySpec(
            policy_name="0618_selected_early_band_v1",
            purpose="0.618 selected -7/-8 combined early recognition",
        ),
    ]


def policy_matches(row: dict[str, Any], policy_name: str) -> bool:
    if row.get("status") != "OK":
        return False

    if str(row.get("checkpoint_ratio")) != "0.618":
        return False

    selected_band = str(row.get("selected_band_w1_0"))

    if policy_name == "0618_selected_minus8_v1":
        return selected_band == "-8"

    if policy_name == "0618_selected_minus7_v1":
        return selected_band == "-7"

    if policy_name == "0618_selected_early_band_v1":
        return selected_band in {"-8", "-7"}

    raise RuntimeError(f"Unknown policy_name={policy_name}")


def generate_random_anchors(
    *,
    start: datetime,
    end: datetime,
    count: int,
    real_anchors: list[datetime],
    exclude_days: float,
    seed: int,
    symbol: str,
) -> list[datetime]:
    if end < start:
        raise RuntimeError(f"Invalid random window: start={iso(start)} end={iso(end)}")

    rng = random.Random(f"{seed}:{symbol}")
    total_days = max(0, int((end.date() - start.date()).days))
    real_dates = [anchor.date() for anchor in real_anchors]
    anchors: list[datetime] = []
    used_dates: set[str] = set()
    attempts = 0
    max_attempts = max(count * 100, 1000)

    while len(anchors) < count and attempts < max_attempts:
        attempts += 1
        day_offset = rng.randint(0, total_days)
        candidate = datetime.combine(
            start.date() + timedelta(days=day_offset),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )

        key = candidate.date().isoformat()
        if key in used_dates:
            continue

        too_close = any(abs((candidate.date() - real_date).days) <= exclude_days for real_date in real_dates)
        if too_close:
            continue

        used_dates.add(key)
        anchors.append(candidate)

    if len(anchors) < count:
        print(
            f"WARN symbol={symbol} requested_random_anchors={count} "
            f"generated={len(anchors)} window={start.date()}..{end.date()} "
            f"exclude_days={exclude_days}"
        )

    return sorted(anchors)


def load_symbol_candles(
    *,
    symbol: str,
    venue: str,
    interval_code: str,
    anchors: list[datetime],
    cycle_days: float,
    offsets: list[float],
    tolerance_hours: float,
) -> list[Candle]:
    query_start = min(anchors) + timedelta(days=min(offsets)) - timedelta(hours=tolerance_hours + 48)
    query_end = max(anchors) + timedelta(days=cycle_days * 1.272 + max(offsets)) + timedelta(
        hours=tolerance_hours + 48
    )

    return load_db(
        symbol=symbol,
        asset_id=None,
        venue=venue,
        interval_code=interval_code,
        start=query_start,
        end=query_end,
    )


def anchor_window_candles(
    *,
    candles: list[Candle],
    anchor: datetime,
    cycle_days: float,
    offsets: list[float],
    tolerance_hours: float,
) -> list[Candle]:
    start = anchor + timedelta(days=min(offsets)) - timedelta(hours=tolerance_hours + 48)
    end = anchor + timedelta(days=cycle_days * 1.272 + max(offsets)) + timedelta(
        hours=tolerance_hours + 48
    )
    return [candle for candle in candles if start <= candle.ts <= end]


def evaluate_anchor(
    *,
    source: str,
    symbol: str,
    anchor: datetime,
    candles: list[Candle],
    venue: str,
    interval_code: str,
    cycle_days: float,
    checkpoint: float,
    offsets: list[float],
    tolerance_hours: float,
    min_due_markers: int,
    future_target_ratio: float,
    bands: list[float],
) -> dict[str, Any]:
    try:
        full_candles = anchor_window_candles(
            candles=candles,
            anchor=anchor,
            cycle_days=cycle_days,
            offsets=offsets,
            tolerance_hours=tolerance_hours,
        )

        if len(full_candles) < 5:
            raise RuntimeError(f"Not enough full-cycle candles loaded: {len(full_candles)}")

        full_results = [
            match(
                candles=full_candles,
                symbol=symbol,
                venue=venue,
                interval_code=interval_code,
                anchor=anchor,
                cycle_days=cycle_days,
                offset_days=offset,
                tolerance_hours=tolerance_hours,
            )
            for offset in offsets
        ]

        best_full = max(full_results, key=lambda result: result.template_match_score)
        full_by_offset = {result.phase_offset_days: result for result in full_results}

        as_of = expected_ts(anchor, cycle_days, checkpoint, 0.0)
        partial_candles = [candle for candle in full_candles if candle.ts <= as_of]

        if len(partial_candles) < 3:
            raise RuntimeError(f"Not enough partial candles loaded: {len(partial_candles)}")

        ranked_candidates = []

        for offset in offsets:
            partial = partial_match(
                candles=partial_candles,
                symbol=symbol,
                venue=venue,
                interval_code=interval_code,
                anchor=anchor,
                as_of=as_of,
                cycle_days=cycle_days,
                offset_days=offset,
                tolerance_hours=tolerance_hours,
                min_due_markers=min_due_markers,
                required_ratio=checkpoint,
            )

            target_ts = expected_ts(anchor, cycle_days, future_target_ratio, offset)
            target_is_future = target_ts > as_of
            ranking_score = partial.partial_match_score if target_is_future else 0.0

            ranked_candidates.append((ranking_score, partial.partial_match_score, offset, partial, target_is_future))

        ranked_candidates.sort(reverse=True, key=lambda item: (item[0], item[1], item[2]))
        _, _, selected_offset, selected, target_is_future = ranked_candidates[0]

        same_full = full_by_offset[selected_offset]
        marker_1000 = marker_by_code(same_full.markers, "MAIN_PULSE_TP_HIGH")
        marker_1272 = marker_by_code(same_full.markers, "OVERSHOOT_EXTENSION_TP")
        as_of_close = last_close_at_or_before(full_candles, as_of)

        return_to_1000 = pct_return(
            as_of_close,
            marker_1000.observed_price if marker_1000 and marker_1000.matched else None,
        )
        return_to_1272 = pct_return(
            as_of_close,
            marker_1272.observed_price if marker_1272 and marker_1272.matched else None,
        )

        best_offset = best_full.phase_offset_days
        offset_distance = abs(selected_offset - best_offset)
        selected_band = nearest_band(selected_offset, bands, 1.0)
        best_band = nearest_band(best_offset, bands, 1.0)

        row = {
            "status": "OK",
            "source": source,
            "symbol": symbol,
            "anchor_ts_utc": iso(anchor),
            "checkpoint_ratio": f"{checkpoint:.3f}",
            "as_of_ts_utc": iso(as_of),
            "selected_partial_offset_days": selected_offset,
            "selected_band_w1_0": selected_band,
            "selected_partial_score": selected.partial_match_score,
            "selected_partial_shape": selected.partial_shape_score,
            "selected_partial_timing": selected.partial_timing_score,
            "selected_partial_coverage": selected.marker_coverage_score,
            "selected_partial_due_markers": selected.due_marker_count,
            "selected_partial_observed_markers": selected.observed_marker_count,
            "future_target_ratio": future_target_ratio,
            "future_target_is_future": target_is_future,
            "as_of_close": as_of_close,
            "return_to_1000_pct": return_to_1000,
            "return_to_1272_pct": return_to_1272,
            "same_offset_full_score": same_full.template_match_score,
            "same_offset_full_shape": same_full.shape_score,
            "same_offset_full_timing": same_full.timing_score,
            "best_full_offset_days": best_offset,
            "best_full_band_w1_0": best_band,
            "best_full_score": best_full.template_match_score,
            "best_full_shape": best_full.shape_score,
            "best_full_timing": best_full.timing_score,
            "offset_distance_days": offset_distance,
            "offset_distance_bucket": distance_bucket(offset_distance),
            "phase_drift_days": best_offset - selected_offset,
            "phase_drift_bucket": phase_drift_bucket(selected_offset, best_offset),
            "offset_matches_best_full_legacy": selected_offset == best_offset,
            "band_match_1_0": selected_band == best_band and selected_band not in {"DRIFT", "UNCLEAR"},
            "venue": venue,
            "interval_code": interval_code,
            "cycle_days": cycle_days,
            "tolerance_hours": tolerance_hours,
            "error": "",
        }

        for spec in policy_specs():
            row[spec.policy_name] = policy_matches(row, spec.policy_name)

        return row

    except Exception as exc:
        return {
            "status": "ERROR",
            "source": source,
            "symbol": symbol,
            "anchor_ts_utc": iso(anchor),
            "checkpoint_ratio": f"{checkpoint:.3f}",
            "error": str(exc),
            "venue": venue,
            "interval_code": interval_code,
            "cycle_days": cycle_days,
            "tolerance_hours": tolerance_hours,
        }


def numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = row.get(key)
        if value in ("", None):
            continue
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def summarize_returns(*, evaluated_rows: list[dict[str, Any]], selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ret1000 = numeric_values(selected_rows, "return_to_1000_pct")
    ret1272 = numeric_values(selected_rows, "return_to_1272_pct")
    partial = numeric_values(selected_rows, "selected_partial_score")

    def avg(items: list[float]) -> float | None:
        if not items:
            return None
        return round(sum(items) / len(items), 4)

    def med(items: list[float]) -> float | None:
        if not items:
            return None
        return round(float(median(items)), 4)

    def positive_rate(items: list[float]) -> float | None:
        if not items:
            return None
        return round(sum(1 for item in items if item > 0.0) / len(items) * 100.0, 4)

    eligible = len(selected_rows)
    evaluated = len(evaluated_rows)

    return {
        "evaluated_rows": evaluated,
        "eligible_rows": eligible,
        "selection_rate_pct": round(eligible / evaluated * 100.0, 4) if evaluated else None,
        "avg_partial_score": avg(partial),
        "avg_return_to_1000_pct": avg(ret1000),
        "median_return_to_1000_pct": med(ret1000),
        "positive_to_1000_pct": positive_rate(ret1000),
        "best_return_to_1000_pct": max(ret1000) if ret1000 else None,
        "worst_return_to_1000_pct": min(ret1000) if ret1000 else None,
        "avg_return_to_1272_pct": avg(ret1272),
        "median_return_to_1272_pct": med(ret1272),
        "positive_to_1272_pct": positive_rate(ret1272),
        "best_return_to_1272_pct": max(ret1272) if ret1272 else None,
        "worst_return_to_1272_pct": min(ret1272) if ret1272 else None,
    }


def build_policy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        for row in rows:
            if policy_matches(row, spec.policy_name):
                out.append(
                    {
                        **row,
                        "policy_name": spec.policy_name,
                        "policy_purpose": spec.purpose,
                    }
                )

    return out


def summary_by_policy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        for source in ("real", "random"):
            evaluated = [row for row in rows if row.get("source") == source and row.get("status") == "OK"]
            selected = [row for row in evaluated if policy_matches(row, spec.policy_name)]
            out.append(
                {
                    "policy_name": spec.policy_name,
                    "source": source,
                    **summarize_returns(evaluated_rows=evaluated, selected_rows=selected),
                }
            )

    return out


def comparison_by_policy(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = {(row["policy_name"], row["source"]): row for row in summary_rows}
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        real = grouped.get((spec.policy_name, "real"), {})
        random_row = grouped.get((spec.policy_name, "random"), {})

        real_avg = real.get("avg_return_to_1000_pct")
        random_avg = random_row.get("avg_return_to_1000_pct")
        real_sel = real.get("selection_rate_pct")
        random_sel = random_row.get("selection_rate_pct")

        out.append(
            {
                "policy_name": spec.policy_name,
                "real_evaluated": real.get("evaluated_rows"),
                "real_eligible": real.get("eligible_rows"),
                "real_selection_rate_pct": real_sel,
                "real_avg_1000": real_avg,
                "real_pos_1000": real.get("positive_to_1000_pct"),
                "real_worst_1000": real.get("worst_return_to_1000_pct"),
                "random_evaluated": random_row.get("evaluated_rows"),
                "random_eligible": random_row.get("eligible_rows"),
                "random_selection_rate_pct": random_sel,
                "random_avg_1000": random_avg,
                "random_pos_1000": random_row.get("positive_to_1000_pct"),
                "random_worst_1000": random_row.get("worst_return_to_1000_pct"),
                "edge_avg_1000": round(real_avg - random_avg, 4)
                if real_avg is not None and random_avg is not None
                else None,
                "selection_rate_delta": round(real_sel - random_sel, 4)
                if real_sel is not None and random_sel is not None
                else None,
            }
        )

    return out


def summary_by_policy_symbol(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    symbols = sorted({str(row.get("symbol")) for row in rows if row.get("status") == "OK"})
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        for symbol in symbols:
            for source in ("real", "random"):
                evaluated = [
                    row
                    for row in rows
                    if row.get("source") == source
                    and row.get("symbol") == symbol
                    and row.get("status") == "OK"
                ]
                selected = [row for row in evaluated if policy_matches(row, spec.policy_name)]
                out.append(
                    {
                        "policy_name": spec.policy_name,
                        "symbol": symbol,
                        "source": source,
                        **summarize_returns(evaluated_rows=evaluated, selected_rows=selected),
                    }
                )

    return out


def print_policy_comparison(rows: list[dict[str, Any]]) -> None:
    print("--- real vs same-symbol random anchors ---")
    print_table(
        [
            "policy",
            "real_eval",
            "real_elig",
            "real_sel",
            "real_avg1000",
            "real_pos",
            "real_worst",
            "rand_eval",
            "rand_elig",
            "rand_sel",
            "rand_avg1000",
            "rand_pos",
            "rand_worst",
            "edge1000",
            "sel_delta",
        ],
        [
            [
                str(row["policy_name"]),
                str(row["real_evaluated"]),
                str(row["real_eligible"]),
                fmt(row["real_selection_rate_pct"], 2),
                fmt(row["real_avg_1000"]),
                fmt(row["real_pos_1000"], 2),
                fmt(row["real_worst_1000"]),
                str(row["random_evaluated"]),
                str(row["random_eligible"]),
                fmt(row["random_selection_rate_pct"], 2),
                fmt(row["random_avg_1000"]),
                fmt(row["random_pos_1000"], 2),
                fmt(row["random_worst_1000"]),
                fmt(row["edge_avg_1000"]),
                fmt(row["selection_rate_delta"], 2),
            ]
            for row in rows
        ],
    )


def print_policy_source_summary(rows: list[dict[str, Any]]) -> None:
    print()
    print("--- policy source summary ---")
    print_table(
        [
            "policy",
            "source",
            "eval",
            "eligible",
            "sel_rate",
            "partial",
            "avg1000",
            "pos1000",
            "best1000",
            "worst1000",
            "avg1272",
            "pos1272",
            "best1272",
            "worst1272",
        ],
        [
            [
                str(row["policy_name"]),
                str(row["source"]),
                str(row["evaluated_rows"]),
                str(row["eligible_rows"]),
                fmt(row["selection_rate_pct"], 2),
                fmt(row["avg_partial_score"]),
                fmt(row["avg_return_to_1000_pct"]),
                fmt(row["positive_to_1000_pct"], 2),
                fmt(row["best_return_to_1000_pct"]),
                fmt(row["worst_return_to_1000_pct"]),
                fmt(row["avg_return_to_1272_pct"]),
                fmt(row["positive_to_1272_pct"], 2),
                fmt(row["best_return_to_1272_pct"]),
                fmt(row["worst_return_to_1272_pct"]),
            ]
            for row in rows
        ],
    )


def print_policy_symbol_summary(rows: list[dict[str, Any]]) -> None:
    print()
    print("--- policy symbol summary ---")
    print_table(
        [
            "policy",
            "symbol",
            "source",
            "eval",
            "eligible",
            "sel_rate",
            "avg1000",
            "pos1000",
            "worst1000",
            "avg1272",
            "pos1272",
        ],
        [
            [
                str(row["policy_name"]),
                str(row["symbol"]),
                str(row["source"]),
                str(row["evaluated_rows"]),
                str(row["eligible_rows"]),
                fmt(row["selection_rate_pct"], 2),
                fmt(row["avg_return_to_1000_pct"]),
                fmt(row["positive_to_1000_pct"], 2),
                fmt(row["worst_return_to_1000_pct"]),
                fmt(row["avg_return_to_1272_pct"]),
                fmt(row["positive_to_1272_pct"], 2),
            ]
            for row in rows
            if row["eligible_rows"] > 0
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only same-symbol random-anchor baseline for calibrated Breath Curve 0.618 early filters."
    )
    parser.add_argument("--symbols", default="BTC,ETH,TAO,RENDER,FIL,HBAR,XLM,PEPE")
    parser.add_argument("--real-anchors", default="2026-03-01,2026-03-22,2026-04-12")
    parser.add_argument("--random-window-start", default=None)
    parser.add_argument("--random-window-end", default=None)
    parser.add_argument("--random-count-per-symbol", type=int, default=100)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--exclude-real-anchor-days", type=float, default=3.0)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument(
        "--offsets",
        default="-10.5,-10,-9.5,-9,-8.5,-8,-7.5,-7,-6.5,-6,-5.5,-5,-4.5,-4,-3.5,-3,-2.5,-2,-1.5,-1,-0.5,0,0.5,1,1.5,2,2.5,3,3.5,4,4.5,5,5.5,6,6.5,7,7.5,8,8.5,9,9.5,10,10.5",
    )
    parser.add_argument("--bands", default="-10.5,-9,-8,-7,-5,-3,0,3,5,7,9,10.5")
    parser.add_argument("--checkpoint", type=float, default=0.618)
    parser.add_argument("--future-target-ratio", type=float, default=1.000)
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument("--min-due-markers", type=int, default=3)
    parser.add_argument("--out-dir", default="data/research/breath_curve_random_anchor_baseline_v2")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    symbols = parse_csv_list(args.symbols)
    real_anchors = [parse_dt(raw) for raw in parse_csv_list(args.real_anchors)]
    offsets = parse_offsets(args.offsets)
    bands = parse_offsets(args.bands)

    random_window_start = parse_dt(args.random_window_start) if args.random_window_start else min(real_anchors)
    random_window_end = parse_dt(args.random_window_end) if args.random_window_end else max(real_anchors)

    all_rows: list[dict[str, Any]] = []

    for symbol in symbols:
        random_anchors = generate_random_anchors(
            start=random_window_start,
            end=random_window_end,
            count=args.random_count_per_symbol,
            real_anchors=real_anchors,
            exclude_days=args.exclude_real_anchor_days,
            seed=args.random_seed,
            symbol=symbol,
        )

        all_anchors = real_anchors + random_anchors
        symbol_candles = load_symbol_candles(
            symbol=symbol,
            venue=args.venue,
            interval_code=args.interval_code,
            anchors=all_anchors,
            cycle_days=args.cycle_days,
            offsets=offsets,
            tolerance_hours=args.tolerance_hours,
        )

        print(
            f"symbol={symbol} candles={len(symbol_candles)} "
            f"real_anchors={len(real_anchors)} random_anchors={len(random_anchors)}"
        )

        for anchor in real_anchors:
            row = evaluate_anchor(
                source="real",
                symbol=symbol,
                anchor=anchor,
                candles=symbol_candles,
                venue=args.venue,
                interval_code=args.interval_code,
                cycle_days=args.cycle_days,
                checkpoint=args.checkpoint,
                offsets=offsets,
                tolerance_hours=args.tolerance_hours,
                min_due_markers=args.min_due_markers,
                future_target_ratio=args.future_target_ratio,
                bands=bands,
            )
            all_rows.append(row)

        for anchor in random_anchors:
            row = evaluate_anchor(
                source="random",
                symbol=symbol,
                anchor=anchor,
                candles=symbol_candles,
                venue=args.venue,
                interval_code=args.interval_code,
                cycle_days=args.cycle_days,
                checkpoint=args.checkpoint,
                offsets=offsets,
                tolerance_hours=args.tolerance_hours,
                min_due_markers=args.min_due_markers,
                future_target_ratio=args.future_target_ratio,
                bands=bands,
            )
            all_rows.append(row)

    policy_rows = build_policy_rows(all_rows)
    source_summary = summary_by_policy(all_rows)
    comparison_rows = comparison_by_policy(source_summary)
    symbol_summary = summary_by_policy_symbol(all_rows)

    out_dir = Path(args.out_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    all_path = out_dir / f"breath_curve_random_anchor_baseline_v2_{stamp}_all_rows.csv"
    policy_path = out_dir / f"breath_curve_random_anchor_baseline_v2_{stamp}_policy_rows.csv"
    source_summary_path = out_dir / f"breath_curve_random_anchor_baseline_v2_{stamp}_source_summary.csv"
    comparison_path = out_dir / f"breath_curve_random_anchor_baseline_v2_{stamp}_comparison.csv"
    symbol_summary_path = out_dir / f"breath_curve_random_anchor_baseline_v2_{stamp}_symbol_summary.csv"

    write_csv(all_path, all_rows)
    write_csv(policy_path, policy_rows)
    write_csv(source_summary_path, source_summary)
    write_csv(comparison_path, comparison_rows)
    write_csv(symbol_summary_path, symbol_summary)

    if args.output == "table":
        print()
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print("post_hoc_fields_used_as_filters=0")
        print("tested_filters=0618_selected_minus8_v1,0618_selected_minus7_v1,0618_selected_early_band_v1")
        print(f"symbols={','.join(symbols)}")
        print(f"real_anchors={','.join(iso(anchor) for anchor in real_anchors)}")
        print(f"random_window={iso(random_window_start)}..{iso(random_window_end)}")
        print(f"random_count_per_symbol={args.random_count_per_symbol}")
        print(f"random_seed={args.random_seed}")
        print(f"rows={len(all_rows)} policy_rows={len(policy_rows)}")
        print()

        print_policy_comparison(comparison_rows)
        print_policy_source_summary(source_summary)
        print_policy_symbol_summary(symbol_summary)

        print()
        print(f"wrote_all_rows={all_path}")
        print(f"wrote_policy_rows={policy_path}")
        print(f"wrote_source_summary={source_summary_path}")
        print(f"wrote_comparison={comparison_path}")
        print(f"wrote_symbol_summary={symbol_summary_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
