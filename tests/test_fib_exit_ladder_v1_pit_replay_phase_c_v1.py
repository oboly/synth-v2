from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

MODULE_NAME = "src.research.run_fib_exit_ladder_v1_pit_replay_phase_c_v1"
MODULE_PATH = Path("src/research/run_fib_exit_ladder_v1_pit_replay_phase_c_v1.py")


def test_phase_c_runner_preserves_frozen_universe_and_defaults() -> None:
    module = importlib.import_module(MODULE_NAME)
    assert tuple(module.DEFAULT_SYMBOLS) == ("LINK", "XLM", "SOL", "XRP", "HOT")
    assert [label for label, _ in module.WINDOWS] == [
        "SELECTION_WINDOW",
        "OOS_WINDOW_1",
        "OOS_WINDOW_2",
    ]
    assert module.METHODOLOGY_VERSION == "FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1"


def test_phase_c_runner_rejects_unfrozen_symbol_scope() -> None:
    module = importlib.import_module(MODULE_NAME)
    with pytest.raises(ValueError, match="frozen universe mismatch"):
        module._parse_symbols("LINK,XLM,SOL,XRP,HOT,SUI")


def test_phase_c_runner_has_no_production_layer_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    forbidden = ("decision_gate", "execution_planner", "executor", "broker", "exit_policy")
    assert not [name for name in imported if any(token in name for token in forbidden)]


def test_phase_c_runner_keeps_promotion_fail_closed_in_source() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert '"methodology_promotion_grade": 0' in source
    assert '"promotion_eligible": False' in source
    assert "connect_read_only()" in source
    assert "conn.rollback()" in source
    assert "conn.close()" in source
