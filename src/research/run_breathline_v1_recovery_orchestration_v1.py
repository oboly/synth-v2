"""
Breathline V1 recovery orchestration Arm-A smoke.

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ARM_ID = "ARM_A"
DEFAULT_RUN_ID_PREFIX = "arm_a"
DEFAULT_OUT_BASE = "data/research/breathline_v1_recovery_orchestration_v1"
DEPENDENCY_CLOSURE_FILES = (
    "src/research/backtest_breath_curve_partial_to_full_v1.py",
    "src/market_context/breath_curve_core_v1.py",
    "src/research/breath_curve_template_matcher_v1.py",
    "src/research/run_breath_curve_template_partial_v1.py",
)
EXPECTED_OFFSET_COUNT = 9
RECOVERY_SOURCE_CODE_STATUS = "PASS"
RECOVERY_SOURCE_DATA_STATUS = "UNAVAILABLE"
RECOVERY_RESULT_STATUS = "UNAVAILABLE"
V1_MODULE = "src.research.backtest_breath_curve_partial_to_full_v1"

FLATTENED_FIELDNAMES = (
    "run_id",
    "arm_id",
    "source_jsonl_path",
    "source_jsonl_row_number",
    "source_jsonl_sha256",
    "source_code_recovery_status",
    "source_data_recovery_status",
    "result_recovery_status",
    "availability_status",
    "symbol",
    "anchor_ts_utc",
    "checkpoint_ratio",
    "selected_partial_offset_days",
    "as_of_ts_utc",
    "phase_offset_days",
    "future_target_is_future",
    "partial_match_score",
    "ranking_score",
    "required_ratio",
    "required_marker_due",
    "required_marker_matched",
    "due_marker_count",
    "observed_marker_count",
    "min_due_markers_met",
    "structurally_eligible",
    "score_zero_reason",
    "notes_json",
    "selected_by_v1",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    return Path.cwd()


def resolve_git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    commit = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not commit:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        detail = stderr or "git rev-parse HEAD failed"
        raise RuntimeError(f"unable to resolve git commit provenance: {detail}")
    return commit


def git_show_head_bytes(repo_root: Path, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        detail = stderr or "git show failed"
        raise RuntimeError(f"unable to resolve frozen dependency {relative_path}: {detail}")
    return completed.stdout


def closure_hashes(repo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative_path in DEPENDENCY_CLOSURE_FILES:
        head_bytes = git_show_head_bytes(repo_root, relative_path)
        hashes[relative_path] = sha256_bytes(head_bytes)
    return hashes


def verify_dependency_closure_integrity(repo_root: Path) -> dict[str, str]:
    hashes = closure_hashes(repo_root)
    for relative_path, committed_hash in hashes.items():
        path = repo_root / relative_path
        if not path.is_file():
            raise RuntimeError(f"frozen dependency missing: {relative_path}")
        working_tree_hash = sha256_file(path)
        if working_tree_hash != committed_hash:
            raise RuntimeError(f"frozen dependency changed: {relative_path}")
    return hashes


def single_value(name: str, raw_value: str) -> str:
    value = raw_value.strip()
    if not value or "," in value:
        raise ValueError(f"{name} must be exactly one value")
    return value


def locate_v1_artifacts(raw_dir: Path) -> tuple[Path, Path]:
    csv_paths = sorted(raw_dir.glob("breath_curve_partial_to_full_v1_*.csv"))
    jsonl_paths = sorted(raw_dir.glob("breath_curve_partial_to_full_v1_*.jsonl"))
    if len(csv_paths) != 1 or len(jsonl_paths) != 1:
        raise RuntimeError(
            f"expected exactly 1 V1 csv and 1 V1 jsonl in {raw_dir}, "
            f"found csv={len(csv_paths)} jsonl={len(jsonl_paths)}"
        )
    return csv_paths[0], jsonl_paths[0]


def parse_jsonl(jsonl_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"jsonl parse error on line {line_number}: {exc}") from exc
            row["_source_jsonl_row_number"] = line_number
            rows.append(row)
            if row.get("status") != "OK":
                continue
            offsets = row.get("all_partial_offsets")
            if not isinstance(offsets, list):
                raise RuntimeError(f"line {line_number}: missing all_partial_offsets for status=OK")
            if len(offsets) != EXPECTED_OFFSET_COUNT:
                raise RuntimeError(
                    f"line {line_number}: expected {EXPECTED_OFFSET_COUNT} all_partial_offsets, got {len(offsets)}"
                )
    return rows


def required_marker_due(notes: list[str]) -> bool | None:
    if "UNKNOWN_REQUIRED_RATIO" in notes:
        return None
    if "REQUIRED_RATIO_NOT_DUE" in notes:
        return False
    return True


def required_marker_matched(result: dict[str, Any]) -> bool | None:
    required_ratio = result.get("required_ratio")
    if required_ratio is None:
        return None
    for marker in result.get("markers") or []:
        if abs(float(marker.get("ratio")) - float(required_ratio)) < 1e-9:
            return bool(marker.get("matched"))
    return None


def structurally_eligible(
    *,
    future_target_is_future: Any,
    required_due: bool | None,
    required_matched: bool | None,
    min_due_met: bool,
) -> bool:
    return (
        future_target_is_future is True
        and required_due is True
        and required_matched is True
        and min_due_met is True
    )


def score_zero_reason(
    notes: list[str],
    *,
    required_matched: bool | None,
) -> list[str]:
    reasons = list(notes)
    has_conflict = False
    if required_matched is True and "REQUIRED_RATIO_NOT_MATCHED" in notes:
        has_conflict = True
    elif (
        required_matched is False
        and "REQUIRED_RATIO_NOT_MATCHED" not in notes
        and "UNKNOWN_REQUIRED_RATIO" not in notes
        and "REQUIRED_RATIO_NOT_DUE" not in notes
    ):
        has_conflict = True

    if has_conflict and "DERIVATION_CONFLICT" not in reasons:
        reasons.append("DERIVATION_CONFLICT")
    return reasons


def build_availability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    ok_row_count = 0
    for fallback_row_number, row in enumerate(rows, start=1):
        source_row_number = int(row.get("_source_jsonl_row_number", fallback_row_number))
        if row.get("status") == "OK":
            ok_row_count += 1
            continue
        if row.get("status") != "ERROR":
            continue
        evidence.append(
            {
                "availability_status": "DATA_UNAVAILABLE",
                "source_jsonl_row_number": source_row_number,
                "symbol": row.get("symbol"),
                "anchor_ts_utc": row.get("anchor_ts_utc"),
                "checkpoint_ratio": row.get("checkpoint_ratio"),
                "raw_error_text": row.get("error", ""),
            }
        )
    availability_status = "DATA_UNAVAILABLE" if evidence else "OK"
    return {
        "availability_status": availability_status,
        "ok_row_count": ok_row_count,
        "data_unavailable_row_count": len(evidence),
        "evidence": evidence,
    }


def flatten_rows(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    source_jsonl_path: str,
    source_jsonl_sha256: str,
    arm_id: str = DEFAULT_ARM_ID,
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for fallback_row_number, row in enumerate(rows, start=1):
        if row.get("status") != "OK":
            continue
        source_row_number = int(row.get("_source_jsonl_row_number", fallback_row_number))
        selected_offset = row.get("selected_partial_offset_days")
        for item in row["all_partial_offsets"]:
            result = item["result"]
            notes = list(result.get("notes") or [])
            phase_offset = result.get("phase_offset_days")
            future_target = item.get("future_target_is_future")
            required_due = required_marker_due(notes)
            required_matched = required_marker_matched(result)
            min_due_met = "INSUFFICIENT_DUE_MARKERS" not in notes
            selected_by_v1 = (
                selected_offset is not None
                and phase_offset is not None
                and abs(float(selected_offset) - float(phase_offset)) < 1e-9
            )
            flattened.append(
                {
                    "run_id": run_id,
                    "arm_id": arm_id,
                    "source_jsonl_path": source_jsonl_path,
                    "source_jsonl_row_number": source_row_number,
                    "source_jsonl_sha256": source_jsonl_sha256,
                    "source_code_recovery_status": RECOVERY_SOURCE_CODE_STATUS,
                    "source_data_recovery_status": RECOVERY_SOURCE_DATA_STATUS,
                    "result_recovery_status": RECOVERY_RESULT_STATUS,
                    "availability_status": "OK",
                    "symbol": result.get("symbol"),
                    "anchor_ts_utc": result.get("anchor_ts_utc"),
                    "checkpoint_ratio": row.get("checkpoint_ratio"),
                    "selected_partial_offset_days": selected_offset,
                    "as_of_ts_utc": result.get("as_of_ts_utc"),
                    "phase_offset_days": phase_offset,
                    "future_target_is_future": future_target,
                    "partial_match_score": result.get("partial_match_score"),
                    "ranking_score": item.get("ranking_score"),
                    "required_ratio": result.get("required_ratio"),
                    "required_marker_due": required_due,
                    "required_marker_matched": required_matched,
                    "due_marker_count": result.get("due_marker_count"),
                    "observed_marker_count": result.get("observed_marker_count"),
                    "min_due_markers_met": min_due_met,
                    "structurally_eligible": structurally_eligible(
                        future_target_is_future=future_target,
                        required_due=required_due,
                        required_matched=required_matched,
                        min_due_met=min_due_met,
                    ),
                    "score_zero_reason": json.dumps(
                        score_zero_reason(
                            notes,
                            required_matched=required_matched,
                        ),
                        separators=(",", ":"),
                    ),
                    "notes_json": json.dumps(notes, separators=(",", ":")),
                    "selected_by_v1": selected_by_v1,
                }
            )
    return flattened


def write_flattened_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FLATTENED_FIELDNAMES))
        writer.writeheader()
        writer.writerows(rows)


def build_manifest(
    *,
    run_id: str,
    generated_at_utc: str,
    query_timestamp_utc: str,
    source_commit: str,
    orchestration_runner_commit: str,
    anchor_set_sha256: str,
    symbols_sha256: str,
    command_line: list[str],
    symbol: str,
    anchor: str,
    raw_csv_path: Path,
    raw_jsonl_path: Path,
    flattened_csv_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    raw_csv_sha256: str,
    raw_jsonl_sha256: str,
    flattened_csv_sha256: str,
    dependency_hashes: dict[str, str],
    flattened_row_count: int,
    subprocess_exit_code: int,
    availability_summary: dict[str, Any],
    dependency_closure_integrity_status: str,
    arm_id: str = DEFAULT_ARM_ID,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "arm_id": arm_id,
        "generated_at_utc": generated_at_utc,
        "query_timestamp_utc": query_timestamp_utc,
        "source_commit": source_commit,
        "orchestration_runner_commit": orchestration_runner_commit,
        "anchor_set_sha256": anchor_set_sha256,
        "symbols_sha256": symbols_sha256,
        "python_version": sys.version,
        "command_line": command_line,
        "symbol": symbol,
        "anchor": anchor,
        "raw_artifacts": {
            "csv": {
                "path": str(raw_csv_path),
                "sha256": raw_csv_sha256,
                "bytes": raw_csv_path.stat().st_size,
            },
            "jsonl": {
                "path": str(raw_jsonl_path),
                "sha256": raw_jsonl_sha256,
                "bytes": raw_jsonl_path.stat().st_size,
            },
        },
        "flattened_artifacts": {
            "csv": {
                "path": str(flattened_csv_path),
                "sha256": flattened_csv_sha256,
                "rows": flattened_row_count,
            }
        },
        "logs": {
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "subprocess_exit_code": subprocess_exit_code,
        },
        "availability_summary": availability_summary,
        "dependency_closure_hashes": dependency_hashes,
        "dependency_closure_integrity_status": dependency_closure_integrity_status,
        "provenance": {
            "v1_module": V1_MODULE,
            "source_code_recovery_status": RECOVERY_SOURCE_CODE_STATUS,
            "source_data_recovery_status": RECOVERY_SOURCE_DATA_STATUS,
            "result_recovery_status": RECOVERY_RESULT_STATUS,
            "availability_status": availability_summary["availability_status"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Arm-A Breathline recovery smoke wrapper around frozen V1."
    )
    parser.add_argument("--symbol", required=True, help="Exactly one symbol.")
    parser.add_argument("--anchor", required=True, help="Exactly one anchor.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_BASE)
    parser.add_argument("--arm-id", default=DEFAULT_ARM_ID)
    parser.add_argument("--run-id-prefix", default=DEFAULT_RUN_ID_PREFIX)
    args = parser.parse_args()

    try:
        symbol = single_value("symbol", args.symbol)
        anchor = single_value("anchor", args.anchor)
    except ValueError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    repo_root = find_repo_root()
    try:
        orchestration_runner_commit = resolve_git_commit(repo_root)
        dependency_hashes = verify_dependency_closure_integrity(repo_root)
    except RuntimeError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    source_commit = orchestration_runner_commit
    symbols_sha256 = sha256_text(symbol)
    anchor_set_sha256 = sha256_text(anchor)
    started_at = utc_now()
    run_id = f"{args.run_id_prefix}_{started_at.strftime('%Y%m%dT%H%M%SZ')}_{symbol.lower()}"
    run_dir = Path(args.out_dir) / run_id
    raw_dir = run_dir / "raw"
    derived_dir = run_dir / "derived"
    manifest_dir = run_dir / "manifest"
    logs_dir = run_dir / "logs"
    for path in (raw_dir, derived_dir, manifest_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    print(
        f"STARTED runner=breathline_v1_recovery_orchestration_v1 arm_id={args.arm_id} "
        f"symbol={symbol} anchor={anchor}",
        flush=True,
    )

    command_line = [
        sys.executable,
        "-m",
        V1_MODULE,
        "--symbols",
        symbol,
        "--anchors",
        anchor,
        "--out-dir",
        str(raw_dir),
    ]
    query_timestamp_utc = iso(utc_now())
    stdout_path = logs_dir / "v1_stdout.txt"
    stderr_path = logs_dir / "v1_stderr.txt"

    print("PHASE subprocess_start", flush=True)
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        completed = subprocess.run(
            command_line,
            cwd=str(repo_root),
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )
    print(f"PHASE subprocess_end exit_code={completed.returncode}", flush=True)
    if completed.returncode != 0:
        print(f"FAILED subprocess_exit_code={completed.returncode}", flush=True)
        return 1

    try:
        raw_csv_path, raw_jsonl_path = locate_v1_artifacts(raw_dir)
        raw_csv_sha256 = sha256_file(raw_csv_path)
        raw_jsonl_sha256 = sha256_file(raw_jsonl_path)
        print("PHASE parse_jsonl", flush=True)
        rows = parse_jsonl(raw_jsonl_path)
        availability_summary = build_availability_summary(rows)
        flattened = flatten_rows(
            rows,
            run_id=run_id,
            source_jsonl_path=str(raw_jsonl_path),
            source_jsonl_sha256=raw_jsonl_sha256,
            arm_id=args.arm_id,
        )
        flattened_csv_path = derived_dir / f"breathline_v1_recovery_arm_a_flattened_{run_id}.csv"
        write_flattened_csv(flattened_csv_path, flattened)
        flattened_csv_sha256 = sha256_file(flattened_csv_path)
        manifest = build_manifest(
            run_id=run_id,
            generated_at_utc=iso(utc_now()),
            query_timestamp_utc=query_timestamp_utc,
            source_commit=source_commit,
            orchestration_runner_commit=orchestration_runner_commit,
            anchor_set_sha256=anchor_set_sha256,
            symbols_sha256=symbols_sha256,
            command_line=command_line,
            symbol=symbol,
            anchor=anchor,
            raw_csv_path=raw_csv_path,
            raw_jsonl_path=raw_jsonl_path,
            flattened_csv_path=flattened_csv_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            raw_csv_sha256=raw_csv_sha256,
            raw_jsonl_sha256=raw_jsonl_sha256,
            flattened_csv_sha256=flattened_csv_sha256,
            dependency_hashes=dependency_hashes,
            flattened_row_count=len(flattened),
            subprocess_exit_code=completed.returncode,
            availability_summary=availability_summary,
            dependency_closure_integrity_status="PASS",
            arm_id=args.arm_id,
        )
    except Exception as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    manifest_path = manifest_dir / f"breathline_v1_recovery_manifest_{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"FINISHED run_id={run_id} flattened_rows={len(flattened)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
