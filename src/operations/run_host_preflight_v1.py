"""
host_preflight_v1

Generic, read-only host-readiness preflight for writer-capability host
selection and acceptance.

This runner supports the ownership correction documented in
`docs/ops/writer_capability_host_ownership_contract_v1.md`. It answers a single
question read-only: "is this host, as observed right now, plausibly ready to be
*considered* as an acceptance or production host for a public market-data writer
capability?" It never selects a host, installs anything, runs a writer, or
writes the database.

Safety boundary:
- read-only local host inspection only (platform / os / shutil / subprocess
  `uname` for host facts)
- no installation, no `systemctl` mutation, no timer activation
- no writer invocation
- no database write and no database connection
- no exchange / broker call of any kind
- external facts that cannot be proven read-only here stay UNVERIFIED

Any check whose truth cannot be established by pure local read-only inspection
is reported UNVERIFIED by design — this runner must never invent a host fact.

broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
host_mutations=0 database_writes=0 writer_invocations=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

RUNNER_NAME = "host_preflight_v1"
RUNNER_VERSION = "0.1"

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_UNVERIFIED = "UNVERIFIED"

# The full required preflight checklist. Locally measurable items are resolved
# read-only below; every other item is reported UNVERIFIED because proving it
# would require a network probe, a DB connection, or host state this read-only
# runner deliberately does not touch.
CHECKLIST = (
    "host_identity",
    "os_and_architecture",
    "cpu_and_load",
    "ram_and_swap",
    "disk_space_and_inodes",
    "python_and_virtualenv",
    "deployment_artifact_strategy",
    "mariadb_connectivity",
    "exchange_api_connectivity",
    "dns",
    "ntp_time_sync",
    "systemd",
    "journald_logrotation",
    "secrets_and_configuration",
    "locks_and_overlap_protection",
    "runtime_per_writer",
    "resource_usage_per_writer",
    "firewall_outbound_connectivity",
    "rollback_capability",
)

# Checks this read-only runner will not attempt to prove; they require a
# network probe, an authenticated connection, or host-specific runtime
# evidence that belongs to the separately authorized acceptance step.
UNVERIFIED_BY_DESIGN = {
    "mariadb_connectivity": "requires a DB connection; not attempted read-only",
    "exchange_api_connectivity": "requires an exchange call; not attempted",
    "dns": "requires a network resolve; not attempted read-only",
    "ntp_time_sync": "requires querying a time source; not attempted",
    "secrets_and_configuration": "must be verified out-of-band; not read here",
    "runtime_per_writer": "proven only by a controlled acceptance run",
    "resource_usage_per_writer": "proven only by a controlled acceptance run",
    "firewall_outbound_connectivity": "requires an outbound probe; not attempted",
    "rollback_capability": "proven only by a documented cutover/rollback plan",
    "deployment_artifact_strategy": "declared by the host-selection decision",
    "journald_logrotation": "requires reading host retention config out-of-band",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def _uname() -> str:
    try:
        return subprocess.run(
            ["uname", "-a"], capture_output=True, text=True, timeout=5, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _host_identity() -> CheckResult:
    node = platform.node().strip()
    if node:
        return CheckResult("host_identity", STATUS_PASS, f"hostname={node}")
    return CheckResult("host_identity", STATUS_UNVERIFIED, "hostname not resolvable")


def _os_and_architecture() -> CheckResult:
    detail = f"system={platform.system()} release={platform.release()} machine={platform.machine()}"
    uname = _uname()
    if uname:
        detail = f"{detail} uname='{uname}'"
    return CheckResult("os_and_architecture", STATUS_PASS, detail)


def _cpu_and_load() -> CheckResult:
    cpu_count = os.cpu_count() or 0
    try:
        load1, load5, load15 = os.getloadavg()
        load_detail = f"load1={load1:.2f} load5={load5:.2f} load15={load15:.2f}"
    except (OSError, AttributeError):
        return CheckResult(
            "cpu_and_load", STATUS_WARN, f"cpu_count={cpu_count} loadavg=UNAVAILABLE"
        )
    status = STATUS_PASS
    if cpu_count and load1 > cpu_count * 2:
        status = STATUS_WARN
    return CheckResult("cpu_and_load", status, f"cpu_count={cpu_count} {load_detail}")


def _read_meminfo_kb(key: str) -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(f"{key}:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _ram_and_swap() -> CheckResult:
    total = _read_meminfo_kb("MemTotal")
    available = _read_meminfo_kb("MemAvailable")
    swap_total = _read_meminfo_kb("SwapTotal")
    if total is None:
        return CheckResult("ram_and_swap", STATUS_UNVERIFIED, "/proc/meminfo unreadable")
    detail = (
        f"mem_total_mb={total // 1024} mem_available_mb="
        f"{(available // 1024) if available is not None else 'NA'} "
        f"swap_total_mb={(swap_total // 1024) if swap_total is not None else 'NA'}"
    )
    return CheckResult("ram_and_swap", STATUS_PASS, detail)


def _disk_space_and_inodes(path: str) -> CheckResult:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return CheckResult("disk_space_and_inodes", STATUS_FAIL, f"disk_usage error: {exc}")
    used_pct = (usage.used / usage.total * 100.0) if usage.total else 0.0
    status = STATUS_PASS
    if used_pct >= 95.0:
        status = STATUS_FAIL
    elif used_pct >= 85.0:
        status = STATUS_WARN
    inode_detail = ""
    try:
        st = os.statvfs(path)
        if st.f_files:
            inode_pct = (st.f_files - st.f_ffree) / st.f_files * 100.0
            inode_detail = f" inodes_used_pct={inode_pct:.1f}"
            if inode_pct >= 95.0:
                status = STATUS_FAIL
    except (OSError, AttributeError):
        inode_detail = " inodes=UNVERIFIED"
    detail = (
        f"path={path} total_gb={usage.total / 1e9:.1f} "
        f"free_gb={usage.free / 1e9:.1f} used_pct={used_pct:.1f}{inode_detail}"
    )
    return CheckResult("disk_space_and_inodes", status, detail)


def _python_and_virtualenv(path: str) -> CheckResult:
    py = platform.python_version()
    venv = None
    for candidate in ("venv/bin/activate", ".venv/bin/activate"):
        if os.path.exists(os.path.join(path, candidate)):
            venv = candidate
            break
    if venv:
        return CheckResult(
            "python_and_virtualenv", STATUS_PASS, f"python={py} venv={venv}"
        )
    return CheckResult(
        "python_and_virtualenv",
        STATUS_WARN,
        f"python={py} venv=NOT_FOUND (checked venv/.venv under {path})",
    )


def _systemd() -> CheckResult:
    if os.path.isdir("/run/systemd/system"):
        return CheckResult("systemd", STATUS_PASS, "systemd init detected (/run/systemd/system)")
    return CheckResult(
        "systemd",
        STATUS_WARN,
        "no /run/systemd/system: host not booted with systemd as init",
    )


def _locks_and_overlap_protection() -> CheckResult:
    # Read-only presence check for the writer lock directory; lock behavior
    # itself is proven only by an acceptance run.
    if os.path.isdir("/tmp"):
        return CheckResult(
            "locks_and_overlap_protection",
            STATUS_PASS,
            "flock lock namespace /tmp present (behavior proven at acceptance)",
        )
    return CheckResult(
        "locks_and_overlap_protection", STATUS_WARN, "/tmp not present"
    )


def run_preflight(path: str) -> list[CheckResult]:
    measured = {
        "host_identity": _host_identity(),
        "os_and_architecture": _os_and_architecture(),
        "cpu_and_load": _cpu_and_load(),
        "ram_and_swap": _ram_and_swap(),
        "disk_space_and_inodes": _disk_space_and_inodes(path),
        "python_and_virtualenv": _python_and_virtualenv(path),
        "systemd": _systemd(),
        "locks_and_overlap_protection": _locks_and_overlap_protection(),
    }
    results: list[CheckResult] = []
    for name in CHECKLIST:
        if name in measured:
            results.append(measured[name])
        else:
            reason = UNVERIFIED_BY_DESIGN.get(name, "not proven read-only")
            results.append(CheckResult(name, STATUS_UNVERIFIED, reason))
    return results


def _print_safety_markers() -> None:
    print(
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "host_mutations=0 database_writes=0 writer_invocations=0 "
        "decision_gate=none execution_planner=none executor=none"
    )


def _render_table(results: list[CheckResult]) -> str:
    width = max(len(r.name) for r in results)
    lines = [f"{'CHECK'.ljust(width)}  STATUS      DETAIL"]
    for r in results:
        lines.append(f"{r.name.ljust(width)}  {r.status.ljust(10)}  {r.detail}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only host preflight for writer-capability host selection. "
            "Performs no install, writer run, database write, or broker call."
        )
    )
    parser.add_argument(
        "--path",
        default=os.getcwd(),
        help="Repository/runtime path whose filesystem and venv are inspected.",
    )
    parser.add_argument("--output", choices=("table", "json"), default="table")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any measurable local check is FAIL (UNVERIFIED never fails).",
    )
    args = parser.parse_args()

    ts = datetime.now(UTC).replace(microsecond=0).isoformat()
    results = run_preflight(args.path)

    counts = {STATUS_PASS: 0, STATUS_WARN: 0, STATUS_FAIL: 0, STATUS_UNVERIFIED: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    if args.output == "json":
        payload = {
            "runner": RUNNER_NAME,
            "version": RUNNER_VERSION,
            "ts_utc": ts,
            "path": args.path,
            "safety_markers": {
                "host_mutations": 0,
                "database_writes": 0,
                "writer_invocations": 0,
                "broker_private_calls": 0,
                "broker_writes": 0,
            },
            "counts": counts,
            "checks": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"STARTED runner={RUNNER_NAME} mode=read_only path={args.path} ts={ts}")
        _print_safety_markers()
        print(_render_table(results))
        print(
            f"FINISHED runner={RUNNER_NAME} pass={counts[STATUS_PASS]} "
            f"warn={counts[STATUS_WARN]} fail={counts[STATUS_FAIL]} "
            f"unverified={counts[STATUS_UNVERIFIED]} ts={ts}"
        )

    if args.strict and counts[STATUS_FAIL] > 0:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
