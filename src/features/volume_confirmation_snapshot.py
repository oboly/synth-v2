from __future__ import annotations

import os
from statistics import mean, pstdev

import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv

load_dotenv(".env")


def get_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        cursorclass=DictCursor,
        autocommit=False,
    )


def run_volume_confirmation_snapshot(interval: str = "1d"):
    conn = get_connection()

    # 🔹 haal candles op
    sql = """
    SELECT asset_id, close_ts_utc, volume_quote_eur
    FROM obs_market_candle
    WHERE interval_code = %s
    ORDER BY asset_id, close_ts_utc
    """

    with conn.cursor() as cur:
        cur.execute(sql, (interval,))
        rows = cur.fetchall()

    # 🔹 groepeer per asset
    per_asset = {}
    for r in rows:
        aid = r["asset_id"]
        per_asset.setdefault(aid, []).append(r)

    inserts = []

    for aid, series in per_asset.items():
        if len(series) < 14:
            continue

        snapshot_ts = series[-1]["close_ts_utc"]

        for lookback in (7, 14):
            window = series[-lookback:]
            volumes = [float(x["volume_quote_eur"] or 0.0) for x in window]

            current = volumes[-1]
            hist = volumes[:-1]

            if not hist:
                continue

            avg = mean(hist)
            std = pstdev(hist) if len(hist) > 1 else 0.0

            ratio = current / avg if avg > 0 else 0.0
            z = (current - avg) / std if std > 0 else 0.0

            inserts.append((
                snapshot_ts,
                aid,
                lookback,
                ratio,
                z,
                current,
                avg,
                std,
            ))

    insert_sql = """
    INSERT INTO volume_confirmation_snapshot (
        snapshot_ts_utc,
        asset_id,
        lookback_days,
        volume_ratio,
        volume_zscore,
        current_volume_quote_eur,
        avg_volume_quote_eur,
        std_volume_quote_eur
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
        volume_ratio = VALUES(volume_ratio),
        volume_zscore = VALUES(volume_zscore),
        current_volume_quote_eur = VALUES(current_volume_quote_eur),
        avg_volume_quote_eur = VALUES(avg_volume_quote_eur),
        std_volume_quote_eur = VALUES(std_volume_quote_eur)
    """

    with conn.cursor() as cur:
        cur.executemany(insert_sql, inserts)

    conn.commit()
    conn.close()

    print({
        "interval": interval,
        "rows_written": len(inserts),
        "assets": len(per_asset)
    })
