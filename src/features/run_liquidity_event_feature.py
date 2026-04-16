#!/usr/bin/env python3
from __future__ import annotations

import os
import pandas as pd
import numpy as np
import pymysql
from dotenv import load_dotenv


def get_conn():
    load_dotenv()
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD") or "",
        database=os.getenv("DB_NAME"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def fetch_candles(conn):
    sql = """
    SELECT
        asset_id,
        venue,
        interval_code,
        open_ts_utc,
        open,
        high,
        low,
        close,
        volume_base
    FROM obs_market_candle
    WHERE interval_code = '1h'
    ORDER BY asset_id, open_ts_utc
    """
    return pd.read_sql(sql, conn)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["range"] = df["high"] - df["low"]
    df["body"] = (df["close"] - df["open"]).abs()
    df["wick"] = df["range"] - df["body"]

    df["wick_ratio"] = df["wick"] / df["range"]
    df["body_ratio"] = df["body"] / df["range"]

    # rolling z-scores
    df["volume_z"] = df.groupby("asset_id")["volume_base"].transform(
        lambda x: (x - x.rolling(50).mean()) / x.rolling(50).std()
    )

    df["range_z"] = df.groupby("asset_id")["range"].transform(
        lambda x: (x - x.rolling(50).mean()) / x.rolling(50).std()
    )

    # flags
    df["sweep_flag"] = (
        (df["wick_ratio"] > 0.6) &
        (df["range_z"] > 1.2)
    ).astype(int)

    # rejection = close terug richting midden
    mid = df["low"] + (df["range"] / 2)
    df["rejection_flag"] = (
        ((df["close"] - mid).abs() < df["range"] * 0.25)
    ).astype(int)

    # normalize z-scores
    df["volume_z_n"] = df["volume_z"].clip(-3, 3) / 3
    df["range_z_n"] = df["range_z"].clip(-3, 3) / 3

    df["liquidity_event_score"] = (
        df["wick_ratio"] * 0.4 +
        df["volume_z_n"] * 0.3 +
        df["range_z_n"] * 0.3
    )

    return df


def write_db(conn, df):
    rows = []

    for _, r in df.iterrows():
        rows.append((
            int(r.asset_id),
            r.venue,
            r.interval_code,
            r.open_ts_utc,
            float(r.wick_ratio) if pd.notna(r.wick_ratio) else None,
            float(r.body_ratio) if pd.notna(r.body_ratio) else None,
            float(r.range) if pd.notna(r.range) else None,
            float(r.volume_z) if pd.notna(r.volume_z) else None,
            float(r.range_z) if pd.notna(r.range_z) else None,
            int(r.sweep_flag),
            int(r.rejection_flag),
            float(r.liquidity_event_score) if pd.notna(r.liquidity_event_score) else None,
        ))

    sql = """
    INSERT INTO feat_liquidity_event (
        asset_id, venue, interval_code, open_ts_utc,
        wick_ratio, body_ratio, range_size,
        volume_zscore, range_zscore,
        sweep_flag, rejection_flag,
        liquidity_event_score
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
        wick_ratio=VALUES(wick_ratio),
        body_ratio=VALUES(body_ratio),
        range_size=VALUES(range_size),
        volume_zscore=VALUES(volume_zscore),
        range_zscore=VALUES(range_zscore),
        sweep_flag=VALUES(sweep_flag),
        rejection_flag=VALUES(rejection_flag),
        liquidity_event_score=VALUES(liquidity_event_score)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def main():
    conn = get_conn()

    df = fetch_candles(conn)
    df = compute_features(df)
    write_db(conn, df)

    print("[OK] liquidity_event features written")


if __name__ == "__main__":
    main()
