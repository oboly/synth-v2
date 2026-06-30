from __future__ import annotations

import csv
from pathlib import Path

from src.research.run_breathline_offset_continuity_aplus_comparison_v1 import main


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_aplus_comparison_accepts_day_units_and_rejects_source_relative_units(tmp_path: Path) -> None:
    market_path = tmp_path / "market.csv"
    aplus_path = tmp_path / "aplus.csv"
    out_path = tmp_path / "out.csv"

    _write_csv(
        market_path,
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "sensitivity_mode",
            "selection_status",
            "selected_template_time_shift_days",
            "raw_shift_delta_days",
        ],
        [
            {
                "symbol": "BTC",
                "raw_lattice_anchor_ts_utc": "2025-01-01T12:00:00Z",
                "sensitivity_mode": "STRICT",
                "selection_status": "UNIQUE_TOP_CANDIDATE",
                "selected_template_time_shift_days": 0.0,
                "raw_shift_delta_days": "",
            },
            {
                "symbol": "BTC",
                "raw_lattice_anchor_ts_utc": "2025-02-01T12:00:00Z",
                "sensitivity_mode": "STRICT",
                "selection_status": "UNIQUE_TOP_CANDIDATE",
                "selected_template_time_shift_days": 1.0,
                "raw_shift_delta_days": 1.0,
            },
        ],
    )
    _write_csv(
        aplus_path,
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "source_artifact_id",
            "source_claimed_timestamp_utc",
            "offset_unit",
            "raw_offset_band",
            "raw_phase",
            "raw_stability",
        ],
        [
            {
                "symbol": "BTC",
                "raw_lattice_anchor_ts_utc": "2025-01-01T12:00:00Z",
                "source_artifact_id": "artifact-a",
                "source_claimed_timestamp_utc": "2025-01-01T12:00:00Z",
                "offset_unit": "days",
                "raw_offset_band": "0",
                "raw_phase": "phase-a",
                "raw_stability": "stable",
            },
            {
                "symbol": "BTC",
                "raw_lattice_anchor_ts_utc": "2025-02-01T12:00:00Z",
                "source_artifact_id": "artifact-b",
                "source_claimed_timestamp_utc": "2025-02-01T12:00:00Z",
                "offset_unit": "source_relative",
                "raw_offset_band": "+0.01",
                "raw_phase": "phase-b",
                "raw_stability": "volatile",
            },
        ],
    )

    code = main(
        [
            "--market-continuity-csv",
            str(market_path),
            "--aplus-csv",
            str(aplus_path),
            "--out-csv",
            str(out_path),
        ]
    )
    assert code == 0

    rows = _read_csv(out_path)
    by_anchor = {row["raw_lattice_anchor_ts_utc"]: row for row in rows}
    assert by_anchor["2025-01-01T12:00:00Z"]["comparability_reason"] == "COMPARABLE"
    assert by_anchor["2025-01-01T12:00:00Z"]["same_shift"] == "True"
    assert by_anchor["2025-02-01T12:00:00Z"]["comparability_reason"] == "REJECTED_OFFSET_UNIT:source_relative"


def test_aplus_comparison_cannot_alter_market_output(tmp_path: Path) -> None:
    market_path = tmp_path / "market.csv"
    aplus_path = tmp_path / "aplus.csv"
    out_path = tmp_path / "out.csv"

    market_row = {
        "symbol": "ETH",
        "raw_lattice_anchor_ts_utc": "2025-03-01T12:00:00Z",
        "sensitivity_mode": "NORMAL",
        "selection_status": "TIED_TOP_CANDIDATES",
        "selected_template_time_shift_days": "",
        "raw_shift_delta_days": "",
    }
    _write_csv(
        market_path,
        list(market_row.keys()),
        [market_row],
    )
    _write_csv(
        aplus_path,
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "source_artifact_id",
            "source_claimed_timestamp_utc",
            "offset_unit",
            "raw_offset_band",
            "raw_phase",
            "raw_stability",
        ],
        [
            {
                "symbol": "ETH",
                "raw_lattice_anchor_ts_utc": "2025-03-01T12:00:00Z",
                "source_artifact_id": "artifact-c",
                "source_claimed_timestamp_utc": "2025-03-01T12:00:00Z",
                "offset_unit": "days",
                "raw_offset_band": "3",
                "raw_phase": "phase-c",
                "raw_stability": "stable",
            },
        ],
    )

    main(
        [
            "--market-continuity-csv",
            str(market_path),
            "--aplus-csv",
            str(aplus_path),
            "--out-csv",
            str(out_path),
        ]
    )
    row = _read_csv(out_path)[0]
    assert row["selection_status"] == market_row["selection_status"]
    assert row["market_selected_shift_days"] == market_row["selected_template_time_shift_days"]
