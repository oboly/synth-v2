from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ChartBundle:
    chart_frame: pd.DataFrame
    selection_frame: pd.DataFrame
    paper_candidate_frame: pd.DataFrame
    profile: dict[str, Any] | None
    display_context: dict[str, Any]


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


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _zone_relation(close_price: float | None, zone_low: float | None, zone_high: float | None) -> str | None:
    if close_price is None or zone_low is None or zone_high is None:
        return None
    low = min(zone_low, zone_high)
    high = max(zone_low, zone_high)
    if close_price < low:
        return "BELOW_ZONE"
    if close_price > high:
        return "ABOVE_ZONE"
    return "INSIDE_ZONE"


def _distance_to_zone_pct(
    close_price: float | None,
    zone_low: float | None,
    zone_high: float | None,
) -> float | None:
    if close_price is None or close_price == 0 or zone_low is None or zone_high is None:
        return None
    low = min(zone_low, zone_high)
    high = max(zone_low, zone_high)
    if low <= close_price <= high:
        return 0.0
    if close_price < low:
        return ((low - close_price) / close_price) * 100.0
    return ((close_price - high) / close_price) * 100.0


def _distance_to_target_pct(
    close_price: float | None,
    target_low: float | None,
    target_high: float | None,
) -> float | None:
    if close_price is None or close_price == 0 or target_low is None or target_high is None:
        return None
    low = min(target_low, target_high)
    high = max(target_low, target_high)
    if low <= close_price <= high:
        return 0.0
    if close_price < low:
        return ((low - close_price) / close_price) * 100.0
    return ((close_price - high) / close_price) * 100.0


def _chart_frame_latest_ts(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None

    values = pd.to_datetime(frame[column], errors="coerce")
    values = values.dropna()
    if values.empty:
        return None

    return _iso_or_none(values.max())


def prepare_display_context(raw_context: dict[str, Any] | None, chart_frame: pd.DataFrame) -> dict[str, Any]:
    context = raw_context or {}
    latest_candle = dict(context.get("latest_candle") or {})
    latest_signal = dict(context.get("latest_signal") or {})
    latest_selection = dict(context.get("latest_selection") or {})
    latest_advice = dict(context.get("latest_advice") or {})
    latest_zone = dict(context.get("latest_execution_zone") or {})
    latest_runtime = dict(context.get("latest_strategy_runtime_snapshot") or {})

    close_price = _to_float(latest_candle.get("close_price"))
    entry_zone_low = _to_float(latest_zone.get("entry_zone_low"))
    entry_zone_high = _to_float(latest_zone.get("entry_zone_high"))
    tp_zone_low = _to_float(latest_zone.get("tp_zone_low"))
    tp_zone_high = _to_float(latest_zone.get("tp_zone_high"))

    zone_relation = latest_zone.get("zone_relation")
    if zone_relation is None:
        zone_relation = _zone_relation(close_price, entry_zone_low, entry_zone_high)

    distance_to_zone_pct = _to_float(latest_zone.get("distance_to_zone_pct"))
    if distance_to_zone_pct is None:
        distance_to_zone_pct = _distance_to_zone_pct(close_price, entry_zone_low, entry_zone_high)

    distance_to_target_pct = _to_float(latest_zone.get("distance_to_target_pct"))
    if distance_to_target_pct is None:
        distance_to_target_pct = _distance_to_target_pct(close_price, tp_zone_low, tp_zone_high)

    return {
        "freshness": {
            "chart_frame_latest_open_ts_utc": _chart_frame_latest_ts(chart_frame, "open_ts_utc"),
            "chart_frame_latest_close_ts_utc": _chart_frame_latest_ts(chart_frame, "close_ts_utc"),
            "latest_candle_close_ts_utc": _iso_or_none(latest_candle.get("close_ts_utc")),
            "latest_signal_ts_utc": _iso_or_none(latest_signal.get("signal_ts_utc")),
            "latest_selection_asof_ts_utc": _iso_or_none(latest_selection.get("asof_ts_utc")),
            "latest_advice_asof_ts_utc": _iso_or_none(latest_advice.get("asof_ts_utc")),
            "latest_execution_zone_asof_ts_utc": _iso_or_none(latest_zone.get("asof_ts_utc")),
            "latest_strategy_runtime_snapshot_ts_utc": _iso_or_none(latest_runtime.get("snapshot_ts_utc")),
            "latest_strategy_runtime_snapshot_id": latest_runtime.get("strategy_runtime_snapshot_id"),
        },
        "price": {
            "latest_close_price": close_price,
        },
        "zone_context": {
            "entry_zone_low": entry_zone_low,
            "entry_zone_high": entry_zone_high,
            "tp_zone_low": tp_zone_low,
            "tp_zone_high": tp_zone_high,
            "invalidation_price": _to_float(latest_zone.get("invalidation_price")),
            "zone_relation": zone_relation,
            "distance_to_zone_pct": distance_to_zone_pct,
            "distance_to_target_pct": distance_to_target_pct,
            "entry_zone_type": latest_zone.get("entry_zone_type"),
            "tp_zone_type": latest_zone.get("tp_zone_type"),
        },
        "latest_signal": latest_signal,
        "latest_selection": latest_selection,
        "latest_advice": latest_advice,
        "latest_strategy_runtime_snapshot": latest_runtime,
    }


def build_chart_bundle(
    chart_frame: pd.DataFrame,
    selection_frame: pd.DataFrame,
    paper_candidate_frame: pd.DataFrame,
    profile: dict[str, Any] | None,
    display_context: dict[str, Any] | None = None,
) -> ChartBundle:
    prepared_chart_frame = prepare_chart_frame(chart_frame)
    return ChartBundle(
        chart_frame=prepared_chart_frame,
        selection_frame=prepare_selection_frame(selection_frame),
        paper_candidate_frame=paper_candidate_frame,
        profile=profile,
        display_context=prepare_display_context(display_context, prepared_chart_frame),
    )
