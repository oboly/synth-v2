"""Phase 4B architecture boundary guards.

Proves the new runtime modules do not import executor, broker order
adapters, credential resolution, manual-execution artifacts, or canonical
rounding directly, and do not duplicate target/invalidation strategy
comparisons.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_MODULES = [
    REPO_ROOT / "src/exit_policy/automatic_exit_runtime_repository_v1.py",
    REPO_ROOT / "src/exit_policy/automatic_exit_runtime_orchestrator_v1.py",
    REPO_ROOT / "src/exit_policy/automatic_exit_runtime_audit_writer_v1.py",
    REPO_ROOT / "src/exit_policy/run_automatic_exit_policy_once_v1.py",
]

FORBIDDEN_IMPORT_PREFIXES = (
    "src.executor",
    "src.manual_execution",
    "src.account_provisioning",
    "src.execution_planner.canonical_rounding_v1",
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


@pytest.mark.parametrize("module_path", RUNTIME_MODULES, ids=lambda p: p.name)
def test_runtime_module_has_no_forbidden_imports(module_path: Path) -> None:
    imported = _imported_module_names(module_path)
    for name in imported:
        for forbidden in FORBIDDEN_IMPORT_PREFIXES:
            assert not (name == forbidden or name.startswith(forbidden + ".")), (
                f"{module_path.name} imports forbidden module {name}"
            )


@pytest.mark.parametrize("module_path", RUNTIME_MODULES, ids=lambda p: p.name)
def test_runtime_module_makes_no_order_or_live_authority_calls(module_path: Path) -> None:
    """No call/attribute in these modules may name an order-submission or LIVE-authority operation.

    Checked as actual call/attribute names (not substrings) so the modules'
    own safety-marker text (e.g. "broker_writes=0") does not false-positive.
    """
    forbidden_call_names = {
        "submit_order", "place_order", "cancel_order", "broker_write",
        "grant_live_trading_authorization", "require_live_execution_permission",
    }
    tree = ast.parse(module_path.read_text())
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
        elif isinstance(node, ast.Attribute):
            name = node.attr
        if name is not None:
            assert name not in forbidden_call_names, f"{module_path.name} references forbidden call/attribute {name}"


def test_orchestrator_does_not_compare_target_or_invalidation_itself() -> None:
    """The orchestrator must read target/invalidation only from the exit profile it forwards; it must never branch on them."""
    text = (REPO_ROOT / "src/exit_policy/automatic_exit_runtime_orchestrator_v1.py").read_text()
    # Structural check: no comparison operators applied to target/invalidation identifiers.
    tree = ast.parse(text)
    target_names = {"active_target_price", "invalidation_price", "current_price"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operand_names = set()
            for operand in (node.left, *node.comparators):
                if isinstance(operand, ast.Attribute):
                    operand_names.add(operand.attr)
                elif isinstance(operand, ast.Name):
                    operand_names.add(operand.id)
            assert not (operand_names & target_names), "orchestrator directly compares target/invalidation/price fields"


def test_repository_does_not_choose_reduce_or_exit_action() -> None:
    text = (REPO_ROOT / "src/exit_policy/automatic_exit_runtime_repository_v1.py").read_text()
    assert '"REDUCE"' not in text and '"EXIT"' not in text


def test_repository_delegates_free_quantity_to_decision_gate() -> None:
    text = (REPO_ROOT / "src/exit_policy/automatic_exit_runtime_repository_v1.py").read_text()
    # Free-quantity resolution is shared by the automated and manual-action
    # builders (Issue #653) via _resolve_position_sizing_evidence_v1.
    start = text.index("def _resolve_position_sizing_evidence_v1(")
    end = text.index("def build_manual_action_runtime_item_v1(")
    helper_body = text[start:end]
    assert "resolve_free_base_quantity_core_v1(" in helper_body
    assert "return balance, free_quantity_result.free_base_quantity" in helper_body
    build_start = text.index("def build_runtime_item_v1(")
    build_body = text[build_start:]
    assert "_resolve_position_sizing_evidence_v1(" in build_body
    assert "free_quantity_base=balance.available_amount" not in text
    assert "available_quantity_base -" not in text


def test_repository_uses_no_hardcoded_quote_or_selection_dependency() -> None:
    text = (REPO_ROOT / "src/exit_policy/automatic_exit_runtime_repository_v1.py").read_text()
    assert "-EUR" not in text
    assert "selection_engine" not in text
    for strategy_flag in ("is_candidate_enabled", "is_portfolio_member", "is_order_proposal_enabled"):
        assert strategy_flag not in text


def test_position_market_identity_does_not_reference_tradeability() -> None:
    text = (REPO_ROOT / "src/exit_policy/automatic_exit_runtime_repository_v1.py").read_text()
    start = text.index("def resolve_position_market_v1(")
    end = text.index("\ndef load_latest_market_price(", start)
    assert "is_tradeable" not in text[start:end]


def test_exit_policy_repository_does_not_resolve_decision_gate_live_permission() -> None:
    """Issue #392 Phase 6 blocker B ownership fix: exit_policy must never own or

    resolve decision-gate LIVE permission semantics -- only decision_gate does.
    """
    text = (REPO_ROOT / "src/exit_policy/automatic_exit_runtime_repository_v1.py").read_text()
    assert "automatic_exit_live_permission" not in text


def test_orchestrator_forwards_decision_gate_owned_live_permission_evaluation() -> None:
    """The orchestrator composes the already-typed decision_gate result; it never resolves permission itself."""
    text = (REPO_ROOT / "src/exit_policy/automatic_exit_runtime_orchestrator_v1.py").read_text()
    assert "from src.decision_gate.automatic_exit_live_permission_evaluation_v1 import" in text
    assert "automatic_exit_live_permission_contract_v1" not in text
    assert "automatic_exit_live_permission_repository_v1" not in text
