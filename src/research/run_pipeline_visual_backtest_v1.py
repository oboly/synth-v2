from __future__ import annotations

"""
Synth v2 - Pipeline Visual Backtest V1.

LAYER: research

BOUNDARY:
  Allowed:
    - read market candles and operational observation snapshots
    - generate deterministic research-only simulated events
    - write requested local HTML / JSONL artifacts

  Forbidden:
    - broker calls, broker writes, order submission, live orders
    - decision_gate, execution_planner, executor logic
    - operational execution_zone_context backfills or writes
    - runtime/dashboard/systemd behavior changes
"""

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from src.common.db import get_connection
from src.ui_chart.chart_assembler import prepare_chart_frame, prepare_selection_frame
from src.ui_chart.chart_repository import (
    fetch_chart_frame,
    fetch_selection_frame,
    resolve_asset,
    table_exists,
)


REPORT_NAME = "pipeline_visual_backtest_v1"
REPORT_VERSION = "1.0"

BLOCK_ADVICE_ACTIONS = {
    "AVOID_NO_NEW_BUY",
    "DO_NOT_ADD",
    "BLOCK_FOR_24H",
    "CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP",
}

EVENT_ORDER = [
    "SETUP_PASS",
    "SETUP_FAIL",
    "SETUP_PASS_NO_ZONE_CONTEXT",
    "OPEN_CONTEXT_NO_FUTURE_CANDLE",
    "ENTER_SIM",
    "EXIT_TARGET_SIM",
    "EXIT_RISK_SIM",
    "MAP_INVALIDATED_PENDING_RECOMPUTE",
    "BLOCK_MARKET_DAMAGE_RISK",
    "BLOCK_AVOID_OR_DO_NOT_ADD",
    "TIMEOUT_SIM",
]


@dataclass(frozen=True)
class PipelineContext:
    asof_ts_utc: datetime
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    selection_state: str | None = None
    setup_filter_state: str | None = None
    setup_filter_reason: str | None = None
    advice_state: str | None = None
    advice_action: str | None = None
    allowed_now: bool | None = None
    leg_direction: str | None = None
    entry_zone_low: Decimal | None = None
    entry_zone_high: Decimal | None = None
    tp_zone_low: Decimal | None = None
    tp_zone_high: Decimal | None = None
    invalidation_price: Decimal | None = None


@dataclass(frozen=True)
class Candle:
    ts_utc: datetime
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class PipelineEvent:
    timestamp_utc: datetime
    event_type: str
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    price: Decimal | None
    setup_filter_reason: str | None
    advice_action: str | None
    selection_state: str | None
    setup_filter_state: str | None
    leg_direction: str | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    target_ref_price: Decimal | None
    invalidation_price: Decimal | None
    notes: str


@dataclass(frozen=True)
class SimulationResult:
    events: list[PipelineEvent]
    skipped_no_future_candle_contexts: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only visual pipeline backtest with Plotly event markers."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--start-ts", required=True)
    parser.add_argument("--end-ts", required=True)
    parser.add_argument("--output-html", required=True)
    parser.add_argument("--output-events-jsonl", default=None)
    parser.add_argument("--output", choices=["summary", "table", "json", "none"], default="summary")
    parser.add_argument("--max-bars", type=int, default=12)
    parser.add_argument(
        "--include-all-contexts",
        action="store_true",
        help="Use every raw observation context instead of the latest context per future candle timestamp.",
    )
    parser.add_argument(
        "--include-open-ended-contexts",
        action="store_true",
        help="Emit OPEN_CONTEXT_NO_FUTURE_CANDLE for contexts with no future candle.",
    )
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, Decimal)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return str(value)
    return value


def fetch_all(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    finally:
        conn.rollback()
        conn.close()


def fetch_candles(
    *,
    asset_id: int,
    venue: str,
    interval_code: str,
    start_ts_utc: datetime,
    end_ts_utc: datetime,
) -> list[Candle]:
    rows = fetch_all(
        """
        SELECT
            open_ts_utc,
            close_ts_utc,
            open_price,
            high_price,
            low_price,
            close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND open_ts_utc >= %s
          AND open_ts_utc < %s
        ORDER BY open_ts_utc
        """,
        (asset_id, venue, interval_code, start_ts_utc, end_ts_utc),
    )
    candles: list[Candle] = []
    for row in rows:
        open_price = dec(row.get("open_price"))
        high_price = dec(row.get("high_price"))
        low_price = dec(row.get("low_price"))
        close_price = dec(row.get("close_price"))
        if None in {open_price, high_price, low_price, close_price}:
            continue
        candles.append(
            Candle(
                ts_utc=row["open_ts_utc"],
                open_ts_utc=row["open_ts_utc"],
                close_ts_utc=row["close_ts_utc"],
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
            )
        )
    return candles


def fetch_observation_contexts(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    start_ts_utc: datetime,
    end_ts_utc: datetime,
) -> list[PipelineContext]:
    contexts: dict[datetime, dict[str, Any]] = {}

    def bucket(asof_ts_utc: datetime) -> dict[str, Any]:
        return contexts.setdefault(
            asof_ts_utc,
            {
                "asof_ts_utc": asof_ts_utc,
                "asset_id": asset_id,
                "symbol": symbol,
                "venue": venue,
                "interval_code": interval_code,
            },
        )

    if table_exists("selection_state"):
        for row in fetch_all(
            """
            SELECT asof_ts_utc, selection_state
            FROM selection_state
            WHERE asset_id = %s
              AND venue = %s
              AND asof_ts_utc >= %s
              AND asof_ts_utc < %s
            ORDER BY asof_ts_utc
            """,
            (asset_id, venue, start_ts_utc, end_ts_utc),
        ):
            data = bucket(row["asof_ts_utc"])
            data["selection_state"] = norm(row.get("selection_state"))

    if table_exists("trade_setup_filter_observation"):
        for row in fetch_all(
            """
            SELECT
                asof_ts_utc,
                selection_state,
                setup_filter_state,
                setup_filter_reason
            FROM trade_setup_filter_observation
            WHERE asset_id = %s
              AND venue = %s
              AND asof_ts_utc >= %s
              AND asof_ts_utc < %s
            ORDER BY asof_ts_utc
            """,
            (asset_id, venue, start_ts_utc, end_ts_utc),
        ):
            data = bucket(row["asof_ts_utc"])
            data["selection_state"] = norm(row.get("selection_state")) or data.get("selection_state")
            data["setup_filter_state"] = norm(row.get("setup_filter_state"))
            data["setup_filter_reason"] = norm(row.get("setup_filter_reason"))

    if table_exists("paper_advice_observation"):
        for row in fetch_all(
            """
            SELECT
                asof_ts_utc,
                selection_state,
                setup_filter_state,
                setup_filter_reason,
                advice_state,
                advice_action,
                allowed_now,
                leg_direction,
                entry_zone_low,
                entry_zone_high,
                tp_zone_low,
                tp_zone_high,
                invalidation_price
            FROM paper_advice_observation
            WHERE asset_id = %s
              AND venue = %s
              AND interval_code = %s
              AND asof_ts_utc >= %s
              AND asof_ts_utc < %s
            ORDER BY asof_ts_utc
            """,
            (asset_id, venue, interval_code, start_ts_utc, end_ts_utc),
        ):
            data = bucket(row["asof_ts_utc"])
            for key in [
                "selection_state",
                "setup_filter_state",
                "setup_filter_reason",
                "advice_state",
                "advice_action",
                "leg_direction",
            ]:
                data[key] = norm(row.get(key)) or data.get(key)
            data["allowed_now"] = bool_or_none(row.get("allowed_now"))
            for key in [
                "entry_zone_low",
                "entry_zone_high",
                "tp_zone_low",
                "tp_zone_high",
                "invalidation_price",
            ]:
                data[key] = dec(row.get(key))

    if table_exists("vw_paper_advice_execution_zone_context_v1"):
        for row in fetch_all(
            """
            SELECT
                asof_ts_utc,
                leg_direction,
                entry_zone_low,
                entry_zone_high,
                tp_zone_low,
                tp_zone_high,
                invalidation_price
            FROM vw_paper_advice_execution_zone_context_v1
            WHERE asset_id = %s
              AND venue = %s
              AND interval_code = %s
              AND asof_ts_utc >= %s
              AND asof_ts_utc < %s
            ORDER BY asof_ts_utc
            """,
            (asset_id, venue, interval_code, start_ts_utc, end_ts_utc),
        ):
            data = bucket(row["asof_ts_utc"])
            data["leg_direction"] = data.get("leg_direction") or norm(row.get("leg_direction"))
            for key in [
                "entry_zone_low",
                "entry_zone_high",
                "tp_zone_low",
                "tp_zone_high",
                "invalidation_price",
            ]:
                data[key] = data.get(key) or dec(row.get(key))

    return [
        PipelineContext(
            asof_ts_utc=data["asof_ts_utc"],
            asset_id=int(data["asset_id"]),
            symbol=str(data["symbol"]),
            venue=str(data["venue"]),
            interval_code=str(data["interval_code"]),
            selection_state=norm(data.get("selection_state")),
            setup_filter_state=norm(data.get("setup_filter_state")),
            setup_filter_reason=norm(data.get("setup_filter_reason")),
            advice_state=norm(data.get("advice_state")),
            advice_action=norm(data.get("advice_action")),
            allowed_now=bool_or_none(data.get("allowed_now")),
            leg_direction=norm(data.get("leg_direction")),
            entry_zone_low=dec(data.get("entry_zone_low")),
            entry_zone_high=dec(data.get("entry_zone_high")),
            tp_zone_low=dec(data.get("tp_zone_low")),
            tp_zone_high=dec(data.get("tp_zone_high")),
            invalidation_price=dec(data.get("invalidation_price")),
        )
        for _, data in sorted(contexts.items())
    ]


def target_ref(context: PipelineContext) -> Decimal | None:
    if context.tp_zone_low is not None and context.tp_zone_high is not None:
        return (context.tp_zone_low + context.tp_zone_high) / Decimal("2")
    return context.tp_zone_low if context.tp_zone_low is not None else context.tp_zone_high


def price_for_event(candle: Candle | None, fallback: Decimal | None = None) -> Decimal | None:
    if fallback is not None:
        return fallback
    if candle is None:
        return None
    return candle.close_price


def make_event(
    context: PipelineContext,
    *,
    event_type: str,
    timestamp_utc: datetime,
    price: Decimal | None,
    notes: str,
) -> PipelineEvent:
    return PipelineEvent(
        timestamp_utc=timestamp_utc,
        event_type=event_type,
        symbol=context.symbol,
        venue=context.venue,
        interval_code=context.interval_code,
        asof_ts_utc=context.asof_ts_utc,
        price=price,
        setup_filter_reason=context.setup_filter_reason,
        advice_action=context.advice_action,
        selection_state=context.selection_state,
        setup_filter_state=context.setup_filter_state,
        leg_direction=context.leg_direction,
        entry_zone_low=context.entry_zone_low,
        entry_zone_high=context.entry_zone_high,
        target_ref_price=target_ref(context),
        invalidation_price=context.invalidation_price,
        notes=notes,
    )


def dedupe_event_key(event: PipelineEvent) -> tuple[Any, ...]:
    return (
        event.symbol,
        event.interval_code,
        event.timestamp_utc,
        event.event_type,
        event.setup_filter_reason,
        event.advice_action,
        event.leg_direction,
    )


def dedupe_events(events: list[PipelineEvent]) -> list[PipelineEvent]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[PipelineEvent] = []
    for event in events:
        key = dedupe_event_key(event)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def target_hit(context: PipelineContext, candle: Candle) -> bool:
    target = target_ref(context)
    direction = (context.leg_direction or "").upper()
    if target is None:
        return False
    if direction == "UP":
        return candle.high_price >= target
    if direction == "DOWN":
        return candle.low_price <= target
    return False


def risk_hit(context: PipelineContext, candle: Candle) -> bool:
    invalidation = context.invalidation_price
    direction = (context.leg_direction or "").upper()
    if invalidation is None:
        return False
    if direction == "UP":
        return candle.low_price < invalidation or candle.close_price < invalidation
    if direction == "DOWN":
        return candle.high_price > invalidation or candle.close_price > invalidation
    return False


def is_blocked(context: PipelineContext) -> str | None:
    if (context.setup_filter_reason or "").upper() == "MARKET_DAMAGE_RISK":
        return "BLOCK_MARKET_DAMAGE_RISK"
    if (context.advice_action or "").upper() in BLOCK_ADVICE_ACTIONS:
        return "BLOCK_AVOID_OR_DO_NOT_ADD"
    return None


def is_actionable(context: PipelineContext) -> bool:
    return (context.setup_filter_state or "").upper() == "PASS"


def has_full_zone_context(context: PipelineContext) -> bool:
    return (
        (context.leg_direction or "").upper() in {"UP", "DOWN"}
        and context.entry_zone_low is not None
        and context.entry_zone_high is not None
        and target_ref(context) is not None
        and context.invalidation_price is not None
    )


def has_exit_sim_context(context: PipelineContext) -> bool:
    return (
        (context.leg_direction or "").upper() in {"UP", "DOWN"}
        and target_ref(context) is not None
        and context.invalidation_price is not None
    )


def future_candles_for_context(
    context: PipelineContext,
    candles: list[Candle],
    max_bars: int,
) -> list[Candle]:
    future = [candle for candle in candles if candle.open_ts_utc > context.asof_ts_utc]
    return future[:max_bars]


def context_event_timestamp(context: PipelineContext, candles: list[Candle]) -> datetime:
    future = future_candles_for_context(context, candles, max_bars=1)
    if future:
        return future[0].open_ts_utc
    return context.asof_ts_utc


def select_latest_context_per_candle(
    contexts: list[PipelineContext],
    candles: list[Candle],
) -> list[PipelineContext]:
    selected: dict[datetime, PipelineContext] = {}
    for context in contexts:
        event_ts = context_event_timestamp(context, candles)
        existing = selected.get(event_ts)
        if existing is None or context.asof_ts_utc > existing.asof_ts_utc:
            selected[event_ts] = context
    return [selected[key] for key in sorted(selected)]


def simulate_events(
    contexts: list[PipelineContext],
    candles: list[Candle],
    *,
    max_bars: int,
    include_open_ended_contexts: bool,
) -> SimulationResult:
    events: list[PipelineEvent] = []
    skipped_no_future_candle_contexts = 0

    for context in contexts:
        future = future_candles_for_context(context, candles, max_bars=max_bars)
        first_candle = future[0] if future else None
        if first_candle is None:
            skipped_no_future_candle_contexts += 1
            if include_open_ended_contexts:
                events.append(
                    make_event(
                        context,
                        event_type="OPEN_CONTEXT_NO_FUTURE_CANDLE",
                        timestamp_utc=context.asof_ts_utc,
                        price=None,
                        notes="selected context has no future candle inside the requested window",
                    )
                )
            continue

        event_ts = first_candle.open_ts_utc

        setup_state = (context.setup_filter_state or "").upper()
        if setup_state == "PASS":
            events.append(
                make_event(
                    context,
                    event_type="SETUP_PASS",
                    timestamp_utc=event_ts,
                    price=price_for_event(first_candle),
                    notes="setup_filter_state=PASS",
                )
            )
        elif setup_state == "FAIL":
            events.append(
                make_event(
                    context,
                    event_type="SETUP_FAIL",
                    timestamp_utc=event_ts,
                    price=price_for_event(first_candle),
                    notes="setup_filter_state=FAIL",
                )
            )

        block_type = is_blocked(context)
        if block_type:
            events.append(
                make_event(
                    context,
                    event_type=block_type,
                    timestamp_utc=event_ts,
                    price=price_for_event(first_candle),
                    notes="blocked before simulated entry",
                )
            )

        for candle in future:
            if context.invalidation_price is not None and risk_hit(context, candle):
                events.append(
                    make_event(
                        context,
                        event_type="MAP_INVALIDATED_PENDING_RECOMPUTE",
                        timestamp_utc=candle.open_ts_utc,
                        price=price_for_event(candle, context.invalidation_price),
                        notes="zone invalidation observed; no zone recompute performed",
                    )
                )
                break

        if block_type or not is_actionable(context):
            continue

        if not has_full_zone_context(context):
            events.append(
                make_event(
                    context,
                    event_type="SETUP_PASS_NO_ZONE_CONTEXT",
                    timestamp_utc=event_ts,
                    price=price_for_event(first_candle),
                    notes="setup_filter_state=PASS but entry/target/risk/leg context is incomplete",
                )
            )
            continue

        enter_candle = future[0]
        events.append(
            make_event(
                context,
                event_type="ENTER_SIM",
                timestamp_utc=enter_candle.open_ts_utc,
                price=enter_candle.close_price,
                notes="research-only simulated entry at first future candle close",
            )
        )

        terminal_event: PipelineEvent | None = None
        if has_exit_sim_context(context):
            for candle in future:
                if risk_hit(context, candle):
                    terminal_event = make_event(
                        context,
                        event_type="EXIT_RISK_SIM",
                        timestamp_utc=candle.open_ts_utc,
                        price=price_for_event(candle, context.invalidation_price),
                        notes="risk/invalidation hit before target",
                    )
                    break
                if target_hit(context, candle):
                    terminal_event = make_event(
                        context,
                        event_type="EXIT_TARGET_SIM",
                        timestamp_utc=candle.open_ts_utc,
                        price=price_for_event(candle, target_ref(context)),
                        notes="target reference hit before timeout",
                    )
                    break

        if terminal_event is None:
            last_candle = future[-1]
            terminal_event = make_event(
                context,
                event_type="TIMEOUT_SIM",
                timestamp_utc=last_candle.open_ts_utc,
                price=last_candle.close_price,
                notes=f"no target/risk hit within {len(future)} bars",
            )
        events.append(terminal_event)

    return SimulationResult(
        events=events,
        skipped_no_future_candle_contexts=skipped_no_future_candle_contexts,
    )


def leakage_bad_row_count(events: list[PipelineEvent]) -> int:
    return sum(1 for event in events if event.asof_ts_utc > event.timestamp_utc)


def event_hover(event: PipelineEvent) -> str:
    return "<br>".join(
        [
            f"timestamp={event.timestamp_utc}",
            f"asof_ts_utc={event.asof_ts_utc}",
            f"event_type={event.event_type}",
            f"setup_filter_reason={event.setup_filter_reason or ''}",
            f"advice_action={event.advice_action or ''}",
            f"selection_state={event.selection_state or ''}",
            f"leg_direction={event.leg_direction or ''}",
            f"entry_zone_low={event.entry_zone_low or ''}",
            f"entry_zone_high={event.entry_zone_high or ''}",
            f"target_ref_price={event.target_ref_price or ''}",
            f"invalidation_price={event.invalidation_price or ''}",
            f"notes={event.notes}",
        ]
    )


def first_zone_context(contexts: list[PipelineContext]) -> PipelineContext | None:
    for context in contexts:
        if (
            context.entry_zone_low is not None
            or context.entry_zone_high is not None
            or context.tp_zone_low is not None
            or context.tp_zone_high is not None
            or context.invalidation_price is not None
        ):
            return context
    return None


def add_zone_overlays(fig: go.Figure, context: PipelineContext | None) -> None:
    if context is None:
        return
    if context.entry_zone_low is not None and context.entry_zone_high is not None:
        fig.add_hrect(
            y0=float(min(context.entry_zone_low, context.entry_zone_high)),
            y1=float(max(context.entry_zone_low, context.entry_zone_high)),
            fillcolor="#2f80ed",
            opacity=0.12,
            line_width=0,
            layer="below",
        )
    if context.tp_zone_low is not None and context.tp_zone_high is not None:
        fig.add_hrect(
            y0=float(min(context.tp_zone_low, context.tp_zone_high)),
            y1=float(max(context.tp_zone_low, context.tp_zone_high)),
            fillcolor="#27ae60",
            opacity=0.10,
            line_width=0,
            layer="below",
        )
    if context.invalidation_price is not None:
        fig.add_hline(
            y=float(context.invalidation_price),
            line_width=1,
            line_dash="dot",
            line_color="#c0392b",
            opacity=0.75,
        )


def render_chart(
    *,
    chart_frame: pd.DataFrame,
    selection_frame: pd.DataFrame,
    contexts: list[PipelineContext],
    events: list[PipelineEvent],
    title: str,
    output_html: Path,
) -> None:
    frame = prepare_chart_frame(chart_frame)
    selection = prepare_selection_frame(selection_frame)

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=frame["ts_utc"] if not frame.empty else [],
            open=frame["open_price"] if not frame.empty else [],
            high=frame["high_price"] if not frame.empty else [],
            low=frame["low_price"] if not frame.empty else [],
            close=frame["close_price"] if not frame.empty else [],
            name="OHLC",
        )
    )

    if not selection.empty and "asof_ts_utc" in selection.columns:
        for _, row in selection.iterrows():
            fig.add_vline(
                x=row["asof_ts_utc"],
                line_width=1,
                opacity=0.12,
                line_color="#666",
            )

    add_zone_overlays(fig, first_zone_context(contexts))

    marker_styles = {
        "SETUP_PASS_NO_ZONE_CONTEXT": ("circle-open", "#7f7f7f", 10),
        "ENTER_SIM": ("triangle-up", "#1f77b4", 11),
        "EXIT_TARGET_SIM": ("star", "#2ca02c", 13),
        "EXIT_RISK_SIM": ("x", "#d62728", 12),
        "MAP_INVALIDATED_PENDING_RECOMPUTE": ("diamond", "#ff7f0e", 12),
        "BLOCK_MARKET_DAMAGE_RISK": ("octagon", "#8c564b", 11),
        "BLOCK_AVOID_OR_DO_NOT_ADD": ("square", "#9467bd", 10),
    }

    for event_type, (symbol, color, size) in marker_styles.items():
        matching = [event for event in events if event.event_type == event_type and event.price is not None]
        if not matching:
            continue
        fig.add_trace(
            go.Scatter(
                x=[event.timestamp_utc for event in matching],
                y=[float(event.price) for event in matching],
                mode="markers",
                name=event_type,
                marker={"symbol": symbol, "color": color, "size": size, "line": {"width": 1}},
                text=[event_hover(event) for event in matching],
                hovertemplate="%{text}<extra></extra>",
            )
        )

    fig.update_layout(
        title=title,
        height=820,
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        margin={"l": 42, "r": 24, "t": 64, "b": 36},
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Price")
    fig.update_xaxes(title_text="UTC")

    output_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_html), include_plotlyjs="cdn", full_html=True)


def write_events_jsonl(events: list[PipelineEvent], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for event in events:
            payload = {key: json_ready(value) for key, value in asdict(event).items()}
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def print_summary(
    *,
    events: list[PipelineEvent],
    raw_event_count: int,
    selected_context_count: int,
    raw_context_count: int,
    skipped_no_future_candle_contexts: int,
    bad_rows: int,
    output: str,
) -> None:
    counts = Counter(event.event_type for event in events)
    summary = {event_type: counts.get(event_type, 0) for event_type in EVENT_ORDER}
    summary["raw_context_count"] = raw_context_count
    summary["selected_context_count"] = selected_context_count
    summary["skipped_no_future_candle_contexts"] = skipped_no_future_candle_contexts
    summary["raw_event_count"] = raw_event_count
    summary["unique_event_count"] = len(events)
    summary["bad_rows"] = bad_rows
    summary["total_events"] = len(events)

    if output == "json":
        print(json.dumps(summary, sort_keys=True))
    elif output == "table":
        print("event_type,count")
        for event_type in EVENT_ORDER:
            print(f"{event_type},{counts.get(event_type, 0)}")
        print(f"raw_context_count,{raw_context_count}")
        print(f"selected_context_count,{selected_context_count}")
        print(f"skipped_no_future_candle_contexts,{skipped_no_future_candle_contexts}")
        print(f"raw_event_count,{raw_event_count}")
        print(f"unique_event_count,{len(events)}")
        print(f"bad_rows,{bad_rows}")
        print(f"total_events,{len(events)}")
    elif output == "summary":
        print("summary_counts=" + json.dumps(summary, sort_keys=True))

    print("broker_private_calls=0 broker_writes=0 order_submission=0 executor=none")


def main() -> int:
    args = parse_args()
    if args.max_bars <= 0:
        raise ValueError("--max-bars must be positive")

    start_ts_utc = parse_ts(args.start_ts)
    end_ts_utc = parse_ts(args.end_ts)
    if end_ts_utc <= start_ts_utc:
        raise ValueError("--end-ts must be after --start-ts")

    asset = resolve_asset(args.symbol)
    if asset is None:
        raise ValueError(f"Unknown asset symbol: {args.symbol}")

    chart_frame = fetch_chart_frame(
        asset_id=asset.asset_id,
        venue=args.venue,
        interval_code=args.interval,
        start_ts_utc=start_ts_utc,
        end_ts_utc=end_ts_utc,
        max_candles=5000,
    )
    selection_frame = fetch_selection_frame(
        asset_id=asset.asset_id,
        venue=args.venue,
        start_ts_utc=start_ts_utc,
        end_ts_utc=end_ts_utc,
        max_rows=5000,
    )
    candles = fetch_candles(
        asset_id=asset.asset_id,
        venue=args.venue,
        interval_code=args.interval,
        start_ts_utc=start_ts_utc,
        end_ts_utc=end_ts_utc,
    )
    contexts = fetch_observation_contexts(
        asset_id=asset.asset_id,
        symbol=asset.symbol,
        venue=args.venue,
        interval_code=args.interval,
        start_ts_utc=start_ts_utc,
        end_ts_utc=end_ts_utc,
    )
    raw_context_count = len(contexts)
    selected_contexts = (
        contexts
        if args.include_all_contexts
        else select_latest_context_per_candle(contexts, candles)
    )
    simulation = simulate_events(
        selected_contexts,
        candles,
        max_bars=args.max_bars,
        include_open_ended_contexts=args.include_open_ended_contexts,
    )
    raw_events = simulation.events
    events = dedupe_events(raw_events)
    artifact_events = (
        events
        if args.include_open_ended_contexts
        else [event for event in events if event.price is not None]
    )
    bad_rows = leakage_bad_row_count(events)

    render_chart(
        chart_frame=chart_frame,
        selection_frame=selection_frame,
        contexts=selected_contexts,
        events=artifact_events,
        title=f"{REPORT_NAME} {REPORT_VERSION} - {asset.symbol} {args.venue} {args.interval}",
        output_html=Path(args.output_html),
    )

    if args.output_events_jsonl:
        write_events_jsonl(artifact_events, Path(args.output_events_jsonl))

    print(f"report_name={REPORT_NAME} report_version={REPORT_VERSION}")
    print(f"symbol={asset.symbol} venue={args.venue} interval={args.interval}")
    print(
        f"candles={len(candles)} raw_contexts={raw_context_count} "
        f"selected_contexts={len(selected_contexts)} raw_events={len(raw_events)} "
        f"unique_events={len(events)} skipped_no_future_candle_contexts="
        f"{simulation.skipped_no_future_candle_contexts} bad_rows={bad_rows}"
    )
    if not any(event.event_type == "MAP_INVALIDATED_PENDING_RECOMPUTE" for event in events):
        print(
            "map_invalidated_pending_recompute=0 "
            "reason=no future candle crossed the available invalidation_price for the observed leg_direction"
        )
    print_summary(
        events=events,
        raw_event_count=len(raw_events),
        selected_context_count=len(selected_contexts),
        raw_context_count=raw_context_count,
        skipped_no_future_candle_contexts=simulation.skipped_no_future_candle_contexts,
        bad_rows=bad_rows,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
