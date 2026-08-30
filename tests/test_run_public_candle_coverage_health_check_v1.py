from __future__ import annotations

from datetime import UTC, datetime

import src.operations.run_public_candle_coverage_health_check_v1 as runner


NOW = datetime(2026, 8, 30, 12, 34, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows=None) -> None:
        self._rows = list(rows or [])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _sql, _params=None) -> None:
        return None

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows=None) -> None:
        self._rows = list(rows or [])
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return _Cursor(self._rows)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _terminal_lines(lines: list[str]) -> list[str]:
    return [
        line
        for line in lines
        if line.startswith("FINISHED ")
        or line.startswith("FAILED ")
        or line.startswith("INTERRUPTED ")
    ]


def test_runner_emits_started_phases_and_exactly_one_finished(monkeypatch, capsys) -> None:
    conn = _Connection([])
    monkeypatch.setattr(runner, "utc_now", lambda: NOW)
    monkeypatch.setattr(runner, "get_connection", lambda: conn)

    exit_code = runner.main(["--interval", "1h"])

    lines = capsys.readouterr().out.splitlines()
    assert exit_code == 1
    assert lines[0].startswith("STARTED run_public_candle_coverage_health_check_v1 ")
    assert any(line.startswith("PHASE_STARTED name=open_read_only_database") for line in lines)
    assert any(line.startswith("PHASE_FINISHED name=open_read_only_database") for line in lines)
    assert any(line.startswith("PHASE_STARTED name=load_enabled_assets") for line in lines)
    assert any(line.startswith("PHASE_FINISHED name=load_enabled_assets") for line in lines)
    terminals = _terminal_lines(lines)
    assert len(terminals) == 1
    assert terminals[0].startswith("FINISHED run_public_candle_coverage_health_check_v1 ")
    assert conn.rolled_back
    assert conn.closed


def test_runner_network_or_database_failure_emits_exactly_one_failed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runner, "utc_now", lambda: NOW)

    def _raise():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(runner, "get_connection", _raise)

    exit_code = runner.main(["--interval", "1h"])

    lines = capsys.readouterr().out.splitlines()
    assert exit_code == 1
    assert lines[0].startswith("STARTED run_public_candle_coverage_health_check_v1 ")
    terminals = _terminal_lines(lines)
    assert len(terminals) == 1
    assert terminals[0].startswith("FAILED run_public_candle_coverage_health_check_v1 ")
    assert "RuntimeError:db unavailable" in terminals[0]


def test_runner_keyboard_interrupt_emits_exactly_one_interrupted(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runner, "utc_now", lambda: NOW)

    def _interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "get_connection", _interrupt)

    exit_code = runner.main(["--interval", "1h"])

    lines = capsys.readouterr().out.splitlines()
    assert exit_code == 130
    assert lines[0].startswith("STARTED run_public_candle_coverage_health_check_v1 ")
    terminals = _terminal_lines(lines)
    assert len(terminals) == 1
    assert terminals[0].startswith("INTERRUPTED run_public_candle_coverage_health_check_v1 ")
