from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    policy_name,
    asset_id,
    symbol,
    entry_ts_utc,
    trade_return,
    feat_close_ts_utc,
    ret_4h,
    ret_24h,
    price_vs_ema20,
    price_vs_ema50,
    volume_ratio_20,
    volume_zscore_20,
    atr_pct,
    body_pct,
    upper_wick_pct,
    lower_wick_pct,
    wick_reversal_score,
    reversion_state_score,
    score_bucket
FROM v_reversion_state_backtest
"""


NUMERIC_COLS = [
    "trade_return",
    "ret_4h",
    "ret_24h",
    "price_vs_ema20",
    "price_vs_ema50",
    "volume_ratio_20",
    "volume_zscore_20",
    "atr_pct",
    "body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "wick_reversal_score",
    "reversion_state_score",
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

    expected_cols = [
        "policy_name",
        "asset_id",
        "symbol",
        "entry_ts_utc",
        "trade_return",
        "feat_close_ts_utc",
        "ret_4h",
        "ret_24h",
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
        "atr_pct",
        "body_pct",
        "upper_wick_pct",
        "lower_wick_pct",
        "wick_reversal_score",
        "reversion_state_score",
        "score_bucket",
    ]

    if list(df.columns) != expected_cols:
        df = df.reindex(columns=expected_cols)

    for col in df.columns:
        df[col] = df[col].map(_normalize_scalar)

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "entry_ts_utc" in df.columns:
        df["entry_ts_utc"] = pd.to_datetime(df["entry_ts_utc"], errors="coerce")

    if "feat_close_ts_utc" in df.columns:
        df["feat_close_ts_utc"] = pd.to_datetime(df["feat_close_ts_utc"], errors="coerce")

    if "policy_name" in df.columns:
        df = df[df["policy_name"].notna()].copy()
        df = df[df["policy_name"].astype(str).str.strip() != ""].copy()
        df = df[df["policy_name"].astype(str) != "policy_name"].copy()

    if "score_bucket" in df.columns:
        df = df[df["score_bucket"].notna()].copy()
        df = df[df["score_bucket"].astype(str).str.strip() != ""].copy()
        df = df[df["score_bucket"].astype(str) != "score_bucket"].copy()

    return df


def print_grouped_return(df: pd.DataFrame, group_cols: list[str]) -> None:
    grouped = (
        df.groupby(group_cols, dropna=False)["trade_return"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )
    print(grouped)


def main() -> None:
    df = load_df()

    print("\n=== ROW COUNT ===")
    print(len(df))

    if df.empty:
        print("\nNo rows returned from v_reversion_state_backtest.")
        return

    print("\n=== COLUMNS ===")
    print(df.columns.tolist())

    print("\n=== DTYPES ===")
    print(df.dtypes)

    print("\n=== NULL RATES ===")
    print(df.isnull().mean().sort_values(ascending=False).head(20))

    print("\n=== POLICY x SCORE ===")
    print_grouped_return(df, ["policy_name", "score_bucket"])

    print("\n=== SCORE SUMMARY ===")
    print_grouped_return(df, ["score_bucket"])

    print("\n=== TOP 15 HIGH SCORE ===")
    cols = [
        "policy_name",
        "symbol",
        "entry_ts_utc",
        "trade_return",
        "reversion_state_score",
        "score_bucket",
        "price_vs_ema20",
        "price_vs_ema50",
        "ret_4h",
        "ret_24h",
        "volume_ratio_20",
        "volume_zscore_20",
    ]
    existing_cols = [c for c in cols if c in df.columns]
    top = df.sort_values(
        ["reversion_state_score", "trade_return"],
        ascending=[False, False],
        na_position="last",
    )
    print(top[existing_cols].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
