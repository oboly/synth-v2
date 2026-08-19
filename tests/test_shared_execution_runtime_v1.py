from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.executor.execution_handoff_v1 import RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_LIVE, RUNTIME_MODE_PAPER
from src.executor.run_shared_execution_runtime_v1 import (
    RuntimeInterrupted,
    config_from_args,
    parse_args,
    run,
)
from src.executor.shared_execution_consumer_v1 import SharedExecutionConsumerResultV1
from src.executor.shared_execution_runtime_v1 import (
    SharedExecutorModeAdapterUnavailableError,
    SharedExecutorRuntimeConfigV1,
    build_runtime_adapter_factory_v1,
)


def _config(mode: str = RUNTIME_MODE_DRY_RUN) -> SharedExecutorRuntimeConfigV1:
    return SharedExecutorRuntimeConfigV1(
        executor_mode=mode,
        runtime_owner="gurkdb",
        executor_identity="shared-executor-v1",
        worker_id="shared-executor-v1:test:1",
        operator_id=9,
    )


def test_paper_and_live_fail_closed_before_runtime_db_composition() -> None:
    with pytest.raises(SharedExecutorModeAdapterUnavailableError, match="PAPER_ADAPTER_NOT_CONFIGURED"):
        build_runtime_adapter_factory_v1(_config(RUNTIME_MODE_PAPER))
    with pytest.raises(SharedExecutorModeAdapterUnavailableError, match="LIVE_RUNTIME_NOT_AUTHORIZED"):
        build_runtime_adapter_factory_v1(_config(RUNTIME_MODE_LIVE))


def test_runtime_requires_explicit_mode_owner_identity_and_operator(monkeypatch) -> None:
    for name in (
        "SYNTH_SHARED_EXECUTOR_MODE",
        "SYNTH_SHARED_EXECUTOR_RUNTIME_OWNER",
        "SYNTH_SHARED_EXECUTOR_IDENTITY",
        "SYNTH_SHARED_EXECUTOR_OPERATOR_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="SYNTH_SHARED_EXECUTOR_MODE required"):
        config_from_args(parse_args([]))


def test_runtime_rejects_live_or_broker_permission_environment(monkeypatch) -> None:
    monkeypatch.setenv("SYNTH_LIVE_EXECUTION_PERMISSION", "GRANTED")
    with pytest.raises(ValueError, match="SYNTH_LIVE_EXECUTION_PERMISSION must remain NOT_GRANTED"):
        config_from_args(parse_args(["--executor-mode", "DRY_RUN", "--runtime-owner", "gurkdb", "--executor-identity", "shared-executor-v1", "--operator-id", "9"]))


def test_explicit_runtime_arguments_win_over_conflicting_environment(monkeypatch) -> None:
    monkeypatch.setenv("SYNTH_SHARED_EXECUTOR_MODE", "LIVE")
    monkeypatch.setenv("SYNTH_SHARED_EXECUTOR_RUNTIME_OWNER", "wrong-owner")
    monkeypatch.setenv("SYNTH_SHARED_EXECUTOR_IDENTITY", "wrong-identity")
    config = config_from_args(parse_args([
        "--executor-mode", "DRY_RUN",
        "--runtime-owner", "gurkdb",
        "--executor-identity", "shared-executor-v1",
        "--operator-id", "9",
    ]))
    assert (config.executor_mode, config.runtime_owner, config.executor_identity) == (
        "DRY_RUN", "gurkdb", "shared-executor-v1",
    )


def test_bounded_runtime_prints_started_and_finished_with_safety_markers(capsys) -> None:
    assert run(_config(), run_cycle=lambda _config: ()) == 0
    output = capsys.readouterr().out
    assert "STARTED runner=run_shared_execution_runtime_v1 mode=DRY_RUN" in output
    assert "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0" in output
    assert "FINISHED runner=run_shared_execution_runtime_v1 result=ok outcomes=0" in output
    assert 'reason_counts={}' in output


def test_runtime_reports_incomplete_outcome_and_signal_interruption(capsys) -> None:
    assert run(
        _config(),
        run_cycle=lambda _config: (
            SharedExecutionConsumerResultV1(7, "SUBMISSION_UNCERTAIN"),
        ),
    ) == 0
    output = capsys.readouterr().out
    assert "OUTCOME runner=run_shared_execution_runtime_v1 handoff_id=7 reason=SUBMISSION_UNCERTAIN" in output
    assert "FINISHED runner=run_shared_execution_runtime_v1 result=incomplete" in output
    assert run(_config(), run_cycle=lambda _config: (_ for _ in ()).throw(RuntimeInterrupted())) == 130
    assert "INTERRUPTED runner=run_shared_execution_runtime_v1 result=signal" in capsys.readouterr().out


def test_runtime_and_consumer_do_not_import_manual_or_strategy_layers() -> None:
    paths = (
        Path("src/executor/run_shared_execution_runtime_v1.py"),
        Path("src/executor/shared_execution_runtime_v1.py"),
        Path("src/executor/dry_run_order_adapter_v1.py"),
        Path("src/executor/shared_execution_consumer_v1.py"),
    )
    imports = set()
    for path in paths:
        tree = ast.parse(path.read_text())
        imports.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
    assert not any("manual_execution" in value for value in imports)
    assert not any(value.startswith(prefix) for value in imports for prefix in (
        "src.decision_gate", "src.execution_planner", "src.entry_policy", "src.exit_policy",
    ))


def test_candidate_systemd_artifacts_are_disabled_dry_run_templates() -> None:
    service = Path("deploy/systemd/synth-shared-executor-runtime.service").read_text()
    timer = Path("deploy/systemd/synth-shared-executor-runtime.timer").read_text()
    assert "ConditionHost=gurkdb" in service
    assert "User=gurk" in service
    assert "WorkingDirectory=/home/gurk/projects/synth-v2" in service
    assert "SYNTH_SHARED_EXECUTOR_MODE=DRY_RUN" in service
    assert "SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED" in service
    assert "SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED" in service
    assert "Restart=no" in service
    assert "--executor-mode DRY_RUN --runtime-owner gurkdb --executor-identity shared-executor-v1" in service
    assert "TimeoutStartSec=2min" in service
    assert "uninstalled and disabled" in service
    assert "OnUnitActiveSec=15s" in timer
    assert "uninstalled and disabled" in timer
