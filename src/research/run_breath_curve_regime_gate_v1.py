from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


REPORT_NAME = "breath_curve_regime_gate_v1"
VERSION = "0.1"


TARGET_COMPOSITE_DEFAULT = "minus8_core_symbols_v1"


@dataclass(frozen=True)
class RunSummary:
    run_dir: Path
    run_id: str
    regime_class: str
    target_edge: float | None
    target_real_eligible: int
    target_random_eligible: int
    target_real_avg1000: float | None
    target_random_avg1000: float | None


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


def as_int(value: Any) -> int:
    parsed = as_float(value)
    if parsed is None:
        return 0
    return int(parsed)


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


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


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


def discover_run_dirs(default_dir: str) -> list[Path]:
    root = Path(default_dir)
    return sorted(
        [
            path
            for path in root.glob("breath_curve_broader_history_v1_*")
            if path.is_dir() and (path / "aggregate_comparison_summary.csv").exists()
        ],
        key=lambda path: path.stat().st_mtime,
    )


def manifest_signature(run_dir: Path) -> str:
    path = run_dir / "cohort_manifest.csv"

    if not path.exists():
        return f"NO_MANIFEST::{run_dir.name}"

    rows = read_csv(path)
    parts = []

    for row in rows:
        parts.append(
            "|".join(
                [
                    str(row.get("anchors", "")),
                    str(row.get("random_window_start", "")),
                    str(row.get("random_window_end", "")),
                ]
            )
        )

    return "\n".join(sorted(parts))


def manifest_is_zero_post_pad(run_dir: Path) -> bool:
    path = run_dir / "cohort_manifest.csv"

    if not path.exists():
        return False

    rows = read_csv(path)

    if not rows:
        return False

    for row in rows:
        anchors = [x.strip() for x in str(row.get("anchors", "")).split(",") if x.strip()]
        random_window_end = str(row.get("random_window_end", "")).strip()

        if not anchors:
            return False

        latest_anchor = anchors[-1]

        if random_window_end != latest_anchor:
            return False

    return True


def dedupe_run_dirs_by_manifest(run_dirs: list[Path]) -> list[Path]:
    by_signature: dict[str, Path] = {}

    for run_dir in run_dirs:
        signature = manifest_signature(run_dir)
        current = by_signature.get(signature)

        if current is None or run_dir.stat().st_mtime > current.stat().st_mtime:
            by_signature[signature] = run_dir

    return sorted(by_signature.values(), key=lambda path: path.stat().st_mtime)


def classify_run(
    run_dir: Path,
    *,
    target_composite: str,
    min_winning_real_eligible: int,
) -> RunSummary:
    aggregate_path = run_dir / "aggregate_comparison_summary.csv"
    aggregate_rows = read_csv(aggregate_path)

    target = next(
        (row for row in aggregate_rows if row.get("composite_name") == target_composite),
        None,
    )

    if target is None:
        return RunSummary(
            run_dir=run_dir,
            run_id=run_dir.name,
            regime_class="UNKNOWN_NO_TARGET",
            target_edge=None,
            target_real_eligible=0,
            target_random_eligible=0,
            target_real_avg1000=None,
            target_random_avg1000=None,
        )

    edge = as_float(target.get("edge_avg_return_to_1000_pct"))
    real_eligible = as_int(target.get("real_eligible"))
    random_eligible = as_int(target.get("random_eligible"))
    real_avg = as_float(target.get("real_avg_return_to_1000_pct"))
    random_avg = as_float(target.get("random_avg_return_to_1000_pct"))

    if edge is not None and edge > 0 and real_eligible >= min_winning_real_eligible:
        regime_class = "WINNING_REGIME"
    elif edge is not None and edge <= 0:
        regime_class = "FAILING_REGIME"
    else:
        regime_class = "NEUTRAL_OR_SAMPLE_THIN"

    return RunSummary(
        run_dir=run_dir,
        run_id=run_dir.name,
        regime_class=regime_class,
        target_edge=edge,
        target_real_eligible=real_eligible,
        target_random_eligible=random_eligible,
        target_real_avg1000=real_avg,
        target_random_avg1000=random_avg,
    )


def load_all_aggregate_rows(run_summaries: list[RunSummary]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for run in run_summaries:
        rows = read_csv(run.run_dir / "aggregate_comparison_summary.csv")
        for row in rows:
            out.append(
                {
                    **row,
                    "run_id": run.run_id,
                    "run_dir": str(run.run_dir),
                    "regime_class": run.regime_class,
                    "target_edge_for_run": run.target_edge,
                    "target_real_eligible_for_run": run.target_real_eligible,
                }
            )

    return out


def candidate_separation_rows(aggregate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    for row in aggregate_rows:
        grouped[str(row.get("composite_name", ""))][str(row.get("regime_class", ""))].append(row)

    out: list[dict[str, Any]] = []

    for composite_name, by_class in grouped.items():
        winning = by_class.get("WINNING_REGIME", [])
        failing = by_class.get("FAILING_REGIME", [])

        def avg_edge(rows: list[dict[str, Any]]) -> float | None:
            values = [
                value
                for value in (as_float(row.get("edge_avg_return_to_1000_pct")) for row in rows)
                if value is not None
            ]
            if not values:
                return None
            return round(mean(values), 4)

        def sum_int(rows: list[dict[str, Any]], key: str) -> int:
            return sum(as_int(row.get(key)) for row in rows)

        winning_edge = avg_edge(winning)
        failing_edge = avg_edge(failing)

        separation = None
        if winning_edge is not None and failing_edge is not None:
            separation = round(winning_edge - failing_edge, 4)

        out.append(
            {
                "composite_name": composite_name,
                "winning_run_count": len(winning),
                "failing_run_count": len(failing),
                "winning_edge_avg": winning_edge,
                "failing_edge_avg": failing_edge,
                "edge_separation": separation,
                "winning_real_eligible": sum_int(winning, "real_eligible"),
                "failing_real_eligible": sum_int(failing, "real_eligible"),
                "winning_random_eligible": sum_int(winning, "random_eligible"),
                "failing_random_eligible": sum_int(failing, "random_eligible"),
                "candidate_read": classify_gate_candidate(composite_name, winning_edge, failing_edge, separation),
            }
        )

    return sorted(
        out,
        key=lambda row: as_float(row.get("edge_separation")) if as_float(row.get("edge_separation")) is not None else -9999,
        reverse=True,
    )


def classify_gate_candidate(
    composite_name: str,
    winning_edge: float | None,
    failing_edge: float | None,
    separation: float | None,
) -> str:
    if winning_edge is None or failing_edge is None or separation is None:
        return "INSUFFICIENT_RUN_CLASSES"

    if winning_edge > 0 and failing_edge <= 0 and separation >= 5:
        return "REGIME_GATE_CANDIDATE"

    if winning_edge > 0 and separation >= 3:
        return "WEAK_REGIME_GATE_CANDIDATE"

    if winning_edge <= 0:
        return "NO_WINNING_EDGE"

    return "LOW_SEPARATION"


def load_cohort_rows(run_summaries: list[RunSummary]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for run in run_summaries:
        path = run.run_dir / "all_cohort_comparison_rows.csv"
        if not path.exists():
            continue

        for row in read_csv(path):
            edge = as_float(row.get("edge_avg_return_to_1000_pct"))
            if edge is None:
                cohort_class = "COHORT_UNKNOWN"
            elif edge > 0:
                cohort_class = "WINNING_COHORT"
            else:
                cohort_class = "FAILING_COHORT"

            out.append(
                {
                    **row,
                    "run_id": run.run_id,
                    "run_dir": str(run.run_dir),
                    "regime_class": run.regime_class,
                    "cohort_class": cohort_class,
                }
            )

    return out


def target_cohort_rows(cohort_rows: list[dict[str, Any]], target_composite: str) -> list[dict[str, Any]]:
    return [
        row
        for row in cohort_rows
        if row.get("composite_name") == target_composite
    ]


def cohort_class_summary(cohort_rows: list[dict[str, Any]], target_composite: str) -> list[dict[str, Any]]:
    rows = target_cohort_rows(cohort_rows, target_composite)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        grouped[str(row.get("cohort_class"))].append(row)

    out: list[dict[str, Any]] = []

    for cohort_class, group in sorted(grouped.items()):
        edges = [
            value
            for value in (as_float(row.get("edge_avg_return_to_1000_pct")) for row in group)
            if value is not None
        ]

        out.append(
            {
                "target_composite": target_composite,
                "cohort_class": cohort_class,
                "cohort_count": len(group),
                "avg_edge": round(mean(edges), 4) if edges else None,
                "real_eligible": sum(as_int(row.get("real_eligible")) for row in group),
                "random_eligible": sum(as_int(row.get("random_eligible")) for row in group),
                "avg_real_return_to_1000_pct": weighted_average(group, "real_avg_return_to_1000_pct", "real_eligible"),
                "avg_random_return_to_1000_pct": weighted_average(group, "random_avg_return_to_1000_pct", "random_eligible"),
            }
        )

    return out


def weighted_average(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float | None:
    total = 0.0
    weight_sum = 0.0

    for row in rows:
        value = as_float(row.get(value_key))
        weight = as_float(row.get(weight_key))

        if value is None or weight is None or weight <= 0:
            continue

        total += value * weight
        weight_sum += weight

    if weight_sum <= 0:
        return None

    return round(total / weight_sum, 4)


def collect_bucket_rows(
    run_summaries: list[RunSummary],
    cohort_rows: list[dict[str, Any]],
    target_composite: str,
) -> list[dict[str, Any]]:
    cohort_class_by_key: dict[tuple[str, str], str] = {}

    for row in cohort_rows:
        if row.get("composite_name") != target_composite:
            continue
        cohort_class_by_key[(str(row.get("run_id")), str(row.get("cohort_id")))] = str(row.get("cohort_class"))

    files = [
        ("symbol", "*_symbol_summary.csv", "symbol"),
        ("btc_eth_context", "*_btc_eth_summary.csv", "btc_eth_context_bucket"),
        ("volume", "*_volume_summary.csv", "symbol_volume_bucket"),
        ("rsi", "*_rsi_summary.csv", "symbol_rsi_bucket"),
        ("trend", "*_trend_summary.csv", "symbol_trend_bucket"),
    ]

    out: list[dict[str, Any]] = []

    for run in run_summaries:
        for cohort_dir in sorted(run.run_dir.glob("cohort_*")):
            if not cohort_dir.is_dir():
                continue

            cohort_id = cohort_dir.name
            preview_dir = cohort_dir / "composite_preview"
            if not preview_dir.exists():
                continue

            for dimension, pattern, bucket_key in files:
                matching = sorted(preview_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
                if not matching:
                    continue

                for row in read_csv(matching[0]):
                    if row.get("composite_name") != target_composite:
                        continue
                    if row.get("source") != "real":
                        continue

                    out.append(
                        {
                            "run_id": run.run_id,
                            "regime_class": run.regime_class,
                            "cohort_id": cohort_id,
                            "cohort_class": cohort_class_by_key.get((run.run_id, cohort_id), "COHORT_UNKNOWN"),
                            "dimension": dimension,
                            "bucket": row.get(bucket_key, ""),
                            "evaluated_rows": row.get("evaluated_rows"),
                            "eligible_rows": row.get("eligible_rows"),
                            "selection_rate_pct": row.get("selection_rate_pct"),
                            "avg_return_to_1000_pct": row.get("avg_return_to_1000_pct"),
                            "positive_to_1000_pct": row.get("positive_to_1000_pct"),
                            "worst_return_to_1000_pct": row.get("worst_return_to_1000_pct"),
                        }
                    )

    return out


def bucket_summary(bucket_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in bucket_rows:
        grouped[
            (
                str(row.get("cohort_class")),
                str(row.get("dimension")),
                str(row.get("bucket")),
            )
        ].append(row)

    out: list[dict[str, Any]] = []

    for (cohort_class, dimension, bucket), group in sorted(grouped.items()):
        out.append(
            {
                "cohort_class": cohort_class,
                "dimension": dimension,
                "bucket": bucket,
                "cohort_rows": len(group),
                "eligible_rows": sum(as_int(row.get("eligible_rows")) for row in group),
                "evaluated_rows": sum(as_int(row.get("evaluated_rows")) for row in group),
                "avg_return_to_1000_pct": weighted_average(group, "avg_return_to_1000_pct", "eligible_rows"),
                "worst_return_to_1000_pct": min(
                    [
                        value
                        for value in (as_float(row.get("worst_return_to_1000_pct")) for row in group)
                        if value is not None
                    ],
                    default=None,
                ),
                "avg_selection_rate_pct": weighted_average(group, "selection_rate_pct", "evaluated_rows"),
            }
        )

    return out


def print_run_classification(rows: list[RunSummary]) -> None:
    print("--- run classification ---")
    print_table(
        [
            "run",
            "class",
            "target_edge",
            "real_elig",
            "rand_elig",
            "real_avg1000",
            "rand_avg1000",
        ],
        [
            [
                row.run_id,
                row.regime_class,
                fmt(row.target_edge),
                str(row.target_real_eligible),
                str(row.target_random_eligible),
                fmt(row.target_real_avg1000),
                fmt(row.target_random_avg1000),
            ]
            for row in rows
        ],
    )


def print_candidate_separation(rows: list[dict[str, Any]]) -> None:
    print()
    print("--- composite regime-gate separation ---")
    print_table(
        [
            "composite",
            "win_runs",
            "fail_runs",
            "win_edge",
            "fail_edge",
            "separation",
            "win_real",
            "fail_real",
            "read",
        ],
        [
            [
                str(row.get("composite_name")),
                str(row.get("winning_run_count")),
                str(row.get("failing_run_count")),
                fmt(row.get("winning_edge_avg")),
                fmt(row.get("failing_edge_avg")),
                fmt(row.get("edge_separation")),
                str(row.get("winning_real_eligible")),
                str(row.get("failing_real_eligible")),
                str(row.get("candidate_read")),
            ]
            for row in rows
        ],
    )


def print_target_cohorts(rows: list[dict[str, Any]], target_composite: str) -> None:
    print()
    print(f"--- target cohort details: {target_composite} ---")
    print_table(
        [
            "run_class",
            "cohort_class",
            "cohort",
            "edge",
            "real_elig",
            "real_avg1000",
            "rand_elig",
            "rand_avg1000",
        ],
        [
            [
                str(row.get("regime_class")),
                str(row.get("cohort_class")),
                str(row.get("cohort_id")),
                fmt(row.get("edge_avg_return_to_1000_pct")),
                str(row.get("real_eligible")),
                fmt(row.get("real_avg_return_to_1000_pct")),
                str(row.get("random_eligible")),
                fmt(row.get("random_avg_return_to_1000_pct")),
            ]
            for row in rows
        ],
    )


def print_bucket_summary(rows: list[dict[str, Any]], limit: int) -> None:
    print()
    print("--- target real bucket summary by winning/failing cohort ---")
    print_table(
        [
            "cohort_class",
            "dimension",
            "bucket",
            "eligible",
            "eval",
            "avg1000",
            "worst1000",
            "sel_rate",
        ],
        [
            [
                str(row.get("cohort_class")),
                str(row.get("dimension")),
                str(row.get("bucket")),
                str(row.get("eligible_rows")),
                str(row.get("evaluated_rows")),
                fmt(row.get("avg_return_to_1000_pct")),
                fmt(row.get("worst_return_to_1000_pct")),
                fmt(row.get("avg_selection_rate_pct"), 2),
            ]
            for row in rows[:limit]
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only regime-gate diagnostic for Breath Curve candidates."
    )
    parser.add_argument("--default-dir", default="data/research/breath_curve_broader_history_v1")
    parser.add_argument("--target-composite", default=TARGET_COMPOSITE_DEFAULT)
    parser.add_argument("--min-winning-real-eligible", type=int, default=10)
    parser.add_argument("--out-dir", default="data/research/breath_curve_regime_gate_v1")
    parser.add_argument("--include-duplicate-manifests", action="store_true")
    parser.add_argument("--include-non-zero-post-pad-runs", action="store_true")
    parser.add_argument("--limit-print", type=int, default=160)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    run_dirs = discover_run_dirs(args.default_dir)

    discovered_run_count = len(run_dirs)

    if not args.include_non_zero_post_pad_runs:
        run_dirs = [run_dir for run_dir in run_dirs if manifest_is_zero_post_pad(run_dir)]

    zero_post_pad_filtered_count = len(run_dirs)

    if not args.include_duplicate_manifests:
        run_dirs = dedupe_run_dirs_by_manifest(run_dirs)

    deduped_run_count = len(run_dirs)

    run_summaries = [
        classify_run(
            run_dir,
            target_composite=args.target_composite,
            min_winning_real_eligible=args.min_winning_real_eligible,
        )
        for run_dir in run_dirs
    ]

    aggregate_rows = load_all_aggregate_rows(run_summaries)
    separation_rows = candidate_separation_rows(aggregate_rows)
    cohort_rows = load_cohort_rows(run_summaries)
    target_rows = target_cohort_rows(cohort_rows, args.target_composite)
    class_summary_rows = cohort_class_summary(cohort_rows, args.target_composite)
    bucket_rows = collect_bucket_rows(run_summaries, cohort_rows, args.target_composite)
    bucket_summary_rows = bucket_summary(bucket_rows)

    out_dir = Path(args.out_dir)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    run_classification_path = out_dir / f"breath_curve_regime_gate_v1_{run_stamp}_run_classification.csv"
    separation_path = out_dir / f"breath_curve_regime_gate_v1_{run_stamp}_composite_separation.csv"
    cohort_path = out_dir / f"breath_curve_regime_gate_v1_{run_stamp}_target_cohorts.csv"
    cohort_class_path = out_dir / f"breath_curve_regime_gate_v1_{run_stamp}_cohort_class_summary.csv"
    bucket_rows_path = out_dir / f"breath_curve_regime_gate_v1_{run_stamp}_bucket_rows.csv"
    bucket_summary_path = out_dir / f"breath_curve_regime_gate_v1_{run_stamp}_bucket_summary.csv"

    write_csv(
        run_classification_path,
        [
            {
                "run_id": row.run_id,
                "run_dir": str(row.run_dir),
                "regime_class": row.regime_class,
                "target_edge": row.target_edge,
                "target_real_eligible": row.target_real_eligible,
                "target_random_eligible": row.target_random_eligible,
                "target_real_avg1000": row.target_real_avg1000,
                "target_random_avg1000": row.target_random_avg1000,
            }
            for row in run_summaries
        ],
    )
    write_csv(separation_path, separation_rows)
    write_csv(cohort_path, target_rows)
    write_csv(cohort_class_path, class_summary_rows)
    write_csv(bucket_rows_path, bucket_rows)
    write_csv(bucket_summary_path, bucket_summary_rows)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print(f"target_composite={args.target_composite}")
        print(f"discovered_run_count={discovered_run_count}")
        print(f"zero_post_pad_filtered_count={zero_post_pad_filtered_count}")
        print(f"deduped_run_count={deduped_run_count}")
        print(f"include_duplicate_manifests={args.include_duplicate_manifests}")
        print(f"include_non_zero_post_pad_runs={args.include_non_zero_post_pad_runs}")
        print(f"run_count={len(run_summaries)}")
        print()

        print_run_classification(run_summaries)
        print_candidate_separation(separation_rows)
        print_target_cohorts(target_rows, args.target_composite)
        print_bucket_summary(bucket_summary_rows, args.limit_print)

        print()
        print(f"wrote_run_classification={run_classification_path}")
        print(f"wrote_composite_separation={separation_path}")
        print(f"wrote_target_cohorts={cohort_path}")
        print(f"wrote_cohort_class_summary={cohort_class_path}")
        print(f"wrote_bucket_rows={bucket_rows_path}")
        print(f"wrote_bucket_summary={bucket_summary_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
