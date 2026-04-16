from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    symbol,
    asset_id,
    entry_ts_utc,
    price_vs_ema20,
    price_vs_ema50,
    volume_ratio_20,
    volume_zscore_20,
    atr_pct,
    reversion_state_score,
    reversion_state_bucket,
    signal_family,
    next_return_4h
FROM v_known_signal_family_4h
WHERE next_return_4h IS NOT NULL
"""


NUMERIC_COLS = [
    "price_vs_ema20",
    "price_vs_ema50",
    "volume_ratio_20",
    "volume_zscore_20",
    "atr_pct",
    "reversion_state_score",
    "next_return_4h",
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

    if "entry_ts_utc" in df.columns:
        df["entry_ts_utc"] = pd.to_datetime(df["entry_ts_utc"], errors="coerce")

    return df


def grouped_returns(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return (
        df.groupby(group_cols, dropna=False)["next_return_4h"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )


def main() -> None:
    df = load_df()

    print("\n=== ROW COUNT ===")
    print(len(df))

    if df.empty:
        print("No rows returned from v_known_signal_family_4h.")
        return

    print("\n=== DATE RANGE ===")
    print(df["entry_ts_utc"].min(), "->", df["entry_ts_utc"].max())

    print("\n=== SIGNAL FAMILY SUMMARY (RECENT) ===")
    recent = df[df["entry_ts_utc"] >= pd.Timestamp("2026-01-01 00:00:00")].copy()
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

    print("\n=== TOP 15 MOMENTUM_CONTINUATION_4H_V1 ===")
    cols = [
        "symbol",
        "entry_ts_utc",
        "signal_family",
        "reversion_state_bucket",
        "reversion_state_score",
        "next_return_4h",
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
    ]
    top = recent[recent["signal_family"] == "MOMENTUM_CONTINUATION_4H_V1"].sort_values(
        ["next_return_4h", "reversion_state_score"],
        ascending=[False, True],
        na_position="last",
    )
    print(top[cols].head(15).to_string(index=False))

    print("\n=== TOP 15 REVERSION_EXTREME_4H_V1 ===")
    top = recent[recent["signal_family"] == "REVERSION_EXTREME_4H_V1"].sort_values(
        ["next_return_4h", "reversion_state_score"],
        ascending=[False, False],
        na_position="last",
    )
    print(top[cols].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
