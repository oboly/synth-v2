from __future__ import annotations

import argparse
import hashlib
import json
import re
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
MANIFEST_NAME = "cq_v1_holdout_input_manifest_v1"
MANIFEST_VERSION = "1.0.0"
PENDING_MANIFEST_SHA256 = "PENDING_RUNTIME_FREEZE"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Frozen CQ v1 cross-sectional holdout comparison")
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--frozen-manifest-json", required=True)
    parser.add_argument("--forward-outcomes-jsonl", required=True)
    parser.add_argument("--forward-summary-json", required=True)
    parser.add_argument("--cq-v1-scores-jsonl", required=True)
    parser.add_argument("--cq-v1-score-summary-json", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}:NOT_OBJECT")
    return payload


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
    if tuple(protocol.get("inputs", {}).get("required_score_candidates", [])) != REQUIRED_CANDIDATES:
        raise ValueError("required CQ v1 candidate family mismatch")
    if tuple(protocol.get("holdout", {}).get("required_horizons", [])) != ("1h", "4h", "24h"):
        raise ValueError("required horizon family mismatch")
    if protocol.get("inputs", {}).get("frozen_manifest_name") != MANIFEST_NAME:
        raise ValueError("frozen manifest name mismatch")
    if protocol.get("inputs", {}).get("frozen_manifest_version") != MANIFEST_VERSION:
        raise ValueError("frozen manifest version mismatch")
    manifest_sha = protocol.get("inputs", {}).get("frozen_manifest_sha256")
    if manifest_sha != PENDING_MANIFEST_SHA256 and not (
        isinstance(manifest_sha, str) and re.fullmatch(r"[0-9a-f]{64}", manifest_sha)
    ):
        raise ValueError("frozen manifest sha256 invalid")
    rule = protocol.get("promotion_rule", {})
    if set(rule) != {"minimum_candidate_sample", "material_spearman_delta"}:
        raise ValueError("promotion_rule schema mismatch")
    return protocol


def _validate_manifest_file_binding(protocol: dict[str, Any], manifest_path: Path) -> str:
    expected = str(protocol["inputs"]["frozen_manifest_sha256"])
    if expected == PENDING_MANIFEST_SHA256:
        raise ValueError("FROZEN_MANIFEST_NOT_YET_PINNED")
    actual = _sha256_file(manifest_path)
    if actual != expected:
        raise ValueError("FROZEN_MANIFEST_FILE_SHA256_MISMATCH")
    return actual


def _validate_manifest(
    protocol: dict[str, Any],
    manifest: dict[str, Any],
    *,
    outcomes_path: Path,
    forward_summary_path: Path,
    scores_path: Path,
    score_summary_path: Path,
) -> None:
    expected_fields = {
        "manifest_name",
        "manifest_version",
        "protocol_version",
        "observation_asof_ts_utc",
        "score_row_count",
        "outcome_row_count",
        "model_family_version",
        "coverage_artifact_sha256",
        "forward_outcomes_jsonl_sha256",
        "forward_summary_json_sha256",
        "cq_v1_scores_jsonl_sha256",
        "cq_v1_score_summary_json_sha256",
    }
    if set(manifest) != expected_fields:
        raise ValueError("FROZEN_MANIFEST_SCHEMA_MISMATCH")
    frozen = protocol["holdout"]["frozen_population"]
    expected_values = {
        "manifest_name": MANIFEST_NAME,
        "manifest_version": MANIFEST_VERSION,
        "protocol_version": protocol["protocol_version"],
        "observation_asof_ts_utc": protocol["holdout"]["observation_asof_ts_utc"],
        "score_row_count": int(frozen["score_row_count"]),
        "outcome_row_count": int(frozen["outcome_row_count"]),
        "model_family_version": MODEL_FAMILY_VERSION,
        "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
    }
    for field, expected in expected_values.items():
        if manifest.get(field) != expected:
            raise ValueError(f"FROZEN_MANIFEST_{field.upper()}_MISMATCH")
    actual_hashes = {
        "forward_outcomes_jsonl_sha256": _sha256_file(outcomes_path),
        "forward_summary_json_sha256": _sha256_file(forward_summary_path),
        "cq_v1_scores_jsonl_sha256": _sha256_file(scores_path),
        "cq_v1_score_summary_json_sha256": _sha256_file(score_summary_path),
    }
    for field, actual in actual_hashes.items():
        if manifest.get(field) != actual:
            raise ValueError(f"FROZEN_MANIFEST_{field.upper()}_MISMATCH")


def _validate_frozen_score_contract(rows: list[dict[str, Any]]) -> None:
    required_set = set(REQUIRED_CANDIDATES)
    for row in rows:
        shadow_id = int(row["shadow_id"])
        if row.get("model_family_version") != MODEL_FAMILY_VERSION:
            raise ValueError(f"shadow_id={shadow_id}:MODEL_FAMILY_VERSION_MISMATCH")
        if row.get("coverage_artifact_sha256") != COVERAGE_ARTIFACT_SHA256:
            raise ValueError(f"shadow_id={shadow_id}:COVERAGE_ARTIFACT_MISMATCH")
        candidates = row.get("candidates")
        if not isinstance(candidates, dict) or set(candidates) != required_set:
            raise ValueError(f"shadow_id={shadow_id}:CANDIDATE_SET_MISMATCH")
        for candidate_id in REQUIRED_CANDIDATES:
            payload = candidates[candidate_id]
            if not isinstance(payload, dict):
                raise ValueError(f"shadow_id={shadow_id}:{candidate_id}:PAYLOAD_INVALID")
            if payload.get("version") != CANDIDATES_BY_ID[candidate_id].version:
                raise ValueError(f"shadow_id={shadow_id}:{candidate_id}:VERSION_MISMATCH")


def _validate_frozen_population(
    protocol: dict[str, Any],
    outcome_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    forward_summary: dict[str, Any],
    score_summary: dict[str, Any],
) -> None:
    frozen = protocol["holdout"]["frozen_population"]
    expected_scores = int(frozen["score_row_count"])
    expected_last = int(frozen["last_shadow_id"])
    expected_outcomes = int(frozen["outcome_row_count"])
    expected_per_horizon = int(frozen["outcome_rows_per_horizon"])
    required_asof = str(protocol["holdout"]["observation_asof_ts_utc"])
    required_horizons = set(protocol["holdout"]["required_horizons"])

    if len(score_rows) != expected_scores:
        raise ValueError("FROZEN_SCORE_POPULATION_COUNT_MISMATCH")
    score_ids = [int(row["shadow_id"]) for row in score_rows]
    if len(set(score_ids)) != expected_scores:
        raise ValueError("FROZEN_SCORE_POPULATION_DUPLICATE_ID")
    if max(score_ids) != expected_last:
        raise ValueError("FROZEN_SCORE_POPULATION_LAST_ID_MISMATCH")

    if score_summary.get("runner") != "cq_v1_score_materialization_v1":
        raise ValueError("SCORE_SUMMARY_RUNNER_MISMATCH")
    if score_summary.get("terminal_state") != "FINISHED":
        raise ValueError("SCORE_SUMMARY_NOT_FINISHED")
    if int(score_summary.get("sample_count", -1)) != expected_scores:
        raise ValueError("SCORE_SUMMARY_SAMPLE_COUNT_MISMATCH")
    if int(score_summary.get("last_shadow_id", -1)) != expected_last:
        raise ValueError("SCORE_SUMMARY_LAST_ID_MISMATCH")
    if score_summary.get("model_family_version") != MODEL_FAMILY_VERSION:
        raise ValueError("SCORE_SUMMARY_MODEL_FAMILY_MISMATCH")
    if score_summary.get("coverage_artifact_sha256") != COVERAGE_ARTIFACT_SHA256:
        raise ValueError("SCORE_SUMMARY_COVERAGE_ARTIFACT_MISMATCH")

    if len(outcome_rows) != expected_outcomes:
        raise ValueError("FROZEN_OUTCOME_POPULATION_COUNT_MISMATCH")
    outcome_pairs: set[tuple[int, str]] = set()
    horizon_counts = {horizon: 0 for horizon in required_horizons}
    outcome_ids: set[int] = set()
    for row in outcome_rows:
        shadow_id = int(row["shadow_id"])
        horizon = str(row["horizon"])
        if horizon not in required_horizons:
            raise ValueError(f"UNEXPECTED_HORIZON:{horizon}")
        pair = (shadow_id, horizon)
        if pair in outcome_pairs:
            raise ValueError("FROZEN_OUTCOME_DUPLICATE_IDENTITY")
        outcome_pairs.add(pair)
        horizon_counts[horizon] += 1
        outcome_ids.add(shadow_id)
        if str(row.get("observation_asof_ts_utc")) != required_asof:
            raise ValueError(f"shadow_id={shadow_id}:OUTCOME_ASOF_MISMATCH")
    if outcome_ids != set(score_ids):
        raise ValueError("FROZEN_OUTCOME_SCORE_POPULATION_MISMATCH")
    if any(count != expected_per_horizon for count in horizon_counts.values()):
        raise ValueError("FROZEN_OUTCOME_HORIZON_COUNT_MISMATCH")

    if forward_summary.get("runner") != "entry_quality_forward_validation_v1":
        raise ValueError("FORWARD_SUMMARY_RUNNER_MISMATCH")
    if int(forward_summary.get("row_count", -1)) != expected_outcomes:
        raise ValueError("FORWARD_SUMMARY_ROW_COUNT_MISMATCH")
    if int(forward_summary.get("observation_count", -1)) != expected_scores:
        raise ValueError("FORWARD_SUMMARY_OBSERVATION_COUNT_MISMATCH")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(args: argparse.Namespace) -> int:
    protocol_path = Path(args.protocol)
    manifest_path = Path(args.frozen_manifest_json)
    outcomes_path = Path(args.forward_outcomes_jsonl)
    forward_summary_path = Path(args.forward_summary_json)
    scores_path = Path(args.cq_v1_scores_jsonl)
    score_summary_path = Path(args.cq_v1_score_summary_json)
    output_dir = Path(args.output_dir)

    print(
        f"STARTED runner={RUNNER_NAME} protocol={protocol_path} manifest={manifest_path} outcomes={outcomes_path} scores={scores_path}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 db_writes=0 production_ranking_changes=0 "
        "decision_gate=none execution_planner=none executor=none broker_private_calls=0 "
        "broker_writes=0 order_submission=0 live_orders=0",
        flush=True,
    )

    if output_dir.exists() and any(output_dir.iterdir()):
        print(f"FAILED runner={RUNNER_NAME} reason=OUTPUT_DIRECTORY_NOT_EMPTY writes=0", flush=True)
        raise ValueError("OUTPUT_DIRECTORY_NOT_EMPTY")

    terminal_state = "FAILED"
    try:
        protocol = _load_protocol(protocol_path)
        frozen_manifest_sha256 = _validate_manifest_file_binding(protocol, manifest_path)
        manifest = _load_json(manifest_path)
        _validate_manifest(
            protocol,
            manifest,
            outcomes_path=outcomes_path,
            forward_summary_path=forward_summary_path,
            scores_path=scores_path,
            score_summary_path=score_summary_path,
        )
        print("PHASE_START name=load_artifacts", flush=True)
        outcome_rows = _load_jsonl(outcomes_path)
        score_rows = _load_jsonl(scores_path)
        forward_summary = _load_json(forward_summary_path)
        score_summary = _load_json(score_summary_path)
        _validate_frozen_score_contract(score_rows)
        _validate_frozen_population(protocol, outcome_rows, score_rows, forward_summary, score_summary)
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
            "frozen_manifest_sha256": frozen_manifest_sha256,
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
                "verdict": verdict,
                "complete_observation_count": evaluation["complete_observation_count"],
                "horizon_counts": evaluation["horizon_counts"],
                "ppp_cohorts": sorted(evaluation["ppp_cohorts"].keys()),
                "candidate_ids": list(REQUIRED_CANDIDATES),
                "terminal_state": "FINISHED",
                "frozen_model_changed": 0,
                "production_ranking_changed": 0,
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
