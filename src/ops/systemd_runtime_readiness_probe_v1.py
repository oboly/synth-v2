"""Issue #585: read-only systemd runtime readiness contract.

Ownership
---------

This module owns exactly one thing: turning a read-only ``systemctl show``
observation of an installed service/timer unit pair into a deterministic
PASS/BLOCK readiness verdict for one named runtime capability. It never
mutates systemd (no start/stop/enable/disable/reload/mask), never mutates
``deploy/ownership/account_runtime_capability_ownership_v1.json``, and never
treats that registry's ``activation_status`` field as evidence of live
runtime state -- that field remains ownership/design metadata only.

Callers (``src/ops/sell_live_activation_controller_v1.py``) inject the probe
callable so tests never touch real systemd.

Fail-closed contract
---------------------

A capability is only ``PASS`` when ALL of the following hold:

- a registry entry for the capability exists
- the registry entry's ``owner_host`` matches the capability's canonical
  owner host
- the service unit is ``loaded`` from the expected installed fragment path
- the service unit is not in a ``failed`` active state (a oneshot service is
  otherwise allowed to be idle/dead between timer firings -- that is its
  expected steady state, not a degraded one)
- the timer unit is ``loaded`` from the expected installed fragment path
- the timer unit's ``UnitFileState`` is ``enabled``
- the timer unit's ``ActiveState`` is ``active``

Any probe failure, missing unit, disabled timer, inactive timer, wrong
owner, wrong fragment path, or unrecognized/malformed systemd state value
blocks. There is no path in this module that promotes registry metadata
alone to a PASS verdict.

Safety:
  service_mutation=0
  systemd_mutation=0
  production_db_mutation=0
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Final

from src.executor.shared_executor_identity_v1 import SHARED_EXECUTOR_RUNTIME_OWNER

SCHEMA_VERSION: Final[str] = "systemd_runtime_readiness_v1"

STATUS_PASS: Final[str] = "PASS"
STATUS_BLOCK: Final[str] = "BLOCK"

_INSTALLED_UNIT_DIR: Final[str] = "/etc/systemd/system"

_SHOW_PROPERTIES: Final[tuple[str, ...]] = (
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "FragmentPath",
)

_LOADED: Final[str] = "loaded"
_ENABLED_STATES: Final[frozenset[str]] = frozenset({"enabled", "enabled-runtime"})
_TIMER_ACTIVE_OK: Final[frozenset[str]] = frozenset({"active"})
_SERVICE_FAILED_STATES: Final[frozenset[str]] = frozenset({"failed"})


@dataclass(frozen=True)
class SystemdUnitStateV1:
    """One read-only ``systemctl show`` observation. Never a mutation request."""

    unit: str
    load_state: str = ""
    active_state: str = ""
    sub_state: str = ""
    unit_file_state: str = ""
    fragment_path: str = ""
    probe_error: str = ""


SystemdProbeV1 = Callable[[str], SystemdUnitStateV1]


def default_systemd_probe_v1(unit: str) -> SystemdUnitStateV1:
    """Read-only ``systemctl show`` probe. Never start/stop/enable/disable/reload/mask."""
    command = [
        "systemctl",
        "--system",
        "show",
        unit,
        "--no-pager",
        "--property=" + ",".join(_SHOW_PROPERTIES),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SystemdUnitStateV1(unit=unit, probe_error=type(exc).__name__)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        return SystemdUnitStateV1(
            unit=unit,
            probe_error=f"RC_{completed.returncode}:{detail[:128]}" if detail else f"RC_{completed.returncode}",
        )

    properties: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value

    return SystemdUnitStateV1(
        unit=unit,
        load_state=properties.get("LoadState", ""),
        active_state=properties.get("ActiveState", ""),
        sub_state=properties.get("SubState", ""),
        unit_file_state=properties.get("UnitFileState", ""),
        fragment_path=properties.get("FragmentPath", ""),
    )


@dataclass(frozen=True)
class RuntimeCapabilityUnitContractV1:
    """Deterministic, versioned expectation for one runtime capability's units."""

    capability_id: str
    owner_host: str
    service_unit: str
    timer_unit: str
    expected_service_fragment_path: str
    expected_timer_fragment_path: str


def _installed_path(unit: str) -> str:
    return f"{_INSTALLED_UNIT_DIR}/{unit}"


REQUIRED_RUNTIME_CAPABILITY_CONTRACTS_V1: Final[dict[str, RuntimeCapabilityUnitContractV1]] = {
    "AUTOMATIC_EXIT_POLICY_RUNTIME": RuntimeCapabilityUnitContractV1(
        capability_id="AUTOMATIC_EXIT_POLICY_RUNTIME",
        owner_host=SHARED_EXECUTOR_RUNTIME_OWNER,
        service_unit="synth-automatic-exit-policy-runtime.service",
        timer_unit="synth-automatic-exit-policy-runtime.timer",
        expected_service_fragment_path=_installed_path("synth-automatic-exit-policy-runtime.service"),
        expected_timer_fragment_path=_installed_path("synth-automatic-exit-policy-runtime.timer"),
    ),
    "SHARED_EXECUTOR_RUNTIME": RuntimeCapabilityUnitContractV1(
        capability_id="SHARED_EXECUTOR_RUNTIME",
        owner_host=SHARED_EXECUTOR_RUNTIME_OWNER,
        service_unit="synth-shared-executor-runtime.service",
        timer_unit="synth-shared-executor-runtime.timer",
        expected_service_fragment_path=_installed_path("synth-shared-executor-runtime.service"),
        expected_timer_fragment_path=_installed_path("synth-shared-executor-runtime.timer"),
    ),
}


@dataclass(frozen=True)
class RuntimeCapabilityReadinessResultV1:
    capability_id: str
    status: str
    reason_code: str
    detail: dict[str, Any] = field(default_factory=dict)


def evaluate_runtime_capability_readiness_v1(
    contract: RuntimeCapabilityUnitContractV1,
    registry_entry: dict[str, Any] | None,
    probe: SystemdProbeV1,
) -> RuntimeCapabilityReadinessResultV1:
    """Evaluate one capability's readiness from registry ownership + live systemd state.

    ``registry_entry`` supplies ownership/design metadata only (existence and
    ``owner_host``). Its ``activation_status`` field, if present, is never
    read here -- it cannot make this function return PASS on its own.
    """
    if registry_entry is None:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "REGISTRY_ENTRY_MISSING"
        )

    observed_owner_host = str(registry_entry.get("owner_host", "UNKNOWN"))
    if observed_owner_host != contract.owner_host:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id,
            STATUS_BLOCK,
            "REGISTRY_OWNER_HOST_MISMATCH",
            {
                "expected_owner_host": contract.owner_host,
                "observed_owner_host": observed_owner_host,
            },
        )

    try:
        service_state = probe(contract.service_unit)
    except Exception as exc:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id,
            STATUS_BLOCK,
            "SERVICE_PROBE_FAILED",
            {"exception_type": type(exc).__name__},
        )
    try:
        timer_state = probe(contract.timer_unit)
    except Exception as exc:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id,
            STATUS_BLOCK,
            "TIMER_PROBE_FAILED",
            {"exception_type": type(exc).__name__},
        )

    detail: dict[str, Any] = {
        "service_unit": contract.service_unit,
        "service_load_state": service_state.load_state,
        "service_active_state": service_state.active_state,
        "service_sub_state": service_state.sub_state,
        "service_fragment_path": service_state.fragment_path,
        "timer_unit": contract.timer_unit,
        "timer_load_state": timer_state.load_state,
        "timer_active_state": timer_state.active_state,
        "timer_unit_file_state": timer_state.unit_file_state,
        "timer_fragment_path": timer_state.fragment_path,
    }

    if service_state.probe_error:
        detail["service_probe_error"] = service_state.probe_error
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "SERVICE_PROBE_FAILED", detail
        )
    if timer_state.probe_error:
        detail["timer_probe_error"] = timer_state.probe_error
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "TIMER_PROBE_FAILED", detail
        )

    if service_state.load_state != _LOADED:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "SERVICE_UNIT_NOT_LOADED", detail
        )
    if service_state.fragment_path != contract.expected_service_fragment_path:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "SERVICE_FRAGMENT_PATH_MISMATCH", detail
        )
    if service_state.active_state in _SERVICE_FAILED_STATES:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "SERVICE_ACTIVE_STATE_FAILED", detail
        )

    if timer_state.load_state != _LOADED:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "TIMER_UNIT_NOT_LOADED", detail
        )
    if timer_state.fragment_path != contract.expected_timer_fragment_path:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "TIMER_FRAGMENT_PATH_MISMATCH", detail
        )
    if timer_state.unit_file_state not in _ENABLED_STATES:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "TIMER_NOT_ENABLED", detail
        )
    if timer_state.active_state not in _TIMER_ACTIVE_OK:
        return RuntimeCapabilityReadinessResultV1(
            contract.capability_id, STATUS_BLOCK, "TIMER_NOT_ACTIVE", detail
        )

    return RuntimeCapabilityReadinessResultV1(contract.capability_id, STATUS_PASS, "OK", detail)
