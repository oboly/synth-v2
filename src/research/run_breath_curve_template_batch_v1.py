from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.research.breath_curve_template_matcher_v1 import (
    load_db,
    match,
    parse_dt,
    parse_offsets,
)


VERSION = "0.1"


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "status",
        "symbol",
        "anchor_ts_utc",
        "cycle_days",
        "best_phase_offset_days",
        "template_match_score",
        "shape_score",
        "timing_score",
        "tolerance_hours",
        "venue",
        "interval_code",
        "error",
    ]

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def best_result_to_summary(result: Any) -> dict[str, Any]:
    return {
        "status": "OK",
        "symbol": result.symbol,
        "anchor_ts_utc": result.anchor_ts_utc,
        "cycle_days": result.cycle_days,
        "best_phase_offset_days": result.phase_offset_days,
        "template_match_score": result.template_match_score,
        "shape_score": result.shape_score,
        "timing_score": result.timing_score,
        "tolerance_hours": result.tolerance_hours,
        "venue": result.venue,
        "interval_code": result.interval_code,
        "error": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch runner for research-only 21-day breath curve template matching."
    )
    parser.add_argument(
        "--symbols",
        default="BTC,ETH,TAO,RENDER,FIL,HBAR,XLM,PEPE",
        help="Comma-separated symbols.",
    )
    parser.add_argument(
        "--anchors",
        required=True,
        help="Comma-separated anchor dates, e.g. 2026-03-01,2026-03-22.",
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument("--offsets", default="-10.5,-7,-5,-3,0,3,5,7,10.5")
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument(
        "--out-dir",
        default="data/research/breath_curve_template_matcher_v1",
    )
    args = parser.parse_args()

    symbols = parse_csv_list(args.symbols)
    anchors = [parse_dt(x) for x in parse_csv_list(args.anchors)]
    offsets = parse_offsets(args.offsets)
    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []

    for anchor in anchors:
        min_offset = min(offsets)
        max_offset = max(offsets)

        query_start = anchor + timedelta(days=min_offset) - timedelta(hours=args.tolerance_hours + 48)
        query_end = anchor + timedelta(days=args.cycle_days * 1.272 + max_offset) + timedelta(
            hours=args.tolerance_hours + 48
        )

        for symbol in symbols:
            try:
                candles = load_db(
                    symbol=symbol,
                    asset_id=None,
                    venue=args.venue,
                    interval_code=args.interval_code,
                    start=query_start,
                    end=query_end,
                )

                if len(candles) < 5:
                    raise RuntimeError(f"Not enough candles loaded: {len(candles)}")

                results = [
                    match(
                        candles=candles,
                        symbol=symbol,
                        venue=args.venue,
                        interval_code=args.interval_code,
                        anchor=anchor,
                        cycle_days=args.cycle_days,
                        offset_days=offset,
                        tolerance_hours=args.tolerance_hours,
                    )
                    for offset in offsets
                ]

                best = max(results, key=lambda r: r.template_match_score)

                summary_rows.append(best_result_to_summary(best))
                detail_rows.append(
                    {
                        "status": "OK",
                        "symbol": symbol,
                        "anchor_ts_utc": best.anchor_ts_utc,
                        "best_phase_offset_days": best.phase_offset_days,
                        "best": asdict(best),
                        "all_offsets": [asdict(r) for r in results],
                    }
                )

                print(
                    f"OK symbol={symbol} anchor={best.anchor_ts_utc} "
                    f"offset={best.phase_offset_days} "
                    f"score={best.template_match_score:.4f} "
                    f"shape={best.shape_score:.4f} "
                    f"timing={best.timing_score:.4f}"
                )

            except Exception as exc:
                err = str(exc)
                anchor_text = anchor.replace(microsecond=0).isoformat().replace("+00:00", "Z")
                summary_rows.append(
                    {
                        "status": "ERROR",
                        "symbol": symbol,
                        "anchor_ts_utc": anchor_text,
                        "cycle_days": args.cycle_days,
                        "best_phase_offset_days": None,
                        "template_match_score": None,
                        "shape_score": None,
                        "timing_score": None,
                        "tolerance_hours": args.tolerance_hours,
                        "venue": args.venue,
                        "interval_code": args.interval_code,
                        "error": err,
                    }
                )
                detail_rows.append(
                    {
                        "status": "ERROR",
                        "symbol": symbol,
                        "anchor_ts_utc": anchor_text,
                        "error": err,
                    }
                )
                print(f"ERROR symbol={symbol} anchor={anchor_text} error={err}")

    csv_path = out_dir / f"breath_curve_template_batch_v1_{stamp}.csv"
    jsonl_path = out_dir / f"breath_curve_template_batch_v1_{stamp}.jsonl"

    write_csv(csv_path, summary_rows)
    write_jsonl(jsonl_path, detail_rows)

    print("")
    print(f"wrote_csv={csv_path}")
    print(f"wrote_jsonl={jsonl_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
