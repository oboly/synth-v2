from __future__ import annotations

import pandas as pd


def compute_rejection_score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in [
        "reclaim_strength",
        "sweep_distance_atr",
        "volume_ratio",
        "wick_ratio",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    out["rejection_score"] = (
        0.40 * out["reclaim_strength"]
        + 0.30 * out["sweep_distance_atr"]
        + 0.20 * out["volume_ratio"]
        + 0.10 * out["wick_ratio"]
    )

    out["is_valid_rejection_event"] = (
        (out["is_sweep"] == 1) &
        (out["is_reclaim"] == 1)
    ).astype(int)

    out["policy_name"] = None
    out.loc[
        (out["is_valid_rejection_event"] == 1) & (out["rejection_score"] >= 0.75),
        "policy_name"
    ] = "rejected_htf_4h"

    return out
