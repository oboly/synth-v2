from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.breathline_v1_recovery_cohort_manifest_v1 import (
    APPROVAL_STATUS_APPROVED,
    V1_CHECKPOINT_RATIOS,
    V1_CYCLE_DAYS,
    V1_OFFSET_GRID,
    canonical_payload_bytes,
    compute_payload_sha256,
    envelope_filename,
    payload_filename,
)
from src.research.run_breathline_v1_recovery_campaign_v1 import (
    CODE_PROVENANCE_FILES,
    STATUS_DATA_UNAVAILABLE,
    STATUS_OK,
    STATUS_SUBPROCESS_FAILED,
    WRAPPER_MODULE,
    main,
)
from src.research.run_breathline_v1_recovery_orchestration_v1 import DEPENDENCY_CLOSURE_FILES

FAKE_COMMIT = "abc123def456"


def write_payload_file(tmp_path: Path, fields: dict) -> Path:
    payload_sha256 = compute_payload_sha256(fields)
    path = tmp_path / payload_filename(payload_sha256)
    path.write_bytes(canonical_payload_bytes(fields))
    return path


def write_envelope_file(tmp_path: Path, *, envelope_id: str, cohort_payload_sha256: str) -> Path:
    fields = {
        "envelope_id": envelope_id,
        "cohort_payload_sha256": cohort_payload_sha256,
        "approval_status": APPROVAL_STATUS_APPROVED,
        "approved_by": "unit-test",
        "approved_at_utc": "2025-01-01T00:00:00Z",
    }
    path = tmp_path / envelope_filename(envelope_id)
    path.write_text(json.dumps(fields, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def write_one_symbol_one_anchor_cohort(tmp_path: Path) -> tuple[Path, Path]:
    fields = {
        "canonical_symbols": ["BTC"],
        "canonical_base_anchors": ["2025-01-15"],
        "checkpoint_ratios": list(V1_CHECKPOINT_RATIOS),
        "cycle_days": V1_CYCLE_DAYS,
        "offset_grid": list(V1_OFFSET_GRID),
        "cohort_source": {"note": "synthetic test fixture"},
    }
    payload_path = write_payload_file(tmp_path, fields)
    payload_sha256 = compute_payload_sha256(fields)
    envelope_path = write_envelope_file(
        tmp_path, envelope_id="env-1", cohort_payload_sha256=payload_sha256
    )
    return payload_path, envelope_path


def make_head_bytes() -> dict[str, bytes]:
    paths = set(DEPENDENCY_CLOSURE_FILES) | set(CODE_PROVENANCE_FILES.values())
    return {path: f"# frozen bytes for {path}\n".encode("utf-8") for path in paths}


def make_wrapper_handler(
    *,
    job_scenarios: dict[str, str] | None = None,
    default_scenario: str = STATUS_OK,
    calls: list[list[str]] | None = None,
):
    job_scenarios = job_scenarios or {}

    def handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if calls is not None:
            calls.append(cmd)
        symbol = cmd[cmd.index("--symbol") + 1]
        arm_id = cmd[cmd.index("--arm-id") + 1]
        out_dir = Path(cmd[cmd.index("--out-dir") + 1])
        run_id_prefix = cmd[cmd.index("--run-id-prefix") + 1]

        control_id = out_dir.name.split(f"{arm_id}_", 1)[1].rsplit(f"_{symbol}_", 1)[0]
        scenario = job_scenarios.get(control_id, default_scenario)

        if scenario == STATUS_SUBPROCESS_FAILED:
            partial_dir = out_dir / f"{run_id_prefix}_partial_run" / "raw"
            partial_dir.mkdir(parents=True, exist_ok=True)
            (partial_dir / "partial.txt").write_text(
                "partial output written before failure\n", encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"")

        run_id = f"{run_id_prefix}_20250101T000000Z_{symbol.lower()}"
        run_dir = out_dir / run_id
        (run_dir / "raw").mkdir(parents=True, exist_ok=True)
        (run_dir / "derived").mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "raw" / "raw.csv").write_text(f"status,symbol\nOK,{symbol}\n", encoding="utf-8")
        (run_dir / "raw" / "raw.jsonl").write_text("{}\n", encoding="utf-8")
        manifest = {
            "run_id": run_id,
            "arm_id": arm_id,
            "symbol": symbol,
            "command_line": [
                sys.executable,
                "-m",
                "src.research.backtest_breath_curve_partial_to_full_v1",
                "--symbols",
                symbol,
                "--anchors",
                cmd[cmd.index("--anchor") + 1],
                "--out-dir",
                str(run_dir / "raw"),
            ],
            "availability_summary": {"availability_status": scenario},
        }
        manifest_path = run_dir / "manifest" / f"breathline_v1_recovery_manifest_{run_id}.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    return handler


def make_coordinator_git_runner(
    head_bytes: dict[str, bytes],
    *,
    clean_worktree: bool = True,
    wrapper_handler=None,
):
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if cmd == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{FAKE_COMMIT}\n".encode(), stderr=b"")
        if cmd == ["git", "status", "--porcelain"]:
            dirty_output = b"" if clean_worktree else b" M some/dirty/file.py\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=dirty_output, stderr=b"")
        if cmd[:2] == ["git", "show"]:
            relative_path = cmd[2].split("HEAD:", 1)[1]
            data = head_bytes.get(relative_path)
            if data is None:
                return subprocess.CompletedProcess(
                    cmd, 1, stdout=b"", stderr=b"fatal: path does not exist in HEAD"
                )
            return subprocess.CompletedProcess(cmd, 0, stdout=data, stderr=b"")
        if wrapper_handler is not None and cmd[:2] == [sys.executable, "-m"] and cmd[2] == WRAPPER_MODULE:
            return wrapper_handler(cmd, **kwargs)
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    return fake_run


def run_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    campaign_out_dir: Path,
    execute: bool,
    clean_worktree: bool = True,
    wrapper_handler=None,
    calls: list[list[str]] | None = None,
) -> int:
    payload_path, envelope_path = write_one_symbol_one_anchor_cohort(tmp_path)
    head_bytes = make_head_bytes()
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_campaign_v1.subprocess.run",
        make_coordinator_git_runner(
            head_bytes, clean_worktree=clean_worktree, wrapper_handler=wrapper_handler
        ),
    )
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_campaign_v1.find_repo_root",
        lambda: tmp_path / "repo",
    )
    argv = [
        "runner",
        "--cohort-payload",
        str(payload_path),
        "--approval-envelope",
        str(envelope_path),
        "--campaign-out-dir",
        str(campaign_out_dir),
    ]
    if execute:
        argv.append("--execute")
    monkeypatch.setattr(sys, "argv", argv)
    return main()


def test_dry_run_default_does_not_execute_or_create_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_out_dir = tmp_path / "campaign"
    result = run_main(tmp_path, monkeypatch, campaign_out_dir=campaign_out_dir, execute=False)
    assert result == 0
    assert not campaign_out_dir.exists()


def test_isolated_output_directory_per_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    campaign_out_dir = tmp_path / "campaign"
    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        wrapper_handler=make_wrapper_handler(),
    )
    assert result == 0
    job_dirs = list((campaign_out_dir / "jobs").iterdir())
    assert len(job_dirs) == 21  # 1 Arm A canonical + 20 B.2a controls
    assert len({path.name for path in job_dirs}) == 21


def test_existing_campaign_output_root_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    campaign_out_dir = tmp_path / "campaign"
    campaign_out_dir.mkdir(parents=True)
    (campaign_out_dir / "preexisting.txt").write_text("do not overwrite\n", encoding="utf-8")

    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        wrapper_handler=make_wrapper_handler(),
    )

    assert result == 1
    assert not (campaign_out_dir / "jobs").exists()
    assert (campaign_out_dir / "preexisting.txt").read_text(encoding="utf-8") == "do not overwrite\n"


def test_dirty_worktree_preflight_blocks_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_out_dir = tmp_path / "campaign"
    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        clean_worktree=False,
        wrapper_handler=make_wrapper_handler(),
    )
    assert result == 1
    assert not campaign_out_dir.exists()


def test_every_job_receives_exactly_one_terminal_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_out_dir = tmp_path / "campaign"
    scenarios = {
        "CANONICAL": STATUS_OK,
        "B2A_M10": STATUS_DATA_UNAVAILABLE,
        "B2A_P01": STATUS_SUBPROCESS_FAILED,
    }
    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        wrapper_handler=make_wrapper_handler(job_scenarios=scenarios),
    )
    assert result == 0

    manifest_path = next(campaign_out_dir.glob("breathline_v1_recovery_campaign_manifest_*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = manifest["jobs"]
    assert len(jobs) == 21
    job_ids = {job["job_id"] for job in jobs}
    assert len(job_ids) == 21  # no duplicates, every job appears exactly once
    for job in jobs:
        assert job["terminal_status"] in {STATUS_OK, STATUS_DATA_UNAVAILABLE, STATUS_SUBPROCESS_FAILED}

    by_control = {job["control_id"]: job for job in jobs}
    assert by_control["CANONICAL"]["terminal_status"] == STATUS_OK
    assert by_control["B2A_M10"]["terminal_status"] == STATUS_DATA_UNAVAILABLE
    assert by_control["B2A_P01"]["terminal_status"] == STATUS_SUBPROCESS_FAILED

    availability_summary = manifest["availability_summary"]
    assert availability_summary["total_jobs"] == 21
    assert availability_summary[STATUS_OK] == 19
    assert availability_summary[STATUS_DATA_UNAVAILABLE] == 1
    assert availability_summary[STATUS_SUBPROCESS_FAILED] == 1


def test_failed_subprocess_retains_available_artifacts_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_out_dir = tmp_path / "campaign"
    scenarios = {"B2A_P01": STATUS_SUBPROCESS_FAILED}
    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        wrapper_handler=make_wrapper_handler(job_scenarios=scenarios),
    )
    assert result == 0

    failed_job_dir = next(
        path for path in (campaign_out_dir / "jobs").iterdir() if "B2A_P01" in path.name
    )
    assert (failed_job_dir / "wrapper_stdout.txt").is_file()
    assert (failed_job_dir / "wrapper_stderr.txt").is_file()
    assert (failed_job_dir / "arm_b_partial_run" / "raw" / "partial.txt").is_file()
    assert (
        failed_job_dir / "arm_b_partial_run" / "raw" / "partial.txt"
    ).read_text(encoding="utf-8") == "partial output written before failure\n"


def test_only_existing_files_are_hashed_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_out_dir = tmp_path / "campaign"
    scenarios = {"B2A_P01": STATUS_SUBPROCESS_FAILED}
    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        wrapper_handler=make_wrapper_handler(job_scenarios=scenarios),
    )
    assert result == 0

    manifest_path = next(campaign_out_dir.glob("breathline_v1_recovery_campaign_manifest_*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failed_job = next(job for job in manifest["jobs"] if job["control_id"] == "B2A_P01")

    hashed_paths = set(failed_job["existing_artifact_hashes"])
    assert hashed_paths == {
        "wrapper_stdout.txt",
        "wrapper_stderr.txt",
        "arm_b_partial_run/raw/partial.txt",
    }
    # No manifest/derived/raw-run-dir artifacts exist for a job that failed
    # before the wrapper produced any of them; nothing fabricated for them.
    assert not any("manifest" in path for path in hashed_paths)
    assert failed_job["wrapper_manifest_path"] is None
    assert failed_job["frozen_v1_subprocess_command_line"] is None


def test_campaign_manifest_contains_required_provenance_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_out_dir = tmp_path / "campaign"
    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        wrapper_handler=make_wrapper_handler(),
    )
    assert result == 0

    manifest_path = next(campaign_out_dir.glob("breathline_v1_recovery_campaign_manifest_*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    required_fields = {
        "source_commit",
        "frozen_dependency_closure_hashes",
        "wrapper_sha256",
        "coordinator_sha256",
        "campaign_matrix_module_sha256",
        "cohort_manifest_loader_sha256",
        "cohort_payload_sha256",
        "approval_envelope_sha256",
        "job_matrix_hash",
        "campaign_run_id",
        "query_timestamp_utc",
        "mutable_data_provenance",
        "availability_summary",
        "control_metadata_csv_path",
        "jobs",
    }
    assert required_fields.issubset(manifest)
    assert manifest["source_commit"] == FAKE_COMMIT
    assert set(manifest["frozen_dependency_closure_hashes"]) == set(DEPENDENCY_CLOSURE_FILES)
    assert Path(manifest["control_metadata_csv_path"]).is_file()

    for job in manifest["jobs"]:
        assert "wrapper_command_line" in job
        assert "frozen_v1_subprocess_command_line" in job
        assert "log_paths" in job
        assert "existing_artifact_hashes" in job


def test_code_hashes_resolve_from_git_head_bytes_not_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_out_dir = tmp_path / "campaign"
    repo_root = tmp_path / "repo"

    # Deliberately write different bytes on disk than what `git show HEAD:...`
    # will return for the coordinator's own source file. The clean-worktree
    # preflight is faked to pass regardless (git status is mocked), isolating
    # this test to: does hashing read from the git object store, not disk?
    coordinator_relative_path = CODE_PROVENANCE_FILES["coordinator_sha256"]
    working_tree_path = repo_root / coordinator_relative_path
    working_tree_path.parent.mkdir(parents=True, exist_ok=True)
    working_tree_path.write_bytes(b"this is NOT the committed HEAD content\n")

    result = run_main(
        tmp_path,
        monkeypatch,
        campaign_out_dir=campaign_out_dir,
        execute=True,
        wrapper_handler=make_wrapper_handler(),
    )
    assert result == 0

    manifest_path = next(campaign_out_dir.glob("breathline_v1_recovery_campaign_manifest_*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    head_bytes = make_head_bytes()
    expected_hash = __import__("hashlib").sha256(head_bytes[coordinator_relative_path]).hexdigest()
    working_tree_hash = __import__("hashlib").sha256(working_tree_path.read_bytes()).hexdigest()

    assert manifest["coordinator_sha256"] == expected_hash
    assert manifest["coordinator_sha256"] != working_tree_hash


def test_no_forbidden_imports_in_new_modules() -> None:
    forbidden_substrings = (
        "src.selection",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.regime",
        "src.ui_chart",
    )
    new_module_paths = (
        PROJECT_ROOT / "src/research/breathline_v1_recovery_cohort_manifest_v1.py",
        PROJECT_ROOT / "src/research/breathline_v1_recovery_campaign_matrix_v1.py",
        PROJECT_ROOT / "src/research/run_breathline_v1_recovery_campaign_v1.py",
    )
    for module_path in new_module_paths:
        source_text = module_path.read_text(encoding="utf-8")
        import_lines = [line for line in source_text.splitlines() if "import" in line]
        for forbidden in forbidden_substrings:
            assert not any(forbidden in line for line in import_lines), (
                f"{module_path} imports forbidden module reference: {forbidden}"
            )
        assert "import broker" not in source_text
        assert "broker." not in source_text
        assert "INSERT INTO" not in source_text
        assert "UPDATE " not in source_text
        assert "cursor.execute" not in source_text
