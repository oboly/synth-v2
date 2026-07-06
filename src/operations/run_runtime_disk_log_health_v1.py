"""
runtime_disk_log_health_v1

Deterministic, read-only disk/log health check for the Odroid runtime host.

Purpose (P0-A, 2026-07-05 incident follow-up): the root cause of the
2026-07-05 Short Swing staleness incident was the Odroid root filesystem
reaching 100% full, which silently broke public price refresh and
linked-profile dashboard rendering. This runner gives an explicit,
deterministic, fail-visible health signal *before* that point is reached,
so a filling filesystem is detected rather than discovered only after
dashboard freshness has already broken.

Safety boundary:
- read-only filesystem inspection only (os.statvfs via shutil.disk_usage,
  optional os.path.getsize for named log files)
- no DB access
- no network calls
- no broker calls of any kind
- no writes, deletes, or log rotation performed by this runner

broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

RUNNER_NAME = "runtime_disk_log_health_v1"
RUNNER_VERSION = "0.1"

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_CRITICAL = "CRITICAL"

# Pre-declared defaults, not tuned to any single host's disk size. Review
# against the actual host's filesystem size before relying on these in
# production (the Odroid root filesystem at incident time was a 15 GB eMMC
# device, so percentage-based thresholds are used here rather than assuming
# a specific absolute byte budget).
DEFAULT_DISK_WARN_PCT = 85.0
DEFAULT_DISK_CRITICAL_PCT = 95.0

# Example absolute log-file thresholds informed by the 2026-07-05 incident
# record (docs/incidents/2026-07-05_odroid_disk_exhaustion_and_stale_short_swing_data.md),
# where /var/log/syslog and /var/log/syslog.1 were each found at ~1.8 GB.
# These are starting defaults for the optional per-file check, not a
# host-verified retention policy — see docs/ops/synth_runtime_runners_v1.md
# for the requirement to inspect actual rsyslog/logrotate/journald config
# before changing retention.
DEFAULT_LOG_WARN_BYTES = 500 * 1024 * 1024  # 500 MB
DEFAULT_LOG_CRITICAL_BYTES = 1500 * 1024 * 1024  # 1.5 GB


@dataclass(frozen=True)
class DiskHealthResult:
    path: str
    exists: bool
    total_bytes: int
    used_bytes: int
    root_free_bytes: int
    writer_available_bytes: int
    reserved_unavailable_bytes: int
    writer_available_pct: float
    writer_used_pct: float
    warn_pct: float
    critical_pct: float
    status: str
    checked_ts_utc: str


@dataclass(frozen=True)
class LogFileHealthResult:
    path: str
    exists: bool
    size_bytes: int
    warn_bytes: int
    critical_bytes: int
    status: str
    checked_ts_utc: str


def _status_for_ratio(value: float, warn: float, critical: float) -> str:
    if value >= critical:
        return STATUS_CRITICAL
    if value >= warn:
        return STATUS_WARN
    return STATUS_OK


def _worst_status(statuses: list[str]) -> str:
    if STATUS_CRITICAL in statuses:
        return STATUS_CRITICAL
    if STATUS_WARN in statuses:
        return STATUS_WARN
    return STATUS_OK


def check_disk_health(
    path: str,
    *,
    warn_pct: float = DEFAULT_DISK_WARN_PCT,
    critical_pct: float = DEFAULT_DISK_CRITICAL_PCT,
) -> DiskHealthResult:
    """Deterministic disk-usage check for the filesystem backing `path`.

    Raises ValueError for invalid thresholds and OSError/FileNotFoundError
    if `path` cannot be inspected (caller decides how to surface that —
    this function does not swallow filesystem errors, per the "make health
    status explicit and fail-visible" requirement).
    """
    if not (0.0 < warn_pct < critical_pct <= 100.0):
        raise ValueError(
            f"Invalid disk thresholds: warn_pct={warn_pct} critical_pct={critical_pct} "
            "(require 0 < warn_pct < critical_pct <= 100)"
        )

    exists = os.path.exists(path)
    stat = os.statvfs(path)
    block_size = stat.f_frsize or stat.f_bsize
    total_bytes = stat.f_blocks * block_size
    root_free_bytes = stat.f_bfree * block_size
    writer_available_bytes = stat.f_bavail * block_size
    reserved_unavailable_bytes = max(root_free_bytes - writer_available_bytes, 0)
    used_bytes = max(total_bytes - root_free_bytes, 0)
    writer_available_pct = (
        writer_available_bytes / total_bytes * 100.0 if total_bytes > 0 else 0.0
    )
    writer_used_pct = 100.0 - writer_available_pct if total_bytes > 0 else 0.0
    status = _status_for_ratio(writer_used_pct, warn_pct, critical_pct)

    return DiskHealthResult(
        path=path,
        exists=exists,
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        root_free_bytes=root_free_bytes,
        writer_available_bytes=writer_available_bytes,
        reserved_unavailable_bytes=reserved_unavailable_bytes,
        writer_available_pct=round(writer_available_pct, 2),
        writer_used_pct=round(writer_used_pct, 2),
        warn_pct=warn_pct,
        critical_pct=critical_pct,
        status=status,
        checked_ts_utc=datetime.now(UTC).isoformat(),
    )


def check_log_file_health(
    path: str,
    *,
    warn_bytes: int = DEFAULT_LOG_WARN_BYTES,
    critical_bytes: int = DEFAULT_LOG_CRITICAL_BYTES,
) -> LogFileHealthResult:
    """Deterministic size check for one named log file.

    A missing file is reported as status OK with size_bytes=0 and
    exists=False — there is nothing to warn about yet, but callers can still
    see the file was not found (e.g. a typo'd path or a not-yet-rotated
    name) rather than that being silently indistinguishable from "small".
    """
    if not (0 <= warn_bytes < critical_bytes):
        raise ValueError(
            f"Invalid log thresholds: warn_bytes={warn_bytes} critical_bytes={critical_bytes} "
            "(require 0 <= warn_bytes < critical_bytes)"
        )

    exists = os.path.isfile(path)
    size_bytes = os.path.getsize(path) if exists else 0
    status = STATUS_OK if not exists else _status_for_ratio(size_bytes, warn_bytes, critical_bytes)

    return LogFileHealthResult(
        path=path,
        exists=exists,
        size_bytes=size_bytes,
        warn_bytes=warn_bytes,
        critical_bytes=critical_bytes,
        status=status,
        checked_ts_utc=datetime.now(UTC).isoformat(),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic read-only disk/log health check. Does not call any "
            "broker, does not write the database, does not rotate or delete "
            "any log. broker_private_calls=0 broker_writes=0 order_submission=0 "
            "decision_gate=none execution_planner=none executor=none"
        )
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Filesystem path whose backing filesystem is checked for disk usage (default: current directory).",
    )
    parser.add_argument("--warn-pct", type=float, default=DEFAULT_DISK_WARN_PCT)
    parser.add_argument("--critical-pct", type=float, default=DEFAULT_DISK_CRITICAL_PCT)
    parser.add_argument(
        "--log-path",
        action="append",
        default=None,
        help="Optional log file path to check by size (repeatable). Not checked if omitted.",
    )
    parser.add_argument("--log-warn-bytes", type=int, default=DEFAULT_LOG_WARN_BYTES)
    parser.add_argument("--log-critical-bytes", type=int, default=DEFAULT_LOG_CRITICAL_BYTES)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        f"STARTED {RUNNER_NAME} version={RUNNER_VERSION} path={args.path} "
        f"log_paths={','.join(args.log_path) if args.log_path else 'NONE'} "
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "decision_gate=none execution_planner=none executor=none"
    )

    try:
        disk_result = check_disk_health(
            args.path, warn_pct=args.warn_pct, critical_pct=args.critical_pct
        )
    except (OSError, ValueError) as exc:
        print(f"FAILED {RUNNER_NAME} error={exc.__class__.__name__}:{exc}")
        return 1

    log_results: list[LogFileHealthResult] = []
    for log_path in args.log_path or []:
        try:
            log_results.append(
                check_log_file_health(
                    log_path,
                    warn_bytes=args.log_warn_bytes,
                    critical_bytes=args.log_critical_bytes,
                )
            )
        except (OSError, ValueError) as exc:
            print(f"FAILED {RUNNER_NAME} log_path={log_path} error={exc.__class__.__name__}:{exc}")
            return 1

    overall_status = _worst_status([disk_result.status] + [r.status for r in log_results])

    if args.output == "json":
        payload = {
            "disk": asdict(disk_result),
            "logs": [asdict(r) for r in log_results],
            "overall_status": overall_status,
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"DISK path={disk_result.path} status={disk_result.status} "
            f"writer_used_pct={disk_result.writer_used_pct} "
            f"writer_available_pct={disk_result.writer_available_pct} "
            f"writer_available_bytes={disk_result.writer_available_bytes} "
            f"root_free_bytes={disk_result.root_free_bytes} "
            f"reserved_unavailable_bytes={disk_result.reserved_unavailable_bytes} "
            f"total_bytes={disk_result.total_bytes} warn_pct={disk_result.warn_pct} "
            f"critical_pct={disk_result.critical_pct}"
        )
        for r in log_results:
            print(
                f"LOG path={r.path} status={r.status} exists={r.exists} "
                f"size_bytes={r.size_bytes} warn_bytes={r.warn_bytes} "
                f"critical_bytes={r.critical_bytes}"
            )

    print(f"FINISHED {RUNNER_NAME} overall_status={overall_status}")
    return 1 if overall_status == STATUS_CRITICAL else 0


if __name__ == "__main__":
    raise SystemExit(main())
