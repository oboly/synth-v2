from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "fib_detector_visual_compare_v1"
REPORT_VERSION = "0.1"
SOURCE_TABLE = "obs_market_candle"

DEFAULT_VENUE = "bitvavo"
DEFAULT_SYMBOL = "BTC"
DEFAULT_INTERVAL = "1d"
DEFAULT_LOOKBACK_CANDLES = 900
DEFAULT_OUTPUT_HTML = "/tmp/fib_detector_compare_BTC_1d.html"

SVG_WIDTH = 1100
SVG_HEIGHT = 320
SVG_PAD_LEFT = 64
SVG_PAD_RIGHT = 28
SVG_PAD_TOP = 20
SVG_PAD_BOTTOM = 40


@dataclass(frozen=True)
class AssetRef:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class Candle:
    candle_index: int
    close_ts_utc: datetime
    close_price: float
    high_price: float
    low_price: float


@dataclass(frozen=True)
class Pivot:
    candle_index: int
    pivot_kind: str
    ts_utc: datetime
    price: float


@dataclass(frozen=True)
class DetectorSection:
    detector_name: str
    detector_params: str
    pivots: list[Pivot]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a stacked visual comparison of long-swing fib pivot detectors "
            "from public candles only (research-only, no targets, no execution)."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
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
        SELECT close_ts_utc, close_price, high_price, low_price
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
        close_ts = row["close_ts_utc"]
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        else:
            close_ts = close_ts.astimezone(UTC)
        candles.append(
            Candle(
                candle_index=idx,
                close_ts_utc=close_ts,
                close_price=float(row["close_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
            )
        )
    return candles


def compress_same_type_pivots(pivots: list[Pivot]) -> list[Pivot]:
    compressed: list[Pivot] = []
    for pivot in pivots:
        if not compressed:
            compressed.append(pivot)
            continue
        prev = compressed[-1]
        if pivot.pivot_kind != prev.pivot_kind:
            compressed.append(pivot)
            continue
        if pivot.pivot_kind == "HIGH":
            if pivot.price > prev.price:
                compressed[-1] = pivot
        else:
            if pivot.price < prev.price:
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
    if len(pivots) < 4:
        return []
    return pivots[-4:]


def basis_direction(sequence: list[Pivot]) -> str:
    if len(sequence) < 2:
        return ""
    return "UP" if sequence[1].price > sequence[0].price else "DOWN"


def correction_multiplier(sequence: list[Pivot]) -> float | None:
    if len(sequence) < 4:
        return None
    basis_move_abs = abs(sequence[1].price - sequence[0].price)
    if basis_move_abs <= 0:
        return None
    return abs(sequence[2].price - sequence[1].price) / basis_move_abs


def continuation_multiplier(sequence: list[Pivot]) -> float | None:
    if len(sequence) < 4:
        return None
    basis_move_abs = abs(sequence[1].price - sequence[0].price)
    if basis_move_abs <= 0:
        return None
    return abs(sequence[3].price - sequence[2].price) / basis_move_abs


def detector_sections(candles: list[Candle]) -> list[DetectorSection]:
    return [
        DetectorSection(
            detector_name="LOCAL_PIVOT_WINDOW_10",
            detector_params="window=10 source=high_low",
            pivots=detect_local_pivots(candles, window=10),
        ),
        DetectorSection(
            detector_name="LOCAL_PIVOT_WINDOW_20",
            detector_params="window=20 source=high_low",
            pivots=detect_local_pivots(candles, window=20),
        ),
        DetectorSection(
            detector_name="ZIGZAG_PERCENT_10",
            detector_params="reversal_pct=10 source=close",
            pivots=detect_zigzag_percent(candles, percent_threshold=10.0),
        ),
        DetectorSection(
            detector_name="ZIGZAG_PERCENT_20",
            detector_params="reversal_pct=20 source=close",
            pivots=detect_zigzag_percent(candles, percent_threshold=20.0),
        ),
        DetectorSection(
            detector_name="ZIGZAG_PERCENT_30",
            detector_params="reversal_pct=30 source=close",
            pivots=detect_zigzag_percent(candles, percent_threshold=30.0),
        ),
    ]


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


def chart_svg(candles: list[Candle], section: DetectorSection) -> str:
    all_prices = [candle.close_price for candle in candles]
    all_prices.extend(pivot.price for pivot in section.pivots)
    min_price = min(all_prices)
    max_price = max(all_prices)

    close_points = " ".join(
        f"{x_for_index(candle.candle_index, len(candles)):.2f},{y_for_price(candle.close_price, min_price, max_price):.2f}"
        for candle in candles
    )
    pivot_line_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in section.pivots
    )
    sequence = latest_sequence(section.pivots)
    sequence_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in sequence
    )

    y_top = y_for_price(max_price, min_price, max_price)
    y_bottom = y_for_price(min_price, min_price, max_price)
    price_labels = [
        (max_price, y_top),
        ((max_price + min_price) / 2.0, (y_top + y_bottom) / 2.0),
        (min_price, y_bottom),
    ]

    markers: list[str] = []
    for pivot in section.pivots:
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        color = "#d14d41" if pivot.pivot_kind == "HIGH" else "#1f8f59"
        markers.append(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4.2' fill='{color}' stroke='#ffffff' stroke-width='1.2'></circle>"
        )

    sequence_labels: list[str] = []
    for idx, pivot in enumerate(sequence):
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        y_offset = -12 if pivot.pivot_kind == "HIGH" else 18
        sequence_labels.append(
            f"<text x='{x:.2f}' y='{y + y_offset:.2f}' class='seq-label'>P{idx}</text>"
        )

    price_axis = "".join(
        f"<text x='8' y='{y:.2f}' class='axis-label'>{esc(fmt_price(price))}</text>"
        for price, y in price_labels
    )

    return f"""
<svg viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" class="chart" role="img" aria-label="{esc(section.detector_name)}">
  <rect x="0" y="0" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="#ffffff"></rect>
  <line x1="{SVG_PAD_LEFT}" y1="{SVG_HEIGHT - SVG_PAD_BOTTOM}" x2="{SVG_WIDTH - SVG_PAD_RIGHT}" y2="{SVG_HEIGHT - SVG_PAD_BOTTOM}" class="axis"></line>
  <line x1="{SVG_PAD_LEFT}" y1="{SVG_PAD_TOP}" x2="{SVG_PAD_LEFT}" y2="{SVG_HEIGHT - SVG_PAD_BOTTOM}" class="axis"></line>
  <polyline points="{close_points}" class="close-line"></polyline>
  <polyline points="{pivot_line_points}" class="pivot-line"></polyline>
  <polyline points="{sequence_points}" class="sequence-line"></polyline>
  {''.join(markers)}
  {''.join(sequence_labels)}
  {price_axis}
</svg>
"""


def pivot_table_rows(section: DetectorSection) -> str:
    sequence = latest_sequence(section.pivots)
    mapping = {
        "P0": sequence[0] if len(sequence) > 0 else None,
        "P1": sequence[1] if len(sequence) > 1 else None,
        "P2": sequence[2] if len(sequence) > 2 else None,
        "P3": sequence[3] if len(sequence) > 3 else None,
    }

    rows = [
        ("detector_name", section.detector_name),
        ("detector_params", section.detector_params),
        ("pivot_count", str(len(section.pivots))),
        ("has_complete_sequence", "1" if len(sequence) == 4 else "0"),
    ]
    for label in ("P0", "P1", "P2", "P3"):
        pivot = mapping[label]
        rows.append((f"{label} timestamp", fmt_ts(pivot.ts_utc) if pivot else ""))
        rows.append((f"{label} price", fmt_price(pivot.price) if pivot else ""))
        rows.append((f"{label} type", pivot.pivot_kind if pivot else ""))
    rows.extend(
        [
            ("basis_direction", basis_direction(sequence)),
            ("correction_multiplier", fmt_number(correction_multiplier(sequence))),
            ("continuation_multiplier", fmt_number(continuation_multiplier(sequence))),
        ]
    )

    return "".join(
        f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>"
        for key, value in rows
    )


def render_html(
    *,
    venue: str,
    symbol: str,
    interval: str,
    candles: list[Candle],
    sections: list[DetectorSection],
) -> str:
    section_blocks = "".join(
        f"""
<section class="detector-card">
  <h2>{esc(section.detector_name)}</h2>
  <div class="detector-meta">{esc(section.detector_params)}</div>
  {chart_svg(candles, section)}
  <table class="detail-table">
    <tbody>
      {pivot_table_rows(section)}
    </tbody>
  </table>
</section>
"""
        for section in sections
    )

    generated_at_utc = fmt_ts(datetime.now(UTC))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fib Detector Compare {esc(symbol)} {esc(interval)}</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --paper: #fffdf9;
      --ink: #1f1d1a;
      --muted: #6f675d;
      --line: #d8cec2;
      --close: #293241;
      --pivot: #8a6a44;
      --sequence: #d14d41;
      --axis: #b7aa9a;
      --table-head: #f0e6d9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 28px;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(209,77,65,0.09), transparent 24%),
        linear-gradient(180deg, #f8f3eb 0%, var(--bg) 100%);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
    }}
    .hero {{
      background: var(--paper);
      border: 1px solid var(--line);
      padding: 20px 22px;
      margin-bottom: 18px;
      box-shadow: 0 14px 40px rgba(31, 29, 26, 0.06);
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
    .detector-card {{
      background: var(--paper);
      border: 1px solid var(--line);
      padding: 18px 18px 20px;
      margin-bottom: 18px;
      box-shadow: 0 12px 36px rgba(31, 29, 26, 0.05);
    }}
    .detector-meta {{
      margin: 6px 0 14px;
      color: var(--muted);
      font-size: 14px;
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
    .pivot-line {{
      fill: none;
      stroke: var(--pivot);
      stroke-width: 1.5;
      stroke-dasharray: 5 4;
    }}
    .sequence-line {{
      fill: none;
      stroke: var(--sequence);
      stroke-width: 2.8;
    }}
    .seq-label {{
      fill: var(--sequence);
      font-size: 13px;
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
      <h1>Fib Detector Visual Compare V1</h1>
      <p>venue={esc(venue)} symbol={esc(symbol)} interval={esc(interval)} rows={len(candles)} source_table={SOURCE_TABLE} generated_at_utc={esc(generated_at_utc)}</p>
      <p>Purpose: stack multiple long-swing pivot detectors vertically for visual review before choosing a detector for multiplier research.</p>
    </section>
    {section_blocks}
    <div class="foot">Visual review only. No DB writes. No targets. No fib-level tests. No strategy advice.</div>
  </div>
</body>
</html>
"""


def build_summary(
    *,
    symbol: str,
    interval: str,
    rows: int,
    sections: int,
    output_html: Path,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "symbol": symbol,
        "interval": interval,
        "rows": rows,
        "sections": sections,
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
        "rows",
        "sections",
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

    conn = get_connection()
    try:
        asset = fetch_asset(conn, symbol=args.symbol)
        candles = fetch_recent_candles(
            conn,
            asset=asset,
            venue=args.venue,
            interval_code=args.interval,
            lookback_candles=args.lookback_candles,
        )
    finally:
        conn.close()

    if not candles:
        raise ValueError(
            f"No candles found for venue={args.venue} symbol={asset.symbol} interval={args.interval}"
        )

    sections = detector_sections(candles)
    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_html(
            venue=args.venue,
            symbol=asset.symbol,
            interval=args.interval,
            candles=candles,
            sections=sections,
        ),
        encoding="utf-8",
    )

    summary = build_summary(
        symbol=asset.symbol,
        interval=args.interval,
        rows=len(candles),
        sections=len(sections),
        output_html=output_html,
    )
    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=False))
    else:
        print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
