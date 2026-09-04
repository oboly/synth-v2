from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.features import run_momentum_evidence_snapshot_v1 as runner


class _Conn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _args() -> list[str]:
    return ["--asof-ts", "2026-09-01T00:00:00Z", "--asset-id", "1", "--market", "BTC-EUR"]


def test_runner_emits_phase_query_and_single_finished_summary(monkeypatch, capsys):
    conn = _Conn()
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(runner, "fetch_candles_for_asof", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        runner,
        "build_momentum_evidence",
        lambda **_kwargs: SimpleNamespace(
            data_quality="MISSING_SOURCE_CANDLE", status="INSUFFICIENT_DATA",
            macd_value=None, histogram_delta=None,
        ),
    )

    assert runner.main(_args()) == 0
    output = capsys.readouterr().out
    assert "STARTED runner=momentum_evidence_snapshot_v1" in output
    assert "PHASE_END runner=momentum_evidence_snapshot_v1 phase=fetch_candles rows=0" in output
    assert output.count("FINISHED runner=momentum_evidence_snapshot_v1") == 1
    assert "status=DRY_RUN" in output
    assert conn.closed


def test_runner_failure_emits_exactly_one_failed_summary(monkeypatch, capsys):
    monkeypatch.setattr(runner, "get_db_connection", _Conn)
    monkeypatch.setattr(
        runner, "fetch_candles_for_asof", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert runner.main(_args()) == 1
    output = capsys.readouterr().out
    assert output.count("FAILED runner=momentum_evidence_snapshot_v1") == 1
    assert "error_type=RuntimeError" in output


def test_runner_interrupt_emits_single_terminal_summary(monkeypatch, capsys):
    monkeypatch.setattr(runner, "get_db_connection", _Conn)
    monkeypatch.setattr(
        runner, "fetch_candles_for_asof", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM"))
    )

    assert runner.main(_args()) == 130
    output = capsys.readouterr().out
    assert output.count("INTERRUPTED runner=momentum_evidence_snapshot_v1") == 1
    assert "signal=SIGTERM" in output


def test_runner_authorization_denial_preserves_exit_code_and_emits_one_failed_summary(monkeypatch, capsys):
    def deny(*_args, **_kwargs):
        raise SystemExit(3)

    monkeypatch.setattr(
        "src.operations.writer_capability_authorization_v1.require_capability_write_authorization",
        deny,
    )
    monkeypatch.setattr(runner, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("DB must not open")))
    monkeypatch.setattr(runner, "persist_snapshot", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not persist")))

    assert runner.main([*_args(), "--write-db"]) == 3
    output = capsys.readouterr().out
    assert output.count("FAILED runner=momentum_evidence_snapshot_v1") == 1
    assert "FINISHED runner=momentum_evidence_snapshot_v1" not in output


def test_write_db_capability_is_unregistered_and_always_fails_closed():
    """`momentum_evidence_snapshot` is deliberately not registered in
    `CAPABILITY_IDENTITY` (writer_capability_authorization_v1). This mirrors
    the existing `ma_breadth_snapshot` precedent: --write-db always denies
    until an explicit, reviewed registration decision is made."""
    from pathlib import Path
    from src.operations.writer_capability_authorization_v1 import CAPABILITY_IDENTITY

    assert "momentum_evidence_snapshot" not in CAPABILITY_IDENTITY
    source = Path("src/operations/writer_capability_authorization_v1.py").read_text()
    assert "momentum_evidence_snapshot" not in source
