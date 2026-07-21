"""
host_preflight_v1

Read-only, stage-aware host-readiness preflight for writer-capability host
selection.

This runner proves only local facts that can be inspected without mutating host
state. It never selects a host, installs a unit, activates a timer, invokes a
writer, writes a database, or calls an exchange/broker.

Evidence stages
---------------
Every check declares an explicit evidence stage:

    PREFLIGHT_LOCAL     provable by read-only local inspection here
    PREFLIGHT_EXTERNAL  provable only by a separately authorized external probe
    ACCEPTANCE          provable only by a controlled acceptance run
    CUTOVER             provable only by a documented cutover/rollback drill

Strict host preflight (`--strict`) requires only PREFLIGHT_LOCAL and
PREFLIGHT_EXTERNAL checks. ACCEPTANCE and CUTOVER checks remain visible but are
deferred and non-blocking during preflight; they are never silently marked PASS.

Preflight-external checks are `UNVERIFIED` here unless a separately produced,
matching external-evidence manifest is supplied via `--external-evidence-file`.
Local checks are always authoritative and can never be overridden by evidence.

Safety boundary:
- read-only local host inspection
- bounded subprocess calls with list arguments and timeouts
- no systemctl mutation
- no writer invocation
- no database connection or write
- no exchange / broker call
- no command execution from any evidence file
- unproved external/acceptance/cutover facts remain UNVERIFIED

broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
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
from pathlib import Path


RUNNER_NAME = "host_preflight_v1"
RUNNER_VERSION = "0.3"

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_UNVERIFIED = "UNVERIFIED"

STAGE_PREFLIGHT_LOCAL = "PREFLIGHT_LOCAL"
STAGE_PREFLIGHT_EXTERNAL = "PREFLIGHT_EXTERNAL"
STAGE_ACCEPTANCE = "ACCEPTANCE"
STAGE_CUTOVER = "CUTOVER"

CAPABILITY_MODULES = {
    "public_price_snapshot": ("src.market_data.run_market_price_snapshot_v1",),
    "public_candle_freshness": ("src.etl.bitvavo.run_candles_etl",),
    "market_rotation_pressure": (
        "src.research.run_market_rotation_history_v1",
        "src.research.run_market_rotation_pressure_v1",
    ),
    "native_short_4h_chain": (
        "src.market_data.native_short_repository_source_identity_v1",
        "src.operations.run_persisted_market_price_freshness_v1",
        "src.operations.run_persisted_market_candle_freshness_v1",
        "src.market_data.run_native_short_scope_status_chain_v1",
        "src.market_data.run_native_short_fib_context_snapshot_v1",
        "src.features.run_feat_candle",
        "src.signal_engine.run_signal_state_etl",
        "src.advice.run_advice_engine",
        "src.ranking.run_ranking_engine",
        "src.measurement.run_asset_interval_quality_snapshot",
        "src.selection.run_selection_engine_v2",
        "src.zone.run_zone_engine_v1",
        "src.trade_setup_filter.run_trade_setup_filter_v1",
        "src.research.run_trade_setup_filter_policy_preview_v1",
        "src.advice.run_paper_advice_policy_v1",
        "src.strategy_runtime.run_strategy_runtime_snapshot",
    ),
}

CAPABILITY_UNITS = {
    "public_price_snapshot": (
        "deploy/systemd/synth-market-price-snapshot-writer.service",
        "deploy/systemd/synth-market-price-snapshot-writer.timer",
    ),
    "public_candle_freshness": (
        "deploy/systemd/synth-market-candle-freshness-writer.service",
        "deploy/systemd/synth-market-candle-freshness-writer.timer",
    ),
    "market_rotation_pressure": (
        "deploy/systemd/synth-market-rotation-pressure-writer.service",
        "deploy/systemd/synth-market-rotation-pressure-writer.timer",
    ),
    "native_short_4h_chain": (
        "deploy/systemd/synth-chain-4h.service",
        "deploy/systemd/synth-chain-4h.timer",
    ),
}

CAPABILITY_THRESHOLDS = {
    "public_price_snapshot": {"min_cpus": 1, "min_mem_mb": 512, "min_free_gb": 1.0},
    "public_candle_freshness": {"min_cpus": 1, "min_mem_mb": 1024, "min_free_gb": 2.0},
    "market_rotation_pressure": {"min_cpus": 1, "min_mem_mb": 1024, "min_free_gb": 2.0},
    "native_short_4h_chain": {"min_cpus": 2, "min_mem_mb": 4096, "min_free_gb": 10.0},
}

# Locally measurable, read-only host facts. Always authoritative; never merged
# from external evidence.
PREFLIGHT_LOCAL_CHECKS = (
    "capability_identity",
    "host_identity",
    "checkout_commit",
    "os_and_architecture",
    "cpu_and_load",
    "ram_and_swap",
    "disk_space_and_inodes",
    "python_and_virtualenv",
    "capability_module_imports",
    "flock",
    "systemd_availability",
    "systemd_unit_validation",
)

# Facts that require a separately authorized external probe (DB/exchange/network/
# host policy). These are the only checks an external-evidence manifest may fill.
PREFLIGHT_EXTERNAL_CHECKS = (
    "mariadb_connectivity",
    "exchange_api_connectivity",
    "dns",
    "ntp_time_sync",
    "journald_logrotation",
    "secrets_and_configuration",
    "firewall_outbound_connectivity",
)

# Deferred: provable only by a controlled acceptance run after separate
# authorization. Non-blocking during preflight.
ACCEPTANCE_CHECKS = (
    "runtime_per_writer",
    "resource_usage_per_writer",
)

# Deferred: provable only by a documented cutover/rollback drill. Non-blocking
# during preflight.
CUTOVER_CHECKS = ("rollback_capability",)

CHECK_ORDER = (
    *PREFLIGHT_LOCAL_CHECKS,
    *PREFLIGHT_EXTERNAL_CHECKS,
    *ACCEPTANCE_CHECKS,
    *CUTOVER_CHECKS,
)

# Base rationale for each external check when it is not yet proven here.
EXTERNAL_CHECK_DESIGN = {
    "mariadb_connectivity": "requires a DB connection; proven by a separately authorized external probe",
    "exchange_api_connectivity": "requires an exchange call; proven by a separately authorized external probe",
    "dns": "requires a network resolve; proven by a separately authorized external probe",
    "ntp_time_sync": "requires querying a time source; proven by a separately authorized external probe",
    "journald_logrotation": "requires host retention policy evidence; proven by a separately authorized external probe",
    "secrets_and_configuration": "must be verified out-of-band; secret values are never read here",
    "firewall_outbound_connectivity": "requires an outbound probe; proven by a separately authorized external probe",
}

# Capability-specific external requirements. Default is required=True for every
# preflight-external check; overrides below mark a check non-required only when
# the capability's proven call graph does not depend on it. Public exchange
# endpoints (bitvavo public ticker/candles) require no private credentials, so
# secrets_and_configuration is not required for the public writers.
#
# market_rotation_pressure: run_market_rotation_history_v1 and
# run_market_rotation_pressure_v1 read persisted candles from MariaDB and use
# only optional public CoinGecko global context; neither calls the exchange API,
# so exchange_api_connectivity is not required.
CAPABILITY_EXTERNAL_REQUIRED_OVERRIDES = {
    "public_price_snapshot": {"secrets_and_configuration": False},
    "public_candle_freshness": {"secrets_and_configuration": False},
    "market_rotation_pressure": {
        "exchange_api_connectivity": False,
        "secrets_and_configuration": False,
    },
    "native_short_4h_chain": {
        "exchange_api_connectivity": False,
        "secrets_and_configuration": False,
    },
}

# Short, capability-specific justification recorded in the detail for a check
# whose requirement differs from the default.
CAPABILITY_EXTERNAL_NOTES = {
    ("public_price_snapshot", "secrets_and_configuration"): "public bitvavo ticker endpoint needs no private exchange credentials",
    ("public_candle_freshness", "secrets_and_configuration"): "public bitvavo candle endpoint needs no private exchange credentials",
    ("market_rotation_pressure", "exchange_api_connectivity"): "reads persisted candles from MariaDB; only optional public CoinGecko global context; no exchange API dependency",
    ("market_rotation_pressure", "secrets_and_configuration"): "no private exchange credentials; optional CoinGecko key degrades gracefully",
    ("native_short_4h_chain", "exchange_api_connectivity"): "market-only chain consumes persisted market state; does not call the exchange API directly",
    ("native_short_4h_chain", "secrets_and_configuration"): "market-only chain reads persisted state; no private exchange credentials",
}

DEFERRED_CHECK_DESIGN = {
    "runtime_per_writer": (STAGE_ACCEPTANCE, "proven only by a separately authorized controlled acceptance run"),
    "resource_usage_per_writer": (STAGE_ACCEPTANCE, "proven only by a separately authorized controlled acceptance run"),
    "rollback_capability": (STAGE_CUTOVER, "proven only by a documented cutover/rollback drill"),
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    required: bool = True
    stage: str = STAGE_PREFLIGHT_LOCAL
    required_stage: str | None = None
    evidence_source: str | None = None


def _external_required(capability: str, check: str) -> bool:
    return CAPABILITY_EXTERNAL_REQUIRED_OVERRIDES.get(capability, {}).get(check, True)


def _external_placeholder_detail(capability: str, check: str, required: bool) -> str:
    base = EXTERNAL_CHECK_DESIGN[check]
    note = CAPABILITY_EXTERNAL_NOTES.get((capability, check))
    detail = f"{base}; required={str(required).lower()}"
    if note:
        detail = f"{detail}; {note}"
    return detail


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _host_identity(expected_host: str) -> CheckResult:
    node = platform.node().strip()
    if not node:
        return CheckResult("host_identity", STATUS_UNVERIFIED, "hostname not resolvable")
    if node != expected_host:
        return CheckResult("host_identity", STATUS_FAIL, f"actual={node} expected={expected_host}")
    return CheckResult("host_identity", STATUS_PASS, f"actual={node} expected={expected_host}")


def _capability_identity(capability: str) -> CheckResult:
    if capability not in CAPABILITY_MODULES:
        return CheckResult("capability_identity", STATUS_FAIL, f"unknown capability={capability}")
    return CheckResult("capability_identity", STATUS_PASS, f"capability={capability}")


def _checkout_commit(checkout_path: Path, expected_commit: str) -> CheckResult:
    if not checkout_path.exists():
        return CheckResult("checkout_commit", STATUS_FAIL, f"checkout_path missing: {checkout_path}")
    try:
        result = _run(["git", "-C", str(checkout_path), "rev-parse", "--verify", "HEAD"], timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("checkout_commit", STATUS_FAIL, f"git rev-parse failed: {exc}")
    actual = result.stdout.strip()
    if result.returncode != 0 or not actual:
        return CheckResult("checkout_commit", STATUS_FAIL, "checkout HEAD unavailable")
    if actual != expected_commit:
        return CheckResult("checkout_commit", STATUS_FAIL, f"actual={actual} expected={expected_commit}")
    return CheckResult("checkout_commit", STATUS_PASS, f"actual={actual}")


def _os_and_architecture() -> CheckResult:
    system = platform.system()
    machine = platform.machine()
    if system != "Linux":
        return CheckResult("os_and_architecture", STATUS_WARN, f"system={system} machine={machine}")
    try:
        uname = _run(["uname", "-a"], timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        uname = ""
    detail = f"system={system} release={platform.release()} machine={machine}"
    if uname:
        detail = f"{detail} uname={uname}"
    return CheckResult("os_and_architecture", STATUS_PASS, detail)


def _cpu_and_load(capability: str) -> CheckResult:
    thresholds = CAPABILITY_THRESHOLDS.get(capability)
    if thresholds is None:
        return CheckResult("cpu_and_load", STATUS_UNVERIFIED, "no capability threshold configured")
    cpu_count = os.cpu_count() or 0
    if cpu_count < int(thresholds["min_cpus"]):
        return CheckResult("cpu_and_load", STATUS_FAIL, f"cpu_count={cpu_count} min={thresholds['min_cpus']}")
    try:
        load1, load5, load15 = os.getloadavg()
    except (OSError, AttributeError):
        return CheckResult("cpu_and_load", STATUS_WARN, f"cpu_count={cpu_count} loadavg=UNAVAILABLE")
    status = STATUS_PASS if load1 <= max(cpu_count * 2, 1) else STATUS_WARN
    return CheckResult(
        "cpu_and_load",
        status,
        f"cpu_count={cpu_count} min={thresholds['min_cpus']} load1={load1:.2f} load5={load5:.2f} load15={load15:.2f}",
    )


def _read_meminfo_kb(key: str) -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(f"{key}:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _ram_and_swap(capability: str) -> CheckResult:
    thresholds = CAPABILITY_THRESHOLDS.get(capability)
    if thresholds is None:
        return CheckResult("ram_and_swap", STATUS_UNVERIFIED, "no capability threshold configured")
    total = _read_meminfo_kb("MemTotal")
    available = _read_meminfo_kb("MemAvailable")
    swap_total = _read_meminfo_kb("SwapTotal")
    if total is None:
        return CheckResult("ram_and_swap", STATUS_UNVERIFIED, "/proc/meminfo unreadable")
    available_mb = (available or 0) // 1024
    total_mb = total // 1024
    status = STATUS_PASS if available_mb >= int(thresholds["min_mem_mb"]) else STATUS_WARN
    return CheckResult(
        "ram_and_swap",
        status,
        f"mem_total_mb={total_mb} mem_available_mb={available_mb} min_available_mb={thresholds['min_mem_mb']} swap_total_mb={(swap_total // 1024) if swap_total is not None else 'NA'}",
    )


def _disk_space_and_inodes(checkout_path: Path, capability: str) -> CheckResult:
    thresholds = CAPABILITY_THRESHOLDS.get(capability)
    if thresholds is None:
        return CheckResult("disk_space_and_inodes", STATUS_UNVERIFIED, "no capability threshold configured")
    try:
        usage = shutil.disk_usage(checkout_path)
    except OSError as exc:
        return CheckResult("disk_space_and_inodes", STATUS_FAIL, f"disk_usage error: {exc}")
    free_gb = usage.free / 1e9
    used_pct = (usage.used / usage.total * 100.0) if usage.total else 0.0
    status = STATUS_PASS
    if free_gb < float(thresholds["min_free_gb"]) or used_pct >= 95.0:
        status = STATUS_FAIL
    elif used_pct >= 85.0:
        status = STATUS_WARN
    inode_detail = "inodes=UNVERIFIED"
    try:
        st = os.statvfs(checkout_path)
        if st.f_files:
            inode_pct = (st.f_files - st.f_ffree) / st.f_files * 100.0
            inode_detail = f"inodes_used_pct={inode_pct:.1f}"
            if inode_pct >= 95.0:
                status = STATUS_FAIL
    except (OSError, AttributeError):
        pass
    return CheckResult(
        "disk_space_and_inodes",
        status,
        f"path={checkout_path} free_gb={free_gb:.1f} min_free_gb={thresholds['min_free_gb']} used_pct={used_pct:.1f} {inode_detail}",
    )


def _venv_python(checkout_path: Path) -> Path | None:
    for rel in ("venv/bin/python", ".venv/bin/python"):
        candidate = checkout_path / rel
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _python_and_virtualenv(checkout_path: Path) -> CheckResult:
    python_path = _venv_python(checkout_path)
    if python_path is None:
        return CheckResult("python_and_virtualenv", STATUS_WARN, f"venv python not found under {checkout_path}")
    try:
        result = _run([str(python_path), "-c", "import sys; print(sys.version.split()[0])"], timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("python_and_virtualenv", STATUS_FAIL, f"venv python execution failed: {exc}")
    version = result.stdout.strip()
    if result.returncode != 0 or not version:
        return CheckResult("python_and_virtualenv", STATUS_FAIL, "venv python did not execute")
    return CheckResult("python_and_virtualenv", STATUS_PASS, f"python={python_path} version={version}")


def _capability_module_imports(checkout_path: Path, capability: str) -> CheckResult:
    python_path = _venv_python(checkout_path)
    modules = CAPABILITY_MODULES.get(capability)
    if python_path is None:
        return CheckResult("capability_module_imports", STATUS_WARN, "venv python unavailable")
    if not modules:
        return CheckResult("capability_module_imports", STATUS_FAIL, f"unknown capability={capability}")
    import_lines = "; ".join(f"__import__({module!r})" for module in modules)
    try:
        result = _run([str(python_path), "-c", import_lines], cwd=checkout_path, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("capability_module_imports", STATUS_FAIL, f"import subprocess failed: {exc}")
    if result.returncode != 0:
        stderr = result.stderr.strip().splitlines()[-1:] or ["module import failed"]
        return CheckResult("capability_module_imports", STATUS_FAIL, stderr[0])
    return CheckResult("capability_module_imports", STATUS_PASS, f"modules={','.join(modules)}")


def _flock() -> CheckResult:
    path = shutil.which("flock")
    if not path:
        return CheckResult("flock", STATUS_FAIL, "flock executable not found")
    return CheckResult("flock", STATUS_PASS, f"flock={path} lock_scope=HOST_LOCAL")


def _systemd_availability() -> CheckResult:
    binary = shutil.which("systemctl")
    if not binary:
        return CheckResult("systemd_availability", STATUS_FAIL, "systemctl not found")
    try:
        result = _run([binary, "is-system-running"], timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("systemd_availability", STATUS_WARN, f"systemctl probe failed: {exc}")
    if result.returncode == 0:
        return CheckResult("systemd_availability", STATUS_PASS, f"systemctl={binary} state={result.stdout.strip()}")
    detail = (result.stdout.strip() or result.stderr.strip() or "systemd state unavailable").splitlines()[0]
    return CheckResult("systemd_availability", STATUS_WARN, f"systemctl={binary} state={detail}")


def _classify_systemd_verify(
    returncode: int,
    stderr: str,
    stdout: str,
    rel_units: tuple[str, ...],
) -> CheckResult:
    """Scope systemd-analyze diagnostics to the supplied capability units.

    Only diagnostics that reference one of the supplied unit files/names are
    treated as blocking for this capability. Unrelated global unit diagnostics
    (for example a host `xfs_scrub_all` warning) are retained deterministically
    as informational metadata and never raise a capability warning.
    """
    basenames = {Path(rel).name for rel in rel_units}
    raw = (stderr or "").strip() or (stdout or "").strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    relevant: list[str] = []
    unrelated: list[str] = []
    for line in lines:
        (relevant if any(base in line for base in basenames) else unrelated).append(line)
    info = f"unrelated_diagnostics={len(unrelated)}"
    if returncode != 0:
        if relevant:
            return CheckResult(
                "systemd_unit_validation", STATUS_FAIL, f"{relevant[0]} ({info})"
            )
        # Nonzero exit attributable only to unrelated units; the supplied
        # capability units produced no diagnostic of their own.
        return CheckResult(
            "systemd_unit_validation",
            STATUS_PASS,
            f"verified={','.join(rel_units)} rc={returncode} {info}",
        )
    if relevant:
        return CheckResult(
            "systemd_unit_validation", STATUS_WARN, f"{relevant[0]} ({info})"
        )
    return CheckResult(
        "systemd_unit_validation",
        STATUS_PASS,
        f"verified={','.join(rel_units)} {info}",
    )


def _systemd_unit_validation(checkout_path: Path, capability: str) -> CheckResult:
    binary = shutil.which("systemd-analyze")
    if not binary:
        return CheckResult("systemd_unit_validation", STATUS_UNVERIFIED, "systemd-analyze not found")
    rel_units = CAPABILITY_UNITS.get(capability)
    if not rel_units:
        return CheckResult("systemd_unit_validation", STATUS_FAIL, f"unknown capability={capability}")
    unit_paths = [str(checkout_path / rel) for rel in rel_units]
    missing = [path for path in unit_paths if not Path(path).exists()]
    if missing:
        return CheckResult("systemd_unit_validation", STATUS_FAIL, f"missing units={missing}")
    try:
        result = _run([binary, "verify", *unit_paths], timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("systemd_unit_validation", STATUS_WARN, f"systemd-analyze verify failed: {exc}")
    return _classify_systemd_verify(result.returncode, result.stderr, result.stdout, tuple(rel_units))


def _local_checks(
    *,
    capability: str,
    expected_host: str,
    expected_commit: str,
    checkout_path: Path,
) -> dict[str, CheckResult]:
    return {
        "capability_identity": _capability_identity(capability),
        "host_identity": _host_identity(expected_host),
        "checkout_commit": _checkout_commit(checkout_path, expected_commit),
        "os_and_architecture": _os_and_architecture(),
        "cpu_and_load": _cpu_and_load(capability),
        "ram_and_swap": _ram_and_swap(capability),
        "disk_space_and_inodes": _disk_space_and_inodes(checkout_path, capability),
        "python_and_virtualenv": _python_and_virtualenv(checkout_path),
        "capability_module_imports": _capability_module_imports(checkout_path, capability),
        "flock": _flock(),
        "systemd_availability": _systemd_availability(),
        "systemd_unit_validation": _systemd_unit_validation(checkout_path, capability),
    }


def run_preflight(
    *,
    capability: str,
    expected_host: str,
    expected_commit: str,
    checkout_path: Path,
    external_evidence_checks: dict[str, dict] | None = None,
) -> list[CheckResult]:
    """Assemble the full stage-aware check list.

    Local checks are always measured here and are authoritative. Preflight
    external checks stay UNVERIFIED unless a matching, permitted entry is present
    in ``external_evidence_checks`` (already validated by the evidence
    validator). Acceptance/cutover checks stay deferred and non-blocking.
    """
    measured = _local_checks(
        capability=capability,
        expected_host=expected_host,
        expected_commit=expected_commit,
        checkout_path=checkout_path,
    )
    evidence = external_evidence_checks or {}
    results: list[CheckResult] = []
    for name in CHECK_ORDER:
        if name in PREFLIGHT_LOCAL_CHECKS:
            results.append(measured[name])
        elif name in PREFLIGHT_EXTERNAL_CHECKS:
            required = _external_required(capability, name)
            merged = evidence.get(name)
            if merged is not None:
                detail = merged["detail"]
                results.append(
                    CheckResult(
                        name,
                        merged["status"],
                        f"{detail}; evidence_source={merged['evidence_source']}; observed_at_utc={merged['observed_at_utc']}",
                        required=required,
                        stage=STAGE_PREFLIGHT_EXTERNAL,
                        evidence_source=merged["evidence_source"],
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name,
                        STATUS_UNVERIFIED,
                        _external_placeholder_detail(capability, name, required),
                        required=required,
                        stage=STAGE_PREFLIGHT_EXTERNAL,
                    )
                )
        else:
            stage, reason = DEFERRED_CHECK_DESIGN[name]
            results.append(
                CheckResult(
                    name,
                    STATUS_UNVERIFIED,
                    reason,
                    required=False,
                    stage=stage,
                    required_stage=stage,
                )
            )
    return results


def _print_safety_markers() -> None:
    print(
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "host_mutations=0 database_writes=0 writer_invocations=0 "
        "systemctl_mutations=0 decision_gate=none execution_planner=none executor=none"
    )


def _render_table(results: list[CheckResult]) -> str:
    width = max(len(r.name) for r in results)
    stage_width = max(len(r.stage) for r in results)
    lines = [
        f"{'CHECK'.ljust(width)}  {'STAGE'.ljust(stage_width)}  STATUS      REQUIRED  DETAIL"
    ]
    for r in results:
        lines.append(
            f"{r.name.ljust(width)}  {r.stage.ljust(stage_width)}  "
            f"{r.status.ljust(10)}  {str(r.required).lower().ljust(8)}  {r.detail}"
        )
    return "\n".join(lines)


def _counts(results: list[CheckResult]) -> dict[str, int]:
    counts = {STATUS_PASS: 0, STATUS_WARN: 0, STATUS_FAIL: 0, STATUS_UNVERIFIED: 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _strict_exit_status(results: list[CheckResult]) -> int:
    for result in results:
        if result.required and result.status == STATUS_FAIL:
            return 3
    for result in results:
        if result.required and result.status == STATUS_WARN:
            return 4
    for result in results:
        if result.required and result.status == STATUS_UNVERIFIED:
            return 5
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only, stage-aware host preflight for writer-capability host selection."
    )
    parser.add_argument("--capability", required=True, choices=sorted(CAPABILITY_MODULES))
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--checkout-path", type=Path, default=None)
    parser.add_argument("--path", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--external-evidence-file",
        type=Path,
        default=None,
        help=(
            "Optional path to a separately produced external-evidence manifest. "
            "Only matching, permitted preflight-external checks are merged; local "
            "checks stay authoritative and no command is ever executed from it."
        ),
    )
    parser.add_argument("--output", choices=("table", "json"), default="table")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero for any required FAIL, WARN, or UNVERIFIED result.",
    )
    args = parser.parse_args()

    checkout_path = (args.checkout_path or args.path or Path.cwd()).resolve()
    ts = datetime.now(UTC).replace(microsecond=0).isoformat()

    external_checks: dict[str, dict] | None = None
    evidence_source_path: str | None = None
    if args.external_evidence_file is not None:
        # Imported lazily so importing the validator (which imports this module's
        # stage constants) never forms a load-time cycle.
        from src.operations.validate_host_preflight_external_evidence_v1 import (
            load_and_validate_external_evidence,
        )

        evidence_source_path = str(args.external_evidence_file)
        validation = load_and_validate_external_evidence(
            args.external_evidence_file,
            capability=args.capability,
            expected_host=args.expected_host,
            expected_commit=args.expected_commit,
        )
        if not validation.ok:
            print(
                f"FAILED runner={RUNNER_NAME} reason=EXTERNAL_EVIDENCE_INVALID "
                f"file={evidence_source_path} error_count={len(validation.errors)} ts={ts}"
            )
            for error in validation.errors:
                print(f"EVIDENCE_ERROR {error}")
            return 2
        external_checks = validation.checks

    results = run_preflight(
        capability=args.capability,
        expected_host=args.expected_host,
        expected_commit=args.expected_commit,
        checkout_path=checkout_path,
        external_evidence_checks=external_checks,
    )
    counts = _counts(results)

    if args.output == "json":
        payload = {
            "runner": RUNNER_NAME,
            "version": RUNNER_VERSION,
            "ts_utc": ts,
            "capability": args.capability,
            "expected_host": args.expected_host,
            "expected_commit": args.expected_commit,
            "checkout_path": str(checkout_path),
            "external_evidence_file": evidence_source_path,
            "strict_requires_stages": [STAGE_PREFLIGHT_LOCAL, STAGE_PREFLIGHT_EXTERNAL],
            "deferred_stages": [STAGE_ACCEPTANCE, STAGE_CUTOVER],
            "safety_markers": {
                "host_mutations": 0,
                "database_writes": 0,
                "writer_invocations": 0,
                "systemctl_mutations": 0,
                "broker_private_calls": 0,
                "broker_writes": 0,
                "exchange_calls": 0,
            },
            "counts": counts,
            "checks": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"STARTED runner={RUNNER_NAME} mode=read_only capability={args.capability} "
            f"checkout_path={checkout_path} external_evidence_file={evidence_source_path} ts={ts}"
        )
        _print_safety_markers()
        print(_render_table(results))
        print(
            f"FINISHED runner={RUNNER_NAME} pass={counts[STATUS_PASS]} "
            f"warn={counts[STATUS_WARN]} fail={counts[STATUS_FAIL]} "
            f"unverified={counts[STATUS_UNVERIFIED]} ts={ts}"
        )

    if args.strict:
        return _strict_exit_status(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
