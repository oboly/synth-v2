from __future__ import annotations

import ast
import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import src.research.run_breathline_lattice_shift_calibration_v2 as runner
from src.market_context.breathline_lattice_matcher_v2 import (
    BASE_MARKERS,
    CYCLE_DAYS,
    DEFAULT_SHIFT_GRID_DAYS,
    effective_schedule_origin_ts,
    expected_marker_ts,
    parse_dt,
)
from src.research.run_breathline_lattice_shift_calibration_v2 import main


FIXED_NOW = datetime(2026, 6, 30, 9, 0, tzinfo=UTC)
FIXED_COMMIT = "0123456789abcdef0123456789abcdef01234567"
MODULE_PATH = Path("src/research/run_breathline_lattice_shift_calibration_v2.py")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _day_start(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _candle_row(
    symbol: str,
    ts: datetime,
    *,
    open_price: float = 100.0,
    high_price: float = 101.0,
    low_price: float = 99.0,
    close_price: float = 100.0,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "open_ts_utc": ts.isoformat().replace("+00:00", "Z"),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
    }


def _build_cycle_rows(symbol: str, anchor: datetime, shift_days: float) -> list[dict[str, object]]:
    start = _day_start(anchor)
    rows = [
        _candle_row(symbol, start + timedelta(days=index))
        for index in range(-2, 38)
    ]
    by_ts = {row["open_ts_utc"]: row for row in rows}
    marker_shapes = {
        "FIRST_LIFT_HIGH": {"high_price": 110.0, "low_price": 100.0, "close_price": 105.0},
        "FIRST_DIP_LOW": {"high_price": 99.0, "low_price": 90.0, "close_price": 94.0},
        "SECOND_PEAK_RETEST_HIGH": {"high_price": 108.0, "low_price": 99.0, "close_price": 104.0},
        "SECOND_DIP_HIGHER_LOW": {"high_price": 100.0, "low_price": 95.0, "close_price": 97.0},
        "IGNITION_PRE_SPIKE": {"high_price": 112.0, "low_price": 100.0, "close_price": 108.0},
        "MAIN_PULSE_TP_HIGH": {"high_price": 130.0, "low_price": 109.0, "close_price": 125.0},
    }
    for marker in BASE_MARKERS:
        ts = _day_start(expected_marker_ts(anchor, shift_days, CYCLE_DAYS, marker.ratio))
        key = ts.isoformat().replace("+00:00", "Z")
        by_ts[key] = _candle_row(symbol, ts, **marker_shapes[marker.code])
    return sorted(by_ts.values(), key=lambda row: str(row["open_ts_utc"]))


def _freeze_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "utc_now", lambda: FIXED_NOW)
    monkeypatch.setattr(runner, "current_git_commit", lambda: FIXED_COMMIT)


def test_calibration_runner_produces_every_required_output_file_from_fixture_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_metadata(monkeypatch)
    input_path = tmp_path / "input.jsonl"
    candles_path = tmp_path / "candles.jsonl"
    out_dir = tmp_path / "out"
    anchor_a = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    anchor_b = datetime(2025, 2, 15, 12, 0, tzinfo=UTC)

    _write_jsonl(
        input_path,
        [
            {"status": "OK", "symbol": "BTC", "raw_lattice_anchor_ts_utc": anchor_a.isoformat().replace("+00:00", "Z"), "interval_code": "1d"},
            {"status": "OK", "symbol": "BTC", "raw_lattice_anchor_ts_utc": anchor_b.isoformat().replace("+00:00", "Z"), "interval_code": "1d"},
            {"status": "SKIP", "symbol": "BTC", "raw_lattice_anchor_ts_utc": "2025-03-01T12:00:00Z", "interval_code": "1d"},
        ],
    )
    _write_jsonl(
        candles_path,
        _build_cycle_rows("BTC", anchor_a, 0.0) + _build_cycle_rows("BTC", anchor_b, 1.0),
    )

    code = main(
        [
            "--input-jsonl",
            str(input_path),
            "--candles-jsonl",
            str(candles_path),
            "--out-dir",
            str(out_dir),
        ]
    )
    assert code == 0
    assert {path.name for path in out_dir.iterdir()} == {
        "ranked_shift_candidates.csv",
        "marker_sequence_evidence.csv",
        "extension_marker_evidence.csv",
        "epoch_shift_continuity.csv",
        "tolerance_sensitivity_summary.csv",
        "manifest.txt",
    }

    manifest = (out_dir / "manifest.txt").read_text(encoding="utf-8")
    assert f"source_git_commit={FIXED_COMMIT}" in manifest
    assert "candle_source=candles_jsonl_fixture" in manifest
    assert "db_writes=0" in manifest
    assert "boundary_marker=effective_schedule_origin_is_schedule_coordinate_only" in manifest

    tolerance_rows = _read_csv(out_dir / "tolerance_sensitivity_summary.csv")
    assert {row["sensitivity_mode"] for row in tolerance_rows} == {"STRICT", "NORMAL", "MAX"}


def test_shift_grid_boundary_ownership() -> None:
    """
    The 21d lattice uses half-open epoch cells [A_n - 10.5d, A_n + 10.5d).
    -10.5 belongs to epoch n; +10.5 is owned by epoch n+1 as its -10.5 candidate.
    Therefore +10.5 must not appear in the default grid, and -10.5 must appear exactly once.
    """
    assert -10.5 in DEFAULT_SHIFT_GRID_DAYS, "-10.5 must be present (lower boundary owner)"
    assert 10.5 not in DEFAULT_SHIFT_GRID_DAYS, "+10.5 must be absent (owned by next epoch)"
    assert DEFAULT_SHIFT_GRID_DAYS.count(-10.5) == 1, "-10.5 must appear exactly once"

    # effective_origin(anchor_n, +10.5) == effective_origin(anchor_n+1, -10.5)
    cycle = timedelta(days=CYCLE_DAYS)
    anchor_n = parse_dt("2024-01-01T00:00:00Z")
    anchor_n1 = anchor_n + cycle
    origin_via_n = effective_schedule_origin_ts(anchor_n, 10.5)
    origin_via_n1 = effective_schedule_origin_ts(anchor_n1, -10.5)
    assert origin_via_n == origin_via_n1, (
        f"Boundary origin mismatch: {origin_via_n} != {origin_via_n1}"
    )


def test_calibration_runner_csv_output_is_lf_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_metadata(monkeypatch)
    input_path = tmp_path / "input.jsonl"
    candles_path = tmp_path / "candles.jsonl"
    out_dir = tmp_path / "out"
    anchor = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    _write_jsonl(input_path, [
        {"status": "OK", "symbol": "BTC", "raw_lattice_anchor_ts_utc": anchor.isoformat().replace("+00:00", "Z"), "interval_code": "1d"},
    ])
    _write_jsonl(candles_path, _build_cycle_rows("BTC", anchor, 0.0))
    main(["--input-jsonl", str(input_path), "--candles-jsonl", str(candles_path), "--out-dir", str(out_dir)])
    for csv_file in sorted(out_dir.glob("*.csv")):
        raw = csv_file.read_bytes()
        assert b"\r\n" not in raw, f"{csv_file.name} contains CRLF"
        assert b"\r" not in raw, f"{csv_file.name} contains bare CR"


def test_source_has_no_forbidden_runtime_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    joined = "\n".join(imports)
    for forbidden in ("decision_gate", "execution_planner", "executor", "broker", "dashboard", "selection_engine"):
        assert forbidden not in joined
