from __future__ import annotations

import sys
from typing import Any

from src.measurement import run_asset_interval_quality_snapshot as runner


class _FakeConnection:
    def close(self) -> None:
        pass


def test_main_uses_bounded_quality_query_read_timeout(monkeypatch, capsys) -> None:
    captured: dict[str, Any] = {}
    connection = _FakeConnection()

    def fake_get_connection(*, read_timeout: int | None = None):
        captured["read_timeout"] = read_timeout
        return connection

    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(runner, "fetch_quality_rows", lambda conn, *, venue: [])
    monkeypatch.setattr(sys, "argv", ["quality", "--venue", "bitvavo", "--output", "none"])

    assert runner.main() == 0
    assert captured["read_timeout"] == runner.QUALITY_QUERY_READ_TIMEOUT_SECONDS == 180
    assert "rows=0" in capsys.readouterr().out
