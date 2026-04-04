from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.features.etl_candle_feat import (
    load_assets,
    run_feat_candle_for_asset_interval,
)


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

    return parser.parse_args()


def main() -> int:
    load_dotenv()

    args = parse_args()

    conn = get_db_connection()

    try:
        assets = load_assets(conn)

        # --- filter assets ---
        if args.asset:
            wanted = {s.upper() for s in args.asset}
            assets = [a for a in assets if a["symbol"] in wanted]

        intervals = args.interval if args.interval else ["1h", "4h", "1d"]
        venue = "bitvavo"

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
