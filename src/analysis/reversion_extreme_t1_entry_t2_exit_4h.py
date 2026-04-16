from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    symbol,
    signal_ts_utc,
    entry_ts_utc,
    exit_ts_utc,
    price_vs_ema20,
    price_vs_ema50,
    volume_ratio_20,
    volume_zscore_20,
    atr_pct,
    reversion_state_score,
    reversion_state_bucket,
    signal_family,
    entry_open_price,
    exit_close_price,
    forward_return_t1_open_to_t2_close_4h
FROM v_reversion_extreme_t1_entry_t2_exit_4h
WHERE forward_return_t1_open_to_t2_close_4h IS NOT NULL
"""


NUMERIC_COLS = [
    "price_vs_ema20",
    "price_vs_ema50",
    "volume_ratio_20",
    "volume_zscore_20",
    "atr_pct",
    "reversion_state_score",
    "entry_open_price",
    "exit_close_price",
    "forward_return_t1_open_to_t2_close_4h",
]


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def load_df() -> pd.DataFrame:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    for col in df.columns:
        df[col] = df[col].map(_normalize_scalar)

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["signal_ts_utc", "entry_ts_utc", "exit_ts_utc"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def grouped_returns(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return (
        df.groupby(group_cols, dropna=False)["forward_return_t1_open_to_t2_close_4h"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )


def main() -> None:
    df = load_df()

    print("\n=== ROW COUNT ===")
    print(len(df))

    if df.empty:
        print("No rows returned from v_reversion_extreme_t1_entry_t2_exit_4h.")
        return

    recent = df[df["signal_ts_utc"] >= pd.Timestamp("2026-01-01 00:00:00")].copy()

    print("\n=== DATE RANGE (RECENT) ===")
    if recent.empty:
        print("No recent rows.")
        return
    print(recent["signal_ts_utc"].min(), "->", recent["signal_ts_utc"].max())

    print("\n=== SIGNAL FAMILY SUMMARY (RECENT) ===")
    print(grouped_returns(recent, ["signal_family"]))

    print("\n=== SIGNAL FAMILY x BUCKET (RECENT) ===")
    print(grouped_returns(recent, ["signal_family", "reversion_state_bucket"]))

    print("\n=== FEATURE MEANS BY SIGNAL FAMILY (RECENT) ===")
    cols = [
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
        "atr_pct",
        "reversion_state_score",
    ]
    print(recent.groupby("signal_family", dropna=False)[cols].mean().sort_index())

    print("\n=== TOP 20 TARGET SIGNAL ===")
    cols = [
        "symbol",
        "signal_ts_utc",
        "entry_ts_utc",
        "exit_ts_utc",
        "signal_family",
        "reversion_state_bucket",
        "reversion_state_score",
        "forward_return_t1_open_to_t2_close_4h",
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
    ]
    top = recent[
        recent["signal_family"] == "REVERSION_EXTREME_T1_ENTRY_T2_EXIT_4H_V1"
    ].sort_values(
        ["forward_return_t1_open_to_t2_close_4h", "reversion_state_score"],
        ascending=[False, False],
        na_position="last",
    )
    print(top[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
