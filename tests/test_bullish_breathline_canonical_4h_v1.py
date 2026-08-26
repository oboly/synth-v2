from __future__ import annotations

import csv
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pymysql.cursors import SSDictCursor

from src.research.run_bullish_breathline_canonical_4h_v1 import (
    FETCH_BATCH_ROWS,
    INTERVAL_CODE,
    VENUE,
    AssetIdentity,
    begin_read_only_transaction,
    collect_tracker_artifacts,
    export_source_candles,
    resolve_asset_identity,
    sha256_file,
    validate_run_id,
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
        if compact == "START TRANSACTION READ ONLY":
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


def test_begin_read_only_transaction_is_explicit() -> None:
    conn = FakeConnection()
    begin_read_only_transaction(conn)
    assert conn.executed == [("START TRANSACTION READ ONLY", None)]


def test_resolve_asset_identity_requires_single_frozen_identity() -> None:
    conn = FakeConnection(assets={"RENDER": [{"asset_id": 7, "symbol": "RENDER"}]})
    assert resolve_asset_identity(conn, "render") == AssetIdentity(asset_id=7, symbol="RENDER")

    with pytest.raises(ValueError, match="outside frozen"):
        resolve_asset_identity(conn, "BTC")

    missing = FakeConnection()
    with pytest.raises(RuntimeError, match="exactly one canonical asset identity"):
        resolve_asset_identity(missing, "RENDER")


def test_export_streams_and_maps_open_ts_to_tracker_ts(tmp_path: Path) -> None:
    identity = AssetIdentity(asset_id=7, symbol="RENDER")
    rows = [
        candle_row(asset_id=7, open_ts=BASE + timedelta(hours=offset))
        for offset in (0, 4, 8, 12, 16)
    ]
    conn = FakeConnection(candles={7: rows})
    path = tmp_path / "canonical.csv"

    result = export_source_candles(conn, identity=identity, csv_path=path)
    exported = read_csv(path)

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


def test_run_id_is_safe_for_versioned_artifact_directory() -> None:
    assert validate_run_id("empirical-20260826T060000Z") == "empirical-20260826T060000Z"
    with pytest.raises(ValueError, match="run_id"):
        validate_run_id("../escape")
