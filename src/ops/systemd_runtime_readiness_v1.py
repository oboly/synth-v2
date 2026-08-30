"""Issue #585: deterministic read-only systemd runtime readiness contract.

Ownership
---------

This module is a read-only ops/deploy helper. It never installs, reloads,
enables, disables, starts, stops, or masks a systemd unit, and it never
mutates ``deploy/ownership/account_runtime_capability_ownership_v1.json`` --
that registry stays ownership/design metadata only (owner_host, entrypoint,
lock scope, private-read authority). This module supplies the missing half:
*observed* systemd state on the capability's owner host, so a readiness
consumer (``src/ops/sell_live_activation_controller_v1.py``) never has to
treat a registry ``activation_status`` value as proof a runtime is actually
loaded, enabled, or active.

A registry-only value -- however it is spelled -- can never by itself make a
capability read as ready here. Every PASSED result in this module required an
actual ``systemctl show`` (or injected fake) call to observe LoadState,
ActiveState, UnitFileState, and FragmentPath for both the service and its
timer.

Contract
--------

For each capability:

- ``owner_host`` (as recorded in the ownership registry, passed in by the
  caller) must equal the capability's canonical expected owner host.
- The service unit must be ``loaded`` from the exact expected installed
  ``FragmentPath`` (``/etc/systemd/system/<unit>``, the canonical install
  path documented across this repository's other systemd runtime lanes).
- The timer unit must be ``loaded`` from its own exact expected
  ``FragmentPath``, ``UnitFileState=enabled``, and ``ActiveState=active``.
- The service's own ``ActiveState`` is *not* required to be ``active``: a
  correctly firing oneshot service is idle (``inactive``/``dead``) between
  timer firings by design. Only a small set of known-benign states is
  accepted; anything else (notably ``failed``) fails closed.
- Any probe failure (subprocess error, non-zero ``systemctl show`` exit,
  unparseable output), unit not found, disabled timer, inactive timer, wrong
  owner, wrong fragment path, or unrecognized/malformed state fails closed
  with an explicit reason code -- never a silent "assume ready".

Dependency injection
---------------------

Production code path (``default_systemd_unit_prober_v1``) shells out to
read-only ``systemctl show ... --no-pager``. Every test in
``tests/test_systemd_runtime_readiness_v1.py`` injects a fake
``SystemdUnitProber`` instead; no test in this repository ever touches real
systemd.

Safety:
  service_mutation=0
  systemctl_mutations=0
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

SCHEMA_VERSION: Final[str] = "systemd_runtime_readiness_v1"
CONTRACT_VERSION: Final[str] = "v1"

STATUS_PASSED: Final[str] = "PASSED"
STATUS_BLOCKED: Final[str] = "BLOCKED"

_SHOW_PROPERTIES: Final[tuple[str, ...]] = (
    "LoadState",
    "ActiveState",
    "UnitFileState",
    "FragmentPath",
)

# A correctly-behaving oneshot service is idle between timer firings. These
# are the only ActiveState values this module treats as a healthy oneshot
# service; anything else (most importantly "failed") fails closed.
_ACCEPTED_ONESHOT_SERVICE_ACTIVE_STATES: Final[frozenset[str]] = frozenset(
    {"inactive", "active", "activating", "deactivating"}
)

INSTALLED_UNIT_DIR: Final[str] = "/etc/systemd/system"


def installed_unit_fragment_path_v1(unit: str) -> str:
    return f"{INSTALLED_UNIT_DIR}/{unit}"


# --- Probe result / injection seam -----------------------------------------


@dataclass(frozen=True)
class SystemdUnitProbeResultV1:
    unit: str
    found: bool
    load_state: str
    active_state: str
    unit_file_state: str
    fragment_path: str
    error: str = ""


SystemdUnitProber = Callable[[str], SystemdUnitProbeResultV1]


def _parse_show_properties(output: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value
    return properties


def default_systemd_unit_prober_v1(
    unit: str,
    *,
    systemctl: str = "systemctl",
    timeout_seconds: int = 10,
) -> SystemdUnitProbeResultV1:
    """Read-only ``systemctl show`` probe. Never enables/starts/installs anything."""
    command = [
        systemctl,
        "--system",
        "show",
        unit,
        "--no-pager",
        "--property=" + ",".join(_SHOW_PROPERTIES),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SystemdUnitProbeResultV1(
            unit=unit, found=False, load_state="", active_state="", unit_file_state="",
            fragment_path="", error=f"PROBE_FAILED:{type(exc).__name__}",
        )
    if result.returncode != 0:
        return SystemdUnitProbeResultV1(
            unit=unit, found=False, load_state="", active_state="", unit_file_state="",
            fragment_path="", error=f"SYSTEMCTL_SHOW_NONZERO_EXIT:{result.returncode}",
        )
    properties = _parse_show_properties(result.stdout)
    load_state = properties.get("LoadState", "")
    return SystemdUnitProbeResultV1(
        unit=unit,
        found=load_state not in ("", "not-found"),
        load_state=load_state,
        active_state=properties.get("ActiveState", ""),
        unit_file_state=properties.get("UnitFileState", ""),
        fragment_path=properties.get("FragmentPath", ""),
    )


# --- Capability spec / result -----------------------------------------------


@dataclass(frozen=True)
class SystemdCapabilityRuntimeSpecV1:
    capability_id: str
    expected_owner_host: str
    service_unit: str
    timer_unit: str
    expected_service_fragment_path: str
    expected_timer_fragment_path: str


@dataclass(frozen=True)
class CapabilityRuntimeReadinessResultV1:
    capability_id: str
    status: str
    reason_code: str
    detail: dict[str, Any] = field(default_factory=dict)


def _blocked(capability_id: str, reason_code: str, detail: dict[str, Any]) -> CapabilityRuntimeReadinessResultV1:
    return CapabilityRuntimeReadinessResultV1(
        capability_id=capability_id, status=STATUS_BLOCKED, reason_code=reason_code, detail=detail
    )


def _passed(capability_id: str, detail: dict[str, Any]) -> CapabilityRuntimeReadinessResultV1:
    return CapabilityRuntimeReadinessResultV1(
        capability_id=capability_id, status=STATUS_PASSED, reason_code="OK", detail=detail
    )


def evaluate_capability_runtime_readiness_v1(
    spec: SystemdCapabilityRuntimeSpecV1,
    *,
    registry_owner_host: str | None,
    prober: SystemdUnitProber,
) -> CapabilityRuntimeReadinessResultV1:
    """Combine registry ownership metadata with actual observed systemd state.

    ``registry_owner_host`` is read once from the caller's already-loaded
    ownership registry (this module never reads that JSON file itself, so it
    stays a pure ops/deploy consumer of whatever the caller already parsed).
    A registry-only value can never substitute for a real probe result below.
    """
    if registry_owner_host != spec.expected_owner_host:
        return _blocked(
            spec.capability_id,
            "RUNTIME_CAPABILITY_OWNER_MISMATCH",
            {
                "expected_owner_host": spec.expected_owner_host,
                "observed_owner_host": registry_owner_host,
            },
        )

    service_probe = prober(spec.service_unit)
    timer_probe = prober(spec.timer_unit)
    detail: dict[str, Any] = {
        "owner_host": spec.expected_owner_host,
        "service_unit": spec.service_unit,
        "service_load_state": service_probe.load_state,
        "service_active_state": service_probe.active_state,
        "service_fragment_path": service_probe.fragment_path,
        "timer_unit": spec.timer_unit,
        "timer_load_state": timer_probe.load_state,
        "timer_unit_file_state": timer_probe.unit_file_state,
        "timer_active_state": timer_probe.active_state,
        "timer_fragment_path": timer_probe.fragment_path,
    }

    if service_probe.error:
        return _blocked(spec.capability_id, "SYSTEMD_PROBE_FAILED", {**detail, "probe_error": service_probe.error, "probe_unit": spec.service_unit})
    if timer_probe.error:
        return _blocked(spec.capability_id, "SYSTEMD_PROBE_FAILED", {**detail, "probe_error": timer_probe.error, "probe_unit": spec.timer_unit})

    if not service_probe.found or service_probe.load_state != "loaded":
        return _blocked(spec.capability_id, "SERVICE_UNIT_NOT_FOUND", detail)
    if service_probe.fragment_path != spec.expected_service_fragment_path:
        return _blocked(spec.capability_id, "SERVICE_UNIT_WRONG_FRAGMENT_PATH", detail)
    if service_probe.active_state not in _ACCEPTED_ONESHOT_SERVICE_ACTIVE_STATES:
        return _blocked(spec.capability_id, "SERVICE_UNIT_ACTIVE_STATE_UNKNOWN", detail)

    if not timer_probe.found or timer_probe.load_state != "loaded":
        return _blocked(spec.capability_id, "TIMER_UNIT_NOT_FOUND", detail)
    if timer_probe.fragment_path != spec.expected_timer_fragment_path:
        return _blocked(spec.capability_id, "TIMER_UNIT_WRONG_FRAGMENT_PATH", detail)
    if timer_probe.unit_file_state != "enabled":
        return _blocked(spec.capability_id, "TIMER_UNIT_DISABLED", detail)
    if timer_probe.active_state != "active":
        return _blocked(spec.capability_id, "TIMER_UNIT_INACTIVE", detail)

    return _passed(spec.capability_id, detail)


# --- Canonical Issue #585 capability specs ----------------------------------

CAPABILITY_SPEC_AUTOMATIC_EXIT_POLICY_RUNTIME: Final[SystemdCapabilityRuntimeSpecV1] = SystemdCapabilityRuntimeSpecV1(
    capability_id="AUTOMATIC_EXIT_POLICY_RUNTIME",
    expected_owner_host="gurkdb",
    service_unit="synth-automatic-exit-policy-runtime.service",
    timer_unit="synth-automatic-exit-policy-runtime.timer",
    expected_service_fragment_path=installed_unit_fragment_path_v1("synth-automatic-exit-policy-runtime.service"),
    expected_timer_fragment_path=installed_unit_fragment_path_v1("synth-automatic-exit-policy-runtime.timer"),
)

CAPABILITY_SPEC_SHARED_EXECUTOR_RUNTIME: Final[SystemdCapabilityRuntimeSpecV1] = SystemdCapabilityRuntimeSpecV1(
    capability_id="SHARED_EXECUTOR_RUNTIME",
    expected_owner_host="gurkdb",
    service_unit="synth-shared-executor-runtime.service",
    timer_unit="synth-shared-executor-runtime.timer",
    expected_service_fragment_path=installed_unit_fragment_path_v1("synth-shared-executor-runtime.service"),
    expected_timer_fragment_path=installed_unit_fragment_path_v1("synth-shared-executor-runtime.timer"),
)

REQUIRED_CAPABILITY_RUNTIME_SPECS: Final[dict[str, SystemdCapabilityRuntimeSpecV1]] = {
    CAPABILITY_SPEC_AUTOMATIC_EXIT_POLICY_RUNTIME.capability_id: CAPABILITY_SPEC_AUTOMATIC_EXIT_POLICY_RUNTIME,
    CAPABILITY_SPEC_SHARED_EXECUTOR_RUNTIME.capability_id: CAPABILITY_SPEC_SHARED_EXECUTOR_RUNTIME,
}
