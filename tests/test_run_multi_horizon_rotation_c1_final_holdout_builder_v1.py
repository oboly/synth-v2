from __future__ import annotations

import json
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research.multi_horizon_rotation_dataset_builder_v1 import AssetCoverage, RotationV1PitIndex
from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS, Candle, CandidateResult
from src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 import (
    APPROVED_EXECUTION_ACCOUNT,
    CANDIDATE_ID,
    PHASE,
    RunnerInterrupted,
    acquire_run_lease_exclusive,
    canonical_run_dir,
    checkpoint_path,
    compute_c1_implementation_fingerprint,
    create_registry_entry_exclusive,
    current_trusted_execution_account,
    default_registry_root,
    enforce_approved_execution_account,
    finalize_c1_holdout_bundle,
    load_checkpoint,
    load_manifest,
    load_registry_entry,
    main,
    mark_checkpoint_terminal,
    mark_registry_terminal,
    parse_args,
    reconcile_partial_to_checkpoint,
    registry_entry_path,
    registry_key_for,
    run_lease_path,
    select_c1_spec,
    validate_resume_checkpoint,
    write_checkpoint,
    write_registry_entry,
)


BASE = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)

# The real, current implementation fingerprint for the frozen C1 spec + the
# actual on-disk replay module -- used when tests hand-construct a
# RUNNING/INTERRUPTED checkpoint or registry entry that a subsequent
# ``--resume`` must accept (the real runner always validates this field on
# resume; see ``verify_c1_implementation_fingerprint``).
REAL_C1_IMPLEMENTATION_FINGERPRINT = compute_c1_implementation_fingerprint(select_c1_spec())[
    "implementation_fingerprint_sha256"
]


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


def _two_asof_manifest() -> dict[str, object]:
    return _manifest(holdout_end="2026-08-22T06:30:00Z")


def _write_run_files(tmp_path: Path, *, manifest: dict[str, object] | None = None, subdir: str = "") -> tuple[Path, Path]:
    run_dir = (tmp_path / subdir) if subdir else tmp_path
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "split_manifest_v1.json"
    integrity_path = run_dir / "source_integrity_v1.json"
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


# --- Canonical per-directory binding (defense in depth, not the security gate) --


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


def test_no_output_dir_argument_at_all(tmp_path: Path) -> None:
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


# --- Registry: pure functions --------------------------------------------


def test_registry_key_is_deterministic_and_path_independent() -> None:
    """The key is a pure function of frozen content, never of any filesystem path."""
    kwargs = dict(
        manifest_sha256="m-sha",
        source_integrity_composite_sha256="i-sha",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    key_a = registry_key_for(**kwargs)
    key_b = registry_key_for(**kwargs)
    assert key_a == key_b
    assert registry_key_for(**{**kwargs, "manifest_sha256": "different"}) != key_a


def test_registry_entry_round_trip_and_terminal_marking(tmp_path: Path) -> None:
    path = registry_entry_path_for_test(tmp_path, "abc")
    assert load_registry_entry(path) is None
    write_registry_entry(
        path,
        venue="bitvavo",
        manifest_sha256="m",
        source_integrity_composite_sha256="i",
        terminal_state="RUNNING",
        opened_run_dir="/some/dir",
    )
    entry = load_registry_entry(path)
    assert entry is not None
    assert entry["terminal_state"] == "RUNNING"

    identity = {
        "venue": "bitvavo",
        "candidate_id": "C1",
        "phase": "final_holdout",
        "manifest_sha256": "m",
        "source_integrity_composite_sha256": "i",
    }
    mark_registry_terminal(path, terminal_state="FAILED", identity=identity)
    assert load_registry_entry(path)["terminal_state"] == "FAILED"

    # marking a NEVER-created entry still locks the fingerprint (fallback identity path)
    missing_path = registry_entry_path_for_test(tmp_path, "never-existed")
    mark_registry_terminal(missing_path, terminal_state="FAILED", identity=identity)
    assert load_registry_entry(missing_path)["terminal_state"] == "FAILED"


def registry_entry_path_for_test(root: Path, key: str) -> Path:
    return root / f"{key}.json"


def test_create_registry_entry_exclusive_is_atomic_under_concurrency(tmp_path: Path) -> None:
    """Low-level proof that the primitive itself -- not just main()'s use of it --
    has no check-then-create race window: many threads racing to create the same
    fingerprint entry must have exactly one winner."""
    path = tmp_path / "race.json"
    identity = dict(
        venue="bitvavo",
        manifest_sha256="m",
        source_integrity_composite_sha256="i",
        terminal_state="RUNNING",
        opened_run_dir="/race",
    )

    def attempt(_: int) -> bool:
        return create_registry_entry_exclusive(path, **identity)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(attempt, range(16)))

    assert results.count(True) == 1
    assert results.count(False) == 15
    entry = load_registry_entry(path)
    assert entry is not None
    assert entry["terminal_state"] == "RUNNING"


# --- Fresh-run one-shot denial (local checkpoint layer) ------------------


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
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"


def test_resume_denied_when_checkpoint_or_partial_missing(tmp_path: Path) -> None:
    manifest_path, integrity_path = _write_run_files(tmp_path)
    exit_code = main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code == 1


def test_resume_denied_when_local_checkpoint_terminal_state_finished(tmp_path: Path) -> None:
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


# --- End-to-end runner harness (fresh, resume, denial, signals, registry) --


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


def _install_fake_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    *,
    phase_start: datetime,
    registry_root: Path | None,
    approve_test_manifest: bool = True,
) -> None:
    """Stub every DB-touching function so main() can run end-to-end deterministically,
    and point the trusted registry at an isolated test directory (never the real repo
    data/research tree). Pass ``registry_root=None`` to leave ``module.REGISTRY_ROOT``
    untouched -- used by tests that set it themselves (e.g. by deriving it from a
    monkeypatched ``pwd.getpwnam``) to exercise the real default-registry-root wiring."""

    def fake_get_db_connection() -> _FakeConnection:
        return _FakeConnection()

    def fake_current_trusted_hostname() -> str:
        return module.APPROVED_EXECUTION_HOST

    def fake_current_trusted_execution_account() -> str:
        return module.APPROVED_EXECUTION_ACCOUNT

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
    monkeypatch.setattr(module, "current_trusted_hostname", fake_current_trusted_hostname)
    monkeypatch.setattr(module, "current_trusted_execution_account", fake_current_trusted_execution_account)
    monkeypatch.setattr(module, "build_integrity_payload", fake_build_integrity_payload)
    monkeypatch.setattr(module, "verify_existing", fake_verify_existing)
    monkeypatch.setattr(module, "fetch_asset_coverage", fake_fetch_asset_coverage)
    monkeypatch.setattr(module, "fetch_rotation_v1_points", fake_fetch_rotation_v1_points)
    monkeypatch.setattr(module, "fetch_candles_for_chunk", fake_fetch_candles_for_chunk)
    monkeypatch.setattr(module, "evaluate_candidate", fake_evaluate_candidate)
    if approve_test_manifest:
        monkeypatch.setattr(module, "verify_approved_split_manifest", lambda manifest: module.manifest_fingerprint(manifest))
    if registry_root is not None:
        monkeypatch.setattr(module, "REGISTRY_ROOT", registry_root)


def test_fresh_run_completes_and_publishes_exactly_one_canonical_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

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

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    registry_entry = load_registry_entry(registry_entry_path(registry_key))
    assert registry_entry is not None
    assert registry_entry["terminal_state"] == "FINISHED"
    monkeypatch.setattr(module, "REGISTRY_ROOT", registry_root)  # sanity: still points at test dir

    # A second fresh invocation in the SAME directory is denied after FINISHED.
    exit_code_again = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code_again == 1
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"
    assert len(artifact.read_text(encoding="utf-8").splitlines()) == 2


def test_byte_identical_manifest_copied_to_second_directory_cannot_reopen_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests 1-3: the trusted registry -- not the caller-chosen directory -- is the
    one-shot boundary. A byte-identical manifest+integrity pair copied into a second
    directory resolves to the same registry key and is denied, even though nothing
    local exists yet in that second directory."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path_a, integrity_path_a = _write_run_files(tmp_path, manifest=manifest, subdir="dir_a")
    registry_root = tmp_path / "_shared_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    exit_code_a = module.main(
        ["--split-manifest", str(manifest_path_a), "--source-integrity", str(integrity_path_a)]
    )
    assert exit_code_a == 0

    # byte-identical copy into a second, unrelated directory
    dir_b = tmp_path / "dir_b"
    dir_b.mkdir()
    manifest_path_b = dir_b / "split_manifest_v1.json"
    integrity_path_b = dir_b / "source_integrity_v1.json"
    manifest_path_b.write_bytes(manifest_path_a.read_bytes())
    integrity_path_b.write_bytes(integrity_path_a.read_bytes())
    assert manifest_path_a.read_bytes() == manifest_path_b.read_bytes()
    assert manifest_path_a != manifest_path_b  # genuinely a different path

    exit_code_b = module.main(
        ["--split-manifest", str(manifest_path_b), "--source-integrity", str(integrity_path_b)]
    )
    assert exit_code_b == 1
    assert not (dir_b / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not checkpoint_path(dir_b).exists()
    assert not (dir_b / ".final_holdout_c1_rows_v1.jsonl.partial").exists()


def test_concurrent_fresh_runs_against_copied_manifest_exactly_one_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the Codex BLOCK: registry creation was a check-then-write
    sequence, so two concurrent fresh runs against byte-identical copied manifest
    and source-integrity inputs could both pass the absence check and both open
    the holdout. Two real threads are raced through a synchronization barrier
    placed right before the exclusive-create call so both reach it together;
    exactly one may win, the other must perform zero replay/outcome construction
    and create zero local state."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path_a, integrity_path_a = _write_run_files(tmp_path, manifest=manifest, subdir="dir_a")
    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_b.mkdir()
    manifest_path_b = dir_b / "split_manifest_v1.json"
    integrity_path_b = dir_b / "source_integrity_v1.json"
    manifest_path_b.write_bytes(manifest_path_a.read_bytes())
    integrity_path_b.write_bytes(integrity_path_a.read_bytes())

    registry_root = tmp_path / "_shared_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    barrier = threading.Barrier(2, timeout=5)
    real_build_integrity_payload = module.build_integrity_payload

    def synced_build_integrity_payload(conn, *, venue, split_manifest):
        result = real_build_integrity_payload(conn, venue=venue, split_manifest=split_manifest)
        barrier.wait()  # both threads reach the exclusive-create call together
        return result

    monkeypatch.setattr(module, "build_integrity_payload", synced_build_integrity_payload)
    # signal.signal() only works on the main thread; main() is driven from two
    # worker threads here, so its (unrelated to this race) handler installation
    # is stubbed out for this test only.
    monkeypatch.setattr(module, "install_interrupt_handlers", lambda: {})

    def run(manifest_path: Path, integrity_path: Path) -> int:
        return module.main(
            ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(run, manifest_path_a, integrity_path_a)
        future_b = executor.submit(run, manifest_path_b, integrity_path_b)
        exit_a = future_a.result()
        exit_b = future_b.result()

    assert {exit_a, exit_b} == {0, 1}, f"expected exactly one winner: exit_a={exit_a} exit_b={exit_b}"

    winner_dir, loser_dir = (dir_a, dir_b) if exit_a == 0 else (dir_b, dir_a)

    # Exactly one authoritative registry entry, and it is FINISHED (the winner
    # ran replay to completion; the loser never touched it).
    entries = list(registry_root.iterdir())
    assert len(entries) == 1
    assert json.loads(entries[0].read_text(encoding="utf-8"))["terminal_state"] == "FINISHED"

    # Winner performed the full replay and published exactly one canonical artifact.
    assert (winner_dir / "final_holdout_c1_rows_v1.jsonl").exists()
    assert (winner_dir / "final_holdout_c1_summary_v1.json").exists()
    assert load_checkpoint(checkpoint_path(winner_dir))["terminal_state"] == "FINISHED"

    # Loser performed zero holdout replay/outcome construction: no local checkpoint,
    # no partial, no artifact, no summary were ever created for it.
    assert not (loser_dir / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not (loser_dir / "final_holdout_c1_summary_v1.json").exists()
    assert not checkpoint_path(loser_dir).exists()
    assert not (loser_dir / ".final_holdout_c1_rows_v1.jsonl.partial").exists()


def test_running_registry_state_permits_exact_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
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
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="RUNNING",
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
        opened_run_dir=str(tmp_path),
    )

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code == 0
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"
    assert not run_lease_path(registry_key).exists()


def test_failed_registry_state_denies_resume_forever(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=None,
        asofs_completed=0,
        row_count=0,
        partial_bytes=0,
        source_query_count=0,
        source_rows_read=0,
        terminal_state="INTERRUPTED",
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="FAILED",
        opened_run_dir=str(tmp_path),
    )

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code == 1
    # never resumed, never overwritten
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FAILED"
    assert load_checkpoint(cp_path)["terminal_state"] == "INTERRUPTED"


def test_finished_registry_state_denies_resume_forever(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=None,
        asofs_completed=0,
        row_count=0,
        partial_bytes=0,
        source_query_count=0,
        source_rows_read=0,
        terminal_state="INTERRUPTED",
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="FINISHED",
        opened_run_dir=str(tmp_path),
    )

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code == 1
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"


def test_sigint_interrupts_cleanly_and_resume_completes_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

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

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    registry_entry = load_registry_entry(registry_entry_path(registry_key))
    assert registry_entry is not None
    assert registry_entry["terminal_state"] == "INTERRUPTED"

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
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"
    assert not run_lease_path(registry_key).exists()


def test_sigint_during_resume_releases_lease_and_leaves_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The lease must be released on SIGINT/SIGTERM during --resume itself (not
    just during a fresh run), leaving the checkpoint/registry INTERRUPTED and a
    further explicit --resume allowed."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=None,
        asofs_completed=0,
        row_count=0,
        partial_bytes=0,
        source_query_count=0,
        source_rows_read=0,
        terminal_state="INTERRUPTED",
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="INTERRUPTED",
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
        opened_run_dir=str(tmp_path),
    )

    def raising_evaluate_candidate(*args, **kwargs):
        raise RunnerInterrupted(signal.SIGINT)

    monkeypatch.setattr(module, "evaluate_candidate", raising_evaluate_candidate)

    exit_code = module.main(
        [
            "--split-manifest",
            str(manifest_path),
            "--source-integrity",
            str(integrity_path),
            "--resume",
        ]
    )
    assert exit_code == 130
    out = capsys.readouterr().out
    assert len([line for line in out.splitlines() if line.startswith("INTERRUPTED")]) == 1

    assert load_checkpoint(cp_path)["terminal_state"] == "INTERRUPTED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "INTERRUPTED"
    lease_path = run_lease_path(registry_key)
    assert not lease_path.exists()

    # A further explicit resume is allowed and completes.
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)
    exit_code_again = module.main(
        [
            "--split-manifest",
            str(manifest_path),
            "--source-integrity",
            str(integrity_path),
            "--resume",
        ]
    )
    assert exit_code_again == 0
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"
    assert not lease_path.exists()


def test_sigterm_interrupts_cleanly_with_exit_143(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

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

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "INTERRUPTED"

    # Previous signal handlers must be restored, not left pointing at the runner's.
    assert signal.getsignal(signal.SIGINT) == sigint_before
    assert signal.getsignal(signal.SIGTERM) == sigterm_before


def test_source_integrity_mismatch_denied_and_creates_no_registry_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    integrity_path.write_text(json.dumps({"composite_sha256": "stale"}), encoding="utf-8")
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not checkpoint_path(tmp_path).exists()
    # Failure happened before the holdout was ever "opened": no registry entry at all.
    assert not registry_root.exists() or list(registry_root.iterdir()) == []


def test_resume_reverifies_source_integrity_and_marks_failed_on_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests 11: a resume-time integrity drift, discovered after the holdout was
    already opened, must permanently lock both the local checkpoint and the
    authoritative registry entry as FAILED (never left resumable)."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

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

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    reg_path = registry_entry_path(registry_key)
    assert load_registry_entry(reg_path)["terminal_state"] == "INTERRUPTED"

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

    cp_path = checkpoint_path(tmp_path)
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"
    assert load_registry_entry(reg_path)["terminal_state"] == "FAILED"

    # FAILED is permanently non-resumable: a further --resume attempt is denied.
    exit_code_again = module.main(
        [
            "--split-manifest",
            str(manifest_path),
            "--source-integrity",
            str(integrity_path),
            "--resume",
        ]
    )
    assert exit_code_again == 1
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"
    assert load_registry_entry(reg_path)["terminal_state"] == "FAILED"


def test_invalid_checkpoint_asof_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

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
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="RUNNING",
        opened_run_dir=str(tmp_path),
    )

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
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FAILED"


def test_manifest_mismatch_denied_on_resume_and_marks_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

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
    registry_key = registry_key_for(
        manifest_sha256="not-the-real-sha",
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256="not-the-real-sha",
        source_integrity_composite_sha256="fixed",
        terminal_state="RUNNING",
        opened_run_dir=str(tmp_path),
    )

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
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FAILED"
    assert not run_lease_path(registry_key).exists()


def test_c1_only_result_from_replay_enforced_marks_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

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

    cp_path = checkpoint_path(tmp_path)
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FAILED"

    # FAILED is permanent: neither a fresh run nor a resume can proceed.
    exit_code_fresh_retry = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code_fresh_retry == 1
    exit_code_resume_retry = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code_resume_retry == 1


# --- Run lease: exclusivity, release, and no-mutation-on-loss -----------


def test_existing_run_lease_denies_resume_before_any_partial_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
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
    partial_path = tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial"
    partial_path.write_bytes(b"")
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="RUNNING",
        opened_run_dir=str(tmp_path),
    )

    # Simulate another resume already holding the lease.
    lease_path = run_lease_path(registry_key)
    won = acquire_run_lease_exclusive(lease_path, registry_key=registry_key)
    assert won is True
    lease_bytes_before = lease_path.read_bytes()
    checkpoint_before = load_checkpoint(cp_path)
    registry_before = load_registry_entry(registry_entry_path(registry_key))

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

    # Nothing about the checkpoint, registry, partial, or the other resume's
    # lease was touched by the denied caller.
    assert load_checkpoint(cp_path) == checkpoint_before
    assert load_registry_entry(registry_entry_path(registry_key)) == registry_before
    assert partial_path.read_bytes() == b""
    assert lease_path.read_bytes() == lease_bytes_before
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not (tmp_path / "final_holdout_c1_summary_v1.json").exists()


def test_two_concurrent_resumes_of_same_checkpoint_exactly_one_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the Codex BLOCK: --resume previously allowed two processes
    to both reconcile the same partial, append rows, and finalize concurrently.
    Two real threads race two --resume invocations of the SAME opened holdout
    (same checkpoint, same registry entry, same partial file), synchronized via
    a barrier placed immediately before the exclusive lease-acquire call."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)
    monkeypatch.setattr(module, "install_interrupt_handlers", lambda: {})  # threads can't signal.signal()

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=None,
        asofs_completed=0,
        row_count=0,
        partial_bytes=0,
        source_query_count=0,
        source_rows_read=0,
        terminal_state="INTERRUPTED",
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="INTERRUPTED",
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
        opened_run_dir=str(tmp_path),
    )

    barrier = threading.Barrier(2, timeout=5)
    real_acquire = module.acquire_run_lease_exclusive

    def synced_acquire(path: Path, *, registry_key: str) -> bool:
        barrier.wait()  # both threads reach the exclusive lease-acquire together
        return real_acquire(path, registry_key=registry_key)

    monkeypatch.setattr(module, "acquire_run_lease_exclusive", synced_acquire)

    def run() -> int:
        return module.main(
            [
                "--split-manifest",
                str(manifest_path),
                "--source-integrity",
                str(integrity_path),
                "--resume",
            ]
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_1 = executor.submit(run)
        future_2 = executor.submit(run)
        exit_1 = future_1.result()
        exit_2 = future_2.result()

    assert {exit_1, exit_2} == {0, 1}, f"expected exactly one winner: exit_1={exit_1} exit_2={exit_2}"

    # Winner resumed without duplicating rows: exactly the two frozen as-ofs, once each.
    artifact = tmp_path / "final_holdout_c1_rows_v1.jsonl"
    assert artifact.exists()
    lines = artifact.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    asofs = [json.loads(line)["asof_ts"] for line in lines]
    assert len(asofs) == len(set(asofs)) == 2

    # Exactly one final artifact/summary; final checkpoint + registry FINISHED.
    assert (tmp_path / "final_holdout_c1_summary_v1.json").exists()
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"

    # Lease absent once the winner has finished.
    assert not run_lease_path(registry_key).exists()


def test_resume_racing_active_fresh_run_fails_closed_with_zero_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the exact-head Codex BLOCK: a fresh runner did not hold the
    run lease until after it had already written its RUNNING checkpoint, so a
    concurrent --resume against that same checkpoint could acquire a
    (previously resume-only) lease and run alongside the still-active fresh
    process. Now fresh and resumed execution share ONE run lease, acquired by
    the fresh runner immediately after it wins authoritative registry creation
    and held continuously through replay/checkpoint/finalization. A --resume
    that observes the RUNNING registry/checkpoint while the fresh runner still
    owns that lease must fail closed -- before any reconciliation or replay --
    and the still-active fresh runner must be left free to finish alone."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)
    monkeypatch.setattr(module, "install_interrupt_handlers", lambda: {})  # threads can't signal.signal()

    reconcile_calls = {"n": 0}
    real_reconcile = module.reconcile_partial_to_checkpoint

    def counting_reconcile(*args, **kwargs):
        reconcile_calls["n"] += 1
        return real_reconcile(*args, **kwargs)

    monkeypatch.setattr(module, "reconcile_partial_to_checkpoint", counting_reconcile)

    fresh_mid_replay = threading.Event()
    allow_fresh_to_finish = threading.Event()
    real_evaluate_candidate = module.evaluate_candidate
    call_count = {"n": 0}

    def blocking_evaluate_candidate(*, candles_by_asset, asof_ts, spec, venue):
        # By the time this is called at least once, the fresh runner has already
        # won registry creation, acquired the run lease, and written its initial
        # RUNNING local checkpoint -- exactly the "registry + local RUNNING
        # checkpoint exist while fresh still owns the run lease" window the
        # required regression scenario targets.
        call_count["n"] += 1
        if call_count["n"] == 1:
            fresh_mid_replay.set()
            assert allow_fresh_to_finish.wait(timeout=5), "test deadlocked waiting for resume attempt"
        return real_evaluate_candidate(
            candles_by_asset=candles_by_asset, asof_ts=asof_ts, spec=spec, venue=venue
        )

    monkeypatch.setattr(module, "evaluate_candidate", blocking_evaluate_candidate)

    def run_fresh() -> int:
        return module.main(
            ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
        )

    def run_resume() -> int:
        assert fresh_mid_replay.wait(timeout=5), "test deadlocked waiting for fresh run to open the holdout"
        try:
            return module.main(
                [
                    "--split-manifest",
                    str(manifest_path),
                    "--source-integrity",
                    str(integrity_path),
                    "--resume",
                ]
            )
        finally:
            allow_fresh_to_finish.set()

    cp_path = checkpoint_path(tmp_path)
    partial_path = tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial"

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_fresh = executor.submit(run_fresh)
        future_resume = executor.submit(run_resume)
        exit_fresh = future_fresh.result()
        exit_resume = future_resume.result()

    # The fresh winner is allowed to continue and finish; the racing resume
    # fails closed.
    assert exit_fresh == 0
    assert exit_resume != 0

    # The denied resume never reached partial reconciliation/replay: it failed
    # at the shared run-lease acquisition, which happens before source
    # integrity is even reverified and strictly before reconcile_partial_to_checkpoint
    # is ever called.
    assert reconcile_calls["n"] == 0

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )

    # Exactly one final artifact/summary, no duplicate rows: the denied resume
    # performed zero output mutation of its own.
    artifact = tmp_path / "final_holdout_c1_rows_v1.jsonl"
    summary = tmp_path / "final_holdout_c1_summary_v1.json"
    assert artifact.exists()
    assert summary.exists()
    lines = artifact.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    asofs = [json.loads(line)["asof_ts"] for line in lines]
    assert len(asofs) == len(set(asofs)) == 2

    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"

    # The run lease -- shared by fresh and resumed execution -- is removed only
    # after the fresh winner reaches terminal completion.
    assert not run_lease_path(registry_key).exists()
    assert not partial_path.exists()


# --- Durable, checkout-independent authoritative registry root -----------


def _fake_pwent(home: Path, *, name: str = APPROVED_EXECUTION_ACCOUNT) -> object:
    """A minimal stand-in for the ``pwd.struct_passwd`` entry returned by
    ``pwd.getpwnam``/``pwd.getpwuid`` -- ``pw_dir`` is read by
    ``default_registry_root`` (via ``getpwnam``); ``pw_name`` is read by
    ``current_trusted_execution_account`` (via ``getpwuid``)."""

    class _FakePwent:
        pw_dir = str(home)
        pw_name = name

    return _FakePwent()


def test_default_registry_root_is_trusted_account_based_and_checkout_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the Codex BLOCK: REGISTRY_ROOT used to be derived from
    Path(__file__) (checkout-local), then from Path.home() / HOME
    (caller-controlled), then from the INVOKING process's effective UID
    (pwd.getpwuid(os.geteuid()).pw_dir) -- which is per-effective-UID, not
    per-approved-identity, so a different local account on the approved host
    could reopen the identical frozen holdout under its own, distinct
    registry root. It must now be a pure function of the FIXED approved
    execution account's trusted OS account metadata
    (pwd.getpwnam(APPROVED_EXECUTION_ACCOUNT).pw_dir) only, so it never
    depends on HOME, the checkout path, worktree path, current working
    directory, or which account is actually invoking the process."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    fake_home = tmp_path / "fake_home"
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: _fake_pwent(fake_home))

    root = module.default_registry_root()
    assert root == (
        fake_home
        / ".local"
        / "state"
        / "synth"
        / "research"
        / "multi_horizon_rotation_c1_final_holdout_registry_v1"
    )

    # Changing the working directory (simulating a different checkout root)
    # must not change the resolved registry root.
    other_cwd = tmp_path / "unrelated_checkout" / "some" / "deep" / "path"
    other_cwd.mkdir(parents=True)
    monkeypatch.chdir(other_cwd)
    assert module.default_registry_root() == root


def test_default_registry_root_is_invariant_under_home_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the exact Codex BLOCK: changing HOME (or XDG_STATE_HOME)
    must NOT change the resolved registry root, since a caller who controls
    HOME could otherwise reopen identical frozen holdout inputs against a
    fresh, empty registry."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    real_home = tmp_path / "real_home"
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: _fake_pwent(real_home))

    root_before = module.default_registry_root()

    spoofed_home = tmp_path / "attacker_controlled_home"
    monkeypatch.setenv("HOME", str(spoofed_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "attacker_controlled_xdg_state"))

    root_after = module.default_registry_root()
    assert root_after == root_before
    assert "attacker_controlled" not in str(root_after)


def test_default_registry_root_same_uid_yields_same_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two independent resolutions for the same approved account must agree."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    fixed_home = tmp_path / "fixed_home"
    calls: list[str] = []

    def fake_getpwnam(name: str) -> object:
        calls.append(name)
        return _fake_pwent(fixed_home)

    monkeypatch.setattr(module.pwd, "getpwnam", fake_getpwnam)

    first = module.default_registry_root()
    second = module.default_registry_root()
    assert first == second
    assert len(set(calls)) == 1  # same approved account name both times


def test_default_registry_root_fails_closed_when_account_metadata_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the approved account has no resolvable passwd entry, the registry
    root must fail closed (raise) rather than silently falling back to HOME
    or any other caller-controlled value."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    def raising_getpwnam(name: str) -> object:
        raise KeyError(f"getpwnam(): name not found: {name!r}")

    monkeypatch.setattr(module.pwd, "getpwnam", raising_getpwnam)

    with pytest.raises(RuntimeError, match="cannot resolve authoritative registry root"):
        module.default_registry_root()


def test_default_registry_root_fails_closed_when_home_dir_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolvable-but-empty pw_dir must also fail closed, not silently fall
    back to HOME or the current working directory."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    class _EmptyHomePwent:
        pw_dir = ""

    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: _EmptyHomePwent())

    with pytest.raises(RuntimeError, match="cannot resolve authoritative registry root"):
        module.default_registry_root()


def test_two_checkout_roots_with_identical_inputs_share_registry_and_second_cannot_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the Codex BLOCK: two different checkout/worktree
    directories with byte-identical frozen manifest/integrity content must
    resolve to the SAME authoritative registry entry, using the real default
    registry-root computation (only ``pwd.getpwnam`` is faked, to avoid
    touching the actual host state) -- not a registry root manually shared
    between the two invocations by the test itself. This also proves the
    approved account still resolves the same registry across checkouts."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    fake_home = tmp_path / "fake_home"
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: _fake_pwent(fake_home))
    monkeypatch.setattr(module, "REGISTRY_ROOT", module.default_registry_root())
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=None)

    manifest = _two_asof_manifest()
    checkout_a = tmp_path / "checkout_a" / "run_dir"
    checkout_b = tmp_path / "checkout_b" / "run_dir"
    manifest_path_a, integrity_path_a = _write_run_files(checkout_a, manifest=manifest)
    manifest_path_b, integrity_path_b = _write_run_files(checkout_b, manifest=manifest)

    exit_a = module.main(
        ["--split-manifest", str(manifest_path_a), "--source-integrity", str(integrity_path_a)]
    )
    assert exit_a == 0
    assert load_checkpoint(checkpoint_path(checkout_a))["terminal_state"] == "FINISHED"

    # Second "checkout" with byte-identical frozen inputs is denied: it shares
    # the SAME authoritative registry entry as the first, resolved purely from
    # frozen content + the durable host-level registry root, independent of
    # which directory each checkout supplied its manifest from.
    exit_b = module.main(
        ["--split-manifest", str(manifest_path_b), "--source-integrity", str(integrity_path_b)]
    )
    assert exit_b == 1
    assert not checkpoint_path(checkout_b).exists()
    assert not (checkout_b / "final_holdout_c1_rows_v1.jsonl").exists()

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    registry_root = module.default_registry_root()
    entries = list(registry_root.glob(f"{registry_key}.json"))
    assert len(entries) == 1
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"


def test_two_checkout_roots_racing_fresh_runs_share_run_lease_exactly_one_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same durable-registry-root regression as above, but proving the run
    lease itself -- not just the registry entry -- is shared across two
    checkout/worktree directories: a second "checkout" racing a fresh run
    against the same frozen inputs must be unable to acquire the run lease
    while the first still owns it, using the real default registry-root
    computation."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    fake_home = tmp_path / "fake_home"
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: _fake_pwent(fake_home))
    monkeypatch.setattr(module, "REGISTRY_ROOT", module.default_registry_root())
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=None)
    monkeypatch.setattr(module, "install_interrupt_handlers", lambda: {})  # threads can't signal.signal()

    manifest = _two_asof_manifest()
    checkout_a = tmp_path / "checkout_a" / "run_dir"
    checkout_b = tmp_path / "checkout_b" / "run_dir"
    manifest_path_a, integrity_path_a = _write_run_files(checkout_a, manifest=manifest)
    manifest_path_b, integrity_path_b = _write_run_files(checkout_b, manifest=manifest)

    barrier = threading.Barrier(2, timeout=5)
    real_build_integrity_payload = module.build_integrity_payload

    def synced_build_integrity_payload(conn, *, venue, split_manifest):
        result = real_build_integrity_payload(conn, venue=venue, split_manifest=split_manifest)
        barrier.wait()  # both threads reach the exclusive-create call together
        return result

    monkeypatch.setattr(module, "build_integrity_payload", synced_build_integrity_payload)

    def run(manifest_path: Path, integrity_path: Path) -> int:
        return module.main(
            ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(run, manifest_path_a, integrity_path_a)
        future_b = executor.submit(run, manifest_path_b, integrity_path_b)
        exit_a = future_a.result()
        exit_b = future_b.result()

    assert {exit_a, exit_b} == {0, 1}, f"expected exactly one winner: exit_a={exit_a} exit_b={exit_b}"
    winner_dir = checkout_a if exit_a == 0 else checkout_b
    loser_dir = checkout_b if exit_a == 0 else checkout_a

    registry_root = module.default_registry_root()
    entries = list(registry_root.glob("*.json"))
    assert len(entries) == 1
    assert json.loads(entries[0].read_text(encoding="utf-8"))["terminal_state"] == "FINISHED"

    assert (winner_dir / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not checkpoint_path(loser_dir).exists()
    assert not (loser_dir / "final_holdout_c1_rows_v1.jsonl").exists()


# --- Signal-safe transactional finalization -------------------------------


def _finalize_kwargs(tmp_path: Path, **overrides: object) -> dict[str, object]:
    partial_path = tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial"
    partial_path.write_bytes(b'{"row":1}\n{"row":2}\n')
    registry_path = tmp_path / "registry_entry.json"
    write_registry_entry(
        registry_path,
        venue="bitvavo",
        manifest_sha256="m-sha",
        source_integrity_composite_sha256="i-sha",
        terminal_state="RUNNING",
        opened_run_dir=str(tmp_path),
    )
    lease_path = tmp_path / "run_lease.json"
    assert acquire_run_lease_exclusive(lease_path, registry_key="k")

    kwargs: dict[str, object] = dict(
        partial_path=partial_path,
        artifact_path=tmp_path / "final_holdout_c1_rows_v1.jsonl",
        summary_path=tmp_path / "final_holdout_c1_summary_v1.json",
        summary={"row_count": 2},
        cp_path=tmp_path / ".final_holdout_c1_checkpoint_v1.json",
        registry_path=registry_path,
        registry_identity={
            "venue": "bitvavo",
            "candidate_id": "C1",
            "phase": "final_holdout",
            "manifest_sha256": "m-sha",
            "source_integrity_composite_sha256": "i-sha",
        },
        run_lease_held_path=lease_path,
        venue="bitvavo",
        manifest_sha="m-sha",
        composite_sha="i-sha",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=BASE + timedelta(minutes=15),
        asofs_completed=2,
        row_count=2,
        source_query_count=1,
        source_rows_read=2,
    )
    write_checkpoint(
        kwargs["cp_path"],
        venue="bitvavo",
        manifest_sha256="m-sha",
        source_integrity_composite_sha256="i-sha",
        phase_start=BASE,
        phase_end=BASE + timedelta(minutes=30),
        last_completed_asof=BASE + timedelta(minutes=15),
        asofs_completed=2,
        row_count=2,
        partial_bytes=len(b'{"row":1}\n{"row":2}\n'),
        source_query_count=1,
        source_rows_read=2,
        terminal_state="RUNNING",
    )
    kwargs.update(overrides)
    return kwargs


def _assert_finished_state(tmp_path: Path, kwargs: dict[str, object]) -> None:
    assert kwargs["artifact_path"].exists()
    assert kwargs["summary_path"].exists()
    assert not kwargs["partial_path"].exists()
    assert load_checkpoint(kwargs["cp_path"])["terminal_state"] == "FINISHED"
    assert load_registry_entry(kwargs["registry_path"])["terminal_state"] == "FINISHED"
    assert not kwargs["run_lease_held_path"].exists()


def test_finalize_completes_cleanly_with_no_interrupt(tmp_path: Path) -> None:
    kwargs = _finalize_kwargs(tmp_path)
    final_bytes, deferred_signum = finalize_c1_holdout_bundle(**kwargs)
    assert final_bytes == len(b'{"row":1}\n{"row":2}\n')
    assert deferred_signum is None
    _assert_finished_state(tmp_path, kwargs)


def test_finalize_interrupted_before_rename_completes_stays_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case A: an interrupt that fires before the rename ever touches disk
    must be re-raised unchanged (nothing published, partial untouched)."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    kwargs = _finalize_kwargs(tmp_path)

    def raising_replace(self, target):
        raise RunnerInterrupted(signal.SIGINT)

    monkeypatch.setattr(Path, "replace", raising_replace)

    with pytest.raises(RunnerInterrupted):
        finalize_c1_holdout_bundle(**kwargs)

    assert kwargs["partial_path"].exists()
    assert not kwargs["artifact_path"].exists()
    assert not kwargs["summary_path"].exists()
    assert load_checkpoint(kwargs["cp_path"])["terminal_state"] == "RUNNING"
    assert load_registry_entry(kwargs["registry_path"])["terminal_state"] == "RUNNING"
    assert kwargs["run_lease_held_path"].exists()


@pytest.mark.parametrize(
    "inject",
    [
        "after_rename",
        "after_summary",
        "after_checkpoint",
        "after_registry",
        "after_lease_release",
    ],
)
def test_finalize_interrupted_at_every_post_rename_step_still_reaches_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inject: str
) -> None:
    """Case B for every required injection point at/after the point of no
    return: interrupt right after the artifact rename, between artifact and
    summary publication, before the FINISHED checkpoint write, before the
    FINISHED registry write, and before the lease release. In every case the
    run must still reach exactly FINISHED with both final files durably
    published and no resumable partial -- never a mix of published output
    with RUNNING/INTERRUPTED state, and the deferred signal must be reported
    back to the caller."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    kwargs = _finalize_kwargs(tmp_path)

    if inject == "after_rename":
        real_replace = Path.replace
        target_artifact = kwargs["artifact_path"]

        def raising_replace(self, target):
            result = real_replace(self, target)
            if Path(target) == target_artifact:
                raise RunnerInterrupted(signal.SIGINT)
            return result

        monkeypatch.setattr(Path, "replace", raising_replace)
    elif inject == "after_summary":
        real_write_json_atomic = module.write_json_atomic

        def raising_write_json_atomic(path, payload):
            real_write_json_atomic(path, payload)
            raise RunnerInterrupted(signal.SIGTERM)

        monkeypatch.setattr(module, "write_json_atomic", raising_write_json_atomic)
    elif inject == "after_checkpoint":
        real_write_checkpoint = module.write_checkpoint

        def raising_write_checkpoint(*args, **kw):
            real_write_checkpoint(*args, **kw)
            if kw.get("terminal_state") == "FINISHED":
                raise RunnerInterrupted(signal.SIGINT)

        monkeypatch.setattr(module, "write_checkpoint", raising_write_checkpoint)
    elif inject == "after_registry":
        real_mark_registry_terminal = module.mark_registry_terminal

        def raising_mark_registry_terminal(*args, **kw):
            real_mark_registry_terminal(*args, **kw)
            raise RunnerInterrupted(signal.SIGTERM)

        monkeypatch.setattr(module, "mark_registry_terminal", raising_mark_registry_terminal)
    elif inject == "after_lease_release":
        real_release_run_lease = module.release_run_lease

        def raising_release_run_lease(path):
            real_release_run_lease(path)
            raise RunnerInterrupted(signal.SIGINT)

        monkeypatch.setattr(module, "release_run_lease", raising_release_run_lease)
    else:
        raise AssertionError(inject)

    final_bytes, deferred_signum = finalize_c1_holdout_bundle(**kwargs)
    assert deferred_signum is not None
    assert final_bytes == len(b'{"row":1}\n{"row":2}\n')
    _assert_finished_state(tmp_path, kwargs)


def test_finalize_reports_only_the_first_deferred_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If interrupts land at more than one step, only the first is reported,
    and every step still runs -- the outcome is still exactly FINISHED."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    kwargs = _finalize_kwargs(tmp_path)

    real_write_json_atomic = module.write_json_atomic

    def raising_write_json_atomic(path, payload):
        real_write_json_atomic(path, payload)
        raise RunnerInterrupted(signal.SIGINT)

    monkeypatch.setattr(module, "write_json_atomic", raising_write_json_atomic)

    real_mark_registry_terminal = module.mark_registry_terminal

    def raising_mark_registry_terminal(*args, **kw):
        real_mark_registry_terminal(*args, **kw)
        raise RunnerInterrupted(signal.SIGTERM)

    monkeypatch.setattr(module, "mark_registry_terminal", raising_mark_registry_terminal)

    final_bytes, deferred_signum = finalize_c1_holdout_bundle(**kwargs)
    assert deferred_signum == signal.SIGINT
    _assert_finished_state(tmp_path, kwargs)


def test_main_reports_finished_not_interrupted_when_signal_deferred_during_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end: a signal delivered exactly at the artifact-rename boundary
    during main()'s own finalization call must produce exit code 0, a single
    FINISHED line (never INTERRUPTED), and a durable FINISHED checkpoint +
    registry with no resumable partial left behind."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    real_replace = Path.replace
    target_artifact = tmp_path / "final_holdout_c1_rows_v1.jsonl"

    def raising_replace(self, target):
        result = real_replace(self, target)
        if Path(target) == target_artifact:
            raise RunnerInterrupted(signal.SIGINT)
        return result

    monkeypatch.setattr(Path, "replace", raising_replace)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 0

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert not any(line.startswith("INTERRUPTED") for line in lines)
    finished_lines = [line for line in lines if line.startswith("FINISHED runner=")]
    assert len(finished_lines) == 1
    assert "deferred_signal=SIGINT" in finished_lines[0]

    artifact = tmp_path / "final_holdout_c1_rows_v1.jsonl"
    summary = tmp_path / "final_holdout_c1_summary_v1.json"
    cp_path = checkpoint_path(tmp_path)
    assert artifact.exists()
    assert summary.exists()
    assert not (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").exists()
    assert load_checkpoint(cp_path)["terminal_state"] == "FINISHED"

    manifest_sha = module.manifest_fingerprint(manifest)
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FINISHED"
    assert not run_lease_path(registry_key).exists()


# --- Approved execution host --------------------------------------------


def test_fresh_run_on_approved_host_completes_and_emits_host_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert f"HOST_APPROVED host={module.APPROVED_EXECUTION_HOST} approved_host={module.APPROVED_EXECUTION_HOST}" in out


def test_fresh_run_denied_on_non_approved_host_before_registry_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the Codex BLOCK: a non-approved host must be denied
    before any registry entry is created and before any DB access/replay --
    zero DB calls, zero registry/checkpoint/output mutation."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    db_calls = {"n": 0}

    def counting_get_db_connection() -> _FakeConnection:
        db_calls["n"] += 1
        return _FakeConnection()

    monkeypatch.setattr(module, "get_db_connection", counting_get_db_connection)
    monkeypatch.setattr(module, "current_trusted_hostname", lambda: "not-the-approved-host")

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    assert db_calls["n"] == 0

    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not (tmp_path / "final_holdout_c1_summary_v1.json").exists()
    assert not checkpoint_path(tmp_path).exists()
    assert not (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").exists()
    assert not any(registry_root.glob("*.json"))


def test_caller_cannot_spoof_approved_host_via_hostname_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trusted hostname source is socket.gethostname(), never the HOSTNAME
    environment variable, so a caller setting HOSTNAME to the approved host
    name cannot bypass the guard when the OS-reported hostname is not
    actually approved."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    monkeypatch.setattr(module, "current_trusted_hostname", lambda: "attacker-controlled-host")
    monkeypatch.setenv("HOSTNAME", module.APPROVED_EXECUTION_HOST)

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    assert not any(registry_root.glob("*.json"))
    assert not checkpoint_path(tmp_path).exists()


def test_current_trusted_hostname_ignores_hostname_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """current_trusted_hostname() must be a pure function of the OS-reported
    hostname (socket.gethostname()), unaffected by the HOSTNAME env var."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    before = module.current_trusted_hostname()
    monkeypatch.setenv("HOSTNAME", "totally-different-spoofed-hostname")
    after = module.current_trusted_hostname()
    assert after == before


# --- Frozen C1 implementation fingerprint --------------------------------


def test_verify_c1_implementation_fingerprint_matches_committed_frozen_doc() -> None:
    """The exact frozen (unmodified) C1 spec + replay implementation must
    verify successfully against the committed expected fingerprint doc."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    result = module.verify_c1_implementation_fingerprint(module.select_c1_spec())
    assert result == REAL_C1_IMPLEMENTATION_FINGERPRINT


def test_verify_c1_implementation_fingerprint_fails_when_c1_spec_changed() -> None:
    """A changed C1 candidate spec (e.g. a different horizon/model_version --
    which would flip lookback/horizon semantics) must fail verification even
    though the replay module source is untouched."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module
    from src.research.multi_horizon_rotation_replay_v1 import CandidateSpec

    drifted_spec = CandidateSpec("C1", "1.0.0-c1-DRIFTED", 15, "VERY_SHORT")
    with pytest.raises(ValueError, match="C1 implementation fingerprint mismatch"):
        module.verify_c1_implementation_fingerprint(drifted_spec)


def test_verify_c1_implementation_fingerprint_fails_when_replay_source_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed replay-implementation source (e.g. a score weight/sign/
    formula edit) must fail verification even though the C1 spec itself is
    untouched -- the fingerprint binds the exact source bytes of the file
    that owns the formula/eligibility/boundary semantics."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    real_path = Path(module.c1_replay_module.__file__).resolve()
    drifted_path = tmp_path / "drifted_multi_horizon_rotation_replay_v1.py"
    drifted_path.write_bytes(real_path.read_bytes() + b"\n# drifted\n")

    class _DriftedReplayModule:
        __file__ = str(drifted_path)

    monkeypatch.setattr(module, "c1_replay_module", _DriftedReplayModule())

    with pytest.raises(ValueError, match="C1 implementation fingerprint mismatch"):
        module.verify_c1_implementation_fingerprint(module.select_c1_spec())


def test_verify_c1_implementation_fingerprint_fails_when_frozen_doc_disagrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even an unmodified implementation must fail closed if the committed
    frozen doc records a different expected value (e.g. it was frozen
    against different code, or has itself drifted)."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    monkeypatch.setattr(
        module,
        "load_frozen_c1_implementation_fingerprint",
        lambda: {"implementation_fingerprint_sha256": "0" * 64},
    )
    with pytest.raises(ValueError, match="C1 implementation fingerprint mismatch"):
        module.verify_c1_implementation_fingerprint(module.select_c1_spec())


def test_fresh_run_denied_before_registry_creation_on_implementation_fingerprint_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the Codex BLOCK: an implementation fingerprint mismatch
    must fail closed BEFORE any registry entry is created, on a fresh run --
    zero registry/checkpoint/output mutation, no holdout outcomes replayed."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)
    monkeypatch.setattr(
        module,
        "load_frozen_c1_implementation_fingerprint",
        lambda: {"implementation_fingerprint_sha256": "0" * 64},
    )

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )
    assert exit_code == 1
    assert not any(registry_root.glob("*.json"))
    assert not checkpoint_path(tmp_path).exists()
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").exists()


def test_resume_denied_and_marked_failed_on_implementation_fingerprint_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the Codex BLOCK: an opened holdout resumed under
    changed C1 implementation must fail closed and permanently lock the run
    FAILED (non-resumable) -- it must not continue, and no further holdout
    rows may be replayed after the mismatch is detected."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    manifest_sha = module.manifest_fingerprint(manifest)
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(
        cp_path,
        venue="bitvavo",
        manifest_sha256=manifest_sha,
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
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
    )
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()
    registry_key = registry_key_for(
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        venue="bitvavo",
        candidate_id="C1",
        phase="final_holdout",
    )
    write_registry_entry(
        registry_entry_path(registry_key),
        venue="bitvavo",
        manifest_sha256=manifest_sha,
        source_integrity_composite_sha256="fixed",
        terminal_state="RUNNING",
        opened_run_dir=str(tmp_path),
        implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT,
    )

    # Simulate the C1 implementation having drifted since this run was opened.
    monkeypatch.setattr(
        module,
        "load_frozen_c1_implementation_fingerprint",
        lambda: {"implementation_fingerprint_sha256": "1" * 64},
    )

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code == 1
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"
    assert load_registry_entry(registry_entry_path(registry_key))["terminal_state"] == "FAILED"
    # No further rows were ever replayed after the mismatch was detected.
    assert load_checkpoint(cp_path)["row_count"] == 0
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
    # FAILED is permanently non-resumable: a further --resume must also be denied.
    exit_code_2 = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )
    assert exit_code_2 == 1
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"


# --- Approved frozen split manifest ---------------------------------------

def test_verify_approved_split_manifest_passes_exact_committed_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module
    approved_sha = "e5f00d7f1903f071a33a30eb91ac1f7a510c1b92e251d42059fc40f7ccc86c0f"
    monkeypatch.setattr(module, "manifest_fingerprint", lambda manifest: approved_sha)
    assert module.verify_approved_split_manifest(_manifest()) == approved_sha

@pytest.mark.parametrize("field", ["final_holdout", "discovery", "validation"])
def test_changed_schema_valid_manifest_is_denied_before_db_registry_or_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module
    manifest = _two_asof_manifest()
    manifest["splits"][field]["end"] = "2026-08-22T06:45:00Z"
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root, approve_test_manifest=False)
    calls = {"db": 0, "registry": 0, "replay": 0}
    def forbidden_db():
        calls["db"] += 1
        raise AssertionError("DB must not run")
    def forbidden_registry(*args, **kwargs):
        calls["registry"] += 1
        raise AssertionError("registry must not run")
    def forbidden_replay(**kwargs):
        calls["replay"] += 1
        raise AssertionError("replay must not run")
    monkeypatch.setattr(module, "get_db_connection", forbidden_db)
    monkeypatch.setattr(module, "create_registry_entry_exclusive", forbidden_registry)
    monkeypatch.setattr(module, "evaluate_candidate", forbidden_replay)
    assert module.main(["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]) == 1
    assert calls == {"db": 0, "registry": 0, "replay": 0}
    assert not checkpoint_path(tmp_path).exists()
    assert not (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").exists()
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()

def test_altered_manifest_with_self_consistent_integrity_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module
    manifest = _two_asof_manifest()
    manifest["splits"]["final_holdout"]["end"] = "2026-08-22T06:45:00Z"
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=tmp_path / "_registry", approve_test_manifest=False)
    integrity_calls = {"n": 0}
    def forbidden_integrity(*args, **kwargs):
        integrity_calls["n"] += 1
        raise AssertionError("integrity must not run")
    monkeypatch.setattr(module, "build_integrity_payload", forbidden_integrity)
    assert module.main(["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]) == 1
    assert integrity_calls["n"] == 0

def test_approved_split_manifest_has_no_environment_or_cli_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=_two_asof_manifest())
    monkeypatch.setenv("APPROVED_SPLIT_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(SystemExit):
        module.parse_args(["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--approved-split-manifest-sha256", "0" * 64])
    assert module.main(["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]) == 1

def test_resume_caller_manifest_drift_fails_checkpoint_registry_and_releases_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module
    approved = _two_asof_manifest()
    approved_sha = module.manifest_fingerprint(approved)
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=approved)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)
    monkeypatch.setattr(module, "load_frozen_c1_implementation_fingerprint", lambda: {"approved_split_manifest_sha256": approved_sha})
    cp_path = checkpoint_path(tmp_path)
    write_checkpoint(cp_path, venue="bitvavo", manifest_sha256=approved_sha, source_integrity_composite_sha256="fixed", phase_start=BASE, phase_end=BASE + timedelta(minutes=30), last_completed_asof=None, asofs_completed=0, row_count=0, partial_bytes=0, source_query_count=0, source_rows_read=0, terminal_state="RUNNING", implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT)
    (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").touch()
    key = registry_key_for(manifest_sha256=approved_sha, source_integrity_composite_sha256="fixed", venue="bitvavo", candidate_id="C1", phase="final_holdout")
    registry_path = registry_entry_path(key)
    write_registry_entry(registry_path, venue="bitvavo", manifest_sha256=approved_sha, source_integrity_composite_sha256="fixed", terminal_state="RUNNING", opened_run_dir=str(tmp_path), implementation_fingerprint_sha256=REAL_C1_IMPLEMENTATION_FINGERPRINT)
    drifted = _two_asof_manifest()
    drifted["splits"]["final_holdout"]["end"] = "2026-08-22T06:45:00Z"
    manifest_path.write_text(json.dumps(drifted), encoding="utf-8")
    replay_calls = {"n": 0}
    monkeypatch.setattr(module, "evaluate_candidate", lambda **kwargs: replay_calls.__setitem__("n", replay_calls["n"] + 1))
    assert module.main(["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]) == 1
    assert replay_calls["n"] == 0
    assert load_checkpoint(cp_path)["terminal_state"] == "FAILED"
    assert load_checkpoint(cp_path)["row_count"] == 0
    assert load_registry_entry(registry_path)["terminal_state"] == "FAILED"
    assert not run_lease_path(key).exists()

@pytest.mark.parametrize("frozen", [{}, {"approved_split_manifest_sha256": "not-a-sha"}])
def test_missing_or_malformed_approved_split_manifest_sha_fails_closed(monkeypatch: pytest.MonkeyPatch, frozen: dict[str, object]) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module
    monkeypatch.setattr(module, "load_frozen_c1_implementation_fingerprint", lambda: frozen)
    with pytest.raises(ValueError, match="approved_split_manifest_sha256"):
        module.verify_approved_split_manifest(_manifest())


# --- Approved execution account (exact-head Codex blocker fix) -----------
#
# The registry root used to be keyed purely by the invoking process's
# effective UID (pwd.getpwuid(os.geteuid())). That is per-effective-UID, not
# per-approved-identity: a different local account on the approved host
# resolves its OWN passwd entry and its OWN, distinct registry root, and
# could reopen the identical frozen holdout content there even though the
# host itself is approved. These tests cover the fix:
# ``enforce_approved_execution_account`` + a registry root now bound to the
# single fixed ``APPROVED_EXECUTION_ACCOUNT`` via ``pwd.getpwnam``.


def test_enforce_approved_execution_account_passes_for_approved_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    monkeypatch.setattr(module, "current_trusted_execution_account", lambda: module.APPROVED_EXECUTION_ACCOUNT)
    module.enforce_approved_execution_account()  # must not raise


def test_enforce_approved_execution_account_denies_different_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    monkeypatch.setattr(module, "current_trusted_execution_account", lambda: "a-different-local-account")
    with pytest.raises(ValueError, match="approved account"):
        module.enforce_approved_execution_account()


def test_current_trusted_execution_account_reads_pw_name_via_effective_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account identity must come from pwd.getpwuid(os.geteuid()).pw_name
    -- trusted OS account metadata keyed by the fixed effective UID -- never
    from USER/LOGNAME or any other caller-controlled environment variable."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    monkeypatch.setattr(module.pwd, "getpwuid", lambda uid: _fake_pwent(Path("/unused"), name="real-account"))
    monkeypatch.setenv("USER", "spoofed-account")
    monkeypatch.setenv("LOGNAME", "spoofed-account")
    monkeypatch.setenv("HOME", "/home/spoofed-account")

    assert module.current_trusted_execution_account() == "real-account"


def test_execution_account_cannot_be_spoofed_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """USER/LOGNAME/HOME must not be able to make a denied account pass the
    approved-account check: the trusted identity comes from
    pwd.getpwuid(os.geteuid()), never from these caller-controlled variables."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    monkeypatch.setattr(
        module.pwd, "getpwuid", lambda uid: _fake_pwent(Path("/unused"), name="attacker-account")
    )
    monkeypatch.setenv("USER", module.APPROVED_EXECUTION_ACCOUNT)
    monkeypatch.setenv("LOGNAME", module.APPROVED_EXECUTION_ACCOUNT)
    monkeypatch.setenv("HOME", f"/home/{module.APPROVED_EXECUTION_ACCOUNT}")

    with pytest.raises(ValueError, match="approved account"):
        module.enforce_approved_execution_account()


def test_current_trusted_execution_account_fails_closed_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    def raising_getpwuid(uid: int) -> object:
        raise KeyError(f"getpwuid(): uid not found: {uid}")

    monkeypatch.setattr(module.pwd, "getpwuid", raising_getpwuid)
    with pytest.raises(RuntimeError, match="cannot resolve trusted execution account"):
        module.current_trusted_execution_account()


def test_run_denied_for_different_execution_account_zero_db_calls_zero_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approved host + different effective UID/account must fail closed before
    any DB connection, and must leave behind no registry/checkpoint/partial/
    final output -- the account check runs before manifest loading, DB
    connect, registry creation, checkpoint, source-integrity work, or replay."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    db_calls: list[int] = []

    def denied_get_db_connection() -> _FakeConnection:
        db_calls.append(1)
        raise AssertionError("must not connect to the database for a denied execution account")

    monkeypatch.setattr(module, "get_db_connection", denied_get_db_connection)
    monkeypatch.setattr(module, "current_trusted_execution_account", lambda: "a-different-local-account")

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path)]
    )

    assert exit_code == 1
    assert db_calls == []
    assert not registry_root.exists() or list(registry_root.iterdir()) == []
    assert not checkpoint_path(tmp_path).exists()
    assert not (tmp_path / ".final_holdout_c1_rows_v1.jsonl.partial").exists()
    assert not (tmp_path / "final_holdout_c1_rows_v1.jsonl").exists()
    assert not (tmp_path / "final_holdout_c1_summary_v1.json").exists()


def test_run_denied_for_different_execution_account_on_resume_zero_db_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same account denial must also apply on --resume, before the
    resume path ever reads a checkpoint or touches the registry."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    manifest = _two_asof_manifest()
    manifest_path, integrity_path = _write_run_files(tmp_path, manifest=manifest)
    registry_root = tmp_path / "_registry"
    _install_fake_pipeline(monkeypatch, module, phase_start=BASE, registry_root=registry_root)

    db_calls: list[int] = []

    def denied_get_db_connection() -> _FakeConnection:
        db_calls.append(1)
        raise AssertionError("must not connect to the database for a denied execution account")

    monkeypatch.setattr(module, "get_db_connection", denied_get_db_connection)
    monkeypatch.setattr(module, "current_trusted_execution_account", lambda: "a-different-local-account")

    exit_code = module.main(
        ["--split-manifest", str(manifest_path), "--source-integrity", str(integrity_path), "--resume"]
    )

    assert exit_code == 1
    assert db_calls == []
    assert not checkpoint_path(tmp_path).exists()


def test_approved_account_still_resolves_same_registry_across_home_cwd_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The approved account's registry root must stay identical across a
    changed HOME, a changed current working directory, and a simulated
    different worktree/checkout path -- it is a pure function of the fixed
    approved account's passwd entry, never of any of those caller-selectable
    values."""
    import src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 as module

    approved_home = tmp_path / "approved_account_home"
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: _fake_pwent(approved_home))

    baseline = module.default_registry_root()

    monkeypatch.setenv("HOME", str(tmp_path / "attacker_controlled_home"))
    other_cwd = tmp_path / "worktree_b" / "deep" / "path"
    other_cwd.mkdir(parents=True)
    monkeypatch.chdir(other_cwd)

    assert module.default_registry_root() == baseline
