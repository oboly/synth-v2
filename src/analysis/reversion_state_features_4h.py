from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    symbol,
    asset_id,
    venue,
    interval_code,
    entry_ts_utc,
    price_vs_ema20,
    price_vs_ema50,
    volume_ratio_20,
    volume_zscore_20,
    atr_pct,
    reversion_state_score,
    reversion_state_bucket,
    entry_close_price,
    next_ts_utc,
    next_close_price,
    next_return_4h
FROM v_reversion_state_features_4h
"""


NUMERIC_COLS = [
    "price_vs_ema20",
    "price_vs_ema50",
    "volume_ratio_20",
    "volume_zscore_20",
    "atr_pct",
    "reversion_state_score",
    "entry_close_price",
    "next_close_price",
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

    for col in ["entry_ts_utc", "next_ts_utc"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

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
        print("No rows returned from v_reversion_state_features_4h.")
        return

    print("\n=== DATE RANGE ===")
    print(df["entry_ts_utc"].min(), "->", df["entry_ts_utc"].max())

    print("\n=== NULL RATES ===")
    print(df.isnull().mean().sort_values(ascending=False).head(20))

    print("\n=== BUCKET SUMMARY ===")
    print(grouped_returns(df[df["next_return_4h"].notna()], ["reversion_state_bucket"]))

    print("\n=== FEATURE MEANS BY BUCKET ===")
    cols = [
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
        "atr_pct",
        "reversion_state_score",
    ]
    print(df.groupby("reversion_state_bucket", dropna=False)[cols].mean().sort_index())

    print("\n=== TOP 20 NEXT_RETURN_4H ===")
    cols = [
        "symbol",
        "entry_ts_utc",
        "reversion_state_bucket",
        "reversion_state_score",
        "next_return_4h",
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
    ]
    top = df.sort_values(
        ["next_return_4h", "reversion_state_score"],
        ascending=[False, False],
        na_position="last",
    )
    print(top[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
