import signal
import time
from datetime import datetime, timedelta

import pytest

import src.research.forecast_confluence_pit_cohort_audit_v1 as audit
import src.research.forecast_confluence_pit_replay_v1 as replay
from src.research.runner_lifecycle_v1 import RunnerLifecycle


class FakeConnection:
    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def row() -> dict:
    return {
        "asof_ts_utc": datetime(2026, 8, 1), "map_id": 1, "market": "AAA", "venue": "bitvavo",
        "reference_price": 100, "pressure_state": None, "sector_rotation_state": None,
        "rotation_pressure_asof_ts_utc": None, "sector_rotation_asof_ts_utc": None,
        "trend_score": .8, "setup_score": .8, "compass_score": .8, "volume_score": .8,
        "distance_entry_to_target_pct": .8, "rotation_pressure_score": None, "sector_rotation_score": None,
    }


def candles() -> dict[str, list[dict]]:
    start = datetime(2026, 8, 1)
    return {"AAA": [
        {"close_ts_utc": start + timedelta(hours=hours), "close_price": 101, "high_price": 102, "low_price": 99}
        for hours in (4, 24, 168)
    ]}


def events(text: str, event: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(f"{event} ")]


def configure_replay(monkeypatch) -> None:
    monkeypatch.setattr(replay, "get_connection", FakeConnection)
    monkeypatch.setattr(replay, "fetch_rows", lambda *_args, **_kwargs: [row()])
    monkeypatch.setattr(replay, "fetch_candles", lambda *_args, **_kwargs: candles())


def test_replay_success_emits_one_terminal_lifecycle(monkeypatch, tmp_path, capsys) -> None:
    configure_replay(monkeypatch)
    assert replay.main(["--start", "2026-08-01T00:00:00Z", "--end", "2026-08-02T00:00:00Z", "--output", str(tmp_path / "result.json"), "--heartbeat-seconds", "0"]) == 0
    text = capsys.readouterr().out
    assert len(events(text, "STARTED")) == 1
    assert len(events(text, "FINISHED")) == 1
    assert not events(text, "INTERRUPTED") and not events(text, "FAILED")
    for phase in ("FETCH_FORECASTS_FINISHED", "FETCH_CANDLES_FINISHED", "EVALUATION_FINISHED", "WRITE_ARTIFACT_FINISHED"):
        assert events(text, phase)


def test_audit_success_emits_paths_and_one_terminal_lifecycle(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(audit, "get_connection", FakeConnection)
    monkeypatch.setattr(audit, "fetch_pipeline_stage_counts", lambda *_args, **_kwargs: {"raw": 1, "venue": 1, "interval": 1, "fib_status": 1, "asset": 1, "same_ts_signal": 1, "dedup": 1, "final": 1})
    monkeypatch.setattr(audit, "fetch_rows", lambda *_args, **_kwargs: [row()])
    monkeypatch.setattr(audit, "fetch_candles", lambda *_args, **_kwargs: candles())
    assert audit.main(["--start", "2026-08-01T00:00:00Z", "--end", "2026-08-02T00:00:00Z", "--output-dir", str(tmp_path), "--created-from-commit", "a" * 40, "--heartbeat-seconds", "0"]) == 0
    text = capsys.readouterr().out
    assert len(events(text, "STARTED")) == len(events(text, "FINISHED")) == 1
    assert "audit_path=" in events(text, "FINISHED")[0]


@pytest.mark.parametrize("signum, name", [(signal.SIGINT, "SIGINT"), (signal.SIGTERM, "SIGTERM")])
def test_replay_signal_emits_one_interrupted(monkeypatch, tmp_path, capsys, signum, name) -> None:
    configure_replay(monkeypatch)
    monkeypatch.setattr(replay, "fetch_rows", lambda *_args, **_kwargs: signal.raise_signal(signum))
    assert replay.main(["--start", "2026-08-01T00:00:00Z", "--end", "2026-08-02T00:00:00Z", "--output", str(tmp_path / "result.json"), "--heartbeat-seconds", "0"]) == 130
    text = capsys.readouterr().out
    assert len(events(text, "INTERRUPTED")) == 1
    assert f"signal={name}" in events(text, "INTERRUPTED")[0]
    assert not events(text, "FINISHED") and not events(text, "FAILED")


def test_replay_failure_emits_one_failed(monkeypatch, tmp_path, capsys) -> None:
    configure_replay(monkeypatch)
    monkeypatch.setattr(replay, "fetch_rows", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert replay.main(["--start", "2026-08-01T00:00:00Z", "--end", "2026-08-02T00:00:00Z", "--output", str(tmp_path / "result.json"), "--heartbeat-seconds", "0"]) == 1
    text = capsys.readouterr().out
    assert len(events(text, "FAILED")) == 1
    assert not events(text, "FINISHED") and not events(text, "INTERRUPTED")


def test_heartbeat_stops_before_terminal(capsys) -> None:
    lifecycle = RunnerLifecycle(runner="test", heartbeat_seconds=.001)
    lifecycle.start()
    lifecycle.phase_started("BLOCKING")
    time.sleep(.01)
    lifecycle.phase_finished("BLOCKING")
    assert not lifecycle.heartbeat_running
    lifecycle.terminal("FINISHED")
    lifecycle.close()
    text = capsys.readouterr().out
    assert events(text, "HEARTBEAT")
    assert len(events(text, "FINISHED")) == 1
