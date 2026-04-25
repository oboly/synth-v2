from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


SOURCE_DB = "synth"
INTERVAL_TO_MINUTES = {"1h": 60, "4h": 240, "1d": 1440}


@dataclass
class Row:
    regime: str
    bonus: Decimal
    touched: int
    ret: Decimal | None


def _d(x):
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--venue", default="bitvavo")
    p.add_argument("--interval-codes", nargs="+", default=["4h"])
    p.add_argument("--from-ts", required=True)
    p.add_argument("--to-ts", required=True)
    p.add_argument("--horizon-candles", type=int, default=3)
    return p.parse_args()


def fetch_ctx(args):
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ec.asset_id, ec.interval_code, ec.asof_ts_utc,
                       ec.expected_entry_zone_low, ec.expected_entry_zone_high,
                       ec.source_ref_json
                FROM execution_zone_context ec
                WHERE ec.venue=%s
                  AND ec.asof_ts_utc >= %s
                  AND ec.asof_ts_utc < %s
                """,
                [args.venue, args.from_ts, args.to_ts],
            )
            return cur.fetchall()
    finally:
        conn.close()


def fetch_future(asset_id, venue, interval, start, minutes):
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT high_price, low_price, close_price
                FROM obs_market_candle
                WHERE asset_id=%s AND venue=%s AND interval_code=%s
                  AND open_ts_utc >= %s
                LIMIT %s
                """,
                [asset_id, venue, interval, start, minutes],
            )
            return cur.fetchall()
    finally:
        conn.close()


def main():
    args = parse_args()
    rows = fetch_ctx(args)

    out: list[Row] = []

    for r in rows:
        js = {}
        try:
            js = json.loads(r["source_ref_json"] or "{}")
        except:
            pass

        fib = js.get("fib_overlay", {})
        if not fib:
            continue

        bonus = _d(fib.get("total_bonus"))
        regime = fib.get("profile_regime_label", "UNK")

        low = r["expected_entry_zone_low"]
        high = r["expected_entry_zone_high"]

        if low is None or high is None:
            continue

        low = _d(low)
        high = _d(high)
        mid = (low + high) / 2

        future = fetch_future(
            r["asset_id"],
            args.venue,
            r["interval_code"],
            r["asof_ts_utc"],
            args.horizon_candles,
        )

        touched = 0
        for c in future:
            if _d(c["low_price"]) <= high and _d(c["high_price"]) >= low:
                touched = 1
                break

        ret = None
        if future:
            last = future[-1]
            if mid != 0:
                ret = (_d(last["close_price"]) - mid) / mid

        out.append(Row(regime, bonus, touched, ret))

    by = defaultdict(list)
    for r in out:
        by[r.regime].append(r)

    print("\nsummary")
    print("regime | rows | touched_rate | avg_bonus | avg_return")

    for k, v in by.items():
        tr = sum(x.touched for x in v) / len(v)
        ab = sum(x.bonus for x in v) / len(v)
        rets = [x.ret for x in v if x.ret is not None]
        ar = sum(rets) / len(rets) if rets else 0
        print(f"{k} | {len(v)} | {tr:.3f} | {ab:.4f} | {ar:.4f}")

    print(f"\nrows={len(out)}")


if __name__ == "__main__":
    main()
