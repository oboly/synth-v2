#!/usr/bin/env python3
"""
Synth ETL
Source: Bitvavo
Target table: venue_ticker_24h
Purpose: snapshot rolling 24h venue stats
"""

import requests
import pymysql
from datetime import datetime, timezone

BITVAVO_URL = "https://api.bitvavo.com/v2/ticker/24h"


def fetch_data():
    r = requests.get(BITVAVO_URL, timeout=10)
    r.raise_for_status()
    return r.json()


def upsert(db, rows):

    sql = """
    INSERT INTO venue_ticker_24h (
        venue,
        market_symbol,
        base_asset,
        quote_asset,
        ts_utc,
        last_price,
        bid,
        ask,
        open_24h,
        high_24h,
        low_24h,
        volume_base_24h,
        volume_quote_24h
    )
    VALUES (
        %s,%s,%s,%s,%s,
        %s,%s,%s,%s,%s,%s,%s,%s
    )
    ON DUPLICATE KEY UPDATE
        last_price=VALUES(last_price),
        bid=VALUES(bid),
        ask=VALUES(ask),
        volume_base_24h=VALUES(volume_base_24h),
        volume_quote_24h=VALUES(volume_quote_24h)
    """

    with db.cursor() as c:
        c.executemany(sql, rows)

    db.commit()


def run(db):

    data = fetch_data()

    ts = datetime.now(timezone.utc)

    rows = []

    for m in data:

        symbol = m["market"]
        base, quote = symbol.split("-")

        rows.append((
            "bitvavo",
            symbol,
            base,
            quote,
            ts,
            m.get("last"),
            m.get("bid"),
            m.get("ask"),
            m.get("open"),
            m.get("high"),
            m.get("low"),
            m.get("volume"),
            m.get("volumeQuote")
        ))

    upsert(db, rows)
