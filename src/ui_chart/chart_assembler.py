from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ChartBundle:
    chart_frame: pd.DataFrame
    selection_frame: pd.DataFrame
    paper_candidate_frame: pd.DataFrame
    profile: dict[str, Any] | None


def prepare_chart_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    out = frame.copy()
    datetime_columns = [
        "ts_utc",
        "open_ts_utc",
        "close_ts_utc",
    ]

    for column in datetime_columns:
        if column in out.columns:
            out[column] = pd.to_datetime(out[column])

    numeric_columns = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume_base",
        "volume_quote_eur",
        "ema_20",
        "ema_50",
        "rsi_14",
        "atr_14",
        "volume_ratio_20",
        "volume_zscore_20",
        "obv",
        "obv_slope_5",
        "dollar_volume_ratio_20",
        "price_vs_ema20",
        "price_vs_ema50",
        "atr_pct",
        "ema_spread_pct",
        "wick_reversal_score",
        "signal_confidence",
        "expansion_position_score",
        "pullback_quality_score",
    ]

    for column in numeric_columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    out["signal_label"] = ""
    label_columns = [
        "trend_signal",
        "volume_signal",
        "setup_signal",
        "risk_signal",
    ]
    present = [column for column in label_columns if column in out.columns]

    if present:
        out["signal_label"] = out[present].fillna("").agg(" | ".join, axis=1)
        out["signal_label"] = out["signal_label"].str.replace(" |  | ", " | ", regex=False)
        out["signal_label"] = out["signal_label"].str.strip(" |")

    return out


def prepare_selection_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    out = frame.copy()
    if "asof_ts_utc" in out.columns:
        out["asof_ts_utc"] = pd.to_datetime(out["asof_ts_utc"])

    for column in ["selection_score", "priority_rank"]:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    out["selection_label"] = ""
    parts = [
        column
        for column in [
            "selection_state",
            "selection_bias",
            "priority_rank",
            "selection_score",
        ]
        if column in out.columns
    ]

    if parts:
        out["selection_label"] = out[parts].fillna("").astype(str).agg(" | ".join, axis=1)

    return out


def build_chart_bundle(
    chart_frame: pd.DataFrame,
    selection_frame: pd.DataFrame,
    paper_candidate_frame: pd.DataFrame,
    profile: dict[str, Any] | None,
) -> ChartBundle:
    return ChartBundle(
        chart_frame=prepare_chart_frame(chart_frame),
        selection_frame=prepare_selection_frame(selection_frame),
        paper_candidate_frame=paper_candidate_frame,
        profile=profile,
    )
