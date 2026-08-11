from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONTRACT_DOC = PROJECT_ROOT / "docs" / "architecture" / "multi_horizon_signal_timescale_contract_v1.md"


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


def _dotted_module_name(path: Path) -> str:
    return ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)


def _modules_matching(relative_root: str, name_substrings: Iterable[str]) -> tuple[str, ...]:
    """Discover dotted module names under a package by filename substring,
    rather than hand-maintaining a fixed module list that silently misses
    files added or renamed later."""

    files = _python_files([PROJECT_ROOT / relative_root])
    substrings = tuple(name_substrings)

    return tuple(
        sorted(
            _dotted_module_name(file_path)
            for file_path in files
            if any(substring in file_path.name for substring in substrings)
        )
    )


ROTATION_PRESSURE_MODULES = _modules_matching("src/research", ("rotation_pressure",))
NATIVE_SHORT_MODULES = _modules_matching("src/market_data", ("native_short",))
ROTATION_PRESSURE_REPORTING_MODULES = _modules_matching(
    "src/reporting", ("rotation_pressure",)
)


def test_signal_timescale_module_discovery_finds_expected_lanes() -> None:
    # Sanity check on the discovery helper itself: if these come back empty,
    # the forbidden-import and recomputation guards below would silently
    # pass over nothing.
    assert ROTATION_PRESSURE_MODULES, "No Rotation Pressure modules discovered under src/research"
    assert NATIVE_SHORT_MODULES, "No Native SHORT modules discovered under src/market_data"
    assert ROTATION_PRESSURE_REPORTING_MODULES, (
        "No Rotation Pressure reporting modules discovered under src/reporting"
    )


def test_decision_gate_has_no_rotation_pressure_or_native_short_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/decision_gate",),
        forbidden_modules=ROTATION_PRESSURE_MODULES + NATIVE_SHORT_MODULES,
        reason=(
            "decision_gate is account-aware permission only. It must not "
            "import any Rotation Pressure or Native SHORT market-data/research "
            "module and recompute market-only signal timescale truth."
        ),
    )


def test_execution_planner_has_no_rotation_pressure_or_native_short_imports() -> None:
    _assert_no_forbidden_imports(
        relative_paths=("src/execution_planner",),
        forbidden_modules=ROTATION_PRESSURE_MODULES + NATIVE_SHORT_MODULES,
        reason=(
            "execution_planner creates execution intent only. It must not "
            "independently resolve market-signal timescale disagreement by "
            "importing any Rotation Pressure or Native SHORT module."
        ),
    )


def test_rotation_pressure_reporting_does_not_import_scoring_modules() -> None:
    """Dependency/data-flow guard: reporting must consume persisted rows,
    not import the research module that computes the score."""

    violations: list[str] = []

    for module in ROTATION_PRESSURE_REPORTING_MODULES:
        file_path = PROJECT_ROOT / Path(*module.split("."))
        file_path = file_path.with_suffix(".py")

        for lineno, imported in _imports_in_file(file_path):
            if imported in ROTATION_PRESSURE_MODULES:
                violations.append(f"{module}:{lineno}: imports {imported}")

    assert not violations, (
        "Rotation Pressure reporting must not import the scoring research "
        f"module directly: {violations}"
    )


def test_rotation_pressure_dashboard_does_not_recompute_score_components() -> None:
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
    weighted_sum_pattern = re.compile(r"0\.\d+\s*\*\s*\w*score")

    for module in ROTATION_PRESSURE_REPORTING_MODULES:
        file_path = PROJECT_ROOT / Path(*module.split("."))
        file_path = file_path.with_suffix(".py")
        source = file_path.read_text()

        violations = [
            pattern.pattern for pattern in forbidden_definition_patterns if pattern.search(source)
        ]

        assert not violations, (
            f"{module} must read persisted score_total/component row fields, "
            f"not define/recompute the scoring functions in the renderer: {violations}"
        )

        assert not weighted_sum_pattern.search(source), (
            f"{module} must not reconstruct the weighted score_total formula "
            "inline."
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


def test_signal_timescale_contract_defines_required_semantic_sections() -> None:
    text = CONTRACT_DOC.read_text()

    required_sections = (
        "## The Four Time Concepts",
        "## Signal/Lane Inventory",
        "## Empirical Duration Findings",
        "## Horizon Composition Semantics",
        "## Precedence and Combination Rules",
        "## Horizon Identity and Provenance Contract",
        "## Guard Expectations",
    )

    for section in required_sections:
        assert section in text, (
            f"Signal timescale contract is missing required section: {section}"
        )


def test_signal_timescale_contract_defines_native_short_coverage_and_ordering() -> None:
    """Keep the two measurement safety rules explicit without parsing prose."""

    text = CONTRACT_DOC.read_text()

    required_rules = (
        "coverage_cutoff_utc <= metric_start_ts",
        "coverage_cutoff_utc > metric_start_ts",
        "requested start→target interval is `LEFT_TRUNCATED` / `UNAVAILABLE`",
        "LEFT_TRUNCATED",
        "RIGHT_CENSORED",
        "LEGACY_UNAVAILABLE",
        "FULLY_OBSERVED",
        "coverage_cutoff_utc→target_event_ts",
        "PARTIAL_OBSERVED_INTERVAL",
        "separately from `FULLY_OBSERVED` start→target statistics",
        "(effective_at_utc ASC, target_event_id ASC)",
    )

    for rule in required_rules:
        assert rule in text, f"Signal timescale contract is missing Native SHORT rule: {rule}"


def test_signal_timescale_contract_lane_inventory_is_structurally_consistent() -> None:
    """Validate the inventory as a structured table (consistent column count,
    required lanes present) rather than only checking for isolated strings."""

    text = CONTRACT_DOC.read_text()
    table_rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ") and not line.startswith("|---")
    ]

    assert table_rows, "Signal timescale contract must contain a structured lane inventory table"

    header = table_rows[0]
    column_count = header.count("|")
    assert column_count >= 9, (
        "Lane inventory header has fewer columns than the required four-"
        f"time-concept structure implies: {header}"
    )

    for row in table_rows[1:]:
        assert row.count("|") == column_count, (
            f"Inventory row has inconsistent column count vs. header: {row[:80]}"
        )

    required_lanes = (
        "Market Rotation Pressure",
        "Native SHORT Fibonacci",
        "Breathline",
    )
    for lane in required_lanes:
        assert any(lane in row for row in table_rows[1:]), (
            f"Lane inventory table is missing a row for required lane: {lane}"
        )
