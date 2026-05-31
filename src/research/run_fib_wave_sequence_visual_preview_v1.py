from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "fib_wave_sequence_visual_preview_v1"
REPORT_VERSION = "0.1"
SOURCE_TABLE = "obs_market_candle"

DEFAULT_VENUE = "bitvavo"
DEFAULT_SYMBOL = "BTC"
DEFAULT_INTERVAL = "1d"
DEFAULT_LOOKBACK_CANDLES = 900
DEFAULT_DETECTOR = "zigzag_percent"
DEFAULT_SWING_WINDOW = 10
DEFAULT_ZIGZAG_PERCENT = 20.0
DEFAULT_MAJOR_FILTER = "none"
DEFAULT_MIN_LEG_VS_PREVIOUS_RATIO = 0.0
DEFAULT_MIN_LEG_DURATION_CANDLES = 0
DEFAULT_OUTPUT_HTML = "/tmp/fib_wave_sequence_BTC_1d.html"

SVG_WIDTH = 1120
SVG_HEIGHT = 360
SVG_PAD_LEFT = 64
SVG_PAD_RIGHT = 24
SVG_PAD_TOP = 22
SVG_PAD_BOTTOM = 44

WAVE_NAMES = ["W1", "W2", "W3", "W4", "W5", "A", "B", "C"]


@dataclass(frozen=True)
class AssetRef:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class Candle:
    candle_index: int
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float


@dataclass(frozen=True)
class Pivot:
    candle_index: int
    pivot_kind: str
    ts_utc: datetime
    price: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a static visual preview of the latest candidate P0-P8 wave sequence "
            "from public candles only (research-only, candidate labels only, no targets)."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument(
        "--detector",
        choices=("local_pivot_window", "zigzag_percent"),
        default=DEFAULT_DETECTOR,
    )
    parser.add_argument("--swing-window", type=int, default=DEFAULT_SWING_WINDOW)
    parser.add_argument("--zigzag-percent", type=float, default=DEFAULT_ZIGZAG_PERCENT)
    parser.add_argument(
        "--major-filter",
        choices=("none", "relative_move", "duration", "relative_move_and_duration"),
        default=DEFAULT_MAJOR_FILTER,
    )
    parser.add_argument(
        "--min-leg-vs-previous-ratio",
        type=float,
        default=DEFAULT_MIN_LEG_VS_PREVIOUS_RATIO,
    )
    parser.add_argument(
        "--min-leg-duration-candles",
        type=int,
        default=DEFAULT_MIN_LEG_DURATION_CANDLES,
    )
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def fmt_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10f}"


def fmt_number(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def fetch_asset(conn: Any, *, symbol: str) -> AssetRef:
    sql = """
        SELECT asset_id, symbol
        FROM asset
        WHERE UPPER(symbol) = UPPER(%s)
          AND is_enabled = 1
        ORDER BY asset_id ASC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Enabled asset not found for symbol={symbol}")
    return AssetRef(asset_id=int(row["asset_id"]), symbol=str(row["symbol"]).upper())


def fetch_recent_candles(
    conn: Any,
    *,
    asset: AssetRef,
    venue: str,
    interval_code: str,
    lookback_candles: int,
) -> list[Candle]:
    sql = """
        SELECT
            open_ts_utc,
            close_ts_utc,
            open_price,
            close_price,
            high_price,
            low_price,
            COALESCE(volume_quote_eur, volume_base, 0) AS volume
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND asset_id = %s
        ORDER BY close_ts_utc DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, asset.asset_id, lookback_candles))
        rows = list(cur.fetchall())

    candles: list[Candle] = []
    for idx, row in enumerate(reversed(rows)):
        open_ts = row["open_ts_utc"]
        close_ts = row["close_ts_utc"]
        if open_ts.tzinfo is None:
            open_ts = open_ts.replace(tzinfo=UTC)
        else:
            open_ts = open_ts.astimezone(UTC)
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        else:
            close_ts = close_ts.astimezone(UTC)
        candles.append(
            Candle(
                candle_index=idx,
                open_ts_utc=open_ts,
                close_ts_utc=close_ts,
                open_price=float(row["open_price"]),
                close_price=float(row["close_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                volume=float(row["volume"]),
            )
        )
    return candles


def start_of_utc_week(value: datetime) -> datetime:
    normalized = value.astimezone(UTC)
    week_start_date = (normalized - timedelta(days=normalized.weekday())).date()
    return datetime(
        week_start_date.year,
        week_start_date.month,
        week_start_date.day,
        tzinfo=UTC,
    )


def aggregate_daily_to_weekly(
    daily_candles: list[Candle],
    *,
    min_daily_candles_per_week: int = 3,
) -> list[Candle]:
    if not daily_candles:
        return []

    grouped: list[list[Candle]] = []
    current_group: list[Candle] = []
    current_week_start: datetime | None = None

    for candle in daily_candles:
        week_start = start_of_utc_week(candle.close_ts_utc)
        if current_week_start is None or week_start != current_week_start:
            if current_group:
                grouped.append(current_group)
            current_group = [candle]
            current_week_start = week_start
        else:
            current_group.append(candle)
    if current_group:
        grouped.append(current_group)

    weekly: list[Candle] = []
    for group in grouped:
        if len(group) < min_daily_candles_per_week:
            continue
        first = group[0]
        last = group[-1]
        weekly.append(
            Candle(
                candle_index=len(weekly),
                open_ts_utc=first.open_ts_utc,
                close_ts_utc=last.close_ts_utc,
                open_price=first.open_price,
                close_price=last.close_price,
                high_price=max(candle.high_price for candle in group),
                low_price=min(candle.low_price for candle in group),
                volume=sum(candle.volume for candle in group),
            )
        )
    return weekly


def compress_same_type_pivots(pivots: list[Pivot]) -> list[Pivot]:
    compressed: list[Pivot] = []
    for pivot in pivots:
        if not compressed:
            compressed.append(pivot)
            continue
        previous = compressed[-1]
        if pivot.pivot_kind != previous.pivot_kind:
            compressed.append(pivot)
            continue
        if pivot.pivot_kind == "HIGH":
            if pivot.price > previous.price:
                compressed[-1] = pivot
        else:
            if pivot.price < previous.price:
                compressed[-1] = pivot
    return compressed


def detect_local_pivots(candles: list[Candle], window: int) -> list[Pivot]:
    if len(candles) < (window * 2) + 1:
        return []
    pivots: list[Pivot] = []
    for idx in range(window, len(candles) - window):
        current = candles[idx]
        window_slice = candles[idx - window : idx + window + 1]
        highs = [candle.high_price for candle in window_slice]
        lows = [candle.low_price for candle in window_slice]
        is_high = current.high_price == max(highs) and highs.count(current.high_price) == 1
        is_low = current.low_price == min(lows) and lows.count(current.low_price) == 1
        if is_high:
            pivots.append(
                Pivot(
                    candle_index=current.candle_index,
                    pivot_kind="HIGH",
                    ts_utc=current.close_ts_utc,
                    price=current.high_price,
                )
            )
        if is_low:
            pivots.append(
                Pivot(
                    candle_index=current.candle_index,
                    pivot_kind="LOW",
                    ts_utc=current.close_ts_utc,
                    price=current.low_price,
                )
            )
    pivots.sort(key=lambda item: (item.candle_index, 0 if item.pivot_kind == "LOW" else 1))
    return compress_same_type_pivots(pivots)


def detect_zigzag_percent(candles: list[Candle], percent_threshold: float) -> list[Pivot]:
    if len(candles) < 2:
        return []
    threshold_ratio = percent_threshold / 100.0
    start = candles[0]
    candidate = Pivot(
        candle_index=start.candle_index,
        pivot_kind="SEED",
        ts_utc=start.close_ts_utc,
        price=start.close_price,
    )
    trend: str | None = None
    extreme = candidate
    pivots: list[Pivot] = []

    for candle in candles[1:]:
        price = candle.close_price
        if trend is None:
            if price >= candidate.price * (1.0 + threshold_ratio):
                pivots.append(
                    Pivot(
                        candle_index=candidate.candle_index,
                        pivot_kind="LOW",
                        ts_utc=candidate.ts_utc,
                        price=candidate.price,
                    )
                )
                trend = "UP"
                extreme = Pivot(candle.candle_index, "HIGH", candle.close_ts_utc, price)
            elif price <= candidate.price * (1.0 - threshold_ratio):
                pivots.append(
                    Pivot(
                        candle_index=candidate.candle_index,
                        pivot_kind="HIGH",
                        ts_utc=candidate.ts_utc,
                        price=candidate.price,
                    )
                )
                trend = "DOWN"
                extreme = Pivot(candle.candle_index, "LOW", candle.close_ts_utc, price)
            continue

        if trend == "UP":
            if price > extreme.price:
                extreme = Pivot(candle.candle_index, "HIGH", candle.close_ts_utc, price)
                continue
            if price <= extreme.price * (1.0 - threshold_ratio):
                pivots.append(extreme)
                trend = "DOWN"
                extreme = Pivot(candle.candle_index, "LOW", candle.close_ts_utc, price)
            continue

        if price < extreme.price:
            extreme = Pivot(candle.candle_index, "LOW", candle.close_ts_utc, price)
            continue
        if price >= extreme.price * (1.0 + threshold_ratio):
            pivots.append(extreme)
            trend = "UP"
            extreme = Pivot(candle.candle_index, "HIGH", candle.close_ts_utc, price)

    return compress_same_type_pivots(pivots)


def latest_sequence(pivots: list[Pivot]) -> list[Pivot]:
    if len(pivots) < 9:
        return []
    return pivots[-9:]


def more_extreme_pivot(first: Pivot, second: Pivot) -> Pivot:
    if first.pivot_kind != second.pivot_kind:
        raise ValueError("Cannot compare pivots of different types")
    if first.pivot_kind == "HIGH":
        return second if second.price > first.price else first
    return second if second.price < first.price else first


def build_major_pivots(
    raw_pivots: list[Pivot],
    *,
    major_filter: str,
    min_leg_vs_previous_ratio: float,
    min_leg_duration_candles: int,
) -> list[Pivot]:
    if not raw_pivots:
        return []
    if major_filter == "none":
        return list(raw_pivots)

    accepted: list[Pivot] = [raw_pivots[0]]
    previous_major_leg_abs: float | None = None

    for candidate in raw_pivots[1:]:
        previous = accepted[-1]
        if candidate.pivot_kind == previous.pivot_kind:
            accepted[-1] = more_extreme_pivot(previous, candidate)
            continue

        candidate_leg_abs = abs(candidate.price - previous.price)
        candidate_leg_duration = candidate.candle_index - previous.candle_index

        passes_move = (
            previous_major_leg_abs is None
            or candidate_leg_abs >= previous_major_leg_abs * min_leg_vs_previous_ratio
        )
        passes_duration = candidate_leg_duration >= min_leg_duration_candles

        if major_filter == "relative_move":
            should_accept = passes_move
        elif major_filter == "duration":
            should_accept = passes_duration
        elif major_filter == "relative_move_and_duration":
            should_accept = passes_move and passes_duration
        else:
            raise ValueError(f"Unsupported major_filter={major_filter}")

        if should_accept:
            accepted.append(candidate)
            previous_major_leg_abs = candidate_leg_abs

    return compress_same_type_pivots(accepted)


def move_abs(sequence: list[Pivot], start_idx: int, finish_idx: int) -> float | None:
    if len(sequence) <= finish_idx:
        return None
    return abs(sequence[finish_idx].price - sequence[start_idx].price)


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def x_for_index(candle_index: int, total: int) -> float:
    usable = SVG_WIDTH - SVG_PAD_LEFT - SVG_PAD_RIGHT
    if total <= 1:
        return float(SVG_PAD_LEFT)
    return SVG_PAD_LEFT + (usable * candle_index / (total - 1))


def y_for_price(price: float, min_price: float, max_price: float) -> float:
    usable = SVG_HEIGHT - SVG_PAD_TOP - SVG_PAD_BOTTOM
    if max_price <= min_price:
        return SVG_PAD_TOP + (usable / 2.0)
    return SVG_PAD_TOP + ((max_price - price) / (max_price - min_price)) * usable


def chart_svg(
    candles: list[Candle],
    raw_pivots: list[Pivot],
    major_pivots: list[Pivot],
    sequence: list[Pivot],
) -> str:
    prices = [candle.close_price for candle in candles] + [pivot.price for pivot in raw_pivots]
    min_price = min(prices)
    max_price = max(prices)

    close_points = " ".join(
        f"{x_for_index(candle.candle_index, len(candles)):.2f},{y_for_price(candle.close_price, min_price, max_price):.2f}"
        for candle in candles
    )
    pivot_line_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in raw_pivots
    )
    major_line_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in major_pivots
    )
    sequence_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in sequence
    )

    raw_markers: list[str] = []
    for pivot in raw_pivots:
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        color = "#c4513d" if pivot.pivot_kind == "HIGH" else "#23845a"
        raw_markers.append(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='2.8' fill='{color}' fill-opacity='0.55' stroke='none'></circle>"
        )
    major_markers: list[str] = []
    for pivot in major_pivots:
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        color = "#c4513d" if pivot.pivot_kind == "HIGH" else "#23845a"
        major_markers.append(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='5.2' fill='{color}' stroke='#ffffff' stroke-width='1.3'></circle>"
        )

    p_labels: list[str] = []
    wave_labels: list[str] = []
    for idx, pivot in enumerate(sequence):
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        y_offset = -14 if pivot.pivot_kind == "HIGH" else 20
        p_labels.append(
            f"<text x='{x:.2f}' y='{y + y_offset:.2f}' class='p-label'>P{idx}</text>"
        )
        if idx < len(sequence) - 1:
            next_pivot = sequence[idx + 1]
            next_x = x_for_index(next_pivot.candle_index, len(candles))
            next_y = y_for_price(next_pivot.price, min_price, max_price)
            mx = (x + next_x) / 2.0
            my = (y + next_y) / 2.0 - 8.0
            wave_labels.append(
                f"<text x='{mx:.2f}' y='{my:.2f}' class='wave-label'>{WAVE_NAMES[idx]}</text>"
            )

    axis_labels = [
        (max_price, y_for_price(max_price, min_price, max_price)),
        ((max_price + min_price) / 2.0, y_for_price((max_price + min_price) / 2.0, min_price, max_price)),
        (min_price, y_for_price(min_price, min_price, max_price)),
    ]

    return f"""
<svg viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" class="chart" role="img" aria-label="Wave sequence preview">
  <rect x="0" y="0" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="#fffdfa"></rect>
  <line x1="{SVG_PAD_LEFT}" y1="{SVG_HEIGHT - SVG_PAD_BOTTOM}" x2="{SVG_WIDTH - SVG_PAD_RIGHT}" y2="{SVG_HEIGHT - SVG_PAD_BOTTOM}" class="axis"></line>
  <line x1="{SVG_PAD_LEFT}" y1="{SVG_PAD_TOP}" x2="{SVG_PAD_LEFT}" y2="{SVG_HEIGHT - SVG_PAD_BOTTOM}" class="axis"></line>
  <polyline points="{close_points}" class="close-line"></polyline>
  <polyline points="{pivot_line_points}" class="raw-pivot-line"></polyline>
  <polyline points="{major_line_points}" class="major-pivot-line"></polyline>
  <polyline points="{sequence_points}" class="sequence-line"></polyline>
  {''.join(raw_markers)}
  {''.join(major_markers)}
  {''.join(p_labels)}
  {''.join(wave_labels)}
  {''.join(f"<text x='8' y='{y:.2f}' class='axis-label'>{esc(fmt_price(price))}</text>" for price, y in axis_labels)}
</svg>
"""


def detector_params(args: argparse.Namespace) -> str:
    if args.detector == "local_pivot_window":
        return f"swing_window={args.swing_window} source=high_low"
    return f"zigzag_percent={args.zigzag_percent:g} source=close"


def sequence_metrics(sequence: list[Pivot]) -> dict[str, float | None]:
    wave1 = move_abs(sequence, 0, 1)
    wave2 = move_abs(sequence, 1, 2)
    wave3 = move_abs(sequence, 2, 3)
    wave4 = move_abs(sequence, 3, 4)
    wave5 = move_abs(sequence, 4, 5)
    wave_a = move_abs(sequence, 5, 6)
    wave_b = move_abs(sequence, 6, 7)
    wave_c = move_abs(sequence, 7, 8)
    return {
        "wave1_move_abs": wave1,
        "wave2_move_abs": wave2,
        "wave3_move_abs": wave3,
        "wave4_move_abs": wave4,
        "wave5_move_abs": wave5,
        "waveA_move_abs": wave_a,
        "waveB_move_abs": wave_b,
        "waveC_move_abs": wave_c,
        "wave2_vs_wave1": ratio(wave2, wave1),
        "wave3_vs_wave1": ratio(wave3, wave1),
        "wave4_vs_wave3": ratio(wave4, wave3),
        "wave5_vs_wave1": ratio(wave5, wave1),
        "wave5_vs_wave3": ratio(wave5, wave3),
        "waveB_vs_waveA": ratio(wave_b, wave_a),
        "waveC_vs_waveA": ratio(wave_c, wave_a),
    }


def detail_table(
    *,
    symbol: str,
    interval: str,
    detector: str,
    detector_params_value: str,
    lookback_candles: int,
    raw_pivots: list[Pivot],
    major_pivots: list[Pivot],
    major_filter: str,
    min_leg_vs_previous_ratio: float,
    min_leg_duration_candles: int,
    sequence: list[Pivot],
) -> str:
    rows: list[tuple[str, str]] = [
        ("symbol", symbol),
        ("interval", interval),
        ("detector", detector),
        ("detector_params", detector_params_value),
        ("lookback_candles", str(lookback_candles)),
        ("raw_pivot_count", str(len(raw_pivots))),
        ("major_pivot_count", str(len(major_pivots))),
        ("removed_minor_pivot_count", str(max(0, len(raw_pivots) - len(major_pivots)))),
        ("major_filter", major_filter),
        ("min_leg_vs_previous_ratio", fmt_number(min_leg_vs_previous_ratio)),
        ("min_leg_duration_candles", str(min_leg_duration_candles)),
        ("pivot_count", str(len(major_pivots))),
        ("has_complete_p0_p8_sequence", "1" if len(sequence) == 9 else "0"),
    ]
    for idx in range(9):
        pivot = sequence[idx] if len(sequence) > idx else None
        rows.append((f"P{idx} timestamp", fmt_ts(pivot.ts_utc) if pivot else ""))
        rows.append((f"P{idx} price", fmt_price(pivot.price) if pivot else ""))
        rows.append((f"P{idx} type", pivot.pivot_kind if pivot else ""))

    metrics = sequence_metrics(sequence) if len(sequence) == 9 else {}
    for key in (
        "wave1_move_abs",
        "wave2_move_abs",
        "wave3_move_abs",
        "wave4_move_abs",
        "wave5_move_abs",
        "waveA_move_abs",
        "waveB_move_abs",
        "waveC_move_abs",
        "wave2_vs_wave1",
        "wave3_vs_wave1",
        "wave4_vs_wave3",
        "wave5_vs_wave1",
        "wave5_vs_wave3",
        "waveB_vs_waveA",
        "waveC_vs_waveA",
    ):
        rows.append((key, fmt_number(metrics.get(key))))

    return "".join(f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>" for key, value in rows)


def render_html(
    *,
    venue: str,
    symbol: str,
    interval: str,
    detector: str,
    detector_params_value: str,
    lookback_candles: int,
    source_interval: str,
    aggregated_interval: str,
    candles: list[Candle],
    raw_pivots: list[Pivot],
    major_pivots: list[Pivot],
    major_filter: str,
    min_leg_vs_previous_ratio: float,
    min_leg_duration_candles: int,
    sequence: list[Pivot],
) -> str:
    generated_at_utc = fmt_ts(datetime.now(UTC))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fib Wave Sequence {esc(symbol)} {esc(interval)}</title>
  <style>
    :root {{
      --bg: #f5efe7;
      --paper: #fffdf9;
      --ink: #1f1d1a;
      --muted: #6f675d;
      --line: #d8cec2;
      --close: #2b3442;
      --raw-pivot: #b9a48a;
      --major-pivot: #8a6a44;
      --sequence: #d14d41;
      --axis: #b7aa9a;
      --table-head: #f0e6d9;
      --wave: #915c2e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 28px;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(145,92,46,0.10), transparent 24%),
        linear-gradient(180deg, #f8f3eb 0%, var(--bg) 100%);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
    }}
    .hero, .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: 0 14px 40px rgba(31, 29, 26, 0.06);
    }}
    .hero {{
      padding: 20px 22px;
      margin-bottom: 18px;
    }}
    .panel {{
      padding: 18px;
    }}
    h1, h2 {{
      margin: 0;
      font-family: "IBM Plex Serif", "Georgia", serif;
      font-weight: 600;
    }}
    .hero p {{
      margin: 10px 0 0;
      color: var(--muted);
    }}
    .chart {{
      width: 100%;
      height: auto;
      display: block;
      background: #fffdfa;
      border: 1px solid var(--line);
    }}
    .axis {{
      stroke: var(--axis);
      stroke-width: 1;
    }}
    .axis-label {{
      fill: var(--muted);
      font-size: 12px;
      font-family: "IBM Plex Mono", monospace;
    }}
    .close-line {{
      fill: none;
      stroke: var(--close);
      stroke-width: 1.8;
    }}
    .raw-pivot-line {{
      fill: none;
      stroke: var(--raw-pivot);
      stroke-width: 1.5;
      stroke-dasharray: 5 4;
    }}
    .major-pivot-line {{
      fill: none;
      stroke: var(--major-pivot);
      stroke-width: 1.8;
    }}
    .sequence-line {{
      fill: none;
      stroke: var(--sequence);
      stroke-width: 3.0;
    }}
    .p-label {{
      fill: var(--sequence);
      font-size: 13px;
      font-weight: 700;
      text-anchor: middle;
      font-family: "IBM Plex Mono", monospace;
    }}
    .wave-label {{
      fill: var(--wave);
      font-size: 12px;
      font-weight: 700;
      text-anchor: middle;
      font-family: "IBM Plex Mono", monospace;
    }}
    .detail-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 14px;
    }}
    .detail-table th,
    .detail-table td {{
      border: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    .detail-table th {{
      width: 280px;
      background: var(--table-head);
      font-family: "IBM Plex Mono", monospace;
      font-weight: 600;
    }}
    .foot {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Fib Wave Sequence Visual Preview V1</h1>
      <p>venue={esc(venue)} symbol={esc(symbol)} interval={esc(interval)} source_interval={esc(source_interval)} aggregated_interval={esc(aggregated_interval)} detector={esc(detector)} rows={len(candles)} raw_pivot_count={len(raw_pivots)} major_pivot_count={len(major_pivots)} generated_at_utc={esc(generated_at_utc)}</p>
      <p>Candidate labels only. This does not claim a correct Elliott count. No targets. No fib-level tests. No DB writes.</p>
    </section>
    <section class="panel">
      <h2>Latest Candidate P0-P8 Sequence</h2>
      <p class="foot">Source table: {esc(SOURCE_TABLE)}. Source interval: {esc(source_interval)}. Aggregated interval: {esc(aggregated_interval)}. Detector params: {esc(detector_params_value)}. Major filter: {esc(major_filter)}.</p>
      {chart_svg(candles, raw_pivots, major_pivots, sequence)}
      <table class="detail-table">
        <tbody>
          {detail_table(symbol=symbol, interval=interval, detector=detector, detector_params_value=detector_params_value, lookback_candles=lookback_candles, raw_pivots=raw_pivots, major_pivots=major_pivots, major_filter=major_filter, min_leg_vs_previous_ratio=min_leg_vs_previous_ratio, min_leg_duration_candles=min_leg_duration_candles, sequence=sequence)}
        </tbody>
      </table>
      <div class="foot">Raw pivots are shown with smaller markers. Major pivots are shown with larger markers. P0-P8 and W1/W2/W3/W4/W5/A/B/C remain candidate visual labels only for inspection.</div>
    </section>
  </div>
</body>
</html>
"""


def build_summary(
    *,
    symbol: str,
    interval: str,
    detector: str,
    rows: int,
    source_interval: str,
    aggregated_interval: str,
    aggregated_rows: int,
    raw_pivot_count: int,
    major_pivot_count: int,
    has_complete_sequence: bool,
    output_html: Path,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "symbol": symbol,
        "interval": interval,
        "source_interval": source_interval,
        "aggregated_interval": aggregated_interval,
        "detector": detector,
        "rows": rows,
        "aggregated_rows": aggregated_rows,
        "pivot_count": major_pivot_count,
        "raw_pivot_count": raw_pivot_count,
        "major_pivot_count": major_pivot_count,
        "removed_minor_pivot_count": max(0, raw_pivot_count - major_pivot_count),
        "has_complete_p0_p8_sequence": 1 if has_complete_sequence else 0,
        "output_html": str(output_html),
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "account_awareness": 0,
    }


def print_summary(summary: dict[str, Any]) -> None:
    for key in (
        "report",
        "version",
        "symbol",
        "interval",
        "source_interval",
        "aggregated_interval",
        "detector",
        "rows",
        "aggregated_rows",
        "pivot_count",
        "raw_pivot_count",
        "major_pivot_count",
        "removed_minor_pivot_count",
        "has_complete_p0_p8_sequence",
        "output_html",
        "db_writes",
        "broker_private_calls",
        "broker_writes",
        "order_submission",
        "decision_gate_changes",
        "execution_planner_changes",
        "executor",
        "account_awareness",
    ):
        print(f"{key}={summary[key]}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_candles <= 0:
        raise ValueError("--lookback-candles must be > 0")
    if args.detector == "local_pivot_window" and args.swing_window <= 0:
        raise ValueError("--swing-window must be > 0")
    if args.detector == "zigzag_percent" and args.zigzag_percent <= 0:
        raise ValueError("--zigzag-percent must be > 0")
    if args.min_leg_vs_previous_ratio < 0:
        raise ValueError("--min-leg-vs-previous-ratio must be >= 0")
    if args.min_leg_duration_candles < 0:
        raise ValueError("--min-leg-duration-candles must be >= 0")

    source_interval = args.interval
    aggregated_interval = args.interval
    fetch_interval = args.interval
    fetch_lookback_candles = args.lookback_candles
    if args.interval == "1w":
        source_interval = "1d"
        aggregated_interval = "1w"
        fetch_interval = "1d"
        fetch_lookback_candles = max(args.lookback_candles * 8, args.lookback_candles)

    conn = get_connection()
    try:
        asset = fetch_asset(conn, symbol=args.symbol)
        candles = fetch_recent_candles(
            conn,
            asset=asset,
            venue=args.venue,
            interval_code=fetch_interval,
            lookback_candles=fetch_lookback_candles,
        )
    finally:
        conn.close()

    if not candles:
        raise ValueError(
            f"No candles found for venue={args.venue} symbol={asset.symbol} interval={fetch_interval}"
        )

    if args.interval == "1w":
        candles = aggregate_daily_to_weekly(candles)
        if args.lookback_candles > 0 and len(candles) > args.lookback_candles:
            candles = candles[-args.lookback_candles :]
            candles = [
                Candle(
                    candle_index=index,
                    open_ts_utc=candle.open_ts_utc,
                    close_ts_utc=candle.close_ts_utc,
                    open_price=candle.open_price,
                    close_price=candle.close_price,
                    high_price=candle.high_price,
                    low_price=candle.low_price,
                    volume=candle.volume,
                )
                for index, candle in enumerate(candles)
            ]
        if not candles:
            raise ValueError(
                f"No aggregated weekly candles available for venue={args.venue} symbol={asset.symbol}"
            )

    if args.detector == "local_pivot_window":
        raw_pivots = detect_local_pivots(candles, args.swing_window)
    else:
        raw_pivots = detect_zigzag_percent(candles, args.zigzag_percent)

    major_pivots = build_major_pivots(
        raw_pivots,
        major_filter=args.major_filter,
        min_leg_vs_previous_ratio=args.min_leg_vs_previous_ratio,
        min_leg_duration_candles=args.min_leg_duration_candles,
    )
    sequence = latest_sequence(major_pivots)
    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_html(
            venue=args.venue,
            symbol=asset.symbol,
            interval=args.interval,
            detector=args.detector,
            detector_params_value=detector_params(args),
            lookback_candles=args.lookback_candles,
            source_interval=source_interval,
            aggregated_interval=aggregated_interval,
            candles=candles,
            raw_pivots=raw_pivots,
            major_pivots=major_pivots,
            major_filter=args.major_filter,
            min_leg_vs_previous_ratio=args.min_leg_vs_previous_ratio,
            min_leg_duration_candles=args.min_leg_duration_candles,
            sequence=sequence,
        ),
        encoding="utf-8",
    )

    summary = build_summary(
        symbol=asset.symbol,
        interval=args.interval,
        source_interval=source_interval,
        aggregated_interval=aggregated_interval,
        detector=args.detector,
        rows=len(candles),
        aggregated_rows=len(candles) if args.interval == "1w" else len(candles),
        raw_pivot_count=len(raw_pivots),
        major_pivot_count=len(major_pivots),
        has_complete_sequence=len(sequence) == 9,
        output_html=output_html,
    )
    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=False))
    else:
        print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
