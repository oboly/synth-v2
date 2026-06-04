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
        runner.fetch_candles = lambda conn, assets, venue, quote, interval_codes: {
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
    test_runner_has_no_forbidden_imports_or_order_strings()
    print("ok")


if __name__ == "__main__":
    main()
