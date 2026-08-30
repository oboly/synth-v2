from __future__ import annotations

from datetime import UTC, datetime

from src.operations.persisted_market_candle_freshness_v1 import (
    BLOCKED,
    CURRENT,
    FRESH,
    FUTURE,
    MALFORMED,
    MISSING,
    PARTIAL_COVERAGE,
    PASS,
    SOURCE_UNAVAILABLE,
    STALE,
    WRITER_FAILED,
    classify_persisted_candle_boundary,
    classify_universe_candle_coverage,
    fetch_persisted_candle_boundary,
    fetch_universe_latest_close_by_symbol,
)
from src.operations.run_public_candle_coverage_health_check_v1 import (
    filter_enabled_symbols_to_active_markets,
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


# ---------------------------------------------------------------------------
# Whole-universe coverage classification (Issue #606 freshness contract).
# ---------------------------------------------------------------------------

LAG_1H = EXPECTED.replace(hour=EXPECTED.hour - 1)
LAG_2H = EXPECTED.replace(hour=EXPECTED.hour - 2)
FUTURE_1H = EXPECTED.replace(hour=EXPECTED.hour + 1)


class _UniverseCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> "_UniverseCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.sql = sql
        self.params = params

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _UniverseConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.cursor_value = _UniverseCursor(rows)

    def cursor(self) -> _UniverseCursor:
        return self.cursor_value


def test_fetch_universe_latest_close_is_one_select_with_no_write_statement() -> None:
    conn = _UniverseConnection(
        [{"symbol": "BTC", "latest_close_ts_utc": EXPECTED}, {"symbol": "ICP", "latest_close_ts_utc": LAG_1H}]
    )
    result = fetch_universe_latest_close_by_symbol(
        conn, venue="BITVAVO", interval_code="1h", symbols=["BTC", "ICP"]
    )
    sql = " ".join(conn.cursor_value.sql.upper().split())
    assert sql.startswith("SELECT ")
    for token in (" INSERT ", " UPDATE ", " DELETE ", " REPLACE "):
        assert token not in f" {sql} "
    assert conn.cursor_value.params == ("bitvavo", "1h", "BTC", "ICP")
    assert result == {"BTC": EXPECTED, "ICP": LAG_1H}


def test_fetch_universe_latest_close_empty_symbols_short_circuits() -> None:
    conn = _UniverseConnection([])
    assert fetch_universe_latest_close_by_symbol(conn, venue="bitvavo", interval_code="1h", symbols=[]) == {}


def test_writer_eligibility_excludes_enabled_but_inactive_market() -> None:
    symbols = filter_enabled_symbols_to_active_markets(
        enabled_symbols=["BTC", "ALMANAK", "ETH", "btc"],
        active_markets={"BTC-EUR", "ETH-EUR", "USDC-EUR"},
        quote_asset="eur",
    )
    assert symbols == ["BTC", "ETH"]


def test_universe_all_current_is_current() -> None:
    coverage = classify_universe_candle_coverage(
        interval_code="1h",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={"BTC": EXPECTED, "ETH": EXPECTED, "ICP": EXPECTED},
    )
    assert coverage.overall_state == CURRENT
    assert coverage.current_count == 3
    assert coverage.stale_count == 0
    assert coverage.missing_count == 0


def test_universe_future_boundary_fails_closed_not_current() -> None:
    coverage = classify_universe_candle_coverage(
        interval_code="1h",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={"BTC": FUTURE_1H, "ETH": FUTURE_1H, "ICP": FUTURE_1H},
    )
    assert coverage.overall_state == STALE
    assert coverage.current_count == 0
    assert coverage.stale_count == 3


def test_universe_isolated_lag_is_partial_coverage_not_writer_failed() -> None:
    """A healthy control set stays current while one symbol (ICP) lags --
    this must read as an isolated gap, not a systemic writer outage."""
    coverage = classify_universe_candle_coverage(
        interval_code="1h",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={"BTC": EXPECTED, "ETH": EXPECTED, "ICP": LAG_1H},
    )
    assert coverage.overall_state == PARTIAL_COVERAGE
    assert coverage.current_count == 2
    assert coverage.stale_count == 1
    assert coverage.dominant_lag_close_ts_utc == LAG_1H
    assert coverage.dominant_lag_symbol_count == 1


def test_universe_shared_stall_boundary_is_writer_failed() -> None:
    """Every symbol stalled at the identical prior boundary: the 2026-08-29
    incident signature (Issue #606) -- a producer/writer outage, not a
    per-market gap."""
    coverage = classify_universe_candle_coverage(
        interval_code="1h",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={"BTC": LAG_1H, "ETH": LAG_1H, "ICP": LAG_1H, "SOL": LAG_1H},
    )
    assert coverage.overall_state == WRITER_FAILED
    assert coverage.current_count == 0
    assert coverage.dominant_lag_close_ts_utc == LAG_1H
    assert coverage.dominant_lag_symbol_count == 4


def test_universe_tied_dominant_lag_uses_latest_timestamp_deterministically() -> None:
    coverage = classify_universe_candle_coverage(
        interval_code="1h",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={
            "BTC": LAG_2H,
            "ETH": LAG_1H,
            "ICP": LAG_2H,
            "SOL": LAG_1H,
        },
        writer_failed_dominance_ratio=0.75,
    )
    assert coverage.overall_state == STALE
    assert coverage.dominant_lag_symbol_count == 2
    assert coverage.dominant_lag_close_ts_utc == LAG_1H


def test_universe_no_dominant_boundary_without_current_symbols_is_stale() -> None:
    coverage = classify_universe_candle_coverage(
        interval_code="1h",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={
            "BTC": LAG_1H,
            "ETH": LAG_2H,
            "ICP": EXPECTED.replace(hour=EXPECTED.hour - 3),
        },
    )
    assert coverage.overall_state == STALE
    assert coverage.current_count == 0


def test_universe_all_missing_is_missing_not_current() -> None:
    """A missing interval must never silently read as current."""
    coverage = classify_universe_candle_coverage(
        interval_code="1w",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={"BTC": None, "ETH": None},
    )
    assert coverage.overall_state == MISSING
    assert coverage.current_count == 0


def test_universe_empty_symbol_set_is_source_unavailable() -> None:
    coverage = classify_universe_candle_coverage(
        interval_code="1h",
        expected_close_ts_utc=EXPECTED,
        symbol_latest_close={},
    )
    assert coverage.overall_state == SOURCE_UNAVAILABLE
    assert coverage.universe_size == 0
