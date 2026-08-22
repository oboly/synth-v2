from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.entry_policy.automatic_buy_dry_run_acceptance_v1 as acceptance
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import (
    PLANNER_STATE_NOT_REACHED,
    PLANNER_STATE_STAGED,
    AutomaticBuyRuntimeItemOutcomeV1,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffV1


def _handoff() -> ExecutionHandoffV1:
    return ExecutionHandoffV1(
        handoff_id=9, plan_source="automatic_buy_planner_v1", plan_reference_id="reference",
        plan_content_hash="hash", trading_account_id=3, venue="bitvavo", market="BTC-EUR",
        side="BUY", executor_mode="DRY_RUN", executor_identity="shared-executor-v1",
        runtime_owner="gurkdb", executor_credential_binding_id=None,
    )


def _patch_path(monkeypatch: pytest.MonkeyPatch, outcome: AutomaticBuyRuntimeItemOutcomeV1, handoff):
    runtime_input = SimpleNamespace(automatic_buy_runtime_input_id=7)
    monkeypatch.setattr(acceptance, "write_automatic_buy_runtime_input_v1",
                        lambda conn, *, source: SimpleNamespace(runtime_input=runtime_input, outcome="inserted"))
    monkeypatch.setattr(acceptance, "build_runtime_item_v1", lambda conn, *, runtime_input: "item")
    captured: dict[str, object] = {}

    def compose(conn, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(runtime_outcome=outcome, handoff=handoff)

    monkeypatch.setattr(acceptance, "evaluate_and_handoff_automatic_buy_runtime_item_v1", compose)
    return captured


class Conn:
    def commit(self) -> None:
        pass


def test_dry_run_acceptance_composes_canonical_path_with_null_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_path(
        monkeypatch,
        AutomaticBuyRuntimeItemOutcomeV1("a" * 64, "CANDIDATE", "APPROVED", PLANNER_STATE_STAGED, "inserted"),
        _handoff(),
    )
    result = acceptance.run_automatic_buy_dry_run_acceptance_v1(Conn(), source=object())  # type: ignore[arg-type]
    assert captured["executor_mode_override"] == "DRY_RUN"
    assert captured["runtime_owner"] == "gurkdb"
    assert captured["executor_identity"] == "shared-executor-v1"
    assert result.handoff_id == 9 and result.plan_reference_id == "reference"
    assert result.safety_markers == acceptance.SAFETY_MARKERS


def test_live_flag_gate_rejection_remains_before_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_path(
        monkeypatch,
        AutomaticBuyRuntimeItemOutcomeV1("a" * 64, "CANDIDATE", "DENIED", PLANNER_STATE_NOT_REACHED, "inserted"),
        None,
    )
    result = acceptance.run_automatic_buy_dry_run_acceptance_v1(Conn(), source=object())  # type: ignore[arg-type]
    assert result.gate_state == "DENIED"
    assert result.planner_state == "NOT_REACHED"
    assert result.handoff_id is None


def test_acceptance_imports_only_explicit_handoff_crossing() -> None:
    imports = {
        node.module for node in ast.walk(ast.parse(
            Path("src/entry_policy/automatic_buy_dry_run_acceptance_v1.py").read_text()
        )) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "src.executor.execution_handoff_v1" in imports
    assert not any(name.startswith("src.broker") for name in imports)
    assert not any(name.startswith("src.executor.execution_credential") for name in imports)
