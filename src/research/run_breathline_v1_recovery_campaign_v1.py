"""
Breathline V1 recovery campaign coordinator.

Drives the Arm A canonical + Arm B B.2a integer-day phase-null control
matrix from one approved cohort payload, invoking the existing one-job
wrapper (run_breathline_v1_recovery_orchestration_v1) once per job. Never
executes frozen V1 directly and never writes to any operational table.

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
from pathlib import Path
from typing import Any

from src.research.breathline_v1_recovery_campaign_matrix_v1 import (
    CampaignJob,
    build_campaign_jobs,
)
from src.research.breathline_v1_recovery_cohort_manifest_v1 import (
    CohortManifestError,
    resolve_approved_cohort,
)
from src.research.run_breathline_v1_recovery_orchestration_v1 import (
    closure_hashes,
    find_repo_root,
    git_show_head_bytes,
    iso,
    resolve_git_commit,
    sha256_bytes,
    sha256_file,
    utc_now,
)

WRAPPER_MODULE = "src.research.run_breathline_v1_recovery_orchestration_v1"
COORDINATOR_MODULE = "src.research.run_breathline_v1_recovery_campaign_v1"
CAMPAIGN_MATRIX_MODULE = "src.research.breathline_v1_recovery_campaign_matrix_v1"
COHORT_MANIFEST_LOADER_MODULE = "src.research.breathline_v1_recovery_cohort_manifest_v1"

# Maps each required campaign-manifest code-hash field to the committed
# HEAD-relative source path it must be resolved from via `git show`.
CODE_PROVENANCE_FILES: dict[str, str] = {
    "wrapper_sha256": f"{WRAPPER_MODULE.replace('.', '/')}.py",
    "coordinator_sha256": f"{COORDINATOR_MODULE.replace('.', '/')}.py",
    "campaign_matrix_module_sha256": f"{CAMPAIGN_MATRIX_MODULE.replace('.', '/')}.py",
    "cohort_manifest_loader_sha256": f"{COHORT_MANIFEST_LOADER_MODULE.replace('.', '/')}.py",
}

STATUS_OK = "OK"
STATUS_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
STATUS_SUBPROCESS_FAILED = "SUBPROCESS_FAILED"

CONTROL_METADATA_FIELDNAMES = (
    "job_id",
    "arm_id",
    "control_id",
    "symbol",
    "base_anchor_ts_utc",
    "physical_anchor_ts_utc",
    "anchor_displacement_days",
    "phase_class_mod_21_days",
    "terminal_status",
)


def verify_clean_worktree(repo_root: Path) -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"unable to verify clean worktree: {stderr or 'git status failed'}")
    output = completed.stdout.decode("utf-8", errors="replace")
    if output.strip():
        raise RuntimeError(
            "worktree is not clean, refusing campaign execution "
            "(HEAD-byte code provenance would not match working-tree code):\n" + output
        )


def resolve_code_hashes(repo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for hash_key, relative_path in CODE_PROVENANCE_FILES.items():
        head_bytes = git_show_head_bytes(repo_root, relative_path)
        hashes[hash_key] = sha256_bytes(head_bytes)
    return hashes


def compute_job_matrix_hash(jobs: list[CampaignJob]) -> str:
    ordered = [
        {
            "job_id": job.job_id,
            "arm_id": job.arm_id,
            "control_id": job.control_id,
            "symbol": job.symbol,
            "base_anchor_ts_utc": job.base_anchor_ts_utc,
            "physical_anchor_ts_utc": job.physical_anchor_ts_utc,
            "anchor_displacement_days": job.anchor_displacement_days,
            "phase_class_mod_21_days": job.phase_class_mod_21_days,
        }
        for job in jobs
    ]
    canonical = json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _hash_existing_files(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not root.exists():
        return hashes
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hashes[str(path.relative_to(root))] = sha256_file(path)
    return hashes


def _find_wrapper_manifest(job_out_dir: Path) -> Path | None:
    manifest_paths = sorted(job_out_dir.glob("*/manifest/*.json"))
    if len(manifest_paths) != 1:
        return None
    return manifest_paths[0]


def run_job(job: CampaignJob, *, repo_root: Path, jobs_dir: Path) -> dict[str, Any]:
    job_out_dir = jobs_dir / job.job_id
    if job_out_dir.exists():
        raise RuntimeError(
            f"job output directory already exists, refusing to overwrite or resume: {job_out_dir}"
        )
    job_out_dir.mkdir(parents=True)

    wrapper_command_line = [
        sys.executable,
        "-m",
        WRAPPER_MODULE,
        "--symbol",
        job.symbol,
        "--anchor",
        job.physical_anchor_ts_utc,
        "--out-dir",
        str(job_out_dir),
        "--arm-id",
        job.arm_id,
        "--run-id-prefix",
        job.run_id_prefix,
    ]

    stdout_path = job_out_dir / "wrapper_stdout.txt"
    stderr_path = job_out_dir / "wrapper_stderr.txt"
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        completed = subprocess.run(
            wrapper_command_line,
            cwd=str(repo_root),
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )

    frozen_v1_subprocess_command_line: list[str] | None = None
    terminal_status = STATUS_SUBPROCESS_FAILED
    wrapper_manifest_path: Path | None = None

    if completed.returncode == 0:
        wrapper_manifest_path = _find_wrapper_manifest(job_out_dir)
        if wrapper_manifest_path is not None:
            wrapper_manifest = json.loads(wrapper_manifest_path.read_text(encoding="utf-8"))
            # The wrapper's manifest "command_line" field is, and remains,
            # the unchanged frozen V1 subprocess invocation only.
            frozen_v1_subprocess_command_line = wrapper_manifest.get("command_line")
            availability_status = wrapper_manifest.get("availability_summary", {}).get(
                "availability_status"
            )
            if availability_status == STATUS_OK:
                terminal_status = STATUS_OK
            elif availability_status == STATUS_DATA_UNAVAILABLE:
                terminal_status = STATUS_DATA_UNAVAILABLE

    return {
        "job_id": job.job_id,
        "arm_id": job.arm_id,
        "control_id": job.control_id,
        "symbol": job.symbol,
        "base_anchor_ts_utc": job.base_anchor_ts_utc,
        "physical_anchor_ts_utc": job.physical_anchor_ts_utc,
        "anchor_displacement_days": job.anchor_displacement_days,
        "phase_class_mod_21_days": job.phase_class_mod_21_days,
        "terminal_status": terminal_status,
        "wrapper_command_line": wrapper_command_line,
        "frozen_v1_subprocess_command_line": frozen_v1_subprocess_command_line,
        "wrapper_exit_code": completed.returncode,
        "job_out_dir": str(job_out_dir),
        "wrapper_manifest_path": str(wrapper_manifest_path) if wrapper_manifest_path else None,
        "log_paths": {
            "wrapper_stdout_path": str(stdout_path),
            "wrapper_stderr_path": str(stderr_path),
        },
        "existing_artifact_hashes": _hash_existing_files(job_out_dir),
    }


def write_control_metadata_csv(path: Path, job_records: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CONTROL_METADATA_FIELDNAMES))
        writer.writeheader()
        for record in job_records:
            writer.writerow({name: record[name] for name in CONTROL_METADATA_FIELDNAMES})


def build_campaign_manifest(
    *,
    campaign_run_id: str,
    generated_at_utc: str,
    query_timestamp_utc: str,
    source_commit: str,
    code_hashes: dict[str, str],
    dependency_closure_hashes: dict[str, str],
    cohort_payload_sha256: str,
    approval_envelope_sha256: str,
    approval_envelope_id: str,
    job_matrix_hash: str,
    job_records: list[dict[str, Any]],
    control_metadata_csv_path: Path,
) -> dict[str, Any]:
    availability_summary = {
        "total_jobs": len(job_records),
        STATUS_OK: sum(1 for record in job_records if record["terminal_status"] == STATUS_OK),
        STATUS_DATA_UNAVAILABLE: sum(
            1 for record in job_records if record["terminal_status"] == STATUS_DATA_UNAVAILABLE
        ),
        STATUS_SUBPROCESS_FAILED: sum(
            1 for record in job_records if record["terminal_status"] == STATUS_SUBPROCESS_FAILED
        ),
    }
    return {
        "campaign_run_id": campaign_run_id,
        "generated_at_utc": generated_at_utc,
        "query_timestamp_utc": query_timestamp_utc,
        "source_commit": source_commit,
        "frozen_dependency_closure_hashes": dependency_closure_hashes,
        **code_hashes,
        "cohort_payload_sha256": cohort_payload_sha256,
        "approval_envelope_sha256": approval_envelope_sha256,
        "approval_envelope_id": approval_envelope_id,
        "job_matrix_hash": job_matrix_hash,
        "mutable_data_provenance": {
            "queried_directly_by_coordinator": False,
            "note": (
                "The coordinator does not read market/candle data directly. "
                "Each job's candle source is owned entirely by the frozen V1 "
                "subprocess invoked once per job through the unmodified wrapper."
            ),
        },
        "availability_summary": availability_summary,
        "control_metadata_csv_path": str(control_metadata_csv_path),
        "jobs": job_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Coordinate the Breathline V1 recovery Arm A + B.2a campaign."
    )
    parser.add_argument("--cohort-payload", required=True)
    parser.add_argument("--approval-envelope", required=True)
    parser.add_argument("--campaign-out-dir", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually run the campaign. Omitted: validate cohort and print the matrix only.",
    )
    args = parser.parse_args()

    payload_path = Path(args.cohort_payload)
    envelope_path = Path(args.approval_envelope)
    campaign_out_dir = Path(args.campaign_out_dir)

    print(
        f"STARTED runner=breathline_v1_recovery_campaign_v1 execute={args.execute} "
        f"cohort_payload={payload_path} approval_envelope={envelope_path}",
        flush=True,
    )

    try:
        payload, envelope = resolve_approved_cohort(payload_path, envelope_path)
    except CohortManifestError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    print(f"PHASE cohort_resolved cohort_payload_sha256={payload.payload_sha256}", flush=True)

    jobs = build_campaign_jobs(payload)
    job_matrix_hash = compute_job_matrix_hash(jobs)
    print(
        f"PHASE matrix_built job_count={len(jobs)} job_matrix_hash={job_matrix_hash}",
        flush=True,
    )

    if not args.execute:
        print(
            f"FINISHED mode=dry_run job_count={len(jobs)} "
            f"cohort_payload_sha256={payload.payload_sha256} job_matrix_hash={job_matrix_hash}",
            flush=True,
        )
        return 0

    repo_root = find_repo_root()
    try:
        source_commit = resolve_git_commit(repo_root)
        verify_clean_worktree(repo_root)
        dependency_closure_hashes = closure_hashes(repo_root)
        code_hashes = resolve_code_hashes(repo_root)
    except RuntimeError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    if campaign_out_dir.exists():
        print(
            f"FAILED campaign output root already exists, refusing to overwrite: {campaign_out_dir}",
            flush=True,
        )
        return 1

    started_at = utc_now()
    campaign_run_id = f"breathline_v1_recovery_campaign_{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    query_timestamp_utc = iso(started_at)
    jobs_dir = campaign_out_dir / "jobs"
    jobs_dir.mkdir(parents=True)

    approval_envelope_sha256 = sha256_file(envelope_path)

    print("PHASE job_execution_start", flush=True)
    job_records: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        print(
            f"PHASE job_start index={index} total={len(jobs)} job_id={job.job_id}",
            flush=True,
        )
        try:
            record = run_job(job, repo_root=repo_root, jobs_dir=jobs_dir)
        except RuntimeError as exc:
            print(f"FAILED {exc}", flush=True)
            return 1
        job_records.append(record)
        print(
            f"PHASE job_end index={index} total={len(jobs)} job_id={job.job_id} "
            f"terminal_status={record['terminal_status']}",
            flush=True,
        )

    control_metadata_csv_path = (
        campaign_out_dir / f"breathline_v1_recovery_control_metadata_{campaign_run_id}.csv"
    )
    write_control_metadata_csv(control_metadata_csv_path, job_records)

    manifest = build_campaign_manifest(
        campaign_run_id=campaign_run_id,
        generated_at_utc=iso(utc_now()),
        query_timestamp_utc=query_timestamp_utc,
        source_commit=source_commit,
        code_hashes=code_hashes,
        dependency_closure_hashes=dependency_closure_hashes,
        cohort_payload_sha256=payload.payload_sha256,
        approval_envelope_sha256=approval_envelope_sha256,
        approval_envelope_id=envelope.envelope_id,
        job_matrix_hash=job_matrix_hash,
        job_records=job_records,
        control_metadata_csv_path=control_metadata_csv_path,
    )
    manifest_path = (
        campaign_out_dir / f"breathline_v1_recovery_campaign_manifest_{campaign_run_id}.json"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    availability_summary = manifest["availability_summary"]
    print(
        f"FINISHED campaign_run_id={campaign_run_id} job_count={len(jobs)} "
        f"ok={availability_summary[STATUS_OK]} "
        f"data_unavailable={availability_summary[STATUS_DATA_UNAVAILABLE]} "
        f"subprocess_failed={availability_summary[STATUS_SUBPROCESS_FAILED]}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
