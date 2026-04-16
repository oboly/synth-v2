from __future__ import annotations

import os
from typing import Optional, List

import pandas as pd
import pymysql
from dotenv import load_dotenv

from src.strategies.rejection_event_score import compute_rejection_score


UPSERT_SQL = """
INSERT INTO advice_state (
    asset_id,
    interval_code,
    open_ts_utc,
    policy_name,
    score
)
VALUES (
    %(asset_id)s,
    %(interval_code)s,
    %(open_ts_utc)s,
    %(policy_name)s,
    %(score)s
)
ON DUPLICATE KEY UPDATE
    policy_name = VALUES(policy_name),
    score = VALUES(score)
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


def load_events(
    conn,
    interval_code: str,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
) -> pd.DataFrame:
    where = ["interval_code = %(interval_code)s"]
    params = {"interval_code": interval_code}

    if from_ts is not None:
        where.append("open_ts_utc >= %(from_ts)s")
        params["from_ts"] = from_ts

    if to_ts is not None:
        where.append("open_ts_utc < %(to_ts)s")
        params["to_ts"] = to_ts

    sql = f"""
    SELECT
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
    FROM feat_rejection_event
    WHERE {" AND ".join(where)}
    ORDER BY asset_id, open_ts_utc
    """

    rows = fetch_all_dicts(conn, sql, params)
    if not rows:
        return pd.DataFrame(
            columns=[
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
        )

    return pd.DataFrame(rows)


def build_output(df: pd.DataFrame) -> pd.DataFrame:
    scored = compute_rejection_score(df)

    out = scored[
        [
            "asset_id",
            "interval_code",
            "open_ts_utc",
            "policy_name",
            "rejection_score",
        ]
    ].copy()

    out = out.rename(columns={"rejection_score": "score"})
    out = out[out["policy_name"].notna()].copy()

    out = out.replace([pd.NA, float("inf"), float("-inf")], None)
    out = out.where(pd.notnull(out), None)

    return out


def run(
    interval_code: str = "4h",
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
) -> int:
    conn = get_connection()
    try:
        events = load_events(
            conn=conn,
            interval_code=interval_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )

        if events.empty:
            print("[INFO] no rejection event rows found")
            return 0

        output = build_output(events)

        if output.empty:
            print("[INFO] no scored rejection policies found")
            return 0

        rows = output.to_dict(orient="records")

        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)

        conn.commit()
        print(f"[DONE] advice_state rejection rows={len(rows)} interval={interval_code}")
        return len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    args = parser.parse_args()

    run(
        interval_code=args.interval,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
    )
