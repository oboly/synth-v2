from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.asset_profile.asset_profile_engine_v1 import (
    PROFILE_VERSION,
    build_asset_profiles,
    from_ts_for_lookback,
)
from src.asset_profile.repository import AssetProfileRepository


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("T", " "))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build derived asset profile snapshots from market data."
    )
    parser.add_argument("--database", default="synth")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--asof-ts", required=True)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--benchmark-symbols", default="BTC,ETH")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def print_table(payload: dict[str, Any]) -> None:
    print("Asset profile snapshot preview")
    for key in [
        "database",
        "venue",
        "interval",
        "asof_ts_utc",
        "lookback_days",
        "profile_version",
        "benchmark_symbols",
        "rows",
        "write_db",
        "written",
    ]:
        print(f"{key}: {payload[key]}")

    print()
    print("symbol | liquidity_class | liquidity_score | beta_profile | beta | vol | coverage")
    print("-" * 120)

    for row in payload["profiles"]:
        print(
            f"{row['symbol']} | "
            f"{row['liquidity_class']} | "
            f"{row['liquidity_score']} | "
            f"{row['beta_profile']} | "
            f"{row['beta_to_market']} | "
            f"{row['realized_volatility']} | "
            f"{row['coverage_ratio']}"
        )

    print()
    print("--- interpretation ---")
    print("READ_ONLY unless --write-db is provided.")
    print("SECTOR_GROUP: intentionally null in v1.")
    print("LIVE_EXECUTION_PERMISSION: NOT_GRANTED")


def main() -> int:
    args = parse_args()

    asof_ts_utc = parse_ts(args.asof_ts)
    from_ts_utc = from_ts_for_lookback(asof_ts_utc, args.lookback_days)
    benchmark_symbols = [
        item.strip().upper()
        for item in str(args.benchmark_symbols).split(",")
        if item.strip()
    ]

    repo = AssetProfileRepository(database=args.database)
    market_rows = repo.fetch_market_rows(
        venue=args.venue,
        interval_code=args.interval,
        from_ts_utc=from_ts_utc.isoformat(sep=" "),
        asof_ts_utc=asof_ts_utc.isoformat(sep=" "),
    )

    profiles = build_asset_profiles(
        market_rows=market_rows,
        venue=args.venue,
        interval_code=args.interval,
        asof_ts_utc=asof_ts_utc,
        lookback_days=args.lookback_days,
        benchmark_symbols=benchmark_symbols,
    )

    written = 0
    if args.write_db:
        written = repo.upsert_snapshots(profiles)

    payload = {
        "database": args.database,
        "venue": args.venue,
        "interval": args.interval,
        "asof_ts_utc": asof_ts_utc,
        "lookback_days": args.lookback_days,
        "profile_version": PROFILE_VERSION,
        "benchmark_symbols": ",".join(benchmark_symbols),
        "rows": len(profiles),
        "write_db": bool(args.write_db),
        "written": written,
        "profiles": [asdict(row) for row in profiles],
    }

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
