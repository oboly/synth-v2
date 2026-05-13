from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "breath_curve_broader_history_v1"
VERSION = "0.1"


@dataclass(frozen=True)
class Cohort:
    cohort_id: str
    anchors: list[date]
    random_window_start: date
    random_window_end: date


def parse_date(raw: str) -> date:
    return datetime.fromisoformat(raw.strip()).date()


def fmt_date(value: date) -> str:
    return value.isoformat()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def as_float(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def fmt(value: Any, places: int = 4) -> str:
    parsed = as_float(value)
    if parsed is None:
        return ""

    text = f"{parsed:.{places}f}"
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


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def latest_file(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError(f"No files found: directory={directory} pattern={pattern}")
    return files[0]


def run_command(cmd: list[str], *, dry_run: bool = False) -> None:
    print("[RUN] " + " ".join(cmd))

    if dry_run:
        return

    subprocess.run(cmd, check=True)


def build_anchor_grid(start_anchor: date, end_anchor: date, step_days: int) -> list[date]:
    anchors: list[date] = []
    current = start_anchor

    while current <= end_anchor:
        anchors.append(current)
        current += timedelta(days=step_days)

    if len(anchors) < 1:
        raise RuntimeError("No anchors generated")

    return anchors


def build_cohorts(
    *,
    anchors: list[date],
    cohort_size: int,
    cohort_stride: int,
    random_window_pre_pad_days: int,
    random_window_post_pad_days: int,
) -> list[Cohort]:
    cohorts: list[Cohort] = []

    if cohort_size < 1:
        raise RuntimeError("cohort_size must be >= 1")

    if cohort_stride < 1:
        raise RuntimeError("cohort_stride must be >= 1")

    for idx in range(0, len(anchors) - cohort_size + 1, cohort_stride):
        cohort_anchors = anchors[idx : idx + cohort_size]
        cohort_id = f"cohort_{idx + 1:02d}_{fmt_date(cohort_anchors[0]).replace('-', '')}_{fmt_date(cohort_anchors[-1]).replace('-', '')}"

        cohorts.append(
            Cohort(
                cohort_id=cohort_id,
                anchors=cohort_anchors,
                random_window_start=cohort_anchors[0] - timedelta(days=random_window_pre_pad_days),
                random_window_end=cohort_anchors[-1] + timedelta(days=random_window_post_pad_days),
            )
        )

    if not cohorts:
        raise RuntimeError("No cohorts generated")

    return cohorts


def comparison_rows_with_cohort(cohort: Cohort, comparison_csv: Path) -> list[dict[str, Any]]:
    rows = read_csv(comparison_csv)

    for row in rows:
        row["cohort_id"] = cohort.cohort_id
        row["anchors"] = ",".join(fmt_date(anchor) for anchor in cohort.anchors)
        row["random_window_start"] = fmt_date(cohort.random_window_start)
        row["random_window_end"] = fmt_date(cohort.random_window_end)

    return rows


def aggregate_comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        grouped.setdefault(str(row["composite_name"]), []).append(row)

    out: list[dict[str, Any]] = []

    for composite_name, group in sorted(grouped.items()):
        cohort_count = len(group)

        real_eligible = sum(int(as_float(row.get("real_eligible")) or 0) for row in group)
        random_eligible = sum(int(as_float(row.get("random_eligible")) or 0) for row in group)
        real_evaluated = sum(int(as_float(row.get("real_evaluated")) or 0) for row in group)
        random_evaluated = sum(int(as_float(row.get("random_evaluated")) or 0) for row in group)

        def weighted_avg(value_key: str, weight_key: str) -> float | None:
            total_weight = 0.0
            total = 0.0

            for row in group:
                value = as_float(row.get(value_key))
                weight = as_float(row.get(weight_key))

                if value is None or weight is None or weight <= 0:
                    continue

                total += value * weight
                total_weight += weight

            if total_weight <= 0:
                return None

            return round(total / total_weight, 4)

        real_avg1000 = weighted_avg("real_avg_return_to_1000_pct", "real_eligible")
        random_avg1000 = weighted_avg("random_avg_return_to_1000_pct", "random_eligible")
        real_pos1000 = weighted_avg("real_positive_to_1000_pct", "real_eligible")
        random_pos1000 = weighted_avg("random_positive_to_1000_pct", "random_eligible")
        real_worst1000 = min(
            [x for x in (as_float(row.get("real_worst_return_to_1000_pct")) for row in group) if x is not None],
            default=None,
        )
        random_worst1000 = min(
            [x for x in (as_float(row.get("random_worst_return_to_1000_pct")) for row in group) if x is not None],
            default=None,
        )

        out.append(
            {
                "composite_name": composite_name,
                "cohort_count": cohort_count,
                "real_evaluated": real_evaluated,
                "real_eligible": real_eligible,
                "real_selection_rate_pct": round(real_eligible / real_evaluated * 100.0, 4)
                if real_evaluated
                else None,
                "real_avg_return_to_1000_pct": real_avg1000,
                "real_positive_to_1000_pct": real_pos1000,
                "real_worst_return_to_1000_pct": real_worst1000,
                "random_evaluated": random_evaluated,
                "random_eligible": random_eligible,
                "random_selection_rate_pct": round(random_eligible / random_evaluated * 100.0, 4)
                if random_evaluated
                else None,
                "random_avg_return_to_1000_pct": random_avg1000,
                "random_positive_to_1000_pct": random_pos1000,
                "random_worst_return_to_1000_pct": random_worst1000,
                "edge_avg_return_to_1000_pct": round(real_avg1000 - random_avg1000, 4)
                if real_avg1000 is not None and random_avg1000 is not None
                else None,
                "edge_positive_to_1000_pct": round(real_pos1000 - random_pos1000, 4)
                if real_pos1000 is not None and random_pos1000 is not None
                else None,
                "edge_worst_return_to_1000_pct": round(real_worst1000 - random_worst1000, 4)
                if real_worst1000 is not None and random_worst1000 is not None
                else None,
            }
        )

    return out


def print_aggregate(rows: list[dict[str, Any]]) -> None:
    print("--- broader history aggregate comparison ---")
    print_table(
        [
            "composite",
            "cohorts",
            "real_elig",
            "real_sel",
            "real_avg1000",
            "real_pos",
            "real_worst",
            "rand_elig",
            "rand_sel",
            "rand_avg1000",
            "rand_pos",
            "rand_worst",
            "edge1000",
            "edge_pos",
            "edge_worst",
        ],
        [
            [
                str(row["composite_name"]),
                str(row["cohort_count"]),
                str(row["real_eligible"]),
                fmt(row["real_selection_rate_pct"], 2),
                fmt(row["real_avg_return_to_1000_pct"]),
                fmt(row["real_positive_to_1000_pct"], 2),
                fmt(row["real_worst_return_to_1000_pct"]),
                str(row["random_eligible"]),
                fmt(row["random_selection_rate_pct"], 2),
                fmt(row["random_avg_return_to_1000_pct"]),
                fmt(row["random_positive_to_1000_pct"], 2),
                fmt(row["random_worst_return_to_1000_pct"]),
                fmt(row["edge_avg_return_to_1000_pct"]),
                fmt(row["edge_positive_to_1000_pct"], 2),
                fmt(row["edge_worst_return_to_1000_pct"]),
            ]
            for row in rows
        ],
    )


def print_cohort_rows(rows: list[dict[str, Any]], composites: set[str]) -> None:
    print()
    print("--- cohort comparison details ---")
    filtered = [row for row in rows if str(row.get("composite_name")) in composites]

    print_table(
        [
            "cohort",
            "composite",
            "real_elig",
            "real_avg1000",
            "real_worst",
            "rand_elig",
            "rand_avg1000",
            "rand_worst",
            "edge1000",
        ],
        [
            [
                str(row["cohort_id"]),
                str(row["composite_name"]),
                str(row.get("real_eligible", "")),
                fmt(row.get("real_avg_return_to_1000_pct")),
                fmt(row.get("real_worst_return_to_1000_pct")),
                str(row.get("random_eligible", "")),
                fmt(row.get("random_avg_return_to_1000_pct")),
                fmt(row.get("random_worst_return_to_1000_pct")),
                fmt(row.get("edge_avg_return_to_1000_pct")),
            ]
            for row in filtered
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only broader-history orchestrator for Breath Curve composite preview."
    )
    parser.add_argument("--start-anchor", default="2026-01-18")
    parser.add_argument("--end-anchor", default="2026-04-12")
    parser.add_argument("--anchor-step-days", type=int, default=21)
    parser.add_argument("--cohort-size", type=int, default=3)
    parser.add_argument("--cohort-stride", type=int, default=1)
    parser.add_argument("--random-window-pre-pad-days", type=int, default=28)
    parser.add_argument("--random-window-post-pad-days", type=int, default=0)
    parser.add_argument("--random-count-per-symbol", type=int, default=50)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--symbols", default="BTC,ETH,TAO,RENDER,FIL,HBAR,XLM,PEPE")
    parser.add_argument("--core-symbols", default="TAO,ETH,FIL,BTC")
    parser.add_argument("--out-dir", default="data/research/breath_curve_broader_history_v1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    start_anchor = parse_date(args.start_anchor)
    end_anchor = parse_date(args.end_anchor)

    anchors = build_anchor_grid(start_anchor, end_anchor, args.anchor_step_days)
    cohorts = build_cohorts(
        anchors=anchors,
        cohort_size=args.cohort_size,
        cohort_stride=args.cohort_stride,
        random_window_pre_pad_days=args.random_window_pre_pad_days,
        random_window_post_pad_days=args.random_window_post_pad_days,
    )

    out_dir = Path(args.out_dir)
    run_stamp = stamp()
    run_dir = out_dir / f"breath_curve_broader_history_v1_{run_stamp}"

    all_comparison_rows: list[dict[str, Any]] = []
    cohort_manifest: list[dict[str, Any]] = []

    for cohort in cohorts:
        cohort_dir = run_dir / cohort.cohort_id
        random_dir = cohort_dir / "random_anchor"
        regime_dir = cohort_dir / "symbol_regime"
        composite_dir = cohort_dir / "composite_preview"

        anchor_arg = ",".join(fmt_date(anchor) for anchor in cohort.anchors)

        cohort_manifest.append(
            {
                "cohort_id": cohort.cohort_id,
                "anchors": anchor_arg,
                "random_window_start": fmt_date(cohort.random_window_start),
                "random_window_end": fmt_date(cohort.random_window_end),
            }
        )

        run_command(
            [
                sys.executable,
                "-m",
                "src.research.run_breath_curve_random_anchor_baseline_v2",
                "--symbols",
                args.symbols,
                "--real-anchors",
                anchor_arg,
                "--random-window-start",
                fmt_date(cohort.random_window_start),
                "--random-window-end",
                fmt_date(cohort.random_window_end),
                "--random-count-per-symbol",
                str(args.random_count_per_symbol),
                "--random-seed",
                str(args.random_seed),
                "--out-dir",
                str(random_dir),
                "--output",
                "none",
            ],
            dry_run=args.dry_run,
        )

        if args.dry_run:
            continue

        random_all_rows = latest_file(random_dir, "*_all_rows.csv")

        run_command(
            [
                sys.executable,
                "-m",
                "src.research.run_breath_curve_symbol_regime_validation_v1",
                "--input-csv",
                str(random_all_rows),
                "--out-dir",
                str(regime_dir),
                "--db-context",
                "--output",
                "none",
            ],
            dry_run=args.dry_run,
        )

        enriched_rows = latest_file(regime_dir, "*_enriched_rows.csv")

        run_command(
            [
                sys.executable,
                "-m",
                "src.research.run_breath_curve_composite_preview_v1",
                "--input-csv",
                str(enriched_rows),
                "--out-dir",
                str(composite_dir),
                "--core-symbols",
                args.core_symbols,
                "--output",
                "none",
            ],
            dry_run=args.dry_run,
        )

        comparison_csv = latest_file(composite_dir, "*_comparison.csv")
        all_comparison_rows.extend(comparison_rows_with_cohort(cohort, comparison_csv))

    manifest_path = run_dir / "cohort_manifest.csv"
    comparison_path = run_dir / "all_cohort_comparison_rows.csv"
    aggregate_path = run_dir / "aggregate_comparison_summary.csv"

    aggregate_rows = aggregate_comparisons(all_comparison_rows)

    if not args.dry_run:
        write_csv(manifest_path, cohort_manifest)
        write_csv(comparison_path, all_comparison_rows)
        write_csv(aggregate_path, aggregate_rows)

    if args.output == "table":
        print()
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print("post_hoc_fields_used_as_filters=0")
        print(f"anchors={','.join(fmt_date(anchor) for anchor in anchors)}")
        print(f"cohorts={len(cohorts)} cohort_size={args.cohort_size} cohort_stride={args.cohort_stride}")
        print(f"random_count_per_symbol={args.random_count_per_symbol}")
        print(f"core_symbols={args.core_symbols}")
        print(f"run_dir={run_dir}")
        print()

        if args.dry_run:
            print("[DRY_RUN] no output written")
        else:
            print_aggregate(aggregate_rows)
            print_cohort_rows(
                all_comparison_rows,
                {
                    "minus8_all_v1",
                    "minus8_core_symbols_v1",
                    "minus8_volume_expansion_v1",
                    "minus8_core_and_btc_eth_bear_v1",
                    "early_band_core_and_bear_or_volume_v1",
                },
            )

            print()
            print(f"wrote_manifest={manifest_path}")
            print(f"wrote_all_comparison_rows={comparison_path}")
            print(f"wrote_aggregate_summary={aggregate_path}")
            print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
