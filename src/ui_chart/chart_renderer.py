from __future__ import annotations

from typing import Any

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


def render_main_chart(
    frame: pd.DataFrame,
    selection_frame: pd.DataFrame,
    profile: dict[str, Any] | None,
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
    if isinstance(value, float) and precision is not None:
        return f"{value:.{precision}f}"
    return str(value)


def display_context_to_markdown(display_context: dict[str, Any] | None) -> str:
    if not display_context:
        return "No display context found."

    freshness = display_context.get("freshness") or {}
    price = display_context.get("price") or {}
    zone = display_context.get("zone_context") or {}

    lines = [
        "### Freshness",
        "",
        "| Field | Value |",
        "|---|---:|",
        "| latest_candle_close_ts_utc | "
        + display_value(freshness.get("latest_candle_close_ts_utc"))
        + " |",
        "| latest_signal_ts_utc | "
        + display_value(freshness.get("latest_signal_ts_utc"))
        + " |",
        "| latest_selection_asof_ts_utc | "
        + display_value(freshness.get("latest_selection_asof_ts_utc"))
        + " |",
        "| latest_advice_asof_ts_utc | "
        + display_value(freshness.get("latest_advice_asof_ts_utc"))
        + " |",
        "| latest_execution_zone_asof_ts_utc | "
        + display_value(freshness.get("latest_execution_zone_asof_ts_utc"))
        + " |",
        "| latest_strategy_runtime_snapshot_ts_utc | "
        + display_value(freshness.get("latest_strategy_runtime_snapshot_ts_utc"))
        + " |",
        "| latest_strategy_runtime_snapshot_id | "
        + display_value(freshness.get("latest_strategy_runtime_snapshot_id"))
        + " |",
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

    return "\n".join(lines)
