from __future__ import annotations

import ast
from pathlib import Path

WRITER_FILE = Path("src/entry_policy/automatic_buy_source_runtime_input_writer_v1.py")
CLI_FILE = Path("src/entry_policy/run_automatic_buy_dry_run_acceptance_v1.py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_source_writer_has_no_executor_broker_or_credential_imports() -> None:
    forbidden_prefixes = (
        "src.executor", "src.broker", "src.manual_execution",
        "src.executor.execution_credential_scope_v1",
        "src.executor.execution_live_authority_v1",
        "src.executor.execution_kill_switch_v1",
    )
    for imported in _imports(WRITER_FILE):
        assert not imported.startswith(forbidden_prefixes), f"{WRITER_FILE}: forbidden import {imported}"


def test_cli_has_no_credential_or_live_authority_imports() -> None:
    forbidden_prefixes = (
        "src.broker",
        "src.manual_execution",
        "src.executor.execution_credential_scope_v1",
        "src.executor.execution_live_authority_v1",
        "src.executor.execution_kill_switch_v1",
    )
    imports = _imports(CLI_FILE)
    for imported in imports:
        assert not imported.startswith(forbidden_prefixes), f"{CLI_FILE}: forbidden import {imported}"
    # The only permitted executor crossing is the shared side-neutral handoff seam.
    executor_imports = {name for name in imports if name.startswith("src.executor")}
    assert executor_imports <= {"src.executor.execution_handoff_v1"}


def test_cli_uses_canonical_writer_repository_and_orchestrator() -> None:
    imports = _imports(CLI_FILE)
    assert "src.entry_policy.automatic_buy_source_runtime_input_writer_v1" in imports
    assert "src.entry_policy.automatic_buy_runtime_repository_v1" in imports
    assert "src.entry_policy.automatic_buy_runtime_orchestrator_v1" in imports
    assert "src.entry_policy.automatic_buy_execution_handoff_application_v1" in imports


def test_cli_hardcodes_dry_run_identity_constants() -> None:
    source = CLI_FILE.read_text()
    assert 'EXECUTOR_MODE: Final[str] = RUNTIME_MODE_DRY_RUN' in source
    assert 'RUNTIME_OWNER: Final[str] = "gurkdb"' in source
    assert 'EXECUTOR_IDENTITY: Final[str] = "shared-executor-v1"' in source
    assert "--executor-mode" not in source
    assert "--runtime-owner" not in source
    assert "--executor-identity" not in source
