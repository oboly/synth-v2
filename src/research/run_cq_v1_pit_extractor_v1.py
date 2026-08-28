from __future__ import annotations

import argparse
import json
import signal
import time
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.cq_v1_pit_extractor_v1 import ShadowObservation, extract_features

RUNNER_NAME = "cq_v1_pit_extractor_v1"
DEFAULT_BATCH_SIZE = 100
_STOP_REQUESTED = False


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(type(value).__name__)


def _signal_handler(signum: int, _frame: Any) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    print(f"SIGNAL received={signum} action=checkpoint_then_stop", flush=True)


def _load_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_checkpoint_scope(checkpoint: dict[str, Any], venue: str | None, batch_size: int) -> None:
    if checkpoint.get("runner") != RUNNER_NAME:
        raise SystemExit("checkpoint runner mismatch")
    if checkpoint.get("venue") != venue:
        raise SystemExit("checkpoint venue mismatch")
    if int(checkpoint.get("batch_size")) != batch_size:
        raise SystemExit("checkpoint batch_size mismatch")


def reconcile_jsonl(path: Path, checkpoint: dict[str, Any]) -> None:
    expected = int(checkpoint.get("processed", 0))
    expected_last = checkpoint.get("last_shadow_id")
    if expected == 0:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            path.write_text("", encoding="utf-8")
        return
    if not path.exists():
        raise ValueError("checkpoint/output mismatch: JSONL missing")
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    if len(raw_lines) < expected:
        raise ValueError("checkpoint/output mismatch: JSONL shorter than checkpoint")

    kept: list[tuple[str, dict[str, Any]]] = []
    prior_shadow_id: int | None = None
    mrp_count = 0
    sector_count = 0
    joint_count = 0
    for index in range(expected):
        try:
            row = json.loads(raw_lines[index])
        except json.JSONDecodeError as exc:
            raise ValueError(f"checkpointed JSONL line {index + 1} is malformed") from exc
        try:
            shadow_id = int(row["shadow_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"checkpointed JSONL line {index + 1} has invalid shadow_id") from exc
        if prior_shadow_id is not None and shadow_id <= prior_shadow_id:
            raise ValueError(
                f"checkpointed JSONL shadow_id sequence is not strictly increasing at line {index + 1}"
            )
        prior_shadow_id = shadow_id
        mrp_count += int(bool(row.get("mrp_available", False)))
        sector_count += int(bool(row.get("sector_available", False)))
        joint_count += int(bool(row.get("joint_available", False)))
        kept.append((raw_lines[index], row))

    if int(kept[-1][1]["shadow_id"]) != int(expected_last):
        raise ValueError("checkpoint/output mismatch: last_shadow_id differs")
    expected_counters = {
        "mrp_available_count": mrp_count,
        "sector_available_count": sector_count,
        "joint_available_count": joint_count,
    }
    for key, recomputed in expected_counters.items():
        if int(checkpoint.get(key, 0)) != recomputed:
            raise ValueError(f"checkpoint/output mismatch: {key} differs")
    if len(raw_lines) != expected:
        path.write_text("\n".join(line for line, _ in kept) + "\n", encoding="utf-8")
        print(f"RESUME_RECONCILE action=truncate_jsonl to_rows={expected}", flush=True)


def _write_json(path: Path, payload: dict[str, Any], event: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(f"WRITE event={event} path={path} flushed=1", flush=True)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=_json_default) + "\n")
        handle.flush()
    print(f"WRITE event=jsonl_append shadow_id={payload['shadow_id']} flushed=1", flush=True)


def _fetch_shadow_batch(conn: Any, after_shadow_id: int, batch_size: int, venue: str | None) -> list[ShadowObservation]:
    sql = """
        SELECT shadow_id, asset_id, venue, asof_ts_utc, evidence_key, cq_model_version
        FROM research_entry_quality_shadow
        WHERE shadow_id > %s
    """
    params: list[Any] = [after_shadow_id]
    if venue:
        sql += " AND venue=%s"
        params.append(venue)
    sql += " ORDER BY shadow_id ASC LIMIT %s"
    params.append(batch_size)
    started = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    print(f"QUERY name=shadow_batch rows={len(rows)} elapsed_sec={time.monotonic()-started:.3f}", flush=True)
    return [ShadowObservation(**row) for row in rows]


def _checkpoint_payload(*, last_shadow_id: int, processed: int, mrp_count: int, sector_count: int, joint_count: int, venue: str | None, batch_size: int, terminal_state: str) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "last_shadow_id": last_shadow_id or None,
        "processed": processed,
        "mrp_available_count": mrp_count,
        "sector_available_count": sector_count,
        "joint_available_count": joint_count,
        "venue": venue,
        "batch_size": batch_size,
        "terminal_state": terminal_state,
        "updated_ts_utc": datetime.now(UTC),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only CQ v1 point-in-time feature coverage extractor")
    parser.add_argument("--output-dir", default="data/research/cq_v1_pit_extractor_v1")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Cumulative maximum observations; 0 means source exhaustion")
    parser.add_argument("--venue", default=None)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 1000:
        raise SystemExit("--batch-size must be within 1..1000")
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    output_dir = Path(args.output_dir)
    rows_path = output_dir / "features.jsonl"
    checkpoint_path = output_dir / "checkpoint.json"
    summary_path = output_dir / "coverage_summary.json"

    checkpoint = _load_checkpoint(checkpoint_path) if args.resume else None
    after_shadow_id = int(checkpoint.get("last_shadow_id") or 0) if checkpoint else 0
    processed = int(checkpoint.get("processed", 0)) if checkpoint else 0
    mrp_count = int(checkpoint.get("mrp_available_count", 0)) if checkpoint else 0
    sector_count = int(checkpoint.get("sector_available_count", 0)) if checkpoint else 0
    joint_count = int(checkpoint.get("joint_available_count", 0)) if checkpoint else 0
    if checkpoint:
        validate_checkpoint_scope(checkpoint, args.venue, args.batch_size)
        reconcile_jsonl(rows_path, checkpoint)
    elif rows_path.exists() and rows_path.read_text(encoding="utf-8").strip():
        raise SystemExit("output exists; use --resume or a new --output-dir")

    print(
        f"STARTED runner={RUNNER_NAME} worker_count=1 venue={args.venue or 'ALL'} batch_size={args.batch_size} "
        f"limit={args.limit} resume={int(args.resume)} output_dir={output_dir}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 db_writes=0 production_ranking_changes=0 decision_gate=none "
        "execution_planner=none executor=none broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        flush=True,
    )

    conn = get_connection()
    invocation_count = 0
    terminal_state = "FINISHED"
    try:
        while not _STOP_REQUESTED:
            remaining = args.batch_size if args.limit == 0 else min(args.batch_size, args.limit - processed)
            if remaining <= 0:
                break
            batch = _fetch_shadow_batch(conn, after_shadow_id, remaining, args.venue)
            if not batch:
                break
            for observation in batch:
                started = time.monotonic()
                with conn.cursor() as cur:
                    extracted = extract_features(cur, observation)
                payload = asdict(extracted)
                payload.update(mrp_available=extracted.mrp_available, sector_available=extracted.sector_available, joint_available=extracted.joint_available)
                _append_jsonl(rows_path, payload)
                after_shadow_id = observation.shadow_id
                processed += 1
                invocation_count += 1
                mrp_count += int(extracted.mrp_available)
                sector_count += int(extracted.sector_available)
                joint_count += int(extracted.joint_available)
                print(f"PROGRESS shadow_id={after_shadow_id} processed={processed} elapsed_sec={time.monotonic()-started:.3f}", flush=True)
                _write_json(checkpoint_path, _checkpoint_payload(last_shadow_id=after_shadow_id, processed=processed, mrp_count=mrp_count, sector_count=sector_count, joint_count=joint_count, venue=args.venue, batch_size=args.batch_size, terminal_state="RUNNING"), "checkpoint")
                if _STOP_REQUESTED or (args.limit and processed >= args.limit):
                    break
        if _STOP_REQUESTED:
            terminal_state = "INTERRUPTED"
    except Exception:
        terminal_state = "FAILED"
        raise
    finally:
        conn.close()
        denominator = processed or 1
        summary = {
            "runner": RUNNER_NAME,
            "sample_count": processed,
            "observations_in_this_invocation": invocation_count,
            "mrp_available_count": mrp_count,
            "sector_available_count": sector_count,
            "joint_available_count": joint_count,
            "mrp_coverage": round(mrp_count / denominator, 6) if processed else 0.0,
            "sector_coverage": round(sector_count / denominator, 6) if processed else 0.0,
            "joint_coverage": round(joint_count / denominator, 6) if processed else 0.0,
            "last_shadow_id": after_shadow_id or None,
            "terminal_state": terminal_state,
            "weights_assigned": 0,
            "cq_v1_scores_emitted": 0,
        }
        _write_json(summary_path, summary, "summary")
        _write_json(checkpoint_path, _checkpoint_payload(last_shadow_id=after_shadow_id, processed=processed, mrp_count=mrp_count, sector_count=sector_count, joint_count=joint_count, venue=args.venue, batch_size=args.batch_size, terminal_state=terminal_state), "checkpoint")
        print(f"{terminal_state} processed={processed} last_shadow_id={after_shadow_id or 'none'}", flush=True)
    return 0 if terminal_state == "FINISHED" else 130 if terminal_state == "INTERRUPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
