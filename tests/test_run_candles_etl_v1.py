from __future__ import annotations

import ast
import contextlib
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import src.etl.bitvavo.run_candles_etl as runner


@pytest.fixture(autouse=True)
def _authorized_writer_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise ETL run/observability mechanics and assume the
    public_candle_freshness capability is already authorized. The unconditional
    writer-capability authorization boundary itself is covered by
    tests/test_writer_capability_authorization_v1.py."""
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod, "require_capability_write_authorization", lambda *a, **k: None
    )


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


@contextlib.contextmanager
def _patched_runner(*, asset_count: int, call_etl_result):
    """Patch runner's DB/config/asset-loading/ETL-call seams with fakes so
    main() can be exercised end-to-end without a real DB or network call.

    call_etl_result may be a dict (returned for every task) or a callable
    taking the same kwargs as call_etl_function and returning a dict, so
    tests can vary the result per asset (e.g. to vary gap_warnings).
    """
    originals = {
        "load_config": runner.load_config,
        "get_db_connection": runner.get_db_connection,
        "load_assets": runner.load_assets,
        "resolve_etl_module": runner.resolve_etl_module,
        "resolve_etl_callable": runner.resolve_etl_callable,
        "build_session": runner.build_session,
        "call_etl_function": runner.call_etl_function,
    }
    conn = _FakeConn()
    assets = [
        runner.AssetRow(asset_id=i, symbol=f"SYM{i}", market=f"SYM{i}-EUR")
        for i in range(1, asset_count + 1)
    ]
    try:
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
        runner.load_assets = lambda _conn, quote_asset, wanted_symbols=None: assets
        runner.resolve_etl_module = lambda: object()
        runner.resolve_etl_callable = lambda _module: object()
        runner.build_session = lambda _module: object()
        if callable(call_etl_result) and not isinstance(call_etl_result, dict):
            runner.call_etl_function = call_etl_result
        else:
            runner.call_etl_function = lambda *args, **kwargs: dict(call_etl_result)
        yield conn
    finally:
        for name, value in originals.items():
            setattr(runner, name, value)
        os.environ.pop("SYNTH_CANDLES_ETL_DEBUG", None)
        os.environ.pop("SYNTH_CANDLES_ETL_PROGRESS_EVERY", None)
        os.environ.pop("SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH", None)


def test_runner_emits_started_progress_checkpoint_and_finished_summary() -> None:
    with _patched_runner(asset_count=1, call_etl_result={"written_rows": 3}) as conn:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    assert code == 0
    assert "STARTED run_candles_etl" in text
    assert "intervals=1w" in text.splitlines()[0]
    assert "RUN_CONTEXT run_candles_etl resolved_intervals=1w" in text
    assert "PHASE_STARTED load_assets" in text
    assert "QUERY_RESULT name=load_assets rows=1" in text
    assert "PROGRESS run_candles_etl completed=1/1" in text
    assert "checkpoint_state_path=" in text
    assert "latest_checkpoint=SYM1-EUR:1w@1/1:rows=3:gaps=0" in text
    assert "raw_payload_rows=0 accepted_rows=0 dropped_rows=0" in text
    assert "FINISHED run_candles_etl" in text
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.closed is True


def test_started_is_emitted_before_config_failure_and_failed_summary_is_unique() -> None:
    originals = {
        "load_config": runner.load_config,
        "get_db_connection": runner.get_db_connection,
    }
    try:
        runner.load_config = lambda _path: (_ for _ in ()).throw(FileNotFoundError("missing config"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()
    finally:
        for name, value in originals.items():
            setattr(runner, name, value)
        os.environ.pop("SYNTH_CANDLES_ETL_DEBUG", None)
        os.environ.pop("SYNTH_CANDLES_ETL_PROGRESS_EVERY", None)
        os.environ.pop("SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH", None)

    lines = text.splitlines()
    assert code == 1
    assert lines[0].startswith("STARTED run_candles_etl ")
    assert lines[-1].startswith("FAILED run_candles_etl ")
    assert text.count("FAILED run_candles_etl ") == 1


def test_bounded_default_mode_suppresses_per_task_chatter_and_heartbeats() -> None:
    """P0-A: with many enabled assets (verified production measurement: 429
    enabled assets at incident-follow-up time), default logging must not
    emit one PHASE_STARTED/CHECKPOINT_WRITTEN/PROGRESS line per asset. It
    must instead emit a bounded heartbeat: first task, every Nth task, and
    the last task."""
    with _patched_runner(
        asset_count=120, call_etl_result={"written_rows": 1, "gap_warnings": 0}
    ):
        os.environ["SYNTH_CANDLES_ETL_PROGRESS_EVERY"] = "50"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    assert code == 0
    assert "logging_mode=bounded" in text
    # No per-task phase-start chatter at all in bounded mode.
    assert "PHASE_STARTED market_interval" not in text
    assert "PHASE_FINISHED market_interval" not in text
    # Heartbeat fires at completed=1, 50, 100, and the final task (120).
    progress_lines = [line for line in text.splitlines() if line.startswith("PROGRESS run_candles_etl")]
    assert len(progress_lines) == 4, progress_lines
    assert "completed=1/120" in progress_lines[0]
    assert "completed=50/120" in progress_lines[1]
    assert "completed=100/120" in progress_lines[2]
    assert "completed=120/120" in progress_lines[3]
    checkpoint_lines = [line for line in text.splitlines() if line.startswith("CHECKPOINT_WRITTEN")]
    assert checkpoint_lines == []
    assert "latest_checkpoint=SYM120-EUR:1w@120/120:rows=1:gaps=0" in text
    assert "FINISHED run_candles_etl" in text
    assert "task_count=120" in text
    assert "total_rows=120" in text
    assert "raw_payload_rows=0 accepted_rows=0 dropped_rows=0" in text


def test_debug_mode_preserves_full_per_task_detail() -> None:
    """--debug-logging must restore exactly the original fully-verbose
    per-task behavior for manual debugging."""
    with _patched_runner(
        asset_count=5, call_etl_result={"written_rows": 1, "gap_warnings": 0}
    ):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w", "--debug-logging"])
        text = buf.getvalue()

    assert code == 0
    assert "logging_mode=debug" in text
    assert text.count("PHASE_STARTED market_interval") == 5
    assert text.count("PHASE_FINISHED market_interval") == 5
    assert text.count("CHECKPOINT_WRITTEN") == 5
    assert text.count("PROGRESS run_candles_etl") == 5


def test_debug_env_var_has_same_effect_as_cli_flag() -> None:
    os.environ["SYNTH_CANDLES_ETL_DEBUG"] = "1"
    try:
        with _patched_runner(
            asset_count=3, call_etl_result={"written_rows": 1, "gap_warnings": 0}
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = runner.main(["--interval", "1w"])
            text = buf.getvalue()
    finally:
        os.environ.pop("SYNTH_CANDLES_ETL_DEBUG", None)

    assert code == 0
    assert "logging_mode=debug" in text
    assert text.count("PHASE_STARTED market_interval") == 3


def test_gap_warnings_are_aggregated_in_progress_and_finished_lines() -> None:
    """Per-asset gap_warnings returned by the ETL callable must be summed
    into a single running total, not reported as N separate lines."""

    def fake_call(_etl_fn, *, asset, **_kwargs):
        # Two of five assets report 2 gaps each; total should be 4.
        gaps = 2 if asset.asset_id in (1, 3) else 0
        return {"written_rows": 1, "gap_warnings": gaps}

    with _patched_runner(asset_count=5, call_etl_result=fake_call):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w", "--debug-logging"])
        text = buf.getvalue()

    assert code == 0
    assert "gap_warnings_total=4" in text


def test_quality_aggregates_are_summed_in_progress_and_finished_lines() -> None:
    def fake_call(_etl_fn, *, asset, **_kwargs):
        return {
            "written_rows": 1,
            "gap_warnings": 0,
            "raw_payload_rows": 5,
            "accepted_rows": 3,
            "dropped_rows": 2,
        }

    with _patched_runner(asset_count=4, call_etl_result=fake_call):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w", "--debug-logging"])
        text = buf.getvalue()

    assert code == 0
    assert "raw_payload_rows=20" in text
    assert "accepted_rows=12" in text
    assert "dropped_rows=8" in text


def test_each_successful_commit_updates_checkpoint_state_between_heartbeats(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "runtime" / "last_checkpoint.json"
    os.environ["SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH"] = str(checkpoint_path)
    with _patched_runner(
        asset_count=120, call_etl_result={"written_rows": 1, "gap_warnings": 0}
    ) as conn:
        os.environ["SYNTH_CANDLES_ETL_PROGRESS_EVERY"] = "50"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert code == 0
    assert conn.commits == 120
    assert payload["status"] == "committed"
    assert payload["market"] == "SYM120-EUR"
    assert payload["interval"] == "1w"
    assert payload["completed"] == 120
    assert payload["total"] == 120
    assert payload["rows_written"] == 1
    assert payload["skipped"] == 0
    assert payload["gap_warnings"] == 0
    assert f"checkpoint_state_path={checkpoint_path}" in text
    assert "latest_checkpoint=SYM120-EUR:1w@120/120:rows=1:gaps=0" in text


def test_failure_retains_exact_final_successful_checkpoint(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "runtime" / "last_checkpoint.json"
    os.environ["SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH"] = str(checkpoint_path)

    def fake_call(_etl_fn, *, asset, **_kwargs):
        if asset.asset_id == 3:
            raise RuntimeError("boom")
        return {"written_rows": asset.asset_id, "gap_warnings": asset.asset_id - 1}

    with _patched_runner(asset_count=5, call_etl_result=fake_call) as conn:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert code == 1
    assert conn.commits == 2
    assert conn.rollbacks == 1
    assert payload["market"] == "SYM2-EUR"
    assert payload["completed"] == 2
    assert payload["rows_written"] == 2
    assert payload["gap_warnings"] == 1
    assert payload["status"] == "committed"
    assert f"checkpoint_state_path={checkpoint_path}" in text
    assert "latest_checkpoint=SYM2-EUR:1w@2/5:rows=2:gaps=1" in text
    assert "FAILED run_candles_etl" in text


def test_interruption_retains_exact_final_successful_checkpoint(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "runtime" / "last_checkpoint.json"
    os.environ["SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH"] = str(checkpoint_path)

    def fake_call(_etl_fn, *, asset, **_kwargs):
        if asset.asset_id == 3:
            raise KeyboardInterrupt("SIGINT")
        return {"written_rows": 1, "gap_warnings": 0}

    with _patched_runner(asset_count=5, call_etl_result=fake_call) as conn:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert code == 130
    assert conn.commits == 2
    assert conn.rollbacks == 1
    assert payload["market"] == "SYM2-EUR"
    assert payload["completed"] == 2
    assert payload["status"] == "committed"
    assert "INTERRUPTED run_candles_etl" in text
    assert "latest_checkpoint=SYM2-EUR:1w@2/5:rows=1:gaps=0" in text


def test_checkpoint_json_preserves_unknown_rows_written(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "runtime" / "last_checkpoint.json"
    with _patched_runner(asset_count=1, call_etl_result={"gap_warnings": 0}) as conn:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(
                ["--interval", "1w", "--checkpoint-state-path", str(checkpoint_path)]
            )
        text = buf.getvalue()

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert code == 0
    assert conn.commits == 1
    assert payload["rows_written"] is None
    assert "latest_checkpoint=SYM1-EUR:1w@1/1:rows=unknown:gaps=0" in text


def test_cli_checkpoint_state_path_overrides_env(tmp_path: Path) -> None:
    env_path = tmp_path / "env.json"
    cli_path = tmp_path / "cli.json"
    os.environ["SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH"] = str(env_path)
    with _patched_runner(asset_count=1, call_etl_result={"written_rows": 1}) as conn:
        code = runner.main(
            ["--interval", "1w", "--checkpoint-state-path", str(cli_path)]
        )
    assert code == 0
    assert conn.commits == 1
    assert cli_path.exists()
    assert not env_path.exists()


def test_default_checkpoint_state_path_is_scope_and_interval_specific() -> None:
    args = runner.parse_args(
        [
            "--config",
            "configs/etl_bitvavo_candles.yaml",
            "--asset",
            "BTC",
            "--asset",
            "ETH",
            "--interval",
            "1h",
            "--interval",
            "4h",
        ]
    )
    path = runner.resolve_checkpoint_state_path(
        args=args,
        intervals=["1h", "4h"],
        wanted_symbols={"BTC", "ETH"},
    )
    normalized, digest = runner._normalized_config_path_identity("configs/etl_bitvavo_candles.yaml")
    config_slug = runner._slugify_checkpoint_component(normalized)
    assert path == Path(
        "/tmp/synth_runtime/"
        f"run_candles_etl__config-{config_slug}-{digest}__intervals-1h-4h__scope-BTC-ETH.json"
    )


def test_default_checkpoint_state_path_does_not_collide_for_same_basename() -> None:
    args_one = runner.parse_args(["--config", "configs/etl/candles.yaml", "--interval", "1h"])
    args_two = runner.parse_args(["--config", "other/candles.yaml", "--interval", "1h"])
    path_one = runner.resolve_checkpoint_state_path(
        args=args_one,
        intervals=["1h"],
        wanted_symbols=None,
    )
    path_two = runner.resolve_checkpoint_state_path(
        args=args_two,
        intervals=["1h"],
        wanted_symbols=None,
    )
    assert path_one != path_two
    assert path_one.name.startswith("run_candles_etl__config-configs-etl-candles.yaml-")
    assert path_two.name.startswith("run_candles_etl__config-other-candles.yaml-")


def test_checkpoint_artifact_writes_are_atomic(tmp_path: Path, monkeypatch) -> None:
    checkpoint_path = tmp_path / "runtime" / "last_checkpoint.json"
    os.environ["SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH"] = str(checkpoint_path)
    replace_calls: list[tuple[str, str]] = []
    fsync_dirs: list[Path] = []
    original_replace = runner.os.replace

    def fake_replace(src, dst):
        replace_calls.append((str(src), str(dst)))
        assert str(src) != str(dst)
        assert Path(src).exists()
        original_replace(src, dst)

    monkeypatch.setattr(runner.os, "replace", fake_replace)
    monkeypatch.setattr(runner, "_fsync_directory", lambda path: fsync_dirs.append(path))
    with _patched_runner(asset_count=3, call_etl_result={"written_rows": 1, "gap_warnings": 0}) as conn:
        code = runner.main(["--interval", "1w"])

    assert code == 0
    assert conn.commits == 3
    assert len(replace_calls) == 3
    assert all(dst == str(checkpoint_path) for _, dst in replace_calls)
    assert fsync_dirs == [checkpoint_path.parent, checkpoint_path.parent, checkpoint_path.parent]
    assert checkpoint_path.exists()
    leftovers = [p for p in checkpoint_path.parent.iterdir() if p.name != checkpoint_path.name]
    assert leftovers == []


def test_checkpoint_write_failure_preserves_prior_valid_artifact(tmp_path: Path, monkeypatch) -> None:
    checkpoint_path = tmp_path / "runtime" / "last_checkpoint.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text('{"status":"prior","rows_written":7}\n', encoding="utf-8")
    os.environ["SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH"] = str(checkpoint_path)
    monkeypatch.setattr(runner.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))

    with _patched_runner(asset_count=1, call_etl_result={"written_rows": 1}) as conn:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    assert code == 1
    assert conn.commits == 1
    assert checkpoint_path.read_text(encoding="utf-8") == '{"status":"prior","rows_written":7}\n'
    assert "FAILED run_candles_etl" in text


def test_dry_run_does_not_claim_db_checkpoint_write(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "runtime" / "last_checkpoint.json"
    os.environ["SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH"] = str(checkpoint_path)
    with _patched_runner(asset_count=3, call_etl_result={"written_rows": 1, "gap_warnings": 0}) as conn:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w", "--dry-run"])
        text = buf.getvalue()

    assert code == 0
    assert conn.commits == 0
    assert "CHECKPOINT_WRITTEN" not in text
    assert "latest_checkpoint=none" in text
    assert not checkpoint_path.exists()


def test_inactive_markets_aggregated_by_default_not_one_line_each() -> None:
    """filter_active_markets skip lines must be aggregated into one bounded
    line in default mode, with full per-market detail only in debug mode."""

    class _ModuleWithActiveFilter:
        @staticmethod
        def fetch_active_bitvavo_markets(*, session, timeout_seconds):
            # Only SYM1-EUR is active; the rest are inactive/delisted.
            return {"SYM1-EUR"}

    with _patched_runner(
        asset_count=15, call_etl_result={"written_rows": 1, "gap_warnings": 0}
    ):
        runner.resolve_etl_module = lambda: _ModuleWithActiveFilter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    assert code == 0
    assert "SKIPPED_MARKET market=" not in text  # no per-market lines by default
    assert "SKIPPED_MARKETS_INACTIVE count=14" in text


def test_unavailable_markets_are_aggregated_in_bounded_mode() -> None:
    def fake_call(_etl_fn, *, asset, interval_code, **_kwargs):
        raise runner.MarketUnavailableError(
            market=asset.market,
            interval_code=interval_code,
            http_status=404,
        )

    with _patched_runner(asset_count=12, call_etl_result=fake_call):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    assert code == 0
    assert "SKIPPED_MARKET_ERROR market=" not in text
    assert "unavailable_market_errors=12" in text
    assert "unavailable_market_sample=[SYM1-EUR:1w@404" in text
    assert "(+7 more)]" in text


def test_unavailable_markets_debug_mode_preserves_detail() -> None:
    def fake_call(_etl_fn, *, asset, interval_code, **_kwargs):
        raise runner.MarketUnavailableError(
            market=asset.market,
            interval_code=interval_code,
            http_status=400,
        )

    with _patched_runner(asset_count=2, call_etl_result=fake_call):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w", "--debug-logging"])
        text = buf.getvalue()

    assert code == 0
    assert text.count("SKIPPED_MARKET_ERROR market=") == 2


def test_large_unavailable_market_run_output_remains_bounded() -> None:
    def fake_call(_etl_fn, *, asset, interval_code, **_kwargs):
        raise runner.MarketUnavailableError(
            market=asset.market,
            interval_code=interval_code,
            http_status=404,
        )

    with _patched_runner(asset_count=250, call_etl_result=fake_call):
        os.environ["SYNTH_CANDLES_ETL_PROGRESS_EVERY"] = "50"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = runner.main(["--interval", "1w"])
        text = buf.getvalue()

    assert code == 0
    progress_lines = [line for line in text.splitlines() if line.startswith("PROGRESS run_candles_etl")]
    assert len(progress_lines) == 6
    assert "unavailable_market_errors=250" in text
    assert text.count("SKIPPED_MARKET_ERROR market=") == 0


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
    test_bounded_default_mode_suppresses_per_task_chatter_and_heartbeats()
    test_debug_mode_preserves_full_per_task_detail()
    test_debug_env_var_has_same_effect_as_cli_flag()
    test_gap_warnings_are_aggregated_in_progress_and_finished_lines()
    test_inactive_markets_aggregated_by_default_not_one_line_each()
    test_runner_has_no_forbidden_imports_or_order_strings()


if __name__ == "__main__":
    main()
