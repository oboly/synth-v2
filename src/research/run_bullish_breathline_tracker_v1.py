"""CLI for the research-only bullish Breathline tracker v1.

Consumes an explicit candle CSV and writes only research artifacts under the selected
output directory. It does not write operational database state or call a broker.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from src.research.bullish_breathline_tracker_v1 import (
    HALF_PHASE_SPLIT_CANDIDATE_DAYS,
    IGNITION_RATIO_GRID,
    MODEL_VERSION,
    NORMAL_PHASE_OFFSETS_DAYS,
    RECOGNITION_RATIO_GRID,
    CandleObservation,
    append_cycle_ledger,
    calibrate_checkpoint_grid,
    cycle_to_jsonable,
    detect_confirmed_pivots,
    extract_bullish_cycles,
    walk_forward_checkpoint_evidence,
)


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _first(row: dict[str, str], names: Iterable[str]) -> str | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def load_candles(path: Path) -> list[CandleObservation]:
    rows: list[CandleObservation] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            ts = _first(row, ("ts", "timestamp", "ts_utc", "open_time", "candle_ts_utc"))
            open_value = _first(row, ("open", "open_price"))
            high = _first(row, ("high", "high_price"))
            low = _first(row, ("low", "low_price"))
            close = _first(row, ("close", "close_price"))
            volume = _first(row, ("volume", "volume_base", "base_volume"))
            if None in (ts, open_value, high, low, close):
                raise ValueError(f"missing required candle field at CSV row {row_number}")
            rows.append(
                CandleObservation(
                    ts=parse_ts(str(ts)),
                    open=float(str(open_value)),
                    high=float(str(high)),
                    low=float(str(low)),
                    close=float(str(close)),
                    volume=None if volume is None else float(str(volume)),
                )
            )
    rows.sort(key=lambda candle: candle.ts)
    if not rows:
        raise ValueError("candle CSV is empty")
    return rows


def calibration_to_jsonable(value: object) -> dict[str, object]:
    payload = asdict(value)  # type: ignore[arg-type]
    payload["frozen_grid"] = list(payload["frozen_grid"])
    payload["discovery_cycle_ids"] = list(payload["discovery_cycle_ids"])
    payload["holdout_cycle_ids"] = list(payload["holdout_cycle_ids"])
    return payload


def run(*, csv_path: Path, symbol: str, out_dir: Path) -> dict[str, object]:
    candles = load_candles(csv_path)
    pivots = detect_confirmed_pivots(candles)
    cycles = extract_bullish_cycles(symbol, candles, pivots)
    out_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = out_dir / "cycle_ledger.jsonl"
    appended_count = append_cycle_ledger(ledger_path, cycles)

    recognition = calibrate_checkpoint_grid(cycles, "recognition") if cycles else None
    ignition = calibrate_checkpoint_grid(cycles, "ignition") if cycles else None
    walk_forward = {
        "recognition": walk_forward_checkpoint_evidence(cycles, "recognition"),
        "ignition": walk_forward_checkpoint_evidence(cycles, "ignition"),
    }

    summary: dict[str, object] = {
        "model_version": MODEL_VERSION,
        "symbol": symbol,
        "source_csv": str(csv_path),
        "candle_count": len(candles),
        "confirmed_pivot_count": len(pivots),
        "cycle_count": len(cycles),
        "ledger_appended_count": appended_count,
        "research_only": True,
        "normal_phase_offsets_days": list(NORMAL_PHASE_OFFSETS_DAYS),
        "half_phase_split_candidate_days": HALF_PHASE_SPLIT_CANDIDATE_DAYS,
        "recognition_ratio_grid": list(RECOGNITION_RATIO_GRID),
        "ignition_ratio_grid": list(IGNITION_RATIO_GRID),
        "recognition_calibration": None if recognition is None else calibration_to_jsonable(recognition),
        "ignition_calibration": None if ignition is None else calibration_to_jsonable(ignition),
        "walk_forward": walk_forward,
        "safety": {
            "account_awareness": 0,
            "selection_engine_changes": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "latest_cycles.json").write_text(
        json.dumps([cycle_to_jsonable(cycle) for cycle in cycles], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Point-in-time candle CSV")
    parser.add_argument("--symbol", required=True, help="Single research symbol, e.g. RENDER")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/research/bullish_breathline_tracker_v1"),
        help="Research artifact directory",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = run(csv_path=args.csv, symbol=args.symbol, out_dir=args.out_dir)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
