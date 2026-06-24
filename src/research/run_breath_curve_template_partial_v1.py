from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import timedelta

from src.market_context.breath_curve_core_v1 import (
    CORE_VERSION,
    PartialResult,
    parse_offsets,
    partial_match,
)
from src.research.breath_curve_template_matcher_v1 import (
    load_db,
    parse_dt,
)


VERSION = CORE_VERSION

def print_result(result: PartialResult) -> None:
    print(f"partial_matcher=breath_curve_template_partial_v1 version={VERSION}")
    print(f"symbol={result.symbol} venue={result.venue} interval={result.interval_code}")
    print(f"anchor={result.anchor_ts_utc} as_of={result.as_of_ts_utc}")
    print(f"cycle_days={result.cycle_days} offset_days={result.phase_offset_days} required_ratio={result.required_ratio}")
    print(f"partial_match_score={result.partial_match_score:.4f}")
    print(f"shape={result.partial_shape_score:.4f} timing={result.partial_timing_score:.4f} coverage={result.marker_coverage_score:.4f}")
    print(f"observed_markers={result.observed_marker_count} due_markers={result.due_marker_count}")
    print(f"shape_rules={result.passed_shape_rule_count}/{result.available_shape_rule_count}")
    print(f"notes={','.join(result.notes) if result.notes else 'None'}")
    print("")
    print("flags:")
    for key, value in result.flags.items():
        print(f"  {key}={value}")
    print("")
    print("markers:")
    for marker in result.markers:
        price = "None" if marker["observed_price"] is None else f'{float(marker["observed_price"]):.8f}'
        print(
            f'  {marker["ratio"]:.3f} {marker["code"]:26s} '
            f'status={marker["status"]:23s} '
            f'expected={marker["expected_ts_utc"]} '
            f'observed={marker["observed_ts_utc"]} '
            f'price={price} '
            f'score={float(marker["timing_score"]):.4f}'
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Partial-cycle research-only breath curve matcher with as-of cutoff."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--anchor-date", required=True)
    parser.add_argument("--as-of-ts", required=True)
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument("--offsets", default="-10.5,-7,-5,-3,0,3,5,7,10.5")
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument("--min-due-markers", type=int, default=3)
    parser.add_argument("--required-ratio", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    anchor = parse_dt(args.anchor_date)
    as_of = parse_dt(args.as_of_ts)
    offsets = parse_offsets(args.offsets)

    if as_of < anchor + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours):
        raise RuntimeError("as-of timestamp is too early for the tested offset grid.")

    query_start = anchor + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours + 48)
    query_end = as_of

    candles = load_db(
        symbol=args.symbol,
        asset_id=None,
        venue=args.venue,
        interval_code=args.interval_code,
        start=query_start,
        end=query_end,
    )

    if len(candles) < 3:
        raise RuntimeError(f"Not enough candles loaded before as-of: {len(candles)}")

    results = [
        partial_match(
            candles=candles,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=args.interval_code,
            anchor=anchor,
            as_of=as_of,
            cycle_days=args.cycle_days,
            offset_days=offset,
            tolerance_hours=args.tolerance_hours,
            min_due_markers=args.min_due_markers,
            required_ratio=args.required_ratio,
        )
        for offset in offsets
    ]

    best = max(results, key=lambda r: r.partial_match_score)

    if args.json:
        print(json.dumps(
            {
                "matcher": "breath_curve_template_partial_v1",
                "version": VERSION,
                "best": asdict(best),
                "all_offsets": [asdict(r) for r in results],
            },
            indent=2,
            sort_keys=True,
        ))
    else:
        print_result(best)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
