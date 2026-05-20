from __future__ import annotations

import argparse
import html
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pymysql
from dotenv import load_dotenv

from src.market_data.market_price_snapshot_v1 import (
    MarketPriceSnapshot,
    fetch_latest_prices_by_symbol,
)
from src.reporting.dashboard_style_v1 import cockpit_base_css, cockpit_nav, pill_classes
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
from src.reporting.market_breath_context_bridge_v1 import (
    build_market_breath_context_rows,
    rows_by_symbol as market_breath_rows_by_symbol,
)
from src.reporting.next_zone_preview_v1 import (
    NextZonePreview,
    format_zone,
    preview_next_zones,
)
from src.reporting.paper_advice_severity_calibration_v1 import (
    calibrate_paper_advice_severity,
)


POLICY_NAME = "paper_advice_static_dashboard_v1"
POLICY_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "data/reporting/paper_advice_dashboard_v1.html"

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
    if parsed is None:
        return "not available"

    utc_value = parsed.replace(tzinfo=UTC)
    local_value = utc_value.astimezone(ZoneInfo(timezone))
    return local_value.strftime("%Y-%m-%d %H:%M:%S %Z")


def fmt_ts_local_first(value: Any, timezone: str = "Europe/Amsterdam") -> str:
    parsed = parse_ts(value)
    if parsed is None:
        return "not available"

    local_text = fmt_ts_local(parsed, timezone=timezone)
    return f"{local_text} Amsterdam time"


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
        "READ_ONLY_APLUS_AVOID": "block",
        "HARD_BLOCK": "danger",
        "SOFT_BLOCK": "block",
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
        f'<span class="pill {css_class(preview.next_zone_state)}">{esc(preview.next_zone_state)}</span>'
    ]
    if preview.next_reaction_zone_label and preview.next_reaction_zone:
        parts.append(
            '<div class="small">'
            f'<span class="pill {css_class(preview.next_reaction_zone_label)}">{esc(preview.next_reaction_zone_label)}</span> '
            f'<span class="zone-value">{esc(format_zone(preview.next_reaction_zone))}</span>'
            "</div>"
        )
    if preview.next_target_zone_label and preview.next_target_zone:
        parts.append(
            '<div class="small">'
            f'<span class="pill {css_class(preview.next_target_zone_label)}">{esc(preview.next_target_zone_label)}</span> '
            f'<span class="zone-value">{esc(format_zone(preview.next_target_zone))}</span>'
            "</div>"
        )
    if preview.next_zone_reason:
        parts.append(f'<div class="muted small">{esc(preview.next_zone_reason)}</div>')
    if preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}:
        parts.append('<div class="muted small">Market context, not permission.</div>')
    return "".join(parts)


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
        f'<div><span class="pill {css_class(phase)}">{esc(phase)}</span> '
        f'<span class="pill {css_class(state)}">{esc(state)}</span></div>'
        f'<div class="small"><span class="pill {css_class(context_state)}">{esc(context_state)}</span></div>'
        f'<div class="muted small">A+ legacy age: <span class="mono">{esc(age)}</span>h '
        f'<span class="pill {css_class(freshness)}">{esc(freshness)}</span></div>'
        f'<div class="muted small">{esc(suggested_context)}</div>'
    )


def advice_severity_html(severity: Any) -> str:
    return (
        f'<div><span class="pill {css_class(severity.advice_severity)}">{esc(severity.advice_severity)}</span></div>'
        f'<div><span class="pill {css_class(severity.advice_substate)}">{esc(severity.advice_substate)}</span></div>'
        f'<div class="muted small">{esc(severity.display_note)}</div>'
    )


def intrabar_context_html(row: Any | None) -> str:
    if not row:
        return '<span class="muted small">not available</span>'
    quality_labels = "".join(
        f'<span class="pill {css_class(part)}">{esc(part)}</span>'
        for part in str(row.data_quality_state or "").split(";")
        if part
    )
    return (
        f'<div><span class="pill {css_class(row.intrabar_lifecycle_state)}">{esc(row.intrabar_lifecycle_state)}</span></div>'
        f'<div><span class="pill {css_class(row.intrabar_recompute_hint)}">{esc(row.intrabar_recompute_hint)}</span></div>'
        f'<div class="muted small">source={esc(row.price_source)} · 15m={esc(row.latest_15m_close_ts_utc or "missing")}</div>'
        f'<div class="badge-row">{quality_labels}</div>'
        '<div class="muted small">Intrabar context, not trade advice.</div>'
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
        progress_labels = "".join(
            f'<span class="pill {css_class(label)}">{esc(label)}</span>'
            for label in price_progress.labels
        )
        progress_html = (
            f'<span class="pill {css_class(price_progress.progress_state)}">{esc(price_progress.progress_state)}</span>'
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
        badge_html = ""
        if badges:
            badge_html = "".join(
                f'<span class="pill {esc(css_name)}">{esc(label)}</span>' for label, css_name in badges
            )
            badge_html = f'<div class="badge-row">{badge_html}</div>'

        body.append(
            f"""
            <tr class="{esc(row_class)}">
                <td class="mono center">{esc(rank_text)}</td>
                <td class="symbol sticky-symbol">
                    {esc(row.get("symbol"))}
                    <div><span class="pill {css_class(leg_direction)}">{esc(leg_direction or "—")}</span></div>
                    {badge_html}
                </td>
                <td><span class="pill {css_class(advice_state)}">{esc(advice_state)}</span></td>
                <td><span class="pill {css_class(action_display)}">{esc(action_display)}</span><div class="muted small">policy/action: {esc(row.get("advice_action"))}</div></td>
                <td class="mono right">{fmt_score(row.get("confidence_score"))}</td>
                <td><span class="pill {css_class(risk_label)}">{esc(risk_label)}</span></td>
                <td class="mono right sticky-price">{esc(fmt_snapshot_price(current_price))}</td>
                <td class="mono right">{fmt_decimal(row.get("price_age_min"), places=1)}</td>
                <td><span class="pill {css_class(entry_display_state)}">{esc(entry_display_state)}</span><div class="muted small">raw: {esc(entry_state)}</div></td>
                <td>{progress_html}</td>
                <td><span class="pill {css_class(target_state)}">{esc(target_state)}</span></td>
                <td><span class="pill {css_class(confirm_state)}">{esc(confirm_state)}</span></td>
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
                <td>{esc(row.get("policy_decision"))}</td>
                <td>{esc(row.get("aplus_bucket"))}</td>
                <td>{market_breath_context_html(market_breath_row)}</td>
                <td>{intrabar_context_html(intrabar_row)}</td>
                <td>{advice_severity_html(severity)}</td>
                <td class="muted small">{esc(reason_codes)}</td>
            </tr>
            """
        )

    return f"""
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th class="sticky-symbol">Symbol / Leg</th>
                    <th>Advice</th>
                    <th>Action</th>
                    <th>Conf</th>
                    <th>Risk</th>
                    <th class="sticky-price">Current price</th>
                    <th>Price age min</th>
                    <th>Entry state</th>
                    <th>Price progress</th>
                    <th>Target state</th>
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
    <style>
        {cockpit_base_css(min_table_width=2050)}
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
        .table-wrap {{
            width: 100%;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            min-width: 2250px;
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
                {cockpit_nav()}
                <div class="legend">
                    <div><strong>ENTRY_ZONE_REACHED</strong> means price is in the entry/reaction zone; it is separate from target state and is not buy permission.</div>
                    <div><strong>Entry state precedence</strong>: target touched, post-entry progress, and entry-window-passed labels take precedence over near-entry labels.</div>
                    <div><strong>CONFIRMATION_PENDING</strong> means price/setup still needs policy or advice confirmation.</div>
                    <div><strong>Price progress</strong> shows where current price sits between entry/reaction zone and target. TARGET_PENDING can still be true while TARGET_NEAR is shown.</div>
                    <div><strong>ACTIVE_MAP</strong> means the map is still valid, not that entry or target was reached.</div>
                    <div><strong>Fast lifecycle candles</strong> check whether the existing map is touched, stale, invalidated, or near reclaim. They do not create a new strategy map.</div>
                    <div><strong>Dimmed labels</strong> in red/stale rows are old-map context; bright red/orange labels are the current lifecycle/recompute reason.</div>
                    <div><strong>Next zones</strong>: Next zones are market-only preview zones after a map is stale, reclaimed, invalidated, or target-finished. They are not orders, allocation advice, or execution intent.</div>
                    <div><strong>Market context is not trade permission.</strong> Policy blocks and next-zone previews can coexist.</div>
                    <div><strong>Severity / Substate</strong>: Review context, not trade advice. Soft caution is not permission; stale A+ context is not a hard current veto by itself.</div>
                    <div><strong>Intrabar lifecycle</strong>: 15m/current-price overlay against the 4h structural map. It is context only and does not change paper advice permission.</div>
                </div>
            </div>
            <div class="badge">broker_private_calls=0 · broker_calls=0 · broker_writes=0 · order_submission=0 · executor=none · account_awareness=0</div>
        </section>

        <section class="grid">
            {render_count_cards(counts)}
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
    print("broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 executor=none account_awareness=0")
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
        snapshot = price_by_symbol.get(str(row.get("symbol") or "").upper())
        row["current_price"] = None if snapshot is None else snapshot.price
        row["price_age_min"] = price_age_min(snapshot, now_utc=now_utc)
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
