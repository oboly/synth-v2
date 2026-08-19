from __future__ import annotations

import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_canonical_buy_runtime_core_remains_executor_and_broker_free() -> None:
    for path in (
        Path("src/entry_policy/automatic_buy_runtime_contract_v1.py"),
        Path("src/entry_policy/automatic_buy_runtime_repository_v1.py"),
        Path("src/entry_policy/automatic_buy_runtime_orchestrator_v1.py"),
        Path("src/entry_policy/run_automatic_buy_policy_once_v1.py"),
    ):
        imports = _imports(path)
        assert not any(name.startswith("src.executor") for name in imports), path
        assert not any(name.startswith("src.broker") for name in imports), path


def test_executor_crossing_exists_only_in_explicit_handoff_composition_seams() -> None:
    application = _imports(Path("src/entry_policy/automatic_buy_execution_handoff_application_v1.py"))
    composition = _imports(Path("src/entry_policy/automatic_buy_live_handoff_composition_v1.py"))
    assert "src.executor.execution_handoff_v1" in application
    assert "src.executor.execution_handoff_v1" in composition
    assert not any(name.startswith("src.broker") for name in application | composition)


def test_live_composition_never_reads_audit_json_as_execution_input() -> None:
    source = Path("src/entry_policy/automatic_buy_live_handoff_composition_v1.py").read_text()
    assert "immutable_plan_json" not in source
    assert "automatic_buy_evaluation_audit_v1" not in source
    assert "runtime_outcome.plan" in source


def test_phase5_preview_is_explicitly_forbidden_from_live_route() -> None:
    source = Path("src/entry_policy/automatic_buy_execution_handoff_application_v1.py").read_text()
    assert "PHASE6_PREVIEW_NON_PAPER_FORBIDDEN" in source
    assert "intake_live_authorized" in source
    assert source.index("PHASE6_PREVIEW_NON_PAPER_FORBIDDEN") > source.index("submit_automatic_buy_preview_to_shared_handoff_v1")


def test_phase7b_adds_no_live_cli_service_or_buy_specific_executor() -> None:
    assert not Path("src/entry_policy/run_automatic_buy_live_v1.py").exists()
    assert not Path("src/executor/automatic_buy_executor_v1.py").exists()
    assert not Path("deploy/systemd/synth-automatic-buy-live.service").exists()
    assert not Path("deploy/systemd/synth-automatic-buy-live.timer").exists()
