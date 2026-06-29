from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.db import get_connection


RUNNER_NAME = "run_breathline_marker_evidence_viewer_v1"
VERSION = "1.0"
INDEX_HTML = "index.html"
EVIDENCE_INDEX_CSV = "evidence_index.csv"
MANIFEST_TXT = "manifest.txt"

SAFETY_MARKERS = {
    "broker_private_calls": "0",
    "broker_writes": "0",
    "order_submission": "0",
    "live_orders": "0",
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "db_writes": "0",
}

TITLE_LINE = "MARKER EVIDENCE — NOT PHASE DURATION"
WARNING_LINE = "VISUAL REVIEW REQUIRED — NO STRATEGY OR EXECUTION USE"
SOURCE_TABLE = "obs_market_candle"
DEFAULT_VENUE = "bitvavo"

SVG_WIDTH = 1360
SVG_HEIGHT = 620
SVG_PAD_LEFT = 84.0
SVG_PAD_RIGHT = 28.0
SVG_PAD_TOP = 70.0
SVG_PAD_BOTTOM = 72.0

INTERVAL_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(days=7),
}

CSV_FIELDS = [
    "symbol",
    "anchor_ts_utc",
    "checkpoint_ratio",
    "page_file",
    "marker_count",
    "matched_marker_count",
    "candle_source",
    "candle_count",
    "warning",
]


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float


@dataclass(frozen=True)
class ParsedMarker:
    code: str
    kind: str
    ratio: float | None
    expected_ts_utc: str
    expected_ts: datetime
    observed_ts_utc: str
    observed_ts: datetime | None
    observed_price: float | None
    matched: bool
    timing_error_hours: float | None


@dataclass(frozen=True)
class EvidenceRecord:
    symbol: str
    anchor_ts_utc: str
    anchor_ts: datetime
    checkpoint_ratio: str
    selected_partial_offset_days: float
    venue: str
    interval_code: str
    cycle_days: float | None
    tolerance_hours: float
    phase_offset_days: float | None
    flags: dict[str, bool | None]
    markers: tuple[ParsedMarker, ...]
    inline_candles: tuple[Candle, ...]


@dataclass(frozen=True)
class CandleLoadResult:
    candles: tuple[Candle, ...]
    source: str
    warning: str


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a research-only static HTML/SVG evidence viewer for existing Breathline "
            "marker observations. Static output only; no execution or strategy use."
        )
    )
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--checkpoint-ratio", default="")
    return parser.parse_args(argv)


def parse_iso_utc(raw: str, *, context: str) -> datetime:
    try:
        value = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {context}: {raw}") from exc
    if value.tzinfo is None:
        raise ValueError(
            f"Invalid {context}: {raw} (explicit timezone required; use Z or numeric UTC offset)"
        )
    return value.astimezone(UTC)


def iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def utc_compact(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def to_float(value: Any, *, context: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {context}: {value}") from exc


def maybe_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def maybe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in ("", None):
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def bool_text(value: bool | None) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    return "UNAVAILABLE"


def require_marker_matched_bool(value: Any, *, symbol: str, anchor_ts_utc: str, code: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(
        "Invalid marker matched for "
        f"symbol={symbol} anchor={anchor_ts_utc} code={code}: "
        "must be literal boolean true or false"
    )


def fmt_float(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def fmt_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.8f}"


def fmt_hours(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:+.3f}h"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"
    value = result.stdout.strip()
    return value or "unavailable"


def ensure_empty_output_dir(path: Path) -> None:
    if path.exists():
        if any(path.iterdir()):
            raise ValueError(f"Output directory must be empty: {path}")
        return
    path.mkdir(parents=True, exist_ok=True)


def parse_symbols(raw: list[str]) -> list[str]:
    return [item for item in dict.fromkeys(str(part).strip().upper() for part in raw if str(part).strip())]


def ratio_sort_value(raw: str) -> tuple[float, str]:
    value = maybe_float(raw)
    return (value if value is not None else math.inf, raw)


def interval_delta(interval_code: str) -> timedelta:
    return INTERVAL_DELTAS.get(str(interval_code).strip(), timedelta(days=1))


def page_file_name(record: EvidenceRecord) -> str:
    ratio_fragment = re.sub(r"[^0-9A-Za-z]+", "p", record.checkpoint_ratio).strip("p") or "ratio"
    return f"evidence_{record.symbol.lower()}_{utc_compact(record.anchor_ts)}_cp_{ratio_fragment}.html"


def record_key(record: EvidenceRecord) -> tuple[str, str, str]:
    return (record.symbol, record.anchor_ts_utc, record.checkpoint_ratio)


def tolerance_window(marker: ParsedMarker, tolerance_hours: float) -> tuple[datetime, datetime]:
    span = timedelta(hours=max(tolerance_hours, 0.0))
    return (marker.expected_ts - span, marker.expected_ts + span)


def marker_timing_delta_hours(marker: ParsedMarker) -> float | None:
    if marker.observed_ts is None:
        return None
    return round((marker.observed_ts - marker.expected_ts).total_seconds() / 3600.0, 3)


def chart_window(record: EvidenceRecord) -> tuple[datetime, datetime]:
    times = [record.anchor_ts]
    for marker in record.markers:
        times.append(marker.expected_ts)
        if marker.observed_ts is not None:
            times.append(marker.observed_ts)
    pad = max(timedelta(hours=record.tolerance_hours), interval_delta(record.interval_code), timedelta(hours=12))
    return (min(times) - pad, max(times) + pad)


def parse_candle_rows(raw_candles: Any, *, context: str) -> tuple[Candle, ...]:
    if raw_candles in (None, ""):
        return ()
    if not isinstance(raw_candles, list):
        raise ValueError(f"Invalid {context}: expected candle list")
    candles: list[Candle] = []
    previous_ts: datetime | None = None
    for index, raw_row in enumerate(raw_candles):
        if not isinstance(raw_row, dict):
            raise ValueError(f"Invalid {context} index={index}: expected object")
        ts_text = (
            raw_row.get("ts_utc")
            or raw_row.get("close_ts_utc")
            or raw_row.get("ts")
            or raw_row.get("close_ts")
        )
        if not ts_text:
            raise ValueError(f"Invalid {context} index={index}: missing candle timestamp")
        ts = parse_iso_utc(str(ts_text), context=f"{context} candle timestamp")
        open_price = to_float(
            raw_row.get("open_price", raw_row.get("open")),
            context=f"{context} candle open_price index={index}",
        )
        high_price = to_float(
            raw_row.get("high_price", raw_row.get("high")),
            context=f"{context} candle high_price index={index}",
        )
        low_price = to_float(
            raw_row.get("low_price", raw_row.get("low")),
            context=f"{context} candle low_price index={index}",
        )
        close_price = to_float(
            raw_row.get("close_price", raw_row.get("close")),
            context=f"{context} candle close_price index={index}",
        )
        if high_price < max(open_price, close_price) or low_price > min(open_price, close_price) or high_price < low_price:
            raise ValueError(f"Invalid {context} index={index}: inconsistent OHLC geometry")
        if previous_ts is not None and ts <= previous_ts:
            raise ValueError(f"Invalid {context}: candle timestamps must be strictly ascending")
        candles.append(
            Candle(
                ts=ts,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
            )
        )
        previous_ts = ts
    return tuple(candles)


def extract_inline_candles(raw_row: dict[str, Any], selected_full: dict[str, Any], *, context: str) -> tuple[Candle, ...]:
    candidates = [
        raw_row.get("evidence_candles"),
        raw_row.get("candles"),
        selected_full.get("evidence_candles"),
        selected_full.get("candles"),
    ]
    for raw_candles in candidates:
        if raw_candles not in (None, ""):
            return parse_candle_rows(raw_candles, context=context)
    return ()


def load_records(
    path: Path,
    *,
    symbols_filter: list[str],
    checkpoint_filter: str,
) -> tuple[int, list[EvidenceRecord]]:
    input_rows = 0
    identities: set[tuple[str, str, str]] = set()
    selected_symbols = set(symbols_filter)
    records: list[EvidenceRecord] = []

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            input_rows += 1
            raw_row = json.loads(line)
            if raw_row.get("status") != "OK":
                continue

            symbol = str(raw_row.get("symbol") or "").strip().upper()
            checkpoint_ratio = str(raw_row.get("checkpoint_ratio") or "").strip()
            anchor_ts_utc = str(raw_row.get("anchor_ts_utc") or "").strip()

            if selected_symbols and symbol not in selected_symbols:
                continue
            if checkpoint_filter and checkpoint_ratio != checkpoint_filter:
                continue

            if not symbol:
                raise ValueError("Accepted row missing symbol")
            if not checkpoint_ratio:
                raise ValueError(f"Accepted row missing checkpoint_ratio for symbol={symbol}")
            if not anchor_ts_utc:
                raise ValueError(f"Accepted row missing anchor_ts_utc for symbol={symbol}")

            identity = (symbol, anchor_ts_utc, checkpoint_ratio)
            if identity in identities:
                raise ValueError(
                    "Duplicate accepted record identity "
                    f"for symbol={symbol} anchor={anchor_ts_utc} checkpoint={checkpoint_ratio}"
                )
            identities.add(identity)

            anchor_ts = parse_iso_utc(anchor_ts_utc, context=f"anchor_ts_utc for symbol={symbol}")
            selected_full = raw_row.get("selected_full_same_offset")
            if not isinstance(selected_full, dict):
                raise ValueError(
                    f"Accepted row missing selected_full_same_offset for symbol={symbol} anchor={anchor_ts_utc}"
                )

            markers_raw = selected_full.get("markers")
            if not isinstance(markers_raw, list) or not markers_raw:
                raise ValueError(
                    f"Accepted row missing marker list for symbol={symbol} anchor={anchor_ts_utc}"
                )

            selected_partial_offset_days = maybe_float(raw_row.get("selected_partial_offset_days"))
            if selected_partial_offset_days is None:
                selected_partial_offset_days = to_float(
                    selected_full.get("phase_offset_days"),
                    context=(
                        "selected_partial_offset_days/phase_offset_days "
                        f"for symbol={symbol} anchor={anchor_ts_utc}"
                    ),
                )

            seen_codes: set[str] = set()
            previous_expected: datetime | None = None
            markers: list[ParsedMarker] = []
            for index, raw_marker in enumerate(markers_raw):
                if not isinstance(raw_marker, dict):
                    raise ValueError(
                        f"Invalid marker payload for symbol={symbol} anchor={anchor_ts_utc} index={index}"
                    )
                code = str(raw_marker.get("code") or "").strip()
                if not code:
                    raise ValueError(
                        f"Accepted row missing marker code for symbol={symbol} anchor={anchor_ts_utc}"
                    )
                if code in seen_codes:
                    raise ValueError(
                        f"Duplicate marker code {code} for symbol={symbol} anchor={anchor_ts_utc}"
                    )
                seen_codes.add(code)
                expected_ts_utc = str(raw_marker.get("expected_ts_utc") or "").strip()
                if not expected_ts_utc:
                    raise ValueError(
                        f"Marker missing expected_ts_utc for symbol={symbol} anchor={anchor_ts_utc} code={code}"
                    )
                expected_ts = parse_iso_utc(
                    expected_ts_utc,
                    context=f"expected_ts_utc for symbol={symbol} anchor={anchor_ts_utc} code={code}",
                )
                if previous_expected is not None and expected_ts <= previous_expected:
                    raise ValueError(
                        "Marker expected timestamps must be strictly ascending "
                        f"for symbol={symbol} anchor={anchor_ts_utc}"
                    )
                previous_expected = expected_ts

                matched = require_marker_matched_bool(
                    raw_marker.get("matched"),
                    symbol=symbol,
                    anchor_ts_utc=anchor_ts_utc,
                    code=code,
                )
                observed_ts_utc = str(raw_marker.get("observed_ts_utc") or "").strip()
                observed_ts = None
                if matched:
                    if not observed_ts_utc:
                        raise ValueError(
                            f"Matched marker missing observed_ts_utc for symbol={symbol} anchor={anchor_ts_utc} code={code}"
                        )
                    observed_ts = parse_iso_utc(
                        observed_ts_utc,
                        context=f"observed_ts_utc for symbol={symbol} anchor={anchor_ts_utc} code={code}",
                    )

                markers.append(
                    ParsedMarker(
                        code=code,
                        kind=str(raw_marker.get("kind") or "").strip().upper(),
                        ratio=maybe_float(raw_marker.get("ratio")),
                        expected_ts_utc=expected_ts_utc,
                        expected_ts=expected_ts,
                        observed_ts_utc=observed_ts_utc,
                        observed_ts=observed_ts,
                        observed_price=maybe_float(raw_marker.get("observed_price")),
                        matched=matched,
                        timing_error_hours=maybe_float(raw_marker.get("timing_error_hours")),
                    )
                )

            venue = str(selected_full.get("venue") or raw_row.get("venue") or DEFAULT_VENUE).strip()
            interval_code = str(selected_full.get("interval_code") or raw_row.get("interval_code") or "1d").strip()
            tolerance_hours = maybe_float(selected_full.get("tolerance_hours"))
            if tolerance_hours is None:
                tolerance_hours = 0.0

            raw_flags = selected_full.get("flags")
            flags: dict[str, bool | None] = {}
            if isinstance(raw_flags, dict):
                for key in sorted(raw_flags):
                    flags[str(key)] = maybe_bool(raw_flags.get(key))

            inline_candles = extract_inline_candles(
                raw_row,
                selected_full,
                context=f"inline evidence candles for symbol={symbol} anchor={anchor_ts_utc}",
            )

            records.append(
                EvidenceRecord(
                    symbol=symbol,
                    anchor_ts_utc=anchor_ts_utc,
                    anchor_ts=anchor_ts,
                    checkpoint_ratio=checkpoint_ratio,
                    selected_partial_offset_days=selected_partial_offset_days,
                    venue=venue,
                    interval_code=interval_code,
                    cycle_days=maybe_float(selected_full.get("cycle_days")),
                    tolerance_hours=tolerance_hours,
                    phase_offset_days=maybe_float(selected_full.get("phase_offset_days")),
                    flags=flags,
                    markers=tuple(markers),
                    inline_candles=inline_candles,
                )
            )

    records.sort(key=lambda row: (row.symbol, row.anchor_ts, ratio_sort_value(row.checkpoint_ratio)))
    return input_rows, records


def fetch_asset_ids(conn: Any, symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}
    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"""
        SELECT asset_id, symbol
        FROM asset
        WHERE UPPER(symbol) IN ({placeholders})
        ORDER BY symbol ASC
    """
    values = [symbol.upper() for symbol in symbols]
    with conn.cursor() as cur:
        cur.execute(sql, values)
        rows = cur.fetchall()
    return {str(row["symbol"]).upper(): int(row["asset_id"]) for row in rows}


def fetch_candles_for_group(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbol_to_asset: dict[str, int],
    group_records: list[EvidenceRecord],
) -> dict[str, tuple[Candle, ...]]:
    symbols = sorted({record.symbol for record in group_records if record.symbol in symbol_to_asset})
    if not symbols:
        return {}
    starts = [chart_window(record)[0] for record in group_records]
    ends = [chart_window(record)[1] for record in group_records]
    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"""
        SELECT
            a.symbol,
            c.close_ts_utc,
            c.open_price,
            c.high_price,
            c.low_price,
            c.close_price
        FROM obs_market_candle c
        JOIN asset a
          ON a.asset_id = c.asset_id
        WHERE c.venue = %s
          AND c.interval_code = %s
          AND a.symbol IN ({placeholders})
          AND c.close_ts_utc >= %s
          AND c.close_ts_utc <= %s
        ORDER BY a.symbol ASC, c.close_ts_utc ASC
    """
    params: list[Any] = [venue, interval_code, *symbols, naive_utc(min(starts)), naive_utc(max(ends))]
    grouped: dict[str, list[Candle]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    for row in rows:
        ts = row["close_ts_utc"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        grouped[str(row["symbol"]).upper()].append(
            Candle(
                ts=ts,
                open_price=float(row["open_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                close_price=float(row["close_price"]),
            )
        )
    return {symbol: tuple(grouped.get(symbol, [])) for symbol in symbols}


def filter_candles_to_record(candles: tuple[Candle, ...], record: EvidenceRecord) -> tuple[Candle, ...]:
    start_ts, end_ts = chart_window(record)
    return tuple(candle for candle in candles if start_ts <= candle.ts <= end_ts)


def resolve_candles(records: list[EvidenceRecord]) -> tuple[dict[tuple[str, str, str], CandleLoadResult], int]:
    resolved: dict[tuple[str, str, str], CandleLoadResult] = {}
    pending: dict[tuple[str, str], list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        key = record_key(record)
        if record.inline_candles:
            filtered = filter_candles_to_record(record.inline_candles, record)
            if filtered:
                resolved[key] = CandleLoadResult(candles=filtered, source="inline", warning="")
            else:
                resolved[key] = CandleLoadResult(
                    candles=(),
                    source="missing",
                    warning=(
                        "WARNING: candles unavailable — inline evidence candles do not cover the "
                        "anchor/marker window."
                    ),
                )
            continue
        if not record.venue or not record.interval_code:
            resolved[key] = CandleLoadResult(
                candles=(),
                source="missing",
                warning=(
                    "WARNING: candles unavailable — no inline candles and no venue/interval for "
                    "read-only DB lookup."
                ),
            )
            continue
        pending[(record.venue, record.interval_code)].append(record)

    if not pending:
        return resolved, 0

    pending_symbols = sorted({record.symbol for group in pending.values() for record in group})
    db_reads = 0
    try:
        conn = get_connection()
    except Exception as exc:
        warning = f"WARNING: candles unavailable — read-only DB lookup failed: {type(exc).__name__}: {exc}"
        for group in pending.values():
            for record in group:
                resolved[record_key(record)] = CandleLoadResult(candles=(), source="missing", warning=warning)
        return resolved, db_reads

    try:
        symbol_to_asset = fetch_asset_ids(conn, pending_symbols)
        db_reads += 1
        for group_key, group_records in sorted(pending.items()):
            venue, interval_code = group_key
            available = [record for record in group_records if record.symbol in symbol_to_asset]
            missing_symbols = [record.symbol for record in group_records if record.symbol not in symbol_to_asset]
            for symbol in missing_symbols:
                matching = [record for record in group_records if record.symbol == symbol]
                for record in matching:
                    resolved[record_key(record)] = CandleLoadResult(
                        candles=(),
                        source="missing",
                        warning=f"WARNING: candles unavailable — asset lookup missing for symbol={symbol}.",
                    )
            if not available:
                continue
            grouped_candles = fetch_candles_for_group(
                conn,
                venue=venue,
                interval_code=interval_code,
                symbol_to_asset=symbol_to_asset,
                group_records=available,
            )
            db_reads += 1
            for record in available:
                filtered = filter_candles_to_record(grouped_candles.get(record.symbol, ()), record)
                if filtered:
                    resolved[record_key(record)] = CandleLoadResult(candles=filtered, source="database", warning="")
                else:
                    resolved[record_key(record)] = CandleLoadResult(
                        candles=(),
                        source="missing",
                        warning=(
                            "WARNING: candles unavailable — no read-only DB candles for "
                            f"symbol={record.symbol} venue={record.venue} interval={record.interval_code}."
                        ),
                    )
    except Exception as exc:
        warning = f"WARNING: candles unavailable — read-only DB lookup failed: {type(exc).__name__}: {exc}"
        for group in pending.values():
            for record in group:
                resolved.setdefault(record_key(record), CandleLoadResult(candles=(), source="missing", warning=warning))
    finally:
        conn.close()

    return resolved, db_reads


def x_for_ts(ts: datetime, *, start_ts: datetime, end_ts: datetime) -> float:
    span = max((end_ts - start_ts).total_seconds(), 1.0)
    progress = (ts - start_ts).total_seconds() / span
    progress = min(max(progress, 0.0), 1.0)
    return SVG_PAD_LEFT + progress * (SVG_WIDTH - SVG_PAD_LEFT - SVG_PAD_RIGHT)


def y_for_price(price: float, *, min_price: float, max_price: float) -> float:
    if math.isclose(min_price, max_price):
        return SVG_PAD_TOP + (SVG_HEIGHT - SVG_PAD_TOP - SVG_PAD_BOTTOM) / 2.0
    return SVG_PAD_TOP + (max_price - price) / (max_price - min_price) * (SVG_HEIGHT - SVG_PAD_TOP - SVG_PAD_BOTTOM)


def marker_color(marker: ParsedMarker) -> str:
    return "#a43d4f" if marker.kind == "HIGH" else "#1d7b5a"


def render_timeline_svg(record: EvidenceRecord, load_result: CandleLoadResult) -> str:
    start_ts, end_ts = chart_window(record)
    plot_top = SVG_PAD_TOP
    plot_height = SVG_HEIGHT - SVG_PAD_TOP - SVG_PAD_BOTTOM
    mid_y = plot_top + plot_height / 2.0
    pieces = [
        f"<svg viewBox='0 0 {SVG_WIDTH} {SVG_HEIGHT}' class='chart' role='img' aria-label='{esc(record.symbol)} evidence timeline'>",
        f"<rect x='0' y='0' width='{SVG_WIDTH}' height='{SVG_HEIGHT}' fill='#fffdf7'></rect>",
        f"<rect x='{SVG_PAD_LEFT:.1f}' y='{SVG_PAD_TOP:.1f}' width='{SVG_WIDTH - SVG_PAD_LEFT - SVG_PAD_RIGHT:.1f}' "
        f"height='{plot_height:.1f}' fill='#fff9ef' stroke='#d9c9a8'></rect>",
        f"<text x='28' y='38' class='chart-warning'>{esc(load_result.warning)}</text>",
        f"<line x1='{SVG_PAD_LEFT:.1f}' y1='{mid_y:.1f}' x2='{SVG_WIDTH - SVG_PAD_RIGHT:.1f}' y2='{mid_y:.1f}' "
        f"stroke='#6a6257' stroke-width='1.6' stroke-dasharray='4 5'></line>",
    ]

    anchor_x = x_for_ts(record.anchor_ts, start_ts=start_ts, end_ts=end_ts)
    pieces.append(
        f"<line x1='{anchor_x:.2f}' y1='{SVG_PAD_TOP:.1f}' x2='{anchor_x:.2f}' y2='{SVG_HEIGHT - SVG_PAD_BOTTOM:.1f}' "
        f"stroke='#003049' stroke-width='2.2' stroke-dasharray='8 4' data-anchor-ts='{esc(record.anchor_ts_utc)}'></line>"
    )
    pieces.append(
        f"<text x='{anchor_x + 6:.2f}' y='{SVG_PAD_TOP + 16:.1f}' class='marker-label'>ANCHOR</text>"
    )

    for marker in record.markers:
        window_start, window_end = tolerance_window(marker, record.tolerance_hours)
        x1 = x_for_ts(window_start, start_ts=start_ts, end_ts=end_ts)
        x2 = x_for_ts(window_end, start_ts=start_ts, end_ts=end_ts)
        expected_x = x_for_ts(marker.expected_ts, start_ts=start_ts, end_ts=end_ts)
        pieces.append(
            f"<rect x='{min(x1, x2):.2f}' y='{SVG_PAD_TOP:.1f}' width='{abs(x2 - x1):.2f}' height='{plot_height:.1f}' "
            f"class='tolerance-window' fill='{marker_color(marker)}' fill-opacity='0.10' "
            f"data-marker-code='{esc(marker.code)}' data-window-start='{esc(iso_utc(window_start))}' "
            f"data-window-end='{esc(iso_utc(window_end))}'></rect>"
        )
        pieces.append(
            f"<line x1='{expected_x:.2f}' y1='{SVG_PAD_TOP:.1f}' x2='{expected_x:.2f}' y2='{SVG_HEIGHT - SVG_PAD_BOTTOM:.1f}' "
            f"class='expected-line' stroke='{marker_color(marker)}' stroke-width='1.6' stroke-dasharray='3 5' "
            f"data-marker-code='{esc(marker.code)}' data-expected-ts='{esc(marker.expected_ts_utc)}'></line>"
        )
        pieces.append(
            f"<text x='{expected_x + 4:.2f}' y='{SVG_HEIGHT - SVG_PAD_BOTTOM + 18:.1f}' class='marker-label'>{esc(marker.code)}</text>"
        )
        if marker.matched and marker.observed_ts is not None:
            observed_x = x_for_ts(marker.observed_ts, start_ts=start_ts, end_ts=end_ts)
            observed_y = mid_y - 42.0 if marker.kind == "HIGH" else mid_y + 42.0
            pieces.append(
                f"<circle cx='{observed_x:.2f}' cy='{observed_y:.2f}' r='6.2' fill='{marker_color(marker)}' stroke='#ffffff' "
                f"stroke-width='1.4' data-selected-marker='{esc(marker.code)}' data-observed-ts='{esc(marker.observed_ts_utc)}' "
                f"data-observed-price='{esc(fmt_price(marker.observed_price))}'></circle>"
            )
            pieces.append(
                f"<line x1='{expected_x:.2f}' y1='{mid_y:.2f}' x2='{observed_x:.2f}' y2='{observed_y:.2f}' "
                f"stroke='{marker_color(marker)}' stroke-width='1.1' stroke-dasharray='2 4'></line>"
            )

    pieces.append("</svg>")
    return "".join(pieces)


def render_candle_svg(record: EvidenceRecord, load_result: CandleLoadResult) -> str:
    candles = list(load_result.candles)
    if not candles:
        return render_timeline_svg(record, load_result)

    start_ts, end_ts = chart_window(record)
    plot_width = SVG_WIDTH - SVG_PAD_LEFT - SVG_PAD_RIGHT
    plot_height = SVG_HEIGHT - SVG_PAD_TOP - SVG_PAD_BOTTOM
    prices = [candle.high_price for candle in candles] + [candle.low_price for candle in candles]
    for marker in record.markers:
        if marker.observed_price is not None:
            prices.append(marker.observed_price)
    min_price = min(prices)
    max_price = max(prices)
    if math.isclose(min_price, max_price):
        min_price *= 0.995
        max_price *= 1.005
    else:
        padding = (max_price - min_price) * 0.08
        min_price -= padding
        max_price += padding

    candle_width = max(3.0, plot_width / max(len(candles), 1) * 0.58)
    pieces = [
        f"<svg viewBox='0 0 {SVG_WIDTH} {SVG_HEIGHT}' class='chart' role='img' aria-label='{esc(record.symbol)} evidence chart'>",
        f"<rect x='0' y='0' width='{SVG_WIDTH}' height='{SVG_HEIGHT}' fill='#fffdf7'></rect>",
        f"<rect x='{SVG_PAD_LEFT:.1f}' y='{SVG_PAD_TOP:.1f}' width='{plot_width:.1f}' height='{plot_height:.1f}' fill='#fff9ef' stroke='#d9c9a8'></rect>",
    ]
    if load_result.warning:
        pieces.append(f"<text x='28' y='38' class='chart-warning'>{esc(load_result.warning)}</text>")

    for idx in range(5):
        value = min_price + (max_price - min_price) * idx / 4.0
        y = y_for_price(value, min_price=min_price, max_price=max_price)
        pieces.append(
            f"<line x1='{SVG_PAD_LEFT:.1f}' y1='{y:.2f}' x2='{SVG_WIDTH - SVG_PAD_RIGHT:.1f}' y2='{y:.2f}' "
            f"stroke='#eadfc8' stroke-width='1' stroke-dasharray='3 4'></line>"
        )
        pieces.append(
            f"<text x='10' y='{y + 4:.2f}' class='axis-label'>{esc(fmt_price(value))}</text>"
        )

    anchor_x = x_for_ts(record.anchor_ts, start_ts=start_ts, end_ts=end_ts)
    pieces.append(
        f"<line x1='{anchor_x:.2f}' y1='{SVG_PAD_TOP:.1f}' x2='{anchor_x:.2f}' y2='{SVG_HEIGHT - SVG_PAD_BOTTOM:.1f}' "
        f"stroke='#003049' stroke-width='2.2' stroke-dasharray='8 4' data-anchor-ts='{esc(record.anchor_ts_utc)}'></line>"
    )
    pieces.append(f"<text x='{anchor_x + 6:.2f}' y='{SVG_PAD_TOP + 16:.1f}' class='marker-label'>ANCHOR</text>")

    for marker in record.markers:
        window_start, window_end = tolerance_window(marker, record.tolerance_hours)
        x1 = x_for_ts(window_start, start_ts=start_ts, end_ts=end_ts)
        x2 = x_for_ts(window_end, start_ts=start_ts, end_ts=end_ts)
        expected_x = x_for_ts(marker.expected_ts, start_ts=start_ts, end_ts=end_ts)
        pieces.append(
            f"<rect x='{min(x1, x2):.2f}' y='{SVG_PAD_TOP:.1f}' width='{abs(x2 - x1):.2f}' height='{plot_height:.1f}' "
            f"class='tolerance-window' fill='{marker_color(marker)}' fill-opacity='0.10' "
            f"data-marker-code='{esc(marker.code)}' data-window-start='{esc(iso_utc(window_start))}' "
            f"data-window-end='{esc(iso_utc(window_end))}'></rect>"
        )
        pieces.append(
            f"<line x1='{expected_x:.2f}' y1='{SVG_PAD_TOP:.1f}' x2='{expected_x:.2f}' y2='{SVG_HEIGHT - SVG_PAD_BOTTOM:.1f}' "
            f"class='expected-line' stroke='{marker_color(marker)}' stroke-width='1.6' stroke-dasharray='3 5' "
            f"data-marker-code='{esc(marker.code)}' data-expected-ts='{esc(marker.expected_ts_utc)}'></line>"
        )
        pieces.append(
            f"<text x='{expected_x + 4:.2f}' y='{SVG_HEIGHT - SVG_PAD_BOTTOM + 18:.1f}' class='marker-label'>{esc(marker.code)}</text>"
        )

    for candle in candles:
        x = x_for_ts(candle.ts, start_ts=start_ts, end_ts=end_ts)
        wick_y1 = y_for_price(candle.high_price, min_price=min_price, max_price=max_price)
        wick_y2 = y_for_price(candle.low_price, min_price=min_price, max_price=max_price)
        open_y = y_for_price(candle.open_price, min_price=min_price, max_price=max_price)
        close_y = y_for_price(candle.close_price, min_price=min_price, max_price=max_price)
        body_y = min(open_y, close_y)
        body_h = max(abs(open_y - close_y), 1.6)
        color = "#0f7b4d" if candle.close_price >= candle.open_price else "#a43d4f"
        pieces.append(
            f"<line class='candle-wick' x1='{x:.2f}' y1='{wick_y1:.2f}' x2='{x:.2f}' y2='{wick_y2:.2f}' stroke='{color}' stroke-width='1.2'></line>"
        )
        pieces.append(
            f"<rect class='candle-body' x='{x - candle_width / 2:.2f}' y='{body_y:.2f}' width='{candle_width:.2f}' height='{body_h:.2f}' "
            f"fill='{color}' fill-opacity='0.82' stroke='{color}' stroke-width='1'></rect>"
        )

    for marker in record.markers:
        if not marker.matched or marker.observed_ts is None or marker.observed_price is None:
            continue
        observed_x = x_for_ts(marker.observed_ts, start_ts=start_ts, end_ts=end_ts)
        observed_y = y_for_price(marker.observed_price, min_price=min_price, max_price=max_price)
        expected_x = x_for_ts(marker.expected_ts, start_ts=start_ts, end_ts=end_ts)
        pieces.append(
            f"<line x1='{expected_x:.2f}' y1='{SVG_PAD_TOP + 18:.1f}' x2='{observed_x:.2f}' y2='{observed_y:.2f}' "
            f"stroke='{marker_color(marker)}' stroke-width='1.1' stroke-dasharray='2 4'></line>"
        )
        pieces.append(
            f"<circle cx='{observed_x:.2f}' cy='{observed_y:.2f}' r='6.2' fill='{marker_color(marker)}' stroke='#ffffff' "
            f"stroke-width='1.4' data-selected-marker='{esc(marker.code)}' data-observed-ts='{esc(marker.observed_ts_utc)}' "
            f"data-observed-price='{esc(fmt_price(marker.observed_price))}'></circle>"
        )

    pieces.append("</svg>")
    return "".join(pieces)


def render_flags_table(record: EvidenceRecord) -> str:
    if not record.flags:
        return "<p class='muted'>No shape flags provided in selected_full_same_offset.flags.</p>"
    rows = "".join(
        f"<tr><th>{esc(key)}</th><td>{esc(bool_text(value))}</td></tr>"
        for key, value in sorted(record.flags.items())
    )
    return f"<table class='detail-table'><tbody>{rows}</tbody></table>"


def render_selected_extrema(record: EvidenceRecord) -> str:
    matched = [marker for marker in record.markers if marker.matched]
    if not matched:
        return "<p class='muted'>No matched extrema on this observation.</p>"
    rows = "".join(
        "<tr>"
        f"<td>{esc(marker.code)}</td>"
        f"<td>{esc(marker.kind or 'NA')}</td>"
        f"<td>{esc(marker.observed_ts_utc or '')}</td>"
        f"<td>{esc(fmt_price(marker.observed_price))}</td>"
        "</tr>"
        for marker in matched
    )
    return (
        "<table class='detail-table'><thead><tr><th>Marker</th><th>Kind</th><th>Observed ts</th><th>Observed price</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def render_marker_table(record: EvidenceRecord) -> str:
    rows: list[str] = []
    for marker in record.markers:
        window_start, window_end = tolerance_window(marker, record.tolerance_hours)
        rows.append(
            "<tr>"
            f"<td>{esc(marker.code)}</td>"
            f"<td>{esc(marker.kind or 'NA')}</td>"
            f"<td>{esc(fmt_float(marker.ratio))}</td>"
            f"<td>{esc(marker.expected_ts_utc)}</td>"
            f"<td>{esc(marker.observed_ts_utc)}</td>"
            f"<td>{esc(fmt_hours(marker_timing_delta_hours(marker)))}</td>"
            f"<td>{esc(fmt_float(marker.timing_error_hours, 3))}</td>"
            f"<td>{esc(fmt_price(marker.observed_price))}</td>"
            f"<td>{esc(iso_utc(window_start))}</td>"
            f"<td>{esc(iso_utc(window_end))}</td>"
            f"<td>{esc('YES' if marker.matched else 'NO')}</td>"
            "</tr>"
        )
    return (
        "<table class='detail-table marker-table'><thead><tr>"
        "<th>Marker code</th><th>Kind</th><th>Ratio</th><th>Expected ts</th><th>Observed ts</th>"
        "<th>Observed - expected</th><th>Timing error hours</th><th>Observed price</th>"
        "<th>Window start</th><th>Window end</th><th>Matched</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_safety_markers() -> str:
    rows = "".join(
        f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>"
        for key, value in SAFETY_MARKERS.items()
    )
    return f"<table class='detail-table'><tbody>{rows}</tbody></table>"


def render_page(
    *,
    record: EvidenceRecord,
    load_result: CandleLoadResult,
    page_file: str,
    generated_at: datetime,
) -> str:
    matched_marker_count = sum(1 for marker in record.markers if marker.matched)
    metadata_rows = [
        ("symbol", record.symbol),
        ("anchor_ts_utc", record.anchor_ts_utc),
        ("checkpoint_ratio", record.checkpoint_ratio),
        ("selected_partial_offset_days", fmt_float(record.selected_partial_offset_days)),
        ("phase_offset_days", fmt_float(record.phase_offset_days)),
        ("cycle_days", fmt_float(record.cycle_days)),
        ("tolerance_hours", fmt_float(record.tolerance_hours)),
        ("venue", record.venue),
        ("interval_code", record.interval_code),
        ("matched_markers", f"{matched_marker_count}/{len(record.markers)}"),
        ("candle_source", load_result.source),
        ("candle_count", str(len(load_result.candles))),
        ("generated_at_utc", iso_utc(generated_at)),
        ("page_file", page_file),
    ]
    metadata_table = "".join(f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>" for key, value in metadata_rows)
    warning_html = (
        f"<div class='warning-box'>{esc(load_result.warning)}</div>" if load_result.warning else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(record.symbol)} marker evidence {esc(record.anchor_ts_utc)} checkpoint {esc(record.checkpoint_ratio)}</title>
  <style>
    :root {{
      --bg: #f4efe2;
      --paper: #fffdf7;
      --ink: #2c241b;
      --muted: #6d655a;
      --line: #d7c8ab;
      --accent: #003049;
      --warn-bg: #fff1dd;
      --warn-border: #bb6c25;
      --mono: "IBM Plex Mono", "SFMono-Regular", monospace;
      --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
      --serif: "IBM Plex Serif", Georgia, serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        linear-gradient(180deg, rgba(0,48,73,0.06), transparent 22%),
        radial-gradient(circle at top right, rgba(187,108,37,0.12), transparent 28%),
        var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      padding: 24px;
    }}
    .wrap {{ max-width: 1440px; margin: 0 auto; }}
    .hero, .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: 0 16px 40px rgba(44, 36, 27, 0.07);
    }}
    .hero {{
      padding: 20px 22px;
      margin-bottom: 18px;
    }}
    h1, h2 {{
      margin: 0;
      font-family: var(--serif);
      font-weight: 600;
      letter-spacing: 0.01em;
    }}
    .hero h1 {{ font-size: 30px; }}
    .hero p {{
      margin: 8px 0 0;
      font-size: 14px;
      color: var(--muted);
      font-family: var(--mono);
    }}
    .alert {{
      margin-top: 14px;
      padding: 12px 14px;
      border: 1px solid var(--warn-border);
      background: var(--warn-bg);
      font-family: var(--mono);
      font-size: 14px;
      line-height: 1.45;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }}
    .card {{ padding: 18px; }}
    .card h2 {{
      font-size: 22px;
      margin-bottom: 12px;
    }}
    .chart {{
      width: 100%;
      height: auto;
      display: block;
      border: 1px solid var(--line);
      background: #fffdf7;
    }}
    .axis-label, .marker-label, .chart-warning {{
      font-family: var(--mono);
      fill: var(--muted);
      font-size: 12px;
    }}
    .chart-warning {{
      fill: #9b4200;
      font-size: 13px;
      font-weight: 600;
    }}
    .marker-label {{
      fill: #52483a;
      font-size: 11px;
    }}
    .warning-box {{
      margin: 14px 0 0;
      padding: 12px 14px;
      border: 1px solid var(--warn-border);
      background: var(--warn-bg);
      font-family: var(--mono);
      font-size: 13px;
    }}
    .detail-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .detail-table th, .detail-table td {{
      border: 1px solid var(--line);
      padding: 8px 10px;
      vertical-align: top;
      text-align: left;
    }}
    .detail-table th {{
      background: #f7f0e1;
      font-family: var(--mono);
      font-weight: 600;
      width: 32%;
    }}
    .marker-table th {{
      width: auto;
      white-space: nowrap;
    }}
    .section-stack {{
      display: grid;
      gap: 18px;
    }}
    .muted {{
      color: var(--muted);
      margin: 0;
      font-size: 14px;
    }}
    .back-link {{
      color: var(--accent);
      font-family: var(--mono);
      text-decoration: none;
    }}
    @media (max-width: 1100px) {{
      .grid {{ grid-template-columns: 1fr; }}
      body {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <a class="back-link" href="{esc(INDEX_HTML)}">Back to index</a>
      <h1>{esc(TITLE_LINE)}</h1>
      <p>{esc(WARNING_LINE)}</p>
      <div class="alert">{esc(TITLE_LINE)}<br>{esc(WARNING_LINE)}</div>
    </section>
    <section class="card">
      <h2>Evidence Chart</h2>
      {render_candle_svg(record, load_result)}
      {warning_html}
    </section>
    <section class="grid">
      <section class="card">
        <h2>Observation</h2>
        <table class="detail-table"><tbody>{metadata_table}</tbody></table>
      </section>
      <section class="card">
        <h2>Safety Markers</h2>
        {render_safety_markers()}
      </section>
    </section>
    <section class="section-stack">
      <section class="card">
        <h2>Shape Flags</h2>
        {render_flags_table(record)}
      </section>
      <section class="card">
        <h2>Selected Extrema</h2>
        {render_selected_extrema(record)}
      </section>
      <section class="card">
        <h2>Marker Table</h2>
        {render_marker_table(record)}
      </section>
    </section>
  </div>
</body>
</html>
"""


def render_index(
    *,
    records: list[EvidenceRecord],
    candle_results: dict[tuple[str, str, str], CandleLoadResult],
    page_files: dict[tuple[str, str, str], str],
    generated_at: datetime,
    symbols_filter: list[str],
    checkpoint_filter: str,
) -> str:
    rows: list[str] = []
    for record in records:
        key = record_key(record)
        load_result = candle_results[key]
        matched_count = sum(1 for marker in record.markers if marker.matched)
        rows.append(
            "<tr>"
            f"<td><a href='{esc(page_files[key])}'>{esc(record.symbol)}</a></td>"
            f"<td>{esc(record.anchor_ts_utc)}</td>"
            f"<td>{esc(record.checkpoint_ratio)}</td>"
            f"<td>{matched_count}/{len(record.markers)}</td>"
            f"<td>{esc(load_result.source)}</td>"
            f"<td>{len(load_result.candles)}</td>"
            f"<td>{esc(load_result.warning)}</td>"
            "</tr>"
        )
    safety_rows = "".join(
        f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>"
        for key, value in SAFETY_MARKERS.items()
    )
    filters = [
        ("symbols_filter", ",".join(symbols_filter) if symbols_filter else "ALL"),
        ("checkpoint_ratio_filter", checkpoint_filter or "ALL"),
        ("generated_at_utc", iso_utc(generated_at)),
        ("pages", str(len(records))),
    ]
    filter_rows = "".join(f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>" for key, value in filters)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Breathline Marker Evidence Viewer</title>
  <style>
    :root {{
      --bg: #f4efe2;
      --paper: #fffdf7;
      --ink: #2c241b;
      --muted: #6d655a;
      --line: #d7c8ab;
      --accent: #003049;
      --warn-bg: #fff1dd;
      --mono: "IBM Plex Mono", "SFMono-Regular", monospace;
      --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
      --serif: "IBM Plex Serif", Georgia, serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        linear-gradient(180deg, rgba(0,48,73,0.06), transparent 22%),
        radial-gradient(circle at top right, rgba(187,108,37,0.12), transparent 28%),
        var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      padding: 24px;
    }}
    .wrap {{ max-width: 1440px; margin: 0 auto; }}
    .hero, .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: 0 16px 40px rgba(44, 36, 27, 0.07);
    }}
    .hero {{
      padding: 20px 22px;
      margin-bottom: 18px;
    }}
    h1, h2 {{
      margin: 0;
      font-family: var(--serif);
      font-weight: 600;
    }}
    .hero p {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 14px;
      font-family: var(--mono);
    }}
    .alert {{
      margin-top: 14px;
      padding: 12px 14px;
      background: var(--warn-bg);
      border: 1px solid #bb6c25;
      font-family: var(--mono);
      font-size: 14px;
      line-height: 1.45;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 0.9fr 1.1fr;
      gap: 18px;
      margin-bottom: 18px;
    }}
    .card {{ padding: 18px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f7f0e1;
      font-family: var(--mono);
      font-weight: 600;
    }}
    a {{ color: var(--accent); }}
    @media (max-width: 1100px) {{
      .grid {{ grid-template-columns: 1fr; }}
      body {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{esc(TITLE_LINE)}</h1>
      <p>{esc(WARNING_LINE)}</p>
      <div class="alert">{esc(TITLE_LINE)}<br>{esc(WARNING_LINE)}</div>
    </section>
    <section class="grid">
      <section class="card">
        <h2>Render Scope</h2>
        <table><tbody>{filter_rows}</tbody></table>
      </section>
      <section class="card">
        <h2>Safety Markers</h2>
        <table><tbody>{safety_rows}</tbody></table>
      </section>
    </section>
    <section class="card">
      <h2>Evidence Pages</h2>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Anchor ts</th>
            <th>Checkpoint</th>
            <th>Matched markers</th>
            <th>Candle source</th>
            <th>Candle count</th>
            <th>Warning</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_manifest(
    *,
    input_path: Path,
    input_rows: int,
    records: list[EvidenceRecord],
    db_reads: int,
    symbols_filter: list[str],
    checkpoint_filter: str,
) -> str:
    lines = [
        f"report={RUNNER_NAME}",
        f"version={VERSION}",
        f"generated_at_utc={iso_utc(utc_now())}",
        f"source_git_commit={current_git_commit()}",
        f"input_jsonl={input_path}",
        f"input_sha256={sha256_file(input_path)}",
        f"input_rows={input_rows}",
        f"rendered_rows={len(records)}",
        f"page_count={len(records)}",
        f"index_html={INDEX_HTML}",
        f"evidence_index_csv={EVIDENCE_INDEX_CSV}",
        f"manifest_txt={MANIFEST_TXT}",
        f"symbols_filter={','.join(symbols_filter) if symbols_filter else 'ALL'}",
        f"checkpoint_ratio_filter={checkpoint_filter or 'ALL'}",
        f"db_reads={db_reads}",
        "static_html_only=1",
        "terminology=marker_evidence_not_phase_duration",
        "scope=research_only_static_review",
    ]
    for key, value in SAFETY_MARKERS.items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input_jsonl)
    out_dir = Path(args.out_dir)
    symbols_filter = parse_symbols(args.symbols)
    checkpoint_filter = str(args.checkpoint_ratio or "").strip()
    started_at = time.perf_counter()

    print(
        "STARTED "
        f"{RUNNER_NAME} mode=research_only_static_html scope=marker_evidence "
        f"symbols={','.join(symbols_filter) if symbols_filter else 'ALL'} "
        f"checkpoint_ratio={checkpoint_filter or 'ALL'}",
        flush=True,
    )
    print(TITLE_LINE, flush=True)
    print(WARNING_LINE, flush=True)
    for key, value in SAFETY_MARKERS.items():
        print(f"{key}={value}", flush=True)

    ensure_empty_output_dir(out_dir)
    input_rows, records = load_records(
        input_path,
        symbols_filter=symbols_filter,
        checkpoint_filter=checkpoint_filter,
    )
    print(f"PHASE loaded_records input_rows={input_rows} rendered_rows={len(records)}", flush=True)

    candle_results, db_reads = resolve_candles(records)
    print(f"PHASE resolved_candles db_reads={db_reads}", flush=True)

    generated_at = utc_now()
    page_files: dict[tuple[str, str, str], str] = {}
    csv_rows: list[dict[str, Any]] = []

    for record in records:
        key = record_key(record)
        page_file = page_file_name(record)
        page_files[key] = page_file
        load_result = candle_results[key]
        (out_dir / page_file).write_text(
            render_page(
                record=record,
                load_result=load_result,
                page_file=page_file,
                generated_at=generated_at,
            ),
            encoding="utf-8",
        )
        csv_rows.append(
            {
                "symbol": record.symbol,
                "anchor_ts_utc": record.anchor_ts_utc,
                "checkpoint_ratio": record.checkpoint_ratio,
                "page_file": page_file,
                "marker_count": len(record.markers),
                "matched_marker_count": sum(1 for marker in record.markers if marker.matched),
                "candle_source": load_result.source,
                "candle_count": len(load_result.candles),
                "warning": load_result.warning,
            }
        )

    (out_dir / INDEX_HTML).write_text(
        render_index(
            records=records,
            candle_results=candle_results,
            page_files=page_files,
            generated_at=generated_at,
            symbols_filter=symbols_filter,
            checkpoint_filter=checkpoint_filter,
        ),
        encoding="utf-8",
    )
    write_csv(out_dir / EVIDENCE_INDEX_CSV, csv_rows, CSV_FIELDS)
    (out_dir / MANIFEST_TXT).write_text(
        build_manifest(
            input_path=input_path,
            input_rows=input_rows,
            records=records,
            db_reads=db_reads,
            symbols_filter=symbols_filter,
            checkpoint_filter=checkpoint_filter,
        ),
        encoding="utf-8",
    )

    print(f"pages_written={len(records)}", flush=True)
    print(f"output_dir={out_dir}", flush=True)
    print(
        f"FINISHED {RUNNER_NAME} elapsed_s={time.perf_counter() - started_at:.3f} "
        f"rendered_rows={len(records)} db_reads={db_reads}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
