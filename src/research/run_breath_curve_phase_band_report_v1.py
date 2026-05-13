from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "breath_curve_phase_band_report_v1"
VERSION = "0.1"


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


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


def nearest_band(offset: float, bands: list[float], width: float) -> str:
    best = min(bands, key=lambda band: abs(offset - band))
    distance = abs(offset - best)

    if distance <= width:
        return f"{best:+g}"

    return "DRIFT"


def values(rows: list[dict[str, str]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = as_float(row.get(key))
        if value is not None:
            out.append(value)
    return out


def average(items: list[float]) -> float | None:
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


def summarize_group(rows: list[dict[str, str]]) -> dict[str, Any]:
    ret1000 = values(rows, "return_to_1000_pct")
    ret1272 = values(rows, "return_to_1272_pct")
    partial_scores = values(rows, "selected_partial_score")
    same_full_scores = values(rows, "same_offset_full_score")
    best_full_scores = values(rows, "best_full_score")

    offset_matches = [row for row in rows if as_bool(row.get("offset_matches_best_full"))]

    return {
        "rows": len(rows),
        "avg_partial": average(partial_scores),
        "median_partial": med(partial_scores),
        "avg_same_full": average(same_full_scores),
        "avg_best_full": average(best_full_scores),
        "offset_match_rate_pct": round(len(offset_matches) / len(rows) * 100.0, 4) if rows else None,
        "avg_ret1000": average(ret1000),
        "avg_ret1272": average(ret1272),
        "pos1000_rate_pct": positive_rate(ret1000),
        "pos1272_rate_pct": positive_rate(ret1272),
        "best_ret1272": max(ret1272) if ret1272 else None,
        "worst_ret1272": min(ret1272) if ret1272 else None,
    }


def summarize_by_band(
    rows: list[dict[str, str]],
    *,
    offset_key: str,
    bands: list[float],
    width: float,
    checkpoint: str | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = {}

    for row in rows:
        if str(row.get("status", "OK")) not in {"", "OK"}:
            continue

        if checkpoint is not None and str(row.get("checkpoint_ratio")) != checkpoint:
            continue

        offset = as_float(row.get(offset_key))
        if offset is None:
            continue

        band = nearest_band(offset, bands, width)
        grouped.setdefault(band, []).append(row)

    out: list[dict[str, Any]] = []
    ordered_bands = [f"{band:+g}" for band in bands] + ["DRIFT"]

    for band in ordered_bands:
        group = grouped.get(band, [])
        if not group:
            continue

        summary = summarize_group(group)
        out.append(
            {
                "checkpoint": checkpoint or "ALL",
                "offset_key": offset_key,
                "band_width_days": width,
                "band": band,
                **summary,
            }
        )

    return out


def summarize_exact_offsets(
    rows: list[dict[str, str]],
    *,
    offset_key: str,
    checkpoint: str | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = {}

    for row in rows:
        if str(row.get("status", "OK")) not in {"", "OK"}:
            continue

        if checkpoint is not None and str(row.get("checkpoint_ratio")) != checkpoint:
            continue

        offset = as_float(row.get(offset_key))
        if offset is None:
            continue

        grouped.setdefault(fmt(offset, 2), []).append(row)

    out: list[dict[str, Any]] = []

    for offset, group in sorted(grouped.items(), key=lambda item: float(item[0])):
        summary = summarize_group(group)
        out.append(
            {
                "checkpoint": checkpoint or "ALL",
                "offset_key": offset_key,
                "offset": offset,
                **summary,
            }
        )

    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only Breath Curve phase-shift band analyzer."
    )
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--bands", default="-10.5,-9,-7,-5,-3,0,3,5,7,9,10.5")
    parser.add_argument("--band-widths", default="0.25,0.5,1.0")
    parser.add_argument("--checkpoints", default="0.618,0.786")
    parser.add_argument("--out-dir", default="data/research/breath_curve_phase_band_report_v1")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    args = parser.parse_args()

    input_csv = Path(args.input_csv)
    rows = load_rows(input_csv)

    bands = parse_float_list(args.bands)
    widths = parse_float_list(args.band_widths)
    checkpoints = parse_csv_list(args.checkpoints)

    band_rows: list[dict[str, Any]] = []
    exact_rows: list[dict[str, Any]] = []

    for checkpoint in [None, *checkpoints]:
        for offset_key in ["selected_partial_offset_days", "best_full_offset_days"]:
            exact_rows.extend(
                summarize_exact_offsets(
                    rows,
                    offset_key=offset_key,
                    checkpoint=checkpoint,
                )
            )

            for width in widths:
                band_rows.extend(
                    summarize_by_band(
                        rows,
                        offset_key=offset_key,
                        bands=bands,
                        width=width,
                        checkpoint=checkpoint,
                    )
                )

    out_dir = Path(args.out_dir)
    stem = input_csv.stem
    band_path = out_dir / f"{stem}_phase_band_summary.csv"
    exact_path = out_dir / f"{stem}_phase_exact_offset_summary.csv"

    write_csv(band_path, band_rows)
    write_csv(exact_path, exact_rows)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("runtime_layer_touch=none")
        print(f"input_csv={input_csv}")
        print(f"rows={len(rows)}")
        print(f"bands={','.join(fmt(band, 2) for band in bands)}")
        print(f"band_widths={','.join(fmt(width, 2) for width in widths)}")
        print("")

        print("--- exact selected offset distribution ---")
        selected_exact = [
            row for row in exact_rows
            if row["offset_key"] == "selected_partial_offset_days"
            and row["checkpoint"] in {"0.618", "0.786"}
        ]
        print_table(
            [
                "checkpoint",
                "offset",
                "rows",
                "partial",
                "offset_match",
                "ret1000",
                "ret1272",
                "pos1272",
                "best1272",
                "worst1272",
            ],
            [
                [
                    str(row["checkpoint"]),
                    str(row["offset"]),
                    str(row["rows"]),
                    fmt(row["avg_partial"]),
                    fmt(row["offset_match_rate_pct"], 2),
                    fmt(row["avg_ret1000"]),
                    fmt(row["avg_ret1272"]),
                    fmt(row["pos1272_rate_pct"], 2),
                    fmt(row["best_ret1272"]),
                    fmt(row["worst_ret1272"]),
                ]
                for row in selected_exact
            ],
        )

        print("")
        print("--- band summary width 0.5 selected offsets ---")
        selected_band = [
            row for row in band_rows
            if row["offset_key"] == "selected_partial_offset_days"
            and row["band_width_days"] == 0.5
            and row["checkpoint"] in {"0.618", "0.786"}
        ]
        print_table(
            [
                "checkpoint",
                "band",
                "rows",
                "partial",
                "offset_match",
                "ret1000",
                "ret1272",
                "pos1272",
                "best1272",
                "worst1272",
            ],
            [
                [
                    str(row["checkpoint"]),
                    str(row["band"]),
                    str(row["rows"]),
                    fmt(row["avg_partial"]),
                    fmt(row["offset_match_rate_pct"], 2),
                    fmt(row["avg_ret1000"]),
                    fmt(row["avg_ret1272"]),
                    fmt(row["pos1272_rate_pct"], 2),
                    fmt(row["best_ret1272"]),
                    fmt(row["worst_ret1272"]),
                ]
                for row in selected_band
            ],
        )

        print("")
        print("--- band summary width 0.5 best full offsets ---")
        best_band = [
            row for row in band_rows
            if row["offset_key"] == "best_full_offset_days"
            and row["band_width_days"] == 0.5
            and row["checkpoint"] in {"0.618", "0.786"}
        ]
        print_table(
            [
                "checkpoint",
                "band",
                "rows",
                "partial",
                "offset_match",
                "ret1000",
                "ret1272",
                "pos1272",
                "best1272",
                "worst1272",
            ],
            [
                [
                    str(row["checkpoint"]),
                    str(row["band"]),
                    str(row["rows"]),
                    fmt(row["avg_partial"]),
                    fmt(row["offset_match_rate_pct"], 2),
                    fmt(row["avg_ret1000"]),
                    fmt(row["avg_ret1272"]),
                    fmt(row["pos1272_rate_pct"], 2),
                    fmt(row["best_ret1272"]),
                    fmt(row["worst_ret1272"]),
                ]
                for row in best_band
            ],
        )

        print("")
        print(f"wrote_band_summary={band_path}")
        print(f"wrote_exact_offset_summary={exact_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
