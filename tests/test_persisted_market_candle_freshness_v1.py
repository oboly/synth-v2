from __future__ import annotations

from datetime import UTC, datetime

from src.operations.persisted_market_candle_freshness_v1 import (
    BLOCKED,
    FRESH,
    FUTURE,
    MALFORMED,
    MISSING,
    PASS,
    STALE,
    classify_persisted_candle_boundary,
    fetch_persisted_candle_boundary,
)


EXPECTED = datetime(2026, 7, 18, 12, tzinfo=UTC)


class _Cursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.sql = sql
        self.params = params

    def fetchone(self) -> dict[str, object]:
        return {"latest_close_ts_utc": EXPECTED.replace(tzinfo=None), "expected_close_row_count": 2}


class _Connection:
    def __init__(self) -> None:
        self.cursor_value = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_value


def test_fetch_is_one_select_with_no_write_statement() -> None:
    conn = _Connection()
    row = fetch_persisted_candle_boundary(
        conn,
        venue="BITVAVO",
        interval_code="4h",
        expected_close_ts_utc=EXPECTED,
    )
    sql = " ".join(conn.cursor_value.sql.upper().split())
    assert sql.startswith("SELECT ")
    for token in (" INSERT ", " UPDATE ", " DELETE ", " REPLACE "):
        assert token not in f" {sql} "
    assert conn.cursor_value.params == (EXPECTED.replace(tzinfo=None), "bitvavo", "4h")
    assert row["expected_close_row_count"] == 2


def test_exact_persisted_boundary_passes() -> None:
    result = classify_persisted_candle_boundary(
        {"latest_close_ts_utc": EXPECTED.replace(tzinfo=None), "expected_close_row_count": 3},
        expected_close_ts_utc=EXPECTED,
    )
    assert result.validation_result == PASS
    assert result.freshness_classification == FRESH
    assert result.is_fresh


def test_missing_stale_future_and_malformed_inputs_fail_closed() -> None:
    cases = (
        (None, MISSING),
        ({"latest_close_ts_utc": None, "expected_close_row_count": 0}, MISSING),
        ({"latest_close_ts_utc": datetime(2026, 7, 18, 8), "expected_close_row_count": 0}, STALE),
        ({"latest_close_ts_utc": datetime(2026, 7, 18, 16), "expected_close_row_count": 1}, FUTURE),
        ({"latest_close_ts_utc": "bad", "expected_close_row_count": 1}, MALFORMED),
        ({"latest_close_ts_utc": EXPECTED, "expected_close_row_count": "bad"}, MALFORMED),
    )
    for row, classification in cases:
        result = classify_persisted_candle_boundary(row, expected_close_ts_utc=EXPECTED)
        assert result.validation_result == BLOCKED
        assert result.freshness_classification == classification
        assert not result.is_fresh
