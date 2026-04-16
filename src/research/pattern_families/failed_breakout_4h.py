from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    symbol,
    entry_ts_utc,
    signal_family,
    next_return_4h
FROM v_failed_breakout_4h
WHERE next_return_4h IS NOT NULL
"""


def normalize(v: Any):
    if isinstance(v, Decimal):
        return float(v)
    return v


def main() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    df = pd.DataFrame(rows)

    if df.empty:
        print("No data")
        return

    for c in df.columns:
        df[c] = df[c].map(normalize)

    if "signal_family" in df.columns:
        df = df[df["signal_family"].notna()].copy()
        df = df[df["signal_family"].astype(str) != "signal_family"].copy()

    if "entry_ts_utc" in df.columns:
        df["entry_ts_utc"] = pd.to_datetime(df["entry_ts_utc"], errors="coerce")

    if "next_return_4h" in df.columns:
        df["next_return_4h"] = pd.to_numeric(df["next_return_4h"], errors="coerce")

    df = df[df["entry_ts_utc"].notna()].copy()
    df = df[df["next_return_4h"].notna()].copy()

    recent = df[df["entry_ts_utc"] >= pd.Timestamp("2026-01-01 00:00:00")].copy()

    print("\n=== DATE RANGE ===")
    if recent.empty:
        print("No recent rows after cleaning.")
        print("Raw min/max:", df["entry_ts_utc"].min(), "->", df["entry_ts_utc"].max())
        return

    print(recent["entry_ts_utc"].min(), "->", recent["entry_ts_utc"].max())

    print("\n=== SUMMARY ===")
    print(
        recent.groupby("signal_family", dropna=False)["next_return_4h"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )

    print("\n=== TOP 20 MOST NEGATIVE ===")
    top = recent[
        recent["signal_family"] == "FAILED_BREAKOUT_4H_V1"
    ].sort_values("next_return_4h", ascending=True, na_position="last")

    print(top.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
