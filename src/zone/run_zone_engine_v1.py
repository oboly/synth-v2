from __future__ import annotations

"""
ENGINE: run_zone_engine_v1
MODE: latest-only

INPUT:
- obs_market_candle
- asset

OUTPUT:
- fib_observation
- zone_observation
- execution_zone_context

CLI:
python -m src.zone.run_zone_engine_v1 \
  --venue bitvavo \
  --interval 4h \
  --sleeve-code SWING_STRUCTURAL \
  --lookback-candles 300 \
  --limit-assets 40 \
  --write-db

NOTES:
- v1 = fib + simple SR clustering
- direct execution handoff via execution_zone_context
- no Elliott dependency
"""

import argparse
import json
from decimal import Decimal
from typing import Any

from src.zone.engine_v1 import build_zone_engine_result
from src.zone.repository import ZoneRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run zone engine v1.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--sleeve-code", default="SWING_STRUCTURAL")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit-assets", type=int, default=40)
    parser.add_argument("--lookback-candles", type=int, default=300)
    parser.add_argument("--swing-window", type=int, default=2)
    parser.add_argument("--sr-tolerance-bps", default="60")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _row_from_result(repo: ZoneRepository, result) -> dict[str, Any]:
    row = repo.dump_result_row(result.execution_context)
    row["leg_direction"] = result.leg_direction
    row["zone_count"] = len(result.zones)
    return row


def _print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "asset_id",
        "symbol",
        "interval_code",
        "asof_ts_utc",
        "leg_direction",
        "entry_zone_low",
        "entry_zone_high",
        "entry_zone_type",
        "tp_zone_low",
        "tp_zone_high",
        "tp_zone_type",
        "invalidation_price",
        "zone_confidence_score",
        "zone_alignment_score",
        "zone_count",
    ]

    printable = []
    for row in rows:
        printable.append([str(row.get(h, "")) for h in headers])

    widths = [len(h) for h in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()
    repo = ZoneRepository()
    results = []

    assets = repo.fetch_assets(
        asset_id=args.asset_id,
        limit=args.limit_assets,
    )

    for asset in assets:
        candles = repo.fetch_recent_candles(
            asset_id=int(asset["asset_id"]),
            symbol=str(asset["symbol"]),
            venue=args.venue,
            interval_code=args.interval,
            limit=args.lookback_candles,
        )
        result = build_zone_engine_result(
            repo=repo,
            candles=candles,
            swing_window=args.swing_window,
            sr_tolerance_bps=Decimal(str(args.sr_tolerance_bps)),
            sleeve_code=args.sleeve_code,
        )
        if result is None:
            continue

        if args.write_db:
            repo.upsert_fib_observation(result.fib_observation)
            for zone in result.zones:
                repo.upsert_zone_observation(zone)
            repo.upsert_execution_zone_context(result.execution_context)

        results.append(_row_from_result(repo, result))

    if args.output == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        _print_table(results)

    print(f"processed_assets={len(assets)} results={len(results)} write_db={args.write_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
