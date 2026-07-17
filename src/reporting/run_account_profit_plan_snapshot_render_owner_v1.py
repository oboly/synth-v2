from __future__ import annotations

"""Safe, per-profile Profit Plan render owner over persisted snapshots only."""

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.market_data.native_short_fib_context_snapshot_v1 import (
    BUNDLE_NAME,
    CSV_FIELDS,
    ROW_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SnapshotContractError,
    render_rows_csv,
    resolve_manifest_artifact_paths,
)


RUNNER_NAME = "account_profit_plan_snapshot_render_owner_v1"
METADATA_SCHEMA = "account_profit_plan_snapshot_render_owner_v1"
DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
DEFAULT_NATIVE_SHORT_SNAPSHOT_ROOT = Path(
    "/var/www/html/synth/_runtime/native_short_context_snapshot_v1"
)
DELTA_STATUSES = ("NO_PREVIOUS_SNAPSHOT", "UNCHANGED", "UPDATED_NOW")
PROFILE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SAFETY_MARKERS: dict[str, int | str | bool] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "renderer_private_broker_calls": 0,
    "native_short_context_build_in_render_stage": False,
}


@dataclass(frozen=True)
class NativeShortSnapshot:
    snapshot_id: str
    rows_path: Path
    row_count: int


@dataclass(frozen=True)
class ProfitPlanSnapshot:
    render_id: str
    symbols: list[dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a top-level JSON object")
    return payload


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def validate_native_short_snapshot(snapshot_root: Path) -> NativeShortSnapshot:
    manifest_path = snapshot_root / "manifest_v1.json"
    manifest = _read_json_object(manifest_path, label="canonical native SHORT manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotContractError("native SHORT manifest schema_version mismatch")
    if manifest.get("row_schema_version") != ROW_SCHEMA_VERSION:
        raise SnapshotContractError("native SHORT manifest row_schema_version mismatch")

    snapshot_id = str(manifest.get("snapshot_id") or "")
    content_digest = str(manifest.get("content_digest") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", content_digest):
        raise SnapshotContractError("native SHORT manifest content_digest is invalid")
    expected_snapshot_id = f"nsctx-v1-{content_digest.removeprefix('sha256:')[:24]}"
    if snapshot_id != expected_snapshot_id:
        raise SnapshotContractError("native SHORT manifest snapshot_id/content_digest mismatch")

    rows_path, bundle_path = resolve_manifest_artifact_paths(snapshot_root, manifest)
    if rows_path.name != "native_short_fib_context_rows_v1.csv" or bundle_path.name != BUNDLE_NAME:
        raise SnapshotContractError("native SHORT manifest references unexpected artifacts")
    if not rows_path.is_file() or not bundle_path.is_file():
        raise SnapshotContractError("native SHORT manifest references missing immutable artifacts")

    rows_payload = rows_path.read_bytes()
    bundle_payload = bundle_path.read_bytes()
    if _sha256(rows_payload) != manifest.get("rows_csv_digest"):
        raise SnapshotContractError("native SHORT rows digest mismatch")
    if _sha256(bundle_payload) != manifest.get("snapshot_bundle_digest"):
        raise SnapshotContractError("native SHORT bundle digest mismatch")

    try:
        with rows_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != CSV_FIELDS:
                raise SnapshotContractError("native SHORT rows schema mismatch")
            csv_rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SnapshotContractError("native SHORT rows CSV is unreadable") from exc

    row_count = manifest.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise SnapshotContractError("native SHORT manifest row_count is invalid")
    if len(csv_rows) != row_count:
        raise SnapshotContractError("native SHORT rows count mismatch")

    bundle = _read_json_object(bundle_path, label="native SHORT snapshot bundle")
    envelope = bundle.get("envelope")
    bundle_rows = bundle.get("rows")
    if not isinstance(envelope, dict) or not isinstance(bundle_rows, list):
        raise SnapshotContractError("native SHORT snapshot bundle shape is invalid")
    if (
        envelope.get("schema_version") != SCHEMA_VERSION
        or envelope.get("row_schema_version") != ROW_SCHEMA_VERSION
        or envelope.get("snapshot_id") != snapshot_id
        or envelope.get("content_digest") != content_digest
        or envelope.get("row_count") != row_count
    ):
        raise SnapshotContractError("native SHORT manifest/bundle identity mismatch")
    if len(bundle_rows) != row_count or render_rows_csv(bundle_rows) != rows_payload:
        raise SnapshotContractError("native SHORT bundle rows do not match immutable CSV")

    return NativeShortSnapshot(snapshot_id=snapshot_id, rows_path=rows_path, row_count=row_count)


def validate_profit_plan_snapshot(path: Path, *, label: str) -> ProfitPlanSnapshot:
    payload = _read_json_object(path, label=label)
    render_id = payload.get("render_id")
    symbols = payload.get("symbols")
    if not isinstance(render_id, str) or not render_id.strip():
        raise ValueError(f"{label} render_id must be a non-empty string")
    if not isinstance(symbols, list):
        raise ValueError(f"{label} symbols must be a list")
    if any(not isinstance(symbol, dict) for symbol in symbols):
        raise ValueError(f"{label} symbols entries must be JSON objects")
    return ProfitPlanSnapshot(render_id=render_id, symbols=symbols)


def _atomic_write(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_metadata(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(
        path,
        (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8"),
        mode=0o644,
    )


def _delta_status_counts(snapshot: ProfitPlanSnapshot) -> dict[str, int]:
    counts = {status: 0 for status in DELTA_STATUSES}
    for symbol in snapshot.symbols:
        delta = symbol.get("delta")
        status = delta.get("delta_status") if isinstance(delta, dict) else None
        if status not in counts:
            raise ValueError(f"current Profit Plan contains invalid delta_status: {status!r}")
        counts[status] += 1
    return counts


def _metadata_payload(
    *,
    profile: str,
    started_ts: str,
    finished_ts: str,
    result: str,
    previous_snapshot_loaded: bool,
    previous_render_id: str | None,
    current_render_id: str | None,
    previous_snapshot_path: Path | None,
    native_snapshot: NativeShortSnapshot | None,
    card_count: int,
    delta_status_counts: Mapping[str, int],
    detail: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": METADATA_SCHEMA,
        "profile": profile,
        "previous_snapshot_loaded": previous_snapshot_loaded,
        "previous_render_id": previous_render_id,
        "current_render_id": current_render_id,
        "previous_snapshot_path": str(previous_snapshot_path) if previous_snapshot_path else None,
        "native_short_snapshot_id": native_snapshot.snapshot_id if native_snapshot else None,
        "native_short_rows_path": str(native_snapshot.rows_path) if native_snapshot else None,
        "card_count": card_count,
        "delta_status_counts": {status: int(delta_status_counts.get(status, 0)) for status in DELTA_STATUSES},
        "started_ts_utc": started_ts,
        "finished_ts_utc": finished_ts,
        "result": result,
        "safety": SAFETY_MARKERS,
    }
    if detail:
        payload["detail"] = detail
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely render one profile Profit Plan from persisted snapshots.")
    parser.add_argument("--account-profile", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--native-short-snapshot-root", type=Path, default=DEFAULT_NATIVE_SHORT_SNAPSHOT_ROOT)
    parser.add_argument("--monitor-href")
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--metadata-path", type=Path)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    profile = args.account_profile
    if not PROFILE_PATTERN.fullmatch(profile):
        print(f"FAILED runner={RUNNER_NAME} detail=invalid_profile", file=sys.stderr, flush=True)
        return 1

    output_root = args.output_root
    profile_dir = output_root / "accounts" / profile
    runtime_dir = profile_dir / "_runtime" / "profit_plan_render_owner_v1"
    metadata_path = args.metadata_path or runtime_dir / "latest_run.json"
    lock_path = args.lock_file or Path(f"/tmp/synth-account-profit-plan-snapshot-render-{profile}.lock")
    canonical_html = profile_dir / "profit-plan.html"
    canonical_json = profile_dir / "profit-plan.json"
    frozen_previous_path = runtime_dir / "previous-profit-plan.json"
    started_ts = _utc_now()
    print(
        f"STARTED runner={RUNNER_NAME} profile={profile} mode=persisted_snapshot worker_count=1 "
        f"started_ts_utc={started_ts}",
        flush=True,
    )
    print(
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "decision_gate=none execution_planner=none executor=none",
        flush=True,
    )

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"FINISHED runner={RUNNER_NAME} profile={profile} result=skipped_locked", flush=True)
            return 0

        native_snapshot: NativeShortSnapshot | None = None
        previous_snapshot: ProfitPlanSnapshot | None = None
        previous_loaded = False
        staging_dir: Path | None = None
        try:
            native_snapshot = validate_native_short_snapshot(args.native_short_snapshot_root)
            print(
                f"PHASE_FINISHED phase=validate_native_short_snapshot profile={profile} "
                f"snapshot_id={native_snapshot.snapshot_id} row_count={native_snapshot.row_count}",
                flush=True,
            )

            if canonical_json.exists():
                previous_snapshot = validate_profit_plan_snapshot(
                    canonical_json,
                    label="previous canonical Profit Plan",
                )
                _atomic_write(frozen_previous_path, canonical_json.read_bytes(), mode=0o600)
                previous_loaded = True
                print(
                    f"PHASE_FINISHED phase=freeze_previous_snapshot profile={profile} "
                    f"previous_render_id={previous_snapshot.render_id}",
                    flush=True,
                )
            else:
                print(
                    f"PHASE_FINISHED phase=freeze_previous_snapshot profile={profile} result=not_present",
                    flush=True,
                )

            runtime_dir.mkdir(parents=True, exist_ok=True)
            staging_dir = Path(tempfile.mkdtemp(prefix="render.", dir=runtime_dir))
            staged_html = staging_dir / "profit-plan.html"
            staged_json = staging_dir / "profit-plan.json"
            command = [
                sys.executable,
                "-m",
                "src.reporting.run_manual_short_trader_profit_plan_v1",
                "--account-profile",
                profile,
                "--venue",
                args.venue,
                "--output-root",
                str(output_root),
                "--output-html",
                str(staged_html),
                "--output-json",
                str(staged_json),
                "--native-short-context-rows",
                str(native_snapshot.rows_path),
                "--native-short-snapshot-status",
                "loaded",
                "--native-short-snapshot-id",
                native_snapshot.snapshot_id,
                "--monitor-href",
                args.monitor_href or f"/synth/accounts/{profile}/open-orders-monitor.html",
                "--output",
                args.output,
            ]
            if previous_loaded:
                command.extend(("--previous-json", str(frozen_previous_path)))
            completed = subprocess.run(command, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"Profit Plan renderer exited {completed.returncode}")
            if not staged_html.is_file() or not staged_json.is_file():
                raise RuntimeError("Profit Plan renderer did not produce both staged outputs")

            current_snapshot = validate_profit_plan_snapshot(staged_json, label="current staged Profit Plan")
            if previous_snapshot and current_snapshot.render_id == previous_snapshot.render_id:
                raise ValueError("current render_id must differ from previous render_id")
            delta_counts = _delta_status_counts(current_snapshot)
            if sum(delta_counts.values()) != len(current_snapshot.symbols):
                raise ValueError("Profit Plan delta counts do not match card count")

            _atomic_write(canonical_html, staged_html.read_bytes(), mode=0o644)
            _atomic_write(canonical_json, staged_json.read_bytes(), mode=0o644)
            finished_ts = _utc_now()
            metadata = _metadata_payload(
                profile=profile,
                started_ts=started_ts,
                finished_ts=finished_ts,
                result="ok",
                previous_snapshot_loaded=previous_loaded,
                previous_render_id=previous_snapshot.render_id if previous_snapshot else None,
                current_render_id=current_snapshot.render_id,
                previous_snapshot_path=frozen_previous_path if previous_loaded else None,
                native_snapshot=native_snapshot,
                card_count=len(current_snapshot.symbols),
                delta_status_counts=delta_counts,
            )
            _write_metadata(metadata_path, metadata)
            print(
                f"FINISHED runner={RUNNER_NAME} profile={profile} result=ok "
                f"card_count={len(current_snapshot.symbols)} current_render_id={current_snapshot.render_id} "
                f"finished_ts_utc={finished_ts}",
                flush=True,
            )
            return 0
        except Exception as exc:
            finished_ts = _utc_now()
            metadata = _metadata_payload(
                profile=profile,
                started_ts=started_ts,
                finished_ts=finished_ts,
                result="failed",
                previous_snapshot_loaded=previous_loaded,
                previous_render_id=previous_snapshot.render_id if previous_snapshot else None,
                current_render_id=None,
                previous_snapshot_path=frozen_previous_path if previous_loaded else None,
                native_snapshot=native_snapshot,
                card_count=0,
                delta_status_counts={},
                detail=str(exc),
            )
            _write_metadata(metadata_path, metadata)
            print(
                f"FAILED runner={RUNNER_NAME} profile={profile} result=failed detail={exc} "
                f"finished_ts_utc={finished_ts}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        finally:
            if staging_dir is not None and staging_dir.exists():
                for child in staging_dir.iterdir():
                    child.unlink(missing_ok=True)
                staging_dir.rmdir()
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def main(argv: Sequence[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
