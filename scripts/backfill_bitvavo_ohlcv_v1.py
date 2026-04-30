from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BASE_URL = "https://api.bitvavo.com/v2"
DEFAULT_DATABASE = "synth"
DEFAULT_TABLE = "obs_market_candle"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVALS = "1h"
DEFAULT_FROM_TS = "2021-01-01 00:00:00"
DEFAULT_TO_TS = "2026-04-28 00:00:00"

INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}

MAX_LIMIT = 1440


@dataclass(frozen=True)
class AssetRow:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class CandleRow:
    asset_id: int
    venue: str
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume_base: Decimal
    volume_quote_eur: Decimal | None
    trade_count: int | None


def parse_ts(value: str) -> datetime:
    normalized = value.strip().replace("T", " ")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def ms(dt: datetime) -> int:
    aware = dt.replace(tzinfo=timezone.utc)
    return int(aware.timestamp() * 1000)


def dt_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)


def split_csv(value: str | None) -> list[str]:
    if value is None or not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def split_symbols(value: str | None) -> list[str]:
    return [item.upper() for item in split_csv(value)]


def split_intervals(value: str | None) -> list[str]:
    return [item.lower() for item in split_csv(value)]


def fetch_json(path: str, params: dict[str, Any], *, retries: int, sleep_seconds: float) -> Any:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"

    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"Content-Type": "application/json"})

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                time.sleep(sleep_seconds)
                return json.loads(body)

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")

            if exc.code == 429:
                wait = min(60, 5 * attempt)
                print(f"RATE_LIMIT: wait {wait}s url={url}")
                time.sleep(wait)
                continue

            if exc.code in {404, 400}:
                print(f"SKIP_HTTP_{exc.code}: {url} body={body[:200]}")
                return []

            if attempt == retries:
                raise

            wait = min(30, 3 * attempt)
            print(f"HTTP_RETRY_{exc.code}: attempt={attempt} wait={wait}s url={url}")
            time.sleep(wait)

        except Exception as exc:
            if attempt == retries:
                raise

            wait = min(30, 3 * attempt)
            print(f"ERROR_RETRY: attempt={attempt} wait={wait}s error={exc}")
            time.sleep(wait)

    return []


def table_exists(database: str, table: str) -> bool:
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s
                """,
                [database, table],
            )
            row = cur.fetchone()
            return bool(row and int(row["n"]) > 0)
    finally:
        conn.close()


def table_columns(database: str, table: str) -> set[str]:
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                """,
                [database, table],
            )
            return {str(row["column_name"]) for row in cur.fetchall()}
    finally:
        conn.close()


def load_assets(database: str, symbols: list[str]) -> list[AssetRow]:
    wanted = set(symbols)

    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT asset_id, symbol
                FROM asset
                WHERE symbol IS NOT NULL
                ORDER BY asset_id ASC
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    out: list[AssetRow] = []
    for row in rows:
        symbol = str(row["symbol"]).upper()
        if wanted and symbol not in wanted:
            continue
        out.append(AssetRow(asset_id=int(row["asset_id"]), symbol=symbol))

    return out


def bitvavo_market(symbol: str) -> str:
    if "-" in symbol:
        return symbol.upper()
    return f"{symbol.upper()}-EUR"


def fetch_candles_for_range(
    *,
    asset: AssetRow,
    interval: str,
    from_ts: datetime,
    to_ts: datetime,
    venue: str,
    retries: int,
    sleep_seconds: float,
) -> list[CandleRow]:
    interval_seconds = INTERVAL_SECONDS[interval]
    step = timedelta(seconds=interval_seconds * MAX_LIMIT)
    cursor = from_ts
    candles: list[CandleRow] = []
    market = bitvavo_market(asset.symbol)

    while cursor < to_ts:
        chunk_end = min(cursor + step, to_ts)

        payload = fetch_json(
            f"/{market}/candles",
            {
                "interval": interval,
                "start": ms(cursor),
                "end": ms(chunk_end),
                "limit": MAX_LIMIT,
            },
            retries=retries,
            sleep_seconds=sleep_seconds,
        )

        if not isinstance(payload, list):
            print(f"SKIP_BAD_PAYLOAD: market={market} interval={interval} payload={payload}")
            cursor = chunk_end
            continue

        for item in payload:
            if not isinstance(item, list) or len(item) < 6:
                continue

            open_ts = dt_from_ms(int(item[0]))
            if open_ts < from_ts or open_ts >= to_ts:
                continue

            close_ts = open_ts + timedelta(seconds=interval_seconds)
            open_price = Decimal(str(item[1]))
            high_price = Decimal(str(item[2]))
            low_price = Decimal(str(item[3]))
            close_price = Decimal(str(item[4]))
            volume_base = Decimal(str(item[5]))
            volume_quote_eur = close_price * volume_base

            candles.append(
                CandleRow(
                    asset_id=asset.asset_id,
                    venue=venue,
                    interval_code=interval,
                    open_ts_utc=open_ts,
                    close_ts_utc=close_ts,
                    open_price=open_price,
                    high_price=high_price,
                    low_price=low_price,
                    close_price=close_price,
                    volume_base=volume_base,
                    volume_quote_eur=volume_quote_eur,
                    trade_count=None,
                )
            )

        cursor = chunk_end

    candles.sort(key=lambda row: row.open_ts_utc)
    return candles


def insert_candles(database: str, table: str, columns: set[str], rows: list[CandleRow]) -> int:
    if not rows:
        return 0

    base_fields = [
        "asset_id",
        "venue",
        "interval_code",
        "open_ts_utc",
        "close_ts_utc",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume_base",
        "volume_quote_eur",
        "trade_count",
        "source_ts_utc",
        "ingest_ts_utc",
    ]

    fields = [field for field in base_fields if field in columns]

    update_fields = [
        field
        for field in fields
        if field
        not in {
            "asset_id",
            "venue",
            "interval_code",
            "open_ts_utc",
            "source_ts_utc",
            "ingest_ts_utc",
        }
    ]

    placeholders = ", ".join(["%s"] * len(fields))
    field_sql = ", ".join(fields)
    update_sql = ", ".join([f"{field} = VALUES({field})" for field in update_fields])

    if update_sql:
        sql = f"INSERT INTO {table} ({field_sql}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_sql}"
    else:
        sql = f"INSERT IGNORE INTO {table} ({field_sql}) VALUES ({placeholders})"

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    values: list[list[Any]] = []
    for row in rows:
        mapping = {
            "asset_id": row.asset_id,
            "venue": row.venue,
            "interval_code": row.interval_code,
            "open_ts_utc": row.open_ts_utc,
            "close_ts_utc": row.close_ts_utc,
            "open_price": row.open_price,
            "high_price": row.high_price,
            "low_price": row.low_price,
            "close_price": row.close_price,
            "volume_base": row.volume_base,
            "volume_quote_eur": row.volume_quote_eur,
            "trade_count": row.trade_count,
            "source_ts_utc": now,
            "ingest_ts_utc": now,
        }
        values.append([mapping[field] for field in fields])

    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, values)
        conn.commit()
    finally:
        conn.close()

    return len(values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Bitvavo EUR OHLCV candles into obs_market_candle."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--from-ts", default=DEFAULT_FROM_TS)
    parser.add_argument("--to-ts", default=DEFAULT_TO_TS)
    parser.add_argument("--intervals", default=DEFAULT_INTERVALS)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--limit-assets", type=int, default=0)
    parser.add_argument("--sleep-seconds", type=float, default=0.08)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from_ts = parse_ts(args.from_ts)
    to_ts = parse_ts(args.to_ts)
    intervals = split_intervals(args.intervals)
    symbols = split_symbols(args.symbols)

    if not intervals:
        raise SystemExit("No intervals supplied.")

    for interval in intervals:
        if interval not in INTERVAL_SECONDS:
            raise SystemExit(f"Unsupported interval: {interval}")

    if not table_exists(args.database, args.table):
        raise SystemExit(f"Missing table: {args.database}.{args.table}")

    columns = table_columns(args.database, args.table)
    required = {"asset_id", "venue", "interval_code", "open_ts_utc", "close_price"}
    missing = sorted(required - columns)
    if missing:
        raise SystemExit(f"Table {args.table} is missing required columns: {missing}")

    assets = load_assets(args.database, symbols)
    if args.limit_assets and args.limit_assets > 0:
        assets = assets[: args.limit_assets]

    print("Bitvavo OHLCV backfill")
    print(f"database: {args.database}")
    print(f"table: {args.table}")
    print(f"venue: {args.venue}")
    print(f"from_ts: {from_ts}")
    print(f"to_ts: {to_ts}")
    print(f"intervals: {intervals}")
    print(f"assets: {len(assets)}")
    print(f"dry_run: {args.dry_run}")
    print()

    grand_fetched = 0
    grand_written = 0

    for asset in assets:
        for interval in intervals:
            print(f"--- {asset.symbol} {interval} ---")
            rows = fetch_candles_for_range(
                asset=asset,
                interval=interval,
                from_ts=from_ts,
                to_ts=to_ts,
                venue=args.venue,
                retries=args.retries,
                sleep_seconds=args.sleep_seconds,
            )

            fetched = len(rows)
            written = 0 if args.dry_run else insert_candles(args.database, args.table, columns, rows)

            grand_fetched += fetched
            grand_written += written

            first = rows[0].open_ts_utc if rows else None
            last = rows[-1].open_ts_utc if rows else None

            print(f"fetched: {fetched}")
            print(f"written: {written}")
            print(f"first: {first}")
            print(f"last: {last}")

    print()
    print("--- summary ---")
    print(f"assets: {len(assets)}")
    print(f"intervals: {intervals}")
    print(f"fetched_total: {grand_fetched}")
    print(f"written_total: {grand_written}")
    print("writes: obs_market_candle only")
    print("orders: none")
    print("live_execution_permission: NOT_GRANTED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
