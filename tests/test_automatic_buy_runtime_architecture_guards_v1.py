from __future__ import annotations

import ast
from pathlib import Path


RUNTIME_FILES = (
    Path("src/entry_policy/automatic_buy_runtime_contract_v1.py"),
    Path("src/entry_policy/automatic_buy_runtime_repository_v1.py"),
    Path("src/entry_policy/automatic_buy_runtime_audit_writer_v1.py"),
    Path("src/entry_policy/automatic_buy_runtime_orchestrator_v1.py"),
    Path("src/entry_policy/run_automatic_buy_policy_once_v1.py"),
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


def test_phase4_runtime_has_no_executor_broker_or_manual_execution_imports() -> None:
    forbidden_prefixes = ("src.executor", "src.broker", "src.manual_execution")
    for path in RUNTIME_FILES:
        for imported in _imports(path):
            assert not imported.startswith(forbidden_prefixes), f"{path}: forbidden import {imported}"


def test_orchestrator_uses_canonical_candidate_gate_and_planner() -> None:
    imports = _imports(Path("src/entry_policy/automatic_buy_runtime_orchestrator_v1.py"))
    assert "src.entry_policy.automatic_buy_candidate_v1" in imports
    assert "src.decision_gate.automatic_buy_gate_v1" in imports
    assert "src.execution_planner.automatic_buy_planner_v1" in imports


def test_phase4_migration_is_append_only_and_idempotent() -> None:
    sql = Path("db/migrations/20260819_automatic_buy_runtime_v1.sql").read_text()
    assert "UNIQUE KEY uq_automatic_buy_runtime_source_snapshot" in sql
    assert "UNIQUE KEY uq_automatic_buy_evaluation_idempotency" in sql
    assert "BEFORE UPDATE ON automatic_buy_runtime_input_v1" in sql
    assert "BEFORE DELETE ON automatic_buy_runtime_input_v1" in sql
    assert "BEFORE UPDATE ON automatic_buy_evaluation_audit_v1" in sql
    assert "BEFORE DELETE ON automatic_buy_evaluation_audit_v1" in sql
    assert "executor" in sql.lower()
    assert "broker" in sql.lower()
