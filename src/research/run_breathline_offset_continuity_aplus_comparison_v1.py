from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.market_context.breathline_lattice_matcher_v2 import parse_dt


REQUIRED_APLUS_COLUMNS = (
    "symbol",
    "raw_lattice_anchor_ts_utc",
    "source_artifact_id",
    "source_claimed_timestamp_utc",
    "offset_unit",
    "raw_offset_band",
    "raw_phase",
    "raw_stability",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only raw comparison between market lattice continuity and manually mapped A+ offsets."
    )
    parser.add_argument("--market-continuity-csv", required=True)
    parser.add_argument("--aplus-csv", required=True)
    parser.add_argument("--out-csv", required=True)
    return parser.parse_args(argv)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def ensure_aplus_columns(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("A+ comparison input is empty.")
    columns = set(rows[0].keys())
    missing = [column for column in REQUIRED_APLUS_COLUMNS if column not in columns]
    if missing:
        raise ValueError(f"A+ comparison input missing required columns: {missing}")


def parse_finite_days(raw_value: str) -> float | None:
    try:
        value = float(str(raw_value).strip())
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def build_aplus_by_identity(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    ensure_aplus_columns(rows)
    mapping: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (str(row["symbol"]).strip(), str(row["raw_lattice_anchor_ts_utc"]).strip())
        mapping[key] = row
    return mapping


def build_aplus_previous_delta(rows: list[dict[str, str]]) -> dict[tuple[str, str], float | None]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["symbol"]).strip()].append(row)

    deltas: dict[tuple[str, str], float | None] = {}
    for symbol, group in grouped.items():
        group.sort(key=lambda row: parse_dt(str(row["raw_lattice_anchor_ts_utc"]).strip()))
        previous_value: float | None = None
        for row in group:
            key = (symbol, str(row["raw_lattice_anchor_ts_utc"]).strip())
            if str(row["offset_unit"]).strip() != "days":
                deltas[key] = None
                continue
            value = parse_finite_days(str(row["raw_offset_band"]).strip())
            if value is None:
                deltas[key] = None
                continue
            deltas[key] = round(value - previous_value, 6) if previous_value is not None else None
            previous_value = value
    return deltas


def _direction(value: float | None) -> int | None:
    if value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def build_rows(
    market_rows: list[dict[str, str]],
    aplus_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    aplus_by_identity = build_aplus_by_identity(aplus_rows)
    aplus_previous_delta = build_aplus_previous_delta(aplus_rows)
    output_rows: list[dict[str, Any]] = []

    for market_row in market_rows:
        symbol = str(market_row.get("symbol") or "").strip()
        raw_anchor = str(market_row.get("raw_lattice_anchor_ts_utc") or "").strip()
        key = (symbol, raw_anchor)
        aplus_row = aplus_by_identity.get(key)

        comparability_reason = "NO_EXACT_APLUS_MATCH"
        aplus_raw_shift = None
        abs_distance = None
        aplus_prev_delta = None
        same_shift = None
        same_drift_direction = None

        if aplus_row is not None:
            offset_unit = str(aplus_row["offset_unit"]).strip()
            raw_offset_band = str(aplus_row["raw_offset_band"]).strip()
            if offset_unit != "days":
                comparability_reason = f"REJECTED_OFFSET_UNIT:{offset_unit}"
            else:
                parsed_offset = parse_finite_days(raw_offset_band)
                if parsed_offset is None:
                    comparability_reason = "REJECTED_NONFINITE_RAW_OFFSET_BAND"
                else:
                    comparability_reason = "COMPARABLE"
                    aplus_raw_shift = parsed_offset
                    market_selected_shift = market_row.get("selected_template_time_shift_days")
                    market_shift = float(market_selected_shift) if market_selected_shift not in ("", None) else None
                    if market_shift is not None:
                        abs_distance = round(abs(market_shift - parsed_offset), 6)
                        same_shift = market_shift == parsed_offset
                    aplus_prev_delta = aplus_previous_delta.get(key)
                    market_prev_delta = market_row.get("raw_shift_delta_days")
                    market_prev_delta_value = float(market_prev_delta) if market_prev_delta not in ("", None) else None
                    same_drift_direction = (
                        _direction(market_prev_delta_value) == _direction(aplus_prev_delta)
                        if market_prev_delta_value is not None and aplus_prev_delta is not None
                        else None
                    )

        output_rows.append(
            {
                "symbol": symbol,
                "raw_lattice_anchor_ts_utc": raw_anchor,
                "sensitivity_mode": market_row.get("sensitivity_mode", ""),
                "selection_status": market_row.get("selection_status", ""),
                "market_selected_shift_days": market_row.get("selected_template_time_shift_days", ""),
                "aplus_raw_shift_days": aplus_raw_shift,
                "absolute_shift_distance_days": abs_distance,
                "market_previous_delta_days": market_row.get("raw_shift_delta_days", ""),
                "aplus_previous_delta_days": aplus_prev_delta,
                "same_shift": same_shift,
                "same_drift_direction": same_drift_direction,
                "comparability_reason": comparability_reason,
                "source_artifact_id": aplus_row.get("source_artifact_id", "") if aplus_row else "",
                "source_claimed_timestamp_utc": aplus_row.get("source_claimed_timestamp_utc", "") if aplus_row else "",
                "raw_phase": aplus_row.get("raw_phase", "") if aplus_row else "",
                "raw_stability": aplus_row.get("raw_stability", "") if aplus_row else "",
            }
        )
    return output_rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    market_rows = read_csv(Path(args.market_continuity_csv))
    aplus_rows = read_csv(Path(args.aplus_csv))
    out_rows = build_rows(market_rows, aplus_rows)
    write_csv(
        Path(args.out_csv),
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "sensitivity_mode",
            "selection_status",
            "market_selected_shift_days",
            "aplus_raw_shift_days",
            "absolute_shift_distance_days",
            "market_previous_delta_days",
            "aplus_previous_delta_days",
            "same_shift",
            "same_drift_direction",
            "comparability_reason",
            "source_artifact_id",
            "source_claimed_timestamp_utc",
            "raw_phase",
            "raw_stability",
        ],
        out_rows,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
