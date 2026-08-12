"""
Architecture-boundary tests for the manual SELL ladder submission
orchestrator (Issue #369). Mirrors the existing import-graph boundary test
pattern in tests/test_manual_execution_p0_architecture_boundaries_v1.py.
"""
from __future__ import annotations

import ast
import pathlib


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_SUBMISSION_MODULES = (
    "manual_execution_client_order_id_v1.py",
    "manual_execution_operator_identity_v1.py",
    "manual_execution_submission_leg_v1.py",
    "manual_execution_submission_orchestrator_v1.py",
    "manual_execution_bitvavo_order_adapter_v1.py",
    "manual_execution_stub_order_adapter_v1.py",
    "manual_live_authorization_v1.py",
    "manual_execution_submission_leg_reconciliation_v1.py",
    "manual_execution_live_authority_v1.py",
    "manual_execution_submission_leg_inmemory_v1.py",
    "manual_execution_live_submission_v1.py",
)


def _imported_module_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


_NON_EXECUTOR_DIRS = (
    "src/selection",
    "src/execution_planner",
    "src/decision_gate",
    "src/reporting",
    "src/advice",
    "src/trade_setup_filter",
)


def test_no_non_executor_layer_imports_the_submission_orchestrator_or_adapters() -> None:
    forbidden = tuple(f"src.executor.{name[:-3]}" for name in _SUBMISSION_MODULES)
    offenders: list[str] = []
    for rel_dir in _NON_EXECUTOR_DIRS:
        directory = _REPO_ROOT / rel_dir
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            imported = _imported_module_names(path)
            for module in forbidden:
                if module in imported:
                    offenders.append(f"{path.relative_to(_REPO_ROOT)} imports {module}")
    assert offenders == [], f"only src/executor may reach manual submission modules: {offenders}"


def test_orchestrator_never_imports_a_broker_client() -> None:
    path = _REPO_ROOT / "src" / "executor" / "manual_execution_submission_orchestrator_v1.py"
    imported = _imported_module_names(path)
    forbidden = (
        "src.execution.bitvavo_client",
        "src.market_data.bitvavo_public_client_v1",
        "src.market_rules.bitvavo_venue_adapter_v1",
    )
    for module in forbidden:
        assert module not in imported, f"orchestrator must not import {module} directly"


def test_only_the_live_bitvavo_adapter_imports_the_broker_client() -> None:
    broker_importing = []
    for name in _SUBMISSION_MODULES:
        if name == "manual_execution_bitvavo_order_adapter_v1.py":
            continue
        path = _REPO_ROOT / "src" / "executor" / name
        imported = _imported_module_names(path)
        if "src.execution.bitvavo_client" in imported:
            broker_importing.append(name)
    assert broker_importing == []


def test_orchestrator_never_imports_credential_decryption() -> None:
    path = _REPO_ROOT / "src" / "executor" / "manual_execution_submission_orchestrator_v1.py"
    imported = _imported_module_names(path)
    assert "src.account_provisioning.credential_crypto_v1" not in imported
    assert "src.account_provisioning.account_credential_loader_v1" not in imported


def test_credential_decryption_confined_to_the_live_adapter() -> None:
    confined = []
    for name in _SUBMISSION_MODULES:
        if name == "manual_execution_bitvavo_order_adapter_v1.py":
            continue
        path = _REPO_ROOT / "src" / "executor" / name
        imported = _imported_module_names(path)
        if "src.account_provisioning.credential_crypto_v1" in imported:
            confined.append(name)
    assert confined == []


def test_no_scheduled_or_automatic_entrypoint_module_exists() -> None:
    # The only operator trigger is the explicit CLI; no cron/systemd runner
    # for manual submission exists in this package.
    executor_dir = _REPO_ROOT / "src" / "executor"
    run_modules = [p.name for p in executor_dir.glob("run_*.py")]
    assert "run_manual_execution_submission_v1.py" in run_modules
    # No second, differently-named "auto"/"scheduled" submission runner.
    suspicious = [
        name for name in run_modules
        if ("auto" in name or "scheduled" in name or "cron" in name) and "manual_execution" in name
    ]
    assert suspicious == []
