from __future__ import annotations

"""Integrity-gated C1-only final-holdout dataset builder for Issue #593.

This is deliberately separate from the discovery/validation builder. It can open
only the frozen final-holdout split, only for preregistered candidate C1, and only
after the frozen canonical source-content fingerprint verifies successfully.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.research.multi_horizon_rotation_dataset_builder_v1 import observed_asset_ids_at_asof
from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS, evaluate_candidate
from src.research.run_multi_horizon_rotation_dataset_builder_v1 import (
    asof_grid,
    build_validation_row,
    chunk_asof_grid_by_utc_day,
    fetch_asset_coverage,
    fetch_candles_for_chunk,
    fetch_rotation_v1_points,
    manifest_fingerprint,
    parse_ts,
    replay_candles_at_asof,
    write_row,
)
from src.research.run_multi_horizon_rotation_source_integrity_v1 import (
    build_integrity_payload,
    verify_existing,
)

RUNNER_NAME = "run_multi_horizon_rotation_c1_final_holdout_builder_v1"
RUNNER_VERSION = "1.0.0"
CANDIDATE_ID = "C1"
PHASE = "final_holdout"


def emit(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="#593 integrity-gated C1-only final holdout builder")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--source-integrity", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def load_manifest(path: Path, *, venue: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("split manifest must be a JSON object")
    if raw.get("venue") != venue:
        raise ValueError("venue does not match frozen split manifest")
    if raw.get("final_holdout_inspected") is not False:
        raise ValueError("final holdout must still be unopened before this one-shot builder starts")
    splits = raw.get("splits")
    if not isinstance(splits, dict) or PHASE not in splits:
        raise ValueError("split manifest missing final_holdout")
    return raw


def select_c1_spec() -> Any:
    matches = [spec for spec in CANDIDATE_SPECS if spec.candidate_id == CANDIDATE_ID]
    if len(matches) != 1:
        raise ValueError("frozen C1 candidate spec missing or ambiguous")
    return matches[0]


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    started = time.perf_counter()
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} phase={PHASE} candidate={CANDIDATE_ID} "
        "workers=1 final_holdout_access=GATED"
    )
    emit(
        "SAFETY research_only=1 market_only=1 database_reads=1 database_writes=0 account_awareness=0 "
        "decision_gate=none execution_planner=none executor=none broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0"
    )

    conn = None
    partial_path: Path | None = None
    try:
        manifest_path = Path(args.split_manifest)
        integrity_path = Path(args.source_integrity)
        output_dir = Path(args.output_dir)
        artifact_path = output_dir / "final_holdout_c1_rows_v1.jsonl"
        partial_path = output_dir / ".final_holdout_c1_rows_v1.jsonl.partial"
        summary_path = output_dir / "final_holdout_c1_summary_v1.json"

        manifest = load_manifest(manifest_path, venue=args.venue)
        manifest_sha = manifest_fingerprint(manifest)
        split = manifest["splits"][PHASE]
        phase_start = parse_ts(split["start"])
        phase_end = parse_ts(split["end"])

        if artifact_path.exists() or summary_path.exists() or partial_path.exists():
            raise ValueError("final holdout output already exists; runner is one-shot and refuses overwrite")

        conn = get_db_connection()

        # Hard gate: recompute and verify frozen source content before any holdout
        # candidate replay or forward-label construction is allowed.
        emit("PHASE_STARTED name=verify_frozen_source_integrity")
        gate_started = time.perf_counter()
        current_integrity = build_integrity_payload(
            conn,
            venue=args.venue,
            split_manifest=manifest,
        )
        verify_existing(integrity_path, current_integrity)
        emit(
            "PHASE_FINISHED name=verify_frozen_source_integrity state=VERIFIED "
            f"composite_sha256={current_integrity['composite_sha256']} "
            f"elapsed_s={time.perf_counter() - gate_started:.3f}"
        )

        source_span = manifest["source_span"]
        coverage = fetch_asset_coverage(conn, venue=args.venue, through_ts=parse_ts(source_span["end"]))
        pit_index = fetch_rotation_v1_points(conn, venue=args.venue, through_ts=phase_end)
        c1_spec = select_c1_spec()
        spec_by_id = {CANDIDATE_ID: c1_spec}
        full_grid = asof_grid(phase_start, phase_end)

        output_dir.mkdir(parents=True, exist_ok=True)
        partial_path.touch(exist_ok=False)
        row_count = 0
        asofs_completed = 0
        source_query_count = 0
        source_rows_read = 0

        emit("PHASE_STARTED name=build_final_holdout_c1_artifact")
        build_started = time.perf_counter()
        with partial_path.open("ab") as handle:
            for chunk in chunk_asof_grid_by_utc_day(full_grid):
                chunk_candles, close_maps, fetched = fetch_candles_for_chunk(
                    conn,
                    venue=args.venue,
                    chunk_asofs=chunk,
                    phase_end=phase_end,
                )
                source_query_count += 1
                source_rows_read += fetched
                for asof in chunk:
                    observed_ids = observed_asset_ids_at_asof(coverage, asof_ts=asof)
                    replay_candles = replay_candles_at_asof(
                        chunk_candles=chunk_candles,
                        observed_asset_ids=observed_ids,
                        asof_ts=asof,
                    )
                    results = evaluate_candidate(
                        candles_by_asset=replay_candles,
                        asof_ts=asof,
                        spec=c1_spec,
                        venue=args.venue,
                    )
                    for result in results:
                        if result.candidate_id != CANDIDATE_ID:
                            raise ValueError("non-C1 result escaped C1-only holdout gate")
                        row = build_validation_row(
                            result=result,
                            close_by_ts=close_maps.get(result.asset_id, {}),
                            spec_by_id=spec_by_id,
                            pit_index=pit_index,
                            phase_end=phase_end,
                        )
                        write_row(handle, row)
                        row_count += 1
                    handle.flush()
                    os.fsync(handle.fileno())
                    asofs_completed += 1
                    if asofs_completed % 96 == 0:
                        emit(
                            f"HEARTBEAT phase={PHASE} candidate={CANDIDATE_ID} asofs_completed={asofs_completed} "
                            f"rows_built={row_count} observed_assets={len(observed_ids)} "
                            f"source_queries={source_query_count} source_rows_read={source_rows_read}"
                        )

        if asofs_completed != len(full_grid):
            raise ValueError(f"as-of completion mismatch: {asofs_completed} != {len(full_grid)}")

        partial_path.replace(artifact_path)
        summary = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": PHASE,
            "candidate_id": CANDIDATE_ID,
            "venue": args.venue,
            "manifest_sha256": manifest_sha,
            "source_integrity_composite_sha256": current_integrity["composite_sha256"],
            "phase_start": phase_start.isoformat().replace("+00:00", "Z"),
            "phase_end_exclusive": phase_end.isoformat().replace("+00:00", "Z"),
            "asof_count": asofs_completed,
            "row_count": row_count,
            "source_query_count": source_query_count,
            "source_rows_read": source_rows_read,
            "final_holdout_access": "OPENED_FOR_PREREGISTERED_C1_ONLY",
            "c2_access": "DENY",
            "c3_access": "DENY",
            "database_writes": 0,
            "live_orders": 0,
        }
        write_json_atomic(summary_path, summary)
        emit(
            f"PHASE_FINISHED name=build_final_holdout_c1_artifact rows={row_count} asofs={asofs_completed} "
            f"elapsed_s={time.perf_counter() - build_started:.3f}"
        )
        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS phase={PHASE} candidate={CANDIDATE_ID} "
            f"rows={row_count} c2_access=DENY c3_access=DENY database_writes=0 live_orders=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except Exception as exc:
        emit(f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc}")
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
