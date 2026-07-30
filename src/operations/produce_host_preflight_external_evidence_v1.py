"""
Produce canonical, read-only host-preflight external evidence.

This producer is intentionally closed to capability profiles whose external
requirements have been reviewed here. It emits only
host_preflight_external_evidence_v1 data, derives every status from a probe or
the canonical capability profile, and never accepts caller-supplied statuses.

Safety boundary:
- one read-only MariaDB transaction (SET/START READ ONLY, SELECT 1, ROLLBACK)
- DNS and bounded outbound TCP connectivity probes
- read-only timedatectl, journalctl, and systemd-analyze inspection
- no writer invocation, database write, systemctl mutation, broker call,
  authorization, acceptance, deployment, decision gate, planner, or executor
- configuration values and subprocess output are never rendered or persisted

The explicitly requested evidence output file is the only filesystem artifact.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import socket
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from dotenv import dotenv_values

from src.operations.run_host_preflight_v1 import PREFLIGHT_EXTERNAL_CHECKS
from src.operations.validate_host_preflight_external_evidence_v1 import (
    SCHEMA_VERSION,
    validate_external_evidence,
)


PRODUCER_NAME = "host_preflight_external_evidence_producer_v1"
EVIDENCE_SOURCE = "src.operations.produce_host_preflight_external_evidence_v1"

REQUIRED_CHECKS = (
    "mariadb_connectivity",
    "dns",
    "ntp_time_sync",
    "journald_logrotation",
    "runtime_configuration",
    "firewall_outbound_connectivity",
)
NOT_REQUIRED_CHECKS = (
    "exchange_api_connectivity",
    "private_exchange_credentials",
)
CAPABILITY_PROFILES = {
    "sector_rotation_snapshot": {
        "required": REQUIRED_CHECKS,
        "not_required": NOT_REQUIRED_CHECKS,
        "outbound_target": ("api.coingecko.com", 443),
    },
}

_DB_ENV_ALIASES = {
    "host": ("DB_HOST", "MYSQL_HOST"),
    "port": ("DB_PORT", "MYSQL_PORT"),
    "user": ("DB_USER", "MYSQL_USER"),
    "password": ("DB_PASSWORD", "MYSQL_PASSWORD"),
    "database": ("DB_NAME", "MYSQL_DATABASE"),
}
_READ_ONLY_SQL = (
    "SET SESSION TRANSACTION READ ONLY",
    "START TRANSACTION READ ONLY",
    "SELECT 1",
)


@dataclass(frozen=True)
class ProbeResult:
    status: str
    reason_code: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


@dataclass(frozen=True)
class DatabaseProbeOutcome:
    result: ProbeResult
    connections: int
    read_queries: int


class Cursor(Protocol):
    def execute(self, statement: str) -> Any: ...

    def fetchone(self) -> Any: ...

    def close(self) -> Any: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def rollback(self) -> Any: ...

    def close(self) -> Any: ...


class ProbeAdapter(Protocol):
    def resolve(self, host: str) -> None: ...

    def connect_tcp(self, host: str, port: int) -> None: ...

    def run_command(self, args: list[str]) -> CommandResult: ...

    def connect_database(self, config: Mapping[str, str | int]) -> Connection: ...


class SystemProbeAdapter:
    def resolve(self, host: str) -> None:
        socket.getaddrinfo(host, None)

    def connect_tcp(self, host: str, port: int) -> None:
        with socket.create_connection((host, port), timeout=5):
            pass

    def run_command(self, args: list[str]) -> CommandResult:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout)

    def connect_database(self, config: Mapping[str, str | int]) -> Connection:
        import pymysql

        return pymysql.connect(
            host=str(config["host"]),
            port=int(config["port"]),
            user=str(config["user"]),
            password=str(config["password"]),
            database=str(config["database"]),
            autocommit=False,
            connect_timeout=10,
            read_timeout=10,
            write_timeout=10,
        )


def _result(passed: bool, pass_code: str, fail_code: str) -> ProbeResult:
    return ProbeResult("PASS" if passed else "FAIL", pass_code if passed else fail_code)


def _load_runtime_configuration(path: Path) -> tuple[ProbeResult, dict[str, str | int] | None]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return ProbeResult("FAIL", "RUNTIME_CONFIG_UNREADABLE"), None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            return ProbeResult("FAIL", "RUNTIME_CONFIG_NOT_REGULAR_FILE"), None
        if info.st_uid != os.geteuid():
            return ProbeResult("FAIL", "RUNTIME_CONFIG_OWNER_MISMATCH"), None
        if stat.S_IMODE(info.st_mode) & 0o077:
            return ProbeResult("FAIL", "RUNTIME_CONFIG_PERMISSIONS_UNSAFE"), None

        # python-dotenv may report malformed source lines. Suppress and discard
        # all parser output so no configuration content reaches logs.
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            descriptor = -1
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                raw = dotenv_values(stream=handle, interpolate=False)
    except Exception:
        return ProbeResult("FAIL", "RUNTIME_CONFIG_PARSE_FAILED"), None
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    config: dict[str, str | int] = {}
    for field, aliases in _DB_ENV_ALIASES.items():
        value = next((raw.get(name) for name in aliases if raw.get(name)), None)
        if not isinstance(value, str) or not value:
            return ProbeResult("FAIL", "RUNTIME_CONFIG_REQUIRED_VALUE_MISSING"), None
        config[field] = value
    try:
        port = int(str(config["port"]))
    except (TypeError, ValueError):
        return ProbeResult("FAIL", "RUNTIME_CONFIG_PORT_INVALID"), None
    if not 1 <= port <= 65535:
        return ProbeResult("FAIL", "RUNTIME_CONFIG_PORT_INVALID"), None
    config["port"] = port
    return ProbeResult("PASS", "RUNTIME_CONFIG_SAFE_AND_COMPLETE"), config


def _probe_dns(adapter: ProbeAdapter, config: Mapping[str, str | int] | None) -> ProbeResult:
    if config is None:
        return ProbeResult("FAIL", "DNS_RUNTIME_CONFIG_UNAVAILABLE")
    try:
        adapter.resolve(str(config["host"]))
    except Exception:
        return ProbeResult("FAIL", "DNS_RESOLUTION_FAILED")
    return ProbeResult("PASS", "DNS_RESOLUTION_OK")


def _probe_firewall(
    adapter: ProbeAdapter, outbound_host: str, outbound_port: int
) -> ProbeResult:
    try:
        adapter.connect_tcp(outbound_host, outbound_port)
    except Exception:
        return ProbeResult("FAIL", "OUTBOUND_TCP_CONNECTIVITY_FAILED")
    return ProbeResult("PASS", "OUTBOUND_TCP_CONNECTIVITY_OK")


def _probe_ntp(adapter: ProbeAdapter) -> ProbeResult:
    try:
        result = adapter.run_command(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"]
        )
    except Exception:
        return ProbeResult("FAIL", "NTP_PROBE_UNAVAILABLE")
    return _result(
        result.returncode == 0 and result.stdout.strip().lower() == "yes",
        "NTP_SYNCHRONIZED",
        "NTP_NOT_PROVEN_SYNCHRONIZED",
    )


_SYSTEMD_ACTIVE_STATES = frozenset(
    {"active", "inactive", "failed", "activating", "deactivating", "reloading"}
)
_SYSTEMD_ENABLED_STATES = frozenset(
    {
        "enabled",
        "enabled-runtime",
        "linked",
        "linked-runtime",
        "alias",
        "masked",
        "masked-runtime",
        "static",
        "indirect",
        "generated",
        "transient",
        "disabled",
    }
)


def _single_state(output: str, allowed: frozenset[str]) -> str | None:
    lines = [line.strip().lower() for line in output.splitlines()]
    if len(lines) != 1 or not lines[0] or lines[0] not in allowed:
        return None
    return lines[0]


def _probe_journald(adapter: ProbeAdapter) -> ProbeResult:
    try:
        journal = adapter.run_command(["journalctl", "--disk-usage", "--no-pager"])
    except Exception:
        return ProbeResult("FAIL", "JOURNALD_USAGE_PROBE_UNAVAILABLE")
    if journal.returncode != 0 or not journal.stdout.strip():
        return ProbeResult("FAIL", "JOURNALD_USAGE_UNREADABLE")

    try:
        active = adapter.run_command(["systemctl", "is-active", "logrotate.timer"])
        enabled = adapter.run_command(["systemctl", "is-enabled", "logrotate.timer"])
    except Exception:
        return ProbeResult("FAIL", "LOGROTATE_TIMER_STATE_PROBE_UNAVAILABLE")

    active_state = _single_state(active.stdout, _SYSTEMD_ACTIVE_STATES)
    enabled_state = _single_state(enabled.stdout, _SYSTEMD_ENABLED_STATES)
    if active_state is None or enabled_state is None:
        return ProbeResult("FAIL", "LOGROTATE_TIMER_STATE_MALFORMED_OR_AMBIGUOUS")
    if active_state == "active" and active.returncode != 0:
        return ProbeResult("FAIL", "LOGROTATE_TIMER_STATE_CONTRADICTORY")
    if active_state != "active":
        return ProbeResult("FAIL", "LOGROTATE_TIMER_NOT_ACTIVE")
    if enabled_state == "enabled" and enabled.returncode != 0:
        return ProbeResult("FAIL", "LOGROTATE_TIMER_STATE_CONTRADICTORY")
    if enabled_state != "enabled":
        return ProbeResult("FAIL", "LOGROTATE_TIMER_NOT_ENABLED")
    return ProbeResult(
        "PASS", "JOURNALD_READABLE_LOGROTATE_TIMER_ACTIVE_ENABLED"
    )


def _probe_mariadb(
    adapter: ProbeAdapter, config: Mapping[str, str | int] | None
) -> DatabaseProbeOutcome:
    if config is None:
        return DatabaseProbeOutcome(
            ProbeResult("FAIL", "MARIADB_RUNTIME_CONFIG_UNAVAILABLE"), 0, 0
        )
    connection: Connection | None = None
    cursor: Cursor | None = None
    connections = 0
    read_queries = 0
    succeeded = False
    try:
        connection = adapter.connect_database(config)
        connections = 1
        cursor = connection.cursor()
        for statement in _READ_ONLY_SQL:
            cursor.execute(statement)
            if statement == "SELECT 1":
                read_queries = 1
        if cursor.fetchone() is None:
            raise RuntimeError("read-only probe returned no row")
        connection.rollback()
        succeeded = True
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    result = ProbeResult(
        "PASS" if succeeded else "FAIL",
        "MARIADB_READ_ONLY_QUERY_OK"
        if succeeded
        else "MARIADB_READ_ONLY_PROBE_FAILED",
    )
    return DatabaseProbeOutcome(result, connections, read_queries)


def collect_evidence(
    *,
    capability: str,
    hostname: str,
    checkout_commit: str,
    runtime_config_file: Path,
    observed_at: datetime,
    adapter: ProbeAdapter,
) -> dict[str, Any]:
    if capability not in CAPABILITY_PROFILES:
        raise ValueError("CAPABILITY_UNSUPPORTED")
    profile = CAPABILITY_PROFILES[capability]
    config_result, config = _load_runtime_configuration(runtime_config_file)
    database_outcome = _probe_mariadb(adapter, config)
    outbound_host, outbound_port = profile["outbound_target"]
    results = {
        "mariadb_connectivity": database_outcome.result,
        "dns": _probe_dns(adapter, config),
        "ntp_time_sync": _probe_ntp(adapter),
        "journald_logrotation": _probe_journald(adapter),
        "runtime_configuration": config_result,
        "firewall_outbound_connectivity": _probe_firewall(
            adapter, outbound_host, outbound_port
        ),
    }
    for name in profile["not_required"]:
        results[name] = ProbeResult("PASS", "NOT_REQUIRED_BY_CAPABILITY")
    if set(results) != set(PREFLIGHT_EXTERNAL_CHECKS):
        raise RuntimeError("EXTERNAL_CHECK_SET_MISMATCH")

    timestamp = observed_at.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    checks = {
        name: {
            "status": results[name].status,
            "detail": f"reason_code={results[name].reason_code}",
            "evidence_source": f"{EVIDENCE_SOURCE}#{name}",
            "observed_at_utc": timestamp,
        }
        for name in PREFLIGHT_EXTERNAL_CHECKS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "capability": capability,
        "hostname": hostname,
        "checkout_commit": checkout_commit,
        "observed_at_utc": timestamp,
        "evidence_producer": PRODUCER_NAME,
        "checks": checks,
        "safety_markers": {
            "host_mutations": 0,
            "database_writes": 0,
            "writer_invocations": 0,
            "systemctl_mutations": 0,
            "order_submission": 0,
            "broker_writes": 0,
            "authorization_created": False,
            "deployment_performed": False,
            "database_connections": database_outcome.connections,
            "database_read_queries": database_outcome.read_queries,
            "dns_lookups": 1 + int(config is not None),
            "exchange_public_calls": 0,
        },
    }


def _actual_checkout_commit(checkout_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout_path), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def _write_evidence(path: Path, payload: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(
    *,
    adapter_factory: Callable[[], ProbeAdapter] = SystemProbeAdapter,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    parser = argparse.ArgumentParser(
        description="Produce canonical read-only host-preflight external evidence."
    )
    parser.add_argument("--capability", required=True, choices=sorted(CAPABILITY_PROFILES))
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--checkout-path", type=Path, required=True)
    parser.add_argument("--runtime-config-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    args = parser.parse_args()

    actual_host = platform.node().strip()
    if not actual_host or actual_host != args.expected_host:
        print("FAILED reason_code=HOST_IDENTITY_MISMATCH")
        return 2
    actual_commit = _actual_checkout_commit(args.checkout_path.resolve())
    if actual_commit != args.expected_commit:
        print("FAILED reason_code=CHECKOUT_COMMIT_MISMATCH")
        return 2
    if args.output_file.exists():
        print("FAILED reason_code=OUTPUT_FILE_ALREADY_EXISTS")
        return 2

    observed_at = now()
    payload = collect_evidence(
        capability=args.capability,
        hostname=actual_host,
        checkout_commit=actual_commit,
        runtime_config_file=args.runtime_config_file,
        observed_at=observed_at,
        adapter=adapter_factory(),
    )
    validation = validate_external_evidence(
        payload,
        capability=args.capability,
        expected_host=actual_host,
        expected_commit=actual_commit,
        reference_time=observed_at,
    )
    if not validation.ok:
        print("FAILED reason_code=PRODUCER_EVIDENCE_INVALID")
        return 2
    try:
        _write_evidence(args.output_file, payload)
    except OSError:
        print("FAILED reason_code=OUTPUT_FILE_WRITE_FAILED")
        return 2
    required = set(CAPABILITY_PROFILES[args.capability]["required"])
    passed = all(payload["checks"][name]["status"] == "PASS" for name in required)
    print(
        f"FINISHED producer={PRODUCER_NAME} status={'PASS' if passed else 'FAIL'} "
        f"required_checks={len(required)} database_writes=0 writer_invocations=0 "
        "host_mutations=0 systemctl_mutations=0 broker_private_calls=0 "
        "broker_writes=0 order_submission=0"
    )
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
