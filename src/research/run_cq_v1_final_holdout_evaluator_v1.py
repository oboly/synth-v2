"""One-shot preregistered final holdout evaluator for Issue #684.

research_only=1
market_only=1
account_awareness=0
db_writes=0
model_retuning=0
production_ranking_changes=0
runtime_activation=0
holdout_analytics_read=1

Frozen candidate family and metric semantics are reused unchanged from the
merged discovery/validation evaluator. This runner supports holdout only.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from src.research import cq_v1_discovery_validation_evaluator_v1 as core

RUNNER_NAME = "run_cq_v1_final_holdout_evaluator_v1"
HOLDOUT_SPLITS = ("holdout",)
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
    "holdout_analytics_read": 1,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="#684 preregistered final holdout evaluator; holdout only")
    parser.add_argument("--population", required=True)
    parser.add_argument("--outcomes", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def _with_safety(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, **SAFETY_MARKERS}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _metrics_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["metrics"].items():
        for horizon, by_score in by_horizon.items():
            for score, data in by_score.items():
                for metric in core.OUTCOME_METRICS:
                    coverage = data["coverage"][metric]
                    rows.append(_with_safety({
                        "split": split, "horizon": horizon, "score": score, "outcome_metric": metric,
                        "total_frozen_observations": data["total_frozen_observations"],
                        "complete_outcome_count": data["complete_outcome_count"],
                        "score_available_count": data["score_available_count"],
                        "jointly_eligible_count": coverage["jointly_eligible_count"],
                        "coverage_pct": coverage["coverage_pct"], "pearson": coverage["pearson"],
                        "spearman": coverage["spearman"],
                        "top_bottom_spread": data["buckets"][metric]["top_bottom_spread"],
                    }))
    return rows


def _bucket_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["metrics"].items():
        for horizon, by_score in by_horizon.items():
            for score, data in by_score.items():
                for metric in core.OUTCOME_METRICS:
                    for bucket in data["buckets"][metric]["buckets"]:
                        rows.append(_with_safety({
                            "split": split, "horizon": horizon, "score": score, "outcome_metric": metric,
                            "bucket": bucket["bucket"], "n": bucket["n"], "score_min": bucket["score_min"],
                            "score_max": bucket["score_max"], "score_mean": bucket["score_mean"],
                            "outcome_mean": bucket[metric]["mean"], "outcome_median": bucket[metric]["median"],
                        }))
    return rows


def _pairwise_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["pairwise"].items():
        for horizon, by_pair in by_horizon.items():
            for pair_key, by_metric in by_pair.items():
                for metric, data in by_metric.items():
                    rows.append(_with_safety({
                        "split": split, "horizon": horizon, "pair": pair_key, "outcome_metric": metric, "n": data["n"],
                        "pearson_left": data["pearson"]["left"], "pearson_right": data["pearson"]["right"],
                        "pearson_delta": data["pearson"]["delta"], "spearman_left": data["spearman"]["left"],
                        "spearman_right": data["spearman"]["right"], "spearman_delta": data["spearman"]["delta"],
                        "top_bottom_spread_left": data["top_bottom_spread"]["left"],
                        "top_bottom_spread_right": data["top_bottom_spread"]["right"],
                        "top_bottom_spread_delta": data["top_bottom_spread"]["delta"],
                    }))
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        raise ValueError(f"immutable output directory already exists: {output_dir}")
    population_path = Path(args.population)
    outcomes_path = Path(args.outcomes)
    population = core.load_population(population_path)
    outcomes = core.load_outcomes(outcomes_path)
    core.validate_identity(population, outcomes)
    holdout_population = [row for row in population if str(row["split"]) == "holdout"]
    holdout_outcomes = [row for row in outcomes if str(row["split"]) == "holdout"]
    if len(holdout_population) != 4004:
        raise ValueError(f"holdout population row count mismatch expected=4004 actual={len(holdout_population)}")
    if len(holdout_outcomes) != core.PINNED_SPLIT_OUTCOME_ROW_COUNTS["holdout"]:
        raise ValueError("holdout outcome row count mismatch")
    print(f"PHASE runner={RUNNER_NAME} phase=open_preregistered_holdout holdout_population_rows={len(holdout_population)} holdout_outcome_rows={len(holdout_outcomes)} holdout_analytics_read=1", flush=True)
    evaluation = core.evaluate(holdout_population, holdout_outcomes, HOLDOUT_SPLITS)
    metrics_rows = _metrics_rows(evaluation)
    bucket_rows = _bucket_rows(evaluation)
    pairwise_rows = _pairwise_rows(evaluation)
    manifest = {
        "runner": RUNNER_NAME, "evaluator_version": core.EVALUATOR_VERSION, "issue": core.ISSUE,
        "preregistered_split": "holdout", "splits_evaluated": ["holdout"],
        "population_sha256": core.PINNED_POPULATION_SHA256, "outcomes_sha256": core.PINNED_OUTCOMES_SHA256,
        "holdout_population_row_count": len(holdout_population), "holdout_outcome_row_count": len(holdout_outcomes),
        "horizons": list(core.HORIZONS), "baseline_scores": list(core.BASELINE_SCORES),
        "pairwise": [list(pair) for pair in core.PAIRWISE],
        "candidate_formulas": {
            "cq_v0": "existing frozen cq_v0 shadow score",
            "cq_v1_balanced": "0.50 * cq_v0 + 0.50 * normalized_mrp_aggregate",
            "cq_v1_anchor": "0.75 * cq_v0 + 0.25 * normalized_mrp_aggregate",
            "normalized_mrp_aggregate": "(mrp_aggregate.market_score + 100) / 200",
        },
        "eligibility_rule": "status == COMPLETE and score available and outcome metric available; identical eligible sample per pair",
        "bucket_policy": {"scheme": "deciles", "bucket_count": core.BUCKET_COUNT, "fallback": "min(10, eligible_n)", "tie_handling": "sort by (score, observation_id)"},
        "metrics_row_count": len(metrics_rows), "bucket_row_count": len(bucket_rows), "pairwise_row_count": len(pairwise_rows),
        **SAFETY_MARKERS,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "evaluation.json", {**evaluation, **SAFETY_MARKERS})
    _write_csv(output_dir / "metrics.csv", metrics_rows)
    _write_csv(output_dir / "bucket_metrics.csv", bucket_rows)
    _write_csv(output_dir / "pairwise_comparisons.csv", pairwise_rows)
    _write_json(output_dir / "manifest.json", manifest)
    (output_dir / "summary.md").write_text("# CQ v1 final preregistered holdout evaluator (#684)\n\n" + "\n".join(f"{k}={v}" for k, v in SAFETY_MARKERS.items()) + "\n\nsplits_evaluated=holdout\ncandidate_family=frozen_from_discovery_validation\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(f"STARTED runner={RUNNER_NAME} mode=final_holdout_only output_dir={args.output_dir}", flush=True)
    print("SAFETY " + " ".join(f"{k}={v}" for k, v in SAFETY_MARKERS.items()), flush=True)
    try:
        manifest = run(args)
    except Exception as exc:
        print(f"FAILED runner={RUNNER_NAME} error_type={type(exc).__name__} error={str(exc)!r} holdout_analytics_read=1 db_writes=0", flush=True)
        return 1
    print(f"FINISHED runner={RUNNER_NAME} split=holdout holdout_population_rows={manifest['holdout_population_row_count']} holdout_outcome_rows={manifest['holdout_outcome_row_count']} holdout_analytics_read=1 db_writes=0 output_dir={args.output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
