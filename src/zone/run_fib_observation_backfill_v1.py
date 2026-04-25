from __future__ import annotations

"""
ENGINE: run_fib_observation_backfill_v1
MODE: historical

INPUT:
- obs_market_candle
- asset

OUTPUT:
- fib_observation_v2

CLI:
python -m src.zone.run_fib_observation_backfill_v1 \
  --venue bitvavo \
  --interval 4h \
  --from-ts "2026-03-01 00:00:00" \
  --to-ts "2026-04-22 00:00:00" \
  --lookback-candles 300 \
  --min-candles 40 \
  --limit-assets 40 \
  --write-db

HISTORICAL:
- supported

NOTES:
- backfills historical fib_observation_v2 snapshots
- reuses zone engine leg detection logic
- writes only fib_observation_v2 in this runner
- no per-candle DB queries; bulk fetch per asset, local loop
"""

import argparse
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.zone.engine_v1 import build_zone_engine_result
from src.zone.models import CandleRow
from src.zone.repository import ZoneRepository


@dataclass(frozen=True)
class AssetRow:
    asset_id: int
    symbol: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill fib_observation_v2 from historical candles.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit-assets", type=int, default=40)
    parser.add_argument("--lookback-candles", type=int, default=300)
    parser.add_argument("--min-candles", type=int, default=40)
    parser.add_argument("--swing-window", type=int, default=2)
    parser.add_argument("--sr-tolerance-bps", default="60")
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fetch_assets(*, asset_id: int | None, limit: int) -> list[AssetRow]:
    params: list[Any] = []
    asset_filter_sql = ""
    if asset_id is not None:
        asset_filter_sql = "AND asset_id = %s"
        params.append(asset_id)

    params.append(limit)

    sql = f"""
    SELECT
        asset_id,
        symbol
    FROM asset
    WHERE is_enabled = 1
      AND is_tradeable = 1
      {asset_filter_sql}
    ORDER BY asset_id
    LIMIT %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [AssetRow(asset_id=int(r["asset_id"]), symbol=str(r["symbol"])) for r in rows]


def fetch_candles(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    from_ts: str,
    to_ts: str,
) -> list[CandleRow]:
    sql = """
    SELECT
        asset_id,
        venue,
        interval_code,
        open_ts_utc,
        close_ts_utc,
        open_price,
        high_price,
        low_price,
        close_price
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND open_ts_utc >= %s
      AND open_ts_utc < %s
    ORDER BY open_ts_utc
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [asset_id, venue, interval_code, from_ts, to_ts])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        CandleRow(
            asset_id=int(row["asset_id"]),
            symbol=symbol,
            venue=str(row["venue"]),
            interval_code=str(row["interval_code"]),
            open_ts_utc=row["open_ts_utc"],
            close_ts_utc=row["close_ts_utc"],
            open_price=_to_decimal(row["open_price"]),
            high_price=_to_decimal(row["high_price"]),
            low_price=_to_decimal(row["low_price"]),
            close_price=_to_decimal(row["close_price"]),
        )
        for row in rows
    ]


def main() -> int:
    args = parse_args()
    repo = ZoneRepository()

    assets = fetch_assets(asset_id=args.asset_id, limit=args.limit_assets)
    sr_tolerance_bps = Decimal(str(args.sr_tolerance_bps))

    total_assets = len(assets)
    total_snapshots = 0
    total_written = 0

    for asset_idx, asset in enumerate(assets, start=1):
        candles = fetch_candles(
            asset_id=asset.asset_id,
            symbol=asset.symbol,
            venue=args.venue,
            interval_code=args.interval,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
        )

        if len(candles) < args.min_candles:
            print(
                f"asset_progress={asset_idx}/{total_assets} "
                f"asset_id={asset.asset_id} symbol={asset.symbol} "
                f"candles={len(candles)} snapshots=0 written=0 skipped=not_enough_candles"
            )
            continue

        asset_snapshots = 0
        asset_written = 0

        for end_idx in range(args.min_candles, len(candles) + 1):
            start_idx = max(0, end_idx - args.lookback_candles)
            subset = candles[start_idx:end_idx]

            result = build_zone_engine_result(
                repo=repo,
                candles=subset,
                swing_window=args.swing_window,
                sr_tolerance_bps=sr_tolerance_bps,
                sleeve_code="BACKFILL_UNUSED",
            )
            asset_snapshots += 1
            total_snapshots += 1

            if result is None:
                continue

            if args.write_db:
                repo.upsert_fib_observation(result.fib_observation)
                asset_written += 1
                total_written += 1

        last_close = candles[-1].close_ts_utc if candles else None
        print(
            f"asset_progress={asset_idx}/{total_assets} "
            f"asset_id={asset.asset_id} symbol={asset.symbol} "
            f"candles={len(candles)} snapshots={asset_snapshots} "
            f"written={asset_written} last_close_ts={last_close}"
        )

    print(
        f"done assets={total_assets} "
        f"total_snapshots={total_snapshots} "
        f"total_written={total_written} "
        f"write_db={args.write_db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
