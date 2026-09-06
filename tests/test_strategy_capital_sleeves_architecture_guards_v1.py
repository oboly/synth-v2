"""Issue #752 architecture guards: layer-boundary proof, not behavior.

23. selection_engine must never import account/balance/sleeve/ledger code.
24. execution_planner must never compute sleeve/capacity policy.
25. executor must never compute sleeve/capacity policy.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_SLEEVE_MODULES = (
    "src.decision_gate.strategy_bucket_capacity_v1",
    "src.decision_gate.strategy_owned_inventory_ledger_v1",
    "src.decision_gate.strategy_owned_inventory_ledger_repository_v1",
    "src.decision_gate.strategy_bucket_account_config_contract_v1",
    "src.decision_gate.strategy_bucket_account_config_repository_v1",
    "src.decision_gate.strategy_bucket_participation_evaluation_v1",
)

FORBIDDEN_ACCOUNT_MODULES = (
    "src.account",
    "src.decision_gate",
    "src.executor",
    "src.broker",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_selection_engine_has_no_account_or_sleeve_imports() -> None:
    selection_dir = REPO_ROOT / "src" / "selection"
    assert selection_dir.is_dir(), "src/selection/ must exist for this guard to be meaningful"
    py_files = list(selection_dir.rglob("*.py"))
    assert py_files, "expected at least one selection_engine module to scan"
    for path in py_files:
        for imported in _imports(path):
            assert not imported.startswith(FORBIDDEN_ACCOUNT_MODULES), (
                f"{path}: selection_engine must stay market-only/account-agnostic, "
                f"found forbidden import {imported}"
            )


def test_execution_planner_does_not_import_sleeve_capacity_or_ledger_modules() -> None:
    planner_dir = REPO_ROOT / "src" / "execution_planner"
    py_files = list(planner_dir.rglob("*.py"))
    assert py_files
    for path in py_files:
        for imported in _imports(path):
            assert imported not in FORBIDDEN_SLEEVE_MODULES, (
                f"{path}: execution_planner must not compute sleeve/allocation "
                f"policy, found forbidden import {imported}"
            )


def test_executor_does_not_import_sleeve_capacity_or_ledger_modules() -> None:
    executor_dir = REPO_ROOT / "src" / "executor"
    py_files = list(executor_dir.rglob("*.py"))
    assert py_files
    for path in py_files:
        for imported in _imports(path):
            assert imported not in FORBIDDEN_SLEEVE_MODULES, (
                f"{path}: executor must not compute sleeve/allocation policy, "
                f"found forbidden import {imported}"
            )
