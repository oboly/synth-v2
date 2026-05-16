from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _has_column(frame: pd.DataFrame, column: str) -> bool:
    return column in frame.columns and frame[column].notna().any()


def _to_py_datetime(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def _add_selection_vertical_lines(
    fig: go.Figure,
    selection_frame: pd.DataFrame,
) -> None:
    if selection_frame.empty or "asof_ts_utc" not in selection_frame.columns:
        return

    for _, row in selection_frame.iterrows():
        x_value = _to_py_datetime(row["asof_ts_utc"])
        if x_value is None:
            continue

        fig.add_shape(
            type="line",
            x0=x_value,
            x1=x_value,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line={
                "width": 1,
            },
            opacity=0.16,
            layer="below",
        )


def _zone_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _add_zone_overlays(fig: go.Figure, display_context: dict[str, Any] | None) -> None:
    if not display_context:
        return

    zone = display_context.get("zone_context") or {}
    entry_low = _zone_float(zone.get("entry_zone_low"))
    entry_high = _zone_float(zone.get("entry_zone_high"))
    target_low = _zone_float(zone.get("tp_zone_low"))
    target_high = _zone_float(zone.get("tp_zone_high"))
    invalidation_price = _zone_float(zone.get("invalidation_price"))

    if entry_low is not None and entry_high is not None:
        fig.add_hrect(
            y0=min(entry_low, entry_high),
            y1=max(entry_low, entry_high),
            row=1,
            col=1,
            fillcolor="#2f80ed",
            opacity=0.12,
            line_width=0,
            layer="below",
        )

    if target_low is not None and target_high is not None:
        fig.add_hrect(
            y0=min(target_low, target_high),
            y1=max(target_low, target_high),
            row=1,
            col=1,
            fillcolor="#27ae60",
            opacity=0.10,
            line_width=0,
            layer="below",
        )

    if invalidation_price is not None:
        fig.add_hline(
            y=invalidation_price,
            row=1,
            col=1,
            line_width=1,
            line_dash="dot",
            line_color="#c0392b",
            opacity=0.70,
        )


def render_main_chart(
    frame: pd.DataFrame,
    selection_frame: pd.DataFrame,
    profile: dict[str, Any] | None,
    display_context: dict[str, Any] | None,
    show_ema20: bool,
    show_ema50: bool,
    show_rsi: bool,
    show_signal_confidence: bool,
    show_signal_labels: bool,
    show_selection_lines: bool,
) -> go.Figure:
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.018,
        row_heights=[0.60, 0.14, 0.12, 0.14],
        subplot_titles=["Price", "Volume", "RSI 14", "Signal confidence"],
    )

    if frame.empty:
        fig.update_layout(
            title=None,
            height=850,
        )
        return fig

    fig.add_trace(
        go.Candlestick(
            x=frame["ts_utc"],
            open=frame["open_price"],
            high=frame["high_price"],
            low=frame["low_price"],
            close=frame["close_price"],
            name="OHLC",
        ),
        row=1,
        col=1,
    )

    if show_ema20 and _has_column(frame, "ema_20"):
        fig.add_trace(
            go.Scatter(
                x=frame["ts_utc"],
                y=frame["ema_20"],
                mode="lines",
                name="EMA 20",
                line={"width": 1.1},
            ),
            row=1,
            col=1,
        )

    if show_ema50 and _has_column(frame, "ema_50"):
        fig.add_trace(
            go.Scatter(
                x=frame["ts_utc"],
                y=frame["ema_50"],
                mode="lines",
                name="EMA 50",
                line={"width": 1.1},
            ),
            row=1,
            col=1,
        )

    if show_signal_labels and _has_column(frame, "signal_label"):
        labeled = frame[frame["signal_label"].fillna("") != ""].copy()
        if not labeled.empty:
            fig.add_trace(
                go.Scatter(
                    x=labeled["ts_utc"],
                    y=labeled["close_price"],
                    mode="markers",
                    name="Signal labels",
                    text=labeled["signal_label"],
                    marker={"size": 4},
                    hovertemplate="%{x}<br>%{text}<br>close=%{y}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    volume_column = "volume_quote_eur"
    if not _has_column(frame, volume_column):
        volume_column = "volume_base"

    if _has_column(frame, volume_column):
        fig.add_trace(
            go.Bar(
                x=frame["ts_utc"],
                y=frame[volume_column],
                name=volume_column,
            ),
            row=2,
            col=1,
        )

    if show_rsi and _has_column(frame, "rsi_14"):
        fig.add_trace(
            go.Scatter(
                x=frame["ts_utc"],
                y=frame["rsi_14"],
                mode="lines",
                name="RSI 14",
                line={"width": 1.05},
            ),
            row=3,
            col=1,
        )
        fig.add_hline(y=70, row=3, col=1, line_width=1, opacity=0.35)
        fig.add_hline(y=30, row=3, col=1, line_width=1, opacity=0.35)

    if show_signal_confidence and _has_column(frame, "signal_confidence"):
        fig.add_trace(
            go.Scatter(
                x=frame["ts_utc"],
                y=frame["signal_confidence"],
                mode="lines",
                name="Signal confidence",
                line={"width": 1.05},
            ),
            row=4,
            col=1,
        )
        fig.add_hline(y=0.60, row=4, col=1, line_width=1, opacity=0.35)

    if show_selection_lines:
        _add_selection_vertical_lines(fig, selection_frame)

    _add_zone_overlays(fig, display_context)

    fig.update_layout(
        title=None,
        height=760,
        xaxis_rangeslider_visible=False,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.0,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 8},
            "itemsizing": "constant",
        },
        margin={
            "l": 24,
            "r": 10,
            "t": 30,
            "b": 18,
        },
        hovermode="x unified",
    )

    fig.update_annotations(font_size=9)

    fig.update_yaxes(title_text="Price", row=1, col=1, title_font_size=8, tickfont_size=8)
    fig.update_yaxes(title_text="Volume", row=2, col=1, title_font_size=8, tickfont_size=8)
    fig.update_yaxes(title_text="RSI", row=3, col=1, title_font_size=8, tickfont_size=8)
    fig.update_yaxes(title_text="Confidence", row=4, col=1, title_font_size=8, tickfont_size=8)
    fig.update_xaxes(tickfont_size=8)

    return fig


def profile_to_markdown(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "No point-in-time asset profile found."

    lines = [
        "| Field | Value |",
        "|---|---:|",
    ]

    for key in [
        "asof_ts_utc",
        "liquidity_class",
        "liquidity_score",
        "beta_profile",
        "beta_to_market",
        "realized_volatility",
        "sector_group_code",
        "sector_confidence",
        "coverage_ratio",
        "lookback_days",
        "profile_version",
    ]:
        lines.append("| " + key + " | " + str(profile.get(key)) + " |")

    return "\n".join(lines)


def display_value(value: Any, precision: int | None = None) -> str:
    if value is None or value == "":
        return "not available"
    if isinstance(value, (float, int)) and precision is not None:
        return f"{value:.{precision}f}"
    return str(value)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None

    if isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed_timestamp = pd.to_datetime(value, errors="coerce", utc=False)
            if pd.isna(parsed_timestamp):
                return None
            parsed = parsed_timestamp.to_pydatetime()

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def format_utc_timestamp(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return "not available"
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def format_display_timestamp(value: Any, timezone_name: str = "Europe/Amsterdam") -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return "not available"
    local_value = parsed.astimezone(ZoneInfo(timezone_name))
    return local_value.strftime("%Y-%m-%d %H:%M %Z")


def runtime_snapshot_display(freshness: dict[str, Any]) -> str:
    snapshot_id = display_value(freshness.get("latest_strategy_runtime_snapshot_id"))
    snapshot_ts = format_display_timestamp(freshness.get("latest_strategy_runtime_snapshot_ts_utc"))
    if snapshot_id == "not available" and snapshot_ts == "not available":
        return "not available"
    return snapshot_id + " / " + snapshot_ts


def display_context_to_markdown(display_context: dict[str, Any] | None) -> str:
    if not display_context:
        return "No display context found."

    freshness = display_context.get("freshness") or {}
    price = display_context.get("price") or {}
    zone = display_context.get("zone_context") or {}

    lines = [
        "### Freshness",
        "",
        "| Source | UTC | Amsterdam |",
        "|---|---:|---:|",
    ]

    freshness_rows = [
        ("Chart frame close", freshness.get("chart_frame_latest_close_ts_utc")),
        ("Source candle close", freshness.get("latest_candle_close_ts_utc")),
        ("Signal", freshness.get("latest_signal_ts_utc")),
        ("Selection", freshness.get("latest_selection_asof_ts_utc")),
        ("Advice", freshness.get("latest_advice_asof_ts_utc")),
        ("Execution zone", freshness.get("latest_execution_zone_asof_ts_utc")),
        ("Runtime snapshot", freshness.get("latest_strategy_runtime_snapshot_ts_utc")),
    ]

    for source, timestamp in freshness_rows:
        lines.append(
            "| "
            + source
            + " | "
            + format_utc_timestamp(timestamp)
            + " | "
            + format_display_timestamp(timestamp)
            + " |"
        )

    snapshot_id = display_value(freshness.get("latest_strategy_runtime_snapshot_id"))
    lines.extend(
        [
            "| Runtime snapshot id | " + snapshot_id + " | " + snapshot_id + " |",
            "",
            "### Latest Price And Zone Context",
            "",
            "| Field | Value |",
            "|---|---:|",
            "| latest_close_price | " + display_value(price.get("latest_close_price"), 8) + " |",
            "| entry_zone_low | " + display_value(zone.get("entry_zone_low"), 8) + " |",
            "| entry_zone_high | " + display_value(zone.get("entry_zone_high"), 8) + " |",
            "| tp_zone_low | " + display_value(zone.get("tp_zone_low"), 8) + " |",
            "| tp_zone_high | " + display_value(zone.get("tp_zone_high"), 8) + " |",
            "| invalidation_price | " + display_value(zone.get("invalidation_price"), 8) + " |",
            "| zone_relation | " + display_value(zone.get("zone_relation")) + " |",
            "| distance_to_zone_pct | " + display_value(zone.get("distance_to_zone_pct"), 4) + " |",
            "| distance_to_target_pct | " + display_value(zone.get("distance_to_target_pct"), 4) + " |",
        ]
    )

    return "\n".join(lines)
