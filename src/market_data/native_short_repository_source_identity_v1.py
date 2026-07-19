from __future__ import annotations

"""Fail-closed source identity for native SHORT production writer entrypoints."""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenance,
    NativeShortWriterProvenanceError,
    build_process_provenance,
    validate_native_short_writer_provenance,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTROLLED_CHAIN_4H_UNTRACKED_PATH = (
    "docs/todo/replay_parameter_study_harness_v1.md"
)
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class NativeShortRepositorySourceIdentityError(NativeShortWriterProvenanceError):
    pass


@dataclass(frozen=True)
class NativeShortRepositorySourceState:
    head_sha: str
    status_porcelain: str


NativeShortRepositorySourceInspector = Callable[[], NativeShortRepositorySourceState]


def _run_git(args: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_IDENTITY_UNAVAILABLE"
        ) from exc
    if completed.returncode != 0:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_IDENTITY_UNAVAILABLE"
        )
    return completed.stdout.rstrip("\n")


def inspect_running_repository_source() -> NativeShortRepositorySourceState:
    top_level = _run_git(("rev-parse", "--show-toplevel"))
    try:
        resolved_top_level = Path(top_level).resolve(strict=True)
        resolved_repository_root = REPOSITORY_ROOT.resolve(strict=True)
    except OSError as exc:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_IDENTITY_UNAVAILABLE"
        ) from exc
    if resolved_top_level != resolved_repository_root:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_ROOT_MISMATCH"
        )

    head_sha = _run_git(("rev-parse", "--verify", "HEAD^{commit}"))
    status_porcelain = _run_git(("status", "--porcelain=v1", "--untracked-files=all"))
    return NativeShortRepositorySourceState(
        head_sha=head_sha,
        status_porcelain=status_porcelain,
    )


def _validate_allowed_untracked_path(
    allowed_untracked_path: str | None,
) -> str | None:
    if allowed_untracked_path is None:
        return None
    if allowed_untracked_path != CONTROLLED_CHAIN_4H_UNTRACKED_PATH:
        raise NativeShortRepositorySourceIdentityError(
            "CONTROLLED_UNTRACKED_PATH_NOT_ALLOWED"
        )
    return allowed_untracked_path


def _dirty_counts(
    status_porcelain: str,
    *,
    allowed_untracked_path: str | None = None,
) -> tuple[int, int, int]:
    staged = 0
    unstaged = 0
    untracked = 0
    allowed_untracked_line = (
        f"?? {allowed_untracked_path}" if allowed_untracked_path is not None else None
    )
    for line in status_porcelain.splitlines():
        if not line:
            continue
        if line.startswith("??"):
            if line == allowed_untracked_line:
                continue
            untracked += 1
            continue
        if len(line) < 2:
            staged += 1
            continue
        if line[0] != " ":
            staged += 1
        if line[1] != " ":
            unstaged += 1
    return staged, unstaged, untracked


def verify_native_short_repository_source_identity(
    provenance: NativeShortWriterProvenance,
    *,
    allowed_untracked_path: str | None = None,
    inspect_repository_source: NativeShortRepositorySourceInspector = (
        inspect_running_repository_source
    ),
) -> NativeShortWriterProvenance:
    """Verify exact production source without requiring Git for TEST provenance."""
    allowed_untracked_path = _validate_allowed_untracked_path(allowed_untracked_path)
    validate_native_short_writer_provenance(provenance)
    mode = NativeShortWriterExecutionMode(str(provenance.execution_mode))
    if mode == NativeShortWriterExecutionMode.TEST:
        return provenance

    verify_repository_commit_sha(
        provenance.repository_commit_sha,
        allowed_untracked_path=allowed_untracked_path,
        inspect_repository_source=inspect_repository_source,
    )
    return provenance


def verify_repository_commit_sha(
    repository_commit_sha: str,
    *,
    allowed_untracked_path: str | None = None,
    inspect_repository_source: NativeShortRepositorySourceInspector = (
        inspect_running_repository_source
    ),
) -> NativeShortRepositorySourceState:
    allowed_untracked_path = _validate_allowed_untracked_path(allowed_untracked_path)
    if _SHA_PATTERN.fullmatch(repository_commit_sha) is None:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_COMMIT_SHA_INVALID"
        )

    try:
        state = inspect_repository_source()
    except NativeShortRepositorySourceIdentityError:
        raise
    except Exception as exc:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_IDENTITY_UNAVAILABLE"
        ) from exc

    if _SHA_PATTERN.fullmatch(state.head_sha) is None:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_HEAD_INVALID"
        )
    if repository_commit_sha != state.head_sha:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_COMMIT_MISMATCH"
        )

    staged, unstaged, untracked = _dirty_counts(
        state.status_porcelain,
        allowed_untracked_path=allowed_untracked_path,
    )
    if staged or unstaged or untracked:
        raise NativeShortRepositorySourceIdentityError(
            "REPOSITORY_CHECKOUT_DIRTY "
            f"staged={staged} unstaged={unstaged} untracked={untracked}"
        )
    return state


def build_verified_process_provenance(
    *,
    writer_entrypoint: str,
    runner_name: str,
    runner_version: str,
    execution_mode: NativeShortWriterExecutionMode | str,
    repository_commit_sha: str,
    trigger_type: str,
    trigger_ref: str,
    invocation_uuid: str | None = None,
    allowed_untracked_path: str | None = None,
    inspect_repository_source: NativeShortRepositorySourceInspector = (
        inspect_running_repository_source
    ),
) -> NativeShortWriterProvenance:
    provenance = build_process_provenance(
        writer_entrypoint=writer_entrypoint,
        runner_name=runner_name,
        runner_version=runner_version,
        execution_mode=execution_mode,
        repository_commit_sha=repository_commit_sha,
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
        invocation_uuid=invocation_uuid,
    )
    return verify_native_short_repository_source_identity(
        provenance,
        allowed_untracked_path=allowed_untracked_path,
        inspect_repository_source=inspect_repository_source,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify exact clean repository source identity before writer execution."
    )
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--allowed-untracked-path")
    args = parser.parse_args(argv)
    try:
        verify_repository_commit_sha(
            args.repository_commit,
            allowed_untracked_path=args.allowed_untracked_path,
        )
    except NativeShortRepositorySourceIdentityError as exc:
        print(f"INVALID_REPOSITORY_SOURCE detail={exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
