from __future__ import annotations

import argparse
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

RETENTION_VERSION = "1.0"
DEFAULT_RETENTION_DAYS = 7
DEFAULT_MIN_RECENT_RUNS = 288
RUN_DIR_RE = re.compile(r"^run_(\d{8}T\d{6}Z)$")

ALLOWED_RELATIVE_ROOTS = (
    Path("data/research/live_like_shadow_event_v1"),
    Path("data/research/live_like_shadow_chain_v1"),
    Path("data/research/live_like_execution_plan_preview_v1"),
    Path("data/research/live_like_decision_preview_v1"),
    Path("data/research/intraday_retest_reclaim_candidate_v1"),
)


@dataclass(frozen=True)
class RunDir:
    path: Path
    timestamp_utc: datetime
    bytes_used: int


@dataclass(frozen=True)
class RootPlan:
    root: Path
    total_runs: int
    retained_runs: int
    delete_runs: tuple[RunDir, ...]
    malformed_entries: tuple[Path, ...]

    @property
    def reclaim_bytes(self) -> int:
        return sum(run.bytes_used for run in self.delete_runs)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bound retention for Odroid live-like runtime run directories. Dry-run is the default."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--min-recent-runs", type=int, default=DEFAULT_MIN_RECENT_RUNS)
    parser.add_argument("--apply", action="store_true", help="Delete planned candidates. Without this flag no data is removed.")
    args = parser.parse_args(argv)
    if args.retention_days < 1:
        parser.error("--retention-days must be >= 1")
    if args.min_recent_runs < 1:
        parser.error("--min-recent-runs must be >= 1")
    return args


def parse_run_timestamp(name: str) -> datetime | None:
    match = RUN_DIR_RE.fullmatch(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def path_size_bytes(path: Path) -> int:
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise RuntimeError(f"symlink encountered inside managed run directory: {entry.path}")
                stat = entry.stat(follow_symlinks=False)
                total += stat.st_size
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
    return total


def resolve_managed_root(repo_root: Path, relative_root: Path) -> Path:
    repo_resolved = repo_root.resolve(strict=True)
    root = repo_resolved / relative_root
    if not root.exists():
        return root
    if root.is_symlink():
        raise RuntimeError(f"managed root must not be a symlink: {root}")
    root_resolved = root.resolve(strict=True)
    try:
        root_resolved.relative_to(repo_resolved)
    except ValueError as exc:
        raise RuntimeError(f"managed root escapes repo root: {root}") from exc
    return root_resolved


def inventory_root(root: Path) -> tuple[list[RunDir], list[Path]]:
    if not root.exists():
        return [], []
    if not root.is_dir():
        raise RuntimeError(f"managed root is not a directory: {root}")

    runs: list[RunDir] = []
    malformed: list[Path] = []
    for entry in root.iterdir():
        timestamp = parse_run_timestamp(entry.name)
        if timestamp is None:
            if entry.name.startswith("run_"):
                malformed.append(entry)
            continue
        if entry.is_symlink():
            raise RuntimeError(f"run directory must not be a symlink: {entry}")
        if not entry.is_dir():
            raise RuntimeError(f"run entry is not a directory: {entry}")
        runs.append(RunDir(path=entry, timestamp_utc=timestamp, bytes_used=path_size_bytes(entry)))

    runs.sort(key=lambda item: item.timestamp_utc, reverse=True)
    malformed.sort(key=lambda path: path.name)
    return runs, malformed


def build_root_plan(
    *,
    root: Path,
    now_utc: datetime,
    retention_days: int,
    min_recent_runs: int,
) -> RootPlan:
    runs, malformed = inventory_root(root)
    cutoff = now_utc - timedelta(days=retention_days)
    protected_paths = {run.path for run in runs[:min_recent_runs]}
    delete_runs = tuple(
        run
        for run in runs
        if run.path not in protected_paths and run.timestamp_utc < cutoff
    )
    return RootPlan(
        root=root,
        total_runs=len(runs),
        retained_runs=len(runs) - len(delete_runs),
        delete_runs=delete_runs,
        malformed_entries=tuple(malformed),
    )


def validate_delete_candidate(root: Path, candidate: RunDir) -> None:
    if candidate.path.is_symlink():
        raise RuntimeError(f"refusing to delete symlink: {candidate.path}")
    if not candidate.path.is_dir():
        raise RuntimeError(f"delete candidate is no longer a directory: {candidate.path}")
    if parse_run_timestamp(candidate.path.name) is None:
        raise RuntimeError(f"delete candidate no longer has canonical run name: {candidate.path}")
    if candidate.path.parent.resolve(strict=True) != root.resolve(strict=True):
        raise RuntimeError(f"delete candidate escaped managed root: {candidate.path}")


def apply_plan(plan: RootPlan) -> int:
    removed = 0
    for candidate in plan.delete_runs:
        validate_delete_candidate(plan.root, candidate)
        shutil.rmtree(candidate.path)
        removed += 1
    return removed


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root)
    now_utc = datetime.now(UTC)

    plans: list[RootPlan] = []
    for relative_root in ALLOWED_RELATIVE_ROOTS:
        root = resolve_managed_root(repo_root, relative_root)
        plans.append(
            build_root_plan(
                root=root,
                now_utc=now_utc,
                retention_days=args.retention_days,
                min_recent_runs=args.min_recent_runs,
            )
        )

    malformed = [entry for plan in plans for entry in plan.malformed_entries]
    if malformed:
        print("status=BLOCKED reason=malformed_run_entries")
        for entry in malformed:
            print(f"malformed={entry}")
        return 2

    total_delete = sum(len(plan.delete_runs) for plan in plans)
    total_bytes = sum(plan.reclaim_bytes for plan in plans)
    mode = "APPLY" if args.apply else "DRY_RUN"
    print(
        f"status=PLAN mode={mode} retention_days={args.retention_days} "
        f"min_recent_runs={args.min_recent_runs} delete_runs={total_delete} "
        f"reclaim={human_bytes(total_bytes)}"
    )
    for plan in plans:
        print(
            f"root={plan.root} total_runs={plan.total_runs} retained_runs={plan.retained_runs} "
            f"delete_runs={len(plan.delete_runs)} reclaim={human_bytes(plan.reclaim_bytes)}"
        )
        for candidate in plan.delete_runs:
            print(
                f"candidate={candidate.path} ts={candidate.timestamp_utc.isoformat()} "
                f"bytes={candidate.bytes_used}"
            )

    if not args.apply:
        return 0

    removed = 0
    for plan in plans:
        removed += apply_plan(plan)
    print(f"status=APPLIED removed_runs={removed} reclaimed_planned={human_bytes(total_bytes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
