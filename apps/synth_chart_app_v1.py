from __future__ import annotations

import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ui_chart.chart_assembler import build_chart_bundle
from src.ui_chart.chart_config import DEFAULT_INTERVAL, DEFAULT_VENUE, SUPPORTED_INTERVALS
from src.ui_chart.chart_renderer import (
    display_context_to_markdown,
    display_value,
    format_display_timestamp,
    profile_to_markdown,
    render_main_chart,
    runtime_snapshot_display,
)
from src.ui_chart.chart_repository import (
    fetch_assets,
    fetch_chart_frame,
    fetch_display_context,
    fetch_paper_candidate_frame,
    fetch_point_in_time_profile,
    fetch_selection_frame,
    resolve_asset,
)


st.set_page_config(
    page_title="Synth v2.5 Chart",
    layout="wide",
)


st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-size: 13px;
    }

    .block-container {
        max-width: 100%;
        padding-top: 0.75rem;
        padding-left: 1.0rem;
        padding-right: 1.0rem;
        padding-bottom: 0.5rem;
    }

    section[data-testid="stSidebar"] {
        width: 15.5rem !important;
        min-width: 15.5rem !important;
    }

    section[data-testid="stSidebar"] > div {
        padding-top: 1rem;
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }

    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        font-size: 0.72rem !important;
    }

    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        font-size: 0.82rem !important;
        margin-bottom: 0.25rem !important;
    }

    div[data-testid="stSelectbox"] > div,
    div[data-testid="stTextInput"] > div,
    div[data-testid="stDateInput"] > div {
        min-height: 2.0rem !important;
        font-size: 0.78rem !important;
    }

    div[data-testid="stMetric"] {
        padding: 0 !important;
    }

    div[data-testid="stMetric"] label {
        font-size: 0.68rem !important;
    }

    div[data-testid="stMetricValue"] {
        font-size: 1.05rem !important;
    }

    h1 {
        font-size: 1.25rem !important;
        margin-bottom: 0.4rem !important;
    }

    .stCaptionContainer {
        font-size: 0.72rem !important;
        margin-top: -0.4rem !important;
        margin-bottom: 0.2rem !important;
    }

    .stPlotlyChart {
        margin-top: -0.8rem;
    }

    details {
        font-size: 0.78rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300)
def cached_assets() -> list[dict[str, object]]:
    return [
        {
            "asset_id": asset.asset_id,
            "symbol": asset.symbol,
            "name": asset.name,
        }
        for asset in fetch_assets()
    ]


@st.cache_data(ttl=120)
def cached_chart_data(
    symbol: str,
    venue: str,
    interval_code: str,
    start_iso: str,
    end_iso: str,
    max_candles: int,
) -> dict[str, object]:
    asset = resolve_asset(symbol)
    if not asset:
        return {
            "error": "Asset not found: " + symbol,
        }

    start_ts = datetime.fromisoformat(start_iso)
    end_ts = datetime.fromisoformat(end_iso)

    chart_frame = fetch_chart_frame(
        asset_id=asset.asset_id,
        venue=venue,
        interval_code=interval_code,
        start_ts_utc=start_ts,
        end_ts_utc=end_ts,
        max_candles=max_candles,
    )

    selection_frame = fetch_selection_frame(
        asset_id=asset.asset_id,
        venue=venue,
        start_ts_utc=start_ts,
        end_ts_utc=end_ts,
    )

    profile = fetch_point_in_time_profile(
        asset_id=asset.asset_id,
        venue=venue,
        interval_code=interval_code,
        asof_ts_utc=end_ts,
    )

    paper_candidate_frame = fetch_paper_candidate_frame(
        asset_id=asset.asset_id,
        venue=venue,
        start_ts_utc=start_ts,
        end_ts_utc=end_ts,
    )

    display_context = fetch_display_context(
        asset_id=asset.asset_id,
        venue=venue,
        interval_code=interval_code,
    )

    bundle = build_chart_bundle(
        chart_frame=chart_frame,
        selection_frame=selection_frame,
        paper_candidate_frame=paper_candidate_frame,
        profile=profile,
        display_context=display_context,
    )

    return {
        "asset_id": asset.asset_id,
        "symbol": asset.symbol,
        "chart_frame": bundle.chart_frame,
        "selection_frame": bundle.selection_frame,
        "paper_candidate_frame": bundle.paper_candidate_frame,
        "profile": bundle.profile,
        "display_context": bundle.display_context,
    }


def date_to_utc_start(value) -> datetime:
    return datetime.combine(value, time.min).replace(tzinfo=None)


def date_to_utc_end(value) -> datetime:
    return datetime.combine(value, time.max).replace(microsecond=0).replace(tzinfo=None)


st.markdown("## Synth v2.5 — Read-only Chart Framework v1")

assets = cached_assets()
symbols = [str(asset["symbol"]) for asset in assets]

if not symbols:
    st.error("No enabled assets found.")
    st.stop()

now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
default_end = now_utc.date()
default_start = (now_utc - timedelta(days=30)).date()

with st.sidebar:
    st.header("Chart controls")

    default_symbol_index = symbols.index("BTC") if "BTC" in symbols else 0

    symbol = st.selectbox(
        "Symbol",
        options=symbols,
        index=default_symbol_index,
    )

    venue = st.text_input(
        "Venue",
        value=DEFAULT_VENUE,
    )

    interval_code = st.selectbox(
        "Interval",
        options=SUPPORTED_INTERVALS,
        index=SUPPORTED_INTERVALS.index(DEFAULT_INTERVAL),
    )

    start_date = st.date_input(
        "Start date UTC",
        value=default_start,
    )

    end_date = st.date_input(
        "End date UTC",
        value=default_end,
    )

    max_candles = st.slider(
        "Max candles",
        min_value=100,
        max_value=5000,
        value=2500,
        step=100,
    )

    st.header("Overlays")

    show_ema20 = st.checkbox("EMA 20", value=True)
    show_ema50 = st.checkbox("EMA 50", value=True)
    show_rsi = st.checkbox("RSI 14 panel", value=True)
    show_signal_confidence = st.checkbox("Signal confidence panel", value=True)
    show_signal_labels = st.checkbox("Signal labels on price", value=False)
    show_selection_lines = st.checkbox("Selection vertical lines", value=True)

start_ts = date_to_utc_start(start_date)
end_ts = date_to_utc_end(end_date)

if end_ts <= start_ts:
    st.error("End date must be after start date.")
    st.stop()

payload = cached_chart_data(
    symbol=symbol,
    venue=venue,
    interval_code=interval_code,
    start_iso=start_ts.isoformat(),
    end_iso=end_ts.isoformat(),
    max_candles=max_candles,
)

if "error" in payload:
    st.error(str(payload["error"]))
    st.stop()

chart_frame = payload["chart_frame"]
selection_frame = payload["selection_frame"]
paper_candidate_frame = payload["paper_candidate_frame"]
profile = payload["profile"]
display_context = payload["display_context"]

freshness = display_context.get("freshness", {})
price_context = display_context.get("price", {})
zone_context = display_context.get("zone_context", {})

count_left, count_middle, count_right = st.columns(3)

with count_left:
    st.metric("Candles", len(chart_frame))

with count_middle:
    st.metric("Selection rows", len(selection_frame))

with count_right:
    st.metric("Paper candidate rows", len(paper_candidate_frame))

fresh_left, fresh_middle, fresh_right, fresh_fourth, fresh_fifth = st.columns(5)

with fresh_left:
    st.metric("Latest close", display_value(price_context.get("latest_close_price"), 8))

with fresh_middle:
    st.metric("Chart latest close", format_display_timestamp(freshness.get("chart_frame_latest_close_ts_utc")))

with fresh_right:
    st.metric("Source candle close", format_display_timestamp(freshness.get("latest_candle_close_ts_utc")))

with fresh_fourth:
    st.metric("Zone as-of", format_display_timestamp(freshness.get("latest_execution_zone_asof_ts_utc")))

with fresh_fifth:
    st.metric("Runtime snapshot", runtime_snapshot_display(freshness))

zone_left, zone_middle, zone_right = st.columns(3)

with zone_left:
    st.metric("Zone relation", display_value(zone_context.get("zone_relation")))

with zone_middle:
    st.metric("Distance to zone %", display_value(zone_context.get("distance_to_zone_pct"), 4))

with zone_right:
    st.metric("Distance to target %", display_value(zone_context.get("distance_to_target_pct"), 4))

profile_label = "No profile"
if profile:
    profile_label = (
        "liquidity="
        + str(profile.get("liquidity_class"))
        + " | beta="
        + str(profile.get("beta_profile"))
        + " | sector="
        + str(profile.get("sector_group_code"))
    )

st.caption(profile_label)

fig = render_main_chart(
    frame=chart_frame,
    selection_frame=selection_frame,
    profile=profile,
    display_context=display_context,
    show_ema20=show_ema20,
    show_ema50=show_ema50,
    show_rsi=show_rsi,
    show_signal_confidence=show_signal_confidence,
    show_signal_labels=show_signal_labels,
    show_selection_lines=show_selection_lines,
)

st.plotly_chart(
    fig,
    width="stretch",
)

with st.expander("Point-in-time asset profile"):
    st.markdown(profile_to_markdown(profile))

with st.expander("Freshness and zone context", expanded=True):
    st.markdown(display_context_to_markdown(display_context))

with st.expander("Latest chart rows"):
    if isinstance(chart_frame, pd.DataFrame) and not chart_frame.empty:
        st.dataframe(chart_frame.tail(50), width="stretch")
    else:
        st.info("No chart rows.")

with st.expander("Selection rows"):
    if isinstance(selection_frame, pd.DataFrame) and not selection_frame.empty:
        st.dataframe(selection_frame.tail(100), width="stretch")
    else:
        st.info("No selection rows in range.")

with st.expander("Paper candidate rows"):
    if isinstance(paper_candidate_frame, pd.DataFrame) and not paper_candidate_frame.empty:
        st.dataframe(paper_candidate_frame.tail(100), width="stretch")
    else:
        st.info("No paper candidate table/rows available yet.")
