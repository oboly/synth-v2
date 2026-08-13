from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.ops.live_like_runtime_retention_v1 import (
    ALLOWED_RELATIVE_ROOTS,
    RootPlan,
    RunDir,
    apply_plan,
    build_root_plan,
    main,
    resolve_managed_root,
    validate_delete_candidate,
)


def make_run(root: Path, stamp: str, payload: bytes = b"x") -> Path:
    run = root / f"run_{stamp}"
    run.mkdir(parents=True)
    (run / "payload.bin").write_bytes(payload)
    return run


def test_age_and_min_recent_count_both_protect_runs(tmp_path: Path) -> None:
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    old_a = make_run(root, "20260701T000000Z")
    old_b = make_run(root, "20260702T000000Z")
    recent = make_run(root, "20260812T000000Z")

    plan = build_root_plan(
        root=root,
        now_utc=datetime(2026, 8, 13, tzinfo=UTC),
        retention_days=7,
        min_recent_runs=2,
    )

    assert [item.path for item in plan.delete_runs] == [old_a]
    assert old_b not in {item.path for item in plan.delete_runs}
    assert recent not in {item.path for item in plan.delete_runs}


def test_dry_run_is_default_and_does_not_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for relative in ALLOWED_RELATIVE_ROOTS:
        (tmp_path / relative).mkdir(parents=True)
    candidate = make_run(tmp_path / ALLOWED_RELATIVE_ROOTS[0], "20200101T000000Z", b"abc")

    monkeypatch.setattr(
        "src.ops.live_like_runtime_retention_v1.datetime",
        _FixedDateTime,
    )
    result = main(["--repo-root", str(tmp_path), "--retention-days", "7", "--min-recent-runs", "1"])

    assert result == 0
    assert candidate.exists()


def test_apply_deletes_only_planned_canonical_run_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for relative in ALLOWED_RELATIVE_ROOTS:
        (tmp_path / relative).mkdir(parents=True)
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    delete_me = make_run(root, "20200101T000000Z")
    keep_me = make_run(root, "20260812T000000Z")

    monkeypatch.setattr(
        "src.ops.live_like_runtime_retention_v1.datetime",
        _FixedDateTime,
    )
    result = main(
        [
            "--repo-root",
            str(tmp_path),
            "--retention-days",
            "7",
            "--min-recent-runs",
            "1",
            "--apply",
        ]
    )

    assert result == 0
    assert not delete_me.exists()
    assert keep_me.exists()


def test_malformed_run_name_blocks_entire_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for relative in ALLOWED_RELATIVE_ROOTS:
        (tmp_path / relative).mkdir(parents=True)
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    candidate = make_run(root, "20200101T000000Z")
    (root / "run_not-a-timestamp").mkdir()

    monkeypatch.setattr(
        "src.ops.live_like_runtime_retention_v1.datetime",
        _FixedDateTime,
    )
    result = main(
        [
            "--repo-root",
            str(tmp_path),
            "--retention-days",
            "7",
            "--min-recent-runs",
            "1",
            "--apply",
        ]
    )

    assert result == 2
    assert candidate.exists()


def test_symlink_run_entry_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "run_20200101T000000Z").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        build_root_plan(
            root=root,
            now_utc=datetime(2026, 8, 13, tzinfo=UTC),
            retention_days=7,
            min_recent_runs=1,
        )


def test_root_symlink_fails_closed(tmp_path: Path) -> None:
    real_root = tmp_path / "real_root"
    real_root.mkdir()
    relative_root = ALLOWED_RELATIVE_ROOTS[0]
    (tmp_path / relative_root).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / relative_root).symlink_to(real_root, target_is_directory=True)

    with pytest.raises(RuntimeError, match="managed root must not be a symlink"):
        resolve_managed_root(tmp_path, relative_root)


def test_canonical_non_directory_entry_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    root.mkdir(parents=True)
    (root / "run_20200101T000000Z").write_bytes(b"not a directory")

    with pytest.raises(RuntimeError, match="run entry is not a directory"):
        build_root_plan(
            root=root,
            now_utc=datetime(2026, 8, 13, tzinfo=UTC),
            retention_days=7,
            min_recent_runs=1,
        )


def test_missing_root_returns_empty_plan(tmp_path: Path) -> None:
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]

    plan = build_root_plan(
        root=root,
        now_utc=datetime(2026, 8, 13, tzinfo=UTC),
        retention_days=7,
        min_recent_runs=1,
    )

    assert plan.total_runs == 0
    assert plan.delete_runs == ()
    assert plan.malformed_entries == ()


def test_revalidation_fails_closed_when_candidate_replaced_with_symlink_before_delete(
    tmp_path: Path,
) -> None:
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    root.mkdir(parents=True)
    candidate_path = make_run(root, "20200101T000000Z")
    candidate = RunDir(path=candidate_path, timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC), bytes_used=1)

    shutil.rmtree(candidate_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    candidate_path.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="refusing to delete symlink"):
        validate_delete_candidate(root, candidate)


def test_revalidation_fails_closed_when_candidate_removed_before_delete(tmp_path: Path) -> None:
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    root.mkdir(parents=True)
    candidate_path = make_run(root, "20200101T000000Z")
    candidate = RunDir(path=candidate_path, timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC), bytes_used=1)

    shutil.rmtree(candidate_path)

    with pytest.raises(RuntimeError, match="delete candidate is no longer a directory"):
        validate_delete_candidate(root, candidate)


def test_apply_plan_revalidates_each_candidate_before_deleting(tmp_path: Path) -> None:
    root = tmp_path / ALLOWED_RELATIVE_ROOTS[0]
    root.mkdir(parents=True)
    safe_path = make_run(root, "20200101T000000Z")
    swapped_path = make_run(root, "20200102T000000Z")
    safe_candidate = RunDir(path=safe_path, timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC), bytes_used=1)
    swapped_candidate = RunDir(path=swapped_path, timestamp_utc=datetime(2020, 1, 2, tzinfo=UTC), bytes_used=1)

    shutil.rmtree(swapped_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    swapped_path.symlink_to(outside, target_is_directory=True)

    plan = RootPlan(
        root=root,
        total_runs=2,
        retained_runs=0,
        delete_runs=(safe_candidate, swapped_candidate),
        malformed_entries=(),
    )

    with pytest.raises(RuntimeError, match="refusing to delete symlink"):
        apply_plan(plan)

    assert not safe_path.exists()
    assert swapped_path.is_symlink()
    assert outside.exists()


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        value = cls(2026, 8, 13, 7, 0, 0, tzinfo=UTC)
        return value if tz is None else value.astimezone(tz)
