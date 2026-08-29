"""Issue #585: unit tests for the read-only systemd runtime readiness probe.

Every test here injects a fake probe callable. None of them ever invoke
``subprocess.run``, ``systemctl``, or any other real systemd interaction.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.executor.shared_executor_identity_v1 import SHARED_EXECUTOR_RUNTIME_OWNER
from src.ops import systemd_runtime_readiness_probe_v1 as probe_module


def _contract(capability_id: str) -> probe_module.RuntimeCapabilityUnitContractV1:
    return probe_module.REQUIRED_RUNTIME_CAPABILITY_CONTRACTS_V1[capability_id]


def _healthy_states(
    contract: probe_module.RuntimeCapabilityUnitContractV1,
) -> dict[str, probe_module.SystemdUnitStateV1]:
    return {
        contract.service_unit: probe_module.SystemdUnitStateV1(
            unit=contract.service_unit,
            load_state="loaded",
            active_state="inactive",
            sub_state="dead",
            fragment_path=contract.expected_service_fragment_path,
        ),
        contract.timer_unit: probe_module.SystemdUnitStateV1(
            unit=contract.timer_unit,
            load_state="loaded",
            active_state="active",
            sub_state="waiting",
            unit_file_state="enabled",
            fragment_path=contract.expected_timer_fragment_path,
        ),
    }


def _probe_from(states: dict[str, probe_module.SystemdUnitStateV1]) -> probe_module.SystemdProbeV1:
    def _probe(unit: str) -> probe_module.SystemdUnitStateV1:
        return states.get(unit, probe_module.SystemdUnitStateV1(unit=unit, load_state="not-found"))

    return _probe


REGISTRY_ENTRY = {"capability_id": "AUTOMATIC_EXIT_POLICY_RUNTIME", "owner_host": SHARED_EXECUTOR_RUNTIME_OWNER,
                   "activation_status": "PLANNED"}


def test_two_required_capabilities_have_contracts() -> None:
    assert set(probe_module.REQUIRED_RUNTIME_CAPABILITY_CONTRACTS_V1) == {
        "AUTOMATIC_EXIT_POLICY_RUNTIME",
        "SHARED_EXECUTOR_RUNTIME",
    }
    for contract in probe_module.REQUIRED_RUNTIME_CAPABILITY_CONTRACTS_V1.values():
        assert contract.owner_host == "gurkdb"


def test_healthy_oneshot_service_and_enabled_active_timer_passes() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(_healthy_states(contract))
    )
    assert result.status == probe_module.STATUS_PASS
    assert result.reason_code == "OK"


def test_registry_entry_missing_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, None, _probe_from(_healthy_states(contract))
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "REGISTRY_ENTRY_MISSING"


def test_registry_owner_host_mismatch_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    entry = dict(REGISTRY_ENTRY, owner_host="odroid")
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, entry, _probe_from(_healthy_states(contract))
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "REGISTRY_OWNER_HOST_MISMATCH"


def test_activation_status_alone_cannot_pass_readiness() -> None:
    """A registry-only ACTIVE-like value must never make readiness pass:
    registry says ACTIVE, but the service unit is not even installed."""
    contract = _contract("SHARED_EXECUTOR_RUNTIME")
    entry = dict(REGISTRY_ENTRY, capability_id=contract.capability_id, activation_status="ACTIVE")
    states = {contract.timer_unit: _healthy_states(contract)[contract.timer_unit]}
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, entry, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "SERVICE_UNIT_NOT_LOADED"


def test_missing_service_unit_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.service_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.service_unit, load_state="not-found"
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "SERVICE_UNIT_NOT_LOADED"


def test_missing_timer_unit_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.timer_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.timer_unit, load_state="not-found"
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "TIMER_UNIT_NOT_LOADED"


def test_disabled_timer_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.timer_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.timer_unit, load_state="loaded", active_state="active",
        sub_state="waiting", unit_file_state="disabled",
        fragment_path=contract.expected_timer_fragment_path,
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "TIMER_NOT_ENABLED"


def test_inactive_timer_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.timer_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.timer_unit, load_state="loaded", active_state="inactive",
        sub_state="dead", unit_file_state="enabled",
        fragment_path=contract.expected_timer_fragment_path,
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "TIMER_NOT_ACTIVE"


def test_wrong_service_fragment_path_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.service_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.service_unit, load_state="loaded", active_state="inactive",
        sub_state="dead", fragment_path="/etc/systemd/system/unrelated.service",
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "SERVICE_FRAGMENT_PATH_MISMATCH"


def test_wrong_timer_fragment_path_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.timer_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.timer_unit, load_state="loaded", active_state="active",
        sub_state="waiting", unit_file_state="enabled",
        fragment_path="/etc/systemd/system/unrelated.timer",
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "TIMER_FRAGMENT_PATH_MISMATCH"


def test_service_probe_error_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.service_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.service_unit, probe_error="SubprocessError"
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "SERVICE_PROBE_FAILED"


def test_timer_probe_error_blocks() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.timer_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.timer_unit, probe_error="TimeoutExpired"
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "TIMER_PROBE_FAILED"


def test_probe_raising_exception_blocks_closed() -> None:
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")

    def _raising_probe(unit: str) -> probe_module.SystemdUnitStateV1:
        raise RuntimeError("SIMULATED_PROBE_CRASH")

    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _raising_probe
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "SERVICE_PROBE_FAILED"


def test_service_failed_active_state_blocks() -> None:
    """A oneshot service MAY be inactive/dead between firings, but 'failed'
    is a genuine degraded state, not the expected idle steady state."""
    contract = _contract("AUTOMATIC_EXIT_POLICY_RUNTIME")
    states = _healthy_states(contract)
    states[contract.service_unit] = probe_module.SystemdUnitStateV1(
        unit=contract.service_unit, load_state="loaded", active_state="failed",
        sub_state="failed", fragment_path=contract.expected_service_fragment_path,
    )
    result = probe_module.evaluate_runtime_capability_readiness_v1(
        contract, REGISTRY_ENTRY, _probe_from(states)
    )
    assert result.status == probe_module.STATUS_BLOCK
    assert result.reason_code == "SERVICE_ACTIVE_STATE_FAILED"


def test_default_probe_issues_only_read_only_show_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default probe must only ever call ``systemctl show`` -- never a
    mutating verb like start/stop/enable/disable/reload/mask."""
    captured: dict[str, Any] = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "LoadState=loaded\nActiveState=active\nSubState=waiting\nUnitFileState=enabled\nFragmentPath=/etc/systemd/system/x.timer\n"
        stderr = ""

    def _fake_run(command: list[str], **kwargs: Any) -> _FakeCompleted:
        captured["command"] = command
        return _FakeCompleted()

    monkeypatch.setattr(probe_module.subprocess, "run", _fake_run)
    state = probe_module.default_systemd_probe_v1("synth-shared-executor-runtime.timer")

    assert captured["command"][0] == "systemctl"
    assert "show" in captured["command"]
    forbidden_verbs = {"start", "stop", "enable", "disable", "reload", "mask", "restart", "daemon-reload"}
    assert not forbidden_verbs.intersection(captured["command"])
    assert state.load_state == "loaded"
    assert state.unit_file_state == "enabled"


def test_default_probe_handles_subprocess_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("systemctl not found")

    monkeypatch.setattr(probe_module.subprocess, "run", _raise)
    state = probe_module.default_systemd_probe_v1("some.service")
    assert state.probe_error
    assert state.load_state == ""
