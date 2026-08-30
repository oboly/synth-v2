from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.common.db import get_db_connection
from src.research.cq_v1_model_candidate_v1 import (
    CANDIDATES,
    COVERAGE_ARTIFACT_SHA256,
    MODEL_FAMILY_VERSION,
    CandidateScore,
    score_all_candidates,
)

RUNNER_NAME = "cq_v1_score_materialization_v1"
OUTPUT_ROWS = "cq_v1_scores.jsonl"
OUTPUT_SUMMARY = "summary.json"
DEFAULT_BATCH_SIZE = 100

IDENTITY_FIELDS = (
    "shadow_id",
    "asset_id",
    "venue",
    "asof_ts_utc",
    "evidence_key",
    "cq_model_version",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize frozen CQ v1 scores from Phase 2C PIT features")
    parser.add_argument("--features-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso_z(value: Any) -> str:
    return _parse_ts(value).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _iso_z(value)
    raise TypeError(type(value).__name__)


def load_feature_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prior_shadow_id: int | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"features JSONL line {line_number} is malformed") from exc
            if not isinstance(row, dict):
                raise ValueError(f"features JSONL line {line_number} must be an object")
            missing = [field for field in IDENTITY_FIELDS if field not in row]
            if missing:
                raise ValueError(f"features JSONL line {line_number} missing identity fields: {','.join(missing)}")
            shadow_id = int(row["shadow_id"])
            if prior_shadow_id is not None and shadow_id <= prior_shadow_id:
                raise ValueError("features shadow_id sequence must be strictly increasing")
            prior_shadow_id = shadow_id
            rows.append(row)
    if not rows:
        raise ValueError("features JSONL is empty")
    return rows


def _chunks(rows: list[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), batch_size):
        yield rows[start : start + batch_size]


def fetch_shadow_rows(conn: Any, shadow_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not shadow_ids:
        return {}
    placeholders = ",".join(["%s"] * len(shadow_ids))
    sql = f"""
        SELECT shadow_id, asset_id, venue, asof_ts_utc, evidence_key,
               cq_model_version, entry_quality_score
        FROM research_entry_quality_shadow
        WHERE shadow_id IN ({placeholders})
    """
    started = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(sql, tuple(shadow_ids))
        rows = cur.fetchall()
    print(f"QUERY name=shadow_identity_batch requested={len(shadow_ids)} rows={len(rows)} elapsed_sec={time.monotonic()-started:.3f}", flush=True)
    if any(not isinstance(row, dict) for row in rows):
        raise TypeError("expected dict cursor rows")
    return {int(row["shadow_id"]): dict(row) for row in rows}


def validate_identity(feature: Mapping[str, Any], shadow: Mapping[str, Any] | None) -> None:
    shadow_id = int(feature["shadow_id"])
    if shadow is None:
        raise ValueError(f"shadow_id={shadow_id}:SHADOW_ROW_MISSING")
    expected = {
        "asset_id": int(feature["asset_id"]),
        "venue": str(feature["venue"]),
        "asof_ts_utc": _iso_z(feature["asof_ts_utc"]),
        "evidence_key": str(feature["evidence_key"]),
        "cq_model_version": str(feature["cq_model_version"]),
    }
    observed = {
        "asset_id": int(shadow["asset_id"]),
        "venue": str(shadow["venue"]),
        "asof_ts_utc": _iso_z(shadow["asof_ts_utc"]),
        "evidence_key": str(shadow["evidence_key"]),
        "cq_model_version": str(shadow["cq_model_version"]),
    }
    mismatched = [field for field in expected if expected[field] != observed[field]]
    if mismatched:
        raise ValueError(f"shadow_id={shadow_id}:IDENTITY_MISMATCH:{','.join(mismatched)}")


def _score_payload(score: CandidateScore) -> dict[str, Any]:
    return {
        "version": score.version,
        "state": score.state,
        "score": score.score,
        "reason": score.reason,
    }


def materialize_row(feature: Mapping[str, Any], shadow: Mapping[str, Any]) -> dict[str, Any]:
    validate_identity(feature, shadow)
    cq_v0 = shadow.get("entry_quality_score")
    scores = score_all_candidates(cq_v0=cq_v0, features=feature)
    return {
        "shadow_id": int(feature["shadow_id"]),
        "asset_id": int(feature["asset_id"]),
        "venue": str(feature["venue"]),
        "asof_ts_utc": _iso_z(feature["asof_ts_utc"]),
        "evidence_key": str(feature["evidence_key"]),
        "cq_model_version": str(feature["cq_model_version"]),
        "cq_v0": cq_v0,
        "model_family_version": MODEL_FAMILY_VERSION,
        "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
        "candidates": {score.candidate_id: _score_payload(score) for score in scores},
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    state_counts: dict[str, dict[str, int]] = {
        spec.candidate_id: {} for spec in CANDIDATES
    }
    for row in rows:
        for candidate_id, payload in row["candidates"].items():
            state = str(payload["state"])
            counts = state_counts[candidate_id]
            counts[state] = counts.get(state, 0) + 1
    sample_count = len(rows)
    available = {
        candidate_id: {
            "count": counts.get("AVAILABLE", 0),
            "rate": round(counts.get("AVAILABLE", 0) / sample_count, 6),
        }
        for candidate_id, counts in state_counts.items()
    }
    return {
        "runner": RUNNER_NAME,
        "sample_count": sample_count,
        "last_shadow_id": rows[-1]["shadow_id"] if rows else None,
        "model_family_version": MODEL_FAMILY_VERSION,
        "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
        "candidate_state_counts": state_counts,
        "candidate_available": available,
        "terminal_state": "FINISHED",
        "forward_outcomes_read": 0,
        "production_ranking_changed": 0,
    }


def run(args: argparse.Namespace) -> int:
    if args.batch_size < 1 or args.batch_size > 1000:
        raise SystemExit("--batch-size must be within 1..1000")
    features_path = Path(args.features_jsonl)
    output_dir = Path(args.output_dir)
    rows_path = output_dir / OUTPUT_ROWS
    summary_path = output_dir / OUTPUT_SUMMARY
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit("output directory is not empty; use a new immutable output directory")

    features = load_feature_rows(features_path)
    print(
        f"STARTED runner={RUNNER_NAME} features={features_path} observations={len(features)} batch_size={args.batch_size}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 db_writes=0 forward_outcomes_read=0 "
        "production_ranking_changes=0 broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        flush=True,
    )

    conn = get_db_connection()
    materialized: list[dict[str, Any]] = []
    try:
        for batch in _chunks(features, args.batch_size):
            shadow_ids = [int(row["shadow_id"]) for row in batch]
            shadow_by_id = fetch_shadow_rows(conn, shadow_ids)
            for feature in batch:
                shadow_id = int(feature["shadow_id"])
                materialized.append(materialize_row(feature, shadow_by_id.get(shadow_id)))
    finally:
        conn.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in materialized:
            handle.write(json.dumps(row, sort_keys=True, default=_json_default) + "\n")
    summary = summarize(materialized)
    summary_path.write_text(json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8")
    print(f"WRITE event=scores path={rows_path} rows={len(materialized)}", flush=True)
    print(f"WRITE event=summary path={summary_path}", flush=True)
    print(
        f"FINISHED runner={RUNNER_NAME} rows={len(materialized)} last_shadow_id={summary['last_shadow_id']} "
        f"forward_outcomes_read=0 production_ranking_changed=0",
        flush=True,
    )
    return 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
