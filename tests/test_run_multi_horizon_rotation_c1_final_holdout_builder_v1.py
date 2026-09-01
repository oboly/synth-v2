from __future__ import annotations

import json
import signal
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research.multi_horizon_rotation_dataset_builder_v1 import AssetCoverage, RotationV1PitIndex
from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS, Candle, CandidateResult
from src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 import (
    CANDIDATE_ID,
    PHASE,
    RunnerInterrupted,
    canonical_run_dir,
    checkpoint_path,
    load_checkpoint,
    load_manifest,
    main,
    mark_checkpoint_terminal,
    parse_args,
    reconcile_partial_to_checkpoint,
    select_c1_spec,
    validate_resume_checkpoint,
    write_checkpoint,
)


BASE = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)


def _manifest(*, end: str = "2026-09-01T02:00:00Z", holdout_end: str = "2026-08-22T06:30:00Z") -> dict[str, object]:
    return {
        "manifest_version": "1.0.0",
        "venue": "bitvavo",
        "source_span": {"start": "2026-07-13T22:00:00Z", "end": end},
        "splits": {
            "discovery": {"start": "2026-07-13T22:00:00Z", "end": "2026-08-12T10:00:00Z"},
            "validation": {"start": "2026-08-12T10:00:00Z", "end": "2026-08-22T06:00:00Z"},
            "final_holdout": {"start": "2026-08-22T06:00:00Z", "end": holdout_end},
        },
        "final_holdout_inspected": False,
    }


def _write_run_files(tmp_path: Path, *, manifest: dict[str, object] | None = None) -> tuple[Path, Path]:
    manifest_path = tmp_path / "split_manifest_v1.json"
    integrity_path = tmp_path / "source_integrity_v1.json"
    manifest_path.write_text(json.dumps(manifest or _manifest()), encoding="utf-8")
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    return manifest_path, integrity_path


# --- CLI / contract -----------------------------------------------------


def test_holdout_contract_is_c1_only() -> None:
    assert PHASE == "final_holdout"
    assert CANDIDATE_ID == "C1"
    spec = select_c1_spec()
    assert spec.candidate_id == "C1"


def test_cli_has_no_output_dir_override() -> None:
    args = parse_args(
        ["--split-manifest", "run/split_manifest_v1.json", "--source-integrity", "run/source_integrity_v1.json"]
    )
    assert not hasattr(args, "output_dir")
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--split-manifest",
                "run/split_manifest_v1.json",
                "--source-integrity",
                "run/source_integrity_v1.json",
                "--output-dir",
                "elsewhere",
            ]
        )


def test_manifest_must_be_unopened_and_match_venue(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = _manifest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = load_manifest(path, venue="bitvavo")
    assert loaded["final_holdout_inspected"] is False

    with pytest.raises(ValueError, match="venue"):
        load_manifest(path, venue="kraken")

    manifest["final_holdout_inspected"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unopened"):
        load_manifest(path, venue="bitvavo")


def test_manifest_requires_final_holdout_split(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = _manifest()
    del manifest["splits"]["final_holdout"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="missing final_holdout"):
        load_manifest(path, venue="bitvavo")


# --- Test 1/2: canonical directory binding, no alternate --output-dir --


def test_canonical_dir_is_the_manifest_directory(tmp_path: Path) -> None:
    manifest_path = tmp_path / "split_manifest_v1.json"
    integrity_path = tmp_path / "source_integrity_v1.json"
    manifest_path.write_text("{}", encoding="utf-8")
    integrity_path.write_text("{}", encoding="utf-8")
    assert canonical_run_dir(manifest_path, integrity_path) == tmp_path.resolve()


def test_canonical_dir_rejects_misnamed_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    integrity_path = tmp_path / "source_integrity_v1.json"
    manifest_path.write_text("{}", encoding="utf-8")
    integrity_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="split_manifest_v1.json"):
        canonical_run_dir(manifest_path, integrity_path)


def test_canonical_dir_rejects_alternate_directory_for_integrity_artifact(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "canonical_run"
    manifest_dir.mkdir()
    other_dir = tmp_path / "attacker_chosen_output_dir"
    other_dir.mkdir()
    manifest_path = manifest_dir / "split_manifest_v1.json"
    integrity_path = other_dir / "source_integrity_v1.json"
    manifest_path.write_text("{}", encoding="utf-8")
    integrity_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="same canonical run directory"):
        canonical_run_dir(manifest_path, integrity_path)


def test_no_output_dir_argument_means_alternate_directory_cannot_reopen_holdout(tmp_path: Path) -> None:
    """Regression for the Codex BLOCK: there is no way to point the runner at a
    second output location for the same frozen manifest, because the runner
    never accepts one."""
    manifest_path, integrity_path = _write_run_files(tmp_path)
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--split-manifest",
                str(manifest_path),
                "--source-integrity",
                str(integrity_path),
                "--output-dir",
                str(tmp_path / "somewhere_else"),
            ]
        )


# --- Fresh-run one-shot denial (tests 3 & 4) ----------------------------


def test_fresh_run_denied_when_running_checkpoint_marker_exists(tmp_path: Path) -> None:
    manifest_path, integrity_path = _write_run_files(tmp_path)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256="whatever",
        source_integrity_composite_sha256="whatever",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=None,
        asofs_completed=0,
        row_count=0,
        partial_bytes=0,
        source_query_count=0,
        source_rows_read=0,
        terminal_state="RUNNING",
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()

    exit_code = main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    checkpoint = load_checkpoint(cp_path)
    assert checkpoint["terminal_state"] == "RUNNING"


def test_fresh_run_denied_after_finished(tmp_path: Path) -> None:
    manifest_path, integrity_path = _write_run_files(tmp_path)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256="whatever",
        source_integrity_composite_sha256="whatever",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=BASE + timedelta(minutes=15),
        asofs_completed=2,
        row_count=2,
        partial_bytes=40,
        source_query_count=1,
        source_rows_read=10,
        terminal_state="FINISHED",
    )
    (tmp_path / "final_holdout_c1_rows_v1.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "final_holdout_c1_summary_v1.json").write_text("{}", encoding="utf-8")

    exit_code = main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    # never overwritten
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"


def test_resume_denied_when_checkpoint_or_partial_missing(tmp_path: Path) -> None:
    manifest_path, integrity_path = _write_run_files(tmp_path)
    exit_code = main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code == 1


def test_resume_denied_when_terminal_state_finished(tmp_path: Path) -> None:
    manifest_path, integrity_path = _write_run_files(tmp_path)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256="whatever",
        source_integrity_composite_sha256="whatever",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=BASE + timedelta(minutes=15),
        asofs_completed=2,
        row_count=2,
        partial_bytes=40,
        source_query_count=1,
        source_rows_read=10,
        terminal_state="FINISHED",
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").write_bytes(b"x" * 40)
    exit_code = main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code == 1


# --- Checkpoint identity / reconcile / grid validation ------------------


def test_validate_resume_checkpoint_rejects_every_identity_mismatch() -> None:
    base_kwargs = dict(
        venue="bitvavo",
        manifest_sha256="manifest-sha",
        source_integrity_composite_sha256="integrity-sha",
    )

    def _checkpoint(**overrides: object) -> dict[str, object]:
        payload = {
            "runner": "run_multi_horizon_rotation_c1_final_holdout_builder_v1",
            "runner_version": "1.0.0",
            "venue": "bitvavo",
            "candidate_id": "C1",
            "phase": "final_holdout",
            "manifest_sha256": "manifest-sha",
            "source_integrity_composite_sha256": "integrity-sha",
            "terminal_state": "RUNNING",
            "asofs_completed": 0,
            "row_count": 0,
            "partial_bytes": 0,
        }
        payload.update(overrides)
        return payload

    validate_resume_checkpoint(_checkpoint(), **base_kwargs)  # sanity: valid case passes

    with pytest.raises(ValueError, match="runner/version"):
        validate_resume_checkpoint(_checkpoint(runner="other"), **base_kwargs)
    with pytest.raises(ValueError, match="venue"):
        validate_resume_checkpoint(_checkpoint(venue="kraken"), **base_kwargs)
    with pytest.raises(ValueError, match="candidate_id"):
        validate_resume_checkpoint(_checkpoint(candidate_id="C2"), **base_kwargs)
    with pytest.raises(ValueError, match="phase"):
        validate_resume_checkpoint(_checkpoint(phase="validation"), **base_kwargs)
    with pytest.raises(ValueError, match="split manifest mismatch"):
        validate_resume_checkpoint(_checkpoint(manifest_sha256="drifted"), **base_kwargs)
    with pytest.raises(ValueError, match="source integrity mismatch"):
        validate_resume_checkpoint(_checkpoint(source_integrity_composite_sha256="drifted"), **base_kwargs)
    with pytest.raises(ValueError, match="not resumable"):
        validate_resume_checkpoint(_checkpoint(terminal_state="FINISHED"), **base_kwargs)
    with pytest.raises(ValueError, match="not resumable"):
        validate_resume_checkpoint(_checkpoint(terminal_state="FAILED"), **base_kwargs)


def test_reconcile_partial_truncates_uncommitted_bytes_and_checks_row_count(tmp_path: Path) -> None:
    committed = b'{"row":1}\n{"row":2}\n'
    uncommitted_tail = b'{"row":3'
    partial = tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial"
    partial.write_bytes(committed + uncommitted_tail)
    checkpoint = {"partial_bytes": len(committed), "row_count": 2}
    reconcile_partial_to_checkpoint(partial, checkpoint)
    assert partial.read_bytes() == committed

    bad_checkpoint = {"partial_bytes": len(committed), "row_count": 99}
    with pytest.raises(ValueError, match="row count mismatch"):
        reconcile_partial_to_checkpoint(partial, bad_checkpoint)


def test_interrupted_checkpoint_is_resumable_and_marks_terminal_state(tmp_path: Path) -> None:
    cp_path = tmp_path / "checkpoint.json"
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256="sha",
        source_integrity_composite_sha256="isha",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=BASE,
        asofs_completed=1,
        row_count=1,
        partial_bytes=10,
        source_query_count=1,
        source_rows_read=5,
        terminal_state="RUNNING",
    )
    mark_checkpoint_terminal(cp_path, terminal_state="INTERRUPTED")
    checkpoint = load_checkpoint(cp_path)
    assert checkpoint["terminal_state"] == "INTERRUPTED"
    assert checkpoint["row_count"] == 1
    validate_resume_checkpoint(
        checkpoint, venue="bitvavo", manifest_sha256="sha", source_integrity_composite_sha256="isha"
    )


# --- End-to-end runner harness (fresh, resume, denial, signals) --------


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def cursor(self):
        return _FakeCursor()

    def close(self) -> None:
        pass


def _install_fake_pipeline(monkeypatch: pytest.MonkeyPatch, module: object, *, phase_start: datetime) -> None:
    """Stub every DB-touching function so main() can run end-to-end deterministically."""

    def fake_get_db_connection() -> _FakeConnection:
        return _FakeConnection()

    def fake_build_integrity_payload(conn, *, venue, split_manifest):
        return {"composite_sha256": "fixed"}

    def fake_verify_existing(path: Path, payload: dict) -> None:
        existing = json.loads(Path(path).read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("canonical source content drifted from frozen integrity artifact")

    def fake_fetch_asset_coverage(conn, *, venue, through_ts=None):
        return [AssetCoverage(asset_id=1, first_close_ts=phase_start - timedelta(days=1), last_close_ts=through_ts)]

    def fake_fetch_rotation_v1_points(conn, *, venue, through_ts):
        return RotationV1PitIndex({})

    def fake_fetch_candles_for_chunk(conn, *, venue, chunk_asofs, phase_end):
        candles = {
            1: [
                Candle(close_ts_utc=asof, close_price=Decimal("100"), volume_base=Decimal("1"))
                for asof in chunk_asofs
            ]
        }
        closes = {1: {asof: Decimal("100") for asof in chunk_asofs}}
        return candles, closes, len(chunk_asofs)

    def fake_evaluate_candidate(*, candles_by_asset, asof_ts, spec, venue):
        results = []
        for asset_id in candles_by_asset:
            results.append(
                CandidateResult(
                    venue=venue,
                    asset_id=asset_id,
                    candidate_id=spec.candidate_id,
                    model_id="multi_horizon_rotation_relative_flow",
                    model_version=spec.model_version,
                    input_interval="15m",
                    lookback_horizon=spec.lookback_horizon,
                    effective_horizon=spec.effective_horizon,
                    observed_lifecycle="UNMEASURED",
                    asof_ts=asof_ts,
                    freshness="FRESH",
                    provenance="test",
                    cohort_size=1,
                    relative_return_unit=Decimal("0.1"),
                    signed_flow_unit=Decimal("0.1"),
                    relative_acceleration_unit=Decimal("0.1"),
                    rotation_score=Decimal("1.0"),
                    data_quality="COMPLETE",
                    reason="OK",
                )
            )
        return results

    monkeypatch.setattr(module, "get_db_connection", fake_get_db_connection)
    monkeypatch.setattr(module, "build_integrity_payload", fake_build_integrity_payload)
    monkeypatch.setattr(module, "verify_existing", fake_verify_existing)
    monkeypatch.setattr(module, "fetch_asset_coverage", fake_fetch_asset_coverage)
    monkeypatch.setattr(module, "fetch_rotation_v1_points", fake_fetch_rotation_v1_points)
    monkeypatch.setattr(module, "fetch_candles_for_chunk", fake_fetch_candles_for_chunk)
    monkeypatch.setattr(module, "evaluate_candidate", fake_evaluate_candidate)


def _two_asof_manifest() -> dict[str, object]:
    return _manifest(holdout_end="2026-08-22T06:30:00Z")


def test_fresh_run_completes_and_publishes_exactly_one_canonical_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 0

    artifact = tmp_path / "final_holdout_c1_rows_v1.jsonl"
    summary = tmp_path / "final_holdout_c1_summary_v1.json"
    cp_path = checkpoint_path(tmp_path)
    assert artifact.exists()
    assert summary.exists()
    lines = artifact.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        assert json.loads(line)["candidate_id"] == "C1"
    checkpoint = load_checkpoint(cp_path)
    assert checkpoint["terminal_state"] == "FINISHED"
    assert checkpoint["row_count"] == 2
    assert checkpoint["manifest_sha256"]
    assert checkpoint["source_integrity_composite_sha256"] == "fixed"

    # Test 4: a second fresh invocation is denied after FINISHED.
    exit_code_again = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code_again == 1
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"
    assert len(artifact.read_text(encoding="utf-8").splitlines()) == 2


def test_sigint_interrupts_cleanly_and_resume_completes_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    calls = {"n": 0}
    real_write_row = module.write_row

    def interrupting_write_row(handle, row):
        calls["n"] += 1
        real_write_row(handle, row)
        if calls["n"] == 1:
            raise RunnerInterrupted(signal.SIGINT)

    monkeypatch.setattr(module, "write_row", interrupting_write_row)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 130
    out = capsys.readouterr().out
    interrupted_lines = [line for line in out.splitlines() if line.startswith("INTERRUPTED")]
    assert len(interrupted_lines) == 1
    assert not any(line.startswith("FINISHED runner=") for line in out.splitlines())
    assert "Traceback" not in out

    cp_path = checkpoint_path(tmp_path)
    checkpoint = load_checkpoint(cp_path)
    assert checkpoint["terminal_state"] == "INTERRUPTED"
    assert checkpoint["asofs_completed"] == 0
    assert checkpoint["row_count"] == 0

    partial = tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial"
    assert partial.exists()

    # Resume with the interruption cleared: continue past the failure point.
    monkeypatch.setattr(module, "write_row", real_write_row)
    exit_code_resumed = module.main(
        [
            "--split-manifest",
            str(manifest_path),
            "--source-integrity",
            str(integrity_path),
            "--resume",
        ]
    )
    assert exit_code_resumed == 0
    artifact = tmp_path / "final_holdout_c1_rows_v1.jsonl"
    lines = artifact.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    asofs = sorted(json.loads(line)["asof_ts"] for line in lines)
    assert len(set(asofs)) == 2
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"


def test_sigterm_interrupts_cleanly_with_exit_143(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    def raising_evaluate_candidate(*args, **kwargs):
        raise RunnerInterrupted(signal.SIGTERM)

    monkeypatch.setattr(module, "evaluate_candidate", raising_evaluate_candidate)

    sigint_before = signal.getsignal(signal.SIGINT)
    sigterm_before = signal.getsignal(signal.SIGTERM)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 143
    out = capsys.readouterr().out
    interrupted_lines = [line for line in out.splitlines() if line.startswith("INTERRUPTED")]
    assert len(interrupted_lines) == 1
    assert not any(line.startswith("FINISHED runner=") for line in out.splitlines())
    assert "Traceback" not in out

    cp_path = checkpoint_path(tmp_path)
    checkpoint = load_checkpoint(cp_path)
    assert checkpoint["terminal_state"] == "INTERRUPTED"

    # Previous signal handlers must be restored, not left pointing at the runner's.
    assert signal.getsignal(signal.SIGINT) == sigint_before
    assert signal.getsignal(signal.SIGTERM) == sigterm_before


def test_source_integrity_mismatch_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "stale"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not checkpoint_path(tmp_path).exists()


def test_resume_reverifies_source_integrity_before_continuing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    calls = {"n": 0}
    real_write_row = module.write_row

    def interrupting_write_row(handle, row):
        calls["n"] += 1
        real_write_row(handle, row)
        if calls["n"] == 1:
            raise RunnerInterrupted(signal.SIGINT)

    monkeypatch.setattr(module, "write_row", interrupting_write_row)
    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 130
    monkeypatch.setattr(module, "write_row", real_write_row)

    # Drift the frozen integrity artifact before resume; recompute always returns
    # "fixed" from the fake pipeline, so a stale artifact must be caught again.
    integrity_path.write_text(json.dumps({"composite_sha256": "drifted"}), encoding="utf-8")
    exit_code_resumed = module.main(
        [
            "--split-manifest",
            str(manifest_path),
            "--source-integrity",
            str(integrity_path),
            "--resume",
        ]
    )
    assert exit_code_resumed == 1
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()


def test_invalid_checkpoint_asof_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=BASE + timedelta(hours=5),  # outside the 2-slot grid
        asofs_completed=1,
        row_count=1,
        partial_bytes=10,
        source_query_count=1,
        source_rows_read=1,
        terminal_state="RUNNING",
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").write_bytes(b'{"row":1}\n')

    exit_code = module.main(
        [
            "--split-manifest",
            str(manifest_path),
            "--source-integrity",
            str(integrity_path),
            "--resume",
        ]
    )
    assert exit_code == 1
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()


def test_manifest_mismatch_denied_on_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256="not-the-real-sha",
        source_integrity_composite_sha256="fixed",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=None,
        asofs_completed=0,
        row_count=0,
        partial_bytes=0,
        source_query_count=0,
        source_rows_read=0,
        terminal_state="RUNNING",
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()

    exit_code = module.main(
        [
            "--split-manifest",
            str(manifest_path),
            "--source-integrity",
            str(integrity_path),
            "--resume",
        ]
    )
    assert exit_code == 1


def test_c1_only_result_from_replay_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "fixed"}), encoding="utf-8")
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE)

    def bad_evaluate_candidate(*, candles_by_asset, asof_ts, spec, venue):
        return [
            CandidateResult(
                venue=venue,
                asset_id=1,
                candidate_id="C2",
                model_id="x",
                model_version=spec.model_version,
                input_interval="15m",
                lookback_horizon=spec.lookback_horizon,
                effective_horizon=spec.effective_horizon,
                observed_lifecycle="UNMEASURED",
                asof_ts=asof_ts,
                freshness="FRESH",
                provenance="test",
                cohort_size=1,
                relative_return_unit=Decimal("0.1"),
                signed_flow_unit=Decimal("0.1"),
                relative_acceleration_unit=Decimal("0.1"),
                rotation_score=Decimal("1.0"),
                data_quality="COMPLETE",
                reason="OK",
            )
        ]

    monkeypatch.setattr(module, "evaluate_candidate", bad_evaluate_candidate)
    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
