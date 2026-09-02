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
import signal
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
SAFETY_MARKER_KEYS = tuple(SAFETY_MARKERS.keys())

OUTPUT_EVALUATION = "evaluation.json"
OUTPUT_METRICS_CSV = "metrics.csv"
OUTPUT_BUCKETS_CSV = "bucket_metrics.csv"
OUTPUT_PAIRWISE_CSV = "pairwise_comparisons.csv"
OUTPUT_MANIFEST = "manifest.json"
OUTPUT_SUMMARY_MD = "summary.md"


class _RunnerInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


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


def _with_safety_markers(row: dict[str, Any]) -> dict[str, Any]:
    """Append the complete frozen safety marker set in deterministic order."""
    return {**row, **SAFETY_MARKERS}


def _metrics_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["metrics"].items():
        for horizon, by_score in by_horizon.items():
            for score, data in by_score.items():
                for outcome_metric in core.OUTCOME_METRICS:
                    coverage = data["coverage"][outcome_metric]
                    rows.append(
                        _with_safety_markers(
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
                            _with_safety_markers(
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
                        )
    return rows


def _pairwise_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, by_horizon in evaluation["pairwise"].items():
        for horizon, by_pair in by_horizon.items():
            for pair_key, by_outcome in by_pair.items():
                for outcome_metric, data in by_outcome.items():
                    rows.append(
                        _with_safety_markers(
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


def _phase(name: str, **counts: Any) -> None:
    details = " ".join(f"{key}={value}" for key, value in counts.items())
    suffix = f" {details}" if details else ""
    print(f"PHASE runner={RUNNER_NAME} phase={name}{suffix}", flush=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    eval_splits = core.resolve_eval_splits(args.split)

    output_dir = Path(args.output_dir)
    if output_dir.exists():
        raise ValueError(f"immutable output directory already exists: {output_dir}")

    population_path = Path(args.population)
    outcomes_path = Path(args.outcomes)

    _phase("verify_inputs", split=args.split)
    population = core.load_population(population_path)
    outcomes = core.load_outcomes(outcomes_path)
    _phase("load_identity_metadata", population_rows=len(population), outcome_rows=len(outcomes))
    core.validate_identity(population, outcomes)

    safe_population, safe_outcomes = core.filter_safe_rows(population, outcomes, eval_splits)
    _phase(
        "filter_analytical_split",
        splits=",".join(eval_splits),
        safe_population_rows=len(safe_population),
        safe_outcome_rows=len(safe_outcomes),
        holdout_analytics_read=0,
    )

    _phase("compute_metrics", safe_outcome_rows=len(safe_outcomes))
    evaluation = core.evaluate(safe_population, safe_outcomes, eval_splits)

    metrics_rows = _metrics_rows(evaluation)
    bucket_rows = _bucket_rows(evaluation)
    pairwise_rows = _pairwise_rows(evaluation)
    _phase(
        "write_artifacts",
        metrics_rows=len(metrics_rows),
        bucket_rows=len(bucket_rows),
        pairwise_rows=len(pairwise_rows),
    )

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
        "safe_population_row_count": len(safe_population),
        "safe_outcome_row_count": len(safe_outcomes),
        "metrics_row_count": len(metrics_rows),
        "bucket_row_count": len(bucket_rows),
        "pairwise_row_count": len(pairwise_rows),
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
    _write_csv(output_dir / OUTPUT_METRICS_CSV, metrics_rows)
    _write_csv(output_dir / OUTPUT_BUCKETS_CSV, bucket_rows)
    _write_csv(output_dir / OUTPUT_PAIRWISE_CSV, pairwise_rows)
    _write_json(output_dir / OUTPUT_MANIFEST, manifest)

    summary_lines = [
        "# CQ v1 discovery/validation evaluator (#684)",
        "",
        f"evaluator_version={core.EVALUATOR_VERSION}",
        f"splits_evaluated={','.join(eval_splits)}",
        *[f"{key}={SAFETY_MARKERS[key]}" for key in SAFETY_MARKER_KEYS],
        "",
        "This artifact reports technical research metrics only. It is not a",
        "directional trading recommendation and does not authorize any",
        "production ranking change.",
        "",
    ]
    (output_dir / OUTPUT_SUMMARY_MD).write_text("\n".join(summary_lines), encoding="utf-8")

    return manifest


def _signal_handler(signum: int, _frame: Any) -> None:
    raise _RunnerInterrupted(signum)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    previous_handlers: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, _signal_handler)

    print(
        f"STARTED runner={RUNNER_NAME} mode=discovery_validation_only split={args.split} "
        f"population={args.population} outcomes={args.outcomes} output_dir={args.output_dir}",
        flush=True,
    )
    print(
        "SAFETY " + " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items()),
        flush=True,
    )

    try:
        manifest = run(args)
    except _RunnerInterrupted as exc:
        print(
            f"INTERRUPTED runner={RUNNER_NAME} signal={exc.signum} resumable=0 "
            "holdout_analytics_read=0 db_writes=0",
            flush=True,
        )
        return 130
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} error_type={type(exc).__name__} "
            f"error={str(exc)!r} holdout_analytics_read=0 db_writes=0",
            flush=True,
        )
        return 1
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)

    print(
        f"FINISHED runner={RUNNER_NAME} splits={manifest['splits_evaluated']} "
        f"population_rows={manifest['population_row_count']} outcome_rows={manifest['outcomes_row_count']} "
        f"safe_outcome_rows={manifest['safe_outcome_row_count']} metrics_rows={manifest['metrics_row_count']} "
        f"bucket_rows={manifest['bucket_row_count']} pairwise_rows={manifest['pairwise_row_count']} "
        f"output_dir={args.output_dir} holdout_analytics_read=0 db_writes=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
