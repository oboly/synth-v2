from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.features import run_ma_breadth_snapshot_v1 as runner


class _Conn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _args() -> list[str]:
    return ["--asof-ts", "2026-09-01T00:00:00Z"]


def test_runner_emits_phase_query_and_single_finished_summary(monkeypatch, capsys):
    conn = _Conn()
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(runner, "fetch_universe_members", lambda *_args, **_kwargs: [object()])
    monkeypatch.setattr(runner, "fetch_candles_at_or_before", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        runner,
        "build_snapshot",
        lambda **_kwargs: SimpleNamespace(data_status="AVAILABLE", eligible_count=1, evaluated_count=1, universe_above_sma50_pct=100),
    )

    assert runner.main(_args()) == 0
    output = capsys.readouterr().out
    assert "STARTED runner=ma_breadth_snapshot_v1" in output
    assert "PHASE_END runner=ma_breadth_snapshot_v1 phase=fetch_universe rows=1" in output
    assert "PHASE_END runner=ma_breadth_snapshot_v1 phase=fetch_candles rows=0" in output
    assert output.count("FINISHED runner=ma_breadth_snapshot_v1") == 1
    assert conn.closed


def test_runner_failure_emits_exactly_one_failed_summary(monkeypatch, capsys):
    monkeypatch.setattr(runner, "get_db_connection", _Conn)
    monkeypatch.setattr(runner, "fetch_universe_members", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    assert runner.main(_args()) == 1
    output = capsys.readouterr().out
    assert output.count("FAILED runner=ma_breadth_snapshot_v1") == 1
    assert "error_type=RuntimeError" in output


def test_runner_authorization_denial_preserves_exit_code_and_emits_failed_summary(monkeypatch, capsys):
    import src.operations.writer_capability_authorization_v1 as authorization_module

    def deny_authorization(*_args, **_kwargs):
        print("AUTHORIZATION_DENIED capability=ma_breadth_snapshot")
        raise SystemExit(3)

    monkeypatch.setattr(authorization_module, "require_capability_write_authorization", deny_authorization)
    monkeypatch.setattr(runner, "get_db_connection", lambda: pytest.fail("DB connection must not be opened"))
    monkeypatch.setattr(runner, "persist_snapshot", lambda *_args, **_kwargs: pytest.fail("DB write must not run"))

    assert runner.main(_args() + ["--write-db"]) == 3
    output = capsys.readouterr().out
    assert "AUTHORIZATION_DENIED capability=ma_breadth_snapshot" in output
    assert output.count("FAILED runner=ma_breadth_snapshot_v1") == 1
    assert "error_type=SystemExit exit_code=3" in output


def test_runner_interrupt_emits_single_terminal_summary(monkeypatch, capsys):
    monkeypatch.setattr(runner, "get_db_connection", _Conn)
    monkeypatch.setattr(runner, "fetch_universe_members", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM")))

    assert runner.main(_args()) == 130
    output = capsys.readouterr().out
    assert output.count("INTERRUPTED runner=ma_breadth_snapshot_v1") == 1
    assert "signal=SIGTERM" in output
