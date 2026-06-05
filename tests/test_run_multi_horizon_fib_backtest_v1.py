from __future__ import annotations

import ast
import io
import json
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import src.research.run_multi_horizon_fib_backtest_v1 as runner
from src.research.multi_horizon_fib_contract_v1 import FibCheckpoint
from src.research.multi_horizon_fib_contract_v1 import Candle


def _candles(symbol: str, interval_code: str, count: int, step: timedelta) -> list[Candle]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows: list[Candle] = []
    for index in range(count):
        low = Decimal("10") + Decimal(index % 3)
        high = low + Decimal("4") + Decimal(index % 2)
        close = low + Decimal("2")
        open_ts = start + index * step
        rows.append(
            Candle(
                symbol=symbol,
                venue="bitvavo",
                quote="EUR",
                interval_code=interval_code,
                open_ts_utc=open_ts,
                close_ts_utc=open_ts + step,
                open_price=(high + low) / Decimal("2"),
                high_price=high,
                low_price=low,
                close_price=close,
            )
        )
    return rows


def test_valid_fixture_reports_outputs_and_helpful_summary() -> None:
    original_fetch_assets = runner.fetch_assets
    original_fetch_candles = runner.fetch_candles
    original_load_context_rows = runner.load_context_rows
    original_get_db_connection = runner.get_db_connection
    try:
        runner.get_db_connection = lambda: type("Conn", (), {"close": lambda self: None})()
        runner.fetch_assets = lambda conn, symbols, quote: [runner.AssetRef(asset_id=1, symbol="WLD")]
        runner.fetch_candles = lambda conn, assets, venue, quote, interval_codes, interval_start_filters, control: {
            "WLD": {
                "1h": _candles("WLD", "1h", 12, timedelta(hours=1)),
                "4h": _candles("WLD", "4h", 12, timedelta(hours=4)),
                "1d": _candles("WLD", "1d", 12, timedelta(days=1)),
                "1w": _candles("WLD", "1w", 12, timedelta(weeks=1)),
            }
        }
        runner.load_context_rows = lambda symbols: {symbol: [] for symbol in symbols}
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = runner.main(
                    [
                        "--mode",
                        "bootstrap",
                        "--symbols",
                        "WLD",
                        "--horizons",
                        "SHORT,MEDIUM,LONG",
                        "--write-files",
                        "--output",
                        "summary",
                        "--output-dir",
                        tmpdir,
                    ]
                )
            text = buf.getvalue()
            assert code == 0
            assert "STARTED run_multi_horizon_fib_backtest_v1" in text
            assert "FINISHED run_multi_horizon_fib_backtest_v1" in text
            assert "broker_writes=0" in text
            assert (Path(tmpdir) / "manifest_v1.json").exists()
    finally:
        runner.fetch_assets = original_fetch_assets
        runner.fetch_candles = original_fetch_candles
        runner.load_context_rows = original_load_context_rows
        runner.get_db_connection = original_get_db_connection


def test_parse_horizons_arg_rejects_invalid_value() -> None:
    try:
        runner.parse_horizons_arg("SHORT,WRONG")
    except ValueError as exc:
        assert "Unsupported horizons" in str(exc)
    else:
        raise AssertionError("invalid horizon must fail")


class _FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fetchmany_calls = 0
        self._position = 0

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return [{"Key_name": "ix_obs_market_candle"}]

    def fetchmany(self, size: int) -> list[dict[str, object]]:
        self.fetchmany_calls += 1
        batch = self.rows[self._position : self._position + size]
        self._position += len(batch)
        return batch

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeConn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.cursors: list[_FakeCursor] = []

    def cursor(self, *args, **kwargs) -> _FakeCursor:
        cursor = _FakeCursor(self.rows)
        self.cursors.append(cursor)
        return cursor


def test_fetch_candles_uses_bounded_fetchmany_and_start_ts_filter() -> None:
    row = {
        "asset_id": 1,
        "symbol": "WLD",
        "venue": "bitvavo",
        "interval_code": "4h",
        "open_ts_utc": datetime(2025, 1, 1, tzinfo=UTC),
        "close_ts_utc": datetime(2025, 1, 1, 4, tzinfo=UTC),
        "open_price": "10",
        "high_price": "12",
        "low_price": "9",
        "close_price": "11",
    }
    conn = _FakeConn([row])
    control = runner.RunControl()
    start_ts = datetime(2025, 1, 1, tzinfo=UTC)
    result = runner.fetch_candles(
        conn,
        assets=[runner.AssetRef(asset_id=1, symbol="WLD")],
        venue="bitvavo",
        quote="EUR",
        interval_codes=["4h"],
        interval_start_filters={("WLD", "4h"): start_ts},
        control=control,
    )
    assert result["WLD"]["4h"][0].close_price == Decimal("11")
    candle_cursor = conn.cursors[-1]
    sql, params = candle_cursor.executed[0]
    assert "close_ts_utc >= %s" in sql
    assert params[-1] == start_ts.replace(tzinfo=None)
    assert candle_cursor.fetchmany_calls > 0


def test_compute_interval_start_filters_uses_checkpoint_minus_overlap() -> None:
    checkpoint = FibCheckpoint(
        symbol="WLD",
        venue="bitvavo",
        quote="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_intervals=["1h"],
        analysis_version="1.0",
        algorithm_version="1.0",
        parameter_profile_id="default_v1",
        last_processed_primary_close_ts="2025-01-10T12:00:00Z",
        last_processed_support_close_ts="2025-01-10T13:00:00Z",
        last_confirmed_pivot_ts=None,
        active_swing_id=None,
        active_swing_low=None,
        active_swing_high=None,
        active_swing_low_ts=None,
        active_swing_high_ts=None,
        active_swing_state=None,
        active_fib_levels={},
        completed_swing_count=0,
        overlap_candles=8,
        updated_ts="2025-01-10T12:00:00Z",
        source_refs={},
    )
    filters = runner.compute_interval_start_filters(
        assets=[runner.AssetRef(asset_id=1, symbol="WLD")],
        horizons=["SHORT"],
        mode="incremental",
        overlap_candles=2,
        checkpoint_cache={("WLD", "SHORT"): checkpoint},
    )
    assert filters[("WLD", "4h")] == datetime(2025, 1, 10, 4, tzinfo=UTC)
    assert filters[("WLD", "1h")] == datetime(2025, 1, 10, 11, tzinfo=UTC)


def test_runner_has_no_forbidden_imports_or_order_strings() -> None:
    source = Path("src/research/run_multi_horizon_fib_backtest_v1.py").read_text(encoding="utf-8")
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
    test_valid_fixture_reports_outputs_and_helpful_summary()
    test_parse_horizons_arg_rejects_invalid_value()
    test_fetch_candles_uses_bounded_fetchmany_and_start_ts_filter()
    test_compute_interval_start_filters_uses_checkpoint_minus_overlap()
    test_runner_has_no_forbidden_imports_or_order_strings()
    print("ok")


if __name__ == "__main__":
    main()
