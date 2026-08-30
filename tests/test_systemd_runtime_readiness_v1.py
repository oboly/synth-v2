"""Issue #585: tests for the read-only systemd runtime readiness contract.

Every test here injects a fake prober. None of them ever shell out to real
systemd.
"""
from __future__ import annotations

from typing import Callable

import pytest

from src.ops import systemd_runtime_readiness_v1 as readiness


SERVICE_UNIT = "synth-example-runtime.service"
TIMER_UNIT = "synth-example-runtime.timer"
EXPECTED_OWNER = "gurkdb"
SERVICE_FRAGMENT = readiness.installed_unit_fragment_path_v1(SERVICE_UNIT)
TIMER_FRAGMENT = readiness.installed_unit_fragment_path_v1(TIMER_UNIT)


def _spec() -> readiness.SystemdCapabilityRuntimeSpecV1:
    return readiness.SystemdCapabilityRuntimeSpecV1(
        capability_id="EXAMPLE_RUNTIME",
        expected_owner_host=EXPECTED_OWNER,
        service_unit=SERVICE_UNIT,
        timer_unit=TIMER_UNIT,
        expected_service_fragment_path=SERVICE_FRAGMENT,
        expected_timer_fragment_path=TIMER_FRAGMENT,
    )


def _probe(
    unit: str,
    *,
    found: bool = True,
    load_state: str = "loaded",
    active_state: str = "inactive",
    unit_file_state: str = "enabled",
    fragment_path: str | None = None,
    error: str = "",
) -> readiness.SystemdUnitProbeResultV1:
    return readiness.SystemdUnitProbeResultV1(
        unit=unit,
        found=found,
        load_state=load_state,
        active_state=active_state,
        unit_file_state=unit_file_state,
        fragment_path=fragment_path if fragment_path is not None else readiness.installed_unit_fragment_path_v1(unit),
        error=error,
    )


def _healthy_service_probe() -> readiness.SystemdUnitProbeResultV1:
    return _probe(SERVICE_UNIT, active_state="inactive")


def _healthy_timer_probe() -> readiness.SystemdUnitProbeResultV1:
    return _probe(TIMER_UNIT, active_state="active", unit_file_state="enabled")


def _fake_prober(probes: dict[str, readiness.SystemdUnitProbeResultV1]) -> Callable[[str], readiness.SystemdUnitProbeResultV1]:
    def _prober(unit: str) -> readiness.SystemdUnitProbeResultV1:
        return probes[unit]

    return _prober


def _evaluate(
    probes: dict[str, readiness.SystemdUnitProbeResultV1],
    *,
    registry_owner_host: str | None = EXPECTED_OWNER,
) -> readiness.CapabilityRuntimeReadinessResultV1:
    return readiness.evaluate_capability_runtime_readiness_v1(
        _spec(), registry_owner_host=registry_owner_host, prober=_fake_prober(probes)
    )


# --- Healthy path ------------------------------------------------------


def test_healthy_oneshot_service_and_enabled_active_timer_passes() -> None:
    result = _evaluate({SERVICE_UNIT: _healthy_service_probe(), TIMER_UNIT: _healthy_timer_probe()})
    assert result.status == readiness.STATUS_PASSED
    assert result.reason_code == "OK"
    assert result.detail["service_active_state"] == "inactive"
    assert result.detail["timer_active_state"] == "active"


def test_service_active_while_timer_firing_still_passes() -> None:
    result = _evaluate(
        {SERVICE_UNIT: _probe(SERVICE_UNIT, active_state="active"), TIMER_UNIT: _healthy_timer_probe()}
    )
    assert result.status == readiness.STATUS_PASSED


# --- Fail-closed cases ---------------------------------------------------


def test_missing_service_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _probe(SERVICE_UNIT, found=False, load_state="not-found", fragment_path=""),
            TIMER_UNIT: _healthy_timer_probe(),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "SERVICE_UNIT_NOT_FOUND"


def test_missing_timer_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _healthy_service_probe(),
            TIMER_UNIT: _probe(TIMER_UNIT, found=False, load_state="not-found", fragment_path=""),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "TIMER_UNIT_NOT_FOUND"


def test_disabled_timer_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _healthy_service_probe(),
            TIMER_UNIT: _probe(TIMER_UNIT, active_state="active", unit_file_state="disabled"),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "TIMER_UNIT_DISABLED"


def test_inactive_timer_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _healthy_service_probe(),
            TIMER_UNIT: _probe(TIMER_UNIT, active_state="inactive", unit_file_state="enabled"),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "TIMER_UNIT_INACTIVE"


def test_wrong_owner_blocks_without_probing() -> None:
    probed_units: list[str] = []

    def _prober(unit: str) -> readiness.SystemdUnitProbeResultV1:
        probed_units.append(unit)
        return _probe(unit)

    result = readiness.evaluate_capability_runtime_readiness_v1(
        _spec(), registry_owner_host="odroid", prober=_prober
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "RUNTIME_CAPABILITY_OWNER_MISMATCH"
    assert result.detail["expected_owner_host"] == EXPECTED_OWNER
    assert result.detail["observed_owner_host"] == "odroid"
    assert probed_units == []


def test_wrong_service_fragment_path_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _probe(SERVICE_UNIT, fragment_path="/etc/systemd/system/some-other-unit.service"),
            TIMER_UNIT: _healthy_timer_probe(),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "SERVICE_UNIT_WRONG_FRAGMENT_PATH"


def test_wrong_timer_fragment_path_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _healthy_service_probe(),
            TIMER_UNIT: _probe(
                TIMER_UNIT, active_state="active", fragment_path="/etc/systemd/system/some-other-unit.timer"
            ),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "TIMER_UNIT_WRONG_FRAGMENT_PATH"


def test_service_probe_error_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _probe(SERVICE_UNIT, error="PROBE_FAILED:FileNotFoundError"),
            TIMER_UNIT: _healthy_timer_probe(),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "SYSTEMD_PROBE_FAILED"
    assert result.detail["probe_unit"] == SERVICE_UNIT


def test_timer_probe_error_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _healthy_service_probe(),
            TIMER_UNIT: _probe(TIMER_UNIT, error="SYSTEMCTL_SHOW_NONZERO_EXIT:1"),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "SYSTEMD_PROBE_FAILED"
    assert result.detail["probe_unit"] == TIMER_UNIT


def test_failed_service_active_state_blocks() -> None:
    result = _evaluate(
        {
            SERVICE_UNIT: _probe(SERVICE_UNIT, active_state="failed"),
            TIMER_UNIT: _healthy_timer_probe(),
        }
    )
    assert result.status == readiness.STATUS_BLOCKED
    assert result.reason_code == "SERVICE_UNIT_ACTIVE_STATE_UNKNOWN"


# --- Default prober / real subprocess wiring (no real systemctl call) ----


def test_default_prober_reports_probe_failed_when_systemctl_missing() -> None:
    result = readiness.default_systemd_unit_prober_v1("does-not-matter.service", systemctl="/no/such/systemctl-binary")
    assert result.found is False
    assert result.error.startswith("PROBE_FAILED:")


def test_default_prober_parses_show_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeCompleted:
        returncode = 0
        stdout = (
            "LoadState=loaded\n"
            "ActiveState=active\n"
            "UnitFileState=enabled\n"
            f"FragmentPath={TIMER_FRAGMENT}\n"
        )
        stderr = ""

    def _fake_run(command, **kwargs):
        assert command[0] == "systemctl"
        assert "show" in command
        return _FakeCompleted()

    monkeypatch.setattr(readiness.subprocess, "run", _fake_run)
    result = readiness.default_systemd_unit_prober_v1(TIMER_UNIT)
    assert result.found is True
    assert result.load_state == "loaded"
    assert result.active_state == "active"
    assert result.unit_file_state == "enabled"
    assert result.fragment_path == TIMER_FRAGMENT
    assert result.error == ""


def test_default_prober_reports_not_found_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeCompleted:
        returncode = 0
        stdout = "LoadState=not-found\nActiveState=inactive\nUnitFileState=\nFragmentPath=\n"
        stderr = ""

    monkeypatch.setattr(readiness.subprocess, "run", lambda command, **kwargs: _FakeCompleted())
    result = readiness.default_systemd_unit_prober_v1(SERVICE_UNIT)
    assert result.found is False
    assert result.load_state == "not-found"


# --- Canonical Issue #585 specs -------------------------------------------


def test_required_capability_specs_match_canonical_units() -> None:
    specs = readiness.REQUIRED_CAPABILITY_RUNTIME_SPECS
    assert set(specs) == {"AUTOMATIC_EXIT_POLICY_RUNTIME", "SHARED_EXECUTOR_RUNTIME"}
    exit_spec = specs["AUTOMATIC_EXIT_POLICY_RUNTIME"]
    assert exit_spec.expected_owner_host == "gurkdb"
    assert exit_spec.service_unit == "synth-automatic-exit-policy-runtime.service"
    assert exit_spec.timer_unit == "synth-automatic-exit-policy-runtime.timer"
    executor_spec = specs["SHARED_EXECUTOR_RUNTIME"]
    assert executor_spec.expected_owner_host == "gurkdb"
    assert executor_spec.service_unit == "synth-shared-executor-runtime.service"
    assert executor_spec.timer_unit == "synth-shared-executor-runtime.timer"
    for spec in specs.values():
        assert spec.expected_service_fragment_path == f"/etc/systemd/system/{spec.service_unit}"
        assert spec.expected_timer_fragment_path == f"/etc/systemd/system/{spec.timer_unit}"


# --- Module never mutates systemd -----------------------------------------


def test_module_defines_no_mutating_systemctl_verbs() -> None:
    import inspect

    source = inspect.getsource(readiness)
    for verb in ("enable", "disable", "start", "stop", "mask", "daemon-reload", "install"):
        assert f'"{verb}"' not in source
        assert f"'{verb}'" not in source
