from __future__ import annotations

import ast
from pathlib import Path

from src.research.multi_horizon_fib_contract_v1 import (
    FIB_TRADING_HORIZONS,
    HORIZON_MATRIX,
    INTERVAL_ROLE_PRIMARY,
    INTERVAL_ROLE_SUPPORT,
    get_horizon_definition,
)


def test_canonical_horizon_matrix_is_exact() -> None:
    assert FIB_TRADING_HORIZONS == ("SHORT", "MEDIUM", "LONG")
    assert HORIZON_MATRIX == {
        "SHORT": {
            "primary_interval": "4h",
            "supporting_intervals": ("1h",),
            "parent_horizon": "MEDIUM",
            "child_horizon": None,
            "live_window_days": 60,
        },
        "MEDIUM": {
            "primary_interval": "1d",
            "supporting_intervals": ("4h",),
            "parent_horizon": "LONG",
            "child_horizon": "SHORT",
            "live_window_days": 365,
        },
        "LONG": {
            "primary_interval": "1w",
            "supporting_intervals": ("1d",),
            "parent_horizon": None,
            "child_horizon": "MEDIUM",
            "live_window_days": 365 * 4,
        },
    }


def test_parent_child_relationships_are_exact() -> None:
    short = get_horizon_definition("SHORT")
    medium = get_horizon_definition("MEDIUM")
    long = get_horizon_definition("LONG")
    assert short.parent_horizon == "MEDIUM"
    assert short.child_horizon is None
    assert medium.parent_horizon == "LONG"
    assert medium.child_horizon == "SHORT"
    assert long.parent_horizon is None
    assert long.child_horizon == "MEDIUM"


def test_interval_role_is_separate_from_trading_horizon() -> None:
    medium = get_horizon_definition("MEDIUM")
    assert medium.fib_trading_horizon == "MEDIUM"
    assert medium.primary_interval == "1d"
    assert medium.supporting_intervals == ("4h",)
    assert INTERVAL_ROLE_PRIMARY == "PRIMARY"
    assert INTERVAL_ROLE_SUPPORT == "SUPPORT"


def test_contract_has_no_forbidden_import_strings() -> None:
    source = Path("src/research/multi_horizon_fib_contract_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for forbidden in ("decision_gate", "execution_planner", "executor"):
                assert forbidden not in module
    for forbidden in ("placeOrder", "cancelOrder", "create order"):
        assert forbidden not in source


def main() -> None:
    test_canonical_horizon_matrix_is_exact()
    test_parent_child_relationships_are_exact()
    test_interval_role_is_separate_from_trading_horizon()
    test_contract_has_no_forbidden_import_strings()
    print("ok")


if __name__ == "__main__":
    main()
