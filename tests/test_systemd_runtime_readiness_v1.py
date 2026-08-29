"""Issue #585: tests for the read-only systemd runtime readiness contract.

Every test injects a fake probe. None of them ever shell out to real
systemd.
"""
from __future__ import annotations

from src.ops import systemd_runtime_readiness_v1 as readiness

_CONTRACT = readiness.CAPABILITY_UNIT_CONTRACTS["AUTOMATIC_EXIT_POLICY_RUNTIME"]


def _healthy_state(unit: str) -> readiness.SystemdUnitStateV1:
    if unit == _CONTRACT.service_unit:
        return readiness.SystemdUnitStateV1(
            unit=unit,
            load_state="loaded",
            active_state="inactive",
            unit_file_state="static",
            fragment_path=_CONTRACT.expected_service_fragment_path,
        )
    return readiness.SystemdUnitStateV1(
        unit=unit,
        load_state="loaded",
        active_state="active",
        unit_file_state="enabled",
        fragment_path=_CONTRACT.expected_timer_fragment_path,
    )


def _probe(overrides: dict[str, readiness.SystemdUnitStateV1] | None = None):
    overrides = overrides or {}

    def probe(unit: str) -> readiness.SystemdUnitStateV1:
        if unit in overrides:
            return overrides[unit]
        return _healthy_state(unit)

    return probe


def test_healthy_oneshot_service_and_enabled_active_timer_is_ready() -> None:
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=_probe()
    )
    assert result.status == readiness.STATUS_READY
    assert result.reason_code == "OK"


def test_missing_registry_entry_blocks() -> None:
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host=None, probe=_probe()
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "REGISTRY_ENTRY_MISSING"


def test_registry_owner_mismatch_blocks() -> None:
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="odroid", probe=_probe()
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "REGISTRY_OWNER_MISMATCH"


def test_service_unit_not_found_blocks() -> None:
    overrides = {
        _CONTRACT.service_unit: readiness.SystemdUnitStateV1(
            unit=_CONTRACT.service_unit, load_state="not-found",
        )
    }
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=_probe(overrides)
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "SERVICE_UNIT_NOT_FOUND"


def test_timer_unit_not_found_blocks() -> None:
    overrides = {
        _CONTRACT.timer_unit: readiness.SystemdUnitStateV1(
            unit=_CONTRACT.timer_unit, load_state="not-found",
        )
    }
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=_probe(overrides)
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "TIMER_UNIT_NOT_FOUND"


def test_disabled_timer_blocks() -> None:
    overrides = {
        _CONTRACT.timer_unit: readiness.SystemdUnitStateV1(
            unit=_CONTRACT.timer_unit,
            load_state="loaded",
            active_state="active",
            unit_file_state="disabled",
            fragment_path=_CONTRACT.expected_timer_fragment_path,
        )
    }
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=_probe(overrides)
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "TIMER_NOT_ENABLED"


def test_inactive_timer_blocks() -> None:
    overrides = {
        _CONTRACT.timer_unit: readiness.SystemdUnitStateV1(
            unit=_CONTRACT.timer_unit,
            load_state="loaded",
            active_state="inactive",
            unit_file_state="enabled",
            fragment_path=_CONTRACT.expected_timer_fragment_path,
        )
    }
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=_probe(overrides)
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "TIMER_NOT_ACTIVE"


def test_wrong_fragment_path_blocks() -> None:
    overrides = {
        _CONTRACT.service_unit: readiness.SystemdUnitStateV1(
            unit=_CONTRACT.service_unit,
            load_state="loaded",
            active_state="inactive",
            unit_file_state="static",
            fragment_path="/etc/systemd/system/some-other-unrelated.service",
        )
    }
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=_probe(overrides)
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "SERVICE_UNIT_WRONG_FRAGMENT_PATH"


def test_service_probe_error_blocks() -> None:
    def probe(unit: str) -> readiness.SystemdUnitStateV1:
        if unit == _CONTRACT.service_unit:
            raise RuntimeError("SIMULATED_SYSTEMCTL_FAILURE")
        return _healthy_state(unit)

    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=probe
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "SERVICE_PROBE_FAILED"


def test_timer_probe_error_blocks() -> None:
    def probe(unit: str) -> readiness.SystemdUnitStateV1:
        if unit == _CONTRACT.timer_unit:
            raise RuntimeError("SIMULATED_SYSTEMCTL_FAILURE")
        return _healthy_state(unit)

    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=probe
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "TIMER_PROBE_FAILED"


def test_probe_reported_error_string_blocks() -> None:
    overrides = {
        _CONTRACT.service_unit: readiness.SystemdUnitStateV1(
            unit=_CONTRACT.service_unit, probe_error="systemctl show failed: rc=1",
        )
    }
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "AUTOMATIC_EXIT_POLICY_RUNTIME", registry_owner_host="gurkdb", probe=_probe(overrides)
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "SERVICE_PROBE_FAILED"


def test_unknown_capability_blocks() -> None:
    result = readiness.evaluate_capability_runtime_readiness_v1(
        "UNKNOWN_CAPABILITY_ID", registry_owner_host="gurkdb", probe=_probe()
    )
    assert result.status == readiness.STATUS_NOT_READY
    assert result.reason_code == "UNKNOWN_CAPABILITY"


def test_probe_systemd_unit_v1_never_mutates() -> None:
    """Static guarantee: the production probe only ever runs `systemctl show`.

    This is a source-level assertion (not a live systemctl call) so the test
    suite never depends on a running systemd.
    """
    import inspect

    source = inspect.getsource(readiness.probe_systemd_unit_v1)
    assert '"show"' in source
    for forbidden in ("enable", "disable", "start", "stop", "mask", "daemon-reload"):
        assert forbidden not in source
