from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from src.operations import produce_host_preflight_external_evidence_v1 as producer
from src.operations import run_host_preflight_v1 as preflight
from src.operations.validate_host_preflight_external_evidence_v1 import (
    SCHEMA_PATH,
    validate_external_evidence,
)


CAPABILITY = "sector_rotation_snapshot"
HOST = "gurkdb"
COMMIT = "a" * 40
OBSERVED = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)
SECRET = "password=SENTINEL_SECRET_MUST_NOT_LEAK"


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[int]:
        return (1,)

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1

    def commit(self) -> None:
        raise AssertionError("producer must never commit")


class FakeAdapter:
    def __init__(
        self,
        *,
        dependency_failure: bool = False,
        secret_failure: bool = False,
        command_results: dict[tuple[str, ...], producer.CommandResult] | None = None,
    ) -> None:
        self.connection = FakeConnection()
        self.calls: list[tuple[str, object]] = []
        self.dependency_failure = dependency_failure
        self.secret_failure = secret_failure
        self.command_results = command_results or {}

    def resolve(self, host: str) -> None:
        self.calls.append(("resolve", host))
        if self.secret_failure:
            raise RuntimeError(SECRET)

    def connect_tcp(self, host: str, port: int) -> None:
        self.calls.append(("connect_tcp", (host, port)))
        if self.secret_failure:
            raise RuntimeError(SECRET)

    def run_command(self, args: list[str]) -> producer.CommandResult:
        self.calls.append(("run_command", tuple(args)))
        if self.dependency_failure:
            raise FileNotFoundError(SECRET)
        configured = self.command_results.get(tuple(args))
        if configured is not None:
            return configured
        if args[0] == "timedatectl":
            return producer.CommandResult(0, "yes\n")
        if args[0] == "journalctl":
            return producer.CommandResult(
                0, "Archived and active journals take up 20.0M in the file system.\n"
            )
        if args[1:2] == ["is-active"]:
            return producer.CommandResult(0, "active\n")
        if args[1:2] == ["is-enabled"]:
            return producer.CommandResult(0, "enabled\n")
        raise AssertionError(f"unexpected command: {args[0]}")

    def connect_database(self, config: dict[str, str | int]) -> FakeConnection:
        self.calls.append(("connect_database", tuple(sorted(config))))
        if self.secret_failure:
            raise RuntimeError(SECRET)
        return self.connection


def _runtime_config(tmp_path: Path, *, secret: str = SECRET) -> Path:
    path = tmp_path / "runtime.env"
    path.write_text(
        "\n".join(
            (
                "DB_HOST=db.example.invalid",
                "DB_PORT=3306",
                "DB_USER=synth_ro",
                f"DB_PASSWORD={secret}",
                "DB_NAME=synth",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _payload(
    tmp_path: Path,
    *,
    adapter: FakeAdapter | None = None,
    runtime_config_file: Path | None = None,
) -> tuple[dict, FakeAdapter]:
    selected_adapter = adapter or FakeAdapter()
    payload = producer.collect_evidence(
        capability=CAPABILITY,
        hostname=HOST,
        checkout_commit=COMMIT,
        runtime_config_file=runtime_config_file or _runtime_config(tmp_path),
        observed_at=OBSERVED,
        adapter=selected_adapter,
    )
    return payload, selected_adapter


def _validate(payload: dict):
    return validate_external_evidence(
        payload,
        capability=CAPABILITY,
        expected_host=HOST,
        expected_commit=COMMIT,
        reference_time=OBSERVED,
    )


def test_sector_rotation_payload_is_accepted_by_schema_and_unknown_capability_rejected(
    tmp_path: Path,
) -> None:
    payload, _ = _payload(tmp_path)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator(schema).validate(payload)

    unknown = dict(payload)
    unknown["capability"] = "unknown_writer"
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(unknown))
    assert errors
    assert errors[0].validator == "enum"


def test_producer_emits_all_required_and_explicit_not_required_checks(
    tmp_path: Path,
) -> None:
    payload, _ = _payload(tmp_path)
    assert set(payload["checks"]) == set(preflight.PREFLIGHT_EXTERNAL_CHECKS)
    assert all(
        payload["checks"][name]["status"] == "PASS"
        for name in producer.REQUIRED_CHECKS
    )
    for name in producer.NOT_REQUIRED_CHECKS:
        assert payload["checks"][name] == {
            "status": "PASS",
            "detail": "reason_code=NOT_REQUIRED_BY_CAPABILITY",
            "evidence_source": f"{producer.EVIDENCE_SOURCE}#{name}",
            "observed_at_utc": "2026-07-30T12:00:00Z",
        }


def test_missing_dependencies_and_unreadable_configuration_fail_closed(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.env"
    payload, _ = _payload(
        tmp_path,
        adapter=FakeAdapter(dependency_failure=True),
        runtime_config_file=missing,
    )
    assert payload["checks"]["runtime_configuration"]["status"] == "FAIL"
    assert payload["checks"]["mariadb_connectivity"]["status"] == "FAIL"
    assert payload["checks"]["dns"]["status"] == "FAIL"
    assert payload["checks"]["ntp_time_sync"]["status"] == "FAIL"
    assert payload["checks"]["journald_logrotation"]["status"] == "FAIL"


def test_journald_command_success_with_empty_output_fails_closed() -> None:
    adapter = FakeAdapter(
        command_results={
            ("journalctl", "--disk-usage", "--no-pager"): producer.CommandResult(
                0, ""
            )
        }
    )
    result = producer._probe_journald(adapter)
    assert result == producer.ProbeResult("FAIL", "JOURNALD_USAGE_UNREADABLE")


@pytest.mark.parametrize(
    ("command", "returncode", "output", "reason_code"),
    (
        (
            ("systemctl", "is-active", "logrotate.timer"),
            3,
            "inactive\n",
            "LOGROTATE_TIMER_NOT_ACTIVE",
        ),
        (
            ("systemctl", "is-enabled", "logrotate.timer"),
            1,
            "disabled\n",
            "LOGROTATE_TIMER_NOT_ENABLED",
        ),
    ),
)
def test_readable_noncompliant_logrotate_policy_fails_closed(
    command: tuple[str, ...],
    returncode: int,
    output: str,
    reason_code: str,
) -> None:
    adapter = FakeAdapter(
        command_results={command: producer.CommandResult(returncode, output)}
    )
    result = producer._probe_journald(adapter)
    assert result == producer.ProbeResult("FAIL", reason_code)


def test_compliant_journald_and_logrotate_policy_passes() -> None:
    result = producer._probe_journald(FakeAdapter())
    assert result == producer.ProbeResult(
        "PASS", "JOURNALD_READABLE_LOGROTATE_TIMER_ACTIVE_ENABLED"
    )


@pytest.mark.parametrize(
    ("command", "returncode", "output", "reason_code"),
    (
        (
            ("systemctl", "is-active", "logrotate.timer"),
            0,
            "active\ninactive\n",
            "LOGROTATE_TIMER_STATE_MALFORMED_OR_AMBIGUOUS",
        ),
        (
            ("systemctl", "is-enabled", "logrotate.timer"),
            0,
            "sometimes\n",
            "LOGROTATE_TIMER_STATE_MALFORMED_OR_AMBIGUOUS",
        ),
        (
            ("systemctl", "is-active", "logrotate.timer"),
            1,
            "active\n",
            "LOGROTATE_TIMER_STATE_CONTRADICTORY",
        ),
    ),
)
def test_malformed_ambiguous_or_contradictory_timer_state_fails_closed(
    command: tuple[str, ...],
    returncode: int,
    output: str,
    reason_code: str,
) -> None:
    adapter = FakeAdapter(
        command_results={command: producer.CommandResult(returncode, output)}
    )
    result = producer._probe_journald(adapter)
    assert result == producer.ProbeResult("FAIL", reason_code)


def test_mariadb_probe_is_transactionally_read_only_and_never_commits(
    tmp_path: Path,
) -> None:
    payload, adapter = _payload(tmp_path)
    connection = adapter.connection
    assert payload["checks"]["mariadb_connectivity"]["status"] == "PASS"
    assert connection.cursor_instance.statements == list(producer._READ_ONLY_SQL)
    assert all(
        statement in {
            "SET SESSION TRANSACTION READ ONLY",
            "START TRANSACTION READ ONLY",
            "SELECT 1",
        }
        for statement in connection.cursor_instance.statements
    )
    assert connection.rollback_count == 1
    assert connection.close_count == 1
    assert connection.cursor_instance.closed is True


def test_secret_shaped_values_never_reach_evidence_or_probe_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _runtime_config(tmp_path)
    output = tmp_path / "evidence.json"
    adapter = FakeAdapter(secret_failure=True)
    monkeypatch.setattr(producer.platform, "node", lambda: HOST)
    monkeypatch.setattr(producer, "_actual_checkout_commit", lambda _path: COMMIT)
    monkeypatch.setattr(
        "sys.argv",
        [
            "produce_host_preflight_external_evidence_v1",
            "--capability",
            CAPABILITY,
            "--expected-host",
            HOST,
            "--expected-commit",
            COMMIT,
            "--checkout-path",
            str(tmp_path),
            "--runtime-config-file",
            str(config),
            "--output-file",
            str(output),
        ],
    )
    rc = producer.main(adapter_factory=lambda: adapter, now=lambda: OBSERVED)
    captured = capsys.readouterr()
    rendered = captured.out + captured.err + output.read_text(encoding="utf-8")
    assert rc == 3
    assert "SENTINEL_SECRET_MUST_NOT_LEAK" not in rendered
    assert "password=" not in rendered


def test_secret_shaped_subprocess_output_is_discarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _runtime_config(tmp_path)
    output = tmp_path / "evidence.json"
    adapter = FakeAdapter(
        command_results={
            ("journalctl", "--disk-usage", "--no-pager"): producer.CommandResult(
                0, SECRET
            )
        }
    )
    monkeypatch.setattr(producer.platform, "node", lambda: HOST)
    monkeypatch.setattr(producer, "_actual_checkout_commit", lambda _path: COMMIT)
    monkeypatch.setattr(
        "sys.argv",
        [
            "produce_host_preflight_external_evidence_v1",
            "--capability",
            CAPABILITY,
            "--expected-host",
            HOST,
            "--expected-commit",
            COMMIT,
            "--checkout-path",
            str(tmp_path),
            "--runtime-config-file",
            str(config),
            "--output-file",
            str(output),
        ],
    )
    assert producer.main(adapter_factory=lambda: adapter, now=lambda: OBSERVED) == 0
    captured = capsys.readouterr()
    rendered = captured.out + captured.err + output.read_text(encoding="utf-8")
    assert "SENTINEL_SECRET_MUST_NOT_LEAK" not in rendered
    assert "password=" not in rendered


def test_system_command_stdout_and_stderr_are_never_rendered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outputs = {
        ("journalctl", "--disk-usage", "--no-pager"): (
            0,
            SECRET,
        ),
        ("systemctl", "is-active", "logrotate.timer"): (0, "active\n"),
        ("systemctl", "is-enabled", "logrotate.timer"): (0, "enabled\n"),
    }

    def fake_run(args: list[str], **_kwargs) -> producer.subprocess.CompletedProcess[str]:
        return producer.subprocess.CompletedProcess(
            args,
            outputs[tuple(args)][0],
            stdout=outputs[tuple(args)][1],
            stderr=SECRET,
        )

    monkeypatch.setattr(producer.subprocess, "run", fake_run)
    result = producer._probe_journald(producer.SystemProbeAdapter())
    captured = capsys.readouterr()
    assert result == producer.ProbeResult(
        "PASS", "JOURNALD_READABLE_LOGROTATE_TIMER_ACTIVE_ENABLED"
    )
    assert SECRET not in result.reason_code + captured.out + captured.err


def test_malformed_producer_payload_fails_canonical_validation(tmp_path: Path) -> None:
    payload, _ = _payload(tmp_path)
    payload["checks"]["dns"]["status"] = "UNVERIFIED"
    result = _validate(payload)
    assert not result.ok
    assert any(issue.code == "CHECK_STATUS_INVALID" for issue in result.issues)


def test_main_refuses_to_persist_malformed_collected_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _runtime_config(tmp_path)
    output = tmp_path / "evidence.json"
    payload, _ = _payload(tmp_path)
    payload["checks"]["dns"]["status"] = "UNVERIFIED"
    monkeypatch.setattr(producer.platform, "node", lambda: HOST)
    monkeypatch.setattr(producer, "_actual_checkout_commit", lambda _path: COMMIT)
    monkeypatch.setattr(producer, "collect_evidence", lambda **_kwargs: payload)
    monkeypatch.setattr(
        "sys.argv",
        [
            "produce_host_preflight_external_evidence_v1",
            "--capability",
            CAPABILITY,
            "--expected-host",
            HOST,
            "--expected-commit",
            COMMIT,
            "--checkout-path",
            str(tmp_path),
            "--runtime-config-file",
            str(config),
            "--output-file",
            str(output),
        ],
    )
    assert producer.main(now=lambda: OBSERVED) == 2
    captured = capsys.readouterr()
    assert captured.out == "FAILED reason_code=PRODUCER_EVIDENCE_INVALID\n"
    assert captured.err == ""
    assert not output.exists()


def test_strict_preflight_consumes_valid_sector_rotation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, _ = _payload(tmp_path)
    validation = _validate(payload)
    assert validation.ok, validation.errors
    monkeypatch.setattr(
        preflight,
        "_local_checks",
        lambda **_kwargs: {
            name: preflight.CheckResult(name, preflight.STATUS_PASS, "ok")
            for name in preflight.PREFLIGHT_LOCAL_CHECKS
        },
    )
    results = preflight.run_preflight(
        capability=CAPABILITY,
        expected_host=HOST,
        expected_commit=COMMIT,
        checkout_path=tmp_path,
        external_evidence_checks=validation.checks,
    )
    assert preflight._strict_exit_status(results) == 0
    by_name = {result.name: result for result in results}
    assert all(by_name[name].status == "PASS" for name in producer.REQUIRED_CHECKS)
    assert all(by_name[name].required is False for name in producer.NOT_REQUIRED_CHECKS)


def test_probe_surface_contains_no_mutation_capable_calls(tmp_path: Path) -> None:
    payload, adapter = _payload(tmp_path)
    assert ("connect_tcp", ("api.coingecko.com", 443)) in adapter.calls
    command_calls = [value for name, value in adapter.calls if name == "run_command"]
    assert command_calls == [
        ("timedatectl", "show", "--property=NTPSynchronized", "--value"),
        ("journalctl", "--disk-usage", "--no-pager"),
        ("systemctl", "is-active", "logrotate.timer"),
        ("systemctl", "is-enabled", "logrotate.timer"),
    ]
    assert all(
        not (
            command[0] == "systemctl"
            and any(action in command for action in ("start", "stop", "enable", "disable"))
        )
        for command in command_calls
    )
    expected_zero_mutation = {
        "host_mutations": 0,
        "database_writes": 0,
        "writer_invocations": 0,
        "systemctl_mutations": 0,
        "order_submission": 0,
        "broker_writes": 0,
        "authorization_created": False,
        "deployment_performed": False,
    }
    assert {
        name: payload["safety_markers"][name] for name in expected_zero_mutation
    } == expected_zero_mutation


def test_payload_and_serialized_json_are_deterministic(tmp_path: Path) -> None:
    first, _ = _payload(tmp_path)
    second, _ = _payload(tmp_path)
    assert first == second
    assert json.dumps(first, indent=2, sort_keys=True) == json.dumps(
        second, indent=2, sort_keys=True
    )


def test_runtime_configuration_permissions_fail_closed(tmp_path: Path) -> None:
    config = _runtime_config(tmp_path)
    config.chmod(0o640)
    payload, _ = _payload(tmp_path, runtime_config_file=config)
    check = payload["checks"]["runtime_configuration"]
    assert check["status"] == "FAIL"
    assert check["detail"] == "reason_code=RUNTIME_CONFIG_PERMISSIONS_UNSAFE"


def test_runtime_configuration_symlink_fails_closed(tmp_path: Path) -> None:
    config = _runtime_config(tmp_path)
    link = tmp_path / "runtime-link.env"
    link.symlink_to(config)
    payload, _ = _payload(tmp_path, runtime_config_file=link)
    assert payload["checks"]["runtime_configuration"]["status"] == "FAIL"
