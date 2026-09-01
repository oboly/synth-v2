from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.research.run_multi_horizon_rotation_source_integrity_v1 import (
    build_integrity_payload,
    canonical_row_bytes,
    hash_rows,
    persist_write_once,
    verify_existing,
)


class FakeCursor:
    def __init__(self, rows_by_query: list[list[dict[str, Any]]]) -> None:
        self.rows_by_query = rows_by_query
        self.rows: list[dict[str, Any]] = []
        self.offset = 0
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.execute_calls.append((sql, params))
        self.rows = self.rows_by_query.pop(0)
        self.offset = 0

    def fetchmany(self, size: int) -> list[dict[str, Any]]:
        batch = self.rows[self.offset : self.offset + size]
        self.offset += len(batch)
        return batch


class FakeConnection:
    def __init__(self, rows_by_query: list[list[dict[str, Any]]]) -> None:
        self.cursor_impl = FakeCursor(rows_by_query)

    def cursor(self) -> FakeCursor:
        return self.cursor_impl


def _manifest() -> dict[str, object]:
    return {
        "manifest_version": "1.0.0",
        "venue": "bitvavo",
        "source_span": {
            "start": "2026-07-13T22:00:00Z",
            "end": "2026-09-01T02:00:00Z",
        },
        "splits": {
            "discovery": {
                "start": "2026-07-13T22:00:00Z",
                "end": "2026-08-12T10:00:00Z",
            },
            "validation": {
                "start": "2026-08-12T10:00:00Z",
                "end": "2026-08-22T06:00:00Z",
            },
            "final_holdout": {
                "start": "2026-08-22T06:00:00Z",
                "end": "2026-09-01T02:00:00Z",
            },
        },
        "final_holdout_inspected": False,
    }


def test_canonical_row_bytes_is_stable_for_decimal_and_timestamp() -> None:
    row = {
        "asset_id": 7,
        "ts": datetime(2026, 8, 1, 12, 15, tzinfo=UTC),
        "price": Decimal("1.2300"),
        "state": "ROTATION_IN",
    }
    assert canonical_row_bytes(row, ("asset_id", "ts", "price", "state")) == (
        b'[7,"2026-08-01T12:15:00Z","1.2300","ROTATION_IN"]\n'
    )


def test_hash_rows_is_order_sensitive_and_deterministic() -> None:
    rows = [
        {"asset_id": 1, "value": Decimal("1.0")},
        {"asset_id": 2, "value": Decimal("2.0")},
    ]
    fields = ("asset_id", "value")
    first = hash_rows(rows, fields)
    second = hash_rows(list(rows), fields)
    reversed_hash = hash_rows(list(reversed(rows)), fields)
    assert first == second
    assert first[1] == 2
    assert reversed_hash[0] != first[0]


def test_build_integrity_payload_hashes_exact_source_union() -> None:
    candle_rows = [
        {
            "asset_id": 1,
            "close_ts_utc": datetime(2026, 7, 12, 10, 0),
            "close_price": Decimal("1.25"),
            "volume_base": Decimal("10.0"),
        }
    ]
    rotation_rows = [
        {
            "pressure_obs_id": 11,
            "pressure_snapshot_id": 5,
            "asset_id": 1,
            "as_of_ts_utc": datetime(2026, 7, 13, 21, 45),
            "score_total": Decimal("-12.5"),
            "pressure_state": "ROTATION_OUT",
            "observation_model_version": "1.0",
            "snapshot_as_of_ts_utc": datetime(2026, 7, 13, 21, 45),
            "snapshot_model_version": "1.0",
        }
    ]
    conn = FakeConnection([candle_rows, rotation_rows])

    payload = build_integrity_payload(
        conn,
        venue="bitvavo",
        split_manifest=_manifest(),
        batch_size=1,
    )

    assert payload["candles"]["row_count"] == 1
    assert payload["rotation_v1"]["row_count"] == 1
    assert payload["final_holdout_outcomes_inspected"] is False
    assert len(str(payload["composite_sha256"])) == 64

    candle_sql, candle_params = conn.cursor_impl.execute_calls[0]
    assert "close_ts_utc >= %s" in candle_sql
    assert "close_ts_utc < %s" in candle_sql
    assert candle_params[1] == datetime(2026, 7, 12, 10, 0)
    assert candle_params[2] == datetime(2026, 9, 1, 2, 0)

    rotation_sql, rotation_params = conn.cursor_impl.execute_calls[1]
    assert "o.as_of_ts_utc < %s" in rotation_sql
    assert rotation_params[-1] == datetime(2026, 9, 1, 2, 0)


def test_write_once_freeze_and_verify_detects_drift(tmp_path: Path) -> None:
    path = tmp_path / "source_integrity_v1.json"
    payload = {"composite_sha256": "abc", "final_holdout_outcomes_inspected": False}

    assert persist_write_once(path, payload) == "FROZEN"
    assert persist_write_once(path, payload) == "VERIFIED_EXISTING"
    verify_existing(path, payload)

    changed = dict(payload)
    changed["composite_sha256"] = "def"
    with pytest.raises(ValueError, match="differs from frozen write-once artifact"):
        persist_write_once(path, changed)
    with pytest.raises(ValueError, match="content drifted"):
        verify_existing(path, changed)

    assert json.loads(path.read_text()) == payload
