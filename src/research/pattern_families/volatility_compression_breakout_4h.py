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
    next_return_4h,
    atr_pct,
    range_pct
FROM v_volatility_compression_breakout_4h
WHERE next_return_4h IS NOT NULL
"""


NUMERIC_COLS = [
    "next_return_4h",
    "atr_pct",
    "range_pct",
]


def normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


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

    for col in df.columns:
        df[col] = df[col].map(normalize)

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "entry_ts_utc" in df.columns:
        df["entry_ts_utc"] = pd.to_datetime(df["entry_ts_utc"], errors="coerce")

    if "signal_family" in df.columns:
        df = df[df["signal_family"].notna()].copy()
        df = df[df["signal_family"].astype(str) != "signal_family"].copy()

    recent = df[df["entry_ts_utc"] >= pd.Timestamp("2026-01-01 00:00:00")].copy()

    print("\n=== SUMMARY ===")
    print(
        recent.groupby("signal_family", dropna=False)["next_return_4h"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )

    print("\n=== FEATURE MEANS ===")
    print(
        recent.groupby("signal_family", dropna=False)[["atr_pct", "range_pct"]]
        .mean()
        .sort_index()
    )

    print("\n=== TOP 20 ===")
    top = recent[
        recent["signal_family"] == "VOLATILITY_COMPRESSION_BREAKOUT_4H_V1"
    ].sort_values("next_return_4h", ascending=False, na_position="last")
    print(top.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
