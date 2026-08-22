from pathlib import Path

from src.operations.verify_agent_worktree_v1 import (
    CANONICAL_RUNTIME_CHECKOUT,
    evaluate_guard,
)


def test_blocks_non_main_requested_branch_on_canonical_gurkdb_checkout() -> None:
    result = evaluate_guard(
        hostname="gurkdb",
        worktree_path=CANONICAL_RUNTIME_CHECKOUT,
        current_branch="main",
        requested_branch="codex/issue-475-test",
    )

    assert result.allowed is False
    assert "may not be used for non-main branch work" in result.reason


def test_blocks_existing_non_main_branch_on_canonical_gurkdb_checkout() -> None:
    result = evaluate_guard(
        hostname="gurkdb",
        worktree_path=CANONICAL_RUNTIME_CHECKOUT,
        current_branch="feature/wrong-place",
        requested_branch=None,
    )

    assert result.allowed is False
    assert "expected 'main'" in result.reason


def test_blocks_detached_head_on_canonical_gurkdb_checkout() -> None:
    result = evaluate_guard(
        hostname="gurkdb",
        worktree_path=CANONICAL_RUNTIME_CHECKOUT,
        current_branch=None,
        requested_branch=None,
    )

    assert result.allowed is False
    assert "DETACHED" in result.reason


def test_allows_main_on_canonical_gurkdb_checkout() -> None:
    result = evaluate_guard(
        hostname="gurkdb",
        worktree_path=CANONICAL_RUNTIME_CHECKOUT,
        current_branch="main",
        requested_branch="main",
    )

    assert result.allowed is True


def test_allows_separate_gurkdb_worktree_for_feature_branch() -> None:
    result = evaluate_guard(
        hostname="gurkdb",
        worktree_path=Path("/home/gurk/projects/synth-v2-wt-475"),
        current_branch="fix/475-protect-gurkdb-runtime-checkout-v2",
        requested_branch="fix/475-protect-gurkdb-runtime-checkout-v2",
    )

    assert result.allowed is True


def test_allows_other_hosts() -> None:
    result = evaluate_guard(
        hostname="devlap",
        worktree_path=CANONICAL_RUNTIME_CHECKOUT,
        current_branch="feature/example",
        requested_branch="feature/example",
    )

    assert result.allowed is True
