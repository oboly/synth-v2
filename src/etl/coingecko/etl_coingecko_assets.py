#!/usr/bin/env python3
"""
Synth ETL
Source: CoinGecko
Target table: asset_market_snapshot
Purpose: global coin market structure
"""

import requests
import pymysql
from datetime import datetime, timezone

URL = "https://api.coingecko.com/api/v3/coins/markets"


def fetch():

    params = dict(
        vs_currency="usd",
        order="market_cap_desc",
        per_page=250,
        page=1,
        sparkline="false"
    )

    r = requests.get(URL, params=params, timeout=15)
    r.raise_for_status()

    return r.json()


def upsert(db, rows):

    sql = """
    INSERT INTO asset_market_snapshot (
        provider,
        asset_id_provider,
        asset_symbol,
        ts_utc,
        price_usd,
        market_cap_usd,
        fully_diluted_valuation_usd,
        total_volume_usd_24h,
        circulating_supply,
        total_supply,
        max_supply,
        market_cap_rank
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    with db.cursor() as c:
        c.executemany(sql, rows)

    db.commit()


def run(db):

    data = fetch()

    ts = datetime.now(timezone.utc)

    rows = []

    for c in data:

        rows.append((
            "coingecko",
            c["id"],
            c["symbol"].upper(),
            ts,
            c.get("current_price"),
            c.get("market_cap"),
            c.get("fully_diluted_valuation"),
            c.get("total_volume"),
            c.get("circulating_supply"),
            c.get("total_supply"),
            c.get("max_supply"),
            c.get("market_cap_rank")
        ))

    upsert(db, rows)
