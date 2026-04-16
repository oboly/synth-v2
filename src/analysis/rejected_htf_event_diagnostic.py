from __future__ import annotations

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    t.policy_name,
    t.asset_id,
    t.symbol,
    t.entry_ts_utc,
    t.trade_return,
    t.selection_state,
    t.selection_bias,
    t.selection_score,
    t.actual_direction,
    e.is_sweep,
    e.is_reclaim,
    e.sweep_direction,
    e.sweep_distance_atr,
    e.reclaim_strength,
    e.wick_ratio AS event_wick_ratio,
    e.close_position,
    e.volume_ratio AS event_volume_ratio,
    le.sweep_flag,
    le.rejection_flag,
    le.liquidity_event_score,
    fc.atr_pct,
    fc.volume_zscore_20,
    fc.body_pct,
    fc.upper_wick_pct,
    fc.lower_wick_pct,
    fc.wick_reversal_score
FROM tmp_rejected_htf_4h_trades t
LEFT JOIN feat_rejection_event e
    ON e.asset_id = t.asset_id
   AND e.interval_code = '4h'
   AND e.open_ts_utc = t.entry_ts_utc
LEFT JOIN feat_liquidity_event le
    ON le.asset_id = t.asset_id
   AND le.interval_code = '4h'
   AND le.venue = 'bitvavo'
   AND le.open_ts_utc = t.entry_ts_utc
LEFT JOIN feat_candle fc
    ON fc.asset_id = t.asset_id
   AND fc.interval_code = '4h'
   AND fc.venue = 'bitvavo'
   AND fc.close_ts_utc = DATE_ADD(t.entry_ts_utc, INTERVAL 4 HOUR)
WHERE t.policy_name IN ('rejected_htf_4h', 'rejected_htf_top10_4h', 'strong_candidate_4h', 'watch_4h')
"""


NUMERIC_COLS = [
    "trade_return",
    "selection_score",
    "is_sweep",
    "is_reclaim",
    "sweep_distance_atr",
    "reclaim_strength",
    "event_wick_ratio",
    "close_position",
    "event_volume_ratio",
    "sweep_flag",
    "rejection_flag",
    "liquidity_event_score",
    "atr_pct",
    "volume_zscore_20",
    "body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "wick_reversal_score",
]


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in NUMERIC_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def print_group_summary(df: pd.DataFrame, group_cols: list[str], value_col: str) -> None:
    grouped = (
        df.groupby(group_cols, dropna=False)[value_col]
        .agg(["count", "mean", "median", "std"])
        .sort_index()
    )
    print(grouped)


def main() -> None:
    conn = get_connection()
    try:
        df = pd.read_sql(SQL, conn)
    finally:
        conn.close()

    df = coerce_numeric(df)

    print("\n=== DTYPES ===")
    print(df.dtypes.sort_index())

    print("\n=== ROW COUNT ===")
    print(len(df))

    print("\n=== NULL RATES ===")
    print(df.isnull().mean().sort_values(ascending=False).head(20))

    print("\n=== POLICY SUMMARY ===")
    print_group_summary(df, ["policy_name"], "trade_return")

    print("\n=== EVENT PRESENCE BY POLICY ===")
    binary_cols = ["is_sweep", "is_reclaim", "sweep_flag", "rejection_flag"]
    existing_binary = [c for c in binary_cols if c in df.columns]
    if existing_binary:
        print(df.groupby("policy_name", dropna=False)[existing_binary].mean())

    print("\n=== CONTINUOUS FEATURE MEANS BY POLICY ===")
    value_cols = [
        "sweep_distance_atr",
        "reclaim_strength",
        "event_wick_ratio",
        "close_position",
        "event_volume_ratio",
        "liquidity_event_score",
        "atr_pct",
        "volume_zscore_20",
        "body_pct",
        "upper_wick_pct",
        "lower_wick_pct",
        "wick_reversal_score",
    ]
    existing_value = [c for c in value_cols if c in df.columns]
    if existing_value:
        print(df.groupby("policy_name", dropna=False)[existing_value].mean())

    print("\n=== FAILED BREAKDOWN EFFECT ===")
    if {"is_sweep", "is_reclaim"}.issubset(df.columns):
        df["failed_breakdown"] = (df["is_sweep"] == 1) & (df["is_reclaim"] == 1)
        print_group_summary(df, ["policy_name", "failed_breakdown"], "trade_return")
    else:
        print("Missing is_sweep / is_reclaim columns.")

    print("\n=== HIGH RECLAIM STRENGTH EFFECT ===")
    if "reclaim_strength" in df.columns and df["reclaim_strength"].notna().any():
        threshold = df["reclaim_strength"].quantile(0.75)
        df["high_reclaim_strength"] = df["reclaim_strength"] >= threshold
        print_group_summary(df, ["policy_name", "high_reclaim_strength"], "trade_return")
    else:
        print("Missing reclaim_strength column.")

    print("\n=== DIRECTION x POLICY ===")
    if "sweep_direction" in df.columns:
        print_group_summary(df, ["policy_name", "sweep_direction"], "trade_return")
    else:
        print("Missing sweep_direction column.")


if __name__ == "__main__":
    main()
