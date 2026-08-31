from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from src.research.cq_v1_holdout_comparison_v1 import (
    REQUIRED_CANDIDATES,
    evaluate,
    join_artifacts,
    promotion_verdict,
)
from src.research.cq_v1_model_candidate_v1 import (
    CANDIDATES_BY_ID,
    COVERAGE_ARTIFACT_SHA256,
    MODEL_FAMILY_VERSION,
)

RUNNER_NAME = "cq_v1_holdout_comparison_v1"
DEFAULT_PROTOCOL = "config/research/cq_v1_holdout_comparison_v1.yaml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Frozen CQ v1 cross-sectional holdout comparison")
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--forward-outcomes-jsonl", required=True)
    parser.add_argument("--cq-v1-scores-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:line={line_number}:MALFORMED_JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:line={line_number}:ROW_NOT_OBJECT")
            rows.append(payload)
    if not rows:
        raise ValueError(f"{path}:EMPTY_ARTIFACT")
    return rows


def _load_protocol(path: Path) -> dict[str, Any]:
    protocol = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if protocol.get("protocol_name") != RUNNER_NAME:
        raise ValueError("protocol_name mismatch")
    if protocol.get("protocol_version") != "1.0.0":
        raise ValueError("protocol_version mismatch")
    required = tuple(protocol.get("inputs", {}).get("required_score_candidates", []))
    if required != REQUIRED_CANDIDATES:
        raise ValueError("required CQ v1 candidate family mismatch")
    if tuple(protocol.get("holdout", {}).get("required_horizons", [])) != ("1h", "4h", "24h"):
        raise ValueError("required horizon family mismatch")
    if protocol.get("eligibility", {}).get("outcome_status_required") != "COMPLETE":
        raise ValueError("outcome status contract mismatch")
    return protocol


def _validate_frozen_score_contract(rows: list[dict[str, Any]]) -> None:
    required_set = set(REQUIRED_CANDIDATES)
    for row in rows:
        shadow_id = int(row.get("shadow_id"))
        if row.get("model_family_version") != MODEL_FAMILY_VERSION:
            raise ValueError(f"shadow_id={shadow_id}:MODEL_FAMILY_VERSION_MISMATCH")
        if row.get("coverage_artifact_sha256") != COVERAGE_ARTIFACT_SHA256:
            raise ValueError(f"shadow_id={shadow_id}:COVERAGE_ARTIFACT_MISMATCH")
        candidates = row.get("candidates")
        if not isinstance(candidates, dict):
            raise ValueError(f"shadow_id={shadow_id}:CANDIDATES_MISSING")
        if set(candidates) != required_set:
            raise ValueError(f"shadow_id={shadow_id}:CANDIDATE_SET_MISMATCH")
        for candidate_id in REQUIRED_CANDIDATES:
            payload = candidates[candidate_id]
            if not isinstance(payload, dict):
                raise ValueError(f"shadow_id={shadow_id}:{candidate_id}:PAYLOAD_INVALID")
            if payload.get("version") != CANDIDATES_BY_ID[candidate_id].version:
                raise ValueError(f"shadow_id={shadow_id}:{candidate_id}:VERSION_MISMATCH")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(args: argparse.Namespace) -> int:
    protocol_path = Path(args.protocol)
    outcomes_path = Path(args.forward_outcomes_jsonl)
    scores_path = Path(args.cq_v1_scores_jsonl)
    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit("output directory is not empty; use a new immutable output directory")

    print(
        f"STARTED runner={RUNNER_NAME} protocol={protocol_path} outcomes={outcomes_path} scores={scores_path}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 db_writes=0 production_ranking_changes=0 "
        "decision_gate=none execution_planner=none executor=none broker_private_calls=0 "
        "broker_writes=0 order_submission=0 live_orders=0",
        flush=True,
    )

    terminal_state = "FAILED"
    try:
        protocol = _load_protocol(protocol_path)
        print("PHASE_START name=load_artifacts", flush=True)
        outcome_rows = _load_jsonl(outcomes_path)
        score_rows = _load_jsonl(scores_path)
        _validate_frozen_score_contract(score_rows)
        print(
            f"PHASE_END name=load_artifacts outcome_rows={len(outcome_rows)} score_rows={len(score_rows)}",
            flush=True,
        )

        print("PHASE_START name=join_frozen_identity", flush=True)
        joined = join_artifacts(
            outcome_rows,
            score_rows,
            required_asof=str(protocol["holdout"]["observation_asof_ts_utc"]),
        )
        print(f"PHASE_END name=join_frozen_identity complete_rows={len(joined)}", flush=True)

        print("PHASE_START name=evaluate_identical_samples", flush=True)
        evaluation = evaluate(joined, bucket_count=int(protocol["metrics"]["buckets"]))
        print(
            f"PHASE_END name=evaluate_identical_samples observations={evaluation['complete_observation_count']}",
            flush=True,
        )

        rule = protocol["promotion_rule"]
        verdict, verdict_evidence = promotion_verdict(
            evaluation,
            minimum_candidate_sample=int(rule["minimum_candidate_sample"]),
            material_delta=float(rule["material_spearman_delta"]),
        )
        report = {
            "runner": RUNNER_NAME,
            "protocol_version": protocol["protocol_version"],
            "holdout_design": protocol["holdout"]["design"],
            "holdout_asof_ts_utc": protocol["holdout"]["observation_asof_ts_utc"],
            "model_family_version": MODEL_FAMILY_VERSION,
            "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
            "verdict": verdict,
            "evaluation": evaluation,
            "verdict_evidence": verdict_evidence,
            "target_outcomes": "UNAVAILABLE_NO_CANONICAL_TARGET_PRICE",
            "frozen_model_changed": 0,
            "production_ranking_changed": 0,
            "db_writes": 0,
        }
        _write_json(output_dir / "holdout_report.json", report)
        _write_json(
            output_dir / "summary.json",
            {
                "runner": RUNNER_NAME,
                "protocol_version": protocol["protocol_version"],
                "model_family_version": MODEL_FAMILY_VERSION,
                "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
                "verdict": verdict,
                "complete_observation_count": evaluation["complete_observation_count"],
                "horizon_counts": evaluation["horizon_counts"],
                "ppp_cohorts": sorted(evaluation["ppp_cohorts"].keys()),
                "candidate_ids": list(REQUIRED_CANDIDATES),
                "frozen_model_changed": 0,
                "production_ranking_changed": 0,
                "terminal_state": "FINISHED",
            },
        )
        terminal_state = "FINISHED"
        print(f"FINISHED runner={RUNNER_NAME} verdict={verdict}", flush=True)
        return 0
    finally:
        if terminal_state != "FINISHED":
            output_dir.mkdir(parents=True, exist_ok=True)
            _write_json(
                output_dir / "summary.json",
                {
                    "runner": RUNNER_NAME,
                    "protocol_version": "1.0.0",
                    "terminal_state": "FAILED",
                    "frozen_model_changed": 0,
                    "production_ranking_changed": 0,
                },
            )
            print(f"FAILED runner={RUNNER_NAME}", flush=True)


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
