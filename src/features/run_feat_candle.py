from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.features.etl_candle_feat import (
    load_assets,
    run_feat_candle_for_asset_interval,
)


def parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run feat_candle ETL"
    )

    parser.add_argument(
        "--asset",
        action="append",
        default=None,
        help="Filter by symbol, e.g. --asset BTC --asset SOL",
    )

    parser.add_argument(
        "--interval",
        action="append",
        default=None,
        help="Filter by interval, e.g. --interval 1h --interval 4h",
    )

    parser.add_argument(
        "--start",
        default=None,
        help="Optional write-window start timestamp, e.g. 2026-05-01T00:00:00+00:00",
    )

    parser.add_argument(
        "--end",
        default=None,
        help="Optional write-window end timestamp, e.g. 2026-05-08T00:00:00+00:00",
    )

    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=None,
        help="Optional bounded write-window lookback from --end or now, in hours.",
    )

    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=300,
        help="Bars loaded before the write-window for indicator warmup. Default: 300.",
    )

    return parser.parse_args()


def resolve_write_window(args: argparse.Namespace) -> tuple[datetime | None, datetime | None]:
    end_ts = parse_iso_utc(args.end) if args.end else datetime.now(UTC)

    if args.start and args.lookback_hours is not None:
        raise ValueError("Use either --start or --lookback-hours, not both.")

    if args.start:
        return parse_iso_utc(args.start), end_ts

    if args.lookback_hours is not None:
        if args.lookback_hours <= 0:
            raise ValueError("--lookback-hours must be positive.")
        return end_ts - timedelta(hours=args.lookback_hours), end_ts

    if args.end:
        return None, end_ts

    return None, None


def main() -> int:
    load_dotenv()

    args = parse_args()
    write_start_ts_utc, write_end_ts_utc = resolve_write_window(args)

    conn = get_db_connection()

    try:
        assets = load_assets(conn)

        if args.asset:
            wanted = {s.upper() for s in args.asset}
            assets = [a for a in assets if a["symbol"] in wanted]

        intervals = args.interval if args.interval else ["1h", "4h", "1d"]
        venue = "bitvavo"

        print(
            "[INFO] feat_candle window "
            f"start={write_start_ts_utc.isoformat() if write_start_ts_utc else 'FULL'} "
            f"end={write_end_ts_utc.isoformat() if write_end_ts_utc else 'OPEN'} "
            f"warmup_bars={args.warmup_bars}"
        )

        total_rows = 0

        for asset in assets:
            asset_id = asset["asset_id"]
            symbol = asset["symbol"]

            for interval in intervals:
                print(
                    f"[RUN] symbol={symbol} asset_id={asset_id} "
                    f"interval={interval}"
                )

                rows = run_feat_candle_for_asset_interval(
                    conn=conn,
                    asset_id=asset_id,
                    venue=venue,
                    interval_code=interval,
                    write_start_ts_utc=write_start_ts_utc,
                    write_end_ts_utc=write_end_ts_utc,
                    warmup_bars=args.warmup_bars,
                )

                total_rows += rows

                print(
                    f"[DONE] symbol={symbol} interval={interval} rows={rows}"
                )

        print(f"[DONE] total_rows={total_rows}")
        return 0

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
