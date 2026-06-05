from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.research.htf_fib_extension_confluence_v1 import (
    HtfSwingInput,
    build_htf_extension_map,
)
from src.research.htf_fib_reentry_ladder_v1 import (
    HtfReentryInput,
    build_fib_retrace_ladder,
)


SHORT_CONTEXT_VERSION = "0.1"
SHORT_CONTEXT_SOURCE_NAME = "native_short_fib_context_v1"
SHORT_CONTEXT_HORIZON = "SHORT"
PRIMARY_INTERVAL = "4h"
SUPPORTING_INTERVAL = "1h"
DEFAULT_QUOTE = "EUR"
DEFAULT_OUTPUT_DIR = Path("data/research/native_short_fib_context_v1")
DEFAULT_ROWS_CSV = DEFAULT_OUTPUT_DIR / "native_short_fib_context_rows_v1.csv"
DEFAULT_ROWS_JSONL = DEFAULT_OUTPUT_DIR / "native_short_fib_context_rows_v1.jsonl"
DEFAULT_COVERAGE_CSV = DEFAULT_OUTPUT_DIR / "coverage_summary_v1.csv"
DEFAULT_MANIFEST_JSON = DEFAULT_OUTPUT_DIR / "manifest_v1.json"

STATUS_AVAILABLE = "NATIVE_SHORT_CONTEXT_AVAILABLE"
STATUS_INSUFFICIENT_4H = "INSUFFICIENT_4H_HISTORY"
STATUS_INSUFFICIENT_1H = "INSUFFICIENT_1H_HISTORY"
STATUS_STALE_OR_INVALID = "CONTEXT_INVALID_OR_STALE"
STATUS_SYMBOL_MISSING = "SYMBOL_CONTEXT_MISSING"

PRIMARY_LIFECYCLE_ACTIVE = "ACTIVE_4H_EXTENSION"
PRIMARY_LIFECYCLE_COMPLETED = "MAP_COMPLETED"
PRIMARY_LIFECYCLE_PULLBACK = "POST_BREAKOUT_PULLBACK"
PRIMARY_LIFECYCLE_BELOW_GATE = "BELOW_BREAKOUT_GATE"

SUPPORT_STATE_UNKNOWN = "UNKNOWN"
SUPPORT_STATE_ALIGNED = "ALIGNED_WITH_4H"
SUPPORT_STATE_CONFLICT = "CONFLICT_WITH_4H"
SUPPORT_STATE_RETEST = "RETESTING_BREAKOUT_GATE"

FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE_PRIMARY = "STALE_PRIMARY_4H"
FRESHNESS_STALE_SUPPORT = "STALE_SUPPORT_1H"

DEFAULT_PRIMARY_LOOKBACK_DAYS = 60
DEFAULT_SUPPORT_LOOKBACK_DAYS = 21
DEFAULT_MIN_PRIMARY_CANDLES = 24
DEFAULT_MIN_SUPPORT_CANDLES = 48
DEFAULT_PIVOT_SPAN = 2
DEFAULT_PRIMARY_STALE_HOURS = 12
DEFAULT_SUPPORT_STALE_HOURS = 3
BREAKOUT_RETEST_PROXIMITY_PCT = Decimal("1.50")

CSV_FIELDS = [
    "symbol",
    "venue",
    "quote_currency",
    "fib_trading_horizon",
    "primary_interval",
    "supporting_interval",
    "context_status",
    "map_cycle_id",
    "anchor_start_ts_utc",
    "anchor_end_ts_utc",
    "anchor_low_price",
    "anchor_high_price",
    "breakout_gate_price",
    "latest_primary_close_ts_utc",
    "latest_support_close_ts_utc",
    "latest_primary_close_price",
    "ext_1_272_price",
    "ext_1_618_price",
    "ext_2_000_price",
    "active_target_levels_json",
    "previous_target_levels_json",
    "reload_r382_price",
    "reload_r500_price",
    "reload_r618_price",
    "reload_r786_price",
    "invalidation_price",
    "primary_4h_lifecycle_state",
    "supporting_1h_state",
    "context_freshness_status",
    "max_primary_high_since_anchor",
    "min_primary_low_since_anchor",
    "source_name",
    "source_version",
    "source_primary_ref",
    "source_support_ref",
]


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class NativeShortContextRow:
    symbol: str
    venue: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str
    context_status: str
    map_cycle_id: str
    anchor_start_ts_utc: datetime | None
    anchor_end_ts_utc: datetime | None
    anchor_low_price: Decimal | None
    anchor_high_price: Decimal | None
    breakout_gate_price: Decimal | None
    latest_primary_close_ts_utc: datetime | None
    latest_support_close_ts_utc: datetime | None
    latest_primary_close_price: Decimal | None
    ext_1_272_price: Decimal | None
    ext_1_618_price: Decimal | None
    ext_2_000_price: Decimal | None
    active_target_levels: tuple[Decimal, ...]
    previous_target_levels: tuple[Decimal, ...]
    reload_r382_price: Decimal | None
    reload_r500_price: Decimal | None
    reload_r618_price: Decimal | None
    reload_r786_price: Decimal | None
    invalidation_price: Decimal | None
    primary_4h_lifecycle_state: str
    supporting_1h_state: str
    context_freshness_status: str
    max_primary_high_since_anchor: Decimal | None
    min_primary_low_since_anchor: Decimal | None
    source_name: str
    source_version: str
    source_primary_ref: str
    source_support_ref: str

    def to_csv_row(self) -> dict[str, str]:
        def _fmt_ts(value: datetime | None) -> str:
            if value is None:
                return ""
            value_utc = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
            return value_utc.isoformat().replace("+00:00", "Z")

        def _fmt_dec(value: Decimal | None) -> str:
            return "" if value is None else format(value, "f")

        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "quote_currency": self.quote_currency,
            "fib_trading_horizon": self.fib_trading_horizon,
            "primary_interval": self.primary_interval,
            "supporting_interval": self.supporting_interval,
            "context_status": self.context_status,
            "map_cycle_id": self.map_cycle_id,
            "anchor_start_ts_utc": _fmt_ts(self.anchor_start_ts_utc),
            "anchor_end_ts_utc": _fmt_ts(self.anchor_end_ts_utc),
            "anchor_low_price": _fmt_dec(self.anchor_low_price),
            "anchor_high_price": _fmt_dec(self.anchor_high_price),
            "breakout_gate_price": _fmt_dec(self.breakout_gate_price),
            "latest_primary_close_ts_utc": _fmt_ts(self.latest_primary_close_ts_utc),
            "latest_support_close_ts_utc": _fmt_ts(self.latest_support_close_ts_utc),
            "latest_primary_close_price": _fmt_dec(self.latest_primary_close_price),
            "ext_1_272_price": _fmt_dec(self.ext_1_272_price),
            "ext_1_618_price": _fmt_dec(self.ext_1_618_price),
            "ext_2_000_price": _fmt_dec(self.ext_2_000_price),
            "active_target_levels_json": json.dumps([_fmt_dec(v) for v in self.active_target_levels]),
            "previous_target_levels_json": json.dumps([_fmt_dec(v) for v in self.previous_target_levels]),
            "reload_r382_price": _fmt_dec(self.reload_r382_price),
            "reload_r500_price": _fmt_dec(self.reload_r500_price),
            "reload_r618_price": _fmt_dec(self.reload_r618_price),
            "reload_r786_price": _fmt_dec(self.reload_r786_price),
            "invalidation_price": _fmt_dec(self.invalidation_price),
            "primary_4h_lifecycle_state": self.primary_4h_lifecycle_state,
            "supporting_1h_state": self.supporting_1h_state,
            "context_freshness_status": self.context_freshness_status,
            "max_primary_high_since_anchor": _fmt_dec(self.max_primary_high_since_anchor),
            "min_primary_low_since_anchor": _fmt_dec(self.min_primary_low_since_anchor),
            "source_name": self.source_name,
            "source_version": self.source_version,
            "source_primary_ref": self.source_primary_ref,
            "source_support_ref": self.source_support_ref,
        }


def _parse_decimal(value: Any) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _find_pivot_lows(candles: list[Candle], span: int) -> list[int]:
    result: list[int] = []
    for index in range(span, len(candles) - span):
        low = candles[index].low_price
        window = candles[index - span : index + span + 1]
        if all(low <= candle.low_price for candle in window):
            result.append(index)
    return result


def _find_pivot_highs(candles: list[Candle], span: int) -> list[int]:
    result: list[int] = []
    for index in range(span, len(candles) - span):
        high = candles[index].high_price
        window = candles[index - span : index + span + 1]
        if all(high >= candle.high_price for candle in window):
            result.append(index)
    return result


def _detect_swings(candles: list[Candle], pivot_span: int) -> list[dict[str, Any]]:
    lows = _find_pivot_lows(candles, pivot_span)
    highs = _find_pivot_highs(candles, pivot_span)
    swings: list[dict[str, Any]] = []
    for high_idx in highs:
        prior_lows = [low_idx for low_idx in lows if low_idx < high_idx]
        if not prior_lows:
            continue
        low_idx = prior_lows[-1]
        swing_low = candles[low_idx].low_price
        swing_high = candles[high_idx].high_price
        if swing_low <= 0 or swing_high <= swing_low:
            continue
        swings.append(
            {
                "low_idx": low_idx,
                "high_idx": high_idx,
                "low_ts": candles[low_idx].close_ts_utc,
                "high_ts": candles[high_idx].close_ts_utc,
                "swing_low": swing_low,
                "swing_high": swing_high,
            }
        )
    deduped: dict[str, dict[str, Any]] = {}
    for swing in swings:
        deduped[swing["high_ts"].isoformat()] = swing
    return [deduped[key] for key in sorted(deduped)]


def _pct_diff(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        return Decimal("0")
    return abs(a - b) / b * Decimal("100")


def _base_row(
    *,
    symbol: str,
    venue: str,
    status: str,
    primary_state: str = "UNKNOWN",
    support_state: str = SUPPORT_STATE_UNKNOWN,
    freshness_status: str = FRESHNESS_FRESH,
) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol.upper(),
        venue=venue,
        quote_currency=DEFAULT_QUOTE,
        fib_trading_horizon=SHORT_CONTEXT_HORIZON,
        primary_interval=PRIMARY_INTERVAL,
        supporting_interval=SUPPORTING_INTERVAL,
        context_status=status,
        map_cycle_id="",
        anchor_start_ts_utc=None,
        anchor_end_ts_utc=None,
        anchor_low_price=None,
        anchor_high_price=None,
        breakout_gate_price=None,
        latest_primary_close_ts_utc=None,
        latest_support_close_ts_utc=None,
        latest_primary_close_price=None,
        ext_1_272_price=None,
        ext_1_618_price=None,
        ext_2_000_price=None,
        active_target_levels=(),
        previous_target_levels=(),
        reload_r382_price=None,
        reload_r500_price=None,
        reload_r618_price=None,
        reload_r786_price=None,
        invalidation_price=None,
        primary_4h_lifecycle_state=primary_state,
        supporting_1h_state=support_state,
        context_freshness_status=freshness_status,
        max_primary_high_since_anchor=None,
        min_primary_low_since_anchor=None,
        source_name=SHORT_CONTEXT_SOURCE_NAME,
        source_version=SHORT_CONTEXT_VERSION,
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
    )


def build_native_short_context_row(
    *,
    symbol: str,
    venue: str,
    primary_candles: list[Candle],
    support_candles: list[Candle],
    now_utc: datetime,
    min_primary_candles: int = DEFAULT_MIN_PRIMARY_CANDLES,
    min_support_candles: int = DEFAULT_MIN_SUPPORT_CANDLES,
    pivot_span: int = DEFAULT_PIVOT_SPAN,
    primary_stale_after: timedelta = timedelta(hours=DEFAULT_PRIMARY_STALE_HOURS),
    support_stale_after: timedelta = timedelta(hours=DEFAULT_SUPPORT_STALE_HOURS),
) -> NativeShortContextRow:
    symbol = symbol.upper()
    if len(primary_candles) < min_primary_candles:
        return _base_row(symbol=symbol, venue=venue, status=STATUS_INSUFFICIENT_4H, primary_state="UNKNOWN")

    swings = _detect_swings(primary_candles, pivot_span)
    if not swings:
        return _base_row(symbol=symbol, venue=venue, status=STATUS_STALE_OR_INVALID, primary_state="UNKNOWN")

    latest_primary = primary_candles[-1]
    if now_utc - latest_primary.close_ts_utc > primary_stale_after:
        return _base_row(
            symbol=symbol,
            venue=venue,
            status=STATUS_STALE_OR_INVALID,
            primary_state="UNKNOWN",
            freshness_status=FRESHNESS_STALE_PRIMARY,
        )

    swing = swings[-1]
    anchor_start_ts = swing["low_ts"]
    anchor_end_ts = swing["high_ts"]
    anchor_low = swing["swing_low"]
    anchor_high = swing["swing_high"]
    anchor_window = [c for c in primary_candles if c.close_ts_utc >= anchor_end_ts]
    max_high_since_anchor = max((c.high_price for c in anchor_window), default=anchor_high)
    min_low_since_anchor = min((c.low_price for c in anchor_window), default=anchor_low)

    extension_map = build_htf_extension_map(
        HtfSwingInput(
            symbol=symbol,
            interval_code=PRIMARY_INTERVAL,
            swing_low=anchor_low,
            swing_high=anchor_high,
            current_price=latest_primary.close_price,
            prior_high_price=anchor_high,
        )
    )
    reentry_ladder = build_fib_retrace_ladder(
        HtfReentryInput(
            symbol=symbol,
            interval_code=PRIMARY_INTERVAL,
            swing_low=anchor_low,
            swing_high=anchor_high,
            current_price=latest_primary.close_price,
            recent_low_price=min_low_since_anchor,
        )
    )
    target_levels = tuple(target.price for target in extension_map.targets)
    previous_target_levels = tuple(level for level in target_levels if max_high_since_anchor >= level)
    active_target_levels = tuple(level for level in target_levels if max_high_since_anchor < level)

    if not active_target_levels:
        primary_state = PRIMARY_LIFECYCLE_COMPLETED
    elif latest_primary.close_price < extension_map.breakout_gate:
        primary_state = PRIMARY_LIFECYCLE_PULLBACK if previous_target_levels else PRIMARY_LIFECYCLE_BELOW_GATE
    else:
        primary_state = PRIMARY_LIFECYCLE_ACTIVE

    support_state = SUPPORT_STATE_UNKNOWN
    status = STATUS_AVAILABLE
    freshness_status = FRESHNESS_FRESH
    latest_support_ts: datetime | None = None
    if len(support_candles) < min_support_candles:
        status = STATUS_INSUFFICIENT_1H
    else:
        latest_support = support_candles[-1]
        latest_support_ts = latest_support.close_ts_utc
        if now_utc - latest_support.close_ts_utc > support_stale_after:
            status = STATUS_STALE_OR_INVALID
            freshness_status = FRESHNESS_STALE_SUPPORT
        else:
            proximity = _pct_diff(latest_support.close_price, extension_map.breakout_gate)
            if latest_support.low_price <= anchor_low:
                support_state = SUPPORT_STATE_CONFLICT
            elif proximity <= BREAKOUT_RETEST_PROXIMITY_PCT:
                support_state = SUPPORT_STATE_RETEST
            elif latest_support.close_price >= extension_map.breakout_gate:
                support_state = SUPPORT_STATE_ALIGNED
            else:
                support_state = SUPPORT_STATE_CONFLICT

    level_by_label = {row.label: row.price for row in reentry_ladder.levels}
    return NativeShortContextRow(
        symbol=symbol,
        venue=venue,
        quote_currency=DEFAULT_QUOTE,
        fib_trading_horizon=SHORT_CONTEXT_HORIZON,
        primary_interval=PRIMARY_INTERVAL,
        supporting_interval=SUPPORTING_INTERVAL,
        context_status=status,
        map_cycle_id=f"{symbol}|SHORT|4h|{anchor_start_ts.isoformat()}|{anchor_end_ts.isoformat()}",
        anchor_start_ts_utc=anchor_start_ts,
        anchor_end_ts_utc=anchor_end_ts,
        anchor_low_price=anchor_low,
        anchor_high_price=anchor_high,
        breakout_gate_price=extension_map.breakout_gate,
        latest_primary_close_ts_utc=latest_primary.close_ts_utc,
        latest_support_close_ts_utc=latest_support_ts,
        latest_primary_close_price=latest_primary.close_price,
        ext_1_272_price=next((target.price for target in extension_map.targets if target.label == "ext_1_272"), None),
        ext_1_618_price=next((target.price for target in extension_map.targets if target.label == "ext_1_618"), None),
        ext_2_000_price=next((target.price for target in extension_map.targets if target.label == "ext_2_000"), None),
        active_target_levels=active_target_levels,
        previous_target_levels=previous_target_levels,
        reload_r382_price=level_by_label.get("retrace_0_382"),
        reload_r500_price=level_by_label.get("retrace_0_500"),
        reload_r618_price=level_by_label.get("retrace_0_618"),
        reload_r786_price=level_by_label.get("retrace_0_786"),
        invalidation_price=anchor_low,
        primary_4h_lifecycle_state=primary_state,
        supporting_1h_state=support_state,
        context_freshness_status=freshness_status,
        max_primary_high_since_anchor=max_high_since_anchor,
        min_primary_low_since_anchor=min_low_since_anchor,
        source_name=SHORT_CONTEXT_SOURCE_NAME,
        source_version=SHORT_CONTEXT_VERSION,
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
    )


def summarize_context_rows(rows: list[NativeShortContextRow]) -> dict[str, int]:
    summary = {
        STATUS_AVAILABLE: 0,
        STATUS_INSUFFICIENT_4H: 0,
        STATUS_INSUFFICIENT_1H: 0,
        STATUS_STALE_OR_INVALID: 0,
        STATUS_SYMBOL_MISSING: 0,
    }
    for row in rows:
        summary[row.context_status] = summary.get(row.context_status, 0) + 1
    return summary


def write_context_rows(
    *,
    rows: list[NativeShortContextRow],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_csv = output_dir / DEFAULT_ROWS_CSV.name
    rows_jsonl = output_dir / DEFAULT_ROWS_JSONL.name
    coverage_csv = output_dir / DEFAULT_COVERAGE_CSV.name
    manifest_json = output_dir / DEFAULT_MANIFEST_JSON.name
    with rows_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())
    with rows_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_csv_row(), sort_keys=True) + "\n")
    summary = summarize_context_rows(rows)
    with coverage_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["context_status", "row_count"])
        writer.writeheader()
        for status, count in summary.items():
            writer.writerow({"context_status": status, "row_count": count})
    manifest = {
        "source_name": SHORT_CONTEXT_SOURCE_NAME,
        "source_version": SHORT_CONTEXT_VERSION,
        "fib_trading_horizon": SHORT_CONTEXT_HORIZON,
        "primary_interval": PRIMARY_INTERVAL,
        "supporting_interval": SUPPORTING_INTERVAL,
        "row_count": len(rows),
        "summary": summary,
        "rows_csv": str(rows_csv),
        "rows_jsonl": str(rows_jsonl),
        "coverage_csv": str(coverage_csv),
    }
    manifest_json.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "rows_csv": rows_csv,
        "rows_jsonl": rows_jsonl,
        "coverage_csv": coverage_csv,
        "manifest_json": manifest_json,
    }


def load_native_short_context_rows(path: Path) -> tuple[dict[str, NativeShortContextRow], bool]:
    if not path.exists():
        return {}, True
    rows: dict[str, NativeShortContextRow] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            symbol = str(raw.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            active_targets = tuple(
                parsed
                for parsed in (_parse_decimal(value) for value in json.loads(raw.get("active_target_levels_json") or "[]"))
                if parsed is not None
            )
            previous_targets = tuple(
                parsed
                for parsed in (_parse_decimal(value) for value in json.loads(raw.get("previous_target_levels_json") or "[]"))
                if parsed is not None
            )
            rows[symbol] = NativeShortContextRow(
                symbol=symbol,
                venue=str(raw.get("venue") or ""),
                quote_currency=str(raw.get("quote_currency") or DEFAULT_QUOTE),
                fib_trading_horizon=str(raw.get("fib_trading_horizon") or SHORT_CONTEXT_HORIZON),
                primary_interval=str(raw.get("primary_interval") or PRIMARY_INTERVAL),
                supporting_interval=str(raw.get("supporting_interval") or SUPPORTING_INTERVAL),
                context_status=str(raw.get("context_status") or STATUS_SYMBOL_MISSING),
                map_cycle_id=str(raw.get("map_cycle_id") or ""),
                anchor_start_ts_utc=_parse_iso(raw.get("anchor_start_ts_utc")),
                anchor_end_ts_utc=_parse_iso(raw.get("anchor_end_ts_utc")),
                anchor_low_price=_parse_decimal(raw.get("anchor_low_price")),
                anchor_high_price=_parse_decimal(raw.get("anchor_high_price")),
                breakout_gate_price=_parse_decimal(raw.get("breakout_gate_price")),
                latest_primary_close_ts_utc=_parse_iso(raw.get("latest_primary_close_ts_utc")),
                latest_support_close_ts_utc=_parse_iso(raw.get("latest_support_close_ts_utc")),
                latest_primary_close_price=_parse_decimal(raw.get("latest_primary_close_price")),
                ext_1_272_price=_parse_decimal(raw.get("ext_1_272_price")),
                ext_1_618_price=_parse_decimal(raw.get("ext_1_618_price")),
                ext_2_000_price=_parse_decimal(raw.get("ext_2_000_price")),
                active_target_levels=active_targets,
                previous_target_levels=previous_targets,
                reload_r382_price=_parse_decimal(raw.get("reload_r382_price")),
                reload_r500_price=_parse_decimal(raw.get("reload_r500_price")),
                reload_r618_price=_parse_decimal(raw.get("reload_r618_price")),
                reload_r786_price=_parse_decimal(raw.get("reload_r786_price")),
                invalidation_price=_parse_decimal(raw.get("invalidation_price")),
                primary_4h_lifecycle_state=str(raw.get("primary_4h_lifecycle_state") or "UNKNOWN"),
                supporting_1h_state=str(raw.get("supporting_1h_state") or SUPPORT_STATE_UNKNOWN),
                context_freshness_status=str(raw.get("context_freshness_status") or FRESHNESS_FRESH),
                max_primary_high_since_anchor=_parse_decimal(raw.get("max_primary_high_since_anchor")),
                min_primary_low_since_anchor=_parse_decimal(raw.get("min_primary_low_since_anchor")),
                source_name=str(raw.get("source_name") or SHORT_CONTEXT_SOURCE_NAME),
                source_version=str(raw.get("source_version") or SHORT_CONTEXT_VERSION),
                source_primary_ref=str(raw.get("source_primary_ref") or "obs_market_candle:4h"),
                source_support_ref=str(raw.get("source_support_ref") or "obs_market_candle:1h"),
            )
    return rows, False
