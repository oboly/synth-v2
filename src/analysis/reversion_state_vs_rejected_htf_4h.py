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
    reversion_state_score,
    score_bucket,
    is_rejected_htf_4h,
    close_price,
    next_close_price,
    next_4h_return
FROM v_reversion_state_vs_rejected_htf_4h
WHERE next_4h_return IS NOT NULL
"""


NUMERIC_COLS = [
    "price_vs_ema20",
    "price_vs_ema50",
    "volume_ratio_20",
    "volume_zscore_20",
    "reversion_state_score",
    "is_rejected_htf_4h",
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

    if "entry_ts_utc" in df.columns:
        df["entry_ts_utc"] = pd.to_datetime(df["entry_ts_utc"], errors="coerce")

    return df


def grouped_returns(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return (
        df.groupby(group_cols, dropna=False)["next_4h_return"]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )


def add_cohort(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["cohort"] = "BASELINE_OTHER_NON_LABEL"

    out.loc[
        (out["is_rejected_htf_4h"] == 0) & (out["score_bucket"].isin(["HIGH", "VERY_HIGH"])),
        "cohort",
    ] = "BASELINE_HIGH_PLUS_NON_LABEL"

    out.loc[
        out["is_rejected_htf_4h"] == 1,
        "cohort",
    ] = "REJECTED_HTF_ALL"

    out.loc[
        (out["is_rejected_htf_4h"] == 1) & (out["score_bucket"].isin(["HIGH", "VERY_HIGH"])),
        "cohort",
    ] = "REJECTED_HTF_HIGH_PLUS"

    return out


def main() -> None:
    df = load_df()

    print("\n=== ROW COUNT ===")
    print(len(df))

    if df.empty:
        print("No rows returned from v_reversion_state_vs_rejected_htf_4h.")
        return

    print("\n=== NULL RATES ===")
    print(df.isnull().mean().sort_values(ascending=False).head(20))

    print("\n=== SCORE BUCKET x LABEL ===")
    print(grouped_returns(df, ["score_bucket", "is_rejected_htf_4h"]))

    df = add_cohort(df)

    print("\n=== COHORT SUMMARY ===")
    print(grouped_returns(df, ["cohort"]))

    print("\n=== TOP 20 REJECTED_HTF_HIGH_PLUS ===")
    cols = [
        "symbol",
        "entry_ts_utc",
        "score_bucket",
        "reversion_state_score",
        "next_4h_return",
    ]
    top = (
        df[df["cohort"] == "REJECTED_HTF_HIGH_PLUS"]
        .sort_values(["next_4h_return", "reversion_state_score"], ascending=[False, False])
    )
    print(top[cols].head(20).to_string(index=False))

    print("\n=== TOP 20 BASELINE_HIGH_PLUS_NON_LABEL ===")
    top = (
        df[df["cohort"] == "BASELINE_HIGH_PLUS_NON_LABEL"]
        .sort_values(["next_4h_return", "reversion_state_score"], ascending=[False, False])
    )
    print(top[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
