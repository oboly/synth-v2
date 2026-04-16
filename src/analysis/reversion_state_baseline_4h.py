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
    close_ts_utc,
    entry_ts_utc,
    next_close_ts_utc,
    price_vs_ema20,
    price_vs_ema50,
    volume_ratio_20,
    volume_zscore_20,
    atr_pct,
    reversion_state_score,
    score_bucket,
    next_4h_return_proxy
FROM v_reversion_state_baseline_4h
"""


NUMERIC_COLS = [
    "price_vs_ema20",
    "price_vs_ema50",
    "volume_ratio_20",
    "volume_zscore_20",
    "atr_pct",
    "reversion_state_score",
    "next_4h_return_proxy",
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

    for col in ["close_ts_utc", "entry_ts_utc", "next_close_ts_utc"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def print_grouped(df: pd.DataFrame, group_cols: list[str]) -> None:
    grouped = (
        df.groupby(group_cols, dropna=False)["next_4h_return_proxy"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )
    print(grouped)


def main() -> None:
    df = load_df()

    print("\n=== ROW COUNT ===")
    print(len(df))

    if df.empty:
        print("No rows returned from v_reversion_state_baseline_4h.")
        return

    print("\n=== NULL RATES ===")
    print(df.isnull().mean().sort_values(ascending=False).head(20))

    print("\n=== SCORE SUMMARY ===")
    print_grouped(df, ["score_bucket"])

    print("\n=== FEATURE MEANS BY SCORE ===")
    cols = [
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
        "atr_pct",
        "reversion_state_score",
    ]
    print(df.groupby("score_bucket", dropna=False)[cols].mean().sort_index())

    print("\n=== TOP 20 VERY_HIGH/HIGH ===")
    cols = [
        "symbol",
        "entry_ts_utc",
        "next_4h_return_proxy",
        "reversion_state_score",
        "score_bucket",
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
    ]
    top = df.sort_values(
        ["reversion_state_score", "next_4h_return_proxy"],
        ascending=[False, False],
        na_position="last",
    )
    print(top[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
