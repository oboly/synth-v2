from __future__ import annotations

import ast
import csv
import json
import subprocess
from pathlib import Path

import pytest

import src.research.run_breathline_marker_timing_report_v1 as runner
from src.research.run_breathline_marker_timing_report_v1 import current_git_commit
from src.research.run_breathline_marker_timing_report_v1 import main


def _marker(
    code: str,
    expected_ts_utc: str,
    *,
    matched: bool,
    observed_ts_utc: str | None = None,
    timing_error_hours: float | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "code": code,
        "expected_ts_utc": expected_ts_utc,
        "matched": matched,
    }
    if observed_ts_utc is not None:
        row["observed_ts_utc"] = observed_ts_utc
    if timing_error_hours is not None:
        row["timing_error_hours"] = timing_error_hours
    return row


def _ok_row(
    symbol: str,
    anchor_ts_utc: str,
    checkpoint_ratio: str,
    selected_partial_offset_days: float,
    markers: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "status": "OK",
        "symbol": symbol,
        "anchor_ts_utc": anchor_ts_utc,
        "checkpoint_ratio": checkpoint_ratio,
        "selected_partial_offset_days": selected_partial_offset_days,
        "selected_full_same_offset": {
            "markers": markers,
        },
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _valid_rows() -> list[dict[str, object]]:
    return [
        _ok_row(
            "BTC",
            "2025-01-01T00:00:00Z",
            "0.618",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-01-01T00:00:00Z", matched=True, observed_ts_utc="2025-01-01T00:00:00Z", timing_error_hours=0.0),
                _marker("FIRST_DIP_LOW", "2025-01-02T00:00:00Z", matched=True, observed_ts_utc="2025-01-02T00:00:00Z", timing_error_hours=0.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-01-03T00:00:00Z", matched=False),
            ],
        ),
        _ok_row(
            "ETH",
            "2025-01-01T00:00:00Z",
            "0.618",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-01-01T00:00:00Z", matched=True, observed_ts_utc="2025-01-01T02:00:00Z", timing_error_hours=2.0),
                _marker("FIRST_DIP_LOW", "2025-01-02T00:00:00Z", matched=True, observed_ts_utc="2025-01-02T04:00:00Z", timing_error_hours=4.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-01-03T00:00:00Z", matched=False),
            ],
        ),
        _ok_row(
            "BTC",
            "2025-02-01T00:00:00Z",
            "0.618",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-02-01T00:00:00Z", matched=True, observed_ts_utc="2025-02-01T00:00:00Z", timing_error_hours=0.0),
                _marker("FIRST_DIP_LOW", "2025-02-02T00:00:00Z", matched=True, observed_ts_utc="2025-02-02T00:00:00Z", timing_error_hours=0.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-02-03T00:00:00Z", matched=False),
            ],
        ),
        _ok_row(
            "ETH",
            "2025-02-01T00:00:00Z",
            "0.618",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-02-01T00:00:00Z", matched=True, observed_ts_utc="2025-02-01T02:00:00Z", timing_error_hours=2.0),
                _marker("FIRST_DIP_LOW", "2025-02-02T00:00:00Z", matched=True, observed_ts_utc="2025-02-02T04:00:00Z", timing_error_hours=4.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-02-03T00:00:00Z", matched=False),
            ],
        ),
        _ok_row(
            "BTC",
            "2025-01-01T00:00:00Z",
            "0.786",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-01-01T00:00:00Z", matched=True, observed_ts_utc="2025-01-01T00:00:00Z", timing_error_hours=0.0),
                _marker("FIRST_DIP_LOW", "2025-01-02T00:00:00Z", matched=True, observed_ts_utc="2025-01-02T00:00:00Z", timing_error_hours=0.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-01-03T00:00:00Z", matched=False),
            ],
        ),
        _ok_row(
            "ETH",
            "2025-01-01T00:00:00Z",
            "0.786",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-01-01T00:00:00Z", matched=True, observed_ts_utc="2024-12-31T23:00:00Z", timing_error_hours=1.0),
                _marker("FIRST_DIP_LOW", "2025-01-02T00:00:00Z", matched=True, observed_ts_utc="2025-01-01T21:00:00Z", timing_error_hours=3.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-01-03T00:00:00Z", matched=False),
            ],
        ),
        _ok_row(
            "BTC",
            "2025-02-01T00:00:00Z",
            "0.786",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-02-01T00:00:00Z", matched=True, observed_ts_utc="2025-02-01T00:00:00Z", timing_error_hours=0.0),
                _marker("FIRST_DIP_LOW", "2025-02-02T00:00:00Z", matched=True, observed_ts_utc="2025-02-02T00:00:00Z", timing_error_hours=0.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-02-03T00:00:00Z", matched=False),
            ],
        ),
        _ok_row(
            "ETH",
            "2025-02-01T00:00:00Z",
            "0.786",
            0.0,
            [
                _marker("FIRST_LIFT_HIGH", "2025-02-01T00:00:00Z", matched=True, observed_ts_utc="2025-01-31T23:00:00Z", timing_error_hours=1.0),
                _marker("FIRST_DIP_LOW", "2025-02-02T00:00:00Z", matched=True, observed_ts_utc="2025-02-01T21:00:00Z", timing_error_hours=3.0),
                _marker("SECOND_PEAK_RETEST_HIGH", "2025-02-03T00:00:00Z", matched=False),
            ],
        ),
    ]


def test_valid_btc_eth_rows_across_two_anchors_write_all_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(input_path, _valid_rows())

    code = main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])
    assert code == 0

    expected_files = {
        "marker_timing_observations.csv",
        "marker_segment_observations.csv",
        "marker_timing_summary.csv",
        "marker_segment_summary.csv",
        "btc_relative_marker_timing_summary.csv",
        "btc_relative_segment_timing_summary.csv",
        "manifest.txt",
    }
    assert {path.name for path in output_dir.iterdir()} == expected_files

    manifest = (output_dir / "manifest.txt").read_text(encoding="utf-8")
    assert "terminology=marker_timing_not_phase_duration" in manifest
    assert "db_reads=0" in manifest
    assert "broker_calls=0" in manifest


def test_correct_positive_and_negative_btc_relative_marker_lag(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(input_path, _valid_rows())

    main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])
    rows = _read_csv(output_dir / "btc_relative_marker_timing_summary.csv")

    by_key = {(row["checkpoint_ratio"], row["symbol"], row["marker_code"]): row for row in rows}
    positive = by_key[("0.618", "ETH", "FIRST_LIFT_HIGH")]
    negative = by_key[("0.786", "ETH", "FIRST_LIFT_HIGH")]

    assert positive["paired_rows"] == "2"
    assert positive["median_relative_marker_lag_hours"] == "2.000000"
    assert positive["min_relative_marker_lag_hours"] == "2.000000"
    assert positive["max_relative_marker_lag_hours"] == "2.000000"

    assert negative["paired_rows"] == "2"
    assert negative["median_relative_marker_lag_hours"] == "-1.000000"
    assert negative["min_relative_marker_lag_hours"] == "-1.000000"
    assert negative["max_relative_marker_lag_hours"] == "-1.000000"


def test_correct_positive_and_negative_btc_relative_segment_duration_delta(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(input_path, _valid_rows())

    main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])
    rows = _read_csv(output_dir / "btc_relative_segment_timing_summary.csv")

    by_key = {
        (row["checkpoint_ratio"], row["symbol"], row["from_marker_code"], row["to_marker_code"]): row
        for row in rows
    }
    positive = by_key[("0.618", "ETH", "FIRST_LIFT_HIGH", "FIRST_DIP_LOW")]
    negative = by_key[("0.786", "ETH", "FIRST_LIFT_HIGH", "FIRST_DIP_LOW")]

    assert positive["paired_rows"] == "2"
    assert positive["median_relative_segment_duration_delta_hours"] == "2.000000"
    assert negative["paired_rows"] == "2"
    assert negative["median_relative_segment_duration_delta_hours"] == "-2.000000"


def test_unmatched_markers_retained_in_totals_but_excluded_from_observed_segments_and_btc_relative(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(input_path, _valid_rows())

    main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])

    marker_summary_rows = _read_csv(output_dir / "marker_timing_summary.csv")
    segment_summary_rows = _read_csv(output_dir / "marker_segment_summary.csv")
    relative_segment_rows = _read_csv(output_dir / "btc_relative_segment_timing_summary.csv")

    marker_row = next(
        row
        for row in marker_summary_rows
        if row["checkpoint_ratio"] == "0.618"
        and row["symbol"] == "ETH"
        and row["marker_code"] == "SECOND_PEAK_RETEST_HIGH"
    )
    assert marker_row["total_rows"] == "2"
    assert marker_row["matched_rows"] == "0"

    segment_row = next(
        row
        for row in segment_summary_rows
        if row["checkpoint_ratio"] == "0.618"
        and row["symbol"] == "ETH"
        and row["from_marker_code"] == "FIRST_DIP_LOW"
        and row["to_marker_code"] == "SECOND_PEAK_RETEST_HIGH"
    )
    assert segment_row["total_rows"] == "2"
    assert segment_row["matched_segment_rows"] == "0"
    assert segment_row["median_observed_duration_hours"] == ""
    assert segment_row["median_observed_minus_expected_hours"] == ""

    assert not any(
        row["checkpoint_ratio"] == "0.618"
        and row["symbol"] == "ETH"
        and row["from_marker_code"] == "FIRST_DIP_LOW"
        and row["to_marker_code"] == "SECOND_PEAK_RETEST_HIGH"
        for row in relative_segment_rows
    )


def test_duplicate_marker_code_rejection(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(
        input_path,
        [
            _ok_row(
                "BTC",
                "2025-01-01T00:00:00Z",
                "0.618",
                0.0,
                [
                    _marker("FIRST_LIFT_HIGH", "2025-01-01T00:00:00Z", matched=True, observed_ts_utc="2025-01-01T00:00:00Z"),
                    _marker("FIRST_LIFT_HIGH", "2025-01-02T00:00:00Z", matched=True, observed_ts_utc="2025-01-02T00:00:00Z"),
                ],
            )
        ],
    )

    with pytest.raises(ValueError, match="Duplicate marker code"):
        main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])


def test_duplicate_accepted_record_identity_rejection(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    rows = _valid_rows()
    rows.append(_valid_rows()[0])
    _write_jsonl(input_path, rows)

    with pytest.raises(ValueError, match="Duplicate accepted record identity"):
        main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])


def test_non_monotonic_expected_timestamps_rejection(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(
        input_path,
        [
            _ok_row(
                "BTC",
                "2025-01-01T00:00:00Z",
                "0.618",
                0.0,
                [
                    _marker("FIRST_LIFT_HIGH", "2025-01-02T00:00:00Z", matched=True, observed_ts_utc="2025-01-02T00:00:00Z"),
                    _marker("FIRST_DIP_LOW", "2025-01-01T00:00:00Z", matched=True, observed_ts_utc="2025-01-01T00:00:00Z"),
                ],
            )
        ],
    )

    with pytest.raises(ValueError, match="strictly ascending"):
        main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])


def test_non_empty_output_directory_rejection(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "existing.txt").write_text("occupied\n", encoding="utf-8")
    _write_jsonl(input_path, _valid_rows())

    with pytest.raises(ValueError, match="Output directory must be empty"):
        main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])


def test_current_git_commit_returns_unavailable_when_git_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git missing")

    monkeypatch.setattr(runner.subprocess, "run", _raise)
    assert current_git_commit() == "unavailable"


def test_current_git_commit_returns_unavailable_when_git_command_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, ["git", "rev-parse", "HEAD"])

    monkeypatch.setattr(runner.subprocess, "run", _raise)
    assert current_git_commit() == "unavailable"


def test_manifest_writes_unavailable_when_git_metadata_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(input_path, _valid_rows())
    monkeypatch.setattr(runner, "current_git_commit", lambda: "unavailable")

    code = main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])

    assert code == 0
    manifest = (output_dir / "manifest.txt").read_text(encoding="utf-8")
    assert "source_git_commit=unavailable" in manifest


def test_runner_source_has_no_database_imports_or_db_call_references() -> None:
    source_path = Path("src/research/run_breathline_marker_timing_report_v1.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_modules = {
        "pymysql",
        "src.common.db",
        "src.execution",
        "src.executor",
        "src.reporting",
        "src.market_data",
    }
    forbidden_names = {
        "load_db",
        "get_connection",
        "db_cursor",
        "bitvavo_client",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module not in forbidden_modules
            for alias in node.names:
                assert alias.name not in forbidden_names

    for forbidden in ("pymysql", "load_db(", "get_connection(", "db_cursor(", "bitvavo_client"):
        assert forbidden not in source
