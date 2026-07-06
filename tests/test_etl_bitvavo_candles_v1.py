from __future__ import annotations

import ast
import io
import os
from contextlib import redirect_stdout
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.etl.bitvavo import etl_bitvavo_candles as etl


class _FakeCursor:
    def __init__(self) -> None:
        self.executemany_calls: list[tuple[str, list[dict[str, object]]]] = []

    def executemany(self, sql: str, payload: list[dict[str, object]]) -> None:
        self.executemany_calls.append((sql, payload))

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeConn:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance


def test_floor_to_week_uses_utc_monday_boundary() -> None:
    assert etl.floor_to_interval(datetime(2026, 6, 3, 14, 27, tzinfo=UTC), "1w") == datetime(
        2026,
        6,
        1,
        0,
        0,
        tzinfo=UTC,
    )


def test_floor_to_week_handles_year_boundary() -> None:
    assert etl.floor_to_interval(datetime(2026, 1, 1, 12, 0, tzinfo=UTC), "1w") == datetime(
        2025,
        12,
        29,
        0,
        0,
        tzinfo=UTC,
    )


def test_parse_weekly_payload_sets_close_to_plus_seven_days() -> None:
    rows = etl.parse_bitvavo_payload(
        asset_id=1,
        venue="bitvavo",
        interval_code="1W",
        payload=[[1748822400000, "1.0", "2.0", "0.5", "1.5", "12.0"]],
    )
    assert rows[0].interval_code == "1w"
    assert rows[0].open_ts_utc == datetime(2025, 6, 2, 0, 0)
    assert rows[0].close_ts_utc == datetime(2025, 6, 9, 0, 0)


def test_run_market_interval_excludes_incomplete_current_week() -> None:
    captured_calls: list[tuple[int, int, str]] = []
    original_fetch = etl.fetch_bitvavo_candles
    try:
        etl.fetch_bitvavo_candles = lambda **kwargs: captured_calls.append(
            (kwargs["start_ms"], kwargs["end_ms"], kwargs["interval_code"])
        ) or [
            [1748217600000, "1.0", "2.0", "0.5", "1.5", "12.0"],
        ]
        result = etl.run_market_interval(
            conn=_FakeConn(),
            session=object(),
            asset_id=1,
            market="WLD-EUR",
            venue="bitvavo",
            interval_code="1w",
            start_dt=datetime(2025, 5, 20, 12, 0, tzinfo=UTC),
            end_dt=datetime(2025, 6, 5, 15, 0, tzinfo=UTC),
            dry_run=True,
        )
    finally:
        etl.fetch_bitvavo_candles = original_fetch

    assert result["written_rows"] == 0
    assert captured_calls == [
        (
            etl.dt_to_ms(datetime(2025, 5, 19, 0, 0, tzinfo=UTC)),
            etl.dt_to_ms(datetime(2025, 6, 2, 0, 0, tzinfo=UTC)),
            "1w",
        )
    ]


def _week_gap_rows() -> list[etl.CandleRow]:
    return [
        etl.CandleRow(
            asset_id=1,
            venue="bitvavo",
            interval_code="1w",
            open_ts_utc=datetime(2025, 5, 19, 0, 0),
            close_ts_utc=datetime(2025, 5, 26, 0, 0),
            open=Decimal("1.0"),
            high=Decimal("2.0"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10.0"),
        ),
        etl.CandleRow(
            asset_id=1,
            venue="bitvavo",
            interval_code="1w",
            open_ts_utc=datetime(2025, 6, 2, 0, 0),
            close_ts_utc=datetime(2025, 6, 9, 0, 0),
            open=Decimal("1.0"),
            high=Decimal("2.0"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10.0"),
        ),
    ]


def test_validate_chunk_rows_returns_gap_count_and_is_silent_by_default() -> None:
    """P0-A bounded logging: gap detection is always counted, but the
    per-gap print is gated behind debug_logging_enabled() so a production
    run over hundreds of assets does not emit one line per gap by default."""
    os.environ.pop(etl.DEBUG_ENV_VAR, None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        gap_count = etl.validate_chunk_rows(
            rows=_week_gap_rows(),
            market="WLD-EUR",
            asset_id=1,
            interval_code="1w",
            chunk_index=1,
            start_dt=datetime(2025, 5, 19, 0, 0, tzinfo=UTC),
            end_dt=datetime(2025, 6, 9, 0, 0, tzinfo=UTC),
        )
    assert gap_count == 1
    assert "intra-chunk gap detected" not in buf.getvalue()


def test_validate_chunk_rows_prints_gap_detail_in_debug_mode() -> None:
    os.environ[etl.DEBUG_ENV_VAR] = "1"
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            gap_count = etl.validate_chunk_rows(
                rows=_week_gap_rows(),
                market="WLD-EUR",
                asset_id=1,
                interval_code="1w",
                chunk_index=1,
                start_dt=datetime(2025, 5, 19, 0, 0, tzinfo=UTC),
                end_dt=datetime(2025, 6, 9, 0, 0, tzinfo=UTC),
            )
    finally:
        os.environ.pop(etl.DEBUG_ENV_VAR, None)
    assert gap_count == 1
    assert "intra-chunk gap detected" in buf.getvalue()


def test_upsert_weekly_candles_uses_idempotent_sql() -> None:
    conn = _FakeConn()
    rows = [
        etl.CandleRow(
            asset_id=1,
            venue="bitvavo",
            interval_code="1w",
            open_ts_utc=datetime(2025, 5, 19, 0, 0),
            close_ts_utc=datetime(2025, 5, 26, 0, 0),
            open=Decimal("1.0"),
            high=Decimal("2.0"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10.0"),
        )
    ]
    written = etl.upsert_candles(conn, rows)
    assert written == 1
    sql, payload = conn.cursor_instance.executemany_calls[0]
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert payload[0]["interval_code"] == "1w"
    assert payload[0]["volume_quote_eur"] == str(Decimal("15.00"))


def test_etl_module_has_no_forbidden_imports_or_order_strings() -> None:
    source = Path("src/etl/bitvavo/etl_bitvavo_candles.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {"decision_gate", "execution_planner", "executor"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in forbidden_imports:
                assert name not in module
    for forbidden in ("placeOrder", "cancelOrder", "create order"):
        assert forbidden not in source


def main() -> None:
    test_floor_to_week_uses_utc_monday_boundary()
    test_floor_to_week_handles_year_boundary()
    test_parse_weekly_payload_sets_close_to_plus_seven_days()
    test_run_market_interval_excludes_incomplete_current_week()
    test_validate_chunk_rows_returns_gap_count_and_is_silent_by_default()
    test_validate_chunk_rows_prints_gap_detail_in_debug_mode()
    test_upsert_weekly_candles_uses_idempotent_sql()
    test_etl_module_has_no_forbidden_imports_or_order_strings()


if __name__ == "__main__":
    main()
