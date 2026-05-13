from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "strategy_scoring_board_v1"
VERSION = "0.1"


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    composite_name: str
    family: str
    version: str
    target: str
    candidate_role: str
    structural_penalty_points: float
    notes: str


STRATEGIES = [
    StrategySpec(
        strategy_id="breath_curve.minus8_all.v1",
        composite_name="minus8_all_v1",
        family="breath_curve",
        version="v1",
        target="return_to_1.000",
        candidate_role="baseline",
        structural_penalty_points=4.0,
        notes="baseline calibrated 0.618 selected -8 candidate",
    ),
    StrategySpec(
        strategy_id="breath_curve.minus8_core_symbols.v1",
        composite_name="minus8_core_symbols_v1",
        family="breath_curve",
        version="v1",
        target="return_to_1.000",
        candidate_role="primary_balanced",
        structural_penalty_points=0.0,
        notes="primary balanced candidate: 0.618 selected -8 + BTC/ETH/FIL/TAO",
    ),
    StrategySpec(
        strategy_id="breath_curve.minus8_core_volume_expansion.v1",
        composite_name="minus8_core_and_volume_expansion_v1",
        family="breath_curve",
        version="v1",
        target="return_to_1.000",
        candidate_role="precision_sample_thin",
        structural_penalty_points=0.0,
        notes="precision candidate: core symbols + volume expansion",
    ),
    StrategySpec(
        strategy_id="breath_curve.minus8_core_btc_eth_bear.v1",
        composite_name="minus8_core_and_btc_eth_bear_v1",
        family="breath_curve",
        version="v1",
        target="return_to_1.000",
        candidate_role="context_confirming",
        structural_penalty_points=1.0,
        notes="context candidate: core symbols + BTC/ETH bearish context",
    ),
    StrategySpec(
        strategy_id="breath_curve.minus8_volume_expansion.v1",
        composite_name="minus8_volume_expansion_v1",
        family="breath_curve",
        version="v1",
        target="return_to_1.000",
        candidate_role="precision_context_clue",
        structural_penalty_points=3.0,
        notes="volume expansion clue independent of core symbol subset",
    ),
    StrategySpec(
        strategy_id="breath_curve.early_band_core_bear_or_volume.v1",
        composite_name="early_band_core_and_bear_or_volume_v1",
        family="breath_curve",
        version="v1",
        target="return_to_1.000",
        candidate_role="recall_includes_demoted_minus7",
        structural_penalty_points=10.0,
        notes="recall candidate; includes selected -7 so less clean",
    ),
]


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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fmt(value: Any, places: int = 4) -> str:
    parsed = as_float(value)
    if parsed is None:
        return ""
    text = f"{parsed:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def latest_aggregate(default_dir: str) -> Path:
    paths = sorted(
        Path(default_dir).glob("breath_curve_broader_history_v1_*/aggregate_comparison_summary.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        raise RuntimeError(f"No aggregate_comparison_summary.csv found under {default_dir}")
    return paths[0]


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


def find_cohort_rows(aggregate_csv: Path) -> list[dict[str, Any]]:
    candidate = aggregate_csv.parent / "all_cohort_comparison_rows.csv"
    if not candidate.exists():
        return []
    return read_csv(candidate)


def cohort_stats(cohort_rows: list[dict[str, Any]], composite_name: str) -> dict[str, Any]:
    rows = [row for row in cohort_rows if row.get("composite_name") == composite_name]
    if not rows:
        return {
            "cohort_edge_positive_count": None,
            "cohort_edge_positive_rate_pct": None,
            "cohort_count_seen": None,
        }

    positive = 0
    valid = 0

    for row in rows:
        edge = as_float(row.get("edge_avg_return_to_1000_pct"))
        if edge is None:
            continue
        valid += 1
        if edge > 0:
            positive += 1

    return {
        "cohort_edge_positive_count": positive,
        "cohort_edge_positive_rate_pct": round(positive / valid * 100.0, 4) if valid else None,
        "cohort_count_seen": valid,
    }


def score_strategy(
    row: dict[str, Any],
    *,
    overlap_penalty: float,
    leakage_penalty: float,
    min_real_for_paper: int,
    min_random_for_paper: int,
    non_overlapping: bool,
    cohort_positive_rate: float | None,
) -> dict[str, Any]:
    real_eligible = as_int(row.get("real_eligible"))
    random_eligible = as_int(row.get("random_eligible"))
    real_evaluated = as_int(row.get("real_evaluated"))
    random_evaluated = as_int(row.get("random_evaluated"))

    edge = as_float(row.get("edge_avg_return_to_1000_pct"))
    edge_pos = as_float(row.get("edge_positive_to_1000_pct"))
    edge_worst = as_float(row.get("edge_worst_return_to_1000_pct"))

    real_avg = as_float(row.get("real_avg_return_to_1000_pct"))
    random_avg = as_float(row.get("random_avg_return_to_1000_pct"))
    real_pos = as_float(row.get("real_positive_to_1000_pct"))
    random_pos = as_float(row.get("random_positive_to_1000_pct"))
    real_worst = as_float(row.get("real_worst_return_to_1000_pct"))
    random_worst = as_float(row.get("random_worst_return_to_1000_pct"))
    real_sel = as_float(row.get("real_selection_rate_pct"))
    random_sel = as_float(row.get("random_selection_rate_pct"))

    selection_delta = None
    if real_sel is not None and random_sel is not None:
        selection_delta = round(real_sel - random_sel, 4)

    edge_score = clamp(((edge or 0.0) / 10.0) * 25.0, 0.0, 25.0)

    positive_score = 0.0
    if real_pos is not None:
        positive_score += clamp(real_pos / 100.0 * 10.0, 0.0, 10.0)
    if edge_pos is not None:
        positive_score += clamp(edge_pos / 20.0 * 5.0, 0.0, 5.0)

    worst_score = 0.0
    if real_worst is not None and real_worst > 0:
        worst_score += clamp(real_worst / 5.0 * 10.0, 0.0, 10.0)
    if edge_worst is not None and edge_worst > 0:
        worst_score += clamp(edge_worst / 5.0 * 10.0, 0.0, 10.0)

    sample_score = 0.0
    sample_score += clamp(real_eligible / max(min_real_for_paper, 1) * 8.0, 0.0, 8.0)
    sample_score += clamp(random_eligible / max(min_random_for_paper, 1) * 5.0, 0.0, 5.0)
    sample_score += clamp((as_int(row.get("cohort_count")) / 3.0) * 2.0, 0.0, 2.0)

    cohort_score = 0.0
    if cohort_positive_rate is not None:
        cohort_score = clamp(cohort_positive_rate / 100.0 * 15.0, 0.0, 15.0)

    selection_score = 0.0
    if selection_delta is not None and selection_delta > 0:
        selection_score = clamp(selection_delta / 15.0 * 10.0, 0.0, 10.0)

    raw_score = edge_score + positive_score + worst_score + sample_score + cohort_score + selection_score

    penalties: list[str] = []
    penalty_points = 0.0

    if not non_overlapping:
        penalty_points += overlap_penalty
        penalties.append(f"OVERLAPPING_COHORTS:{fmt(overlap_penalty, 2)}")

    if leakage_penalty > 0:
        penalty_points += leakage_penalty
        penalties.append(f"LEAKAGE_RISK:{fmt(leakage_penalty, 2)}")

    if real_eligible < 5:
        penalty_points += 10.0
        penalties.append("REAL_SAMPLE_LT_5:10")
    elif real_eligible < 10:
        penalty_points += 5.0
        penalties.append("REAL_SAMPLE_LT_10:5")

    if random_eligible < 20:
        penalty_points += 3.0
        penalties.append("RANDOM_SAMPLE_LT_20:3")

    if real_worst is not None and real_worst < 0:
        penalty_points += 10.0
        penalties.append("NEGATIVE_REAL_WORST:10")

    if edge is not None and edge <= 0:
        penalty_points += 15.0
        penalties.append("NON_POSITIVE_EDGE:15")

    final_score = round(clamp(raw_score - penalty_points, 0.0, 100.0), 4)

    blockers: list[str] = []

    if not non_overlapping:
        blockers.append("NEEDS_NON_OVERLAPPING_VALIDATION")
    if real_eligible < min_real_for_paper:
        blockers.append(f"REAL_ELIGIBLE_LT_{min_real_for_paper}")
    if random_eligible < min_random_for_paper:
        blockers.append(f"RANDOM_ELIGIBLE_LT_{min_random_for_paper}")
    if real_worst is None or real_worst <= 0:
        blockers.append("REAL_WORST_NOT_POSITIVE")
    if edge is None or edge <= 0:
        blockers.append("EDGE_NOT_POSITIVE")

    if final_score >= 75 and not blockers:
        promotion_status = "PAPER_CANDIDATE"
    elif final_score >= 60 and edge is not None and edge > 0 and real_worst is not None and real_worst > 0:
        promotion_status = "VALIDATION_CANDIDATE"
    elif final_score >= 40:
        promotion_status = "RESEARCH_ONLY"
    else:
        promotion_status = "REJECTED"

    return {
        "real_eligible": real_eligible,
        "random_eligible": random_eligible,
        "real_evaluated": real_evaluated,
        "random_evaluated": random_evaluated,
        "real_selection_rate_pct": real_sel,
        "random_selection_rate_pct": random_sel,
        "selection_rate_delta_pct": selection_delta,
        "real_avg_return_to_1000_pct": real_avg,
        "random_avg_return_to_1000_pct": random_avg,
        "edge_avg_return_to_1000_pct": edge,
        "real_positive_to_1000_pct": real_pos,
        "random_positive_to_1000_pct": random_pos,
        "edge_positive_to_1000_pct": edge_pos,
        "real_worst_return_to_1000_pct": real_worst,
        "random_worst_return_to_1000_pct": random_worst,
        "edge_worst_return_to_1000_pct": edge_worst,
        "edge_score": round(edge_score, 4),
        "positive_score": round(positive_score, 4),
        "worst_case_score": round(worst_score, 4),
        "sample_score": round(sample_score, 4),
        "cohort_stability_score": round(cohort_score, 4),
        "selection_quality_score": round(selection_score, 4),
        "raw_score": round(raw_score, 4),
        "penalty_points": round(penalty_points, 4),
        "overall_research_score": final_score,
        "promotion_status": promotion_status,
        "penalties": ",".join(penalties),
        "blockers": ",".join(blockers),
    }


def apply_structural_penalty(scored: dict[str, Any], spec: StrategySpec) -> dict[str, Any]:
    out = dict(scored)

    structural_penalty = float(spec.structural_penalty_points)
    if structural_penalty <= 0:
        out["structural_penalty_points"] = 0.0
        return out

    existing_penalties = str(out.get("penalties", "")).strip()
    penalty_label = f"STRUCTURAL_{spec.candidate_role}:{fmt(structural_penalty, 2)}"

    out["structural_penalty_points"] = structural_penalty
    out["penalty_points"] = round((as_float(out.get("penalty_points")) or 0.0) + structural_penalty, 4)
    out["overall_research_score"] = round(
        clamp((as_float(out.get("overall_research_score")) or 0.0) - structural_penalty, 0.0, 100.0),
        4,
    )
    out["penalties"] = ",".join([x for x in [existing_penalties, penalty_label] if x])

    score = as_float(out.get("overall_research_score")) or 0.0
    edge = as_float(out.get("edge_avg_return_to_1000_pct"))
    real_worst = as_float(out.get("real_worst_return_to_1000_pct"))
    blockers = str(out.get("blockers", "")).strip()

    if score >= 75 and not blockers:
        out["promotion_status"] = "PAPER_CANDIDATE"
    elif score >= 60 and edge is not None and edge > 0 and real_worst is not None and real_worst > 0:
        out["promotion_status"] = "VALIDATION_CANDIDATE"
    elif score >= 40:
        out["promotion_status"] = "RESEARCH_ONLY"
    else:
        out["promotion_status"] = "REJECTED"

    return out


def build_board_rows(
    aggregate_rows: list[dict[str, Any]],
    cohort_rows: list[dict[str, Any]],
    *,
    input_csv: Path,
    overlap_penalty: float,
    leakage_penalty: float,
    min_real_for_paper: int,
    min_random_for_paper: int,
    non_overlapping: bool,
) -> list[dict[str, Any]]:
    by_composite = {row.get("composite_name"): row for row in aggregate_rows}
    out: list[dict[str, Any]] = []

    asof = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for spec in STRATEGIES:
        source = by_composite.get(spec.composite_name)
        if not source:
            out.append(
                {
                    "asof_ts_utc": asof,
                    "strategy_id": spec.strategy_id,
                    "strategy_family": spec.family,
                    "strategy_version": spec.version,
                    "composite_name": spec.composite_name,
                    "target": spec.target,
                    "promotion_status": "MISSING_SOURCE",
                    "overall_research_score": 0,
                    "source_csv": str(input_csv),
                    "notes": spec.notes,
                }
            )
            continue

        cohort = cohort_stats(cohort_rows, spec.composite_name)
        scored = score_strategy(
            source,
            overlap_penalty=overlap_penalty,
            leakage_penalty=leakage_penalty,
            min_real_for_paper=min_real_for_paper,
            min_random_for_paper=min_random_for_paper,
            non_overlapping=non_overlapping,
            cohort_positive_rate=as_float(cohort.get("cohort_edge_positive_rate_pct")),
        )

        scored = apply_structural_penalty(scored, spec)

        out.append(
            {
                "asof_ts_utc": asof,
                "strategy_id": spec.strategy_id,
                "strategy_family": spec.family,
                "strategy_version": spec.version,
                "composite_name": spec.composite_name,
                "target": spec.target,
                "candidate_role": spec.candidate_role,
                "source_csv": str(input_csv),
                "research_only": True,
                "market_only": True,
                "account_agnostic": True,
                "selection_engine": "none",
                "decision_gate": "none",
                "execution_planner": "none",
                "executor": "none",
                "broker_writes": 0,
                "order_submission": 0,
                **cohort,
                **scored,
                "notes": spec.notes,
            }
        )

    return sorted(out, key=lambda row: as_float(row.get("overall_research_score")) or 0.0, reverse=True)


def print_board(rows: list[dict[str, Any]]) -> None:
    print("--- strategy scoring board ---")
    print_table(
        [
            "strategy",
            "status",
            "score",
            "real_elig",
            "rand_elig",
            "edge1000",
            "real_worst",
            "rand_worst",
            "cohort_pos",
            "blockers",
        ],
        [
            [
                str(row["strategy_id"]),
                str(row["promotion_status"]),
                fmt(row.get("overall_research_score"), 2),
                str(row.get("real_eligible", "")),
                str(row.get("random_eligible", "")),
                fmt(row.get("edge_avg_return_to_1000_pct")),
                fmt(row.get("real_worst_return_to_1000_pct")),
                fmt(row.get("random_worst_return_to_1000_pct")),
                fmt(row.get("cohort_edge_positive_rate_pct"), 2),
                str(row.get("blockers", "")),
            ]
            for row in rows
        ],
    )


def print_score_breakdown(rows: list[dict[str, Any]]) -> None:
    print()
    print("--- score breakdown ---")
    print_table(
        [
            "strategy",
            "edge",
            "positive",
            "worst",
            "sample",
            "cohort",
            "selection",
            "raw",
            "penalty",
            "final",
        ],
        [
            [
                str(row["strategy_id"]),
                fmt(row.get("edge_score"), 2),
                fmt(row.get("positive_score"), 2),
                fmt(row.get("worst_case_score"), 2),
                fmt(row.get("sample_score"), 2),
                fmt(row.get("cohort_stability_score"), 2),
                fmt(row.get("selection_quality_score"), 2),
                fmt(row.get("raw_score"), 2),
                fmt(row.get("penalty_points"), 2),
                fmt(row.get("overall_research_score"), 2),
            ]
            for row in rows
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only strategy scoring board v1.")
    parser.add_argument("--input-csv", default=None)
    parser.add_argument("--default-dir", default="data/research/breath_curve_broader_history_v1")
    parser.add_argument("--out-dir", default="data/research/strategy_scoring_board_v1")
    parser.add_argument("--overlap-penalty", type=float, default=10.0)
    parser.add_argument("--leakage-penalty", type=float, default=0.0)
    parser.add_argument("--min-real-for-paper", type=int, default=20)
    parser.add_argument("--min-random-for-paper", type=int, default=50)
    parser.add_argument("--non-overlapping", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_csv = Path(args.input_csv) if args.input_csv else latest_aggregate(args.default_dir)
    aggregate_rows = read_csv(input_csv)
    cohort_rows = find_cohort_rows(input_csv)

    board_rows = build_board_rows(
        aggregate_rows,
        cohort_rows,
        input_csv=input_csv,
        overlap_penalty=args.overlap_penalty,
        leakage_penalty=args.leakage_penalty,
        min_real_for_paper=args.min_real_for_paper,
        min_random_for_paper=args.min_random_for_paper,
        non_overlapping=args.non_overlapping,
    )

    out_dir = Path(args.out_dir)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    board_path = out_dir / f"strategy_scoring_board_v1_{run_stamp}.csv"

    write_csv(board_path, board_rows)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print(f"input_csv={input_csv}")
        print(f"cohort_rows={len(cohort_rows)}")
        print(f"non_overlapping={args.non_overlapping}")
        print(f"overlap_penalty={args.overlap_penalty}")
        print()

        print_board(board_rows)
        print_score_breakdown(board_rows)

        print()
        print(f"wrote_board={board_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
