#!/usr/bin/env python3
"""
Synth ETL
Source: CoinGecko
Target table: market_global_snapshot
Purpose: macro crypto market context
"""

import requests
import pymysql
from datetime import datetime, timezone

URL = "https://api.coingecko.com/api/v3/global"


def fetch():

    r = requests.get(URL, timeout=10)
    r.raise_for_status()

    return r.json()["data"]


def upsert(db, row):

    sql = """
    INSERT INTO market_global_snapshot (
        provider,
        ts_utc,
        total_market_cap_usd,
        total_volume_usd_24h,
        btc_dominance_pct,
        eth_dominance_pct,
        active_cryptocurrencies,
        markets
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """

    with db.cursor() as c:
        c.execute(sql, row)

    db.commit()


def run(db):

    d = fetch()

    ts = datetime.now(timezone.utc)

    row = (
        "coingecko",
        ts,
        d["total_market_cap"]["usd"],
        d["total_volume"]["usd"],
        d["market_cap_percentage"]["btc"],
        d["market_cap_percentage"]["eth"],
        d["active_cryptocurrencies"],
        d["markets"]
    )

    upsert(db, row)
