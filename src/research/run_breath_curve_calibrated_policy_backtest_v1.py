from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any, Callable


REPORT_NAME = "breath_curve_calibrated_policy_backtest_v1"
VERSION = "0.1"


@dataclass(frozen=True)
class PolicySpec:
    policy_name: str
    purpose: str
    predicate: Callable[[dict[str, Any]], bool]


def dec(value: Any) -> Decimal | None:
    if value is None:
        return None

    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null", "nan"}:
        return None

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def as_float(value: Any) -> float | None:
    parsed = dec(value)
    if parsed is None:
        return None
    return float(parsed)


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: Any, places: int = 4) -> str:
    parsed = dec(value)
    if parsed is None:
        return ""

    q = Decimal("1").scaleb(-places)
    text = format(parsed.quantize(q), "f")
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


def parse_float_list(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def source_anchor_date(row: dict[str, Any]) -> str:
    for key in (
        "anchor_date",
        "anchor",
        "anchor_ts",
        "anchor_ts_utc",
        "anchor_datetime",
        "cycle_anchor",
        "cycle_anchor_date",
    ):
        value = str(row.get(key, "")).strip()
        if value:
            return value.replace("T", " ").split(" ")[0]
    return ""


def annotate_row(row: dict[str, str], bands: list[float]) -> dict[str, Any]:
    out: dict[str, Any] = dict(row)

    selected_offset = as_float(row.get("selected_partial_offset_days"))
    best_offset = as_float(row.get("best_full_offset_days"))

    distance = abs(selected_offset - best_offset) if selected_offset is not None and best_offset is not None else None

    selected_band_0_5 = nearest_band(selected_offset, bands, 0.5)
    selected_band_1_0 = nearest_band(selected_offset, bands, 1.0)
    selected_band_1_5 = nearest_band(selected_offset, bands, 1.5)
    best_band_0_5 = nearest_band(best_offset, bands, 0.5)
    best_band_1_0 = nearest_band(best_offset, bands, 1.0)
    best_band_1_5 = nearest_band(best_offset, bands, 1.5)

    out["anchor_date"] = source_anchor_date(row)
    out["selected_offset_days"] = selected_offset
    out["best_full_offset_days"] = best_offset
    out["offset_distance_days"] = distance
    out["offset_distance_bucket"] = distance_bucket(distance)
    out["selected_band_w0_5"] = selected_band_0_5
    out["selected_band_w1_0"] = selected_band_1_0
    out["selected_band_w1_5"] = selected_band_1_5
    out["best_full_band_w0_5"] = best_band_0_5
    out["best_full_band_w1_0"] = best_band_1_0
    out["best_full_band_w1_5"] = best_band_1_5
    out["band_match_1_0"] = selected_band_1_0 == best_band_1_0 and selected_band_1_0 not in {"DRIFT", "UNCLEAR"}
    out["band_match_1_5"] = selected_band_1_5 == best_band_1_5 and selected_band_1_5 not in {"DRIFT", "UNCLEAR"}
    out["phase_drift_days"] = best_offset - selected_offset if selected_offset is not None and best_offset is not None else None
    out["phase_drift_bucket"] = phase_drift_bucket(selected_offset, best_offset)
    out["offset_match_legacy"] = as_bool(row.get("offset_matches_best_full"))

    return out


def values(rows: list[dict[str, Any]], key: str) -> list[Decimal]:
    out: list[Decimal] = []
    for row in rows:
        parsed = dec(row.get(key))
        if parsed is not None:
            out.append(parsed)
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ret1000 = values(rows, "return_to_1000_pct")
    ret1272 = values(rows, "return_to_1272_pct")
    partial = values(rows, "selected_partial_score")
    distance = values(rows, "offset_distance_days")

    def avg(items: list[Decimal]) -> Decimal | None:
        if not items:
            return None
        return sum(items) / Decimal(str(len(items)))

    def med(items: list[Decimal]) -> Decimal | None:
        if not items:
            return None
        return Decimal(str(median(items)))

    def pos_rate(items: list[Decimal]) -> Decimal | None:
        if not items:
            return None
        positive = sum(1 for item in items if item > 0)
        return Decimal(str(positive)) / Decimal(str(len(items))) * Decimal("100")

    return {
        "rows": len(rows),
        "avg_partial_score": avg(partial),
        "avg_distance_days": avg(distance),
        "median_distance_days": med(distance),
        "avg_return_to_1000_pct": avg(ret1000),
        "median_return_to_1000_pct": med(ret1000),
        "positive_to_1000_pct": pos_rate(ret1000),
        "avg_return_to_1272_pct": avg(ret1272),
        "median_return_to_1272_pct": med(ret1272),
        "positive_to_1272_pct": pos_rate(ret1272),
        "best_return_to_1000_pct": max(ret1000) if ret1000 else None,
        "worst_return_to_1000_pct": min(ret1000) if ret1000 else None,
        "best_return_to_1272_pct": max(ret1272) if ret1272 else None,
        "worst_return_to_1272_pct": min(ret1272) if ret1272 else None,
    }


def grouped_summary(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        group_key = tuple(str(row.get(key, "")) for key in keys)
        grouped[group_key].append(row)

    out: list[dict[str, Any]] = []
    for group_key, group_rows in sorted(grouped.items()):
        out.append({**{keys[idx]: group_key[idx] for idx in range(len(keys))}, **summarize(group_rows)})
    return out


def is_checkpoint(row: dict[str, Any], checkpoint: str) -> bool:
    return str(row.get("checkpoint_ratio", "")).strip() == checkpoint


def in_selected_early_band(row: dict[str, Any]) -> bool:
    return str(row.get("selected_band_w1_0")) in {"-8", "-7"}


def in_0786_ignition_band(row: dict[str, Any]) -> bool:
    return bool(row.get("band_match_1_0")) or bool(row.get("band_match_1_5"))


def in_best_full_plus7(row: dict[str, Any]) -> bool:
    return str(row.get("best_full_band_w1_0")) == "+7"


def policies() -> list[PolicySpec]:
    return [
        PolicySpec(
            policy_name="0618_selected_early_band_v1",
            purpose="early measured recognition / forming structure",
            predicate=lambda row: is_checkpoint(row, "0.618") and in_selected_early_band(row),
        ),
        PolicySpec(
            policy_name="0786_ignition_band_match_v1",
            purpose="ignition / overflow confirmation",
            predicate=lambda row: is_checkpoint(row, "0.786") and in_0786_ignition_band(row),
        ),
        PolicySpec(
            policy_name="extension_best_full_plus7_v1",
            purpose="extension / overflow path research",
            predicate=in_best_full_plus7,
        ),
    ]


def apply_policies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in policies():
        for row in rows:
            if spec.predicate(row):
                out.append({**row, "policy_name": spec.policy_name, "policy_purpose": spec.purpose})

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


def print_summary_table(title: str, keys: list[str], rows: list[dict[str, Any]]) -> None:
    print()
    print(title)
    print_table(
        keys
        + [
            "rows",
            "partial",
            "dist",
            "ret1000",
            "pos1000",
            "ret1272",
            "pos1272",
            "best1000",
            "worst1000",
            "best1272",
            "worst1272",
        ],
        [
            [
                *[str(row.get(key, "")) for key in keys],
                str(row["rows"]),
                fmt(row["avg_partial_score"]),
                fmt(row["avg_distance_days"]),
                fmt(row["avg_return_to_1000_pct"]),
                fmt(row["positive_to_1000_pct"], 2),
                fmt(row["avg_return_to_1272_pct"]),
                fmt(row["positive_to_1272_pct"], 2),
                fmt(row["best_return_to_1000_pct"]),
                fmt(row["worst_return_to_1000_pct"]),
                fmt(row["best_return_to_1272_pct"]),
                fmt(row["worst_return_to_1272_pct"]),
            ]
            for row in rows
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only calibrated Breath Curve policy backtest v1."
    )
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--bands", default="-10.5,-9,-8,-7,-5,-3,0,3,5,7,9,10.5")
    parser.add_argument("--out-dir", default="data/research/breath_curve_calibrated_policy_backtest_v1")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_csv = Path(args.input_csv)
    raw_rows = load_rows(input_csv)
    bands = parse_float_list(args.bands)

    annotated_rows = [annotate_row(row, bands) for row in raw_rows if str(row.get("status", "")).strip() in {"", "OK"}]
    policy_rows = apply_policies(annotated_rows)

    out_dir = Path(args.out_dir)
    stem = input_csv.stem
    annotated_path = out_dir / f"{stem}_calibrated_annotated.csv"
    policy_path = out_dir / f"{stem}_calibrated_policy_rows.csv"
    policy_summary_path = out_dir / f"{stem}_calibrated_policy_summary.csv"
    symbol_summary_path = out_dir / f"{stem}_calibrated_policy_symbol_summary.csv"
    selected_summary_path = out_dir / f"{stem}_calibrated_selected_band_summary.csv"
    best_summary_path = out_dir / f"{stem}_calibrated_best_full_band_summary.csv"
    drift_summary_path = out_dir / f"{stem}_calibrated_phase_drift_summary.csv"

    policy_summary = grouped_summary(policy_rows, ["policy_name"])
    symbol_summary = grouped_summary(policy_rows, ["policy_name", "symbol"])
    selected_summary = grouped_summary(policy_rows, ["policy_name", "selected_band_w1_0"])
    best_summary = grouped_summary(policy_rows, ["policy_name", "best_full_band_w1_0"])
    drift_summary = grouped_summary(policy_rows, ["policy_name", "phase_drift_bucket"])

    write_csv(annotated_path, annotated_rows)
    write_csv(policy_path, policy_rows)
    write_csv(policy_summary_path, policy_summary)
    write_csv(symbol_summary_path, symbol_summary)
    write_csv(selected_summary_path, selected_summary)
    write_csv(best_summary_path, best_summary)
    write_csv(drift_summary_path, drift_summary)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print("exact_offset_match_role=legacy_diagnostic_not_primary_filter")
        print(f"input_csv={input_csv}")
        print(f"input_rows={len(raw_rows)}")
        print(f"annotated_rows={len(annotated_rows)}")
        print(f"policy_rows={len(policy_rows)}")
        print(f"bands={','.join(fmt(band, 2) for band in bands)}")

        print_summary_table("--- policy summary ---", ["policy_name"], policy_summary)
        print_summary_table("--- policy by symbol ---", ["policy_name", "symbol"], symbol_summary)
        print_summary_table("--- policy by selected band ---", ["policy_name", "selected_band_w1_0"], selected_summary)
        print_summary_table("--- policy by best full band ---", ["policy_name", "best_full_band_w1_0"], best_summary)
        print_summary_table("--- policy by phase drift ---", ["policy_name", "phase_drift_bucket"], drift_summary)

        print()
        print(f"wrote_annotated={annotated_path}")
        print(f"wrote_policy_rows={policy_path}")
        print(f"wrote_policy_summary={policy_summary_path}")
        print(f"wrote_symbol_summary={symbol_summary_path}")
        print(f"wrote_selected_band_summary={selected_summary_path}")
        print(f"wrote_best_full_band_summary={best_summary_path}")
        print(f"wrote_phase_drift_summary={drift_summary_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
