"""Issue #585: read-only systemd runtime readiness contract.

Ownership
---------

This module answers exactly one question, read-only: is the installed
systemd state on the capability's owner host actually running the way the
canonical unit contract below says it must run? It is deliberately separate
from ``deploy/ownership/account_runtime_capability_ownership_v1.json``,
which remains ownership/design metadata only (who owns a capability, what
its entrypoint/lock-scope/private-read-authority are) and is never itself
proof that a service or timer is installed, enabled, or running.

``sell_live_activation_controller_v1.py``'s ``RUNTIME_READY`` phase is the
only current consumer. It combines this module's live systemd truth with the
ownership registry's ``owner_host`` field (still the sole source of *which*
host is supposed to own a capability); the registry's ``activation_status``
field is never read by this module and must never by itself make a
capability's runtime readiness PASS.

A registry-only ``owner_host`` value is also never enough on its own: this
module additionally checks that it is actually executing on that same host
(``socket.gethostname()``, or an injected fake in tests) before it will
trust anything a local ``systemctl show`` reports. Identically named,
fully healthy local units on any other machine fail closed.

This module never mutates systemd: it only ever runs
``systemctl --system show <unit> --no-pager --property=...``, a read-only
query. No enable/start/stop/disable/mask/daemon-reload call exists anywhere
in this file.

Safety:
  service_mutation=0
  production_db_mutation=0
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
"""
from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Final

SCHEMA_VERSION: Final[str] = "systemd_runtime_readiness_v1"

STATUS_READY: Final[str] = "READY"
STATUS_NOT_READY: Final[str] = "NOT_READY"

# Canonical installed-unit directory. Units are copied here manually by a
# reviewed operator step (see docs/ops/); this module never writes to it.
_EXPECTED_UNIT_DIR: Final[str] = "/etc/systemd/system"

_ENABLED_UNIT_FILE_STATE: Final[str] = "enabled"
_ACTIVE_STATE_ACTIVE: Final[str] = "active"
_LOAD_STATE_LOADED: Final[str] = "loaded"


@dataclass(frozen=True)
class SystemdUnitContractV1:
    """Canonical expected service/timer pair for one capability."""

    capability_id: str
    owner_host: str
    service_unit: str
    timer_unit: str

    @property
    def expected_service_fragment_path(self) -> str:
        return f"{_EXPECTED_UNIT_DIR}/{self.service_unit}"

    @property
    def expected_timer_fragment_path(self) -> str:
        return f"{_EXPECTED_UNIT_DIR}/{self.timer_unit}"


# Issue #585 required capabilities. Adding a capability here requires a
# matching entry in deploy/ownership/account_runtime_capability_ownership_v1.json
# (owner_host) and reviewed unit files under deploy/systemd/.
CAPABILITY_UNIT_CONTRACTS: Final[dict[str, SystemdUnitContractV1]] = {
    "AUTOMATIC_EXIT_POLICY_RUNTIME": SystemdUnitContractV1(
        capability_id="AUTOMATIC_EXIT_POLICY_RUNTIME",
        owner_host="gurkdb",
        service_unit="synth-automatic-exit-policy-runtime.service",
        timer_unit="synth-automatic-exit-policy-runtime.timer",
    ),
    "SHARED_EXECUTOR_RUNTIME": SystemdUnitContractV1(
        capability_id="SHARED_EXECUTOR_RUNTIME",
        owner_host="gurkdb",
        service_unit="synth-shared-executor-runtime.service",
        timer_unit="synth-shared-executor-runtime.timer",
    ),
}


@dataclass(frozen=True)
class SystemdUnitStateV1:
    """Observed, read-only ``systemctl show`` state for one unit."""

    unit: str
    load_state: str = ""
    active_state: str = ""
    unit_file_state: str = ""
    fragment_path: str = ""
    probe_error: str = ""


# Dependency-injection seam: production uses probe_systemd_unit_v1; tests
# inject a fake that never shells out to real systemd.
SystemdUnitProbe = Callable[[str], SystemdUnitStateV1]

# --- Host-truth seam ---------------------------------------------------------
#
# A local ``systemctl show`` probe only proves something about *this* host's
# units. It can never prove anything about a capability's declared owner host
# unless this process is actually executing on that owner host. Without this
# check, any machine with identically named local units (healthy or not)
# could reach STATUS_READY purely because the ownership *registry* happens to
# record the correct owner_host string -- a value describing intended
# ownership, not where this code is currently running.
HostnameResolver = Callable[[], str]


def default_hostname_resolver_v1() -> str:
    """Read-only local hostname read. Never mutates anything."""
    return socket.gethostname()


def _parse_show_properties(output: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value
    return properties


def probe_systemd_unit_v1(
    unit: str,
    *,
    systemctl_binary: str = "systemctl",
    timeout_seconds: int = 10,
) -> SystemdUnitStateV1:
    """Read-only ``systemctl show`` probe for one unit. Never mutates systemd."""
    command = [
        systemctl_binary,
        "--system",
        "show",
        unit,
        "--no-pager",
        "--property=LoadState,ActiveState,UnitFileState,FragmentPath",
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
        return SystemdUnitStateV1(unit=unit, probe_error=f"systemctl show failed: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"rc={result.returncode}"
        return SystemdUnitStateV1(unit=unit, probe_error=f"systemctl show failed: {detail}")

    properties = _parse_show_properties(result.stdout)
    return SystemdUnitStateV1(
        unit=unit,
        load_state=properties.get("LoadState", ""),
        active_state=properties.get("ActiveState", ""),
        unit_file_state=properties.get("UnitFileState", ""),
        fragment_path=properties.get("FragmentPath", ""),
    )


@dataclass(frozen=True)
class CapabilityRuntimeReadinessV1:
    capability_id: str
    status: str
    reason_code: str
    detail: dict[str, Any] = field(default_factory=dict)


def _not_ready(
    capability_id: str, reason_code: str, detail: dict[str, Any]
) -> CapabilityRuntimeReadinessV1:
    return CapabilityRuntimeReadinessV1(
        capability_id=capability_id, status=STATUS_NOT_READY, reason_code=reason_code, detail=detail
    )


def evaluate_capability_runtime_readiness_v1(
    capability_id: str,
    *,
    registry_owner_host: str | None,
    probe: SystemdUnitProbe = probe_systemd_unit_v1,
    hostname_resolver: HostnameResolver = default_hostname_resolver_v1,
) -> CapabilityRuntimeReadinessV1:
    """Evaluate one capability's actual, observed systemd runtime state.

    Fails closed on every unresolved condition: unknown capability, missing
    registry entry, wrong owner, wrong probe host, unit not found, wrong
    installed fragment path, disabled timer, inactive timer, or a probe
    error. The oneshot service's own ``active_state`` is deliberately never
    a pass/fail condition -- it is expected to be idle/dead between timer
    firings; only the timer's enabled+active state is authoritative for "is
    this capability actually scheduled to run."

    Local systemd state is never treated as this capability's canonical
    runtime truth unless ``hostname_resolver()`` -- the actual host this
    process is executing on -- equals the capability's declared owner host.
    Any mismatch fails closed *before* the local probe is even consulted:
    identically named healthy local units on the wrong host must never be
    able to reach STATUS_READY.
    """
    contract = CAPABILITY_UNIT_CONTRACTS.get(capability_id)
    if contract is None:
        return _not_ready(capability_id, "UNKNOWN_CAPABILITY", {})

    if registry_owner_host is None:
        return _not_ready(capability_id, "REGISTRY_ENTRY_MISSING", {})
    if registry_owner_host != contract.owner_host:
        return _not_ready(
            capability_id,
            "REGISTRY_OWNER_MISMATCH",
            {
                "expected_owner_host": contract.owner_host,
                "observed_owner_host": registry_owner_host,
            },
        )

    observed_local_host = hostname_resolver()
    if observed_local_host != contract.owner_host:
        return _not_ready(
            capability_id,
            "RUNTIME_PROBE_NOT_ON_OWNER_HOST",
            {
                "expected_owner_host": contract.owner_host,
                "observed_local_host": observed_local_host,
            },
        )

    try:
        service_state = probe(contract.service_unit)
    except Exception as exc:  # noqa: BLE001 - probe failure must fail closed, not raise
        return _not_ready(
            capability_id,
            "SERVICE_PROBE_FAILED",
            {"service_unit": contract.service_unit, "exception_type": type(exc).__name__},
        )
    try:
        timer_state = probe(contract.timer_unit)
    except Exception as exc:  # noqa: BLE001
        return _not_ready(
            capability_id,
            "TIMER_PROBE_FAILED",
            {"timer_unit": contract.timer_unit, "exception_type": type(exc).__name__},
        )

    detail: dict[str, Any] = {
        "owner_host": registry_owner_host,
        "service_unit": contract.service_unit,
        "service_load_state": service_state.load_state,
        "service_active_state": service_state.active_state,
        "service_fragment_path": service_state.fragment_path,
        "timer_unit": contract.timer_unit,
        "timer_load_state": timer_state.load_state,
        "timer_active_state": timer_state.active_state,
        "timer_unit_file_state": timer_state.unit_file_state,
        "timer_fragment_path": timer_state.fragment_path,
    }

    if service_state.probe_error:
        return _not_ready(capability_id, "SERVICE_PROBE_FAILED", {**detail, "probe_error": service_state.probe_error})
    if timer_state.probe_error:
        return _not_ready(capability_id, "TIMER_PROBE_FAILED", {**detail, "probe_error": timer_state.probe_error})

    if service_state.load_state != _LOAD_STATE_LOADED:
        return _not_ready(capability_id, "SERVICE_UNIT_NOT_FOUND", detail)
    if service_state.fragment_path != contract.expected_service_fragment_path:
        return _not_ready(capability_id, "SERVICE_UNIT_WRONG_FRAGMENT_PATH", detail)

    if timer_state.load_state != _LOAD_STATE_LOADED:
        return _not_ready(capability_id, "TIMER_UNIT_NOT_FOUND", detail)
    if timer_state.fragment_path != contract.expected_timer_fragment_path:
        return _not_ready(capability_id, "TIMER_UNIT_WRONG_FRAGMENT_PATH", detail)
    if timer_state.unit_file_state != _ENABLED_UNIT_FILE_STATE:
        return _not_ready(capability_id, "TIMER_NOT_ENABLED", detail)
    if timer_state.active_state != _ACTIVE_STATE_ACTIVE:
        return _not_ready(capability_id, "TIMER_NOT_ACTIVE", detail)

    return CapabilityRuntimeReadinessV1(
        capability_id=capability_id, status=STATUS_READY, reason_code="OK", detail=detail
    )
