from __future__ import annotations

"""Read-only dataset builder for Issue #593 discovery/validation artifacts.

The runner derives and freezes one 60/20/20 split from source availability,
builds exactly one non-holdout phase per invocation, and never exposes a
final-holdout phase option.
"""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.research.multi_horizon_rotation_dataset_builder_v1 import (
    AssetCoverage,
    RotationV1PitIndex,
    RotationV1Point,
    comparable_horizon_return,
    derive_common_source_span,
    forward_response,
    observed_asset_ids_at_asof,
    split_manifest_payload,
)
from src.research.multi_horizon_rotation_replay_v1 import (
    CANDIDATE_SPECS,
    Candle,
    CandidateResult,
    evaluate_candidate,
)
from src.research.multi_horizon_rotation_validation_v1 import ensure_utc


RUNNER_NAME = "run_multi_horizon_rotation_dataset_builder_v1"
RUNNER_VERSION = "1.0.0"
ALLOWED_PHASES = ("discovery", "validation")
MAX_LOOKBACK = timedelta(hours=36)
MAX_FORWARD = timedelta(hours=24)
FORWARD_HORIZONS = {
    "forward_15m": timedelta(minutes=15),
    "forward_1h": timedelta(hours=1),
    "forward_4h": timedelta(hours=4),
    "forward_24h": timedelta(hours=24),
}
ROTATION_V1_MODEL_VERSION = "1.0"


def emit(message: str) -> None:
    print(message, flush=True)


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat().replace("+00:00", "Z")
    raise TypeError(type(value).__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build #593 discovery/validation rows without holdout access")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--phase", required=True, choices=ALLOWED_PHASES)
    parser.add_argument("--output-dir", default="data/research/multi_horizon_rotation_validation_v1")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def manifest_fingerprint(manifest: dict[str, object]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def coverage_fingerprint(coverage: list[AssetCoverage]) -> str:
    payload = [
        {
            "asset_id": row.asset_id,
            "first_close_ts": json_default(ensure_utc(row.first_close_ts)),
            "last_close_ts": json_default(ensure_utc(row.last_close_ts)),
        }
        for row in sorted(coverage, key=lambda item: item.asset_id)
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def load_frozen_manifest(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("frozen split manifest must be a JSON object")
    if raw.get("manifest_version") != "1.0.0":
        raise ValueError("frozen split manifest_version must be 1.0.0")
    if raw.get("final_holdout_inspected") is not False:
        raise ValueError("frozen split manifest must assert final_holdout_inspected=false")
    return raw


def _validate_frozen_manifest_candidate(
    *, path: Path, candidate: dict[str, object]
) -> tuple[dict[str, object], str]:
    frozen = load_frozen_manifest(path)
    if manifest_fingerprint(frozen) != manifest_fingerprint(candidate):
        raise ValueError("fresh source availability disagrees with frozen split manifest")
    return frozen, "REUSED"


def persist_or_reuse_manifest(path: Path, candidate: dict[str, object]) -> tuple[dict[str, object], str]:
    """Create the frozen manifest exactly once; concurrent losers validate and reuse it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return _validate_frozen_manifest_candidate(path=path, candidate=candidate)

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return candidate, "CREATED"


def checkpoint_path(output_dir: Path, phase: str) -> Path:
    return output_dir / f".{phase}_checkpoint_v1.json"


def write_checkpoint(
    path: Path,
    *,
    venue: str,
    phase: str,
    manifest_sha256: str,
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
        "phase": phase,
        "manifest_sha256": manifest_sha256,
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
    phase: str,
    expected_manifest_sha256: str,
) -> None:
    if checkpoint.get("runner") != RUNNER_NAME or checkpoint.get("runner_version") != RUNNER_VERSION:
        raise ValueError("checkpoint runner/version mismatch")
    if checkpoint.get("venue") != venue or checkpoint.get("phase") != phase:
        raise ValueError("checkpoint venue/phase mismatch")
    if checkpoint.get("manifest_sha256") != expected_manifest_sha256:
        raise ValueError("checkpoint split/source manifest mismatch")
    if checkpoint.get("terminal_state") == "FINISHED":
        raise ValueError("checkpoint is already FINISHED; start a new run without --resume")
    for key in ("asofs_completed", "row_count", "partial_bytes"):
        if int(checkpoint.get(key, -1)) < 0:
            raise ValueError(f"checkpoint {key} must be non-negative")


def _count_newlines(path: Path) -> int:
    count = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            count += block.count(b"\n")
    return count


def reconcile_partial_to_checkpoint(partial_path: Path, checkpoint: dict[str, Any]) -> None:
    if not partial_path.exists():
        raise ValueError("resume requested but partial artifact is missing")
    expected_bytes = int(checkpoint["partial_bytes"])
    actual_bytes = partial_path.stat().st_size
    if actual_bytes < expected_bytes:
        raise ValueError(
            f"partial artifact shorter than checkpoint: actual={actual_bytes} expected={expected_bytes}"
        )
    with partial_path.open("r+b") as handle:
        handle.truncate(expected_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    line_count = _count_newlines(partial_path)
    if line_count != int(checkpoint["row_count"]):
        raise ValueError(
            f"partial artifact row count mismatch after reconcile: actual={line_count} "
            f"expected={checkpoint['row_count']}"
        )


def mark_checkpoint_terminal(path: Path, *, terminal_state: str) -> None:
    checkpoint = load_checkpoint(path)
    last_raw = checkpoint.get("last_completed_asof")
    write_checkpoint(
        path,
        venue=str(checkpoint["venue"]),
        phase=str(checkpoint["phase"]),
        manifest_sha256=str(checkpoint["manifest_sha256"]),
        last_completed_asof=None if last_raw is None else parse_ts(last_raw),
        asofs_completed=int(checkpoint["asofs_completed"]),
        row_count=int(checkpoint["row_count"]),
        partial_bytes=int(checkpoint["partial_bytes"]),
        source_query_count=int(checkpoint.get("source_query_count", 0)),
        source_rows_read=int(checkpoint.get("source_rows_read", 0)),
        terminal_state=terminal_state,
    )


def fetch_asset_coverage(
    conn: Any,
    *,
    venue: str,
    through_ts: datetime | None = None,
) -> list[AssetCoverage]:
    cutoff_clause = "" if through_ts is None else " AND close_ts_utc < %s"
    sql = f"""
    SELECT asset_id, MIN(close_ts_utc) AS first_close_ts, MAX(close_ts_utc) AS last_close_ts
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = '15m'
      {cutoff_clause}
    GROUP BY asset_id
    ORDER BY asset_id
    """
    params: tuple[Any, ...]
    if through_ts is None:
        params = (venue,)
    else:
        params = (venue, ensure_utc(through_ts).replace(tzinfo=None))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        AssetCoverage(
            asset_id=int(row["asset_id"]),
            first_close_ts=parse_ts(row["first_close_ts"]),
            last_close_ts=parse_ts(row["last_close_ts"]),
        )
        for row in rows
    ]


def fetch_rotation_v1_first_ts(conn: Any, *, venue: str) -> datetime:
    sql = """
    SELECT MIN(as_of_ts_utc) AS first_ts
    FROM market_rotation_pressure_snapshot_v1
    WHERE venue = %s AND model_version = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, ROTATION_V1_MODEL_VERSION))
        row = cur.fetchone()
    if not row or row.get("first_ts") is None:
        raise ValueError("Rotation V1 PIT history unavailable for venue")
    return parse_ts(row["first_ts"])


def _candidate_manifest(
    *,
    venue: str,
    coverage: list[AssetCoverage],
    rotation_first: datetime,
) -> dict[str, object]:
    span = derive_common_source_span(coverage=coverage, rotation_v1_first_ts=rotation_first)
    manifest = split_manifest_payload(span)
    manifest["venue"] = venue
    manifest["source_coverage_sha256"] = coverage_fingerprint(coverage)
    return manifest


def load_or_freeze_source_manifest(
    conn: Any,
    *,
    venue: str,
    manifest_path: Path,
) -> tuple[dict[str, object], list[AssetCoverage], str]:
    rotation_first = fetch_rotation_v1_first_ts(conn, venue=venue)
    if manifest_path.exists():
        frozen = load_frozen_manifest(manifest_path)
        if frozen.get("venue") != venue:
            raise ValueError("frozen split manifest venue mismatch")
        source_span = frozen.get("source_span")
        if not isinstance(source_span, dict) or "end" not in source_span:
            raise ValueError("frozen split manifest missing source_span.end")
        frozen_end = parse_ts(source_span["end"])
        capped_coverage = fetch_asset_coverage(conn, venue=venue, through_ts=frozen_end)
        candidate = _candidate_manifest(
            venue=venue,
            coverage=capped_coverage,
            rotation_first=rotation_first,
        )
        reused, state = persist_or_reuse_manifest(manifest_path, candidate)
        return reused, capped_coverage, state

    full_coverage = fetch_asset_coverage(conn, venue=venue)
    preliminary_span = derive_common_source_span(
        coverage=full_coverage,
        rotation_v1_first_ts=rotation_first,
    )
    capped_coverage = fetch_asset_coverage(conn, venue=venue, through_ts=preliminary_span.end)
    candidate = _candidate_manifest(
        venue=venue,
        coverage=capped_coverage,
        rotation_first=rotation_first,
    )
    frozen, state = persist_or_reuse_manifest(manifest_path, candidate)
    return frozen, capped_coverage, state


def fetch_rotation_v1_points(
    conn: Any,
    *,
    venue: str,
    through_ts: datetime,
) -> RotationV1PitIndex:
    sql = """
    SELECT o.asset_id, o.as_of_ts_utc, o.score_total, o.pressure_state
    FROM market_rotation_pressure_observation_v1 o
    JOIN market_rotation_pressure_snapshot_v1 s
      ON s.pressure_snapshot_id = o.pressure_snapshot_id
    WHERE s.venue = %s
      AND o.model_version = %s
      AND s.model_version = %s
      AND o.as_of_ts_utc < %s
      AND s.as_of_ts_utc < %s
    ORDER BY o.asset_id, o.as_of_ts_utc, o.pressure_obs_id
    """
    cutoff = ensure_utc(through_ts).replace(tzinfo=None)
    with conn.cursor() as cur:
        cur.execute(sql, (venue, ROTATION_V1_MODEL_VERSION, ROTATION_V1_MODEL_VERSION, cutoff, cutoff))
        rows = cur.fetchall()
    by_asset: dict[int, list[RotationV1Point]] = {}
    for row in rows:
        by_asset.setdefault(int(row["asset_id"]), []).append(
            RotationV1Point(
                asof_ts=parse_ts(row["as_of_ts_utc"]),
                score_total=float(row["score_total"]),
                pressure_state=str(row["pressure_state"]),
            )
        )
    return RotationV1PitIndex(by_asset)


def fetch_candles_for_chunk(
    conn: Any,
    *,
    venue: str,
    chunk_asofs: list[datetime],
    phase_end: datetime,
) -> tuple[dict[int, list[Candle]], dict[int, dict[datetime, Decimal]], int]:
    if not chunk_asofs:
        return {}, {}, 0
    first_asof = ensure_utc(chunk_asofs[0])
    last_asof = ensure_utc(chunk_asofs[-1])
    start = first_asof - MAX_LOOKBACK
    latest_needed = min(last_asof + MAX_FORWARD, ensure_utc(phase_end) - timedelta(minutes=15))
    sql = """
    SELECT asset_id, close_ts_utc, close_price, volume_base
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = '15m'
      AND close_ts_utc >= %s
      AND close_ts_utc <= %s
    ORDER BY asset_id, close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, start.replace(tzinfo=None), latest_needed.replace(tzinfo=None)))
        rows = cur.fetchall()

    candles: dict[int, list[Candle]] = {}
    closes: dict[int, dict[datetime, Decimal]] = {}
    for row in rows:
        asset_id = int(row["asset_id"])
        ts = parse_ts(row["close_ts_utc"])
        close = Decimal(str(row["close_price"]))
        closes.setdefault(asset_id, {})[ts] = close
        candles.setdefault(asset_id, []).append(
            Candle(
                close_ts_utc=ts,
                close_price=close,
                volume_base=Decimal(str(row["volume_base"])),
            )
        )
    return candles, closes, len(rows)


def replay_candles_at_asof(
    *,
    chunk_candles: dict[int, list[Candle]],
    observed_asset_ids: tuple[int, ...],
    asof_ts: datetime,
) -> dict[int, list[Candle]]:
    asof = ensure_utc(asof_ts)
    start = asof - MAX_LOOKBACK
    return {
        asset_id: [
            candle
            for candle in chunk_candles.get(asset_id, [])
            if start <= ensure_utc(candle.close_ts_utc) <= asof
        ]
        for asset_id in observed_asset_ids
    }


def asof_grid(start: datetime, end: datetime) -> list[datetime]:
    out: list[datetime] = []
    current = ensure_utc(start)
    stop = ensure_utc(end)
    while current < stop:
        out.append(current)
        current += timedelta(minutes=15)
    return out


def chunk_asof_grid_by_utc_day(grid: list[datetime]) -> list[list[datetime]]:
    chunks: list[list[datetime]] = []
    current_date: date | None = None
    current_chunk: list[datetime] = []
    for raw_asof in grid:
        asof = ensure_utc(raw_asof)
        asof_date = asof.date()
        if current_date is not None and asof_date != current_date:
            chunks.append(current_chunk)
            current_chunk = []
        current_date = asof_date
        current_chunk.append(asof)
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def build_validation_row(
    *,
    result: CandidateResult,
    close_by_ts: dict[datetime, Decimal],
    spec_by_id: dict[str, Any],
    pit_index: RotationV1PitIndex,
    phase_end: datetime,
) -> dict[str, Any]:
    spec = spec_by_id[result.candidate_id]
    pit = pit_index.latest_at_or_before(asset_id=result.asset_id, asof_ts=result.asof_ts)
    row = {
        "venue": result.venue,
        "asset_id": result.asset_id,
        "asof_ts": result.asof_ts,
        "candidate_id": result.candidate_id,
        "candidate_model_id": result.model_id,
        "candidate_model_version": result.model_version,
        "candidate_effective_horizon": result.effective_horizon,
        "candidate_score": None if result.rotation_score is None else float(result.rotation_score),
        "candidate_data_quality": result.data_quality,
        "candidate_reason": result.reason,
        "candidate_cohort_size": result.cohort_size,
        "b0_score": None if pit is None else pit.score_total,
        "b0_pressure_state": None if pit is None else pit.pressure_state,
        "b0_model_version": ROTATION_V1_MODEL_VERSION,
        "b1_return": comparable_horizon_return(
            close_by_ts=close_by_ts,
            asof_ts=result.asof_ts,
            spec=spec,
        ),
        "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
    }
    for field, horizon in FORWARD_HORIZONS.items():
        row[field] = forward_response(
            close_by_ts=close_by_ts,
            asof_ts=result.asof_ts,
            horizon=horizon,
            phase_end=phase_end,
        )
    return row


def write_row(handle: BinaryIO, row: dict[str, Any]) -> None:
    payload = (json.dumps(row, sort_keys=True, default=json_default) + "\n").encode("utf-8")
    handle.write(payload)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    started = time.perf_counter()
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} mode=research-read-only "
        f"venue={args.venue} phase={args.phase} workers=1 resume={int(bool(args.resume))} "
        "final_holdout_access=DENY"
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
    query_count = 0
    query_rows = 0
    try:
        conn = get_db_connection()
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "split_manifest_v1.json"

        emit("PHASE_STARTED name=freeze_or_validate_source_manifest")
        phase_started = time.perf_counter()
        manifest, coverage, manifest_state = load_or_freeze_source_manifest(
            conn,
            venue=args.venue,
            manifest_path=manifest_path,
        )
        manifest_sha256 = manifest_fingerprint(manifest)
        split = manifest["splits"][args.phase]
        phase_start = parse_ts(split["start"])
        phase_end = parse_ts(split["end"])
        source_span = manifest["source_span"]
        emit(
            f"PHASE_FINISHED name=freeze_or_validate_source_manifest state={manifest_state} "
            f"coverage_assets={len(coverage)} source_start={source_span['start']} source_end={source_span['end']} "
            f"phase_start={phase_start.isoformat()} phase_end={phase_end.isoformat()} "
            f"manifest_sha256={manifest_sha256} elapsed_s={time.perf_counter() - phase_started:.3f}"
        )

        artifact_path = output_dir / f"{args.phase}_rows_v1.jsonl"
        partial_path = output_dir / f".{args.phase}_rows_v1.jsonl.partial"
        summary_path = output_dir / f"{args.phase}_summary_v1.json"
        cp_path = checkpoint_path(output_dir, args.phase)

        if args.resume:
            checkpoint = load_checkpoint(cp_path)
            validate_resume_checkpoint(
                checkpoint,
                venue=args.venue,
                phase=args.phase,
                expected_manifest_sha256=manifest_sha256,
            )
            reconcile_partial_to_checkpoint(partial_path, checkpoint)
            last_raw = checkpoint.get("last_completed_asof")
            last_completed_asof = None if last_raw is None else parse_ts(last_raw)
            asofs_completed = int(checkpoint["asofs_completed"])
            row_count = int(checkpoint["row_count"])
            query_count = int(checkpoint.get("source_query_count", 0))
            query_rows = int(checkpoint.get("source_rows_read", 0))
            emit(
                f"RESUME checkpoint={cp_path} last_completed_asof={last_completed_asof} "
                f"asofs_completed={asofs_completed} rows={row_count} partial_bytes={checkpoint['partial_bytes']}"
            )
        else:
            for stale_path in (artifact_path, partial_path, summary_path, cp_path):
                if stale_path.exists():
                    stale_path.unlink()
            partial_path.touch()
            write_checkpoint(
                cp_path,
                venue=args.venue,
                phase=args.phase,
                manifest_sha256=manifest_sha256,
                last_completed_asof=None,
                asofs_completed=0,
                row_count=0,
                partial_bytes=0,
                source_query_count=0,
                source_rows_read=0,
                terminal_state="RUNNING",
            )

        emit("PHASE_STARTED name=load_rotation_v1_pit")
        phase_started = time.perf_counter()
        pit_index = fetch_rotation_v1_points(conn, venue=args.venue, through_ts=phase_end)
        emit(f"PHASE_FINISHED name=load_rotation_v1_pit elapsed_s={time.perf_counter() - phase_started:.3f}")

        emit(f"PHASE_STARTED name=build_{args.phase}_artifact")
        phase_started = time.perf_counter()
        spec_by_id = {spec.candidate_id: spec for spec in CANDIDATE_SPECS}
        full_grid = asof_grid(phase_start, phase_end)
        if last_completed_asof is not None:
            if last_completed_asof not in full_grid:
                raise ValueError("checkpoint last_completed_asof is outside frozen phase grid")
            expected_completed = full_grid.index(last_completed_asof) + 1
            if asofs_completed != expected_completed:
                raise ValueError(
                    f"checkpoint asofs_completed mismatch: actual={asofs_completed} expected={expected_completed}"
                )
        elif asofs_completed != 0:
            raise ValueError("checkpoint has completed as-of count without last_completed_asof")
        remaining_grid = [
            asof for asof in full_grid
            if last_completed_asof is None or ensure_utc(asof) > ensure_utc(last_completed_asof)
        ]
        chunks = chunk_asof_grid_by_utc_day(remaining_grid)
        with partial_path.open("ab") as handle:
            for chunk in chunks:
                chunk_candles, close_maps, fetched = fetch_candles_for_chunk(
                    conn,
                    venue=args.venue,
                    chunk_asofs=chunk,
                    phase_end=phase_end,
                )
                query_rows += fetched
                query_count += 1
                for asof in chunk:
                    observed_ids = observed_asset_ids_at_asof(coverage, asof_ts=asof)
                    replay_candles = replay_candles_at_asof(
                        chunk_candles=chunk_candles,
                        observed_asset_ids=observed_ids,
                        asof_ts=asof,
                    )
                    for spec in CANDIDATE_SPECS:
                        results = evaluate_candidate(
                            candles_by_asset=replay_candles,
                            asof_ts=asof,
                            spec=spec,
                            venue=args.venue,
                        )
                        for result in results:
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
                        phase=args.phase,
                        manifest_sha256=manifest_sha256,
                        last_completed_asof=last_completed_asof,
                        asofs_completed=asofs_completed,
                        row_count=row_count,
                        partial_bytes=partial_bytes,
                        source_query_count=query_count,
                        source_rows_read=query_rows,
                        terminal_state="RUNNING",
                    )
                    if asofs_completed % 96 == 0:
                        emit(
                            f"HEARTBEAT phase={args.phase} asofs_completed={asofs_completed} rows_built={row_count} "
                            f"observed_assets={len(observed_ids)} source_queries={query_count} "
                            f"source_rows_read={query_rows} elapsed_s={time.perf_counter() - phase_started:.3f}"
                        )

        if asofs_completed != len(full_grid):
            raise ValueError(
                f"as-of completion mismatch: completed={asofs_completed} expected={len(full_grid)}"
            )
        partial_path.replace(artifact_path)
        partial_path = None
        final_bytes = artifact_path.stat().st_size
        write_checkpoint(
            cp_path,
            venue=args.venue,
            phase=args.phase,
            manifest_sha256=manifest_sha256,
            last_completed_asof=last_completed_asof,
            asofs_completed=asofs_completed,
            row_count=row_count,
            partial_bytes=final_bytes,
            source_query_count=query_count,
            source_rows_read=query_rows,
            terminal_state="FINISHED",
        )
        summary = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "venue": args.venue,
            "phase": args.phase,
            "manifest_sha256": manifest_sha256,
            "manifest_state": manifest_state,
            "row_count": row_count,
            "asof_count": len(full_grid),
            "source_query_count": query_count,
            "source_rows_read": query_rows,
            "source_batching": "one_bounded_query_per_utc_asof_day",
            "asset_universe_rule": "first_canonical_15m_close_at_or_before_asof",
            "artifact_write": "streamed_checkpointed_atomic_partial_then_replace",
            "resume_supported": True,
            "final_holdout_access": "DENY",
            "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
            "database_writes": 0,
        }
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        emit(
            f"PHASE_FINISHED name=build_{args.phase}_artifact rows={row_count} source_queries={query_count} "
            f"source_rows_read={query_rows} elapsed_s={time.perf_counter() - phase_started:.3f}"
        )
        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS phase={args.phase} rows={row_count} "
            f"manifest_state={manifest_state} final_holdout_access=DENY database_writes=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except KeyboardInterrupt:
        if cp_path is not None and partial_path is not None and partial_path.exists():
            try:
                mark_checkpoint_terminal(cp_path, terminal_state="INTERRUPTED")
            except Exception:
                pass
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} partial_artifact={partial_path} checkpoint={cp_path} "
            f"final_holdout_access=DENY database_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 130
    except Exception as exc:
        if cp_path is not None and partial_path is not None and partial_path.exists():
            try:
                mark_checkpoint_terminal(cp_path, terminal_state="FAILED")
            except Exception:
                pass
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} partial_artifact={partial_path} "
            f"checkpoint={cp_path} final_holdout_access=DENY database_writes=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
