from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pymysql.cursors import SSDictCursor

import src.research.run_bullish_breathline_canonical_4h_v1 as runner_module
from src.research.run_bullish_breathline_canonical_4h_v1 import (
    FETCH_BATCH_ROWS,
    INTERVAL_CODE,
    VENUE,
    AssetIdentity,
    RunnerInterrupted,
    begin_read_only_transaction,
    collect_tracker_artifacts,
    export_source_candles,
    load_source_checkpoint,
    periodic_heartbeat,
    prepare_tracker_output_dir,
    resolve_asset_identity,
    sha256_file,
    validate_run_id,
    write_source_checkpoint,
)


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
        self.conn.fetchmany_sizes.append(size)
        if self.index >= len(self.rows):
            return []
        # Deliberately return tiny batches so tests prove the wrapper keeps asking
        # fetchmany() instead of relying on one broad fetchall().
        end = min(len(self.rows), self.index + 2)
        result = self.rows[self.index:end]
        self.index = end
        return result


class FakeConnection:
    def __init__(
        self,
        *,
        assets: dict[str, list[dict[str, Any]]] | None = None,
        candles: dict[int, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.assets = assets or {}
        self.candles = candles or {}
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.fetchmany_sizes: list[int] = []
        self.cursor_classes: list[object | None] = []
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self, cursor_class: object | None = None) -> FakeCursor:
        self.cursor_classes.append(cursor_class)
        return FakeCursor(self)

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def candle_row(
    *,
    asset_id: int,
    open_ts: datetime,
    venue: str = VENUE,
    interval_code: str = INTERVAL_CODE,
    open_price: str = "100.0000",
    high_price: str = "105.0000",
    low_price: str = "95.0000",
    close_price: str = "102.0000",
    volume_base: str | None = "10.5000",
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "venue": venue,
        "interval_code": interval_code,
        "open_ts_utc": open_ts,
        "close_ts_utc": open_ts + timedelta(hours=4),
        "open_price": Decimal(open_price),
        "high_price": Decimal(high_price),
        "low_price": Decimal(low_price),
        "close_price": Decimal(close_price),
        "volume_base": None if volume_base is None else Decimal(volume_base),
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def terminal_lines(output: str) -> list[str]:
    return [
        line
        for line in output.splitlines()
        if line.startswith("FINISHED ")
        or line.startswith("FAILED ")
        or line.startswith("INTERRUPTED ")
    ]


def test_begin_read_only_transaction_guarantees_consistent_snapshot() -> None:
    conn = FakeConnection()
    begin_read_only_transaction(conn)
    assert conn.executed == [
        ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ", None),
        ("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY", None),
    ]


def test_required_safety_markers_are_explicit() -> None:
    markers = runner_module.SAFETY_MARKERS
    assert markers["research_only"] is True
    assert markers["market_only"] is True
    assert markers["account_awareness"] == 0
    assert markers["selection_engine_changes"] == 0
    assert markers["decision_gate_changes"] == 0
    assert markers["execution_planner_changes"] == 0
    assert markers["executor_changes"] == 0
    assert markers["broker_calls"] == 0
    assert markers["broker_private_calls"] == 0
    assert markers["broker_writes"] == 0
    assert markers["order_submission"] == 0
    assert markers["live_orders"] == 0
    assert markers["live_trading_permission"] == 0
    assert markers["db_writes"] == 0
    assert markers["production_db_writes"] == 0
    assert markers["production_schema_changes"] == 0
    assert markers["runtime_activation"] == 0
    assert markers["decision_gate"] == "none"
    assert markers["execution_planner"] == "none"
    assert markers["executor"] == "none"


def test_resolve_asset_identity_requires_single_frozen_identity(capsys: pytest.CaptureFixture[str]) -> None:
    conn = FakeConnection(assets={"RENDER": [{"asset_id": 7, "symbol": "RENDER"}]})
    assert resolve_asset_identity(conn, "render") == AssetIdentity(asset_id=7, symbol="RENDER")
    output = capsys.readouterr().out
    assert "QUERY_FINISHED resolve_asset_identity" in output
    assert "row_count=1" in output
    assert "symbol=RENDER" in output

    with pytest.raises(ValueError, match="outside frozen"):
        resolve_asset_identity(conn, "BTC")

    missing = FakeConnection()
    with pytest.raises(RuntimeError, match="exactly one canonical asset identity"):
        resolve_asset_identity(missing, "RENDER")


def test_export_streams_and_maps_open_ts_to_tracker_ts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = AssetIdentity(asset_id=7, symbol="RENDER")
    rows = [
        candle_row(asset_id=7, open_ts=BASE + timedelta(hours=offset))
        for offset in (0, 4, 8, 12, 16)
    ]
    conn = FakeConnection(candles={7: rows})
    path = tmp_path / "canonical.csv"

    result = export_source_candles(conn, identity=identity, csv_path=path)
    exported = read_csv(path)
    output = capsys.readouterr().out

    assert result.source_row_count == 5
    assert result.source_gap_count == 0
    assert result.first_source_ts == "2026-01-01T00:00:00Z"
    assert result.last_source_ts == "2026-01-01T16:00:00Z"
    assert result.source_sha256 == sha256_file(path)
    assert exported[0] == {
        "ts": "2026-01-01T00:00:00Z",
        "open": "100.0000",
        "high": "105.0000",
        "low": "95.0000",
        "close": "102.0000",
        "volume": "10.5000",
    }
    assert SSDictCursor in conn.cursor_classes
    assert conn.fetchmany_sizes
    assert all(size == FETCH_BATCH_ROWS for size in conn.fetchmany_sizes)
    assert any("ORDER BY open_ts_utc ASC" in sql for sql, _ in conn.executed)
    assert "QUERY_FINISHED source_export" in output
    assert "row_count=5" in output
    assert "CHECKPOINT source_csv" in output


def test_gap_is_reported_without_fabricating_rows(tmp_path: Path) -> None:
    identity = AssetIdentity(asset_id=7, symbol="RENDER")
    conn = FakeConnection(
        candles={
            7: [
                candle_row(asset_id=7, open_ts=BASE),
                candle_row(asset_id=7, open_ts=BASE + timedelta(hours=8)),
            ]
        }
    )
    path = tmp_path / "canonical.csv"

    result = export_source_candles(conn, identity=identity, csv_path=path)

    assert result.source_row_count == 2
    assert len(read_csv(path)) == 2
    assert result.source_gap_count == 1
    assert result.inferred_missing_candle_count == 1
    assert result.gaps[0].delta_seconds == 8 * 60 * 60
    assert result.gaps[0].inferred_missing_candles == 1


@pytest.mark.parametrize(
    ("timestamps", "message"),
    [
        ((BASE, BASE), "duplicate candle timestamp"),
        ((BASE, BASE - timedelta(hours=4)), "non-monotonic candle timestamp"),
    ],
)
def test_duplicate_and_non_monotonic_timestamps_fail_closed(
    tmp_path: Path,
    timestamps: tuple[datetime, datetime],
    message: str,
) -> None:
    identity = AssetIdentity(asset_id=7, symbol="RENDER")
    conn = FakeConnection(
        candles={7: [candle_row(asset_id=7, open_ts=value) for value in timestamps]}
    )
    path = tmp_path / "canonical.csv"

    with pytest.raises(ValueError, match=message):
        export_source_candles(conn, identity=identity, csv_path=path)
    assert not path.exists()


def test_invalid_ohlc_fails_closed(tmp_path: Path) -> None:
    identity = AssetIdentity(asset_id=7, symbol="RENDER")
    conn = FakeConnection(
        candles={
            7: [
                candle_row(
                    asset_id=7,
                    open_ts=BASE,
                    open_price="100",
                    high_price="99",
                    low_price="90",
                    close_price="98",
                )
            ]
        }
    )
    path = tmp_path / "canonical.csv"

    with pytest.raises(ValueError, match="invalid OHLC"):
        export_source_candles(conn, identity=identity, csv_path=path)
    assert not path.exists()


def test_unexpected_scope_row_fails_closed(tmp_path: Path) -> None:
    identity = AssetIdentity(asset_id=7, symbol="RENDER")
    conn = FakeConnection(
        candles={7: [candle_row(asset_id=7, open_ts=BASE, venue="other")]}
    )
    path = tmp_path / "canonical.csv"

    with pytest.raises(ValueError, match="unexpected venue"):
        export_source_candles(conn, identity=identity, csv_path=path)
    assert not path.exists()


def test_empty_history_fails_closed(tmp_path: Path) -> None:
    identity = AssetIdentity(asset_id=7, symbol="RENDER")
    conn = FakeConnection(candles={7: []})
    path = tmp_path / "canonical.csv"

    with pytest.raises(RuntimeError, match="empty canonical history"):
        export_source_candles(conn, identity=identity, csv_path=path)
    assert not path.exists()


def test_zero_cycle_tracker_result_does_not_require_fabricated_ledger(tmp_path: Path) -> None:
    tracker_dir = tmp_path / "tracker"
    tracker_dir.mkdir()
    (tracker_dir / "latest_cycles.json").write_text("[]\n", encoding="utf-8")
    (tracker_dir / "summary.json").write_text('{"cycle_count":0}\n', encoding="utf-8")

    artifacts = collect_tracker_artifacts(tracker_dir, cycle_count=0)

    assert artifacts["summary.json"]["present"] is True
    assert artifacts["latest_cycles.json"]["present"] is True
    assert artifacts["cycle_ledger.jsonl"]["present"] is False
    assert artifacts["cycle_ledger.jsonl"]["sha256"] is None

    with pytest.raises(RuntimeError, match="expected tracker artifact missing"):
        collect_tracker_artifacts(tracker_dir, cycle_count=1)


def test_prepare_tracker_output_dir_removes_stale_append_only_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracker_dir = tmp_path / "tracker"
    tracker_dir.mkdir()
    (tracker_dir / "cycle_ledger.jsonl").write_text('{"cycle_id":"stale"}\n', encoding="utf-8")
    (tracker_dir / "summary.json").write_text('{"cycle_count":1}\n', encoding="utf-8")

    prepare_tracker_output_dir(tracker_dir)
    output = capsys.readouterr().out

    assert not tracker_dir.exists()
    assert "INFO reset_tracker_output" in output


def test_source_checkpoint_is_hash_bound_and_reloadable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    source_by_symbol = {}
    for asset_id, symbol in ((7, "RENDER"), (8, "TAO")):
        path = run_dir / symbol / "source" / "canonical_candles.csv"
        conn = FakeConnection(
            candles={asset_id: [candle_row(asset_id=asset_id, open_ts=BASE)]}
        )
        source_by_symbol[symbol] = export_source_candles(
            conn,
            identity=AssetIdentity(asset_id=asset_id, symbol=symbol),
            csv_path=path,
        )

    hashes = {"tracker.py": "abc123"}
    checkpoint = write_source_checkpoint(
        run_dir,
        run_id="resume-test",
        analysis_commit_sha="analysis-sha",
        tracker_source_commit_sha="tracker-sha",
        tracker_source_sha256=hashes,
        source_by_symbol=source_by_symbol,
    )
    identities, loaded, loaded_path = load_source_checkpoint(
        run_dir,
        run_id="resume-test",
        analysis_commit_sha="analysis-sha",
        tracker_source_commit_sha="tracker-sha",
        tracker_source_sha256=hashes,
    )

    assert loaded_path == checkpoint
    assert [identity.symbol for identity in identities] == ["RENDER", "TAO"]
    assert loaded["RENDER"].source_sha256 == source_by_symbol["RENDER"].source_sha256

    render_path = Path(loaded["RENDER"].source_csv)
    render_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        load_source_checkpoint(
            run_dir,
            run_id="resume-test",
            analysis_commit_sha="analysis-sha",
            tracker_source_commit_sha="tracker-sha",
            tracker_source_sha256=hashes,
        )


def test_periodic_heartbeat_emits_progress(capsys: pytest.CaptureFixture[str]) -> None:
    with periodic_heartbeat("tracker", interval_seconds=0.01, symbol="RENDER"):
        time.sleep(0.04)
    output = capsys.readouterr().out
    assert "HEARTBEAT tracker" in output
    assert "symbol=RENDER" in output
    assert "elapsed_seconds=" in output


def test_main_emits_exactly_one_finished_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        runner_module,
        "run",
        lambda **_kwargs: {
            "assets": [
                {
                    "symbol": "RENDER",
                    "source_row_count": 10,
                    "source_gap_count": 0,
                    "tracker_summary": {"cycle_count": 2},
                }
            ]
        },
    )

    rc = runner_module.main(
        ["--out-root", str(tmp_path), "--run-id", "lifecycle-success"]
    )
    output = capsys.readouterr().out
    lines = output.splitlines()
    terminals = terminal_lines(output)

    assert rc == 0
    assert lines[0].startswith("STARTED bullish_breathline_canonical_4h_v1 ")
    assert "mode=canonical_db_to_tracker" in lines[0]
    assert "workers=1" in lines[0]
    assert len(terminals) == 1
    assert terminals[0].startswith("FINISHED ")
    assert "broker_private_calls=0" in terminals[0]
    assert "broker_writes=0" in terminals[0]
    assert "order_submission=0" in terminals[0]
    assert "live_orders=0" in terminals[0]
    assert "decision_gate=none" in terminals[0]
    assert "execution_planner=none" in terminals[0]
    assert "executor=none" in terminals[0]
    assert lines[-1].startswith("FINISHED ")


def test_main_emits_exactly_one_failed_terminal_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fail(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(runner_module, "run", fail)
    rc = runner_module.main(
        ["--out-root", str(tmp_path), "--run-id", "lifecycle-failure"]
    )
    output = capsys.readouterr().out

    assert rc == 1
    assert len(terminal_lines(output)) == 1
    assert terminal_lines(output)[0].startswith("FAILED ")
    assert "error_type=RuntimeError" in terminal_lines(output)[0]
    assert "Traceback" not in output


def test_main_emits_exactly_one_interrupted_terminal_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def interrupt(**_kwargs: Any) -> dict[str, Any]:
        raise RunnerInterrupted("synthetic interrupt")

    monkeypatch.setattr(runner_module, "run", interrupt)
    rc = runner_module.main(
        ["--out-root", str(tmp_path), "--run-id", "lifecycle-interrupt"]
    )
    output = capsys.readouterr().out

    assert rc == 130
    assert len(terminal_lines(output)) == 1
    assert terminal_lines(output)[0].startswith("INTERRUPTED ")
    assert "Traceback" not in output


def test_run_id_is_safe_for_versioned_artifact_directory() -> None:
    assert validate_run_id("empirical-20260826T060000Z") == "empirical-20260826T060000Z"
    with pytest.raises(ValueError, match="run_id"):
        validate_run_id("../escape")
