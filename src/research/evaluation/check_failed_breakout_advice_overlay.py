from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.common.db import get_connection


SQL = """
SELECT
    symbol,
    asof_ts_utc,
    advice_ts_4h_utc,
    selection_state,
    selection_bias,
    selection_score,
    failed_breakout_flag_4h,
    breakout_failure_state,
    avoid_long_overlay_flag,
    advice_overlay_reason,
    selection_score_after_overlay
FROM v_selection_with_failed_breakout_overlay
WHERE asof_ts_utc >= '2026-01-01 00:00:00'
"""


def normalize(v: Any):
    if isinstance(v, Decimal):
        return float(v)
    return v


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

    for c in df.columns:
        df[c] = df[c].map(normalize)

    for col in ["asof_ts_utc", "advice_ts_4h_utc"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in ["selection_score", "selection_score_after_overlay"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print("\n=== OVERLAY COUNTS ===")
    print(
        df.groupby(
            ["failed_breakout_flag_4h", "avoid_long_overlay_flag", "selection_bias"],
            dropna=False
        )
        .size()
        .sort_values(ascending=False)
        .head(30)
    )

    print("\n=== IMPACTED ROWS SAMPLE ===")
    impacted = df[df["avoid_long_overlay_flag"] == 1].copy()
    impacted = impacted.sort_values(
        ["asof_ts_utc", "symbol"],
        ascending=[False, True],
    )
    print(impacted.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
