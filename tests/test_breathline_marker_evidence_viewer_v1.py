from __future__ import annotations

import ast
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import src.research.run_breathline_marker_evidence_viewer_v1 as runner
from src.research.run_breathline_marker_evidence_viewer_v1 import main


FIXED_NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
FIXED_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _marker(
    code: str,
    expected_ts_utc: str,
    *,
    kind: str,
    ratio: float,
    matched: bool,
    observed_ts_utc: str | None = None,
    observed_price: float | None = None,
    timing_error_hours: float | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "code": code,
        "expected_ts_utc": expected_ts_utc,
        "kind": kind,
        "ratio": ratio,
        "matched": matched,
    }
    if observed_ts_utc is not None:
        row["observed_ts_utc"] = observed_ts_utc
    if observed_price is not None:
        row["observed_price"] = observed_price
    if timing_error_hours is not None:
        row["timing_error_hours"] = timing_error_hours
    return row


def _candle(
    ts_utc: str,
    *,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> dict[str, object]:
    return {
        "ts_utc": ts_utc,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
    }


def _ok_row(
    *,
    symbol: str,
    anchor_ts_utc: str,
    checkpoint_ratio: str,
    selected_partial_offset_days: float,
    markers: list[dict[str, object]],
    flags: dict[str, bool] | None = None,
    evidence_candles: list[dict[str, object]] | None = None,
    venue: str = "bitvavo",
    interval_code: str = "1d",
    tolerance_hours: float = 24.0,
) -> dict[str, object]:
    row: dict[str, object] = {
        "status": "OK",
        "symbol": symbol,
        "anchor_ts_utc": anchor_ts_utc,
        "checkpoint_ratio": checkpoint_ratio,
        "selected_partial_offset_days": selected_partial_offset_days,
        "selected_full_same_offset": {
            "venue": venue,
            "interval_code": interval_code,
            "cycle_days": 21.0,
            "phase_offset_days": selected_partial_offset_days,
            "tolerance_hours": tolerance_hours,
            "flags": flags or {},
            "markers": markers,
        },
    }
    if evidence_candles is not None:
        row["evidence_candles"] = evidence_candles
    return row


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _fixture_rows() -> list[dict[str, object]]:
    btc_candles = [
        _candle("2025-01-01T00:00:00Z", open_price=100.0, high_price=104.0, low_price=99.0, close_price=103.0),
        _candle("2025-01-02T00:00:00Z", open_price=103.0, high_price=106.0, low_price=101.0, close_price=105.0),
        _candle("2025-01-03T00:00:00Z", open_price=105.0, high_price=109.0, low_price=104.0, close_price=108.0),
        _candle("2025-01-04T00:00:00Z", open_price=108.0, high_price=112.0, low_price=106.0, close_price=111.0),
        _candle("2025-01-05T00:00:00Z", open_price=111.0, high_price=113.0, low_price=107.0, close_price=109.0),
    ]
    eth_candles = [
        _candle("2025-01-01T00:00:00Z", open_price=50.0, high_price=53.0, low_price=49.0, close_price=52.0),
        _candle("2025-01-02T00:00:00Z", open_price=52.0, high_price=56.0, low_price=51.0, close_price=55.0),
        _candle("2025-01-03T00:00:00Z", open_price=55.0, high_price=57.0, low_price=53.0, close_price=54.0),
        _candle("2025-01-04T00:00:00Z", open_price=54.0, high_price=60.0, low_price=54.0, close_price=59.0),
        _candle("2025-01-05T00:00:00Z", open_price=59.0, high_price=62.0, low_price=58.0, close_price=61.0),
    ]
    return [
        _ok_row(
            symbol="BTC",
            anchor_ts_utc="2025-01-01T00:00:00Z",
            checkpoint_ratio="0.618",
            selected_partial_offset_days=0.0,
            evidence_candles=btc_candles,
            flags={
                "first_lift_above_anchor": True,
                "first_dip_below_first_lift": True,
                "pulse_above_second_peak": False,
            },
            markers=[
                _marker(
                    "FIRST_LIFT_HIGH",
                    "2025-01-02T00:00:00Z",
                    kind="HIGH",
                    ratio=0.236,
                    matched=True,
                    observed_ts_utc="2025-01-02T00:00:00Z",
                    observed_price=106.0,
                    timing_error_hours=0.0,
                ),
                _marker(
                    "FIRST_DIP_LOW",
                    "2025-01-03T00:00:00Z",
                    kind="LOW",
                    ratio=0.382,
                    matched=True,
                    observed_ts_utc="2025-01-03T00:00:00Z",
                    observed_price=104.0,
                    timing_error_hours=0.0,
                ),
                _marker(
                    "SECOND_PEAK_RETEST_HIGH",
                    "2025-01-04T00:00:00Z",
                    kind="HIGH",
                    ratio=0.500,
                    matched=False,
                ),
            ],
        ),
        _ok_row(
            symbol="ETH",
            anchor_ts_utc="2025-01-01T00:00:00Z",
            checkpoint_ratio="0.618",
            selected_partial_offset_days=0.5,
            evidence_candles=eth_candles,
            flags={
                "first_lift_above_anchor": True,
                "first_dip_below_first_lift": True,
                "pulse_above_second_peak": True,
            },
            markers=[
                _marker(
                    "FIRST_LIFT_HIGH",
                    "2025-01-02T00:00:00Z",
                    kind="HIGH",
                    ratio=0.236,
                    matched=True,
                    observed_ts_utc="2025-01-02T00:00:00Z",
                    observed_price=56.0,
                    timing_error_hours=0.0,
                ),
                _marker(
                    "FIRST_DIP_LOW",
                    "2025-01-03T00:00:00Z",
                    kind="LOW",
                    ratio=0.382,
                    matched=True,
                    observed_ts_utc="2025-01-03T00:00:00Z",
                    observed_price=53.0,
                    timing_error_hours=0.0,
                ),
                _marker(
                    "SECOND_PEAK_RETEST_HIGH",
                    "2025-01-04T00:00:00Z",
                    kind="HIGH",
                    ratio=0.500,
                    matched=True,
                    observed_ts_utc="2025-01-04T00:00:00Z",
                    observed_price=60.0,
                    timing_error_hours=0.0,
                ),
            ],
        ),
        _ok_row(
            symbol="BTC",
            anchor_ts_utc="2025-02-01T00:00:00Z",
            checkpoint_ratio="0.786",
            selected_partial_offset_days=0.0,
            markers=[
                _marker(
                    "FIRST_LIFT_HIGH",
                    "2025-02-02T00:00:00Z",
                    kind="HIGH",
                    ratio=0.236,
                    matched=False,
                ),
            ],
        ),
    ]


def _freeze_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "utc_now", lambda: FIXED_NOW)
    monkeypatch.setattr(runner, "current_git_commit", lambda: FIXED_COMMIT)


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self._connection = connection
        self._rows: list[dict[str, object]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        normalized = " ".join(sql.split())
        if "FROM asset" in normalized:
            self._rows = [
                {"asset_id": 1, "symbol": "BTC"},
            ]
            return
        if "FROM obs_market_candle c JOIN asset a" in normalized:
            self._rows = [
                {
                    "symbol": "BTC",
                    "close_ts_utc": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
                    "open_price": 100.0,
                    "high_price": 104.0,
                    "low_price": 99.0,
                    "close_price": 103.0,
                },
                {
                    "symbol": "BTC",
                    "close_ts_utc": datetime(2025, 1, 2, 0, 0, tzinfo=UTC),
                    "open_price": 103.0,
                    "high_price": 106.0,
                    "low_price": 101.0,
                    "close_price": 105.0,
                },
                {
                    "symbol": "BTC",
                    "close_ts_utc": datetime(2025, 1, 3, 0, 0, tzinfo=UTC),
                    "open_price": 105.0,
                    "high_price": 109.0,
                    "low_price": 104.0,
                    "close_price": 108.0,
                },
                {
                    "symbol": "BTC",
                    "close_ts_utc": datetime(2025, 1, 4, 0, 0, tzinfo=UTC),
                    "open_price": 108.0,
                    "high_price": 112.0,
                    "low_price": 106.0,
                    "close_price": 111.0,
                },
                {
                    "symbol": "BTC",
                    "close_ts_utc": datetime(2025, 1, 5, 0, 0, tzinfo=UTC),
                    "open_price": 111.0,
                    "high_price": 113.0,
                    "low_price": 107.0,
                    "close_price": 109.0,
                },
            ]
            return
        raise AssertionError(f"Unexpected SQL in fake cursor: {normalized}")

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def test_deterministic_filtered_outputs_write_expected_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _freeze_metadata(monkeypatch)
    input_path = tmp_path / "input.jsonl"
    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"
    _write_jsonl(input_path, _fixture_rows())

    code_a = main(
        [
            "--input-jsonl",
            str(input_path),
            "--out-dir",
            str(out_a),
            "--symbols",
            "BTC",
            "ETH",
            "--checkpoint-ratio",
            "0.618",
        ]
    )
    code_b = main(
        [
            "--input-jsonl",
            str(input_path),
            "--out-dir",
            str(out_b),
            "--symbols",
            "BTC",
            "ETH",
            "--checkpoint-ratio",
            "0.618",
        ]
    )
    assert code_a == 0
    assert code_b == 0

    expected_files = {
        "index.html",
        "evidence_index.csv",
        "manifest.txt",
        "evidence_btc_20250101T000000Z_cp_0p618.html",
        "evidence_eth_20250101T000000Z_cp_0p618.html",
    }
    assert {path.name for path in out_a.iterdir()} == expected_files
    assert {path.name for path in out_b.iterdir()} == expected_files

    assert (out_a / "index.html").read_text(encoding="utf-8") == (out_b / "index.html").read_text(encoding="utf-8")
    assert (
        (out_a / "evidence_btc_20250101T000000Z_cp_0p618.html").read_text(encoding="utf-8")
        == (out_b / "evidence_btc_20250101T000000Z_cp_0p618.html").read_text(encoding="utf-8")
    )

    csv_rows = _read_csv(out_a / "evidence_index.csv")
    assert csv_rows == [
        {
            "symbol": "BTC",
            "anchor_ts_utc": "2025-01-01T00:00:00Z",
            "checkpoint_ratio": "0.618",
            "page_file": "evidence_btc_20250101T000000Z_cp_0p618.html",
            "marker_count": "3",
            "matched_marker_count": "2",
            "candle_source": "inline",
            "candle_count": "5",
            "warning": "",
        },
        {
            "symbol": "ETH",
            "anchor_ts_utc": "2025-01-01T00:00:00Z",
            "checkpoint_ratio": "0.618",
            "page_file": "evidence_eth_20250101T000000Z_cp_0p618.html",
            "marker_count": "3",
            "matched_marker_count": "3",
            "candle_source": "inline",
            "candle_count": "5",
            "warning": "",
        },
    ]

    manifest = (out_a / "manifest.txt").read_text(encoding="utf-8")
    assert "rendered_rows=2" in manifest
    assert "source_git_commit=0123456789abcdef0123456789abcdef01234567" in manifest
    assert "symbols_filter=BTC,ETH" in manifest
    assert "checkpoint_ratio_filter=0.618" in manifest


def test_page_contains_expected_windows_selected_markers_and_required_banner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _freeze_metadata(monkeypatch)
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(input_path, _fixture_rows())

    main(
        [
            "--input-jsonl",
            str(input_path),
            "--out-dir",
            str(output_dir),
            "--symbols",
            "BTC",
            "--checkpoint-ratio",
            "0.618",
        ]
    )

    html_text = (output_dir / "evidence_btc_20250101T000000Z_cp_0p618.html").read_text(encoding="utf-8")
    assert runner.TITLE_LINE in html_text
    assert runner.WARNING_LINE in html_text
    assert "data-anchor-ts='2025-01-01T00:00:00Z'" in html_text
    assert "data-marker-code='FIRST_LIFT_HIGH'" in html_text
    assert "data-window-start='2025-01-01T00:00:00Z'" in html_text
    assert "data-window-end='2025-01-03T00:00:00Z'" in html_text
    assert "data-selected-marker='FIRST_LIFT_HIGH'" in html_text
    assert "data-observed-price='106.00000000'" in html_text
    assert "FIRST_DIP_LOW" in html_text
    assert "pulse_above_second_peak" in html_text
    assert "NO" in html_text


def test_missing_candle_warning_renders_without_db_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _freeze_metadata(monkeypatch)

    def _raise_connection() -> None:
        raise RuntimeError("db offline")

    monkeypatch.setattr(runner, "get_connection", _raise_connection)

    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    rows = [
        _ok_row(
            symbol="BTC",
            anchor_ts_utc="2025-02-01T00:00:00Z",
            checkpoint_ratio="0.618",
            selected_partial_offset_days=0.0,
            markers=[
                _marker(
                    "FIRST_LIFT_HIGH",
                    "2025-02-02T00:00:00Z",
                    kind="HIGH",
                    ratio=0.236,
                    matched=False,
                ),
                _marker(
                    "FIRST_DIP_LOW",
                    "2025-02-03T00:00:00Z",
                    kind="LOW",
                    ratio=0.382,
                    matched=False,
                ),
            ],
            evidence_candles=None,
        )
    ]
    _write_jsonl(input_path, rows)

    code = main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])
    assert code == 0

    html_text = (output_dir / "evidence_btc_20250201T000000Z_cp_0p618.html").read_text(encoding="utf-8")
    assert "WARNING: candles unavailable — read-only DB lookup failed: RuntimeError: db offline" in html_text
    assert "data-marker-code='FIRST_LIFT_HIGH'" in html_text
    assert "data-window-start='2025-02-01T00:00:00Z'" in html_text
    assert runner.WARNING_LINE in html_text

    csv_rows = _read_csv(output_dir / "evidence_index.csv")
    assert csv_rows[0]["candle_source"] == "missing"
    assert "db offline" in csv_rows[0]["warning"]


def test_mocked_read_only_db_success_renders_real_candles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _freeze_metadata(monkeypatch)
    fake_connection = _FakeConnection()
    monkeypatch.setattr(runner, "get_connection", lambda: fake_connection)

    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    rows = [
        _ok_row(
            symbol="BTC",
            anchor_ts_utc="2025-01-01T00:00:00Z",
            checkpoint_ratio="0.618",
            selected_partial_offset_days=0.0,
            markers=[
                _marker(
                    "FIRST_LIFT_HIGH",
                    "2025-01-02T00:00:00Z",
                    kind="HIGH",
                    ratio=0.236,
                    matched=True,
                    observed_ts_utc="2025-01-02T00:00:00Z",
                    observed_price=106.0,
                    timing_error_hours=0.0,
                ),
                _marker(
                    "FIRST_DIP_LOW",
                    "2025-01-03T00:00:00Z",
                    kind="LOW",
                    ratio=0.382,
                    matched=True,
                    observed_ts_utc="2025-01-03T00:00:00Z",
                    observed_price=104.0,
                    timing_error_hours=0.0,
                ),
                _marker(
                    "SECOND_PEAK_RETEST_HIGH",
                    "2025-01-04T00:00:00Z",
                    kind="HIGH",
                    ratio=0.500,
                    matched=False,
                ),
            ],
            evidence_candles=None,
        )
    ]
    _write_jsonl(input_path, rows)

    code = main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])
    assert code == 0
    assert fake_connection.closed is True

    csv_rows = _read_csv(output_dir / "evidence_index.csv")
    assert csv_rows[0]["candle_source"] == "database"
    assert csv_rows[0]["candle_count"] == "5"

    html_text = (output_dir / "evidence_btc_20250101T000000Z_cp_0p618.html").read_text(encoding="utf-8")
    assert "class='candle-body'" in html_text
    assert "class='candle-wick'" in html_text

    manifest_text = (output_dir / "manifest.txt").read_text(encoding="utf-8")
    assert "db_reads=2" in manifest_text
    assert "candles unavailable" not in html_text.lower()


def test_safety_markers_appear_in_manifest_and_pages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _freeze_metadata(monkeypatch)
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(input_path, _fixture_rows())

    main(
        [
            "--input-jsonl",
            str(input_path),
            "--out-dir",
            str(output_dir),
            "--symbols",
            "BTC",
            "--checkpoint-ratio",
            "0.618",
        ]
    )

    manifest_text = (output_dir / "manifest.txt").read_text(encoding="utf-8")
    index_text = (output_dir / "index.html").read_text(encoding="utf-8")
    page_text = (output_dir / "evidence_btc_20250101T000000Z_cp_0p618.html").read_text(encoding="utf-8")
    for key, value in runner.SAFETY_MARKERS.items():
        marker = f"{key}={value}"
        assert marker in manifest_text
        assert key in index_text
        assert key in page_text


def test_runner_source_has_no_forbidden_layer_imports() -> None:
    source_path = Path("src/research/run_breathline_marker_evidence_viewer_v1.py")
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text)

    forbidden_prefixes = (
        "src.selection",
        "src.selection_engine",
        "src.decision_gate",
        "src.execution",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "src.reporting",
        "src.account",
        "src.account_",
        "src.account_provisioning",
        "src.asset_profile",
    )

    def is_forbidden(module_name: str) -> bool:
        return any(module_name.startswith(prefix) for prefix in forbidden_prefixes)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not is_forbidden(alias.name), alias.name
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert not is_forbidden(module_name), module_name


def test_inline_candles_must_be_strictly_ascending(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    rows = [
        _ok_row(
            symbol="BTC",
            anchor_ts_utc="2025-01-01T00:00:00Z",
            checkpoint_ratio="0.618",
            selected_partial_offset_days=0.0,
            markers=[
                _marker(
                    "FIRST_LIFT_HIGH",
                    "2025-01-02T00:00:00Z",
                    kind="HIGH",
                    ratio=0.236,
                    matched=False,
                ),
            ],
            evidence_candles=[
                _candle("2025-01-02T00:00:00Z", open_price=1.0, high_price=2.0, low_price=0.5, close_price=1.5),
                _candle("2025-01-01T00:00:00Z", open_price=1.5, high_price=2.1, low_price=1.0, close_price=1.8),
            ],
        )
    ]
    _write_jsonl(input_path, rows)

    with pytest.raises(ValueError, match="strictly ascending"):
        main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])


def test_utc_timestamps_require_explicit_timezone(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "out"
    rows = [
        _ok_row(
            symbol="BTC",
            anchor_ts_utc="2025-01-01T00:00:00",
            checkpoint_ratio="0.618",
            selected_partial_offset_days=0.0,
            markers=[
                _marker(
                    "FIRST_LIFT_HIGH",
                    "2025-01-02T00:00:00Z",
                    kind="HIGH",
                    ratio=0.236,
                    matched=False,
                )
            ],
        )
    ]
    _write_jsonl(input_path, rows)

    with pytest.raises(ValueError, match="explicit timezone required"):
        main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])


@pytest.mark.parametrize(
    ("matched_value", "label"),
    [
        ("true", "string_true"),
        ("false", "string_false"),
        (1, "int_one"),
        (0, "int_zero"),
        (None, "missing"),
    ],
)
def test_marker_matched_must_be_literal_boolean(
    tmp_path: Path,
    matched_value: object,
    label: str,
) -> None:
    input_path = tmp_path / f"{label}.jsonl"
    output_dir = tmp_path / f"out_{label}"
    marker = {
        "code": "FIRST_LIFT_HIGH",
        "expected_ts_utc": "2025-01-02T00:00:00Z",
        "kind": "HIGH",
        "ratio": 0.236,
    }
    if matched_value is not None:
        marker["matched"] = matched_value
    rows = [
        _ok_row(
            symbol="BTC",
            anchor_ts_utc="2025-01-01T00:00:00Z",
            checkpoint_ratio="0.618",
            selected_partial_offset_days=0.0,
            markers=[marker],
        )
    ]
    _write_jsonl(input_path, rows)

    with pytest.raises(ValueError, match="must be literal boolean true or false"):
        main(["--input-jsonl", str(input_path), "--out-dir", str(output_dir)])
