"""Tests for Issue #707 Phase C: the read-only DB replay runner wrapped
around the frozen Phase B PIT engine.

Covers the Phase C required test groups for the runner:
    - query is SELECT-only
    - exact five assets
    - exact three windows
    - deterministic candle ordering
    - duplicate candle rejection
    - missing asset/window fail closed
    - selection and OOS structurally separated
    - frozen grid cannot be overridden (no CLI override surface)
    - no forbidden architecture imports/writes

No DB access is made by this test module; DB interaction points are
exercised with fake connection/cursor objects.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research import fib_exit_ladder_v1_pit_replay_engine_v1 as engine
from src.research import run_fib_exit_ladder_v1_pit_replay_v1 as runner

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "src/research/run_fib_exit_ladder_v1_pit_replay_v1.py"

FORBIDDEN_IMPORT_SUBSTRINGS = (
    "decision_gate",
    "execution_planner",
    "executor",
    "account",
    "broker",
    "order",
)


# ---------------------------------------------------------------------------
# Frozen universe / windows / grid: exact values, no override surface.
# ---------------------------------------------------------------------------


def test_exact_five_assets():
    assert runner.REQUIRED_ASSET_UNIVERSE == ("LINK", "XLM", "SOL", "XRP", "HOT")


def test_exact_three_windows():
    labels = [label for label, _ in runner.WINDOWS]
    assert labels == ["SELECTION_WINDOW", "OOS_WINDOW_1", "OOS_WINDOW_2"]

    bounds_by_label = dict(runner.WINDOWS)
    assert bounds_by_label["SELECTION_WINDOW"] == ("2020-01-01 00:00:00", "2022-01-01 00:00:00")
    assert bounds_by_label["OOS_WINDOW_1"] == ("2022-01-01 00:00:00", "2024-01-01 00:00:00")
    assert bounds_by_label["OOS_WINDOW_2"] == ("2024-01-01 00:00:00", "2026-09-01 00:00:00")


def test_venue_and_interval_frozen():
    assert runner.VENUE == "bitvavo"
    assert runner.INTERVAL_CODE == "1d"


def test_frozen_grid_cannot_be_overridden_via_cli():
    args = runner.parse_args(["--output-dir", "/tmp/whatever"])
    provided = vars(args)
    forbidden_flags = {
        "symbols",
        "target_family",
        "max_ladder_sell_fraction",
        "from_ts",
        "to_ts",
        "venue",
        "interval",
        "candidate_families",
        "sell_fraction_grid",
    }
    assert forbidden_flags.isdisjoint(provided.keys())


def test_parse_args_only_exposes_connection_and_output_flags():
    args = runner.parse_args([])
    assert set(vars(args).keys()) == {"env_file", "output_dir"}


# ---------------------------------------------------------------------------
# Query is SELECT-only.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed_sql: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.executed_sql.append(sql)

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj


def _candle_row(day: int, price: str = "1.00"):
    return {
        "open_ts_utc": datetime(2020, 1, 1) + timedelta(days=day),
        "open_price": price,
        "high_price": price,
        "low_price": price,
        "close_price": price,
    }


def test_fetch_window_candles_issues_select_only_sql():
    rows = [_candle_row(day) for day in range(25)]
    conn = _FakeConn(rows)
    candles = runner.fetch_window_candles(
        conn,
        asset_id=1,
        symbol="LINK",
        window_label="SELECTION_WINDOW",
        window=runner.WINDOWS[0][1],
    )
    assert len(candles) == 25
    for sql in conn.cursor_obj.executed_sql:
        first_word = sql.strip().split(None, 1)[0].lower()
        assert first_word == "select"


def test_forbidden_sql_is_rejected_by_shared_assert_read_only_sql():
    from src.research.run_fib_exit_ladder_backtest_v1 import assert_read_only_sql

    with pytest.raises(RuntimeError):
        assert_read_only_sql("DELETE FROM obs_market_candle")
    with pytest.raises(RuntimeError):
        assert_read_only_sql("INSERT INTO obs_market_candle VALUES (1)")
    assert_read_only_sql("SELECT 1")  # does not raise


def test_connect_read_only_uses_read_only_transaction_statements(monkeypatch):
    executed = []

    class _RecordingCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=()):
            executed.append(sql)

    class _RecordingConn:
        def cursor(self):
            return _RecordingCursor()

    def fake_connect(**kwargs):
        return _RecordingConn()

    monkeypatch.setattr(runner.pymysql, "connect", fake_connect)
    runner.connect_read_only()
    assert executed == ["SET SESSION TRANSACTION READ ONLY", "START TRANSACTION READ ONLY"]


# ---------------------------------------------------------------------------
# Deterministic candle ordering / duplicate rejection / fail-closed.
# ---------------------------------------------------------------------------


def test_deterministic_ordering_accepted():
    rows = [_candle_row(day) for day in range(25)]
    conn = _FakeConn(rows)
    candles = runner.fetch_window_candles(
        conn, asset_id=1, symbol="LINK", window_label="SELECTION_WINDOW", window=runner.WINDOWS[0][1]
    )
    timestamps = [candle.open_ts_utc for candle in candles]
    assert timestamps == sorted(timestamps)


def test_non_monotonic_ordering_rejected():
    rows = [_candle_row(day) for day in range(20)]
    rows[5], rows[6] = rows[6], rows[5]  # out of order
    conn = _FakeConn(rows)
    with pytest.raises(runner.PitReplayRunnerError):
        runner.fetch_window_candles(
            conn, asset_id=1, symbol="LINK", window_label="SELECTION_WINDOW", window=runner.WINDOWS[0][1]
        )


def test_duplicate_candle_timestamp_rejected():
    rows = [_candle_row(day) for day in range(20)]
    rows[10] = rows[9]  # duplicate timestamp
    conn = _FakeConn(rows)
    with pytest.raises(runner.PitReplayRunnerError):
        runner.fetch_window_candles(
            conn, asset_id=1, symbol="LINK", window_label="SELECTION_WINDOW", window=runner.WINDOWS[0][1]
        )


def test_empty_window_fails_closed():
    conn = _FakeConn([])
    with pytest.raises(runner.PitReplayRunnerError):
        runner.fetch_window_candles(
            conn, asset_id=1, symbol="LINK", window_label="SELECTION_WINDOW", window=runner.WINDOWS[0][1]
        )


def test_missing_asset_fails_closed(monkeypatch):
    monkeypatch.setattr(runner, "_bt_fetch_asset_id", lambda conn, symbol: None)
    with pytest.raises(runner.PitReplayRunnerError):
        runner.fetch_asset_id(conn=None, symbol="LINK")


# ---------------------------------------------------------------------------
# Selection / OOS evidence structural separation.
# ---------------------------------------------------------------------------


def _empty_symbol_result(symbol, window, status="INSUFFICIENT_CANDLES"):
    return engine._empty_pit_result(symbol, window, "PRO_3X4X", Decimal("0.40"), status)


def test_selection_grid_rows_and_oos_rows_come_from_disjoint_windows():
    grid_results = {
        (family, fraction): _empty_symbol_result("LINK", "SELECTION_WINDOW")
        for family in engine.CANDIDATE_FAMILIES
        for fraction in engine.SELL_FRACTION_GRID
    }
    replay = engine.PitSymbolReplayResult(
        symbol="LINK",
        selected_policy=None,
        selection_grid_results=grid_results,
        oos_window_1_result=_empty_symbol_result("LINK", "OOS_WINDOW_1"),
        oos_window_2_result=_empty_symbol_result("LINK", "OOS_WINDOW_2"),
    )
    results = {"LINK": replay}

    grid_rows = runner.build_selection_grid_rows(results)
    oos_rows = runner.build_oos_rows(results)

    assert grid_rows, "expected non-empty selection grid evidence"
    assert oos_rows, "expected non-empty OOS evidence"
    assert all(row["window"] == "SELECTION_WINDOW" for row in grid_rows)
    assert all(row["window"] in ("OOS_WINDOW_1", "OOS_WINDOW_2") for row in oos_rows)


def test_build_oos_rows_source_never_reads_selection_grid_results():
    source = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    oos_fn = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "build_oos_rows"
    )
    referenced_attrs = {
        node.attr for node in ast.walk(oos_fn) if isinstance(node, ast.Attribute)
    }
    assert "selection_grid_results" not in referenced_attrs


def test_build_selection_grid_rows_source_never_reads_oos_results():
    source = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    grid_fn = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "build_selection_grid_rows"
    )
    referenced_attrs = {
        node.attr for node in ast.walk(grid_fn) if isinstance(node, ast.Attribute)
    }
    assert "oos_window_1_result" not in referenced_attrs
    assert "oos_window_2_result" not in referenced_attrs


# ---------------------------------------------------------------------------
# Architecture boundary: no forbidden imports/writes anywhere in this module.
# ---------------------------------------------------------------------------


def test_runner_module_has_no_forbidden_imports():
    source = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            lowered = name.lower()
            for forbidden in FORBIDDEN_IMPORT_SUBSTRINGS:
                assert forbidden not in lowered, f"forbidden import {name!r} in runner module"


def test_runner_module_contains_no_non_select_sql_verbs():
    text = RUNNER_PATH.read_text(encoding="utf-8").upper()
    for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "ALTER ", "TRUNCATE"):
        assert verb not in text


def test_write_evidence_produces_manifest_and_hashes(tmp_path):
    grid_results = {
        (family, fraction): _empty_symbol_result("LINK", "SELECTION_WINDOW")
        for family in engine.CANDIDATE_FAMILIES
        for fraction in engine.SELL_FRACTION_GRID
    }
    replay = engine.PitSymbolReplayResult(
        symbol="LINK",
        selected_policy=None,
        selection_grid_results=grid_results,
        oos_window_1_result=None,
        oos_window_2_result=None,
    )
    results = {"LINK": replay}
    row_counts = {"LINK": {"SELECTION_WINDOW": 25, "OOS_WINDOW_1": 30, "OOS_WINDOW_2": 40}}

    manifest = runner.write_evidence(tmp_path, results, row_counts)

    raw_dir = tmp_path / "raw"
    for filename in manifest["files"]:
        file_path = raw_dir / filename
        assert file_path.exists()
        assert runner.sha256_of_file(file_path) == manifest["files"][filename]["sha256"]
