from __future__ import annotations

"""Integrity-gated C1-only final-holdout dataset builder for Issue #593.

This is deliberately separate from the discovery/validation builder. It can open
only the frozen final-holdout split, only for preregistered candidate C1, and only
after the frozen canonical source-content fingerprint verifies successfully.

The holdout has exactly one canonical output location: the directory that
already contains the frozen ``split_manifest_v1.json`` supplied on the command
line. There is deliberately no ``--output-dir`` override, so the holdout cannot
be reopened in a second location by pointing the runner somewhere else. A
checkpoint written into that same canonical directory acts as the one-shot
"opened" marker: once it exists in ``RUNNING``/``INTERRUPTED`` state, only an
explicit ``--resume`` of that exact run is permitted, and once it reaches
``FINISHED`` no further build is permitted at all.
"""

import argparse
import json
import os
import signal
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
    finalize_artifact_bundle,
    json_default,
    manifest_fingerprint,
    parse_ts,
    reconcile_partial_to_checkpoint,
    replay_candles_at_asof,
    write_json_atomic,
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
MANIFEST_BASENAME = "split_manifest_v1.json"
INTEGRITY_BASENAME = "source_integrity_v1.json"
RESUMABLE_TERMINAL_STATES = ("RUNNING", "INTERRUPTED")


class RunnerInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def emit(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="#593 integrity-gated C1-only final holdout builder")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--source-integrity", required=True)
    parser.add_argument("--resume", action="store_true")
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


def canonical_run_dir(manifest_path: Path, integrity_path: Path) -> Path:
    """Derive the single canonical run directory and fail closed on any bypass attempt.

    There is no ``--output-dir`` argument. The canonical directory is always
    the directory that holds the frozen ``split_manifest_v1.json`` the caller
    supplied, and the frozen ``source_integrity_v1.json`` must live in that
    exact same directory. This removes the ability to reopen the holdout by
    pointing an alternate output location at an otherwise-unopened manifest.
    """
    if manifest_path.name != MANIFEST_BASENAME:
        raise ValueError(f"--split-manifest must be named {MANIFEST_BASENAME}")
    if integrity_path.name != INTEGRITY_BASENAME:
        raise ValueError(f"--source-integrity must be named {INTEGRITY_BASENAME}")
    manifest_dir = manifest_path.resolve().parent
    integrity_dir = integrity_path.resolve().parent
    if integrity_dir != manifest_dir:
        raise ValueError(
            "source integrity artifact must live in the same canonical run directory "
            "as the frozen split manifest"
        )
    return manifest_dir


def checkpoint_path(canonical_dir: Path) -> Path:
    return canonical_dir / ".final_holdout_c1_checkpoint_v1.json"


def write_checkpoint(
    path: Path,
    *,
    venue: str,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
    phase_start: datetime,
    phase_end: datetime,
    last_completed_asof: datetime | None,
    asofs_completed: int,
    row_count: int,
    partial_bytes: int,
    source_query_count: int,
    source_rows_read: int,
    terminal_state: str,
) -> None:
    payload = {
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "venue": venue,
        "candidate_id": CANDIDATE_ID,
        "manifest_sha256": manifest_sha256,
        "source_integrity_composite_sha256": source_integrity_composite_sha256,
        "phase": PHASE,
        "phase_start": json_default(phase_start),
        "phase_end": json_default(phase_end),
        "last_completed_asof": None if last_completed_asof is None else json_default(last_completed_asof),
        "asofs_completed": asofs_completed,
        "row_count": row_count,
        "partial_bytes": partial_bytes,
        "source_query_count": source_query_count,
        "source_rows_read": source_rows_read,
        "terminal_state": terminal_state,
        "updated_ts_utc": json_default(datetime.now(UTC)),
    }
    write_json_atomic(path, payload)


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("resume requested but checkpoint is missing")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("checkpoint must be a JSON object")
    return raw


def validate_resume_checkpoint(
    checkpoint: dict[str, Any],
    *,
    venue: str,
    manifest_sha256: str,
    source_integrity_composite_sha256: str,
) -> None:
    if checkpoint.get("runner") != RUNNER_NAME or checkpoint.get("runner_version") != RUNNER_VERSION:
        raise ValueError("checkpoint runner/version mismatch")
    if checkpoint.get("venue") != venue:
        raise ValueError("checkpoint venue mismatch")
    if checkpoint.get("candidate_id") != CANDIDATE_ID:
        raise ValueError("checkpoint candidate_id mismatch")
    if checkpoint.get("phase") != PHASE:
        raise ValueError("checkpoint phase mismatch")
    if checkpoint.get("manifest_sha256") != manifest_sha256:
        raise ValueError("checkpoint split manifest mismatch")
    if checkpoint.get("source_integrity_composite_sha256") != source_integrity_composite_sha256:
        raise ValueError("checkpoint source integrity mismatch")
    terminal_state = checkpoint.get("terminal_state")
    if terminal_state not in RESUMABLE_TERMINAL_STATES:
        raise ValueError(
            f"checkpoint terminal_state={terminal_state!r} is not resumable; "
            "only RUNNING or INTERRUPTED checkpoints may be resumed"
        )
    for key in ("asofs_completed", "row_count", "partial_bytes"):
        if int(checkpoint.get(key, -1)) < 0:
            raise ValueError(f"checkpoint {key} must be non-negative")


def mark_checkpoint_terminal(path: Path, *, terminal_state: str) -> None:
    checkpoint = load_checkpoint(path)
    last_raw = checkpoint.get("last_completed_asof")
    write_checkpoint(
        path,
        venue=str(checkpoint["venue"]),
        manifest_sha256=str(checkpoint["manifest_sha256"]),
        source_integrity_composite_sha256=str(checkpoint["source_integrity_composite_sha256"]),
        phase_start=parse_ts(checkpoint["phase_start"]),
        phase_end=parse_ts(checkpoint["phase_end"]),
        last_completed_asof=None if last_raw is None else parse_ts(last_raw),
        asofs_completed=int(checkpoint["asofs_completed"]),
        row_count=int(checkpoint["row_count"]),
        partial_bytes=int(checkpoint["partial_bytes"]),
        source_query_count=int(checkpoint.get("source_query_count", 0)),
        source_rows_read=int(checkpoint.get("source_rows_read", 0)),
        terminal_state=terminal_state,
    )


def install_interrupt_handlers() -> dict[int, Any]:
    def handle_interrupt(signum: int, _frame: Any) -> None:
        raise RunnerInterrupted(signum)

    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    for signum in previous:
        signal.signal(signum, handle_interrupt)
    return previous


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    started = time.perf_counter()
    previous_handlers = install_interrupt_handlers()
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} phase={PHASE} candidate={CANDIDATE_ID} "
        f"workers=1 resume={int(bool(args.resume))} final_holdout_access=GATED"
    )
    emit(
        "SAFETY research_only=1 market_only=1 database_reads=1 database_writes=0 account_awareness=0 "
        "decision_gate=none execution_planner=none executor=none broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0"
    )

    conn = None
    partial_path: Path | None = None
    cp_path: Path | None = None
    last_completed_asof: datetime | None = None
    asofs_completed = 0
    row_count = 0
    source_query_count = 0
    source_rows_read = 0
    try:
        manifest_path = Path(args.split_manifest)
        integrity_path = Path(args.source_integrity)
        canonical_dir = canonical_run_dir(manifest_path, integrity_path)
        artifact_path = canonical_dir / "final_holdout_c1_rows_v1.jsonl"
        partial_path = canonical_dir / ".final_holdout_c1_rows_v1.jsonl.partial"
        summary_path = canonical_dir / "final_holdout_c1_summary_v1.json"
        cp_path = checkpoint_path(canonical_dir)

        manifest = load_manifest(manifest_path, venue=args.venue)
        manifest_sha = manifest_fingerprint(manifest)
        split = manifest["splits"][PHASE]
        phase_start = parse_ts(split["start"])
        phase_end = parse_ts(split["end"])

        checkpoint: dict[str, Any] | None = None
        if args.resume:
            if not cp_path.exists() or not partial_path.exists():
                raise ValueError(
                    "resume requested but the canonical checkpoint and/or partial artifact is missing"
                )
            checkpoint = load_checkpoint(cp_path)
            if checkpoint.get("terminal_state") not in RESUMABLE_TERMINAL_STATES:
                raise ValueError(
                    f"checkpoint terminal_state={checkpoint.get('terminal_state')!r} is not resumable; "
                    "only RUNNING or INTERRUPTED checkpoints may be resumed"
                )
        else:
            if artifact_path.exists() or summary_path.exists() or cp_path.exists() or partial_path.exists():
                raise ValueError(
                    "final holdout output already exists in the canonical run directory; "
                    "runner is one-shot and refuses to reopen or overwrite it. Use --resume "
                    "to continue an interrupted RUNNING checkpoint."
                )

        conn = get_db_connection()

        # Hard gate: recompute and verify frozen source content before any holdout
        # candidate replay or forward-label construction is allowed. This must
        # happen on both a fresh run and a resumed run.
        emit("PHASE_STARTED name=verify_frozen_source_integrity")
        gate_started = time.perf_counter()
        current_integrity = build_integrity_payload(
            conn,
            venue=args.venue,
            split_manifest=manifest,
        )
        verify_existing(integrity_path, current_integrity)
        composite_sha = current_integrity["composite_sha256"]
        emit(
            "PHASE_FINISHED name=verify_frozen_source_integrity state=VERIFIED "
            f"composite_sha256={composite_sha} "
            f"elapsed_s={time.perf_counter() - gate_started:.3f}"
        )

        source_span = manifest["source_span"]
        coverage = fetch_asset_coverage(conn, venue=args.venue, through_ts=parse_ts(source_span["end"]))
        pit_index = fetch_rotation_v1_points(conn, venue=args.venue, through_ts=phase_end)
        c1_spec = select_c1_spec()
        spec_by_id = {CANDIDATE_ID: c1_spec}
        full_grid = asof_grid(phase_start, phase_end)

        if args.resume:
            assert checkpoint is not None
            validate_resume_checkpoint(
                checkpoint,
                venue=args.venue,
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
            )
            reconcile_partial_to_checkpoint(partial_path, checkpoint)
            last_raw = checkpoint.get("last_completed_asof")
            last_completed_asof = None if last_raw is None else parse_ts(last_raw)
            asofs_completed = int(checkpoint["asofs_completed"])
            row_count = int(checkpoint["row_count"])
            source_query_count = int(checkpoint.get("source_query_count", 0))
            source_rows_read = int(checkpoint.get("source_rows_read", 0))
            if last_completed_asof is not None:
                if last_completed_asof not in full_grid:
                    raise ValueError("checkpoint last_completed_asof is outside frozen final-holdout grid")
                expected_completed = full_grid.index(last_completed_asof) + 1
                if asofs_completed != expected_completed:
                    raise ValueError(
                        f"checkpoint asofs_completed mismatch: actual={asofs_completed} "
                        f"expected={expected_completed}"
                    )
            elif asofs_completed != 0:
                raise ValueError("checkpoint has completed as-of count without last_completed_asof")
            emit(
                f"RESUME checkpoint={cp_path} last_completed_asof={last_completed_asof} "
                f"asofs_completed={asofs_completed} rows={row_count} partial_bytes={checkpoint['partial_bytes']}"
            )
        else:
            partial_path.touch(exist_ok=False)
            # Freeze the one-shot holdout-open checkpoint immediately after integrity
            # verification succeeds and immediately before the first holdout replay.
            # Its existence is what makes any later non-resume invocation fail closed.
            write_checkpoint(
                cp_path,
                venue=args.venue,
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
                phase_start=phase_start,
                phase_end=phase_end,
                last_completed_asof=None,
                asofs_completed=0,
                row_count=0,
                partial_bytes=0,
                source_query_count=0,
                source_rows_read=0,
                terminal_state="RUNNING",
            )
            emit(f"OPENED checkpoint={cp_path} state=RUNNING composite_sha256={composite_sha}")

        remaining_grid = [
            asof for asof in full_grid
            if last_completed_asof is None or asof > last_completed_asof
        ]

        emit("PHASE_STARTED name=build_final_holdout_c1_artifact")
        build_started = time.perf_counter()
        with partial_path.open("ab") as handle:
            for chunk in chunk_asof_grid_by_utc_day(remaining_grid):
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
                    last_completed_asof = asof
                    partial_bytes = handle.tell()
                    write_checkpoint(
                        cp_path,
                        venue=args.venue,
                        manifest_sha256=manifest_sha,
                        source_integrity_composite_sha256=composite_sha,
                        phase_start=phase_start,
                        phase_end=phase_end,
                        last_completed_asof=last_completed_asof,
                        asofs_completed=asofs_completed,
                        row_count=row_count,
                        partial_bytes=partial_bytes,
                        source_query_count=source_query_count,
                        source_rows_read=source_rows_read,
                        terminal_state="RUNNING",
                    )
                    if asofs_completed % 96 == 0:
                        emit(
                            f"HEARTBEAT phase={PHASE} candidate={CANDIDATE_ID} asofs_completed={asofs_completed} "
                            f"rows_built={row_count} observed_assets={len(observed_ids)} "
                            f"source_queries={source_query_count} source_rows_read={source_rows_read}"
                        )

        if asofs_completed != len(full_grid):
            raise ValueError(f"as-of completion mismatch: {asofs_completed} != {len(full_grid)}")

        summary = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": PHASE,
            "candidate_id": CANDIDATE_ID,
            "venue": args.venue,
            "manifest_sha256": manifest_sha,
            "source_integrity_composite_sha256": composite_sha,
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
            "resume_supported": True,
        }

        def persist_finished_checkpoint(final_bytes: int) -> None:
            write_checkpoint(
                cp_path,
                venue=args.venue,
                manifest_sha256=manifest_sha,
                source_integrity_composite_sha256=composite_sha,
                phase_start=phase_start,
                phase_end=phase_end,
                last_completed_asof=last_completed_asof,
                asofs_completed=asofs_completed,
                row_count=row_count,
                partial_bytes=final_bytes,
                source_query_count=source_query_count,
                source_rows_read=source_rows_read,
                terminal_state="FINISHED",
            )

        finalize_artifact_bundle(
            partial_path=partial_path,
            artifact_path=artifact_path,
            summary_path=summary_path,
            summary=summary,
            persist_finished_checkpoint=persist_finished_checkpoint,
        )
        partial_path = None
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
    except RunnerInterrupted as exc:
        if cp_path is not None and partial_path is not None and partial_path.exists() and cp_path.exists():
            try:
                mark_checkpoint_terminal(cp_path, terminal_state="INTERRUPTED")
            except Exception:
                pass
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} signal={signal.Signals(exc.signum).name} "
            f"partial_artifact={partial_path} checkpoint={cp_path} final_holdout_access=GATED "
            f"database_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 128 + exc.signum
    except Exception as exc:
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} "
            f"partial_artifact={partial_path} checkpoint={cp_path} final_holdout_access=GATED "
            f"database_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
