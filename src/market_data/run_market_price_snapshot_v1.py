from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import requests

from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import (
    MarketPriceSnapshot,
    insert_market_price_snapshots,
    split_market_symbol,
    utc_now_naive,
)


REPORT_NAME = "market_price_snapshot_v1"
REPORT_VERSION = "0.1"

BITVAVO_TICKER_PRICE_URL = "https://api.bitvavo.com/v2/ticker/price"
SOURCE_NAME = "bitvavo_public_ticker_price"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write centralized public market price snapshots from Bitvavo /ticker/price."
    )
    parser.add_argument("--venue", choices=("bitvavo",), default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json", "none"), default="table")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    return parser.parse_args()


def fetch_bitvavo_ticker_prices(*, timeout_seconds: int) -> list[dict[str, Any]]:
    response = requests.get(BITVAVO_TICKER_PRICE_URL, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected Bitvavo /ticker/price response shape: {type(data)}")
    return data


def build_snapshots(
    payload: list[dict[str, Any]],
    *,
    venue: str,
    quote_currency: str,
    observed_ts_utc: datetime,
) -> list[MarketPriceSnapshot]:
    quote = quote_currency.upper()
    snapshots: list[MarketPriceSnapshot] = []

    for row in payload:
        if not isinstance(row, dict):
            continue
        market_raw = row.get("market")
        price_raw = row.get("price")
        if market_raw is None or price_raw is None:
            continue

        market = str(market_raw).strip().upper()
        symbol = split_market_symbol(market, quote)
        if symbol is None:
            continue

        snapshots.append(
            MarketPriceSnapshot(
                venue=venue.lower(),
                symbol=symbol,
                market=market,
                quote_currency=quote,
                price=Decimal(str(price_raw)),
                source_name=SOURCE_NAME,
                source_ts_utc=None,
                observed_ts_utc=observed_ts_utc,
            )
        )

    snapshots.sort(key=lambda item: item.symbol)
    return snapshots


def serialize_snapshot(snapshot: MarketPriceSnapshot) -> dict[str, Any]:
    data = asdict(snapshot)
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = str(value)
        elif isinstance(value, datetime):
            data[key] = value.isoformat(sep=" ")
    return data


def print_table(snapshots: list[MarketPriceSnapshot]) -> None:
    headers = ["symbol", "market", "quote", "price", "observed_ts_utc"]
    table = [
        [
            snapshot.symbol,
            snapshot.market,
            snapshot.quote_currency,
            str(snapshot.price),
            snapshot.observed_ts_utc.isoformat(sep=" "),
        ]
        for snapshot in snapshots
    ]
    widths = [
        max(len(headers[idx]), *(len(row[idx]) for row in table)) if table else len(headers[idx])
        for idx in range(len(headers))
    ]

    def fmt(row: list[str]) -> str:
        return " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(row)))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))
    for row in table:
        print(fmt(row))


def main() -> int:
    args = parse_args()
    authorization = None
    if args.write_db:
        from src.operations.writer_capability_authorization_v1 import (
            require_capability_write_authorization,
        )

        # Final mandatory authorization boundary before any mutation and before
        # any network work. A direct invocation cannot bypass ownership.
        authorization = require_capability_write_authorization(
            "public_price_snapshot",
            service="synth-market-price-snapshot-writer.service",
        )
    quote = args.quote.upper()
    observed_ts_utc = utc_now_naive()

    payload = fetch_bitvavo_ticker_prices(timeout_seconds=args.timeout_seconds)
    snapshots = build_snapshots(
        payload,
        venue=args.venue,
        quote_currency=quote,
        observed_ts_utc=observed_ts_utc,
    )

    written = 0
    if args.write_db:
        conn = get_connection()
        try:
            written = insert_market_price_snapshots(conn, snapshots, authorization=authorization)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    if args.output != "none":
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print("scope=public-market-price-snapshot")
        print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
        print("account_awareness=0 decision_gate=none execution_planner=none executor=none")
        print(
            f"venue={args.venue} quote={quote} fetched_rows={len(payload)} "
            f"snapshot_rows={len(snapshots)} db_writes={written if args.write_db else 0}"
        )
        print()
        if args.output == "json":
            print(json.dumps([serialize_snapshot(row) for row in snapshots], indent=2, sort_keys=True))
        elif args.output == "table":
            print_table(snapshots)

    if args.output == "none":
        print(
            f"[DONE] report={REPORT_NAME} version={REPORT_VERSION} venue={args.venue} quote={quote} "
            f"snapshot_rows={len(snapshots)} db_writes={written if args.write_db else 0} "
            "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
            "account_awareness=0 executor=none"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
