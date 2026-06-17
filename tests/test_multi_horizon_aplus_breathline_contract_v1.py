from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _existing_paths(relative_paths: Iterable[str]) -> list[Path]:
    paths = [PROJECT_ROOT / path for path in relative_paths]
    existing = [path for path in paths if path.exists()]

    if not existing:
        pytest.skip(f"No target paths exist yet: {', '.join(relative_paths)}")

    return existing


def _python_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []

    for path in paths:
        if path.is_file() and path.suffix == ".py":
            files.append(path)
            continue

        if path.is_dir():
            files.extend(
                child
                for child in path.rglob("*.py")
                if "__pycache__" not in child.parts
            )

    if not files:
        pytest.skip("No Python files found in target paths")

    return sorted(files)


def _module_parts_for_file(path: Path) -> list[str]:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)

    if parts[-1] == "__init__":
        return parts[:-1]

    return parts


def _package_parts_for_file(path: Path) -> list[str]:
    parts = _module_parts_for_file(path)

    if path.name == "__init__.py":
        return parts

    return parts[:-1]


def _resolve_from_import_module(path: Path, node: ast.ImportFrom) -> str:
    module = node.module or ""

    if node.level == 0:
        return module

    package_parts = _package_parts_for_file(path)
    ascend = node.level - 1

    if ascend > len(package_parts):
        return "." * node.level + module

    base_parts = package_parts[: len(package_parts) - ascend]
    module_parts = module.split(".") if module else []

    return ".".join([*base_parts, *module_parts])


def _imports_in_file(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))

        elif isinstance(node, ast.ImportFrom):
            base_module = _resolve_from_import_module(path, node)

            if base_module:
                imports.append((node.lineno, base_module))

            for alias in node.names:
                if alias.name == "*":
                    continue

                expanded = (
                    f"{base_module}.{alias.name}"
                    if base_module
                    else alias.name
                )
                imports.append((node.lineno, expanded))

    return imports


def _matches_forbidden_module(imported: str, forbidden: str) -> bool:
    if "." in forbidden:
        return imported == forbidden or imported.startswith(f"{forbidden}.")

    return forbidden in imported.split(".")


def _assert_no_forbidden_imports(
    *,
    relative_paths: Iterable[str],
    forbidden_modules: Iterable[str],
    reason: str,
) -> None:
    roots = _existing_paths(relative_paths)
    files = _python_files(roots)
    forbidden = tuple(forbidden_modules)

    violations: list[str] = []

    for file_path in files:
        for lineno, imported in _imports_in_file(file_path):
            if any(_matches_forbidden_module(imported, item) for item in forbidden):
                rel = file_path.relative_to(PROJECT_ROOT)
                violations.append(f"{rel}:{lineno}: imports {imported}")

    assert not violations, reason + "\n" + "\n".join(violations)


def test_selection_engine_has_no_account_or_execution_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/selection", "src/selection_engine"),
        forbidden_modules=(
            "src.decision_gate",
            "src.execution_planner",
            "src.executor",
            "src.execution",
            "src.account",
            "src.accounts",
            "src.balance",
            "src.balances",
            "src.position",
            "src.positions",
            "src.broker",
            "src.brokers",
            "src.order_submit",
            "broker",
            "brokers",
            "order_submit",
        ),
        reason=(
            "selection_engine must remain market-only and account-agnostic. "
            "It must not import account, broker, decision, execution, or order layers."
        ),
    )


def test_decision_gate_has_no_market_structure_computation_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/decision_gate",),
        forbidden_modules=(
            "src.market_context",
            "src.features",
            "src.market_data.fib_navigation_map",
            "src.aplus",
        ),
        reason=(
            "decision_gate must apply account/risk permission only. "
            "It must not recompute Fibo, Breathline, features, or market context."
        ),
    )


def test_execution_planner_has_no_market_context_or_selection_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/execution_planner",),
        forbidden_modules=(
            "src.market_context",
            "src.features",
            "src.selection",
            "src.selection_engine",
            "src.aplus",
        ),
        reason=(
            "execution_planner must create order intent only. "
            "It must not import or reinterpret market context, selection, or A+."
        ),
    )


def test_executor_has_no_strategy_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/executor", "src/agents"),
        forbidden_modules=(
            "src.selection",
            "src.selection_engine",
            "src.aplus",
            "src.market_context",
        ),
        reason=(
            "executor/agents must handle broker/order execution only. "
            "They must not import strategy, A+, or market-context layers."
        ),
    )


def test_aplus_module_has_no_execution_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/aplus",),
        forbidden_modules=(
            "src.decision_gate",
            "src.execution_planner",
            "src.executor",
            "src.execution",
            "src.broker",
            "src.brokers",
            "src.order_submit",
            "broker",
            "brokers",
            "order_submit",
        ),
        reason=(
            "src.aplus must remain research/context extraction. "
            "It must not import decision, execution, broker, or order-submit layers."
        ),
    )


def test_horizon_labels_are_canonical_set() -> None:
    from src.research.multi_horizon_fib_contract_v1 import FIB_TRADING_HORIZONS

    assert FIB_TRADING_HORIZONS == ("SHORT", "MEDIUM", "LONG")


def test_breathline_factor_names_keep_symbolic_target_research_only() -> None:
    from src.aplus.factor_extractor import map_aplus_signal_to_prediction_factors

    factors = map_aplus_signal_to_prediction_factors(
        phase_label="EXPANSION",
        direction_label="BULLISH",
        confidence_score=Decimal("0.85"),
        target_price=Decimal("50000"),
        target_currency="EUR",
    )

    factor_names = {factor.factor_name for factor in factors}

    assert "breathline_phase" in factor_names
    assert "breathline_direction" in factor_names
    assert "symbolic_target_price" in factor_names

    forbidden_exact_names = {
        "entry_price",
        "exit_price",
        "stop_price",
        "stop_loss",
        "limit_price",
        "ladder",
        "order_quantity",
        "order_size",
        "fill_price",
        "broker_action",
        "execution_action",
    }

    violations = sorted(factor_names & forbidden_exact_names)

    assert not violations, (
        "A+ factor names must remain research/context vocabulary only. "
        f"Forbidden runtime execution terms found: {violations}"
    )


def test_horizon_strategy_state_is_pending_implementation() -> None:
    pytest.skip(
        "HorizonStrategyState is documented in the architecture contract, "
        "but not implemented until a future PR."
    )
