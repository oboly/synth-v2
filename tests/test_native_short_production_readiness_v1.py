"""Tests for the lightweight native SHORT production readiness check
(``src.operations.run_native_short_production_readiness_v1``).

This module orchestrates existing canonical contracts (DB env/grant
preflight, the authority manifest, systemd unit inspection, freshness
classifiers, repository source identity) into one blocker/warning verdict.
These tests exercise that orchestration and classification logic through
monkeypatched seams; they do not re-test the underlying contracts, which are
covered in their own test files.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import src.operations.run_native_short_production_readiness_v1 as readiness
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceState,
)


# ---------------------------------------------------------------------------
# Fakes for the database layer.
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self.conn = conn
        self.last_sql = ""

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self.last_sql = " ".join(sql.split())

    def fetchall(self):
        if "information_schema.tables" in self.last_sql:
            return [{"TABLE_NAME": name} for name in self.conn.existing_tables]
        return []

    def fetchone(self):
        if "market_price_snapshot" in self.last_sql:
            return self.conn.price_row
        if "obs_market_candle" in self.last_sql:
            return self.conn.candle_row
        return None


class _FakeConnection:
    def __init__(
        self,
        *,
        existing_tables: set[str],
        price_row: Any = None,
        candle_row: Any = None,
    ) -> None:
        self.existing_tables = existing_tables
        self.price_row = price_row
        self.candle_row = candle_row
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _FakeGrantConfig:
    host = "gurkdb"
    port = 3306
    user = "synth_chain_4h_writer"
    password = "not-a-real-secret"
    database = "synth"


class _FakeAudit:
    def __init__(self, *, passed: bool, missing=(), unexpected=(), violations=()) -> None:
        self.passed = passed
        self.missing = missing
        self.unexpected = unexpected
        self.violations = violations


class _FakeGrantResult:
    def __init__(self, audit: _FakeAudit) -> None:
        self.audit = audit


def _all_required_tables() -> set[str]:
    return set(readiness.REQUIRED_OBJECT_PRIVILEGES)


def _fresh_price_row(now):
    return {"observed_ts_utc": now.replace(tzinfo=None), "snapshot_row_count": 5}


def _fresh_candle_row(expected_close):
    return {"latest_close_ts_utc": expected_close.replace(tzinfo=None), "expected_close_row_count": 1}


def _patch_db_layer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing_tables: set[str] | None = None,
    grant_passed: bool = True,
    grant_missing: tuple = (),
    price_row: Any = "FRESH",
    candle_row: Any = "FRESH",
) -> _FakeConnection:
    monkeypatch.setattr(
        readiness.env_preflight, "run_preflight", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        readiness.grant_preflight, "load_candidate_config", lambda *a, **k: _FakeGrantConfig()
    )
    monkeypatch.setattr(
        readiness.grant_preflight,
        "run_preflight",
        lambda config: _FakeGrantResult(
            _FakeAudit(passed=grant_passed, missing=grant_missing)
        ),
    )

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    expected_close = readiness._expected_4h_close_ts_utc(now)

    resolved_price_row = _fresh_price_row(now) if price_row == "FRESH" else price_row
    resolved_candle_row = (
        _fresh_candle_row(expected_close) if candle_row == "FRESH" else candle_row
    )

    conn = _FakeConnection(
        existing_tables=existing_tables if existing_tables is not None else _all_required_tables(),
        price_row=resolved_price_row,
        candle_row=resolved_candle_row,
    )
    monkeypatch.setattr(readiness.pymysql, "connect", lambda **kwargs: conn)
    return conn


# ---------------------------------------------------------------------------
# HARD BLOCKER: missing required table.
# ---------------------------------------------------------------------------

def test_missing_required_table_is_hard_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = _all_required_tables() - {"native_short_map_level_target_event_coverage_v1"}
    _patch_db_layer(monkeypatch, existing_tables=tables)
    outcome = readiness.ReadinessOutcome()
    readiness.check_database(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert not outcome.ready
    assert any("REQUIRED_OBJECT_MISSING" in b for b in outcome.hard_blockers)
    assert any("native_short_map_level_target_event_coverage_v1" in b for b in outcome.hard_blockers)


# ---------------------------------------------------------------------------
# HARD BLOCKER: missing grant.
# ---------------------------------------------------------------------------

def test_missing_grant_is_hard_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db_layer(
        monkeypatch,
        grant_passed=False,
        grant_missing=("synth.native_short_map_level_target_event_v1:INSERT",),
    )
    outcome = readiness.ReadinessOutcome()
    readiness.check_database(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert not outcome.ready
    assert any("GRANT_CONTRACT_MISMATCH" in b for b in outcome.hard_blockers)


def test_database_query_failure_is_hard_blocker_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness.env_preflight, "run_preflight", lambda **kwargs: object())
    monkeypatch.setattr(
        readiness.grant_preflight, "load_candidate_config", lambda *a, **k: _FakeGrantConfig()
    )
    monkeypatch.setattr(
        readiness.grant_preflight,
        "run_preflight",
        lambda config: _FakeGrantResult(_FakeAudit(passed=True)),
    )

    def _boom(**kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(readiness.pymysql, "connect", _boom)
    outcome = readiness.ReadinessOutcome()
    readiness.check_database(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert not outcome.ready
    assert any("DB_CONNECTION_FAILED" in b for b in outcome.hard_blockers)


# ---------------------------------------------------------------------------
# HARD BLOCKER: authorization file unreadable/missing.
# ---------------------------------------------------------------------------

def test_missing_authorization_file_is_hard_blocker(tmp_path: Path) -> None:
    outcome = readiness.ReadinessOutcome()
    cap = {"authorization_guard": {"authorization_file": str(tmp_path / "missing.json")}}
    readiness.check_authorization_file(outcome, cap=cap)
    assert not outcome.ready
    assert any("AUTHORIZATION_FILE_MISSING" in b for b in outcome.hard_blockers)


def test_group_world_writable_authorization_file_is_hard_blocker(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text("{}", encoding="utf-8")
    auth_file.chmod(0o666)
    outcome = readiness.ReadinessOutcome()
    cap = {"authorization_guard": {"authorization_file": str(auth_file)}}
    readiness.check_authorization_file(outcome, cap=cap)
    assert not outcome.ready
    assert any("AUTHORIZATION_FILE_INSECURE" in b for b in outcome.hard_blockers)


def test_secure_readable_authorization_file_passes(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text("{}", encoding="utf-8")
    auth_file.chmod(0o640)
    outcome = readiness.ReadinessOutcome()
    cap = {"authorization_guard": {"authorization_file": str(auth_file)}}
    readiness.check_authorization_file(outcome, cap=cap)
    assert outcome.ready
    assert outcome.hard_blockers == []


# ---------------------------------------------------------------------------
# WARNING ONLY: stale price / stale candle.
# ---------------------------------------------------------------------------

def test_stale_price_is_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db_layer(monkeypatch, price_row=None)  # MISSING -> not fresh
    outcome = readiness.ReadinessOutcome()
    readiness.check_database(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert outcome.ready
    assert any("PUBLIC_PRICE_STALE" in w for w in outcome.warnings)


def test_stale_candle_is_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db_layer(monkeypatch, candle_row=None)  # MISSING -> not fresh
    outcome = readiness.ReadinessOutcome()
    readiness.check_database(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert outcome.ready
    assert any("EXPECTED_CANDLE_NOT_PERSISTED" in w for w in outcome.warnings)


def test_database_checks_never_commit_and_always_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _patch_db_layer(monkeypatch)
    outcome = readiness.ReadinessOutcome()
    readiness.check_database(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert conn.rollback_calls == 1
    assert conn.close_calls == 1
    assert not hasattr(conn, "commit_calls")


# ---------------------------------------------------------------------------
# WARNING ONLY: timer inactive / service last result failed.
# ---------------------------------------------------------------------------

class _FakeUnitState:
    def __init__(self, **kwargs: Any) -> None:
        self.unit = kwargs.get("unit", readiness.SERVICE_UNIT)
        self.load_state = kwargs.get("load_state", "loaded")
        self.fragment_path = kwargs.get("fragment_path", "/etc/systemd/system/x.service")
        self.drop_in_paths = kwargs.get("drop_in_paths", "")
        self.unit_file_state = kwargs.get("unit_file_state", "disabled")
        self.active_state = kwargs.get("active_state", "inactive")
        self.content = kwargs.get("content", b"")
        self.error = kwargs.get("error", "")


def _matching_service_content() -> bytes:
    lines = ["[Unit]", "ConditionHost=gurkdb", "[Service]"]
    lines.append("User=" + readiness.systemd_preflight.EXPECTED_SERVICE_FIELDS[("Service", "User")][0])
    lines.append(
        "WorkingDirectory="
        + readiness.systemd_preflight.EXPECTED_SERVICE_FIELDS[("Service", "WorkingDirectory")][0]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_timer_inactive_is_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _FakeUnitState(content=_matching_service_content(), unit_file_state="disabled", active_state="inactive")
    monkeypatch.setattr(readiness.systemd_preflight, "_load_unit_state", lambda unit, systemctl: state)
    monkeypatch.setattr(readiness, "_systemctl_show", lambda systemctl, unit, props: {})
    outcome = readiness.ReadinessOutcome()
    readiness.check_service_identity(outcome, systemctl="/usr/bin/systemctl")
    assert outcome.ready
    assert any("TIMER_NOT_ACTIVE" in w for w in outcome.warnings)


def test_service_last_result_failed_is_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _FakeUnitState(content=_matching_service_content(), unit_file_state="enabled", active_state="active")
    monkeypatch.setattr(readiness.systemd_preflight, "_load_unit_state", lambda unit, systemctl: state)
    monkeypatch.setattr(
        readiness,
        "_systemctl_show",
        lambda systemctl, unit, props: {"Result": "exit-code", "ExecMainStatus": "1"},
    )
    outcome = readiness.ReadinessOutcome()
    readiness.check_service_identity(outcome, systemctl="/usr/bin/systemctl")
    assert outcome.ready
    assert any("SERVICE_LAST_RESULT_NOT_SUCCESS" in w for w in outcome.warnings)


def test_service_identity_mismatch_is_hard_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_content = b"[Unit]\nConditionHost=devlap\n[Service]\nUser=someoneelse\nWorkingDirectory=/tmp\n"
    state = _FakeUnitState(content=bad_content)
    monkeypatch.setattr(readiness.systemd_preflight, "_load_unit_state", lambda unit, systemctl: state)
    monkeypatch.setattr(readiness, "_systemctl_show", lambda systemctl, unit, props: {})
    outcome = readiness.ReadinessOutcome()
    readiness.check_service_identity(outcome, systemctl="/usr/bin/systemctl")
    assert not outcome.ready
    assert any("SERVICE_IDENTITY_MISMATCH" in b for b in outcome.hard_blockers)


def test_service_not_installed_is_hard_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _FakeUnitState(load_state="not-found", content=None)
    monkeypatch.setattr(readiness.systemd_preflight, "_load_unit_state", lambda unit, systemctl: state)
    outcome = readiness.ReadinessOutcome()
    readiness.check_service_identity(outcome, systemctl="/usr/bin/systemctl")
    assert not outcome.ready
    assert any("SERVICE_NOT_INSTALLED" in b for b in outcome.hard_blockers)


def test_systemctl_not_found_is_hard_blocker() -> None:
    outcome = readiness.ReadinessOutcome()
    readiness.check_service_identity(outcome, systemctl=None)
    assert not outcome.ready
    assert any("SYSTEMCTL_NOT_FOUND" in b for b in outcome.hard_blockers)


# ---------------------------------------------------------------------------
# HARD BLOCKER: required scripts/modules missing.
# ---------------------------------------------------------------------------

def test_missing_wrapper_script_is_hard_blocker() -> None:
    outcome = readiness.ReadinessOutcome()
    cap = {"wrappers_invoked": ["scripts/does_not_exist_v1.sh"], "modules_invoked": []}
    readiness.check_required_entrypoints(outcome, cap=cap, repo_root=readiness.REPOSITORY_ROOT)
    assert not outcome.ready
    assert any("WRAPPER_SCRIPT_MISSING" in b for b in outcome.hard_blockers)


def test_missing_module_is_hard_blocker() -> None:
    outcome = readiness.ReadinessOutcome()
    cap = {"wrappers_invoked": [], "modules_invoked": ["src.market_data.does_not_exist_module_v1"]}
    readiness.check_required_entrypoints(outcome, cap=cap, repo_root=readiness.REPOSITORY_ROOT)
    assert not outcome.ready
    assert any("MODULE_MISSING" in b for b in outcome.hard_blockers)


def test_existing_wrapper_and_module_pass() -> None:
    outcome = readiness.ReadinessOutcome()
    cap = {
        "wrappers_invoked": ["scripts/run_chain_4h.sh"],
        "modules_invoked": ["src.market_data.native_short_repository_source_identity_v1"],
    }
    readiness.check_required_entrypoints(outcome, cap=cap, repo_root=readiness.REPOSITORY_ROOT)
    assert outcome.ready


# ---------------------------------------------------------------------------
# HARD BLOCKER: checkout not on main / dirty. WARNING: controlled dirt.
# ---------------------------------------------------------------------------

def test_checkout_not_on_main_is_hard_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain=""),
    )
    monkeypatch.setattr(readiness, "_current_branch", lambda repo_root: "feature/x")
    outcome = readiness.ReadinessOutcome()
    readiness.check_checkout(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert not outcome.ready
    assert any("CHECKOUT_NOT_ON_MAIN" in b for b in outcome.hard_blockers)


def test_checkout_dirty_is_hard_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(
            head_sha="a" * 40, status_porcelain=" M some_tracked_file.py\n"
        ),
    )
    monkeypatch.setattr(readiness, "_current_branch", lambda repo_root: "main")
    outcome = readiness.ReadinessOutcome()
    readiness.check_checkout(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert not outcome.ready
    assert any("CHECKOUT_DIRTY" in b for b in outcome.hard_blockers)


def test_controlled_untracked_file_is_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    controlled_line = f"?? {readiness.CONTROLLED_CHAIN_4H_UNTRACKED_PATH}\n"
    monkeypatch.setattr(
        readiness,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain=controlled_line),
    )
    monkeypatch.setattr(readiness, "_current_branch", lambda repo_root: "main")
    outcome = readiness.ReadinessOutcome()
    readiness.check_checkout(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert outcome.ready
    assert any("CONTROLLED_UNTRACKED_FILE_PRESENT" in w for w in outcome.warnings)


def test_clean_checkout_on_main_passes_with_no_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness,
        "inspect_running_repository_source",
        lambda: NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain=""),
    )
    monkeypatch.setattr(readiness, "_current_branch", lambda repo_root: "main")
    outcome = readiness.ReadinessOutcome()
    readiness.check_checkout(outcome, repo_root=readiness.REPOSITORY_ROOT)
    assert outcome.ready
    assert outcome.warnings == []


# ---------------------------------------------------------------------------
# Top-level main(): exit codes and no-mutation safety markers.
# ---------------------------------------------------------------------------

def test_main_exits_zero_when_only_warnings(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    outcome = readiness.ReadinessOutcome(warnings=["PUBLIC_PRICE_STALE: x"])
    monkeypatch.setattr(readiness, "evaluate_readiness", lambda: outcome)
    rc = readiness.main([])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert doc["ready"] is True
    assert doc["warning_count"] == 1
    assert doc["hard_blocker_count"] == 0


def test_main_exits_one_when_hard_blockers(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    outcome = readiness.ReadinessOutcome(hard_blockers=["REQUIRED_OBJECT_MISSING: x"])
    monkeypatch.setattr(readiness, "evaluate_readiness", lambda: outcome)
    rc = readiness.main([])
    assert rc == 1
    doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert doc["ready"] is False
    assert doc["hard_blocker_count"] == 1


def test_main_exits_two_when_evaluation_itself_fails(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def _boom():
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(readiness, "evaluate_readiness", _boom)
    rc = readiness.main([])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert doc["ready"] is False
    assert doc["reason_code"] == "READINESS_EVALUATION_FAILED"


def test_result_document_reports_zero_mutation_safety_markers(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    outcome = readiness.ReadinessOutcome()
    monkeypatch.setattr(readiness, "evaluate_readiness", lambda: outcome)
    readiness.main([])
    doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert doc["host_mutations"] == 0
    assert doc["database_writes"] == 0
    assert doc["systemd_mutations"] == 0
    assert doc["credential_changes"] == 0
    assert doc["writer_invocations"] == 0
    assert doc["decision_gate"] == "none"
    assert doc["execution_planner"] == "none"
    assert doc["executor"] == "none"


# ---------------------------------------------------------------------------
# Shell wrapper: symlink invocation from an unrelated cwd.
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
SHELL_WRAPPER = REPO / "scripts" / "synth_native_short_readiness_check_v1.sh"


def test_shell_wrapper_resolves_repo_through_symlink_from_unrelated_cwd(tmp_path: Path) -> None:
    fake_bin = tmp_path / "usr_local_bin"
    fake_bin.mkdir()
    symlink = fake_bin / "synth-native-short-readiness-check"
    symlink.symlink_to(SHELL_WRAPPER)

    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()

    completed = subprocess.run(
        [str(symlink)],
        cwd=str(unrelated_cwd),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "no usable venv found" not in completed.stderr
    assert "could not resolve physical script path" not in completed.stderr
    assert completed.returncode in (0, 1)
    doc = json.loads(completed.stdout.strip().splitlines()[-1])
    assert doc["event"] == "RESULT"
    assert "ready" in doc
