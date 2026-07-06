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
import shutil
from collections import namedtuple
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import src.operations.run_runtime_disk_log_health_v1 as health


_UsageTuple = namedtuple("_UsageTuple", ["total", "used", "free"])


def _fake_usage(total: int, used_pct: float) -> _UsageTuple:
    used = int(total * used_pct / 100.0)
    return _UsageTuple(total=total, used=used, free=total - used)


# ---------------------------------------------------------------------------
# check_disk_health — boundary classification
# ---------------------------------------------------------------------------


def test_disk_health_ok_below_warn_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 50.0))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_OK
    assert result.used_pct == 50.0


def test_disk_health_warn_at_exact_warn_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 85.0))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_WARN


def test_disk_health_critical_at_exact_critical_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 95.0))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_CRITICAL


def test_disk_health_critical_at_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for the 2026-07-05 incident: a 100%-full filesystem must
    classify as CRITICAL, not silently as fresh/OK."""
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 100.0))
    result = health.check_disk_health(".", warn_pct=85.0, critical_pct=95.0)
    assert result.status == health.STATUS_CRITICAL
    assert result.free_bytes == 0


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
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 10.0))
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
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 99.0))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = health.main(["--path", "."])
    text = buf.getvalue()
    assert code == 1
    assert "status=CRITICAL" in text
    assert "overall_status=CRITICAL" in text
    assert "status=OK" not in text


def test_cli_overall_status_is_worst_of_disk_and_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 10.0))
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
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _fake_usage(1000, 10.0))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = health.main(["--path", ".", "--output", "json"])
    text = buf.getvalue()
    assert code == 0
    json_line = next(line for line in text.splitlines() if line.startswith("{"))
    payload = json.loads(json_line)
    assert payload["overall_status"] == "OK"
    assert payload["disk"]["status"] == "OK"
    assert payload["logs"] == []


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
