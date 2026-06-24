from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from src.market_context.breath_curve_core_v1 import (
    Candle,
    MARKERS,
    CORE_VERSION,
    MarkerMatch,
    MatchResult,
    find_marker,
    gt,
    iso,
    lt,
    match,
    parse_dt,
    parse_offsets,
    shape_score,
)

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    import pymysql
except Exception:
    pymysql = None

VERSION = CORE_VERSION


def env_any(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def db_connect() -> Any:
    if pymysql is None:
        raise RuntimeError("pymysql not installed. Use --csv or install pymysql.")

    if load_dotenv:
        load_dotenv()

    return pymysql.connect(
        host=env_any("SYNTH_DB_HOST", "DB_HOST", "MYSQL_HOST", default="127.0.0.1"),
        port=int(env_any("SYNTH_DB_PORT", "DB_PORT", "MYSQL_PORT", default="3306")),
        user=env_any("SYNTH_DB_USER", "DB_USER", "MYSQL_USER", default="root"),
        password=env_any("SYNTH_DB_PASSWORD", "DB_PASSWORD", "MYSQL_PASSWORD", default=""),
        database=env_any("SYNTH_DB_NAME", "DB_NAME", "MYSQL_DATABASE", default="synth"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def table_cols(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            """,
            (table_name,),
        )
        return {row["COLUMN_NAME"] for row in cur.fetchall()}


def choose(cols: set[str], options: list[str], required: bool = True) -> str | None:
    for option in options:
        if option in cols:
            return option
    if required:
        raise RuntimeError(f"Missing expected column. Tried: {options}")
    return None


def resolve_asset_id(conn: Any, symbol: str) -> int:
    cols = table_cols(conn, "asset")
    id_col = choose(cols, ["asset_id", "id"])
    symbol_col = choose(cols, ["symbol", "asset_code", "code", "base_symbol", "ticker"])

    candidates = sorted({
        symbol,
        symbol.upper(),
        symbol.replace("-EUR", "").upper(),
        symbol.replace("/EUR", "").upper(),
        symbol.replace("USDT", "").upper(),
    })

    placeholders = ",".join(["%s"] * len(candidates))
    sql = f"SELECT `{id_col}` AS asset_id FROM asset WHERE `{symbol_col}` IN ({placeholders}) LIMIT 1"

    with conn.cursor() as cur:
        cur.execute(sql, tuple(candidates))
        row = cur.fetchone()

    if not row:
        raise RuntimeError(f"Could not resolve asset_id for symbol={symbol}. Try --asset-id.")

    return int(row["asset_id"])


def load_db(symbol: str, asset_id: int | None, venue: str, interval_code: str, start: datetime, end: datetime) -> list[Candle]:
    conn = db_connect()
    try:
        cols = table_cols(conn, "obs_market_candle")

        asset_col = choose(cols, ["asset_id"])
        ts_col = choose(cols, ["open_ts_utc", "close_ts_utc", "ts_utc", "timestamp_utc"])
        open_col = choose(cols, ["open", "open_price", "close_open", "o"])
        high_col = choose(cols, ["high", "high_price", "close_high", "h"])
        low_col = choose(cols, ["low", "low_price", "close_low", "l"])
        close_col = choose(cols, ["close", "close_price", "close_close", "c"])
        venue_col = choose(cols, ["venue"], required=False)
        interval_col = choose(cols, ["interval_code", "timeframe"], required=False)
        aid = asset_id if asset_id is not None else resolve_asset_id(conn, symbol)

        where = [f"`{asset_col}` = %s", f"`{ts_col}` >= %s", f"`{ts_col}` <= %s"]
        params: list[Any] = [aid, iso(start), iso(end)]

        if venue_col:
            where.append(f"`{venue_col}` = %s")
            params.append(venue)

        if interval_col:
            where.append(f"`{interval_col}` = %s")
            params.append(interval_code)

        sql = f"""
            SELECT
                `{ts_col}` AS ts,
                `{open_col}` AS open_price,
                `{high_col}` AS high_price,
                `{low_col}` AS low_price,
                `{close_col}` AS close_price
            FROM obs_market_candle
            WHERE {' AND '.join(where)}
            ORDER BY `{ts_col}` ASC
        """

        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

        out: list[Candle] = []
        for row in rows:
            ts = row["ts"]
            if isinstance(ts, str):
                dt = parse_dt(ts)
            else:
                dt = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)

            out.append(Candle(
                ts=dt,
                open=float(row["open_price"]),
                high=float(row["high_price"]),
                low=float(row["low_price"]),
                close=float(row["close_price"]),
            ))

        return out
    finally:
        conn.close()


def load_csv(path: str) -> list[Candle]:
    out: list[Candle] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ts = row.get("open_ts_utc") or row.get("timestamp") or row.get("ts") or row.get("time")
            if not ts:
                raise RuntimeError("CSV requires open_ts_utc, timestamp, ts, or time.")
            out.append(Candle(
                ts=parse_dt(ts),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return sorted(out, key=lambda c: c.ts)


def print_result(result: MatchResult) -> None:
    print(f"symbol={result.symbol} venue={result.venue} interval={result.interval_code}")
    print(f"anchor={result.anchor_ts_utc} cycle_days={result.cycle_days} offset_days={result.phase_offset_days}")
    print(f"template_match_score={result.template_match_score:.4f}")
    print(f"shape_score={result.shape_score:.4f} timing_score={result.timing_score:.4f}")
    print("")
    print("flags:")
    for key, value in result.flags.items():
        print(f"  {key}={value}")
    print("")
    print("markers:")
    for marker in result.markers:
        price = "None" if marker.observed_price is None else f"{marker.observed_price:.8f}"
        error = "None" if marker.timing_error_hours is None else f"{marker.timing_error_hours:.2f}h"
        print(
            f"  {marker.ratio:.3f} {marker.code:26s} "
            f"expected={marker.expected_ts_utc} observed={marker.observed_ts_utc} "
            f"price={price} error={error} score={marker.timing_score:.4f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only 21-day breath curve template matcher.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--anchor-date", required=True)
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument("--offsets", default="-10.5,-7,-5,-3,0,3,5,7,10.5")
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    anchor = parse_dt(args.anchor_date)
    offsets = parse_offsets(args.offsets)

    query_start = anchor + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours + 48)
    query_end = anchor + timedelta(days=args.cycle_days * 1.272 + max(offsets)) + timedelta(hours=args.tolerance_hours + 48)

    if args.csv:
        candles = [c for c in load_csv(args.csv) if query_start <= c.ts <= query_end]
    else:
        candles = load_db(args.symbol, args.asset_id, args.venue, args.interval_code, query_start, query_end)

    if len(candles) < 5:
        raise RuntimeError(f"Not enough candles loaded: {len(candles)}")

    results = [
        match(candles, args.symbol, args.venue, args.interval_code, anchor, args.cycle_days, offset, args.tolerance_hours)
        for offset in offsets
    ]

    best = max(results, key=lambda r: r.template_match_score)

    if args.json:
        print(json.dumps({
            "matcher": "breath_curve_template_matcher_v1",
            "version": VERSION,
            "best": asdict(best),
            "all_offsets": [asdict(r) for r in results],
        }, indent=2, sort_keys=True))
    else:
        print(f"matcher=breath_curve_template_matcher_v1 version={VERSION}")
        print_result(best)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
