"""Issue #392 Phase 6 blocker A: import/call boundary guards.

Proves: the pure adapter has no broker/credential/live-authority/kill-switch
imports and no reporting/audit JSON parser; it is the sole #392 -> #206
import boundary under src/execution_planner; src/executor core does not
import automatic_exit planner/policy modules; exit_policy candidate/gate
modules do not import src.executor; decision_gate does not import
src.executor; the core planner (automatic_exit_planner_v1.py) does not
import src.executor.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

ADAPTER_MODULE = REPO_ROOT / "src/execution_planner/automatic_exit_execution_handoff_adapter_v1.py"
APPLICATION_MODULE = REPO_ROOT / "src/execution_planner/automatic_exit_execution_handoff_application_v1.py"

NO_EXECUTOR_IMPORT_MODULES = [
    REPO_ROOT / "src/execution_planner/automatic_exit_planner_v1.py",
    REPO_ROOT / "src/exit_policy/automatic_exit_candidate_v1.py",
    REPO_ROOT / "src/exit_policy/automatic_exit_runtime_contract_v1.py",
    REPO_ROOT / "src/decision_gate/automatic_exit_gate_v1.py",
    REPO_ROOT / "src/decision_gate/automatic_exit_live_permission_evaluation_v1.py",
]

FORBIDDEN_ADAPTER_IMPORT_PREFIXES = (
    "src.executor.execution_credential_scope_v1",
    "src.executor.execution_live_authority_v1",
    "src.executor.execution_kill_switch_v1",
    "src.exit_policy.automatic_exit_runtime_audit_writer_v1",
    "requests",
    "httpx",
    "ccxt",
    "python_bitvavo_api",
)


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_adapter_has_no_broker_credential_authority_kill_switch_or_audit_parser_imports() -> None:
    imported = _imported_module_names(ADAPTER_MODULE)
    for name in imported:
        for forbidden in FORBIDDEN_ADAPTER_IMPORT_PREFIXES:
            assert not (name == forbidden or name.startswith(forbidden + ".")), (
                f"adapter imports forbidden module {name}"
            )


def test_adapter_is_the_only_execution_planner_module_importing_executor_plan_reference() -> None:
    execution_planner_dir = REPO_ROOT / "src/execution_planner"
    importers = []
    for path in execution_planner_dir.glob("*.py"):
        if path.name in {"automatic_exit_execution_handoff_adapter_v1.py", "automatic_exit_execution_handoff_application_v1.py"}:
            continue
        imported = _imported_module_names(path)
        if any(name.startswith("src.executor") for name in imported):
            importers.append(path.name)
    assert importers == [], f"unexpected src.executor importers under execution_planner: {importers}"


def test_application_seam_only_imports_the_adapter_and_shared_handoff() -> None:
    imported = _imported_module_names(APPLICATION_MODULE)
    executor_imports = {name for name in imported if name.startswith("src.executor")}
    assert executor_imports <= {"src.executor.execution_handoff_v1"}


@pytest.mark.parametrize("module_path", NO_EXECUTOR_IMPORT_MODULES, ids=lambda p: p.name)
def test_no_392_strategy_or_gate_module_imports_executor(module_path: Path) -> None:
    imported = _imported_module_names(module_path)
    for name in imported:
        assert not (name == "src.executor" or name.startswith("src.executor.")), (
            f"{module_path.name} imports src.executor"
        )


def test_executor_core_does_not_import_automatic_exit_planner_or_policy_modules() -> None:
    executor_dir = REPO_ROOT / "src/executor"
    offenders = []
    for path in executor_dir.glob("*.py"):
        imported = _imported_module_names(path)
        if any(
            name.startswith("src.execution_planner.automatic_exit")
            or name.startswith("src.exit_policy")
            for name in imported
        ):
            offenders.append(path.name)
    assert offenders == [], f"unexpected #392 importers under src/executor: {offenders}"
