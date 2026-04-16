from __future__ import annotations

import os
from typing import Optional, Dict, List

import pandas as pd
import pymysql
from dotenv import load_dotenv

from src.features.rejection_event import compute_rejection_events


UPSERT_SQL = """
INSERT INTO feat_rejection_event (
    asset_id,
    interval_code,
    open_ts_utc,
    is_sweep,
    is_reclaim,
    sweep_direction,
    sweep_distance_atr,
    reclaim_strength,
    wick_ratio,
    close_position,
    volume_ratio
)
VALUES (
    %(asset_id)s,
    %(interval_code)s,
    %(open_ts_utc)s,
    %(is_sweep)s,
    %(is_reclaim)s,
    %(sweep_direction)s,
    %(sweep_distance_atr)s,
    %(reclaim_strength)s,
    %(wick_ratio)s,
    %(close_position)s,
    %(volume_ratio)s
)
ON DUPLICATE KEY UPDATE
    is_sweep = VALUES(is_sweep),
    is_reclaim = VALUES(is_reclaim),
    sweep_direction = VALUES(sweep_direction),
    sweep_distance_atr = VALUES(sweep_distance_atr),
    reclaim_strength = VALUES(reclaim_strength),
    wick_ratio = VALUES(wick_ratio),
    close_position = VALUES(close_position),
    volume_ratio = VALUES(volume_ratio)
"""


def get_connection():
    load_dotenv()

    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def fetch_all_dicts(conn, sql: str, params: Optional[dict] = None) -> List[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return list(cur.fetchall())


def get_table_columns(conn, table_name: str) -> set[str]:
    sql = """
    SELECT COLUMN_NAME
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = %(table_name)s
    """
    rows = fetch_all_dicts(conn, sql, {"table_name": table_name})
    return {row["COLUMN_NAME"] for row in rows}


def pick_existing(columns: set[str], candidates: list[str], label: str) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise RuntimeError(
        f"No usable column found for '{label}'. Tried: {', '.join(candidates)}"
    )


def resolve_candle_mapping(conn) -> Dict[str, str]:
    columns = get_table_columns(conn, "obs_market_candle")

    mapping = {
        "asset_id": pick_existing(columns, ["asset_id"], "asset_id"),
        "interval_code": pick_existing(columns, ["interval_code"], "interval_code"),
        "open_ts_utc": pick_existing(columns, ["open_ts_utc"], "open_ts_utc"),
        "open": pick_existing(
            columns,
            ["open", "open_price", "open_price_eur", "price_open", "o"],
            "open",
        ),
        "high": pick_existing(
            columns,
            ["high", "high_price", "high_price_eur", "price_high", "h"],
            "high",
        ),
        "low": pick_existing(
            columns,
            ["low", "low_price", "low_price_eur", "price_low", "l"],
            "low",
        ),
        "close": pick_existing(
            columns,
            ["close", "close_price", "close_price_eur", "price_close", "c"],
            "close",
        ),
        "volume": pick_existing(
            columns,
            [
                "volume_base",
                "volume",
                "base_volume",
                "volume_qty",
                "volume_coin",
                "v",
            ],
            "volume",
        ),
        "venue": pick_existing(columns, ["venue"], "venue"),
    }

    return mapping


def load_candles(
    conn,
    interval_code: str,
    venue: str = "bitvavo",
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
) -> pd.DataFrame:
    mapping = resolve_candle_mapping(conn)

    print("[INFO] obs_market_candle mapping:")
    for k, v in mapping.items():
        print(f"  - {k} -> {v}")

    where = [
        f"{mapping['venue']} = %(venue)s",
        f"{mapping['interval_code']} = %(interval_code)s",
    ]
    params = {
        "venue": venue,
        "interval_code": interval_code,
    }

    if from_ts is not None:
        where.append(f"{mapping['open_ts_utc']} >= %(from_ts)s")
        params["from_ts"] = from_ts

    if to_ts is not None:
        where.append(f"{mapping['open_ts_utc']} < %(to_ts)s")
        params["to_ts"] = to_ts

    sql = f"""
    SELECT
        {mapping['asset_id']} AS asset_id,
        {mapping['interval_code']} AS interval_code,
        {mapping['open_ts_utc']} AS open_ts_utc,
        {mapping['open']} AS open,
        {mapping['high']} AS high,
        {mapping['low']} AS low,
        {mapping['close']} AS close,
        {mapping['volume']} AS volume
    FROM obs_market_candle
    WHERE {" AND ".join(where)}
    ORDER BY asset_id, open_ts_utc
    """

    rows = fetch_all_dicts(conn, sql, params)
    if not rows:
        return pd.DataFrame(
            columns=["asset_id", "interval_code", "open_ts_utc", "open", "high", "low", "close", "volume"]
        )

    df = pd.DataFrame(rows)

    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def sanitize_output(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    keep_cols = [
        "asset_id",
        "interval_code",
        "open_ts_utc",
        "is_sweep",
        "is_reclaim",
        "sweep_direction",
        "sweep_distance_atr",
        "reclaim_strength",
        "wick_ratio",
        "close_position",
        "volume_ratio",
    ]
    out = out[keep_cols]

    out["is_sweep"] = out["is_sweep"].fillna(False).astype(int)
    out["is_reclaim"] = out["is_reclaim"].fillna(False).astype(int)

    numeric_cols = [
        "sweep_distance_atr",
        "reclaim_strength",
        "wick_ratio",
        "close_position",
        "volume_ratio",
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.replace([pd.NA, float("inf"), float("-inf")], None)
    out = out.where(pd.notnull(out), None)

    return out


def run(
    interval_code: str = "4h",
    venue: str = "bitvavo",
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
) -> int:
    conn = get_connection()
    try:
        candles = load_candles(
            conn=conn,
            interval_code=interval_code,
            venue=venue,
            from_ts=from_ts,
            to_ts=to_ts,
        )

        if candles.empty:
            print("[INFO] no candle rows found")
            return 0

        result_frames = []

        for asset_id, asset_df in candles.groupby("asset_id", sort=False):
            work = asset_df.copy().reset_index(drop=True)
            enriched = compute_rejection_events(work)
            result_frames.append(enriched)

        result = pd.concat(result_frames, ignore_index=True)
        result = sanitize_output(result)

        rows = result.to_dict(orient="records")

        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)

        conn.commit()
        print(f"[DONE] feat_rejection_event rows={len(rows)} interval={interval_code}")
        return len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    args = parser.parse_args()

    run(
        interval_code=args.interval,
        venue=args.venue,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
    )
