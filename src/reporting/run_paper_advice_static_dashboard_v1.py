from __future__ import annotations

import argparse
import csv
import html
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.market_data.market_price_snapshot_v1 import (
    MarketPriceSnapshot,
    fetch_latest_prices_by_symbol,
)
from src.reporting.current_price_snapshot_v1 import classify_current_price_snapshot
from src.reporting.badge_html_v1 import badge_html as shared_badge_html
from src.reporting.dashboard_style_v1 import (
    DEFAULT_NAV_ACCOUNT_PROFILE,
    cockpit_base_css,
    cockpit_nav,
    pill_classes,
    synth_favicon_head_html,
)
from src.reporting.dashboard_time_v1 import format_ui_timestamp
from src.reporting.entry_zone_state_v1 import (
    classify_entry_zone_state,
    classify_price_progress_state,
    classify_target_state,
    confirmation_display_state,
    promotion_blockers,
    semantic_advice_action_display,
    semantic_entry_display_state,
)
from src.reporting.fast_lifecycle_recompute_v1 import classify_fast_lifecycle
from src.reporting.intrabar_lifecycle_context_v1 import (
    build_intrabar_lifecycle_context_rows,
    rows_by_symbol as intrabar_rows_by_symbol,
)
from src.reporting.label_registry_v1 import get_label_human_label
from src.reporting.market_breath_context_bridge_v1 import (
    build_market_breath_context_rows,
    rows_by_symbol as market_breath_rows_by_symbol,
)
from src.reporting.next_zone_preview_v1 import (
    NextZonePreview,
    format_zone,
    preview_next_zones,
)
from src.reporting.policy_block_reason_display_v1 import (
    block_reason_summary_text,
    classify_policy_block_display,
)
from src.reporting.paper_advice_severity_calibration_v1 import (
    calibrate_paper_advice_severity,
)


POLICY_NAME = "paper_advice_static_dashboard_v1"
POLICY_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "data/reporting/paper_advice_dashboard_v1.html"
DEFAULT_FIB_MAP_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")

ADVICE_ORDER = {
    "WATCH_CORE": 1,
    "WATCH": 2,
    "BLOCK_24H": 3,
    "CORE_CONTEXT": 4,
    "WAIT": 5,
    "NO_NEW_BUY": 6,
    "AVOID": 7,
}

FRESH_MAP_THRESHOLD = timedelta(hours=6)

CONSTRUCTIVE_MARKET_BREATH_CONTEXTS = {
    "MARKET_BREATH_EXPANSION_CONTEXT",
    "MARKET_BREATH_ACCUMULATION_CONTEXT",
}

NEUTRAL_MARKET_BREATH_CONTEXTS = {
    "MARKET_BREATH_NEUTRAL_CONTEXT",
    "MARKET_BREATH_COMPRESSION_CONTEXT",
}

TRIM_REVIEW_STATES = {
    "TARGET_REACHED",
    "TARGET_REACHED_STALE",
    "TARGET_OVERSHOT",
    "DOWNSIDE_TARGET_REACHED",
}


@dataclass(frozen=True)
class ManualSupportContext:
    manual_action_label: str
    direction_label: str
    strategy_family: str
    horizon_bucket: str
    why_lines: tuple[str, ...]
    strongest_reasons: tuple[str, ...]
    invalidation_line: str
    target_line_html: str
    trim_reload_hint: str
    fib_context_html: str
    freshness_line: str
    source_modules: tuple[str, ...]
    missing_lines: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render latest paper advice observation rows to a static read-only HTML dashboard."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lifecycle-candle-interval", default="1h")
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--title", default="Synth Paper Advice")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def get_connection() -> pymysql.connections.Connection:
    load_dotenv(dotenv_path=Path(".env"))

    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME", "synth"),
        cursorclass=pymysql.cursors.DictCursor,
    )


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fmt_decimal(value: Any, places: int | None = None) -> str:
    dec = to_decimal(value)
    if dec is None:
        return "—"

    if places is not None:
        quant = Decimal("1." + ("0" * places))
        dec = dec.quantize(quant)

    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text


def fmt_snapshot_price(value: Any) -> str:
    dec = to_decimal(value)
    if dec is None:
        return ""
    try:
        return str(dec.quantize(Decimal("0.000000")))
    except Exception:
        return format(dec, "f")


def price_age_min(snapshot: MarketPriceSnapshot | None, *, now_utc: datetime) -> Decimal | None:
    if snapshot is None:
        return None
    age_seconds = Decimal(str((now_utc.replace(tzinfo=None) - snapshot.observed_ts_utc).total_seconds()))
    return age_seconds / Decimal("60")


def apply_current_price_snapshot(
    row: dict[str, Any],
    snapshot: MarketPriceSnapshot | None,
    *,
    now_utc: datetime,
) -> None:
    display = classify_current_price_snapshot(snapshot, now_utc=now_utc)
    row["current_price_status"] = display.status
    row["price_age_min"] = display.age_min
    row["current_price"] = display.safe_price


def fmt_score(value: Any) -> str:
    dec = to_decimal(value)
    if dec is None:
        return "—"
    return f"{(dec * Decimal('100')).quantize(Decimal('0.1'))}%"


def fmt_range(low: Any, high: Any) -> str:
    left = fmt_decimal(low)
    right = fmt_decimal(high)

    if left == "—" and right == "—":
        return "—"
    if left == right:
        return left
    return f"{left} → {right}"


def esc(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return html.escape(value.isoformat(sep=" ", timespec="seconds"))
    return html.escape(str(value))


def load_fib_target_map_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    rows_by_symbol: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            rows_by_symbol[symbol] = row
    return rows_by_symbol


def attach_fib_map_context(row: dict[str, Any], fib_row: dict[str, Any] | None) -> None:
    if not fib_row:
        row["fib_map_lookup_status"] = "UNKNOWN"
        return

    row["fib_map_lookup_status"] = "FOUND"
    for key, value in fib_row.items():
        row[f"fib_map_{key}"] = value


def fmt_percent_text(value: Any, *, places: int = 1) -> str:
    dec = to_decimal(value)
    if dec is None:
        return "—"
    return f"{fmt_decimal(dec, places=places)}%"


def badge_html(label: Any, css_name: str | None = None, text: Any | None = None) -> str:
    return shared_badge_html(
        label,
        css_name=css_name or css_class("" if label is None else str(label)),
        text=text,
    )


def badge_text_html(label: str) -> str:
    return badge_html(label, css_name=css_class(label), text=get_label_human_label(label))


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nat"}:
        return None

    text = text.replace("T", " ").removesuffix("Z")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def is_recent_ts(value: Any, *, now_utc: datetime) -> bool:
    ts = parse_ts(value)
    if ts is None:
        return False
    age = now_utc.replace(tzinfo=None) - ts
    return timedelta(0) <= age <= FRESH_MAP_THRESHOLD


def fmt_ts(value: Any) -> str:
    parsed = parse_ts(value)
    if parsed is None:
        return "not available"
    return parsed.isoformat(sep=" ", timespec="seconds")


def fmt_ts_local(value: Any, timezone: str = "Europe/Amsterdam") -> str:
    parsed = parse_ts(value)
    return format_ui_timestamp(parsed, timezone=timezone)


def fmt_ts_local_first(value: Any, timezone: str = "Europe/Amsterdam") -> str:
    parsed = parse_ts(value)
    return fmt_ts_local(parsed, timezone=timezone)


def latest_lifecycle_candle_ts(rows: list[dict[str, Any]]) -> datetime | None:
    timestamps = [ts for ts in (parse_ts(row.get("latest_close_ts_utc")) for row in rows) if ts is not None]
    if not timestamps:
        return None
    return max(timestamps)


def selected_asof_bounds(rows: list[dict[str, Any]]) -> tuple[datetime | None, datetime | None]:
    timestamps = [ts for ts in (parse_ts(row.get("asof_ts_utc")) for row in rows) if ts is not None]
    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)


def advice_state_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("advice_state") or "UNKNOWN")
        counts[state] = counts.get(state, 0) + 1
    return [
        {"advice_state": state, "n": count}
        for state, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def css_class(value: str | None) -> str:
    if not value:
        return "muted"

    normalized = value.upper()

    mapping = {
        "WATCH_CORE": "good",
        "WATCH": "watch",
        "BLOCK_24H": "block",
        "CORE_CONTEXT": "context",
        "WAIT": "wait",
        "NO_NEW_BUY": "danger",
        "AVOID": "danger",
        "HIGH": "danger",
        "ELEVATED": "block",
        "MODERATE": "watch",
        "UNKNOWN": "muted",
        "UP": "good",
        "DOWN": "danger",
        "PASS": "good",
        "FAIL": "muted",
        "BLOCK_FOR_24H": "block",
        "INSUFFICIENT_SAMPLE": "muted",
        "MARKET_DAMAGE_RISK": "block",
        "MARKET_DAMAGE_CAUTION": "watch",
        "ENTRY_ZONE_REACHED": "watch",
        "ENTRY_ZONE_NEAR": "watch",
        "REACTION_ZONE_REACHED": "watch",
        "REACTION_ZONE_NEAR": "watch",
        "IN_ENTRY_ZONE": "watch",
        "IN_REACTION_ZONE": "watch",
        "CONFIRMATION_PENDING": "watch",
        "POST_ENTRY_PROGRESS": "watch",
        "TARGET_APPROACHING": "watch",
        "TARGET_NEAR": "watch",
        "ENTRY_WINDOW_PASSED": "watch",
        "CHASE_RISK": "watch",
        "LATE_ENTRY_REVIEW": "watch",
        "REACTION_PROGRESS": "watch",
        "DOWNSIDE_TARGET_APPROACHING": "watch",
        "DOWNSIDE_TARGET_NEAR": "watch",
        "PAPER_BUY_READY": "good",
        "TARGET_PENDING": "muted",
        "TARGET_REACHED": "watch",
        "DOWNSIDE_TARGET_REACHED": "watch",
        "TARGET_REACHED_STALE": "watch",
        "TARGET_OVERSHOT": "watch",
        "RECLAIM_NEAR": "watch",
        "RECLAIM_CONFIRMED": "watch",
        "INVALIDATION_TOUCHED": "danger",
        "MAP_RECOMPUTE_NEEDED": "danger",
        "DOWN_MAP_INVALIDATED_BY_RECLAIM": "danger",
        "UP_MAP_INVALIDATED_BY_BREAKDOWN": "danger",
        "RECLAIM_NEXT_ZONE_PREVIEW": "danger",
        "BREAKDOWN_NEXT_ZONE_PREVIEW": "danger",
        "NEXT_ZONE_UNKNOWN": "danger",
        "UPSIDE_EXTENSION_PREVIEW": "watch",
        "DOWNSIDE_EXTENSION_PREVIEW": "watch",
        "RECLAIM_RETEST_SUPPORT": "watch",
        "NEXT_UPSIDE_REACTION_TARGET": "watch",
        "TARGET_RETEST_SUPPORT": "watch",
        "NEXT_UPSIDE_EXTENSION": "watch",
        "DOWNSIDE_TARGET_SUPPORT_RETEST": "watch",
        "NEXT_DOWNSIDE_EXTENSION": "watch",
        "BREAKDOWN_RETEST_RESISTANCE": "watch",
        "NEXT_DOWNSIDE_REACTION_TARGET": "watch",
        "CURRENT_MAP_ACTIVE": "good",
        "BTC_PRIOR_OVERHEAT_ZONE": "block",
        "SELECTION_STATE_NOT_ELIGIBLE": "muted",
        "RANK_OUTSIDE_SETUP_ELIGIBLE_RANGE": "muted",
        "PRIORITY_RANK_MISSING": "muted",
        "BTC_PRIOR_24H_MISSING": "muted",
        "ASSET_SUITABILITY_WEAK_SET_CANDIDATE": "muted",
        "MARKET_BREATH_EXPANSION_CONTEXT": "good",
        "MARKET_BREATH_ACCUMULATION_CONTEXT": "watch",
        "MARKET_BREATH_LATE_RISK_CONTEXT": "block",
        "MARKET_BREATH_RESET_CONTEXT": "danger",
        "MARKET_BREATH_NEUTRAL_CONTEXT": "muted",
        "MARKET_BREATH_COMPRESSION_CONTEXT": "watch",
        "MARKET_BREATH_UNKNOWN": "muted",
        "FRESH": "good",
        "AGING": "watch",
        "STALE": "block",
        "VERY_STALE": "danger",
        "LEGACY_CONTEXT_ONLY": "muted",
        "READ_ONLY_APLUS_AVOID_CONTEXT": "muted",
        "BLOCK_MARKET_DAMAGE": "watch",
        "BLOCK_SETUP_FILTER_FAIL": "watch",
        "BLOCK_RECOMPUTE_PENDING": "watch",
        "BLOCK_CHASE_RISK": "watch",
        "BLOCK_INSUFFICIENT_SAMPLE": "muted",
        "BLOCK_SELECTION_NOT_ELIGIBLE": "muted",
        "BLOCK_POLICY_UNCLASSIFIED": "watch",
        "READ_ONLY_APLUS_AVOID": "block",
        "HARD_BLOCK": "danger",
        "SOFT_BLOCK": "block",
        "BUY_REVIEW": "good",
        "RELOAD_REVIEW": "watch",
        "TRIM_REVIEW": "watch",
        "INVALIDATED": "danger",
        "BULLISH_SHORT_TERM": "good",
        "BULLISH_MEDIUM_TERM": "context",
        "NEUTRAL_WAIT": "wait",
        "BEARISH_RISK": "danger",
        "TRIM_CANDIDATE": "watch",
        "RELOAD_CANDIDATE": "watch",
        "MISSING_ZONE_MAP": "danger",
        "MISSING_CURRENT_PRICE": "danger",
        "MISSING_INVALIDATION": "watch",
        "MISSING_MARKET_BREATH_CONTEXT": "watch",
        "MISSING_INTRABAR_CONTEXT": "muted",
        "FIBO_ZONE_RECLAIM_V1": "context",
        "REGIME_CONTEXT_V1": "context",
        "BREATHLINE_CONTEXT_V1": "watch",
        "ROTATION_REVIEW_V1": "watch",
        "UNKNOWN_STRATEGY_CONTEXT": "muted",
        "SHORT_TERM_SPIKE": "watch",
        "MEDIUM_TERM_SWING": "context",
        "LONG_TERM_CYCLE": "good",
        "UNKNOWN_HORIZON": "muted",
        "OPPORTUNITY_REVIEW": "watch",
        "MOMENTUM_EXTENSION_REVIEW": "watch",
        "RECLAIM_REVIEW": "watch",
        "WAIT_FOR_RECLAIM": "watch",
        "WAIT_FOR_PULLBACK": "watch",
        "CONTEXT_ONLY": "context",
        "STALE_APLUS_CONTEXT": "muted",
        "REFRESH_NEEDED_REVIEW": "watch",
        "NO_CHASE_WITHOUT_NEW_ZONE": "block",
        "TARGET_REACHED_WAIT_FOR_REMAP": "watch",
        "EXTENSION_REVIEW_NO_CHASE": "watch",
        "WAIT_FOR_NEW_MAP": "watch",
        "CURRENT_CAUTION_CONTEXT": "block",
        "ACTIVE_REVIEW_CONTEXT": "context",
        "SETUP_CONTEXT_ONLY": "muted",
        "INTRABAR_ACTIVE": "good",
        "INTRABAR_TARGET_TOUCHED": "watch",
        "INTRABAR_TARGET_OVERSHOT": "block",
        "INTRABAR_RECLAIM_TOUCHED": "watch",
        "INTRABAR_RECLAIM_CONFIRMED": "block",
        "INTRABAR_INVALIDATION_TOUCHED": "danger",
        "INTRABAR_EXTENSION_CONTINUING": "watch",
        "INTRABAR_RETESTING_NEW_ZONE": "watch",
        "INTRABAR_UNKNOWN": "muted",
        "INTRABAR_RECOMPUTE_REVIEW": "block",
        "INTRABAR_MONITOR_RECOMPUTE": "watch",
        "NO_INTRABAR_RECOMPUTE_HINT": "muted",
        "NO_STRUCTURAL_MAP": "danger",
        "PRICE_SNAPSHOT_FRESH": "good",
        "PRICE_SNAPSHOT_STALE": "block",
        "LTF_CANDLES_FRESH": "good",
        "LTF_CANDLES_STALE": "block",
        "LTF_HISTORY_SHORT": "block",
        "LTF_MISSING": "danger",
        "STRUCTURAL_MAP_MISSING": "danger",
    }

    return pill_classes(mapping.get(normalized, "muted"), normalized)


def zone_labels(leg_direction: str | None) -> tuple[str, str, str]:
    normalized = (leg_direction or "").strip().upper()
    if normalized == "UP":
        return ("Entry zone", "Upside TP zone", "Invalidation below")
    if normalized == "DOWN":
        return ("Reaction zone", "Downside entry zone", "Invalidation above reaction zone")
    return ("Zone", "Target zone", "Invalidation")


def zone_display_cells(row: dict[str, Any]) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    leg_direction = str(row.get("leg_direction") or "").strip().upper()
    zone_label, target_label, invalidation_label = zone_labels(leg_direction)
    reaction_zone = fmt_range(row.get("entry_zone_low"), row.get("entry_zone_high"))
    target_zone = fmt_range(row.get("tp_zone_low"), row.get("tp_zone_high"))
    invalidation = fmt_decimal(row.get("invalidation_price"))

    if leg_direction == "DOWN":
        return (
            (zone_label, reaction_zone),
            (invalidation_label, invalidation),
            (target_label, target_zone),
        )

    return (
        (zone_label, reaction_zone),
        (target_label, target_zone),
        (invalidation_label, invalidation),
    )


def next_zone_html(preview: NextZonePreview) -> str:
    parts = [
        badge_html(preview.next_zone_state)
    ]
    if preview.next_reaction_zone_label and preview.next_reaction_zone:
        parts.append(
            '<div class="small">'
            f'{badge_html(preview.next_reaction_zone_label)} '
            f'<span class="zone-value">{esc(format_zone(preview.next_reaction_zone))}</span>'
            "</div>"
        )
    if preview.next_target_zone_label and preview.next_target_zone:
        parts.append(
            '<div class="small">'
            f'{badge_html(preview.next_target_zone_label)} '
            f'<span class="zone-value">{esc(format_zone(preview.next_target_zone))}</span>'
            "</div>"
        )
    if preview.next_zone_reason:
        parts.append(f'<div class="muted small">{esc(preview.next_zone_reason)}</div>')
    if preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}:
        parts.append('<div class="muted small">Market context, not permission.</div>')
    return "".join(parts)


def _target_midpoint(low: Any, high: Any) -> Decimal | None:
    low_dec = to_decimal(low)
    high_dec = to_decimal(high)
    if low_dec is not None and high_dec is not None:
        return (low_dec + high_dec) / Decimal("2")
    return low_dec if low_dec is not None else high_dec


def _target_distance_text(target_mid: Decimal | None, current_price: Any) -> str:
    price = to_decimal(current_price)
    if target_mid is None or price is None or price <= 0:
        return ""
    delta = ((target_mid / price) - Decimal("1")) * Decimal("100")
    return f"{delta.quantize(Decimal('0.1'))}%"


def relevant_target_html(row: dict[str, Any], preview: NextZonePreview) -> str:
    if preview.next_target_zone_label and preview.next_target_zone:
        zone_text = format_zone(preview.next_target_zone)
        target_mid = (preview.next_target_zone[0] + preview.next_target_zone[1]) / Decimal("2")
        label = preview.next_target_zone_label
    else:
        leg_direction = str(row.get("leg_direction") or "").strip().upper()
        _, target_label, _ = zone_labels(leg_direction)
        zone_text = fmt_range(row.get("tp_zone_low"), row.get("tp_zone_high"))
        if zone_text == "—":
            return '<span class="muted">—</span>'
        label = target_label
        target_mid = _target_midpoint(row.get("tp_zone_low"), row.get("tp_zone_high"))

    distance = _target_distance_text(target_mid, row.get("current_price"))
    distance_html = "" if not distance else f'<div class="muted small">distance: {esc(distance)}</div>'
    return (
        f'<div>{badge_html(label)}</div>'
        f'<div class="zone-value">{esc(zone_text)}</div>'
        f"{distance_html}"
    )


def market_breath_context_html(row: dict[str, Any] | None) -> str:
    if not row:
        return '<span class="muted small">not available</span>'

    phase = str(row.get("market_breath_phase") or "UNKNOWN")
    state = str(row.get("market_breath_state") or "UNKNOWN")
    context_state = str(row.get("market_breath_context_state") or "MARKET_BREATH_UNKNOWN")
    freshness = str(row.get("aplus_legacy_freshness_state") or "UNKNOWN")
    bias = str(row.get("aplus_table1_strategic_bias") or "").upper()
    bias_label = f"APLUS_{bias}" if bias else "APLUS_UNKNOWN"
    age = fmt_decimal(row.get("aplus_table1_age_hours"), places=1)
    suggested_context = f"{freshness}_{bias_label} + {context_state}"

    return (
        f'<div>{badge_html(phase)} {badge_html(state)}</div>'
        f'<div class="small">{badge_html(context_state)}</div>'
        f'<div class="muted small">A+ legacy age: <span class="mono">{esc(age)}</span>h '
        f'{badge_html(freshness)}</div>'
        f'<div class="muted small">{esc(suggested_context)}</div>'
    )


def advice_severity_html(severity: Any) -> str:
    policy_block = getattr(severity, "policy_block", None)
    policy_html = ""
    if policy_block is not None:
        policy_html = (
            f'<div>{badge_html(policy_block.display_policy_label)}</div>'
            f'<div class="muted small">Cause: {esc(policy_block.block_primary_reason)}</div>'
            f'<div class="muted small">Unblock: {esc(policy_block.unblock_condition_label)}</div>'
        )
    return (
        f'<div>{badge_html(severity.advice_severity)}</div>'
        f'<div>{badge_html(severity.advice_substate)}</div>'
        f"{policy_html}"
        f'<div class="muted small">{esc(severity.display_note)}</div>'
    )


def intrabar_context_html(row: Any | None) -> str:
    if not row:
        return '<span class="muted small">not available</span>'
    quality_labels = "".join(
        badge_html(part)
        for part in str(row.data_quality_state or "").split(";")
        if part
    )
    return (
        f'<div>{badge_html(row.intrabar_lifecycle_state)}</div>'
        f'<div>{badge_html(row.intrabar_recompute_hint)}</div>'
        f'<div class="muted small">source={esc(row.price_source)} · 15m={esc(row.latest_15m_close_ts_utc or "missing")}</div>'
        f'<div class="badge-row">{quality_labels}</div>'
        '<div class="muted small">Intrabar context, not trade advice.</div>'
    )


def bool_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "YES" if value else "NO"
    text = str(value).strip().upper()
    if text in {"1", "TRUE", "YES", "Y", "ALLOW", "ALLOWED"}:
        return "YES"
    if text in {"0", "FALSE", "NO", "N"}:
        return "NO"
    return text


def market_breath_context_code(row: dict[str, Any] | None) -> str:
    return str((row or {}).get("market_breath_context_state") or "").strip().upper()


def normalized_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            parts.extend(normalized_blob(k, v) for k, v in value.items())
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(normalized_blob(item) for item in value)
            continue
        parts.append(str(value).strip().upper())
    return " ".join(part for part in parts if part)


def has_zone_map(row: dict[str, Any]) -> bool:
    return any(
        to_decimal(row.get(field)) is not None
        for field in (
            "entry_zone_low",
            "entry_zone_high",
            "tp_zone_low",
            "tp_zone_high",
            "invalidation_price",
        )
    )


def infer_strategy_family(
    row: dict[str, Any],
    *,
    lifecycle: Any,
    next_preview: NextZonePreview,
    market_breath_row: dict[str, Any] | None,
) -> str:
    source_blob = normalized_blob(
        row.get("source_ref_json"),
        row.get("reason_codes_json"),
        row.get("setup_filter_reason"),
        row.get("policy_decision"),
        row.get("suggested_horizon"),
    )
    next_zone_state = str(next_preview.next_zone_state or "").strip().upper()
    lifecycle_state = str(lifecycle.lifecycle_state or "").strip().upper()
    zone_reclaim_context = has_zone_map(row) and (
        next_zone_state in {
            "RECLAIM_NEXT_ZONE_PREVIEW",
            "RECLAIM_RETEST_SUPPORT",
            "BREAKDOWN_RETEST_RESISTANCE",
        }
        or lifecycle_state in {"RECLAIM_NEAR", "RECLAIM_CONFIRMED"}
        or str(row.get("leg_direction") or "").strip().upper() in {"UP", "DOWN"}
    )

    if "ROTATION" in source_blob:
        return "ROTATION_REVIEW_V1"
    if "BREATHLINE" in source_blob:
        return "BREATHLINE_CONTEXT_V1"
    if zone_reclaim_context:
        return "FIBO_ZONE_RECLAIM_V1"
    if market_breath_row is not None:
        return "REGIME_CONTEXT_V1"
    return "UNKNOWN_STRATEGY_CONTEXT"


def infer_horizon_bucket(
    row: dict[str, Any],
    *,
    lifecycle: Any,
    next_preview: NextZonePreview,
    intrabar_row: Any | None,
) -> str:
    suggested_horizon = str(row.get("suggested_horizon") or "").strip().upper()
    policy_decision = str(row.get("policy_decision") or "").strip().upper()
    intrabar_state = "" if intrabar_row is None else str(intrabar_row.intrabar_lifecycle_state or "").strip().upper()
    next_zone_state = str(next_preview.next_zone_state or "").strip().upper()
    lifecycle_state = str(lifecycle.lifecycle_state or "").strip().upper()

    if "LONG" in suggested_horizon or policy_decision == "LONG_HORIZON_ONLY":
        return "LONG_TERM_CYCLE"
    if intrabar_state in {
        "INTRABAR_TARGET_OVERSHOT",
        "INTRABAR_EXTENSION_CONTINUING",
        "INTRABAR_TARGET_TOUCHED",
    }:
        return "SHORT_TERM_SPIKE"
    if (
        has_zone_map(row)
        and (
            next_zone_state in {
                "RECLAIM_NEXT_ZONE_PREVIEW",
                "RECLAIM_RETEST_SUPPORT",
                "BREAKDOWN_RETEST_RESISTANCE",
            }
            or lifecycle_state in {"RECLAIM_NEAR", "RECLAIM_CONFIRMED"}
            or str(row.get("leg_direction") or "").strip().upper() in {"UP", "DOWN"}
        )
    ):
        return "MEDIUM_TERM_SWING"
    return "UNKNOWN_HORIZON"


def infer_source_modules(
    row: dict[str, Any],
    *,
    current_price: Any,
    market_breath_row: dict[str, Any] | None,
    intrabar_row: Any | None,
) -> tuple[str, ...]:
    modules: list[str] = ["paper_advice_observation", "paper_advice_policy_v1"]
    if row.get("selection_state") is not None or row.get("setup_filter_state") is not None:
        modules.append("trade_setup_filter_observation")
    if has_zone_map(row):
        modules.append("execution_zone_context")
    if to_decimal(current_price) is not None:
        modules.append("market_price_snapshot_v1")
    if market_breath_row is not None:
        modules.append("market_breath_context_bridge_v1")
    if intrabar_row is not None:
        modules.append("intrabar_lifecycle_context_v1")
    if row.get("aplus_bucket") is not None:
        modules.append("aplus_table1_row")
    if str(row.get("fib_map_lookup_status") or "").strip().upper() == "FOUND":
        modules.append("fibo_target_map_v1")
    return tuple(dict.fromkeys(modules))


def manual_missing_lines(
    row: dict[str, Any],
    *,
    market_breath_row: dict[str, Any] | None,
    intrabar_row: Any | None,
    current_price: Any,
) -> tuple[str, ...]:
    missing: list[str] = []
    if to_decimal(current_price) is None:
        missing.append("MISSING_CURRENT_PRICE")
    if (
        to_decimal(row.get("entry_zone_low")) is None
        and to_decimal(row.get("entry_zone_high")) is None
        and to_decimal(row.get("tp_zone_low")) is None
        and to_decimal(row.get("tp_zone_high")) is None
    ):
        missing.append("MISSING_ZONE_MAP")
    if to_decimal(row.get("invalidation_price")) is None:
        missing.append("MISSING_INVALIDATION")
    if market_breath_row is None:
        missing.append("MISSING_MARKET_BREATH_CONTEXT")
    if intrabar_row is None:
        missing.append("MISSING_INTRABAR_CONTEXT")
    if str(row.get("fib_map_lookup_status") or "").strip().upper() != "FOUND":
        missing.append("FIB_MAP_UNKNOWN")
    return tuple(missing)


def fib_context_html(
    row: dict[str, Any],
    *,
    current_price: Any,
    next_preview: NextZonePreview,
    entry_blocked: bool,
    selection_state: str,
    setup_state: str,
    policy_decision: str,
    advice_action: str,
    allowed_now: str,
) -> str:
    fib_status = str(row.get("fib_map_lookup_status") or "UNKNOWN").strip().upper()
    invalidation_text = fmt_snapshot_price(row.get("invalidation_price"))
    fallback_target_mid = _target_midpoint(row.get("tp_zone_low"), row.get("tp_zone_high"))
    fallback_target_price = fmt_snapshot_price(fallback_target_mid)
    fallback_target_distance = _target_distance_text(fallback_target_mid, current_price)
    block_reasons = [
        f"selection_state={selection_state or 'UNKNOWN'}",
        f"setup_filter_state={setup_state or 'UNKNOWN'}",
        f"policy/action={(policy_decision or 'UNKNOWN')}/{(advice_action or 'UNKNOWN')}",
        f"edge_permission={allowed_now or 'UNKNOWN'}",
    ]
    block_html = ""
    if entry_blocked:
        block_html = (
            "<div class='small'><strong>entry_block</strong>: Map target visible, entry blocked.</div>"
            f"<div class='muted small'>{esc(' · '.join(block_reasons))}</div>"
        )

    if fib_status != "FOUND":
        return (
            "<div class='small'><strong>fib_map_state</strong>: <span class='pill'>FIB_MAP_UNKNOWN</span></div>"
            f"<div class='small'><strong>current_price</strong>: <span class='mono'>{esc(fmt_snapshot_price(current_price))}</span></div>"
            f"<div class='small'><strong>current mapped target</strong>: MAP_TARGET @ <span class='mono'>{esc(fallback_target_price)}</span> · distance={esc(fallback_target_distance or '—')}</div>"
            f"<div class='muted small'>{relevant_target_html(row, next_preview)}</div>"
            f"<div class='small'><strong>invalidation</strong>: <span class='mono'>{esc(invalidation_text)}</span></div>"
            f"{block_html}"
            "<div class='muted small'>No fib target map row was found for this symbol in data/research/fibo_target_map_v1.</div>"
        )

    current_price_text = fmt_snapshot_price(current_price)
    interval = str(row.get("fib_map_interval") or "unknown")
    target_status = str(row.get("fib_map_target_status") or "UNKNOWN")
    anchor_quality = str(row.get("fib_map_anchor_quality") or "UNKNOWN")
    anchor_end = fmt_ts_local_first(row.get("fib_map_anchor_end_ts"))
    bars_since_anchor = fmt_decimal(row.get("fib_map_bars_since_anchor_end"))
    reaction_text = fmt_snapshot_price(row.get("fib_map_local_reaction_price"))
    support_level = str(row.get("fib_map_next_fibo_support_level") or "UNKNOWN")
    support_price = fmt_snapshot_price(row.get("fib_map_next_fibo_support_price"))
    support_distance = fmt_percent_text(row.get("fib_map_distance_to_next_fibo_support_pct"))
    target_level = str(row.get("fib_map_next_extension_target_level") or "UNKNOWN")
    target_price = fmt_snapshot_price(row.get("fib_map_next_extension_target_price"))
    target_distance = fmt_percent_text(row.get("fib_map_distance_to_next_extension_pct"))
    main_level = str(row.get("fib_map_main_extension_target_level") or "UNKNOWN")
    main_price = fmt_snapshot_price(row.get("fib_map_main_extension_target_price"))
    reentry_label = str(row.get("fib_map_reentry_zone_label") or "UNKNOWN")

    return (
        f"<div class='small'><strong>fib_map_state</strong>: {esc(target_status)} · interval={esc(interval)} · anchor_quality={esc(anchor_quality)}</div>"
        f"<div class='small'><strong>current price</strong>: <span class='mono'>{esc(current_price_text)}</span></div>"
        f"<div class='small'><strong>invalidation</strong>: <span class='mono'>{esc(invalidation_text)}</span></div>"
        f"<div class='small'><strong>support/retest zone</strong>: {esc(support_level)} @ <span class='mono'>{esc(support_price)}</span> · distance={esc(support_distance)} · reload={esc(reentry_label)}</div>"
        f"<div class='small'><strong>next reaction zone</strong>: local_reaction @ <span class='mono'>{esc(reaction_text)}</span></div>"
        f"<div class='small'><strong>upside map target</strong>: {esc(target_level)} @ <span class='mono'>{esc(target_price)}</span> · target distance={esc(target_distance)}</div>"
        f"<div class='small'><strong>main bull target</strong>: {esc(main_level)} @ <span class='mono'>{esc(main_price)}</span></div>"
        f"{block_html}"
        f"<div class='muted small'><strong>map freshness</strong>: anchor_end={esc(anchor_end)} · bars_since_anchor_end={esc(bars_since_anchor)}</div>"
    )


def manual_support_context(
    row: dict[str, Any],
    *,
    current_price: Any,
    entry_state: str,
    target_state: str,
    price_progress_state: str,
    lifecycle: Any,
    next_preview: NextZonePreview,
    market_breath_row: dict[str, Any] | None,
    intrabar_row: Any | None,
    block_display: Any,
    action_label: str,
) -> ManualSupportContext:
    leg_direction = str(row.get("leg_direction") or "").strip().upper()
    setup_state = str(row.get("setup_filter_state") or "").strip().upper()
    setup_reason = str(row.get("setup_filter_reason") or "").strip().upper()
    selection_state = str(row.get("selection_state") or "").strip().upper()
    advice_state = str(row.get("advice_state") or "").strip().upper()
    advice_action = str(row.get("advice_action") or "").strip().upper()
    market_context = market_breath_context_code(market_breath_row)
    allowed_now = bool_text(row.get("allowed_now"))
    invalidated = lifecycle.recompute_needed or is_pullback_invalidated(row)
    target_reached = (
        target_state in TRIM_REVIEW_STATES
        or str(lifecycle.lifecycle_state or "").strip().upper() in TRIM_REVIEW_STATES
    )
    entry_ready = entry_state in {
        "ENTRY_ZONE_REACHED",
        "ENTRY_ZONE_NEAR",
        "REACTION_ZONE_REACHED",
        "REACTION_ZONE_NEAR",
    }
    constructive_market = market_context in CONSTRUCTIVE_MARKET_BREATH_CONTEXTS
    neutral_market = market_context in NEUTRAL_MARKET_BREATH_CONTEXTS

    if invalidated:
        manual_action = "INVALIDATED"
    elif target_reached:
        manual_action = "TRIM_REVIEW"
    elif (
        block_display is not None
        or advice_state in {"AVOID", "NO_NEW_BUY", "BLOCK_24H"}
        or advice_action in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY", "BLOCK_NEW_24H_ENTRY"}
        or selection_state == "AVOID"
        or setup_reason == "MARKET_DAMAGE_RISK"
    ):
        manual_action = "AVOID"
    elif (
        leg_direction == "UP"
        and advice_state == "PAPER_READY"
        and advice_action == "PAPER_TEST_ALLOWED"
        and setup_state == "PASS"
        and entry_ready
        and not invalidated
    ):
        manual_action = "BUY_REVIEW"
    elif (
        leg_direction == "UP"
        and entry_ready
        and setup_state == "PASS"
        and not invalidated
        and market_context in (CONSTRUCTIVE_MARKET_BREATH_CONTEXTS | NEUTRAL_MARKET_BREATH_CONTEXTS)
    ):
        manual_action = "RELOAD_REVIEW"
    elif setup_state == "PASS" and not invalidated and target_state == "TARGET_PENDING":
        manual_action = "HOLD"
    else:
        manual_action = "WAIT"

    if manual_action == "TRIM_REVIEW":
        direction = "TRIM_CANDIDATE"
    elif manual_action == "RELOAD_REVIEW":
        direction = "RELOAD_CANDIDATE"
    elif manual_action == "BUY_REVIEW":
        direction = "BULLISH_SHORT_TERM"
    elif manual_action in {"AVOID", "INVALIDATED"} or leg_direction == "DOWN":
        direction = "BEARISH_RISK"
    elif constructive_market:
        direction = "BULLISH_MEDIUM_TERM" if not entry_ready else "BULLISH_SHORT_TERM"
    else:
        direction = "NEUTRAL_WAIT"

    strategy_family = infer_strategy_family(
        row,
        lifecycle=lifecycle,
        next_preview=next_preview,
        market_breath_row=market_breath_row,
    )
    horizon_bucket = infer_horizon_bucket(
        row,
        lifecycle=lifecycle,
        next_preview=next_preview,
        intrabar_row=intrabar_row,
    )

    why_lines: list[str] = []
    if entry_ready:
        why_lines.append(
            f"Zone context: {get_label_human_label(entry_state)} around {fmt_range(row.get('entry_zone_low'), row.get('entry_zone_high'))}."
        )
    elif leg_direction:
        why_lines.append(
            f"Zone context: {leg_direction} leg with {get_label_human_label(action_label)} display."
        )

    if str(next_preview.next_zone_state or "").upper() in {
        "RECLAIM_NEXT_ZONE_PREVIEW",
        "RECLAIM_RETEST_SUPPORT",
        "BREAKDOWN_RETEST_RESISTANCE",
    }:
        why_lines.append(
            f"Reclaim/retest context: {get_label_human_label(str(next_preview.next_zone_state))}."
        )
    elif str(lifecycle.lifecycle_state or "").upper() in {"RECLAIM_NEAR", "RECLAIM_CONFIRMED"}:
        why_lines.append(
            f"Reclaim/retest context: {get_label_human_label(str(lifecycle.lifecycle_state))}."
        )

    if market_breath_row is None:
        why_lines.append("Market breath / context overlay: missing.")
    else:
        phase = str(market_breath_row.get("market_breath_phase") or "UNKNOWN")
        why_lines.append(
            f"Regime / breath context: {phase} -> {get_label_human_label(market_context or 'UNKNOWN')}."
        )

    if setup_state == "FAIL":
        why_lines.append(
            f"Setup fail reason: {get_label_human_label(setup_reason or 'SETUP_FAIL')}."
        )
    elif setup_state:
        why_lines.append(f"Setup state: {setup_state}.")

    if intrabar_row is None:
        why_lines.append("Fast lifecycle / intrabar context: missing.")
    else:
        why_lines.append(
            f"Fast lifecycle: {get_label_human_label(str(lifecycle.lifecycle_state or 'UNKNOWN'))}; intrabar: {get_label_human_label(str(intrabar_row.intrabar_lifecycle_state or 'UNKNOWN'))}."
        )

    invalidation_line = (
        f"{zone_labels(leg_direction)[2]}: {fmt_decimal(row.get('invalidation_price'))}"
        if to_decimal(row.get("invalidation_price")) is not None
        else "Invalidation / risk reason: missing."
    )
    if invalidated:
        invalidation_line = (
            f"Invalidation / risk reason: {get_label_human_label(str(lifecycle.lifecycle_state or 'INVALIDATED'))}; {lifecycle.recompute_reason or 'fresh map required'}."
        )
    elif block_display is not None:
        invalidation_line = (
            f"Invalidation / risk reason: {block_display.block_primary_reason}; unblock: {block_display.unblock_condition_label}."
        )

    target_line_html = (
        f"Target / reaction zone: {relevant_target_html(row, next_preview)}"
        if to_decimal(current_price) is not None
        else "Target / reaction zone: missing current price."
    )

    if manual_action == "TRIM_REVIEW":
        trim_reload_hint = "Trim / reload hint: trim candidate near mapped target or extension; do not chase a fresh add."
    elif manual_action in {"BUY_REVIEW", "RELOAD_REVIEW"}:
        trim_reload_hint = "Trim / reload hint: reload/buy review only if the reaction-entry context still holds on the chart."
    elif manual_action == "HOLD":
        trim_reload_hint = "Trim / reload hint: hold and monitor until target, invalidation, or a fresh remap changes context."
    else:
        trim_reload_hint = "Trim / reload hint: no trim/reload edge shown from current paper inputs."

    freshness_parts = [
        f"paper_asof={fmt_ts_local_first(row.get('asof_ts_utc'))}",
        f"price_age_min={fmt_decimal(row.get('price_age_min'), places=1)}",
    ]
    if allowed_now:
        freshness_parts.append(f"allowed_now={allowed_now}")
    if market_context:
        freshness_parts.append(f"market_context={market_context}")
    freshness_line = "Freshness: " + " · ".join(freshness_parts)
    source_modules = infer_source_modules(
        row,
        current_price=current_price,
        market_breath_row=market_breath_row,
        intrabar_row=intrabar_row,
    )
    strongest_reasons = tuple(why_lines[:4]) if why_lines else ("Current paper context only.",)
    entry_blocked = bool(
        block_display is not None
        or allowed_now == "NO"
        or selection_state == "AVOID"
        or setup_state == "FAIL"
        or advice_state in {"AVOID", "NO_NEW_BUY", "BLOCK_24H", "WAIT"}
    )
    fib_html = fib_context_html(
        row,
        current_price=current_price,
        next_preview=next_preview,
        entry_blocked=entry_blocked,
        selection_state=selection_state,
        setup_state=setup_state,
        policy_decision=str(row.get("policy_decision") or "").strip().upper(),
        advice_action=advice_action,
        allowed_now=allowed_now,
    )

    return ManualSupportContext(
        manual_action_label=manual_action,
        direction_label=direction,
        strategy_family=strategy_family,
        horizon_bucket=horizon_bucket,
        why_lines=tuple(why_lines),
        strongest_reasons=strongest_reasons,
        invalidation_line=invalidation_line,
        target_line_html=target_line_html,
        trim_reload_hint=trim_reload_hint,
        fib_context_html=fib_html,
        freshness_line=freshness_line,
        source_modules=source_modules,
        missing_lines=manual_missing_lines(
            row,
            market_breath_row=market_breath_row,
            intrabar_row=intrabar_row,
            current_price=current_price,
        ),
    )


def manual_support_html(context: ManualSupportContext) -> str:
    why_html = "".join(f"<div>{esc(line)}</div>" for line in context.why_lines)
    reason_html = "".join(f"<div>{esc(line)}</div>" for line in context.strongest_reasons)
    missing_html = "".join(
        badge_text_html(label) for label in context.missing_lines
    )
    missing_block = (
        "<span class='muted'>none</span>"
        if not missing_html
        else f"<div class='badge-row'>{missing_html}</div>"
    )
    source_modules_text = ", ".join(context.source_modules) if context.source_modules else "missing"
    return (
        f"<div class='badge-row'>{badge_text_html(context.manual_action_label)} {badge_text_html(context.direction_label)}</div>"
        f"<div class='small'><strong>strategy_family</strong>: {badge_text_html(context.strategy_family)}</div>"
        f"<div class='small'><strong>horizon_bucket</strong>: {badge_text_html(context.horizon_bucket)}</div>"
        f"<div class='small'><strong>paper_action</strong>: {badge_text_html(context.manual_action_label)}</div>"
        f"<div class='small'><strong>direction_label</strong>: {badge_text_html(context.direction_label)}</div>"
        f"<div class='small'><strong>strongest_reasons</strong>:{reason_html}</div>"
        f"<div class='muted small'><strong>risk/invalidation</strong>: {esc(context.invalidation_line)}</div>"
        f"<div class='small'><strong>target/reaction_zone</strong>: {context.target_line_html}</div>"
        f"<div class='small'><strong>fib_target_map</strong>: {context.fib_context_html}</div>"
        f"<div class='muted small'><strong>freshness</strong>: {esc(context.freshness_line)}</div>"
        f"<div class='muted small'><strong>source_modules</strong>: <span class='mono'>{esc(source_modules_text)}</span></div>"
        f"<div class='muted small'><strong>trim/reload_hint</strong>: {esc(context.trim_reload_hint)}</div>"
        f"<div class='small'><strong>why</strong>:{why_html}</div>"
        f"<div class='small'><strong>missing_inputs</strong>: {missing_block}</div>"
    )


def _range_bounds(low: Any, high: Any) -> tuple[Decimal | None, Decimal | None]:
    values = [value for value in (to_decimal(low), to_decimal(high)) if value is not None]
    if not values:
        return None, None
    return min(values), max(values)


def zone_lifecycle_start_ts(row: dict[str, Any]) -> datetime | None:
    raw_source_ref = row.get("source_ref_json")
    if raw_source_ref:
        try:
            payload = json.loads(str(raw_source_ref))
            if isinstance(payload, dict):
                zone_ts = parse_ts(payload.get("zone_asof_ts_utc"))
                if zone_ts is not None:
                    return zone_ts
        except json.JSONDecodeError:
            pass

    return parse_ts(row.get("context_ts_utc")) or parse_ts(row.get("asof_ts_utc"))


def is_pullback_invalidated(row: dict[str, Any]) -> bool:
    return bool(row.get("path_invalidated"))


def pullback_lifecycle_badge(row: dict[str, Any]) -> tuple[str, str]:
    price = to_decimal(row.get("latest_close_price"))
    latest_high = to_decimal(row.get("latest_high_price"))
    latest_low = to_decimal(row.get("latest_low_price"))
    reaction_low, reaction_high = _range_bounds(row.get("entry_zone_low"), row.get("entry_zone_high"))
    downside_low, downside_high = _range_bounds(row.get("tp_zone_low"), row.get("tp_zone_high"))

    if price is None:
        return "PULLBACK WATCH", "watch"

    if is_pullback_invalidated(row):
        return "INVALIDATED", "danger"

    latest_overlaps_downside_entry = (
        latest_low is not None
        and latest_high is not None
        and downside_low is not None
        and downside_high is not None
        and latest_low <= downside_high
        and latest_high >= downside_low
    )

    if row.get("path_downside_entry_reached"):
        if (
            reaction_high is not None
            and (price > reaction_high or (latest_high is not None and latest_high > reaction_high))
        ):
            return "REACTION RETEST AFTER ENTRY", "watch"
        if price is not None and downside_high is not None and price > downside_high:
            return "POST-ENTRY BOUNCE", "watch"
        if latest_overlaps_downside_entry:
            return "DOWNSIDE ENTRY REACHED", "context"
        if price is not None and downside_low is not None and price < downside_low:
            return "BELOW DOWNSIDE ENTRY", "block"
        return "DOWNSIDE ENTRY REACHED", "context"

    if downside_low is not None and downside_high is not None:
        if latest_overlaps_downside_entry:
            return "DOWNSIDE ENTRY REACHED", "context"
        if price < downside_low:
            return "BELOW DOWNSIDE ENTRY", "block"

    if reaction_low is not None and reaction_high is not None and reaction_low <= price <= reaction_high:
        return "REACTION ZONE ACTIVE", "watch"

    if (
        reaction_low is not None
        and reaction_high is not None
        and latest_low is not None
        and latest_high is not None
        and latest_low <= reaction_high
        and latest_high >= reaction_low
    ):
        return "REACTION ZONE ACTIVE", "watch"

    if reaction_high is not None and (price > reaction_high or (latest_high is not None and latest_high > reaction_high)):
        return "REACTION RETEST", "watch"

    if (
        reaction_low is not None
        and downside_high is not None
        and price < reaction_low
        and price > downside_high
    ):
        return "PULLBACK IN PROGRESS", "watch"

    return "PULLBACK WATCH", "watch"


def display_badges(row: dict[str, Any]) -> list[tuple[str, str]]:
    badges: list[tuple[str, str]] = []
    leg_direction = str(row.get("leg_direction") or "").strip().upper()
    policy_decision = str(row.get("policy_decision") or "").strip().upper()
    setup_filter_state = str(row.get("setup_filter_state") or "").strip().upper()
    selection_state = str(row.get("selection_state") or "").strip().upper()

    if leg_direction == "DOWN":
        invalidated = is_pullback_invalidated(row)
        badges.append(pullback_lifecycle_badge(row))
        if invalidated:
            badges.append(("EXPIRED MAP", "danger"))
            badges.append(("RECOMPUTE NEEDED", "block"))
            badges.append(("NOT ACTIONABLE", "block"))

        badges.append(("WATCHLIST ONLY", "context"))

        if policy_decision == "BLOCK_FOR_24H" and not invalidated:
            badges.append(("NOT ACTIONABLE", "block"))

    if setup_filter_state == "FAIL":
        badges.append(("SETUP FAILED", "muted"))
        setup_reason = setup_fail_primary_reason(row)
        if setup_reason:
            badges.append((setup_reason, css_class(setup_reason)))

    if selection_state in {"AVOID", "NO_EDGE_PERMISSION"}:
        badges.append(("NO EDGE", "danger"))

    return badges


def setup_fail_primary_reason(row: dict[str, Any]) -> str:
    setup_filter_state = str(row.get("setup_filter_state") or "").strip().upper()
    if setup_filter_state != "FAIL":
        return ""
    return str(row.get("setup_filter_reason") or "").strip().upper()


def setup_reason_codes(row: dict[str, Any]) -> list[str]:
    reason = setup_fail_primary_reason(row)
    return [reason] if reason else []


def reason_codes_display(row: dict[str, Any]) -> str:
    codes: list[str] = []
    raw_reason_codes = row.get("reason_codes_json")
    if raw_reason_codes:
        try:
            parsed = json.loads(str(raw_reason_codes))
            if isinstance(parsed, list):
                codes.extend(str(item) for item in parsed)
            elif isinstance(parsed, dict):
                codes.extend(f"{k}={v}" for k, v in parsed.items())
            else:
                codes.append(str(parsed))
        except json.JSONDecodeError:
            codes.append(str(raw_reason_codes))

    for code in setup_reason_codes(row):
        if code and code not in codes:
            insert_at = codes.index("SETUP_FAIL") + 1 if "SETUP_FAIL" in codes else len(codes)
            codes.insert(insert_at, code)

    return ", ".join(codes)


def enrich_candle_context(
    conn: pymysql.connections.Connection,
    rows: list[dict[str, Any]],
    venue: str,
    advice_interval: str,
    lifecycle_candle_interval: str,
) -> None:
    asset_ids = sorted({int(row["asset_id"]) for row in rows if row.get("asset_id") is not None})
    if not asset_ids:
        return

    placeholders = ",".join(["%s"] * len(asset_ids))
    latest_params: list[Any] = [
        venue,
        lifecycle_candle_interval,
        *asset_ids,
        venue,
        lifecycle_candle_interval,
    ]

    lifecycle_starts: dict[int, datetime] = {}
    for row in rows:
        if row.get("asset_id") is None:
            continue
        start_ts = zone_lifecycle_start_ts(row)
        if start_ts is None:
            continue
        asset_id = int(row["asset_id"])
        existing = lifecycle_starts.get(asset_id)
        if existing is None or start_ts < existing:
            lifecycle_starts[asset_id] = start_ts
        row["zone_lifecycle_start_ts_utc"] = start_ts
        row["advice_interval_code"] = advice_interval
        row["lifecycle_candle_interval_code"] = lifecycle_candle_interval

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                c.asset_id,
                c.close_ts_utc,
                c.close_price,
                c.high_price,
                c.low_price
            FROM obs_market_candle c
            JOIN (
                SELECT asset_id, MAX(close_ts_utc) AS max_close_ts_utc
                FROM obs_market_candle
                WHERE venue = %s
                  AND interval_code = %s
                  AND asset_id IN ({placeholders})
                GROUP BY asset_id
            ) latest
              ON latest.asset_id = c.asset_id
             AND latest.max_close_ts_utc = c.close_ts_utc
            WHERE c.venue = %s
              AND c.interval_code = %s
            """,
            latest_params,
        )
        price_rows = {int(row["asset_id"]): row for row in cur.fetchall()}

    for row in rows:
        asset_id = row.get("asset_id")
        if asset_id is None:
            continue
        price_row = price_rows.get(int(asset_id))
        if not price_row:
            continue
        row["latest_close_price"] = price_row.get("close_price")
        row["latest_high_price"] = price_row.get("high_price")
        row["latest_low_price"] = price_row.get("low_price")
        row["latest_close_ts_utc"] = price_row.get("close_ts_utc")

    if not lifecycle_starts:
        return

    min_start_ts = min(lifecycle_starts.values())

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                asset_id,
                close_ts_utc,
                high_price,
                low_price
            FROM obs_market_candle
            WHERE venue = %s
              AND interval_code = %s
              AND asset_id IN ({placeholders})
              AND close_ts_utc >= %s
            ORDER BY asset_id, close_ts_utc
            """,
            [venue, lifecycle_candle_interval, *asset_ids, min_start_ts],
        )
        path_candles = list(cur.fetchall())

    candles_by_asset: dict[int, list[dict[str, Any]]] = {}
    for candle in path_candles:
        candles_by_asset.setdefault(int(candle["asset_id"]), []).append(candle)

    for row in rows:
        if str(row.get("leg_direction") or "").strip().upper() != "DOWN":
            continue
        if row.get("asset_id") is None:
            continue

        start_ts = row.get("zone_lifecycle_start_ts_utc")
        if not isinstance(start_ts, datetime):
            continue

        invalidation = to_decimal(row.get("invalidation_price"))
        downside_low, downside_high = _range_bounds(row.get("tp_zone_low"), row.get("tp_zone_high"))
        path_invalidated = False
        path_downside_entry_reached = False

        for candle in candles_by_asset.get(int(row["asset_id"]), []):
            close_ts = parse_ts(candle.get("close_ts_utc"))
            if close_ts is None or close_ts < start_ts:
                continue

            high = to_decimal(candle.get("high_price"))
            low = to_decimal(candle.get("low_price"))

            if invalidation is not None and high is not None and high >= invalidation:
                path_invalidated = True

            if (
                downside_low is not None
                and downside_high is not None
                and low is not None
                and high is not None
                and low <= downside_high
                and high >= downside_low
            ):
                path_downside_entry_reached = True

        row["path_invalidated"] = path_invalidated
        row["path_downside_entry_reached"] = path_downside_entry_reached


def fetch_latest_rows(
    conn: pymysql.connections.Connection,
    venue: str,
    interval: str,
    lifecycle_candle_interval: str,
    limit: int,
) -> tuple[datetime | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(asof_ts_utc) AS latest_asof
            FROM paper_advice_observation
            WHERE venue = %(venue)s
              AND interval_code = %(interval)s
            """,
            {"venue": venue, "interval": interval},
        )
        latest = cur.fetchone()

    latest_asof = latest["latest_asof"] if latest else None

    if latest_asof is None:
        return None, [], [], None

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH ranked_advice AS (
                SELECT
                    paper_advice_observation_id,
                    asset_id,
                    symbol,
                    priority_rank,
                    selection_state,
                    selection_bias,
                    selection_score,
                    setup_filter_state,
                    setup_filter_reason,
                    policy_decision,
                    suggested_horizon,
                    allowed_now,
                    aplus_bucket,
                    aplus_phase,
                    aplus_coherence,
                    aplus_field,
                    aplus_geometry,
                    aplus_structural_role,
                    aplus_expansion_quality,
                    aplus_anchor_strength,
                    aplus_strategic_bias,
                    leg_direction,
                    entry_zone_low,
                    entry_zone_high,
                    entry_zone_type,
                    tp_zone_low,
                    tp_zone_high,
                    tp_zone_type,
                    invalidation_price,
                    zone_confidence_score,
                    zone_alignment_score,
                    advice_state,
                    advice_action,
                    confidence_score,
                    risk_label,
                    reason_codes_json,
                    source_ref_json,
                    asof_ts_utc,
                    context_ts_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY asset_id
                        ORDER BY asof_ts_utc DESC, paper_advice_observation_id DESC
                    ) AS rn
                FROM paper_advice_observation
                WHERE venue = %(venue)s
                  AND interval_code = %(interval)s
            )
            SELECT
                asset_id,
                symbol,
                priority_rank,
                selection_state,
                selection_bias,
                selection_score,
                setup_filter_state,
                setup_filter_reason,
                policy_decision,
                suggested_horizon,
                allowed_now,
                aplus_bucket,
                aplus_phase,
                aplus_coherence,
                aplus_field,
                aplus_geometry,
                aplus_structural_role,
                aplus_expansion_quality,
                aplus_anchor_strength,
                aplus_strategic_bias,
                leg_direction,
                entry_zone_low,
                entry_zone_high,
                entry_zone_type,
                tp_zone_low,
                tp_zone_high,
                tp_zone_type,
                invalidation_price,
                zone_confidence_score,
                zone_alignment_score,
                advice_state,
                advice_action,
                confidence_score,
                risk_label,
                reason_codes_json,
                source_ref_json,
                asof_ts_utc,
                context_ts_utc
            FROM ranked_advice
            WHERE rn = 1
            ORDER BY
                CASE advice_state
                    WHEN 'WATCH_CORE' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'BLOCK_24H' THEN 3
                    WHEN 'CORE_CONTEXT' THEN 4
                    WHEN 'WAIT' THEN 5
                    WHEN 'NO_NEW_BUY' THEN 6
                    WHEN 'AVOID' THEN 7
                    ELSE 99
                END,
                confidence_score DESC,
                priority_rank IS NULL,
                priority_rank ASC,
                symbol ASC
            LIMIT %(limit)s
            """,
            {
                "venue": venue,
                "interval": interval,
                "limit": int(limit),
            },
        )
        rows = list(cur.fetchall())

    counts = advice_state_counts(rows)
    enrich_candle_context(conn, rows, venue, interval, lifecycle_candle_interval)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                strategy_runtime_snapshot_id,
                snapshot_ts_utc,
                git_commit,
                runtime_scope,
                venue,
                interval_code,
                chain_name,
                live_trading_enabled,
                decision_gate_enabled,
                execution_enabled,
                notes
            FROM strategy_runtime_snapshot
            WHERE interval_code = %(interval)s
            ORDER BY strategy_runtime_snapshot_id DESC
            LIMIT 1
            """,
            {"interval": interval},
        )
        runtime = cur.fetchone()

    return latest_asof, rows, counts, runtime


def is_expired_recompute_map(row: dict[str, Any]) -> bool:
    leg_direction = str(row.get("leg_direction") or "").strip().upper()
    return leg_direction == "DOWN" and is_pullback_invalidated(row)


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    primary_states = {"WATCH_CORE", "WATCH", "BLOCK_24H", "CORE_CONTEXT", "WAIT"}
    expired = [row for row in rows if is_expired_recompute_map(row)]
    expired_ids = {id(row) for row in expired}
    primary = [
        row
        for row in rows
        if id(row) not in expired_ids and str(row.get("advice_state", "")).upper() in primary_states
    ]
    primary_ids = {id(row) for row in primary}
    defensive = [row for row in rows if id(row) not in primary_ids and id(row) not in expired_ids]
    return primary, expired, defensive


def render_count_cards(counts: list[dict[str, Any]]) -> str:
    cards = []

    for row in counts:
        state = str(row["advice_state"])
        n = row["n"]
        cards.append(
            f"""
            <div class="metric {css_class(state)}">
                <div class="metric-label">{esc(state)}</div>
                <div class="metric-value">{esc(n)}</div>
            </div>
            """
        )

    return "\n".join(cards)


def render_manual_support_section(
    rows: list[dict[str, Any]],
    *,
    market_breath_by_symbol: dict[str, dict[str, Any]] | None = None,
    intrabar_by_symbol: dict[str, Any] | None = None,
    limit: int = 10,
) -> str:
    if not rows:
        return '<div class="empty">No rows.</div>'

    cards: list[str] = []
    for row in rows[:limit]:
        symbol = str(row.get("symbol") or "").upper()
        current_price = row.get("current_price")
        market_breath_row = (market_breath_by_symbol or {}).get(symbol)
        intrabar_row = (intrabar_by_symbol or {}).get(symbol)
        entry_state = classify_entry_zone_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
        )
        target_state = classify_target_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
        )
        price_progress = classify_price_progress_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            in_position_context=False,
        )
        lifecycle = classify_fast_lifecycle(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
        )
        next_preview = preview_next_zones(
            symbol=row.get("symbol"),
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
            lifecycle_state=lifecycle.lifecycle_state,
            lifecycle_reason=lifecycle.recompute_reason,
            target_state=target_state,
            price_progress_state=price_progress.progress_state,
        )
        action_display = semantic_advice_action_display(
            advice_action=row.get("advice_action"),
            lifecycle_state=lifecycle.lifecycle_state,
            intrabar_state=None if intrabar_row is None else intrabar_row.intrabar_lifecycle_state,
        )
        block_display = classify_policy_block_display(
            row,
            lifecycle_state=lifecycle.lifecycle_state,
            recompute_needed=lifecycle.recompute_needed,
            recompute_reason=lifecycle.recompute_reason,
            target_state=target_state,
            entry_state=entry_state,
            price_progress_state=price_progress.progress_state,
            market_breath_row=market_breath_row,
        )
        support = manual_support_context(
            row,
            current_price=current_price,
            entry_state=entry_state,
            target_state=target_state,
            price_progress_state=price_progress.progress_state,
            lifecycle=lifecycle,
            next_preview=next_preview,
            market_breath_row=market_breath_row,
            intrabar_row=intrabar_row,
            block_display=block_display,
            action_label=action_display,
        )
        cards.append(
            f"""
            <article class="manual-card">
                <div class="manual-card-head">
                    <div class="symbol">{esc(symbol)}</div>
                    <div>{badge_html(str(row.get("leg_direction") or "—"))}</div>
                </div>
                {manual_support_html(support)}
            </article>
            """
        )

    return f"<div class='manual-grid'>{''.join(cards)}</div>"


def render_table(
    rows: list[dict[str, Any]],
    market_breath_by_symbol: dict[str, dict[str, Any]] | None = None,
    intrabar_by_symbol: dict[str, Any] | None = None,
) -> str:
    if not rows:
        return '<div class="empty">No rows.</div>'

    body = []
    now_utc = datetime.now(UTC)

    for row in rows:
        advice_state = str(row.get("advice_state") or "")
        risk_label = str(row.get("risk_label") or "")
        leg_direction = str(row.get("leg_direction") or "")

        reason_codes = reason_codes_display(row)
        symbol = str(row.get("symbol") or "").upper()
        market_breath_row = (market_breath_by_symbol or {}).get(symbol)
        intrabar_row = (intrabar_by_symbol or {}).get(symbol)
        setup_reason = setup_fail_primary_reason(row)
        setup_reason_html = ""
        if setup_reason:
            setup_reason_html = f'<div class="muted small">setup reason: {esc(setup_reason)}</div>'

        rank = row.get("priority_rank")
        rank_text = "—" if rank is None else str(rank)

        zone_cell_1, zone_cell_2, zone_cell_3 = zone_display_cells(row)
        current_price = row.get("current_price")
        current_price_status = str(row.get("current_price_status") or "MISSING_CURRENT_PRICE").upper()
        entry_state = classify_entry_zone_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
        )
        target_state = classify_target_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
        )
        price_progress = classify_price_progress_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            in_position_context=False,
        )
        lifecycle = classify_fast_lifecycle(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
        )
        next_preview = preview_next_zones(
            symbol=row.get("symbol"),
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
            lifecycle_state=lifecycle.lifecycle_state,
            lifecycle_reason=lifecycle.recompute_reason,
            target_state=target_state,
            price_progress_state=price_progress.progress_state,
        )
        target_html = relevant_target_html(row, next_preview)
        progress_labels = "".join(
            badge_html(label, css_name=css_class(label))
            for label in price_progress.labels
        )
        progress_html = (
            f'{badge_html(price_progress.progress_state, css_name=css_class(price_progress.progress_state))}'
            f"{progress_labels}"
        )
        entry_display_state = semantic_entry_display_state(
            entry_state=entry_state,
            price_progress_state=price_progress.progress_state,
            price_progress_labels=price_progress.labels,
        )
        confirm_state = confirmation_display_state(
            advice_action=row.get("advice_action"),
            policy_decision=row.get("policy_decision"),
            entry_state=entry_state,
            price_progress_state=price_progress.progress_state,
            price_progress_labels=price_progress.labels,
        )
        severity = calibrate_paper_advice_severity(
            row,
            market_breath_row=market_breath_row,
            lifecycle_state=lifecycle.lifecycle_state,
            recompute_needed=lifecycle.recompute_needed,
            recompute_reason=lifecycle.recompute_reason,
            target_state=target_state,
            risk_state=None,
            entry_state=entry_state,
            price_progress_state=price_progress.progress_state,
        )
        action_display = semantic_advice_action_display(
            advice_action=row.get("advice_action"),
            lifecycle_state=lifecycle.lifecycle_state,
            intrabar_state=None if intrabar_row is None else intrabar_row.intrabar_lifecycle_state,
        )
        blockers = promotion_blockers(row, candidate_group=None) if entry_state.endswith("_REACHED") else []
        block_display = classify_policy_block_display(
            row,
            lifecycle_state=lifecycle.lifecycle_state,
            recompute_needed=lifecycle.recompute_needed,
            recompute_reason=lifecycle.recompute_reason,
            target_state=target_state,
            entry_state=entry_state,
            price_progress_state=price_progress.progress_state,
            market_breath_row=market_breath_row,
        )
        severity = (
            severity
            if block_display is None
            else type(severity)(
                advice_severity=severity.advice_severity,
                advice_substate=severity.advice_substate,
                reason_codes=severity.reason_codes,
                display_label=severity.display_label,
                display_note=severity.display_note,
                policy_block=block_display,
            )
        )
        action_label = action_display
        action_class = css_class(action_label)
        action_detail = f"policy/action: {esc(row.get('advice_action'))}"
        policy_html = esc(row.get("policy_decision"))
        if current_price_status == "STALE_CURRENT_PRICE":
            action_label = "STALE_CURRENT_PRICE"
            action_class = css_class("STALE_CURRENT_PRICE")
            action_detail = "Current public price snapshot is stale; price-based action review blocked."
        if current_price_status == "STALE_CURRENT_PRICE":
            policy_html = (
                f'{badge_html("STALE_CURRENT_PRICE")}'
                f'<div class="muted small">Current public price snapshot is stale.</div>'
            )
        elif block_display is not None:
            action_label = block_display.display_policy_label
            action_class = css_class(block_display.display_policy_label)
            action_detail = block_reason_summary_text(block_display)
            policy_html = (
                f'{badge_html(block_display.display_policy_label)}'
                f'<div class="muted small">raw: {esc(block_display.raw_policy_state)}</div>'
                f'<div class="muted small">cause: {esc(block_display.block_primary_reason)}</div>'
                f'<div class="muted small">unblock: {esc(block_display.unblock_condition_label)}</div>'
            )
        row_classes = []
        if lifecycle.recompute_needed or (leg_direction.strip().upper() == "DOWN" and is_pullback_invalidated(row)):
            row_classes.extend(["expired", "stale-map"])
        elif is_recent_ts(row.get("asof_ts_utc"), now_utc=now_utc):
            row_classes.append("fresh-map")
        row_class = " ".join(row_classes)
        badges = display_badges(row)
        if lifecycle.lifecycle_state not in {"ACTIVE_MAP", "PRICE_UNKNOWN", "LIFECYCLE_UNKNOWN"}:
            badges.append((lifecycle.lifecycle_state, css_class(lifecycle.lifecycle_state)))
        if lifecycle.recompute_needed:
            badges.append(("MAP_RECOMPUTE_NEEDED", css_class("MAP_RECOMPUTE_NEEDED")))
        for reason in (part.strip() for part in lifecycle.recompute_reason.split(",")):
            if reason in {"DOWN_MAP_INVALIDATED_BY_RECLAIM", "UP_MAP_INVALIDATED_BY_BREAKDOWN"}:
                badges.append((reason, css_class(reason)))
        if "fresh-map" in row_classes:
            badges.append(("FRESH_MAP", "good"))
        badges_html = ""
        if badges:
            badges_html = "".join(
                badge_html(label, css_name=css_name) for label, css_name in badges
            )
            badges_html = f'<div class="badge-row">{badges_html}</div>'
        manual_support = manual_support_context(
            row,
            current_price=current_price,
            entry_state=entry_state,
            target_state=target_state,
            price_progress_state=price_progress.progress_state,
            lifecycle=lifecycle,
            next_preview=next_preview,
            market_breath_row=market_breath_row,
            intrabar_row=intrabar_row,
            block_display=block_display,
            action_label=action_label,
        )

        body.append(
            f"""
            <tr class="{esc(row_class)}">
                <td class="mono center">{esc(rank_text)}</td>
                <td class="symbol sticky-symbol">
                    {esc(row.get("symbol"))}
                    <div>{badge_html(leg_direction or "—")}</div>
                    {badges_html}
                </td>
                <td>{badge_html(advice_state)}</td>
                <td>{badge_html(action_label, css_name=action_class)}<div class="muted small">{esc(action_detail)}</div></td>
                <td>{badge_text_html(manual_support.manual_action_label)}</td>
                <td>{badge_text_html(manual_support.direction_label)}</td>
                <td>{badge_text_html(manual_support.strategy_family)}</td>
                <td>{badge_text_html(manual_support.horizon_bucket)}</td>
                <td class="mono right">{fmt_score(row.get("confidence_score"))}</td>
                <td>{badge_html(risk_label)}</td>
                <td class="mono right sticky-price">{esc(fmt_snapshot_price(current_price) or current_price_status)}</td>
                <td class="mono right">{fmt_decimal(row.get("price_age_min"), places=1)}</td>
                <td>{badge_html(entry_display_state)}<div class="muted small">raw: {esc(entry_state)}</div></td>
                <td>{progress_html}</td>
                <td>{badge_html(target_state)}</td>
                <td class="mono sticky-target">{target_html}</td>
                <td>{badge_html(confirm_state)}</td>
                <td class="muted small">{esc(", ".join(blockers))}</td>
                <td>{next_zone_html(next_preview)}</td>
                <td class="mono">
                    <div class="cell-label">{esc(zone_cell_1[0])}</div>
                    {zone_cell_1[1]}
                </td>
                <td class="mono">
                    <div class="cell-label">{esc(zone_cell_2[0])}</div>
                    {zone_cell_2[1]}
                </td>
                <td class="mono">
                    <div class="cell-label">{esc(zone_cell_3[0])}</div>
                    {zone_cell_3[1]}
                </td>
                <td>{esc(row.get("selection_state"))}</td>
                <td>{esc(row.get("setup_filter_state"))}{setup_reason_html}</td>
                <td>{policy_html}</td>
                <td>{badge_html(row.get("aplus_bucket"))}</td>
                <td>{market_breath_context_html(market_breath_row)}</td>
                <td>{intrabar_context_html(intrabar_row)}</td>
                <td>{advice_severity_html(severity)}</td>
                <td>{manual_support_html(manual_support)}</td>
                <td class="muted small">{esc(reason_codes)}</td>
            </tr>
            """
        )

    return f"""
    <div class="table-wrap">
        <table class="sticky-table">
            <thead class="sticky-header">
                <tr>
                    <th>Rank</th>
                    <th class="sticky-symbol">Symbol / Leg</th>
                    <th>Advice</th>
                    <th>Action</th>
                    <th>paper_action</th>
                    <th>direction_label</th>
                    <th>strategy_family</th>
                    <th>horizon_bucket</th>
                    <th>Conf</th>
                    <th>Risk</th>
                    <th class="sticky-price">Current price</th>
                    <th>Price age min</th>
                    <th>Entry state</th>
                    <th>Price progress</th>
                    <th>Target state</th>
                    <th class="sticky-target">Relevant target</th>
                    <th>Confirmation</th>
                    <th>Promotion blockers</th>
                    <th>Next zones</th>
                    <th>Zone 1</th>
                    <th>Zone 2</th>
                    <th>Zone 3</th>
                    <th>Selection</th>
                    <th>Setup</th>
                    <th>Policy</th>
                    <th>A+</th>
                    <th>Market Breath Context</th>
                    <th>Intrabar Lifecycle</th>
                    <th>Severity / Substate</th>
                    <th>candidate_inbox</th>
                    <th>Reasons</th>
                </tr>
            </thead>
            <tbody>
                {''.join(body)}
            </tbody>
        </table>
    </div>
    """


def render_html(
    title: str,
    venue: str,
    interval: str,
    lifecycle_candle_interval: str,
    latest_asof: datetime | None,
    rows: list[dict[str, Any]],
    counts: list[dict[str, Any]],
    runtime: dict[str, Any] | None,
    market_breath_by_symbol: dict[str, dict[str, Any]] | None = None,
    intrabar_by_symbol: dict[str, Any] | None = None,
) -> str:
    generated_ts = datetime.now(UTC).replace(tzinfo=None)
    primary_rows, expired_rows, defensive_rows = split_rows(rows)
    latest_lifecycle_ts = latest_lifecycle_candle_ts(rows)
    selected_min_asof, selected_max_asof = selected_asof_bounds(rows)

    latest_text = fmt_ts_local_first(latest_asof)
    selected_min_text = fmt_ts_local_first(selected_min_asof)
    selected_max_text = fmt_ts_local_first(selected_max_asof)
    latest_lifecycle_text = fmt_ts_local_first(latest_lifecycle_ts)
    generated_text = fmt_ts_local_first(generated_ts)
    runtime_text = "—"
    runtime_flags = "—"

    if runtime:
        runtime_text = (
            f"id={runtime.get('strategy_runtime_snapshot_id')} "
            f"snapshot={fmt_ts_local_first(runtime.get('snapshot_ts_utc'))} "
            f"chain={runtime.get('chain_name')}"
        )
        runtime_flags = (
            f"live_trading_enabled={runtime.get('live_trading_enabled')} · "
            f"decision_gate_enabled={runtime.get('decision_gate_enabled')} · "
            f"execution_enabled={runtime.get('execution_enabled')}"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="300">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(title)}</title>
    {synth_favicon_head_html().rstrip()}
    <style>
        {cockpit_base_css(min_table_width=2400)}
        :root {{
            --bg: #0b1020;
            --panel: #121a2f;
            --panel2: #17213b;
            --line: #2a3659;
            --text: #edf2ff;
            --muted: #95a1bf;
            --good: #34d399;
            --watch: #fbbf24;
            --block: #fb923c;
            --danger: #fb7185;
            --context: #60a5fa;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            background: radial-gradient(circle at top left, #1f2a4d, var(--bg) 36rem);
            color: var(--text);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        .page {{
            max-width: 1760px;
            margin: 0 auto;
            padding: 18px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: flex-start;
            margin-bottom: 18px;
        }}
        h1 {{
            margin: 0 0 8px 0;
            font-size: 28px;
            letter-spacing: -0.04em;
        }}
        h2 {{
            margin: 26px 0 12px 0;
            font-size: 18px;
            letter-spacing: -0.02em;
        }}
        .subtitle {{
            color: var(--muted);
            font-size: 14px;
            line-height: 1.5;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--line);
            background: rgba(18, 26, 47, 0.85);
            border-radius: 999px;
            padding: 7px 10px;
            color: var(--muted);
            font-size: 13px;
            white-space: nowrap;
        }}
        .cockpit-nav {{
            display: flex;
            flex-wrap: wrap;
            gap: 14px;
            margin-top: 12px;
        }}
        .cockpit-nav a {{
            color: var(--context);
            font-size: 14px;
            text-decoration: none;
        }}
        .cockpit-nav a:hover {{
            text-decoration: underline;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin: 18px 0;
        }}
        .metric {{
            border: 1px solid var(--line);
            background: linear-gradient(180deg, var(--panel), var(--panel2));
            border-radius: 18px;
            padding: 14px;
            min-height: 86px;
        }}
        .metric-label {{
            color: var(--muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}
        .metric-value {{
            font-size: 30px;
            font-weight: 800;
            margin-top: 8px;
        }}
        .panel {{
            border: 1px solid var(--line);
            background: rgba(18, 26, 47, 0.9);
            border-radius: 22px;
            padding: 16px;
            margin-top: 16px;
            box-shadow: 0 18px 50px rgba(0,0,0,0.26);
        }}
        .manual-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 12px;
        }}
        .manual-card {{
            border: 1px solid rgba(42, 54, 89, 0.7);
            background: rgba(10, 16, 32, 0.82);
            border-radius: 18px;
            padding: 14px;
        }}
        .manual-card-head {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }}
        .table-wrap {{
            width: 100%;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            min-width: 2550px;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th {{
            text-align: left;
            color: var(--muted);
            font-weight: 650;
            border-bottom: 1px solid var(--line);
            padding: 10px 8px;
            white-space: nowrap;
        }}
        td {{
            border-bottom: 1px solid rgba(42, 54, 89, 0.55);
            padding: 10px 8px;
            vertical-align: top;
        }}
        tr:hover {{
            background: rgba(96, 165, 250, 0.07);
        }}
        tr.expired {{
            opacity: 0.68;
        }}
        tr.expired td:nth-child(7),
        tr.expired td:nth-child(8),
        tr.expired td:nth-child(9) {{
            color: var(--muted);
        }}
        .symbol {{
            font-weight: 800;
            font-size: 14px;
        }}
        .mono {{
            font-variant-numeric: tabular-nums;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        .right {{ text-align: right; }}
        .center {{ text-align: center; }}
        .small {{ font-size: 12px; }}
        .muted {{ color: var(--muted); }}
        .cell-label {{
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 2px;
        }}
        .pill {{
            display: inline-flex;
            border-radius: 999px;
            border: 1px solid var(--line);
            padding: 4px 8px;
            font-size: 12px;
            white-space: nowrap;
            background: rgba(255,255,255,0.04);
        }}
        .badge-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 6px;
        }}
        .good {{ color: var(--good); }}
        .watch {{ color: var(--watch); }}
        .block {{ color: var(--block); }}
        .danger {{ color: var(--danger); }}
        .context {{ color: var(--context); }}
        .wait {{ color: var(--muted); }}
        .empty {{
            color: var(--muted);
            padding: 18px;
        }}
        .footer {{
            color: var(--muted);
            font-size: 12px;
            margin-top: 24px;
            line-height: 1.6;
        }}
        @media (max-width: 860px) {{
            .page {{ padding: 14px; }}
            .header {{ flex-direction: column; }}
            h1 {{ font-size: 23px; }}
            table {{ font-size: 12px; }}
            th, td {{ padding: 8px 6px; }}
        }}
    </style>
</head>
<body>
    <main class="page">
        <section class="header">
            <div>
                <h1>{esc(title)}</h1>
                <div class="subtitle">
                    Read-only paper advice · venue={esc(venue)} · advice interval={esc(interval)} · Fast lifecycle candles={esc(lifecycle_candle_interval)}<br>
                    row mode: latest_per_asset · latest overall advice asof: {esc(latest_text)}<br>
                    selected row asof range: {esc(selected_min_text)} → {esc(selected_max_text)}<br>
                    latest Fast lifecycle candle: {esc(latest_lifecycle_text)}<br>
                    dashboard rendered: {esc(generated_text)}<br>
                    Setup/policy changes when the 4h chain writes a new paper_advice_observation snapshot. Fast lifecycle candles check whether the existing map is touched, stale, invalidated, or near reclaim. They do not create a new strategy map.
                </div>
                {cockpit_nav(account_profile=DEFAULT_NAV_ACCOUNT_PROFILE)}
                <div class="legend">
                    <div><strong>Read-only review context.</strong> This page is not trade advice or order permission.</div>
                    <div><strong>Hover/tap a badge for label description.</strong></div>
                    <div><strong>Raw lifecycle/recompute reasons</strong> stay visible as review context.</div>
                    <div><strong>Fast lifecycle / intrabar overlays</strong> are context only and do not create a new strategy map.</div>
                    <div><strong>No broker/order path</strong>: broker/order/executor remain disabled here.</div>
                </div>
            </div>
                <div>{badge_html("broker_private_calls=0", css_name="ok")}{badge_html("broker_calls=0", css_name="ok")}{badge_html("broker_writes=0", css_name="ok")}{badge_html("order_submission=0", css_name="ok")}{badge_html("executor=none", css_name="ok")}{badge_html("live_trading=false", css_name="ok")}{badge_html("paper/manual only", css_name="ok")}{badge_html("account_awareness=0", css_name="ok")}</div>
        </section>

        <section class="grid">
            {render_count_cards(counts)}
        </section>

        <section class="panel">
            <h2>Manual trade support</h2>
            <div class="subtitle">
                Read-only manual-decision support and strategy-candidate inbox. Labels are display-only overlays on current paper advice, zone/fib context, market breath context, and fast lifecycle freshness.<br>
                Candidate rows surface explicit strategy_family, horizon_bucket, paper_action, direction_label, strongest_reasons, source_modules, and missing_inputs.<br>
                Missing context is shown explicitly and must be treated as missing, not neutral.
            </div>
            {render_manual_support_section(primary_rows + expired_rows + defensive_rows, market_breath_by_symbol=market_breath_by_symbol, intrabar_by_symbol=intrabar_by_symbol)}
        </section>

        <section class="panel">
            <h2>Navigation candidates</h2>
            {render_table(primary_rows, market_breath_by_symbol, intrabar_by_symbol)}
        </section>

        <section class="panel">
            <h2>Expired / recompute-needed maps</h2>
            {render_table(expired_rows, market_breath_by_symbol, intrabar_by_symbol)}
        </section>

        <section class="panel">
            <h2>Defensive / no-new-buy rows</h2>
            {render_table(defensive_rows, market_breath_by_symbol, intrabar_by_symbol)}
        </section>

        <section class="footer">
            Generated: {esc(generated_text)}<br>
            Runtime: {esc(runtime_text)}<br>
            Runtime flags: {esc(runtime_flags)}<br>
            Safety: broker_writes=0 · order_submission=0 · executor=none · live_trading=false · paper/manual only<br>
            Setup-fail reasons are read from paper_advice_observation / trade_setup_filter observations when available.<br>
            Boundary: this page is display-only. It does not call the broker, decision_gate, execution_planner, executor, or order APIs.
        </section>
    </main>
</body>
</html>
"""


def write_html(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def print_table(
    path: Path,
    latest_asof: datetime | None,
    rows: list[dict[str, Any]],
    counts: list[dict[str, Any]],
    lifecycle_candle_interval: str,
    market_price_snapshot_rows: int,
    quote_currency: str,
) -> None:
    print(f"report={POLICY_NAME} version={POLICY_VERSION}")
    print("scope=static-readonly paper-advice")
    print(
        "broker_private_calls=0 broker_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 executor=none live_trading=false "
        "paper/manual_only=true account_awareness=0"
    )
    selected_min_asof, selected_max_asof = selected_asof_bounds(rows)
    print("row_mode=latest_per_asset")
    print(f"latest_asof={latest_asof}")
    print(f"selected_min_asof={selected_min_asof}")
    print(f"selected_max_asof={selected_max_asof}")
    print(f"lifecycle_candle_interval={lifecycle_candle_interval}")
    print(f"market_price_snapshot_rows={market_price_snapshot_rows} quote={quote_currency.upper()}")
    print(f"rows={len(rows)}")
    print(f"output_html={path}")
    print()
    print("--- advice state counts ---")
    for row in counts:
        print(f"{row['advice_state']}={row['n']}")


def main() -> int:
    args = parse_args()
    output_path = Path(args.output_html)
    fib_map_by_symbol = load_fib_target_map_rows(DEFAULT_FIB_MAP_ROWS)

    conn = get_connection()
    try:
        latest_asof, rows, counts, runtime = fetch_latest_rows(
            conn,
            venue=str(args.venue),
            interval=str(args.interval),
            lifecycle_candle_interval=str(args.lifecycle_candle_interval),
            limit=int(args.limit),
        )
        price_by_symbol = fetch_latest_prices_by_symbol(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            symbols=sorted({str(row.get("symbol") or "").upper() for row in rows}),
        )
        market_breath_rows = build_market_breath_context_rows(
            conn,
            venue=str(args.venue),
            interval_code=str(args.interval),
            symbols=sorted({str(row.get("symbol") or "").upper() for row in rows}),
        )
        market_breath_by_symbol = market_breath_rows_by_symbol(market_breath_rows)
        intrabar_rows = build_intrabar_lifecycle_context_rows(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            structural_interval_code=str(args.interval),
            symbols=sorted({str(row.get("symbol") or "").upper() for row in rows}),
        )
        intrabar_by_symbol = intrabar_rows_by_symbol(intrabar_rows)
    finally:
        conn.close()

    now_utc = datetime.now(UTC)
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        snapshot = price_by_symbol.get(symbol)
        apply_current_price_snapshot(row, snapshot, now_utc=now_utc)
        attach_fib_map_context(row, fib_map_by_symbol.get(symbol))
    selected_min_asof, selected_max_asof = selected_asof_bounds(rows)

    html_content = render_html(
        title=str(args.title),
        venue=str(args.venue),
        interval=str(args.interval),
        lifecycle_candle_interval=str(args.lifecycle_candle_interval),
        latest_asof=latest_asof,
        rows=rows,
        counts=counts,
        runtime=runtime,
        market_breath_by_symbol=market_breath_by_symbol,
        intrabar_by_symbol=intrabar_by_symbol,
    )

    write_html(output_path, html_content)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "policy_name": POLICY_NAME,
                    "policy_version": POLICY_VERSION,
                    "row_mode": "latest_per_asset",
                    "latest_asof": latest_asof.isoformat(sep=" ") if latest_asof else None,
                    "selected_min_asof": (
                        selected_min_asof.isoformat(sep=" ") if selected_min_asof else None
                    ),
                    "selected_max_asof": (
                        selected_max_asof.isoformat(sep=" ") if selected_max_asof else None
                    ),
                    "lifecycle_candle_interval": str(args.lifecycle_candle_interval),
                    "market_price_snapshot_rows": len(price_by_symbol),
                    "market_breath_context_rows": len(market_breath_by_symbol),
                    "intrabar_lifecycle_context_rows": len(intrabar_by_symbol),
                    "quote": str(args.quote).upper(),
                    "rows": len(rows),
                    "output_html": str(output_path),
                    "broker_calls": 0,
                    "broker_private_calls": 0,
                    "broker_writes": 0,
                    "order_submission": 0,
                    "executor": "none",
                    "live_orders": 0,
                    "account_awareness": 0,
                },
                indent=2,
            )
        )
    else:
        print_table(
            output_path,
            latest_asof,
            rows,
            counts,
            str(args.lifecycle_candle_interval),
            len(price_by_symbol),
            str(args.quote),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
