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
    state_ts_utc,
    reversion_state_score,
    score_bucket,
    is_rejected_htf_4h,
    price_vs_ema20,
    price_vs_ema50,
    volume_ratio_20,
    volume_zscore_20,
    close_price,
    next_close_price,
    next_4h_return
FROM v_reversion_state_vs_rejected_htf_4h_recent
WHERE next_4h_return IS NOT NULL
"""


NUMERIC_COLS = [
    "reversion_state_score",
    "is_rejected_htf_4h",
    "price_vs_ema20",
    "price_vs_ema50",
    "volume_ratio_20",
    "volume_zscore_20",
    "close_price",
    "next_close_price",
    "next_4h_return",
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

    for col in ["entry_ts_utc", "state_ts_utc"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def grouped_returns(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return (
        df.groupby(group_cols, dropna=False)["next_4h_return"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )


def main() -> None:
    df = load_df()

    print("\n=== ROW COUNT ===")
    print(len(df))

    if df.empty:
        print("No rows returned from v_reversion_state_vs_rejected_htf_4h_recent.")
        return

    print("\n=== DATE RANGE ===")
    print(df["entry_ts_utc"].min(), "->", df["entry_ts_utc"].max())

    print("\n=== STATE ALIGNMENT LAG HOURS ===")
    lag_hours = (df["entry_ts_utc"] - df["state_ts_utc"]).dt.total_seconds() / 3600.0
    print(lag_hours.describe())

    print("\n=== NULL RATES ===")
    print(df.isnull().mean().sort_values(ascending=False).head(20))

    print("\n=== SCORE BUCKET SUMMARY ===")
    print(grouped_returns(df, ["score_bucket"]))

    print("\n=== TOP 20 ===")
    cols = [
        "symbol",
        "entry_ts_utc",
        "state_ts_utc",
        "score_bucket",
        "reversion_state_score",
        "next_4h_return",
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
    ]
    top = df.sort_values(
        ["next_4h_return", "reversion_state_score"],
        ascending=[False, False],
        na_position="last",
    )
    print(top[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
