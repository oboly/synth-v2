from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.run_breathline_v1_recovery_orchestration_v1 import (
    DEPENDENCY_CLOSURE_FILES,
    EXPECTED_OFFSET_COUNT,
    FLATTENED_FIELDNAMES,
    V1_MODULE,
    closure_hashes,
    main,
    parse_jsonl,
    flatten_rows,
    sha256_text,
)


OFFSETS = [-10.5, -7.0, -5.0, -3.0, 0.0, 3.0, 5.0, 7.0, 10.5]
FAKE_GIT_COMMIT = "abc123def456"


def make_ok_row(
    *,
    selected_offset: float = 0.0,
    notes: list[str] | None = None,
    selected_marker_matched: bool | None = None,
    selected_future_target_is_future: bool | None = None,
) -> dict[str, object]:
    selected_notes = notes or []
    partials = []
    for offset in OFFSETS:
        marker_matched = offset == selected_offset and "REQUIRED_RATIO_NOT_DUE" not in selected_notes
        if offset == selected_offset and selected_marker_matched is not None:
            marker_matched = selected_marker_matched
        future_target_is_future = offset != 10.5
        if offset == selected_offset and selected_future_target_is_future is not None:
            future_target_is_future = selected_future_target_is_future
        partials.append(
            {
                "ranking_score": 0.75 if offset == selected_offset else 0.25,
                "future_target_is_future": future_target_is_future,
                "result": {
                    "symbol": "BTC",
                    "anchor_ts_utc": "2025-01-01T00:00:00Z",
                    "as_of_ts_utc": "2025-01-14T00:00:00Z",
                    "phase_offset_days": offset,
                    "partial_match_score": 0.75 if offset == selected_offset else 0.25,
                    "required_ratio": 0.618,
                    "due_marker_count": 4,
                    "observed_marker_count": 3,
                    "notes": selected_notes if offset == selected_offset else [],
                    "markers": [
                        {"ratio": 0.618, "matched": marker_matched},
                    ],
                },
            }
        )
    return {
        "status": "OK",
        "symbol": "BTC",
        "anchor_ts_utc": "2025-01-01T00:00:00Z",
        "checkpoint_ratio": 0.618,
        "selected_partial_offset_days": selected_offset,
        "all_partial_offsets": partials,
    }


def make_error_row(*, checkpoint_ratio: float = 0.786, error: str = "source candles unavailable") -> dict[str, object]:
    return {
        "status": "ERROR",
        "symbol": "BTC",
        "anchor_ts_utc": "2025-01-01T00:00:00Z",
        "checkpoint_ratio": checkpoint_ratio,
        "error": error,
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_v1_outputs(raw_dir: Path, rows: list[dict[str, object]]) -> tuple[Path, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_path = raw_dir / "breath_curve_partial_to_full_v1_20250101T000000Z.csv"
    jsonl_path = raw_dir / "breath_curve_partial_to_full_v1_20250101T000000Z.jsonl"
    csv_path.write_text("status,symbol\nOK,BTC\n", encoding="utf-8")
    write_jsonl(jsonl_path, rows)
    return csv_path, jsonl_path


def fake_completed_process(returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["python"], returncode=returncode)


def build_fake_dependency_repo(
    repo_root: Path,
    *,
    working_tree_overrides: dict[str, bytes] | None = None,
    missing_paths: set[str] | None = None,
) -> dict[str, bytes]:
    committed_bytes = {
        relative_path: f"frozen:{relative_path}\n".encode("utf-8")
        for relative_path in DEPENDENCY_CLOSURE_FILES
    }
    overrides = working_tree_overrides or {}
    missing = missing_paths or set()
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / ".git").write_text("gitdir: /tmp/fake-worktree\n", encoding="utf-8")
    for relative_path, committed in committed_bytes.items():
        if relative_path in missing:
            continue
        file_path = repo_root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(overrides.get(relative_path, committed))
    return committed_bytes


def make_fake_subprocess_run(
    repo_root: Path,
    committed_bytes: dict[str, bytes],
    *,
    rows: list[dict[str, object]] | None = None,
    v1_returncode: int = 0,
    calls: list[list[str]] | None = None,
):
    def fake_run(cmd: list[str], **kwargs: object):
        if calls is not None:
            calls.append(cmd)
        if cmd == ["git", "rev-parse", "HEAD"]:
            assert kwargs["cwd"] == str(repo_root)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=f"{FAKE_GIT_COMMIT}\n".encode("utf-8"),
                stderr=b"",
            )
        if cmd[:2] == ["git", "show"]:
            assert kwargs["cwd"] == str(repo_root)
            relative_path = cmd[2].removeprefix("HEAD:")
            data = committed_bytes.get(relative_path)
            if data is None:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=1,
                    stdout=b"",
                    stderr=b"fatal: path does not exist in HEAD",
                )
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=data,
                stderr=b"",
            )
        assert cmd[:3] == [sys.executable, "-m", V1_MODULE]
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, rows or [make_ok_row()])
        return fake_completed_process(returncode=v1_returncode)

    return fake_run


def make_dependency_head_bytes() -> dict[str, bytes]:
    return {
        relative_path: f"# frozen bytes for {relative_path}\n".encode("utf-8")
        for relative_path in DEPENDENCY_CLOSURE_FILES
    }


def write_dependency_worktree(
    repo_root: Path,
    head_bytes: dict[str, bytes],
    *,
    modified_path: str | None = None,
    missing_path: str | None = None,
) -> None:
    for relative_path, data in head_bytes.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == missing_path:
            continue
        if relative_path == modified_path:
            path.write_bytes(data + b"# modified\n")
            continue
        path.write_bytes(data)


def make_git_runner(
    head_bytes: dict[str, bytes],
    *,
    v1_handler: callable | None = None,
) -> callable:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
        if cmd == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"abc123def456\n", stderr=b"")
        if cmd[:2] == ["git", "show"]:
            relative_path = cmd[2].split("HEAD:", 1)[1]
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=head_bytes[relative_path],
                stderr=b"",
            )
        if v1_handler is not None:
            return v1_handler(cmd, **kwargs)
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    return fake_run


def test_parse_jsonl_requires_nine_offsets(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "sample.jsonl"
    bad_row = make_ok_row()
    bad_row["all_partial_offsets"] = bad_row["all_partial_offsets"][:3]
    write_jsonl(jsonl_path, [bad_row])

    with pytest.raises(RuntimeError, match="expected 9 all_partial_offsets, got 3"):
        parse_jsonl(jsonl_path)


def test_closure_hashes_include_all_four_frozen_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(tmp_path, head_bytes)
    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes))

    hashes = closure_hashes(tmp_path)

    assert tuple(hashes) == DEPENDENCY_CLOSURE_FILES
    assert set(hashes) == {
        "src/research/backtest_breath_curve_partial_to_full_v1.py",
        "src/market_context/breath_curve_core_v1.py",
        "src/research/breath_curve_template_matcher_v1.py",
        "src/research/run_breath_curve_template_partial_v1.py",
    }
    assert hashes == {
        relative_path: __import__("hashlib").sha256(data).hexdigest()
        for relative_path, data in head_bytes.items()
    }


def test_flatten_rows_keeps_directly_traceable_fields() -> None:
    rows = [make_ok_row(selected_offset=0.0, notes=["INSUFFICIENT_DUE_MARKERS"])]
    flattened = flatten_rows(
        rows,
        run_id="run123",
        source_jsonl_path="/tmp/raw.jsonl",
        source_jsonl_sha256="abc123",
    )

    assert len(flattened) == EXPECTED_OFFSET_COUNT
    assert set(flattened[0]) == set(FLATTENED_FIELDNAMES)

    selected = [row for row in flattened if row["selected_by_v1"]]
    assert len(selected) == 1
    assert selected[0]["phase_offset_days"] == 0.0
    assert selected[0]["required_marker_due"] is True
    assert selected[0]["required_marker_matched"] is True
    assert selected[0]["min_due_markers_met"] is False
    assert selected[0]["structurally_eligible"] is False
    assert json.loads(selected[0]["score_zero_reason"]) == ["INSUFFICIENT_DUE_MARKERS"]
    assert json.loads(selected[0]["notes_json"]) == ["INSUFFICIENT_DUE_MARKERS"]


def test_flatten_rows_derives_structurally_eligible_true_and_false() -> None:
    rows = [
        make_ok_row(selected_offset=0.0),
        make_ok_row(selected_offset=10.5),
    ]

    flattened = flatten_rows(
        rows,
        run_id="run123",
        source_jsonl_path="/tmp/raw.jsonl",
        source_jsonl_sha256="abc123",
    )

    selected = [row for row in flattened if row["selected_by_v1"]]
    assert len(selected) == 2
    assert selected[0]["structurally_eligible"] is True
    assert selected[1]["future_target_is_future"] is False
    assert selected[1]["structurally_eligible"] is False
    assert json.loads(selected[1]["score_zero_reason"]) == []


def test_flatten_rows_appends_derivation_conflict_for_required_marker_contradictions() -> None:
    rows = [
        make_ok_row(
            selected_offset=0.0,
            notes=["REQUIRED_RATIO_NOT_MATCHED"],
            selected_marker_matched=True,
        ),
        make_ok_row(
            selected_offset=3.0,
            selected_marker_matched=False,
        ),
    ]

    flattened = flatten_rows(
        rows,
        run_id="run123",
        source_jsonl_path="/tmp/raw.jsonl",
        source_jsonl_sha256="abc123",
    )

    selected = [row for row in flattened if row["selected_by_v1"]]
    assert len(selected) == 2
    assert json.loads(selected[0]["score_zero_reason"]) == [
        "REQUIRED_RATIO_NOT_MATCHED",
        "DERIVATION_CONFLICT",
    ]
    assert json.loads(selected[1]["score_zero_reason"]) == ["DERIVATION_CONFLICT"]


def test_flatten_rows_does_not_treat_required_ratio_not_due_as_conflict() -> None:
    rows = [
        make_ok_row(
            selected_offset=0.0,
            notes=["REQUIRED_RATIO_NOT_DUE"],
            selected_marker_matched=False,
        )
    ]

    flattened = flatten_rows(
        rows,
        run_id="run123",
        source_jsonl_path="/tmp/raw.jsonl",
        source_jsonl_sha256="abc123",
    )

    selected = [row for row in flattened if row["selected_by_v1"]]
    assert len(selected) == 1
    assert selected[0]["required_marker_due"] is False
    assert selected[0]["structurally_eligible"] is False
    assert json.loads(selected[0]["score_zero_reason"]) == ["REQUIRED_RATIO_NOT_DUE"]


def test_main_smoke_writes_only_expected_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == [sys.executable, "-m", V1_MODULE]
        assert cmd[3:7] == ["--symbols", "BTC", "--anchors", "2025-01-01"]
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, [make_ok_row()])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--symbol", "BTC", "--anchor", "2025-01-01", "--out-dir", str(out_dir)],
    )

    assert main() == 0

    run_dirs = list(out_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert sorted(path.name for path in run_dir.iterdir()) == ["derived", "logs", "manifest", "raw"]

    raw_csv, raw_jsonl = write_v1_outputs(tmp_path / "expected_raw", [make_ok_row()])
    actual_raw_dir = run_dir / "raw"
    assert (actual_raw_dir / raw_csv.name).read_bytes() == raw_csv.read_bytes()
    assert (actual_raw_dir / raw_jsonl.name).read_bytes() == raw_jsonl.read_bytes()

    derived_paths = list((run_dir / "derived").glob("*.csv"))
    manifest_paths = list((run_dir / "manifest").glob("*.json"))
    log_paths = sorted(path.name for path in (run_dir / "logs").iterdir())
    assert len(derived_paths) == 1
    assert len(manifest_paths) == 1
    assert log_paths == ["v1_stderr.txt", "v1_stdout.txt"]

    with derived_paths[0].open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        flattened = list(reader)
    assert len(flattened) == EXPECTED_OFFSET_COUNT
    assert reader.fieldnames is not None
    assert "future_target_is_future" in reader.fieldnames
    assert "target_is_future" not in reader.fieldnames

    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["arm_id"] == "ARM_A"
    assert manifest["symbol"] == "BTC"
    assert manifest["anchor"] == "2025-01-01"
    assert manifest["orchestration_runner_commit"] == FAKE_GIT_COMMIT
    assert manifest["source_commit"] == FAKE_GIT_COMMIT
    assert manifest["symbols_sha256"] == sha256_text("BTC")
    assert manifest["anchor_set_sha256"] == sha256_text("2025-01-01")
    assert manifest["flattened_artifacts"]["csv"]["rows"] == EXPECTED_OFFSET_COUNT
    assert set(manifest["dependency_closure_hashes"]) == set(DEPENDENCY_CLOSURE_FILES)
    assert manifest["dependency_closure_integrity_status"] == "PASS"
    assert manifest["availability_summary"]["availability_status"] == "OK"
    assert manifest["provenance"]["v1_module"] == V1_MODULE


def test_main_fails_when_subprocess_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        return fake_completed_process(returncode=1)

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--symbol", "BTC", "--anchor", "2025-01-01", "--out-dir", str(out_dir)],
    )

    assert main() == 1


def test_main_fails_when_v1_jsonl_is_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        bad_row = make_ok_row()
        bad_row["all_partial_offsets"] = bad_row["all_partial_offsets"][:2]
        write_v1_outputs(raw_dir, [bad_row])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--symbol", "BTC", "--anchor", "2025-01-01", "--out-dir", str(out_dir)],
    )

    assert main() == 1


def test_main_records_error_rows_as_manifest_data_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, [make_ok_row(), make_error_row(error="missing bounded candles")])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--symbol", "BTC", "--anchor", "2025-01-01", "--out-dir", str(out_dir)],
    )

    assert main() == 0

    run_dir = next(out_dir.iterdir())
    derived_path = next((run_dir / "derived").glob("*.csv"))
    manifest_path = next((run_dir / "manifest").glob("*.json"))

    with derived_path.open(newline="", encoding="utf-8") as handle:
        flattened = list(csv.DictReader(handle))
    assert len(flattened) == EXPECTED_OFFSET_COUNT

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["availability_summary"]["availability_status"] == "DATA_UNAVAILABLE"
    assert manifest["availability_summary"]["data_unavailable_row_count"] == 1
    assert manifest["availability_summary"]["evidence"] == [
        {
            "availability_status": "DATA_UNAVAILABLE",
            "source_jsonl_row_number": 2,
            "symbol": "BTC",
            "anchor_ts_utc": "2025-01-01T00:00:00Z",
            "checkpoint_ratio": 0.786,
            "raw_error_text": "missing bounded candles",
        }
    ]
    assert manifest["provenance"]["availability_status"] == "DATA_UNAVAILABLE"


@pytest.mark.parametrize(
    ("modified_path", "missing_path", "expected_message"),
    [
        (DEPENDENCY_CLOSURE_FILES[0], None, "frozen dependency changed"),
        (None, DEPENDENCY_CLOSURE_FILES[1], "frozen dependency missing"),
    ],
)
def test_main_fails_before_v1_subprocess_when_frozen_dependency_is_not_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    modified_path: str | None,
    missing_path: str | None,
    expected_message: str,
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(
        repo_root,
        head_bytes,
        modified_path=modified_path,
        missing_path=missing_path,
    )
    calls: list[list[str]] = []

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"v1 subprocess should not run: {cmd}")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return make_git_runner(head_bytes, v1_handler=v1_handler)(cmd, **kwargs)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--symbol", "BTC", "--anchor", "2025-01-01", "--out-dir", str(out_dir)],
    )

    assert main() == 1
    assert calls[0] == ["git", "rev-parse", "HEAD"]
    assert calls[1][0:2] == ["git", "show"]
    assert not out_dir.exists()
    captured = capsys.readouterr()
    assert expected_message in captured.out
    if modified_path is not None:
        assert modified_path in captured.out
    if missing_path is not None:
        assert missing_path in captured.out


def test_default_args_preserve_arm_a_run_id_and_arm_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, [make_ok_row()])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--symbol", "BTC", "--anchor", "2025-01-01", "--out-dir", str(out_dir)],
    )

    assert main() == 0

    run_dir = next(out_dir.iterdir())
    assert run_dir.name.startswith("arm_a_")
    manifest_path = next((run_dir / "manifest").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["arm_id"] == "ARM_A"
    assert manifest["run_id"].startswith("arm_a_")


def test_default_flattened_csv_schema_is_byte_identical_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, [make_ok_row()])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--symbol", "BTC", "--anchor", "2025-01-01", "--out-dir", str(out_dir)],
    )

    assert main() == 0

    run_dir = next(out_dir.iterdir())
    derived_path = next((run_dir / "derived").glob("*.csv"))
    header_line = derived_path.read_text(encoding="utf-8").splitlines()[0]
    assert header_line == ",".join(FLATTENED_FIELDNAMES)


def test_arm_b_and_arm_b_prefix_override_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, [make_ok_row()])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--symbol",
            "BTC",
            "--anchor",
            "2025-01-01",
            "--out-dir",
            str(out_dir),
            "--arm-id",
            "ARM_B",
            "--run-id-prefix",
            "arm_b",
        ],
    )

    assert main() == 0

    run_dir = next(out_dir.iterdir())
    assert run_dir.name.startswith("arm_b_")
    manifest_path = next((run_dir / "manifest").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["arm_id"] == "ARM_B"
    assert manifest["run_id"].startswith("arm_b_")

    derived_path = next((run_dir / "derived").glob("*.csv"))
    with derived_path.open(newline="", encoding="utf-8") as handle:
        flattened = list(csv.DictReader(handle))
    assert all(row["arm_id"] == "ARM_B" for row in flattened)


def test_metadata_args_do_not_alter_frozen_v1_subprocess_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)
    calls: list[list[str]] = []

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, [make_ok_row()])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--symbol",
            "BTC",
            "--anchor",
            "2025-01-01",
            "--out-dir",
            str(out_dir),
            "--arm-id",
            "ARM_B",
            "--run-id-prefix",
            "arm_b",
        ],
    )

    assert main() == 0
    assert len(calls) == 1
    v1_command = calls[0]
    assert v1_command[:3] == [sys.executable, "-m", V1_MODULE]
    assert "--arm-id" not in v1_command
    assert "--run-id-prefix" not in v1_command
    assert "ARM_B" not in v1_command
    assert "arm_b" not in v1_command
    assert v1_command[3:9] == [
        "--symbols",
        "BTC",
        "--anchors",
        "2025-01-01",
        "--out-dir",
        v1_command[8],
    ]


def test_wrapper_manifest_command_line_key_unchanged_and_holds_frozen_v1_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_dir = Path(cmd[8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(raw_dir, [make_ok_row()])
        return fake_completed_process()

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--symbol",
            "BTC",
            "--anchor",
            "2025-01-01",
            "--out-dir",
            str(out_dir),
            "--arm-id",
            "ARM_B",
            "--run-id-prefix",
            "arm_b",
        ],
    )

    assert main() == 0

    run_dir = next(out_dir.iterdir())
    manifest_path = next((run_dir / "manifest").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "command_line" in manifest
    assert "wrapper_command_line" not in manifest
    assert "frozen_v1_subprocess_command_line" not in manifest
    assert manifest["command_line"][:3] == [sys.executable, "-m", V1_MODULE]
    assert "--arm-id" not in manifest["command_line"]
    assert "--run-id-prefix" not in manifest["command_line"]
