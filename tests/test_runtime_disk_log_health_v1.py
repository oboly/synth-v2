"""
Tests for src/operations/run_runtime_disk_log_health_v1.py (P0-A).

Verifies:
- deterministic OK/WARN/CRITICAL disk-usage classification at threshold boundaries
- deterministic OK/WARN/CRITICAL log-file-size classification, including missing files
- invalid threshold configuration is rejected (fail loud, not silently accepted)
- CLI exits 0 for OK/WARN and 1 for CRITICAL (fail-visible, not silently fresh)
- JSON output round-trips the same status
- no broker/decision/execution imports or calls

broker_private_calls=0 broker_writes=0 order_submission=0
"""
from __future__ import annotations

import ast
import io
import json
import os
from collections import namedtuple
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import src.operations.run_runtime_disk_log_health_v1 as health


_StatVfsTuple = namedtuple(
    "_StatVfsTuple",
    [
        "f_bsize",
        "f_frsize",
        "f_blocks",
        "f_bfree",
        "f_bavail",
        "f_files",
        "f_ffree",
        "f_favail",
        "f_flag",
        "f_namemax",
    ],
)


def _fake_statvfs(*, total: int, root_free: int, writer_available: int) -> _StatVfsTuple:
    return _StatVfsTuple(
        f_bsize=1,
        f_frsize=1,
        f_blocks=total,
        f_bfree=root_free,
        f_bavail=writer_available,
        f_files=0,
        f_ffree=0,
        f_favail=0,
        f_flag=0,
        f_namemax=255,
    )


# ---------------------------------------------------------------------------
# check_disk_health — boundary classification
# ---------------------------------------------------------------------------


def test_disk_health_ok_below_warn_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=500, writer_available=500))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_OK
    assert result.writer_used_pct == 50.0


def test_disk_health_warn_at_exact_warn_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=150, writer_available=150))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_WARN


def test_disk_health_critical_at_exact_critical_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=50, writer_available=50))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_CRITICAL


def test_disk_health_critical_at_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for the 2026-07-05 incident: a 100%-full filesystem must
    classify as CRITICAL, not silently as fresh/OK."""
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=0, writer_available=0))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_CRITICAL
    assert result.writer_available_bytes == 0


def test_disk_health_uses_writer_available_capacity_before_non_root_enospc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        os,
        "statvfs",
        lambda _path: _fake_statvfs(total=1000, root_free=100, writer_available=40),
    )
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_CRITICAL
    assert result.root_free_bytes == 100
    assert result.writer_available_bytes == 40
    assert result.reserved_unavailable_bytes == 60


@pytest.mark.parametrize(
    "warn_pct,critical_pct",
    [(95.0, 85.0), (0.0, 50.0), (50.0, 101.0), (50.0, 50.0)],
)
def test_disk_health_rejects_invalid_thresholds(warn_pct: float, critical_pct: float) -> None:
    with pytest.raises(ValueError):
        health.check_disk_health(".", warn_pct=warn_pct, critical_pct=critical_pct)


# ---------------------------------------------------------------------------
# check_log_file_health — boundary classification
# ---------------------------------------------------------------------------


def test_log_file_health_missing_file_is_ok(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.log"
    result = health.check_log_file_health(str(missing), warn_bytes=100, critical_bytes=200)
    assert result.exists is False
    assert result.size_bytes == 0
    assert result.status == health.STATUS_OK


def test_log_file_health_ok_below_warn(tmp_path: Path) -> None:
    small = tmp_path / "small.log"
    small.write_bytes(b"x" * 50)
    result = health.check_log_file_health(str(small), warn_bytes=100, critical_bytes=200)
    assert result.status == health.STATUS_OK
    assert result.size_bytes == 50


def test_log_file_health_warn_at_threshold(tmp_path: Path) -> None:
    mid = tmp_path / "mid.log"
    mid.write_bytes(b"x" * 100)
    result = health.check_log_file_health(str(mid), warn_bytes=100, critical_bytes=200)
    assert result.status == health.STATUS_WARN


def test_log_file_health_critical_at_threshold(tmp_path: Path) -> None:
    big = tmp_path / "big.log"
    big.write_bytes(b"x" * 200)
    result = health.check_log_file_health(str(big), warn_bytes=100, critical_bytes=200)
    assert result.status == health.STATUS_CRITICAL


def test_log_file_health_rejects_invalid_thresholds(tmp_path: Path) -> None:
    f = tmp_path / "f.log"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        health.check_log_file_health(str(f), warn_bytes=200, critical_bytes=100)


# ---------------------------------------------------------------------------
# CLI — fail-visible exit codes and output modes
# ---------------------------------------------------------------------------


def test_cli_exits_zero_and_prints_ok_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=900, writer_available=900))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = health.main(["--path", "."])
    text = buf.getvalue()
    assert code == 0
    assert "STARTED runtime_disk_log_health_v1" in text
    assert "status=OK" in text
    assert "FINISHED runtime_disk_log_health_v1 overall_status=OK" in text


def test_cli_exits_one_on_critical_disk_and_does_not_claim_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-visible requirement: CRITICAL must produce a non-zero exit code,
    not a silent continuation as if fresh/healthy."""
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=10, writer_available=10))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = health.main(["--path", "."])
    text = buf.getvalue()
    assert code == 1
    assert "status=CRITICAL" in text
    assert "overall_status=CRITICAL" in text
    assert "status=OK" not in text


def test_cli_overall_status_is_worst_of_disk_and_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=900, writer_available=900))
    big_log = tmp_path / "syslog"
    big_log.write_bytes(b"x" * 300)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = health.main(
            [
                "--path",
                ".",
                "--log-path",
                str(big_log),
                "--log-warn-bytes",
                "100",
                "--log-critical-bytes",
                "200",
            ]
        )
    text = buf.getvalue()
    assert code == 1
    assert "DISK path=. status=OK" in text
    assert f"LOG path={big_log} status=CRITICAL" in text
    assert "overall_status=CRITICAL" in text


def test_cli_json_output_round_trips_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=900, writer_available=900))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = health.main(["--path", ".", "--output", "json"])
    text = buf.getvalue()
    assert code == 0
    json_line = next(line for line in text.splitlines() if line.startswith("{"))
    payload = json.loads(json_line)
    assert payload["overall_status"] == "OK"
    assert payload["disk"]["status"] == "OK"
    assert payload["disk"]["writer_available_bytes"] == 900
    assert payload["logs"] == []


def test_help_and_runtime_output_use_broker_private_calls_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    help_buf = io.StringIO()
    with pytest.raises(SystemExit):
        with redirect_stdout(help_buf):
            health.parse_args(["--help"])
    help_text = help_buf.getvalue()
    assert "broker_private_calls=0" in help_text
    assert "broker_calls=0" not in help_text

    monkeypatch.setattr(os, "statvfs", lambda _path: _fake_statvfs(total=1000, root_free=900, writer_available=900))
    run_buf = io.StringIO()
    with redirect_stdout(run_buf):
        code = health.main(["--path", "."])
    assert code == 0
    text = run_buf.getvalue()
    assert "broker_private_calls=0" in text


def test_cli_never_writes_or_broker_calls_module_has_no_forbidden_imports() -> None:
    source = Path("src/operations/run_runtime_disk_log_health_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "src.common.db",
        "src.account",
        "decision_gate",
        "execution_planner",
        "executor",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in forbidden_imports:
                assert name not in module, f"forbidden import found: {module}"
    lowered = source.lower()
    for forbidden in ("placeorder", "cancelorder", "create order", "requests.", "bitvavo"):
        assert forbidden not in lowered, f"forbidden token found: {forbidden}"
