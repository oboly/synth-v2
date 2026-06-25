from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from src.market_context.breath_curve_core_v1 import nearest_band


REPORT_NAME = "breath_curve_phase_calibration_v2"
VERSION = "0.1"


def parse_float_list(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def as_float(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip()

    if text == "" or text.lower() in {"none", "null", "nan"}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return ""

    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal("1").scaleb(-places)
    text = format(dec.quantize(q), "f")

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


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def values(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []

    for row in rows:
        value = as_float(row.get(key))
        if value is not None:
            out.append(value)

    return out


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


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ret1000 = values(rows, "return_to_1000_pct")
    ret1272 = values(rows, "return_to_1272_pct")
    partial = values(rows, "selected_partial_score")
    same_full = values(rows, "same_offset_full_score")
    best_full = values(rows, "best_full_score")
    distance = values(rows, "offset_distance_days")
    exact_matches = [row for row in rows if as_bool(row.get("offset_matches_best_full"))]

    return {
        "rows": len(rows),
        "avg_distance": avg(distance),
        "median_distance": med(distance),
        "exact_match_rate_pct": round(len(exact_matches) / len(rows) * 100.0, 4) if rows else None,
        "avg_partial": avg(partial),
        "median_partial": med(partial),
        "avg_same_full": avg(same_full),
        "avg_best_full": avg(best_full),
        "avg_ret1000": avg(ret1000),
        "median_ret1000": med(ret1000),
        "pos1000_rate_pct": positive_rate(ret1000),
        "avg_ret1272": avg(ret1272),
        "median_ret1272": med(ret1272),
        "pos1272_rate_pct": positive_rate(ret1272),
        "best_ret1272": max(ret1272) if ret1272 else None,
        "worst_ret1272": min(ret1272) if ret1272 else None,
    }


def annotate_rows(raw_rows: list[dict[str, str]], bands: list[float], widths: list[float]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []

    for raw in raw_rows:
        row: dict[str, Any] = dict(raw)

        selected_offset = as_float(raw.get("selected_partial_offset_days"))
        best_offset = as_float(raw.get("best_full_offset_days"))

        if selected_offset is not None and best_offset is not None:
            distance = abs(selected_offset - best_offset)
        else:
            distance = None

        row["offset_distance_days"] = distance
        row["offset_distance_bucket"] = distance_bucket(distance)

        for width in widths:
            key = str(width).replace(".", "_")
            selected_band = nearest_band(selected_offset, bands, width)
            best_band = nearest_band(best_offset, bands, width)

            row[f"selected_band_w{key}"] = selected_band
            row[f"best_full_band_w{key}"] = best_band
            row[f"band_match_w{key}"] = selected_band == best_band and selected_band not in {"DRIFT", "UNCLEAR"}

        annotated.append(row)

    return annotated


def grouped_summary(
    rows: list[dict[str, Any]],
    group_keys: list[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        key = tuple(str(row.get(group_key, "")) for group_key in group_keys)
        grouped[key].append(row)

    out: list[dict[str, Any]] = []

    for key, group in sorted(grouped.items()):
        summary = summarize(group)
        out.append(
            {
                **{group_keys[idx]: key[idx] for idx in range(len(group_keys))},
                **summary,
            }
        )

    return out


def band_match_summary(rows: list[dict[str, Any]], widths: list[float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for width in widths:
        key = str(width).replace(".", "_")
        match_col = f"band_match_w{key}"

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        for row in rows:
            checkpoint = str(row.get("checkpoint_ratio", ""))
            band_match = "MATCH" if as_bool(row.get(match_col)) else "NO_MATCH"
            grouped[(checkpoint, band_match)].append(row)

        for (checkpoint, band_match), group in sorted(grouped.items()):
            summary = summarize(group)
            out.append(
                {
                    "band_width_days": width,
                    "checkpoint_ratio": checkpoint,
                    "band_match": band_match,
                    **summary,
                }
            )

    return out


def selected_best_cross_summary(rows: list[dict[str, Any]], width: float) -> list[dict[str, Any]]:
    key = str(width).replace(".", "_")
    selected_col = f"selected_band_w{key}"
    best_col = f"best_full_band_w{key}"

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        checkpoint = str(row.get("checkpoint_ratio", ""))
        selected_band = str(row.get(selected_col, ""))
        best_band = str(row.get(best_col, ""))
        grouped[(checkpoint, selected_band, best_band)].append(row)

    out: list[dict[str, Any]] = []

    for (checkpoint, selected_band, best_band), group in sorted(grouped.items()):
        summary = summarize(group)
        out.append(
            {
                "band_width_days": width,
                "checkpoint_ratio": checkpoint,
                "selected_band": selected_band,
                "best_full_band": best_band,
                **summary,
            }
        )

    return out


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only Breath Curve phase calibration v2."
    )
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--bands", default="-10.5,-9,-7,-5,-3,0,3,5,7,9,10.5")
    parser.add_argument("--band-widths", default="0.5,1.0,1.5")
    parser.add_argument("--cross-width", type=float, default=1.0)
    parser.add_argument("--out-dir", default="data/research/breath_curve_phase_calibration_v2")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    args = parser.parse_args()

    input_csv = Path(args.input_csv)
    raw_rows = load_rows(input_csv)

    bands = parse_float_list(args.bands)
    widths = parse_float_list(args.band_widths)

    annotated = annotate_rows(raw_rows, bands, widths)

    distance_rows = grouped_summary(
        annotated,
        ["checkpoint_ratio", "offset_distance_bucket"],
    )

    selected_band_rows = grouped_summary(
        annotated,
        ["checkpoint_ratio", "selected_band_w1_0"],
    )

    best_band_rows = grouped_summary(
        annotated,
        ["checkpoint_ratio", "best_full_band_w1_0"],
    )

    band_match_rows = band_match_summary(annotated, widths)
    cross_rows = selected_best_cross_summary(annotated, args.cross_width)

    out_dir = Path(args.out_dir)
    stem = input_csv.stem

    annotated_path = out_dir / f"{stem}_phase_calibration_annotated.csv"
    distance_path = out_dir / f"{stem}_phase_calibration_distance_summary.csv"
    selected_path = out_dir / f"{stem}_phase_calibration_selected_band_summary.csv"
    best_path = out_dir / f"{stem}_phase_calibration_best_band_summary.csv"
    match_path = out_dir / f"{stem}_phase_calibration_band_match_summary.csv"
    cross_path = out_dir / f"{stem}_phase_calibration_selected_to_best_cross.csv"

    write_csv(annotated_path, annotated)
    write_csv(distance_path, distance_rows)
    write_csv(selected_path, selected_band_rows)
    write_csv(best_path, best_band_rows)
    write_csv(match_path, band_match_rows)
    write_csv(cross_path, cross_rows)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("runtime_layer_touch=none")
        print(f"input_csv={input_csv}")
        print(f"rows={len(annotated)}")
        print(f"bands={','.join(fmt(band, 2) for band in bands)}")
        print(f"band_widths={','.join(fmt(width, 2) for width in widths)}")
        print("")

        print("--- distance bucket summary ---")
        print_table(
            [
                "checkpoint",
                "distance_bucket",
                "rows",
                "avg_dist",
                "exact",
                "partial",
                "ret1000",
                "pos1000",
                "ret1272",
                "pos1272",
                "best1272",
                "worst1272",
            ],
            [
                [
                    str(row["checkpoint_ratio"]),
                    str(row["offset_distance_bucket"]),
                    str(row["rows"]),
                    fmt(row["avg_distance"]),
                    fmt(row["exact_match_rate_pct"], 2),
                    fmt(row["avg_partial"]),
                    fmt(row["avg_ret1000"]),
                    fmt(row["pos1000_rate_pct"], 2),
                    fmt(row["avg_ret1272"]),
                    fmt(row["pos1272_rate_pct"], 2),
                    fmt(row["best_ret1272"]),
                    fmt(row["worst_ret1272"]),
                ]
                for row in distance_rows
            ],
        )

        print("")
        print("--- band-match summary ---")
        print_table(
            [
                "width",
                "checkpoint",
                "band_match",
                "rows",
                "avg_dist",
                "partial",
                "ret1000",
                "pos1000",
                "ret1272",
                "pos1272",
                "best1272",
                "worst1272",
            ],
            [
                [
                    fmt(row["band_width_days"], 2),
                    str(row["checkpoint_ratio"]),
                    str(row["band_match"]),
                    str(row["rows"]),
                    fmt(row["avg_distance"]),
                    fmt(row["avg_partial"]),
                    fmt(row["avg_ret1000"]),
                    fmt(row["pos1000_rate_pct"], 2),
                    fmt(row["avg_ret1272"]),
                    fmt(row["pos1272_rate_pct"], 2),
                    fmt(row["best_ret1272"]),
                    fmt(row["worst_ret1272"]),
                ]
                for row in band_match_rows
            ],
        )

        print("")
        print("--- selected band summary width 1.0 ---")
        print_table(
            [
                "checkpoint",
                "selected_band",
                "rows",
                "avg_dist",
                "partial",
                "ret1000",
                "pos1000",
                "ret1272",
                "pos1272",
                "best1272",
                "worst1272",
            ],
            [
                [
                    str(row["checkpoint_ratio"]),
                    str(row["selected_band_w1_0"]),
                    str(row["rows"]),
                    fmt(row["avg_distance"]),
                    fmt(row["avg_partial"]),
                    fmt(row["avg_ret1000"]),
                    fmt(row["pos1000_rate_pct"], 2),
                    fmt(row["avg_ret1272"]),
                    fmt(row["pos1272_rate_pct"], 2),
                    fmt(row["best_ret1272"]),
                    fmt(row["worst_ret1272"]),
                ]
                for row in selected_band_rows
            ],
        )

        print("")
        print("--- best full band summary width 1.0 ---")
        print_table(
            [
                "checkpoint",
                "best_band",
                "rows",
                "avg_dist",
                "partial",
                "ret1000",
                "pos1000",
                "ret1272",
                "pos1272",
                "best1272",
                "worst1272",
            ],
            [
                [
                    str(row["checkpoint_ratio"]),
                    str(row["best_full_band_w1_0"]),
                    str(row["rows"]),
                    fmt(row["avg_distance"]),
                    fmt(row["avg_partial"]),
                    fmt(row["avg_ret1000"]),
                    fmt(row["pos1000_rate_pct"], 2),
                    fmt(row["avg_ret1272"]),
                    fmt(row["pos1272_rate_pct"], 2),
                    fmt(row["best_ret1272"]),
                    fmt(row["worst_ret1272"]),
                ]
                for row in best_band_rows
            ],
        )

        print("")
        print(f"wrote_annotated={annotated_path}")
        print(f"wrote_distance_summary={distance_path}")
        print(f"wrote_selected_band_summary={selected_path}")
        print(f"wrote_best_band_summary={best_path}")
        print(f"wrote_band_match_summary={match_path}")
        print(f"wrote_cross_summary={cross_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
