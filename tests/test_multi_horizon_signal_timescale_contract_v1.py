from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONTRACT_DOC = PROJECT_ROOT / "docs" / "architecture" / "multi_horizon_signal_timescale_contract_v1.md"

ROTATION_PRESSURE_SCORE_MODULE = (
    PROJECT_ROOT / "src" / "reporting" / "market_rotation_pressure_dashboard_v1.py"
)


def _python_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []

    for path in paths:
        if not path.exists():
            continue

        if path.is_file() and path.suffix == ".py":
            files.append(path)
            continue

        if path.is_dir():
            files.extend(
                child
                for child in path.rglob("*.py")
                if "__pycache__" not in child.parts
            )

    return sorted(files)


def _resolve_from_import_module(path: Path, node: ast.ImportFrom) -> str:
    module = node.module or ""

    if node.level == 0:
        return module

    package_parts = list(path.relative_to(PROJECT_ROOT).with_suffix("").parts[:-1])
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
    roots = [PROJECT_ROOT / path for path in relative_paths]
    files = _python_files(roots)
    forbidden = tuple(forbidden_modules)

    violations: list[str] = []

    for file_path in files:
        for lineno, imported in _imports_in_file(file_path):
            if any(_matches_forbidden_module(imported, item) for item in forbidden):
                rel = file_path.relative_to(PROJECT_ROOT)
                violations.append(f"{rel}:{lineno}: imports {imported}")

    assert not violations, reason + "\n" + "\n".join(violations)


def test_decision_gate_has_no_rotation_pressure_or_native_short_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/decision_gate",),
        forbidden_modules=(
            "src.research.run_market_rotation_pressure_v1",
            "src.research.market_rotation_pressure_v1",
            "src.market_data.native_short_map_lifecycle_v1",
            "src.market_data.native_short_scope_status_v1",
            "src.market_data.native_short_map_level_status_v1",
        ),
        reason=(
            "decision_gate is account-aware permission only. It must not "
            "import Rotation Pressure scoring or Native SHORT lifecycle "
            "modules and recompute market-only signal timescale truth."
        ),
    )


def test_execution_planner_has_no_rotation_pressure_or_native_short_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/execution_planner",),
        forbidden_modules=(
            "src.research.run_market_rotation_pressure_v1",
            "src.research.market_rotation_pressure_v1",
            "src.market_data.native_short_map_lifecycle_v1",
            "src.market_data.native_short_scope_status_v1",
            "src.market_data.native_short_map_level_status_v1",
        ),
        reason=(
            "execution_planner creates execution intent only. It must not "
            "independently resolve market-signal timescale disagreement by "
            "importing Rotation Pressure or Native SHORT internals."
        ),
    )


def test_rotation_pressure_dashboard_does_not_recompute_score_components() -> None:
    assert ROTATION_PRESSURE_SCORE_MODULE.exists(), (
        f"Expected reporting module not found: {ROTATION_PRESSURE_SCORE_MODULE}"
    )

    source = ROTATION_PRESSURE_SCORE_MODULE.read_text()

    forbidden_definition_patterns = (
        re.compile(r"def\s+score_return_24h\b"),
        re.compile(r"def\s+score_signed_volume_24h\b"),
        re.compile(r"def\s+score_return_7d\b"),
        re.compile(r"def\s+score_signed_volume_7d\b"),
        re.compile(r"def\s+score_acceleration\b"),
        re.compile(r"def\s+score_market_relative\b"),
        re.compile(r"def\s+score_persistence\b"),
        re.compile(r"\btanh\s*\("),
    )

    violations = [
        pattern.pattern for pattern in forbidden_definition_patterns if pattern.search(source)
    ]

    assert not violations, (
        "Rotation Pressure reporting must read persisted score_total/component "
        "row fields, not define/recompute the scoring functions in the "
        f"renderer: {violations}"
    )

    weighted_sum_pattern = re.compile(r"0\.\d+\s*\*\s*\w*score")
    assert not weighted_sum_pattern.search(source), (
        "Rotation Pressure reporting must not reconstruct the weighted "
        "score_total formula inline."
    )


def test_signal_timescale_contract_doc_exists_and_defines_four_time_concepts() -> None:
    assert CONTRACT_DOC.exists(), f"Missing canonical contract: {CONTRACT_DOC}"

    text = CONTRACT_DOC.read_text()

    for required in (
        "Input interval",
        "Lookback horizon",
        "Effective signal horizon",
        "Observed lifecycle duration",
        "ALIGNED",
        "NESTED",
        "TRANSITIONAL",
        "GENUINELY_CONFLICTING",
        "NOT_COMPARABLE",
    ):
        assert required in text, (
            f"Signal timescale contract is missing required concept: {required}"
        )
