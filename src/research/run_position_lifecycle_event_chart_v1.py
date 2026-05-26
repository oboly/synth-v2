from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.reporting.dashboard_style_v1 import cockpit_base_css, cockpit_nav


REPORT_NAME = "position_lifecycle_event_chart_v1"
REPORT_VERSION = "1.0"

DEFAULT_INPUT_ROWS = Path("data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_OUTPUT_DIR = Path("data/research/position_lifecycle_event_chart_v1")
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_CHART_INTERVAL = "15m"
DEFAULT_BEFORE_HOURS = 48
DEFAULT_AFTER_HOURS = 24
DEFAULT_MAX_CHARTS = 50

INDEX_HTML = "index.html"
MANIFEST_JSON = "manifest_v1.json"
SELECTED_EVENTS_JSONL = "selected_events_v1.jsonl"

SORT_CHOICES = (
    "adjusted4h_desc",
    "adjusted4h_asc",
    "event_ts_desc",
    "mae_desc",
    "mfe_desc",
    "opportunity_cost4h_desc",
    "avoided_drawdown4h_desc",
)


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float


@dataclass(frozen=True)
class OutputPaths:
    index_html: Path
    manifest_json: Path
    selected_events_jsonl: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render research-only visual review charts for selected position lifecycle events "
            "(SVG + static HTML, no lifecycle recomputation, no execution)."
        )
    )
    parser.add_argument("--input-rows", default=str(DEFAULT_INPUT_ROWS))
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--chart-interval", default=DEFAULT_CHART_INTERVAL)
    parser.add_argument("--before-hours", type=int, default=DEFAULT_BEFORE_HOURS)
    parser.add_argument("--after-hours", type=int, default=DEFAULT_AFTER_HOURS)
    parser.add_argument("--max-charts", type=int, default=DEFAULT_MAX_CHARTS)
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--action", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--sort", choices=SORT_CHOICES, default="adjusted4h_desc")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def esc(value: Any) -> str:
    return (
        str("" if value is None else value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            loaded = json.loads(payload)
            if isinstance(loaded, dict):
                rows.append(loaded)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def build_output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        index_html=output_dir / INDEX_HTML,
        manifest_json=output_dir / MANIFEST_JSON,
        selected_events_jsonl=output_dir / SELECTED_EVENTS_JSONL,
    )


def bucket_name(row: dict[str, Any]) -> str:
    return f"{row.get('position_lifecycle_action')}|{row.get('reason_bucket')}"


def load_selected_rows(
    *,
    input_rows: Path,
    venue: str,
    quote: str,
    bucket: str | None,
    action: str | None,
    symbol: str | None,
    sort_name: str,
    max_charts: int,
) -> list[dict[str, Any]]:
    rows = read_jsonl(input_rows)
    selected: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("venue") or "").lower() != venue.lower():
            continue
        if str(row.get("quote") or "").upper() != quote.upper():
            continue
        if bucket and bucket_name(row) != bucket:
            continue
        if action and str(row.get("position_lifecycle_action") or "").upper() != str(action).upper():
            continue
        if symbol and str(row.get("symbol") or "").upper() != str(symbol).upper():
            continue
        selected.append(row)
    selected.sort(key=sort_key(sort_name))
    if max_charts <= 0:
        raise ValueError("--max-charts must be greater than zero")
    return selected[:max_charts]


def sort_key(sort_name: str):
    def number_desc(field: str):
        return lambda row: (-(as_float(row.get(field)) or float("-inf")), str(row.get("symbol") or ""), str(row.get("event_ts_utc") or ""))

    def number_asc(field: str):
        return lambda row: ((as_float(row.get(field)) if as_float(row.get(field)) is not None else float("inf")), str(row.get("symbol") or ""), str(row.get("event_ts_utc") or ""))

    if sort_name == "adjusted4h_desc":
        return number_desc("adjusted_return_score_4h")
    if sort_name == "adjusted4h_asc":
        return number_asc("adjusted_return_score_4h")
    if sort_name == "mae_desc":
        return number_desc("max_adverse_excursion_pct")
    if sort_name == "mfe_desc":
        return number_desc("max_favorable_excursion_pct")
    if sort_name == "opportunity_cost4h_desc":
        return number_desc("opportunity_cost_4h")
    if sort_name == "avoided_drawdown4h_desc":
        return number_desc("avoided_drawdown_score_4h")
    if sort_name == "event_ts_desc":
        return lambda row: (-parse_ts(row.get("event_ts_utc")).timestamp(), str(row.get("symbol") or ""))
    raise ValueError(f"Unsupported sort: {sort_name}")


def fetch_asset_map(conn: Any, symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}
    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"SELECT asset_id, symbol FROM asset WHERE symbol IN ({placeholders})"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(symbols))
        rows = cur.fetchall()
    return {str(row["symbol"]).upper(): int(row["asset_id"]) for row in rows}


def to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def fetch_candles(
    conn: Any,
    *,
    asset_ids: dict[str, int],
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
) -> dict[str, list[Candle]]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT asset_id, close_ts_utc, open_price, high_price, low_price, close_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id ASC, close_ts_utc ASC
    """
    params: list[Any] = [venue, interval_code, to_naive_utc(start_ts), to_naive_utc(end_ts), *asset_ids.values()]
    reverse_asset = {asset_id: symbol for symbol, asset_id in asset_ids.items()}
    grouped: dict[str, list[Candle]] = {symbol: [] for symbol in asset_ids}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    for row in rows:
        symbol = reverse_asset.get(int(row["asset_id"]))
        if symbol is None:
            continue
        close_ts = row["close_ts_utc"]
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        else:
            close_ts = close_ts.astimezone(UTC)
        grouped[symbol].append(
            Candle(
                close_ts_utc=close_ts,
                open_price=float(row["open_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                close_price=float(row["close_price"]),
            )
        )
    return grouped


def chart_file_name(row: dict[str, Any], index: int) -> str:
    symbol = re.sub(r"[^A-Za-z0-9_-]+", "_", str(row.get("symbol") or "UNK"))
    action = re.sub(r"[^A-Za-z0-9_-]+", "_", str(row.get("position_lifecycle_action") or "ACTION"))
    ts = re.sub(r"[^0-9A-Za-z]+", "", str(row.get("event_ts_utc") or "ts"))
    return f"chart_{index:03d}_{symbol}_{action}_{ts}.svg"


def pill_html(text: str, css_name: str) -> str:
    return f"<span class='pill {esc(css_name)}'>{esc(text)}</span>"


def text_line(x: float, y: float, text: str, *, fill: str = "#e7edf8", size: int = 13, weight: str = "400") -> str:
    return f"<text x='{x:.1f}' y='{y:.1f}' fill='{fill}' font-size='{size}' font-weight='{weight}' font-family='system-ui, sans-serif'>{esc(text)}</text>"


def format_pct(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return "NA"
    return f"{number:+.3f}%"


def format_price(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return "NA"
    return f"{number:.4f}"


def guidance_label(row: dict[str, Any]) -> str:
    adjusted4h = as_float(row.get("adjusted_return_score_4h"))
    raw4h = as_float((row.get("forward_returns") or {}).get("4h"))
    mfe = as_float(row.get("max_favorable_excursion_pct"))
    mae = as_float(row.get("max_adverse_excursion_pct"))
    bucket = str(row.get("reason_bucket") or "").upper()
    if bucket in {"UNKNOWN_REASON_BUCKET"} or not row.get("entry_zone_low"):
        return "NEEDS_ZONE_CONTEXT"
    if adjusted4h is not None and adjusted4h >= 0.5:
        return "GOOD_TRIGGER"
    if adjusted4h is not None and adjusted4h < 0:
        return "WRONG_ACTION"
    if mfe is not None and mae is not None and abs(mae) >= 2.0 and abs(mfe) < 1.0:
        return "TOO_EARLY"
    if raw4h is not None and abs(raw4h) < 0.15:
        return "NOISY"
    return "TOO_LATE"


def guidance_css(label: str) -> str:
    if label in {"GOOD_TRIGGER"}:
        return "ok"
    if label in {"TOO_EARLY", "TOO_LATE", "NOISY", "NEEDS_ZONE_CONTEXT"}:
        return "warn"
    return "bad"


def line_y(value: float, min_price: float, max_price: float, top: float, height: float) -> float:
    if math.isclose(max_price, min_price):
        return top + height / 2.0
    return top + (max_price - value) / (max_price - min_price) * height


def chart_svg(row: dict[str, Any], candles: list[Candle], *, before_hours: int, after_hours: int) -> str:
    event_ts = parse_ts(row["event_ts_utc"])
    start_ts = event_ts - timedelta(hours=before_hours)
    end_ts = event_ts + timedelta(hours=after_hours)
    window = [c for c in candles if start_ts <= c.close_ts_utc <= end_ts]
    width = 1440
    height = 820
    left = 84.0
    right = 48.0
    top = 190.0
    bottom = 88.0
    plot_width = width - left - right
    plot_height = height - top - bottom

    if not window:
        return (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
            f"<rect width='{width}' height='{height}' fill='#0b1020'/>"
            f"{text_line(24, 42, str(row.get('symbol') or 'UNKNOWN') + ' lifecycle review chart', size=24, weight='700')}"
            f"{text_line(24, 82, 'No candles available for selected chart window.', fill='#ff6b6b', size=16, weight='600')}"
            f"</svg>"
        )

    prices = [c.high_price for c in window] + [c.low_price for c in window]
    overlay_values = [
        as_float(row.get("reference_price")),
        as_float(row.get("current_price")),
        as_float(row.get("entry_zone_low")),
        as_float(row.get("entry_zone_high")),
        as_float(row.get("tp_zone_low")),
        as_float(row.get("tp_zone_high")),
        as_float(row.get("invalidation_price")),
    ]
    for value in overlay_values:
        if value is not None:
            prices.append(value)
    min_price = min(prices)
    max_price = max(prices)
    if math.isclose(min_price, max_price):
        min_price *= 0.995
        max_price *= 1.005
    else:
        pad = (max_price - min_price) * 0.08
        min_price -= pad
        max_price += pad

    def x_for_ts(ts: datetime) -> float:
        span = max((end_ts - start_ts).total_seconds(), 1.0)
        progress = (ts - start_ts).total_seconds() / span
        return left + progress * plot_width

    pieces: list[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        f"<rect width='{width}' height='{height}' fill='#0b1020'/>",
        f"<rect x='{left:.1f}' y='{top:.1f}' width='{plot_width:.1f}' height='{plot_height:.1f}' rx='10' fill='#121a2f' stroke='#273657'/>",
        text_line(24, 38, f"{row.get('symbol')} {row.get('position_lifecycle_action')} {row.get('reason_bucket')}", size=24, weight="700"),
        text_line(24, 66, f"event_ts={row.get('event_ts_utc')}  guidance={guidance_label(row)}", fill="#8ea0bf", size=14),
        text_line(24, 92, f"reason={str(row.get('position_lifecycle_reason') or 'NA')[:150]}", fill="#e7edf8", size=14),
        text_line(
            24,
            118,
            "returns "
            f"15m={format_pct((row.get('forward_returns') or {}).get('15m'))} "
            f"1h={format_pct((row.get('forward_returns') or {}).get('1h'))} "
            f"4h={format_pct((row.get('forward_returns') or {}).get('4h'))} "
            f"24h={format_pct((row.get('forward_returns') or {}).get('24h'))}",
            fill="#7aa2ff",
            size=14,
        ),
        text_line(
            24,
            144,
            f"adjusted4h={format_pct(row.get('adjusted_return_score_4h'))} "
            f"adjusted24h={format_pct(row.get('adjusted_return_score_24h'))} "
            f"mfe={format_pct(row.get('max_favorable_excursion_pct'))} "
            f"mae={format_pct(row.get('max_adverse_excursion_pct'))}",
            fill="#55d6a7",
            size=14,
        ),
    ]

    for idx in range(5):
        value = min_price + (max_price - min_price) * idx / 4.0
        y = line_y(value, min_price, max_price, top, plot_height)
        pieces.append(f"<line x1='{left:.1f}' y1='{y:.1f}' x2='{left + plot_width:.1f}' y2='{y:.1f}' stroke='#273657' stroke-width='1' stroke-dasharray='2 4'/>")
        pieces.append(text_line(12, y + 4, format_price(value), fill="#8ea0bf", size=12))

    candle_width = max(2.0, plot_width / max(len(window), 1) * 0.55)
    for candle in window:
        x = x_for_ts(candle.close_ts_utc)
        wick_y1 = line_y(candle.high_price, min_price, max_price, top, plot_height)
        wick_y2 = line_y(candle.low_price, min_price, max_price, top, plot_height)
        open_y = line_y(candle.open_price, min_price, max_price, top, plot_height)
        close_y = line_y(candle.close_price, min_price, max_price, top, plot_height)
        body_top = min(open_y, close_y)
        body_height = max(abs(open_y - close_y), 1.5)
        fill = "#55d6a7" if candle.close_price >= candle.open_price else "#ff6b6b"
        pieces.append(f"<line x1='{x:.1f}' y1='{wick_y1:.1f}' x2='{x:.1f}' y2='{wick_y2:.1f}' stroke='{fill}' stroke-width='1.2'/>")
        pieces.append(
            f"<rect x='{x - candle_width / 2:.1f}' y='{body_top:.1f}' width='{candle_width:.1f}' height='{body_height:.1f}' "
            f"fill='{fill}' fill-opacity='0.85' stroke='{fill}' stroke-width='1'/>"
        )

    event_x = x_for_ts(event_ts)
    pieces.append(f"<line x1='{event_x:.1f}' y1='{top:.1f}' x2='{event_x:.1f}' y2='{top + plot_height:.1f}' stroke='#ffd166' stroke-width='2' stroke-dasharray='6 4'/>")
    pieces.append(text_line(event_x + 6, top + 18, "EVENT", fill="#ffd166", size=12, weight="700"))

    def horizontal_overlay(value: float | None, color: str, label: str, dash: str = "6 4") -> None:
        if value is None:
            return
        y = line_y(value, min_price, max_price, top, plot_height)
        pieces.append(f"<line x1='{left:.1f}' y1='{y:.1f}' x2='{left + plot_width:.1f}' y2='{y:.1f}' stroke='{color}' stroke-width='1.6' stroke-dasharray='{dash}'/>")
        pieces.append(text_line(left + plot_width - 180, y - 4, f'{label} {format_price(value)}', fill=color, size=12, weight="600"))

    horizontal_overlay(as_float(row.get("reference_price")) or as_float(row.get("current_price")), "#7aa2ff", "reference", "2 4")
    horizontal_overlay(as_float(row.get("entry_zone_low")), "#55d6a7", "entry_low")
    horizontal_overlay(as_float(row.get("entry_zone_high")), "#55d6a7", "entry_high")
    horizontal_overlay(as_float(row.get("tp_zone_low")), "#ffd166", "target_low")
    horizontal_overlay(as_float(row.get("tp_zone_high")), "#ffd166", "target_high")
    horizontal_overlay(as_float(row.get("invalidation_price")), "#ff6b6b", "invalidation")

    secondary = ", ".join(str(item) for item in (row.get("secondary_reason_buckets") or [])[:6]) or "NA"
    source_modules = ", ".join(str(item) for item in (row.get("source_modules") or [])[:5]) or "NA"
    missing_inputs = ", ".join(str(item) for item in (row.get("missing_inputs") or [])[:5]) or "none"
    pieces.append(text_line(24, height - 56, f"secondary={secondary}", fill="#8ea0bf", size=12))
    pieces.append(text_line(24, height - 36, f"source_modules={source_modules}", fill="#8ea0bf", size=12))
    pieces.append(text_line(24, height - 16, f"missing_inputs={missing_inputs}", fill="#8ea0bf", size=12))
    pieces.append("</svg>")
    return "".join(pieces)


def render_index_html(
    *,
    rows: list[dict[str, Any]],
    chart_files: list[str],
    args: argparse.Namespace,
    selected_events_path: Path,
) -> str:
    guidance_html = " ".join(
        [
            pill_html("GOOD_TRIGGER", "ok"),
            pill_html("TOO_EARLY", "warn"),
            pill_html("TOO_LATE", "warn"),
            pill_html("NOISY", "warn"),
            pill_html("WRONG_ACTION", "bad"),
            pill_html("NEEDS_ZONE_CONTEXT", "context"),
        ]
    )
    table_rows: list[str] = []
    for row, chart_file in zip(rows, chart_files, strict=True):
        table_rows.append(
            "<tr>"
            f"<td>{esc(row.get('symbol'))}</td>"
            f"<td>{esc(row.get('event_ts_utc'))}</td>"
            f"<td>{pill_html(str(row.get('position_lifecycle_action') or ''), 'context')}</td>"
            f"<td>{pill_html(str(row.get('reason_bucket') or ''), 'muted')}</td>"
            f"<td class='right'>{esc(format_pct(row.get('adjusted_return_score_4h')))}</td>"
            f"<td class='right'>{esc(format_pct(row.get('adjusted_return_score_24h')))}</td>"
            f"<td class='right'>{esc(format_pct((row.get('forward_returns') or {}).get('4h')))}</td>"
            f"<td class='right'>{esc(format_pct((row.get('forward_returns') or {}).get('24h')))}</td>"
            f"<td class='right'>{esc(format_pct(row.get('max_favorable_excursion_pct')))}</td>"
            f"<td class='right'>{esc(format_pct(row.get('max_adverse_excursion_pct')))}</td>"
            f"<td>{pill_html(guidance_label(row), guidance_css(guidance_label(row)))}</td>"
            f"<td><a href='{esc(chart_file)}'>chart</a></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Position Lifecycle Event Chart V1</title>
  <style>
  {cockpit_base_css(min_table_width=1320)}
  .banner {{ background: #121a2f; border: 1px solid #273657; border-radius: 12px; padding: 16px; }}
  .kv {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px 14px; color: #8ea0bf; }}
  .kv strong {{ color: #e7edf8; }}
  .review-help {{ line-height: 1.5; color: #8ea0bf; }}
  a {{ color: #7aa2ff; }}
  </style>
</head>
<body>
  <div class="page">
    {cockpit_nav()}
    <header>
      <h1>Position Lifecycle Visual Event Review</h1>
      <p class="muted">Research-only visualization. No lifecycle recomputation, no paper trading, no live trading, no executor.</p>
    </header>
    <main>
      <section class="banner">
        <div class="kv">
          <div><strong>input_rows</strong> {esc(args.input_rows)}</div>
          <div><strong>venue</strong> {esc(args.venue)}</div>
          <div><strong>quote</strong> {esc(args.quote)}</div>
          <div><strong>chart_interval</strong> {esc(args.chart_interval)}</div>
          <div><strong>before_hours</strong> {esc(args.before_hours)}</div>
          <div><strong>after_hours</strong> {esc(args.after_hours)}</div>
          <div><strong>max_charts</strong> {esc(args.max_charts)}</div>
          <div><strong>bucket</strong> {esc(args.bucket or 'ALL')}</div>
          <div><strong>action</strong> {esc(args.action or 'ALL')}</div>
          <div><strong>symbol</strong> {esc(args.symbol or 'ALL')}</div>
          <div><strong>sort</strong> {esc(args.sort)}</div>
          <div><strong>selected_events</strong> <a href="{esc(selected_events_path.name)}">{esc(selected_events_path.name)}</a></div>
        </div>
      </section>
      <section class="panel">
        <h2>Safety</h2>
        <p>{pill_html('db_writes=0', 'ok')} {pill_html('broker_calls=0', 'ok')} {pill_html('broker_writes=0', 'ok')} {pill_html('order_submission=0', 'ok')} {pill_html('executor=none', 'ok')} {pill_html('live_trading=false', 'ok')} {pill_html('visualization_only=true', 'ok')}</p>
      </section>
      <section class="panel">
        <h2>Review Guidance</h2>
        <p>{guidance_html}</p>
        <div class="review-help">
          <div><strong>GOOD_TRIGGER</strong> adjusted outcome and structure context both look supportive.</div>
          <div><strong>TOO_EARLY</strong> review arrived before the move stabilized and drawdown dominated first.</div>
          <div><strong>TOO_LATE</strong> some move already happened and remaining edge looks reduced.</div>
          <div><strong>NOISY</strong> small forward move relative to noise; chart inspection still required.</div>
          <div><strong>WRONG_ACTION</strong> adjusted score stayed negative for the chosen lifecycle action.</div>
          <div><strong>NEEDS_ZONE_CONTEXT</strong> zone or structure fields were missing or too weak for reliable review.</div>
        </div>
      </section>
      <section class="panel">
        <h2>Selected Events</h2>
        <div class="table-wrap">
          <table class="sticky-table">
            <thead>
              <tr>
                <th>symbol</th>
                <th>event_ts_utc</th>
                <th>action</th>
                <th>primary_reason_bucket</th>
                <th class="right">adjusted4h</th>
                <th class="right">adjusted24h</th>
                <th class="right">raw4h</th>
                <th class="right">raw24h</th>
                <th class="right">mfe</th>
                <th class="right">mae</th>
                <th>guidance</th>
                <th>chart</th>
              </tr>
            </thead>
            <tbody>
              {''.join(table_rows)}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  </div>
</body>
</html>
"""


def build_manifest(*, args: argparse.Namespace, rows: list[dict[str, Any]], output_paths: OutputPaths, chart_files: list[str]) -> dict[str, Any]:
    event_timestamps = [parse_ts(row["event_ts_utc"]) for row in rows if row.get("event_ts_utc")]
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "input_rows": str(args.input_rows),
        "output_dir": str(Path(args.output_dir)),
        "chart_interval": args.chart_interval,
        "before_hours": int(args.before_hours),
        "after_hours": int(args.after_hours),
        "max_charts": int(args.max_charts),
        "selected_count": len(rows),
        "bucket_filter": args.bucket,
        "action_filter": args.action,
        "symbol_filter": args.symbol,
        "sort": args.sort,
        "symbols": sorted({str(row.get("symbol") or "") for row in rows if row.get("symbol")}),
        "first_event_ts": None if not event_timestamps else fmt_ts(min(event_timestamps)),
        "latest_event_ts": None if not event_timestamps else fmt_ts(max(event_timestamps)),
        "files": {
            "index_html": str(output_paths.index_html),
            "manifest_json": str(output_paths.manifest_json),
            "selected_events_jsonl": str(output_paths.selected_events_jsonl),
            "charts": chart_files,
        },
        "safety": {
            "db_writes": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "executor": "none",
            "live_trading": False,
            "visualization_only": True,
        },
    }


def print_summary(summary: dict[str, Any], *, output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
        return
    print(f"report={summary['report']} version={summary['version']}")
    print(
        f"selected_count={summary['selected_count']} sort={summary['sort']} "
        f"bucket={summary['bucket_filter'] or 'ALL'} action={summary['action_filter'] or 'ALL'} symbol={summary['symbol_filter'] or 'ALL'}"
    )
    print(
        f"chart_interval={summary['chart_interval']} before_hours={summary['before_hours']} after_hours={summary['after_hours']} "
        f"max_charts={summary['max_charts']}"
    )
    print(
        "safety "
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 executor=none live_trading=false visualization_only=true"
    )
    if summary["selected_count"]:
        print(f"first_event_ts={summary['first_event_ts']} latest_event_ts={summary['latest_event_ts']}")
    print("files " + " ".join([f"index_html={summary['files']['index_html']}", f"selected_events_jsonl={summary['files']['selected_events_jsonl']}"]))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_rows = Path(args.input_rows)
    output_dir = Path(args.output_dir)
    paths = build_output_paths(output_dir)

    selected_rows = load_selected_rows(
        input_rows=input_rows,
        venue=args.venue,
        quote=args.quote,
        bucket=args.bucket,
        action=args.action,
        symbol=args.symbol,
        sort_name=args.sort,
        max_charts=args.max_charts,
    )
    if not selected_rows:
        raise FileNotFoundError(f"No lifecycle outcome rows matched filters in {input_rows}")

    event_timestamps = [parse_ts(row["event_ts_utc"]) for row in selected_rows]
    start_ts = min(event_timestamps) - timedelta(hours=int(args.before_hours))
    end_ts = max(event_timestamps) + timedelta(hours=int(args.after_hours))
    symbols = sorted({str(row.get("symbol") or "").upper() for row in selected_rows if row.get("symbol")})

    conn = get_connection()
    try:
        asset_ids = fetch_asset_map(conn, symbols)
        candles_by_symbol = fetch_candles(
            conn,
            asset_ids=asset_ids,
            venue=args.venue,
            interval_code=args.chart_interval,
            start_ts=start_ts,
            end_ts=end_ts,
        )
    finally:
        conn.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    chart_files: list[str] = []
    for index, row in enumerate(selected_rows, start=1):
        chart_name = chart_file_name(row, index)
        chart_files.append(chart_name)
        svg = chart_svg(
            row,
            candles_by_symbol.get(str(row.get("symbol") or "").upper(), []),
            before_hours=int(args.before_hours),
            after_hours=int(args.after_hours),
        )
        if args.write_files:
            (output_dir / chart_name).write_text(svg, encoding="utf-8")

    index_html = render_index_html(
        rows=selected_rows,
        chart_files=chart_files,
        args=args,
        selected_events_path=paths.selected_events_jsonl,
    )
    manifest = build_manifest(args=args, rows=selected_rows, output_paths=paths, chart_files=chart_files)

    if args.write_files:
        paths.index_html.write_text(index_html, encoding="utf-8")
        write_json(paths.manifest_json, manifest)
        write_jsonl(paths.selected_events_jsonl, selected_rows)

    print_summary(manifest, output_mode=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
