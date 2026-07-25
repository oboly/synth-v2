"""
Read-only installed-systemd equivalence preflight for native_short_4h_chain.

This runner compares the canonical devlap repository service/timer pair with
the installed system-level unit fragments and their observed inactive state.
It never installs, reloads, enables, starts, stops, disables, or masks units.

Safety boundary:
host_mutations=0 systemctl_mutations=0 database_writes=0 writer_invocations=0
canonical_publication=0 broker_private_calls=0 broker_writes=0
order_submission=0 live_orders=0 decision_gate=none execution_planner=none
executor=none
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


RUNNER_NAME = "native_short_systemd_equivalence_preflight_v1"
RUNNER_VERSION = "v1"

SERVICE_UNIT = "synth-chain-4h.service"
TIMER_UNIT = "synth-chain-4h.timer"
LEGACY_UNITS = (
    "synth-4h-market-chain.service",
    "synth-4h-market-chain.timer",
)
SERVICE_REL_PATH = Path("deploy/systemd") / SERVICE_UNIT
TIMER_REL_PATH = Path("deploy/systemd") / TIMER_UNIT

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"

EXPECTED_SERVICE_FIELDS = {
    ("Unit", "ConditionHost"): ("devlap",),
    ("Service", "User"): ("gurk",),
    ("Service", "Group"): ("gurk",),
    ("Service", "WorkingDirectory"): ("/home/gurk/projects/synth-v2",),
    ("Service", "ExecStart"): (
        "/bin/bash /home/gurk/projects/synth-v2/scripts/run_chain_4h.sh",
    ),
    ("Service", "ExecStartPre"): (
        "/home/gurk/projects/synth-v2/venv/bin/python "
        "-m src.operations.verify_writer_capability_authorization_v1 "
        "--capability native_short_4h_chain "
        "--service synth-chain-4h.service "
        "--checkout-path /home/gurk/projects/synth-v2 "
        "--registry deploy/ownership/writer_capability_ownership_v1.json",
    ),
    ("Service", "EnvironmentFile"): (),
    ("Service", "Environment"): (
        "SYNTH_REPO_DIR=/home/gurk/projects/synth-v2",
        "SYNTH_CHAIN_4H_LOCKED=0",
        "SYNTH_CHAIN_4H_LOCK_FILE=/tmp/synth_chain_4h.lock",
        "SYNTH_EXECUTION_MODE=paper",
        "SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED",
        "SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED",
        "SYNTH_WRITER_EXECUTION_MODE=PRODUCTION",
    ),
    ("Service", "PrivateTmp"): ("false",),
}

EXPECTED_TIMER_FIELDS = {
    ("Unit", "ConditionHost"): ("devlap",),
    ("Unit", "Requires"): (),
    ("Unit", "Wants"): (),
    ("Timer", "OnCalendar"): ("*-*-* 00,04,08,12,16,20:12:00 UTC",),
    ("Timer", "Persistent"): ("true",),
    ("Timer", "RandomizedDelaySec"): ("120",),
    ("Timer", "AccuracySec"): ("1s",),
    ("Timer", "Unit"): (SERVICE_UNIT,),
}

EXPECTED_UNIT_FILE_STATE = "disabled"
EXPECTED_ACTIVE_STATE = "inactive"


@dataclass(frozen=True)
class UnitState:
    unit: str
    load_state: str
    fragment_path: str
    drop_in_paths: str
    unit_file_state: str
    active_state: str
    content: bytes | None
    error: str = ""


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


UnitLoader = Callable[[str, str], UnitState]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse_unit(content: bytes) -> dict[tuple[str, str], tuple[str, ...]]:
    fields: dict[tuple[str, str], list[str]] = {}
    section = ""
    logical_lines: list[str] = []
    pending = ""
    for raw_line in content.decode("utf-8").splitlines():
        stripped = raw_line.rstrip()
        if pending:
            stripped = pending + stripped.lstrip()
        if stripped.endswith("\\"):
            pending = stripped[:-1]
            continue
        pending = ""
        logical_lines.append(stripped)
    if pending:
        logical_lines.append(pending)

    for line in logical_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        if not section or "=" not in line:
            continue
        key, value = line.split("=", 1)
        token = (section, key.strip())
        fields.setdefault(token, []).append(value.strip())
    return {key: tuple(values) for key, values in fields.items()}


def _show_properties(output: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value
    return properties


def _load_unit_state(unit: str, systemctl: str) -> UnitState:
    command = [
        systemctl,
        "--system",
        "show",
        unit,
        "--no-pager",
        "--property=LoadState,FragmentPath,DropInPaths,UnitFileState,ActiveState",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return UnitState(unit, "", "", "", "", "", None, f"systemctl show failed: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"rc={result.returncode}"
        return UnitState(unit, "", "", "", "", "", None, f"systemctl show failed: {detail}")

    properties = _show_properties(result.stdout)
    fragment_path = properties.get("FragmentPath", "")
    content: bytes | None = None
    error = ""
    if fragment_path:
        try:
            content = Path(fragment_path).read_bytes()
        except OSError as exc:
            error = f"installed fragment unreadable path={fragment_path}: {exc}"
    return UnitState(
        unit=unit,
        load_state=properties.get("LoadState", ""),
        fragment_path=fragment_path,
        drop_in_paths=properties.get("DropInPaths", ""),
        unit_file_state=properties.get("UnitFileState", ""),
        active_state=properties.get("ActiveState", ""),
        content=content,
        error=error,
    )


def _field_detail(
    parsed: dict[tuple[str, str], tuple[str, ...]],
    expected: dict[tuple[str, str], tuple[str, ...]],
    keys: tuple[tuple[str, str], ...],
) -> tuple[bool, str]:
    mismatches = []
    for key in keys:
        actual = parsed.get(key, ())
        wanted = expected[key]
        if actual != wanted:
            mismatches.append(f"{key[0]}.{key[1]} expected={wanted!r} actual={actual!r}")
    if mismatches:
        return False, "; ".join(mismatches)
    rendered = ", ".join(f"{section}.{key}={expected[(section, key)]!r}" for section, key in keys)
    return True, rendered


def _semantic_check(
    name: str,
    state: UnitState,
    expected: dict[tuple[str, str], tuple[str, ...]],
    keys: tuple[tuple[str, str], ...],
) -> CheckResult:
    if state.content is None:
        return CheckResult(name, STATUS_FAIL, state.error or f"{state.unit} content unavailable")
    ok, detail = _field_detail(_parse_unit(state.content), expected, keys)
    return CheckResult(name, STATUS_PASS if ok else STATUS_FAIL, detail)


def _repository_contract_check(
    name: str,
    content: bytes,
    expected: dict[tuple[str, str], tuple[str, ...]],
) -> CheckResult:
    ok, detail = _field_detail(_parse_unit(content), expected, tuple(expected))
    return CheckResult(name, STATUS_PASS if ok else STATUS_FAIL, detail)


def _presence_check(name: str, state: UnitState) -> CheckResult:
    ok = state.load_state == "loaded" and state.content is not None and not state.error
    detail = (
        f"unit={state.unit} load_state={state.load_state or 'UNAVAILABLE'} "
        f"fragment_path={state.fragment_path or 'NONE'}"
    )
    if state.error:
        detail = f"{detail} error={state.error}"
    return CheckResult(name, STATUS_PASS if ok else STATUS_FAIL, detail)


def _hash_check(name: str, repository: bytes, state: UnitState) -> CheckResult:
    expected_hash = _sha256(repository)
    actual_hash = _sha256(state.content) if state.content is not None else "UNAVAILABLE"
    return CheckResult(
        name,
        STATUS_PASS if actual_hash == expected_hash else STATUS_FAIL,
        f"repository_sha256={expected_hash} installed_sha256={actual_hash}",
    )


def _drop_in_check(name: str, state: UnitState) -> CheckResult:
    ok = (
        state.load_state == "loaded"
        and not state.error
        and not state.drop_in_paths.strip()
    )
    return CheckResult(
        name,
        STATUS_PASS if ok else STATUS_FAIL,
        f"unit={state.unit} load_state={state.load_state or 'UNAVAILABLE'} "
        f"drop_in_paths={state.drop_in_paths or 'NONE'}"
        + (f" error={state.error}" if state.error else ""),
    )


def _state_check(name: str, state: UnitState) -> CheckResult:
    ok = (
        state.unit_file_state == EXPECTED_UNIT_FILE_STATE
        and state.active_state == EXPECTED_ACTIVE_STATE
    )
    return CheckResult(
        name,
        STATUS_PASS if ok else STATUS_FAIL,
        f"unit={state.unit} unit_file_state={state.unit_file_state or 'UNAVAILABLE'} "
        f"active_state={state.active_state or 'UNAVAILABLE'} "
        f"expected={EXPECTED_UNIT_FILE_STATE}/{EXPECTED_ACTIVE_STATE}",
    )


def run_preflight(
    *,
    checkout_path: Path,
    systemctl: str,
    unit_loader: UnitLoader | None = None,
) -> list[CheckResult]:
    loader = unit_loader or _load_unit_state
    service_repository = (checkout_path / SERVICE_REL_PATH).read_bytes()
    timer_repository = (checkout_path / TIMER_REL_PATH).read_bytes()
    service = loader(SERVICE_UNIT, systemctl)
    timer = loader(TIMER_UNIT, systemctl)

    results = [
        _repository_contract_check(
            "repository_service_contract", service_repository, EXPECTED_SERVICE_FIELDS
        ),
        _repository_contract_check(
            "repository_timer_contract", timer_repository, EXPECTED_TIMER_FIELDS
        ),
        _presence_check("service_presence", service),
        _presence_check("timer_presence", timer),
        _hash_check("service_content_sha256", service_repository, service),
        _hash_check("timer_content_sha256", timer_repository, timer),
        _drop_in_check("service_drop_ins", service),
        _drop_in_check("timer_drop_ins", timer),
        _semantic_check(
            "service_user_group",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Service", "User"), ("Service", "Group")),
        ),
        _semantic_check(
            "service_working_directory",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Service", "WorkingDirectory"),),
        ),
        _semantic_check(
            "service_command",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Service", "ExecStart"),),
        ),
        _semantic_check(
            "service_authorization",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Service", "ExecStartPre"),),
        ),
        _semantic_check(
            "service_environment_files",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Service", "EnvironmentFile"),),
        ),
        _semantic_check(
            "service_environment",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Service", "Environment"),),
        ),
        _semantic_check(
            "service_lock",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Service", "PrivateTmp"), ("Service", "Environment")),
        ),
        _semantic_check(
            "service_host_condition",
            service,
            EXPECTED_SERVICE_FIELDS,
            (("Unit", "ConditionHost"),),
        ),
        _semantic_check(
            "timer_activation_dependencies",
            timer,
            EXPECTED_TIMER_FIELDS,
            (
                ("Unit", "Requires"),
                ("Unit", "Wants"),
                ("Timer", "Unit"),
            ),
        ),
        _semantic_check(
            "timer_cadence",
            timer,
            EXPECTED_TIMER_FIELDS,
            (
                ("Timer", "OnCalendar"),
                ("Timer", "Persistent"),
                ("Timer", "RandomizedDelaySec"),
                ("Timer", "AccuracySec"),
                ("Timer", "Unit"),
            ),
        ),
        _semantic_check(
            "timer_host_condition",
            timer,
            EXPECTED_TIMER_FIELDS,
            (("Unit", "ConditionHost"),),
        ),
        _state_check("service_enabled_active_state", service),
        _state_check("timer_enabled_active_state", timer),
    ]

    legacy_states = [loader(unit, systemctl) for unit in LEGACY_UNITS]
    legacy_ok = all(state.load_state == "not-found" for state in legacy_states)
    legacy_detail = ", ".join(
        f"{state.unit}={state.load_state or 'UNAVAILABLE'}/{state.active_state or 'UNAVAILABLE'}"
        for state in legacy_states
    )
    results.append(
        CheckResult(
            "legacy_systemd_units_absent",
            STATUS_PASS if legacy_ok else STATUS_FAIL,
            legacy_detail,
        )
    )
    return results


def _safety_markers() -> dict[str, int | str]:
    return {
        "host_mutations": 0,
        "systemctl_mutations": 0,
        "database_writes": 0,
        "writer_invocations": 0,
        "canonical_publication": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "decision_gate": "none",
        "execution_planner": "none",
        "executor": "none",
    }


def _print_safety_markers() -> None:
    print(" ".join(f"{key}={value}" for key, value in _safety_markers().items()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only exact installed-unit equivalence preflight for the "
            "devlap native_short_4h_chain systemd pair."
        )
    )
    parser.add_argument("--checkout-path", type=Path, default=Path.cwd())
    parser.add_argument("--systemctl", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    args = parser.parse_args()

    checkout_path = args.checkout_path.resolve()
    systemctl = args.systemctl or shutil.which("systemctl")
    if not systemctl:
        print(f"FAILED runner={RUNNER_NAME} reason=SYSTEMCTL_NOT_FOUND")
        _print_safety_markers()
        return 2

    ts = datetime.now(UTC).replace(microsecond=0).isoformat()
    try:
        results = run_preflight(checkout_path=checkout_path, systemctl=systemctl)
    except OSError as exc:
        print(f"FAILED runner={RUNNER_NAME} reason=REPOSITORY_UNIT_UNREADABLE detail={exc}")
        _print_safety_markers()
        return 2

    failed = [result for result in results if result.status == STATUS_FAIL]
    status = "PASS" if not failed else "MISMATCH"
    if args.output == "json":
        print(
            json.dumps(
                {
                    "runner": RUNNER_NAME,
                    "version": RUNNER_VERSION,
                    "ts_utc": ts,
                    "status": status,
                    "checkout_path": str(checkout_path),
                    "expected_enabled_active_state": "disabled/inactive",
                    "safety_markers": _safety_markers(),
                    "checks": [asdict(result) for result in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(
            f"STARTED runner={RUNNER_NAME} mode=read_only scope=system_systemd "
            f"checkout_path={checkout_path} worker_count=1 ts={ts}"
        )
        _print_safety_markers()
        for result in results:
            print(f"CHECK name={result.name} status={result.status} detail={result.detail}")
        print(
            f"FINISHED runner={RUNNER_NAME} status={status} "
            f"pass={len(results) - len(failed)} fail={len(failed)} ts={ts}"
        )
    return 0 if not failed else 3


if __name__ == "__main__":
    raise SystemExit(main())
