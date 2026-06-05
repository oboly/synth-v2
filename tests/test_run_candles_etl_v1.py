from __future__ import annotations

import ast
import io
from contextlib import redirect_stdout
from pathlib import Path

import src.etl.bitvavo.run_candles_etl as runner


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_runner_emits_started_progress_checkpoint_and_finished_summary() -> None:
    original_load_config = runner.load_config
    original_get_db_connection = runner.get_db_connection
    original_load_assets = runner.load_assets
    original_resolve_etl_module = runner.resolve_etl_module
    original_resolve_etl_callable = runner.resolve_etl_callable
    original_build_session = runner.build_session
    original_call_etl_function = runner.call_etl_function
    try:
        conn = _FakeConn()
        runner.load_config = lambda path: runner.EtlConfig(
            venue="bitvavo",
            quote_asset="EUR",
            intervals=["1w"],
            default_lookback={"1w": "8w"},
            batch_limit=10,
            timeout_seconds=20,
            sleep_seconds=0.0,
            raw={"etl": {}},
        )
        runner.get_db_connection = lambda: conn
        runner.load_assets = lambda _conn, quote_asset, wanted_symbols=None: [
            runner.AssetRow(asset_id=1, symbol="WLD", market="WLD-EUR")
        ]
        runner.resolve_etl_module = lambda: object()
        runner.resolve_etl_callable = lambda _module: object()
        runner.build_session = lambda _module: object()
        runner.call_etl_function = lambda *args, **kwargs: {"written_rows": 3}

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()
    finally:
        runner.load_config = original_load_config
        runner.get_db_connection = original_get_db_connection
        runner.load_assets = original_load_assets
        runner.resolve_etl_module = original_resolve_etl_module
        runner.resolve_etl_callable = original_resolve_etl_callable
        runner.build_session = original_build_session
        runner.call_etl_function = original_call_etl_function

    assert code == 0
    assert "STARTED run_candles_etl" in text
    assert "PHASE_STARTED load_assets" in text
    assert "QUERY_RESULT name=load_assets rows=1" in text
    assert "CHECKPOINT_WRITTEN market=WLD-EUR interval=1w rows=3" in text
    assert "PROGRESS run_candles_etl completed=1/1" in text
    assert "FINISHED run_candles_etl" in text
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.closed is True


def test_runner_has_no_forbidden_imports_or_order_strings() -> None:
    source = Path("src/etl/bitvavo/run_candles_etl.py").read_text(encoding="utf-8")
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
    test_runner_emits_started_progress_checkpoint_and_finished_summary()
    test_runner_has_no_forbidden_imports_or_order_strings()


if __name__ == "__main__":
    main()
