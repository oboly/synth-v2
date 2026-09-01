"""CLI runner for the frozen CQ v1 discovery+validation evaluator (#684).

research_only=1
market_only=1
account_awareness=0
db_writes=0
model_retuning=0
production_ranking_changes=0
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
holdout_analytics_read=0
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from src.research import cq_v1_discovery_validation_evaluator_v1 as core

RUNNER_NAME = "run_cq_v1_discovery_validation_evaluator_v1"

SAFETY_MARKERS = {
    "research_only": 1,
    "market_only": 1,
    "account_awareness": 0,
    "db_writes": 0,
    "model_retuning": 0,
    "production_ranking_changes": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "runtime_activation": 0,
    "holdout_analytics_read": 0,
}

OUTPUT_EVALUATION = "evaluation.json"
OUTPUT_METRICS_CSV = "metrics.csv"
OUTPUT_BUCKETS_CSV = "bucket_metrics.csv"
OUTPUT_PAIRWISE_CSV = "pairwise_comparisons.csv"
OUTPUT_MANIFEST = "manifest.json"
OUTPUT_SUMMARY_MD = "summary.md"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#684 frozen CQ v1 evaluator: discovery/validation only, holdout analytics disabled"
    )
    parser.add_argument("--population", required=True)
    parser.add_argument("--outcomes", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--split",
        choices=list(core.ALLOWED_EVAL_SPLITS),
        default="discovery_validation",
        help="holdout and all are not implemented in this evaluator and are rejected",
    )
    return parser.parse_args(argv)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _metrics_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["metrics"].items():
        for horizon, by_score in by_horizon.items():
            for score, data in by_score.items():
                for outcome_metric in core.OUTCOME_METRICS:
                    coverage = data["coverage"][outcome_metric]
                    rows.append(
                        {
                            "split": split,
                            "horizon": horizon,
                            "score": score,
                            "outcome_metric": outcome_metric,
                            "total_frozen_observations": data["total_frozen_observations"],
                            "complete_outcome_count": data["complete_outcome_count"],
                            "score_available_count": data["score_available_count"],
                            "jointly_eligible_count": coverage["jointly_eligible_count"],
                            "coverage_pct": coverage["coverage_pct"],
                            "pearson": coverage["pearson"],
                            "spearman": coverage["spearman"],
                            "top_bottom_spread": data["buckets"][outcome_metric]["top_bottom_spread"],
                        }
                    )
    return rows


def _bucket_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["metrics"].items():
        for horizon, by_score in by_horizon.items():
            for score, data in by_score.items():
                for outcome_metric in core.OUTCOME_METRICS:
                    for bucket in data["buckets"][outcome_metric]["buckets"]:
                        rows.append(
                            {
                                "split": split,
                                "horizon": horizon,
                                "score": score,
                                "outcome_metric": outcome_metric,
                                "bucket": bucket["bucket"],
                                "n": bucket["n"],
                                "score_min": bucket["score_min"],
                                "score_max": bucket["score_max"],
                                "score_mean": bucket["score_mean"],
                                "outcome_mean": bucket[outcome_metric]["mean"],
                                "outcome_median": bucket[outcome_metric]["median"],
                            }
                        )
    return rows


def _pairwise_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["pairwise"].items():
        for horizon, by_pair in by_horizon.items():
            for pair_key, by_outcome in by_pair.items():
                for outcome_metric, data in by_outcome.items():
                    rows.append(
                        {
                            "split": split,
                            "horizon": horizon,
                            "pair": pair_key,
                            "outcome_metric": outcome_metric,
                            "n": data["n"],
                            "pearson_left": data["pearson"]["left"],
                            "pearson_right": data["pearson"]["right"],
                            "pearson_delta": data["pearson"]["delta"],
                            "spearman_left": data["spearman"]["left"],
                            "spearman_right": data["spearman"]["right"],
                            "spearman_delta": data["spearman"]["delta"],
                            "top_bottom_spread_left": data["top_bottom_spread"]["left"],
                            "top_bottom_spread_right": data["top_bottom_spread"]["right"],
                            "top_bottom_spread_delta": data["top_bottom_spread"]["delta"],
                        }
                    )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(args: argparse.Namespace) -> dict[str, Any]:
    eval_splits = core.resolve_eval_splits(args.split)

    output_dir = Path(args.output_dir)
    if output_dir.exists():
        raise ValueError(f"immutable output directory already exists: {output_dir}")

    population_path = Path(args.population)
    outcomes_path = Path(args.outcomes)
    population = core.load_population(population_path)
    outcomes = core.load_outcomes(outcomes_path)
    core.validate_identity(population, outcomes)

    safe_population, safe_outcomes = core.filter_safe_rows(population, outcomes, eval_splits)
    evaluation = core.evaluate(safe_population, safe_outcomes, eval_splits)

    manifest = {
        "runner": RUNNER_NAME,
        "evaluator_version": core.EVALUATOR_VERSION,
        "issue": core.ISSUE,
        "population_path": str(population_path),
        "population_sha256": core.PINNED_POPULATION_SHA256,
        "outcomes_path": str(outcomes_path),
        "outcomes_sha256": core.PINNED_OUTCOMES_SHA256,
        "split_requested": args.split,
        "splits_evaluated": list(eval_splits),
        "horizons": list(core.HORIZONS),
        "population_row_count": core.PINNED_POPULATION_ROW_COUNT,
        "outcomes_row_count": core.PINNED_OUTCOMES_ROW_COUNT,
        "split_outcome_row_counts": core.PINNED_SPLIT_OUTCOME_ROW_COUNTS,
        "candidate_formulas": {
            "cq_v0": "existing frozen cq_v0 shadow score",
            "cq_v1_balanced": "0.50 * cq_v0 + 0.50 * normalized_mrp_aggregate",
            "cq_v1_anchor": "0.75 * cq_v0 + 0.25 * normalized_mrp_aggregate",
            "normalized_mrp_aggregate": "(mrp_aggregate.market_score + 100) / 200",
        },
        "baseline_scores": list(core.BASELINE_SCORES),
        "eligibility_rule": "status == COMPLETE and score available and outcome metric available (identical eligible sample per comparison)",
        "bucket_policy": {
            "scheme": "deciles",
            "bucket_count": core.BUCKET_COUNT,
            "fallback": "bucket_count = min(10, eligible_n) when eligible_n < 10",
            "tie_handling": "sort by (score, observation_id), ordinal rank split into fixed buckets",
        },
        **SAFETY_MARKERS,
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / OUTPUT_EVALUATION, {**evaluation, **SAFETY_MARKERS})
    _write_csv(output_dir / OUTPUT_METRICS_CSV, _metrics_rows(evaluation))
    _write_csv(output_dir / OUTPUT_BUCKETS_CSV, _bucket_rows(evaluation))
    _write_csv(output_dir / OUTPUT_PAIRWISE_CSV, _pairwise_rows(evaluation))
    _write_json(output_dir / OUTPUT_MANIFEST, manifest)

    summary_lines = [
        "# CQ v1 discovery/validation evaluator (#684)",
        "",
        f"evaluator_version={core.EVALUATOR_VERSION}",
        f"splits_evaluated={','.join(eval_splits)}",
        "holdout_analytics_read=0",
        "model_retuning=0",
        "production_ranking_changes=0",
        "",
        "This artifact reports technical research metrics only. It is not a",
        "directional trading recommendation and does not authorize any",
        "production ranking change.",
        "",
    ]
    (output_dir / OUTPUT_SUMMARY_MD).write_text("\n".join(summary_lines), encoding="utf-8")

    print(
        f"FINISHED runner={RUNNER_NAME} splits={list(eval_splits)} "
        f"population_rows={len(population)} outcome_rows={len(outcomes)} "
        f"output_dir={output_dir}",
        flush=True,
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        f"STARTED runner={RUNNER_NAME} mode=discovery_validation_only split={args.split} "
        f"population={args.population} outcomes={args.outcomes} output_dir={args.output_dir}",
        flush=True,
    )
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
