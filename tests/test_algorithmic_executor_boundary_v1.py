import ast
from pathlib import Path


CANONICAL_MODULES = (
    "execution_credential_scope_v1.py",
    "_trusted_clock_v1.py",
    "execution_plan_reference_v1.py",
    "execution_handoff_v1.py",
    "execution_client_order_id_v1.py",
    "execution_leg_v1.py",
    "broker_ack_classification_v1.py",
    "execution_submission_orchestrator_v1.py",
    "stub_order_adapter_v1.py",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "src.selection_engine",
    "src.selection",
    "src.entry_policy",
    "src.exit_policy",
    "src.decision_gate",
    "src.execution_planner",
    "src.manual_execution",
    "src.executor.manual_execution_",
)
FORBIDDEN_EXECUTOR_TERMS = (
    "target_price",
    "invalidation",
    "allocation",
    "free_quantity",
    "ladder_spacing",
    "rounding",
    "market_ranking",
)


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_shared_executor_boundary_documents_both_lanes_and_live_denial() -> None:
    text = Path("docs/architecture/algorithmic_executor_boundary_v1.md").read_text()
    assert "#392" in text and "#399" in text
    assert "denied" in text and "RECONCILIATION_REQUIRED" in text
    assert "10eba297" in text and "historical donor" in text


def test_all_canonical_executor_modules_respect_import_boundaries() -> None:
    executor_root = Path("src/executor")
    for filename in CANONICAL_MODULES:
        modules = imported_modules(executor_root / filename)
        assert not any(
            module.startswith(prefix)
            for module in modules
            for prefix in FORBIDDEN_IMPORT_PREFIXES
        ), (filename, modules)


def test_canonical_executor_contains_no_strategy_or_planning_logic() -> None:
    executor_root = Path("src/executor")
    combined = "\n".join(
        (executor_root / filename).read_text().lower()
        for filename in CANONICAL_MODULES
    )
    for forbidden_term in FORBIDDEN_EXECUTOR_TERMS:
        assert forbidden_term not in combined


def test_only_manual_compatibility_module_imports_the_canonical_scope() -> None:
    compatibility = Path("src/executor/manual_execution_credential_scope_v1.py")
    modules = imported_modules(compatibility)
    assert "src.executor.execution_credential_scope_v1" in modules
    canonical_modules = imported_modules(Path("src/executor/execution_credential_scope_v1.py"))
    assert not any("manual_execution" in module for module in canonical_modules)
