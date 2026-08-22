from __future__ import annotations

import argparse
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

CANONICAL_HOST = "gurkdb"
CANONICAL_RUNTIME_CHECKOUT = Path("/home/gurk/projects/synth-v2")
CANONICAL_RUNTIME_BRANCH = "main"


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str


def evaluate_guard(
    *,
    hostname: str,
    worktree_path: Path,
    current_branch: str | None,
    requested_branch: str | None,
) -> GuardResult:
    resolved_path = worktree_path.expanduser().resolve()

    if hostname != CANONICAL_HOST:
        return GuardResult(True, "host_not_canonical_runtime_owner")

    if resolved_path != CANONICAL_RUNTIME_CHECKOUT:
        return GuardResult(True, "worktree_not_canonical_runtime_checkout")

    if current_branch != CANONICAL_RUNTIME_BRANCH:
        branch = current_branch or "DETACHED"
        return GuardResult(
            False,
            f"canonical runtime checkout branch is {branch!r}; expected 'main'",
        )

    if requested_branch is not None and requested_branch != CANONICAL_RUNTIME_BRANCH:
        return GuardResult(
            False,
            "canonical runtime checkout may not be used for non-main branch work; "
            f"requested={requested_branch!r}",
        )

    return GuardResult(True, "canonical_runtime_checkout_main_only")


def _current_branch(worktree_path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(worktree_path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    branch = completed.stdout.strip()
    return branch or None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed when agent/development work tries to use the canonical "
            "gurkDB runtime checkout for non-main branch work."
        )
    )
    parser.add_argument(
        "--worktree-path",
        default=".",
        help="Repository/worktree path to validate (default: current directory).",
    )
    parser.add_argument(
        "--requested-branch",
        default=None,
        help="Branch the caller intends to use/create in this worktree.",
    )
    args = parser.parse_args()

    worktree_path = Path(args.worktree_path)
    try:
        current_branch = _current_branch(worktree_path)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"FAIL guard=agent_worktree_v1 reason=git_branch_probe_failed detail={exc}")
        return 3

    result = evaluate_guard(
        hostname=socket.gethostname(),
        worktree_path=worktree_path,
        current_branch=current_branch,
        requested_branch=args.requested_branch,
    )

    status = "PASS" if result.allowed else "FAIL"
    print(
        f"{status} guard=agent_worktree_v1 "
        f"host={socket.gethostname()} "
        f"worktree={worktree_path.expanduser().resolve()} "
        f"current_branch={current_branch or 'DETACHED'} "
        f"requested_branch={args.requested_branch or 'NONE'} "
        f"reason={result.reason}"
    )
    return 0 if result.allowed else 3


if __name__ == "__main__":
    raise SystemExit(main())
