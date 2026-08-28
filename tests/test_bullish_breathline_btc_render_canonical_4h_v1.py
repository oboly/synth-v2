from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import src.research.run_bullish_breathline_btc_render_canonical_4h_v1 as runner


BASE = datetime(2026, 1, 1, 0, 0, 0)


class FakeCursor:
    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn
        self.rows: list[dict[str, Any]] = []
        self.index = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> int:
        compact = " ".join(sql.split())
        self.conn.executed.append((compact, params))
        self.index = 0
        if compact in {
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
            "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY",
        }:
            self.rows = []
        elif "FROM asset" in compact:
            assert params is not None
            requested = str(params[0]).upper()
            self.rows = list(self.conn.assets.get(requested, []))
        elif "FROM obs_market_candle" in compact:
            assert params is not None
            asset_id = int(params[0])
            self.rows = list(self.conn.candles.get(asset_id, []))
        else:
            raise AssertionError(f"unexpected SQL: {compact}")
        return len(self.rows)

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def fetchmany(self, size: int) -> list[dict[str, Any]]:
        if self.index >= len(self.rows):
            return []
        end = min(len(self.rows), self.index + size)
        result = self.rows[self.index:end]
        self.index = end
        return result


class FakeConnection:
    def __init__(self) -> None:
        self.assets = {
            "BTC": [{"asset_id": 1, "symbol": "BTC"}],
            "RENDER": [{"asset_id": 38, "symbol": "RENDER"}],
        }
        self.candles = {
            1: [candle(1, BASE), candle(1, BASE + timedelta(hours=4))],
            38: [candle(38, BASE), candle(38, BASE + timedelta(hours=4))],
        }
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self, _cursor_class: object | None = None) -> FakeCursor:
        return FakeCursor(self)

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def candle(asset_id: int, open_ts: datetime) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "venue": runner.VENUE,
        "interval_code": runner.INTERVAL_CODE,
        "open_ts_utc": open_ts,
        "close_ts_utc": open_ts + timedelta(hours=4),
        "open_price": Decimal("100"),
        "high_price": Decimal("105"),
        "low_price": Decimal("95"),
        "close_price": Decimal("102"),
        "volume_base": Decimal("10"),
    }


def fake_tracker(*, csv_path: Path, symbol: str, out_dir: Path) -> dict[str, Any]:
    assert csv_path.is_file()
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "model_version": "bullish-breathline-tracker-v1.0.0",
        "symbol": symbol,
        "cycle_count": 1,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    (out_dir / "latest_cycles.json").write_text("[]\n", encoding="utf-8")
    (out_dir / "cycle_ledger.jsonl").write_text(
        json.dumps({"cycle_id": f"{symbol.lower()}-1", "symbol": symbol}) + "\n",
        encoding="utf-8",
    )
    return summary


def patch_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "resolve_analysis_commit", lambda root: "analysis-418")
    monkeypatch.setattr(runner, "runner_source_sha256", lambda: "runner-hash")
    monkeypatch.setattr(runner, "registry_source_sha256", lambda: "registry-hash")
    monkeypatch.setattr(runner, "resolve_tracker_source_commit", lambda root: "tracker-commit")
    monkeypatch.setattr(
        runner,
        "tracker_source_hashes",
        lambda root: {"tracker.py": "tracker-hash"},
    )


def test_scope_and_safety_are_frozen() -> None:
    assert runner.SYMBOLS == ("BTC", "RENDER")
    assert runner.REGISTRY_VERSION == "1.0.0"
    assert runner.SAFETY_MARKERS["research_only"] is True
    assert runner.SAFETY_MARKERS["market_only"] is True
    assert runner.SAFETY_MARKERS["account_awareness"] == 0
    assert runner.SAFETY_MARKERS["relationship_analysis"] == 0
    assert runner.SAFETY_MARKERS["broker_writes"] == 0
    assert runner.SAFETY_MARKERS["order_submission"] == 0
    assert runner.SAFETY_MARKERS["decision_gate"] == "none"
    assert runner.SAFETY_MARKERS["execution_planner"] == "none"
    assert runner.SAFETY_MARKERS["executor"] == "none"


def test_identity_resolution_allows_only_btc_and_render() -> None:
    conn = FakeConnection()
    assert runner.resolve_asset_identity(conn, "btc") == runner.AssetIdentity(1, "BTC")
    assert runner.resolve_asset_identity(conn, "render") == runner.AssetIdentity(38, "RENDER")
    with pytest.raises(ValueError, match="outside frozen #418"):
        runner.resolve_asset_identity(conn, "TAO")


def test_run_produces_independent_ledgers_without_relationship_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    patch_provenance(monkeypatch)
    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    monkeypatch.setattr(runner, "run_tracker", fake_tracker)

    manifest = runner.run(
        out_root=tmp_path,
        run_id="independent-ledgers",
        cli_args=["--run-id", "independent-ledgers"],
        heartbeat_seconds=3600,
    )

    assert manifest["symbols"] == ["BTC", "RENDER"]
    assert manifest["relationship_analysis_performed"] is False
    assert manifest["relationship_registry_version"] == "1.0.0"
    assert manifest["analysis_commit_sha"] == "analysis-418"
    assert manifest["runner_source_sha256"] == "runner-hash"
    assert manifest["registry_source_sha256"] == "registry-hash"
    assert [asset["symbol"] for asset in manifest["assets"]] == ["BTC", "RENDER"]

    for symbol in runner.SYMBOLS:
        tracker_dir = tmp_path / "independent-ledgers" / symbol / "tracker"
        assert (tracker_dir / "cycle_ledger.jsonl").is_file()
        assert (tracker_dir / "summary.json").is_file()

    stored = json.loads(
        (tmp_path / "independent-ledgers" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert stored["relationship_analysis_performed"] is False
    assert stored["safety"]["relationship_analysis"] == 0
    assert conn.rollback_calls == 1
    assert conn.close_calls == 1


def test_completed_run_id_is_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_provenance(monkeypatch)
    run_dir = tmp_path / "complete"
    run_dir.mkdir()
    manifest = run_dir / "run_manifest.json"
    manifest.write_text('{"complete":true}\n', encoding="utf-8")
    sentinel = run_dir / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="completed immutable run"):
        runner.run(
            out_root=tmp_path,
            run_id="complete",
            cli_args=[],
        )

    assert sentinel.read_text(encoding="utf-8") == "keep\n"
