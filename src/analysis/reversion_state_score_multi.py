from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    policy_name,
    symbol,
    entry_ts_utc,
    trade_return,
    price_vs_ema20,
    price_vs_ema50,
    volume_ratio_20,
    volume_zscore_20,
    reversion_state_score,
    score_bucket
FROM v_reversion_state_backtest_multi
"""


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
        "symbol",
        "entry_ts_utc",
        "trade_return",
        "price_vs_ema20",
        "price_vs_ema50",
        "volume_ratio_20",
        "volume_zscore_20",
        "reversion_state_score",
        "score_bucket",
    ]

    df = df.reindex(columns=expected_cols)

    for col in df.columns:
        df[col] = df[col].map(_normalize_scalar)

    df["trade_return"] = pd.to_numeric(df["trade_return"], errors="coerce")
    df["reversion_state_score"] = pd.to_numeric(df["reversion_state_score"], errors="coerce")

    df = df[df["policy_name"].notna()]
    df = df[df["score_bucket"].notna()]

    return df


def print_policy_matrix(df: pd.DataFrame) -> None:
    grouped = (
        df.groupby(["policy_name", "score_bucket"])["trade_return"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )
    print(grouped)


def print_bucket_global(df: pd.DataFrame) -> None:
    grouped = (
        df.groupby(["score_bucket"])["trade_return"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )
    print(grouped)


def main() -> None:
    df = load_df()

    print("\n=== ROW COUNT ===")
    print(len(df))

    if df.empty:
        print("No data.")
        return

    print("\n=== POLICY x SCORE MATRIX ===")
    print_policy_matrix(df)

    print("\n=== GLOBAL SCORE EFFECT ===")
    print_bucket_global(df)


if __name__ == "__main__":
    main()
