from __future__ import annotations

import argparse
import hashlib
import json
import signal
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
OUTPUT_CHECKPOINT = "checkpoint.json"
DEFAULT_BATCH_SIZE = 100
_STOP_REQUESTED = False

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
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def _signal_handler(signum: int, _frame: Any) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    print(f"SIGNAL received={signum} action=checkpoint_then_stop", flush=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=_json_default))


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("cq_v0 must be finite when present")
    return result


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
            if "cq_v0" not in row:
                raise ValueError(f"features JSONL line {line_number} missing frozen cq_v0")
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
    frozen_cq = _decimal_or_none(feature.get("cq_v0"))
    current_cq = _decimal_or_none(shadow.get("entry_quality_score"))
    if frozen_cq != current_cq:
        raise ValueError(f"shadow_id={shadow_id}:CQ_V0_MISMATCH")


def _score_payload(score: CandidateScore) -> dict[str, Any]:
    return {
        "version": score.version,
        "state": score.state,
        "score": score.score,
        "reason": score.reason,
    }


def expected_row_from_feature(feature: Mapping[str, Any]) -> dict[str, Any]:
    cq_v0 = _decimal_or_none(feature.get("cq_v0"))
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


def materialize_row(feature: Mapping[str, Any], shadow: Mapping[str, Any] | None) -> dict[str, Any]:
    validate_identity(feature, shadow)
    return expected_row_from_feature(feature)


def summarize(rows: list[dict[str, Any]], terminal_state: str, features_sha256: str) -> dict[str, Any]:
    state_counts: dict[str, dict[str, int]] = {spec.candidate_id: {} for spec in CANDIDATES}
    for row in rows:
        for candidate_id, payload in row["candidates"].items():
            state = str(payload["state"])
            counts = state_counts[candidate_id]
            counts[state] = counts.get(state, 0) + 1
    sample_count = len(rows)
    available = {
        candidate_id: {
            "count": counts.get("AVAILABLE", 0),
            "rate": round(counts.get("AVAILABLE", 0) / sample_count, 6) if sample_count else 0.0,
        }
        for candidate_id, counts in state_counts.items()
    }
    return {
        "runner": RUNNER_NAME,
        "sample_count": sample_count,
        "last_shadow_id": rows[-1]["shadow_id"] if rows else None,
        "features_sha256": features_sha256,
        "model_family_version": MODEL_FAMILY_VERSION,
        "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
        "candidate_state_counts": state_counts,
        "candidate_available": available,
        "terminal_state": terminal_state,
        "forward_outcomes_read": 0,
        "production_ranking_changed": 0,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=_json_default) + "\n")
        handle.flush()


def _parse_checkpointed_prefix(rows_path: Path, processed: int) -> list[dict[str, Any]]:
    if processed == 0:
        if rows_path.exists() and rows_path.read_bytes():
            rows_path.write_bytes(b"")
        return []
    if not rows_path.exists():
        raise ValueError("checkpoint/output mismatch: score JSONL missing")
    raw_lines = rows_path.read_bytes().splitlines(keepends=True)
    if len(raw_lines) < processed:
        raise ValueError("checkpoint/output mismatch: score JSONL shorter than checkpoint")
    rows: list[dict[str, Any]] = []
    for index in range(processed):
        raw = raw_lines[index].decode("utf-8").strip()
        try:
            row = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"checkpointed score JSONL line {index + 1} is malformed") from exc
        if not isinstance(row, dict):
            raise ValueError(f"checkpointed score JSONL line {index + 1} must be an object")
        rows.append(row)
    if len(raw_lines) != processed:
        rows_path.write_bytes(b"".join(raw_lines[:processed]))
        print(f"RESUME_RECONCILE action=truncate_jsonl to_rows={processed}", flush=True)
    return rows


def _checkpoint_payload(
    features_path: Path,
    features_sha256: str,
    batch_size: int,
    rows: list[dict[str, Any]],
    terminal_state: str,
) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "features_jsonl": str(features_path),
        "features_sha256": features_sha256,
        "batch_size": batch_size,
        "processed": len(rows),
        "last_shadow_id": rows[-1]["shadow_id"] if rows else None,
        "terminal_state": terminal_state,
        "model_family_version": MODEL_FAMILY_VERSION,
        "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
        "updated_ts_utc": datetime.now(UTC).isoformat(),
    }


def _load_resume(
    output_dir: Path,
    features_path: Path,
    features: list[dict[str, Any]],
    features_sha256: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    checkpoint_path = output_dir / OUTPUT_CHECKPOINT
    rows_path = output_dir / OUTPUT_ROWS
    if not checkpoint_path.exists():
        raise SystemExit("--resume requires checkpoint.json")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("runner") != RUNNER_NAME:
        raise SystemExit("checkpoint runner mismatch")
    if checkpoint.get("features_jsonl") != str(features_path):
        raise SystemExit("checkpoint features_jsonl mismatch")
    if checkpoint.get("features_sha256") != features_sha256:
        raise SystemExit("checkpoint features SHA-256 mismatch")
    if int(checkpoint.get("batch_size")) != batch_size:
        raise SystemExit("checkpoint batch_size mismatch")
    if checkpoint.get("model_family_version") != MODEL_FAMILY_VERSION:
        raise SystemExit("checkpoint model family mismatch")
    if checkpoint.get("coverage_artifact_sha256") != COVERAGE_ARTIFACT_SHA256:
        raise SystemExit("checkpoint coverage artifact mismatch")
    processed = int(checkpoint.get("processed", 0))
    if processed > len(features):
        raise ValueError("checkpoint processed exceeds feature population")
    rows = _parse_checkpointed_prefix(rows_path, processed)
    expected_last = checkpoint.get("last_shadow_id")
    actual_last = rows[-1]["shadow_id"] if rows else None
    if expected_last != actual_last:
        raise ValueError("checkpoint/output mismatch: last_shadow_id differs")
    for index, row in enumerate(rows):
        expected = _jsonable(expected_row_from_feature(features[index]))
        if row != expected:
            raise ValueError(f"checkpoint/output mismatch: row {index + 1} differs from frozen feature input")
    return rows


def run(args: argparse.Namespace) -> int:
    global _STOP_REQUESTED
    _STOP_REQUESTED = False
    if args.batch_size < 1 or args.batch_size > 1000:
        raise SystemExit("--batch-size must be within 1..1000")
    features_path = Path(args.features_jsonl)
    output_dir = Path(args.output_dir)
    rows_path = output_dir / OUTPUT_ROWS
    summary_path = output_dir / OUTPUT_SUMMARY
    checkpoint_path = output_dir / OUTPUT_CHECKPOINT

    features_sha256 = _sha256_file(features_path)
    features = load_feature_rows(features_path)
    if args.resume:
        materialized = _load_resume(output_dir, features_path, features, features_sha256, args.batch_size)
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise SystemExit("output directory is not empty; use --resume or a new immutable output directory")
        materialized = []

    processed = len(materialized)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    print(
        f"STARTED runner={RUNNER_NAME} features={features_path} features_sha256={features_sha256} "
        f"observations={len(features)} processed={processed} batch_size={args.batch_size} resume={int(args.resume)}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 db_writes=0 forward_outcomes_read=0 "
        "production_ranking_changes=0 broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        flush=True,
    )

    conn = get_db_connection()
    terminal_state = "FINISHED"
    try:
        remaining_features = features[processed:]
        for batch in _chunks(remaining_features, args.batch_size):
            shadow_ids = [int(row["shadow_id"]) for row in batch]
            shadow_by_id = fetch_shadow_rows(conn, shadow_ids)
            for feature in batch:
                row = materialize_row(feature, shadow_by_id.get(int(feature["shadow_id"])))
                _append_row(rows_path, row)
                materialized.append(row)
                _write_json(
                    checkpoint_path,
                    _checkpoint_payload(features_path, features_sha256, args.batch_size, materialized, "RUNNING"),
                )
                print(f"PROGRESS shadow_id={row['shadow_id']} processed={len(materialized)}", flush=True)
                if _STOP_REQUESTED:
                    terminal_state = "INTERRUPTED"
                    break
            if _STOP_REQUESTED:
                break
    except Exception:
        terminal_state = "FAILED"
        raise
    finally:
        conn.close()
        summary = summarize(materialized, terminal_state, features_sha256)
        _write_json(summary_path, summary)
        _write_json(
            checkpoint_path,
            _checkpoint_payload(features_path, features_sha256, args.batch_size, materialized, terminal_state),
        )
        print(f"WRITE event=summary path={summary_path} terminal_state={terminal_state}", flush=True)
        print(
            f"{terminal_state} runner={RUNNER_NAME} rows={len(materialized)} "
            f"last_shadow_id={summary['last_shadow_id'] or 'none'} forward_outcomes_read=0 production_ranking_changed=0",
            flush=True,
        )
    return 130 if terminal_state == "INTERRUPTED" else 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
