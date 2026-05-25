from __future__ import annotations

import argparse
import html
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.common.db import get_connection
from src.reporting.dashboard_style_v1 import cockpit_base_css, cockpit_nav, pill_classes
from src.reporting.entry_zone_state_v1 import (
    classify_entry_zone_state,
    classify_price_progress_state,
    confirmation_display_state,
    semantic_advice_action_display,
    semantic_entry_display_state,
)
from src.reporting.fast_lifecycle_recompute_v1 import classify_fast_lifecycle
from src.reporting.intrabar_lifecycle_context_v1 import (
    build_intrabar_lifecycle_context_rows,
    rows_by_symbol as intrabar_rows_by_symbol,
)
from src.reporting.run_fast_recompute_lifecycle_v1 import (
    build_recompute_rows,
    render_rows_table as render_recompute_rows_table,
)
from src.reporting.next_zone_preview_v1 import (
    NextZonePreview,
    format_zone,
    preview_next_zones,
)
from src.reporting.market_breath_context_bridge_v1 import (
    build_market_breath_context_rows,
    rows_by_symbol as market_breath_rows_by_symbol,
)
from src.reporting.paper_advice_severity_calibration_v1 import (
    calibrate_paper_advice_severity,
)
from src.reporting.policy_block_reason_display_v1 import (
    block_reason_summary_text,
    classify_policy_block_display,
)
from src.reporting.rotation_destination_eligibility_v1 import (
    DestinationConfidence,
    DestinationEligibility,
    destination_confidence,
    evaluate_rotation_destination_eligibility,
)
from src.market_data.market_price_snapshot_v1 import (
    MarketPriceSnapshot,
    fetch_latest_prices_by_symbol,
)
from src.research.run_position_rotation_preview_v1 import (
    build_rows,
    dec,
    fetch_latest_paper_advice_rows,
    fetch_latest_position_rows,
    fetch_zone_fib_context_by_symbol,
    market_candidate_quality_score,
    rank_market_candidates,
    risk_state_for_advice,
    target_state_for_advice,
)


REPORT_NAME = "position_rotation_static_dashboard_v1"
REPORT_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "/var/www/html/synth/rotation-preview.html"


@dataclass(frozen=True)
class EurBalanceSnapshot:
    available_amount: Decimal
    reserved_amount: Decimal
    total_amount: Decimal
    snapshot_ts_utc: datetime | None


@dataclass(frozen=True)
class PositionValuation:
    value_eur: Decimal | None
    source: str


@dataclass(frozen=True)
class CandidateDestinationContext:
    advice: dict[str, Any] | None
    current_price: Decimal | None
    target_state: str
    risk_state: str
    entry_state: str
    entry_display_state: str
    price_progress: Any
    lifecycle: Any
    effective_lifecycle_state: str
    effective_recompute_needed: bool
    effective_recompute_reason: str
    next_preview: NextZonePreview
    intrabar_row: Any
    action_display: str
    confirmation_state: str


@dataclass(frozen=True)
class HoldingDisplayState:
    action_label: str
    action_helper: str
    increase_label: str
    increase_helper: str
    context_label: str
    context_helper: str
    group_label: str
    entry_display_state: str
    next_preview: NextZonePreview
    lifecycle_state: str
    recompute_needed: bool
    recompute_reason: str
    fresh_badge: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render static HTML dashboard for read-only position rotation preview."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--trading-account-id", type=int, default=2)
    parser.add_argument("--stale-days", type=Decimal, default=Decimal("1.0"))
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def dec_text(value: Decimal | None, places: str = "0.01") -> str:
    if value is None:
        return ""
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def eur_text(value: Decimal | None) -> str:
    if value is None:
        return "UNKNOWN"
    return f"€ {dec_text(value, '0.01')}"


def eur_html(value: Decimal | None) -> str:
    if value is None:
        return "<span class='muted'>UNKNOWN</span>"
    return esc(eur_text(value))


def age_minutes(ts: datetime | None, *, now_utc: datetime) -> Decimal | None:
    if ts is None:
        return None
    age_seconds = Decimal(str((now_utc.replace(tzinfo=None) - ts).total_seconds()))
    return age_seconds / Decimal("60")


def age_days(ts: datetime | None, *, now_utc: datetime) -> Decimal | None:
    minutes = age_minutes(ts, now_utc=now_utc)
    if minutes is None:
        return None
    return minutes / Decimal("1440")


def signed_pct_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    try:
        quantized = value.quantize(Decimal("0.01"))
    except Exception:
        quantized = value
    if quantized == 0:
        return "0.00%"
    if quantized > 0:
        return f"+{quantized}%"
    return f"{quantized}%"


def pct_class(value: Decimal | None) -> str:
    if value is None:
        return ""
    if value > 0:
        return "ok"
    if value < 0:
        return "warn"
    return "muted"


def distance_context(row: Any) -> str | None:
    leg_direction = str(row.leg_direction or "").upper()
    advice_action = str(row.advice_action or "").upper()
    rotation_state = str(row.rotation_state or "").upper()

    if (
        leg_direction == "DOWN"
        or advice_action == "DO_NOT_ADD"
        or "REDUCE" in rotation_state
        or "EXIT" in rotation_state
    ):
        return "down"
    if leg_direction == "UP":
        return "up"
    return None


def target_pct_class(value: Decimal | None, context: str | None) -> str:
    if value is None:
        return ""
    if context == "down":
        return "ok" if value < 0 else "warn" if value > 0 else "muted"
    if context == "up":
        return "ok" if value > 0 else "warn" if value < 0 else "muted"
    return pct_class(value)


def risk_pct_class(value: Decimal | None, context: str | None) -> str:
    if value is None:
        return ""
    if context == "down":
        return "bad" if value > 0 else "ok" if value < 0 else "muted"
    if context == "up":
        return "bad" if value < 0 else "ok" if value > 0 else "muted"
    return pct_class(value)


def pct_delta(reference: Decimal | None, current_price: Decimal | None) -> Decimal | None:
    if reference is None or current_price is None or current_price <= 0:
        return None
    return ((reference / current_price) - Decimal("1")) * Decimal("100")


def entry_delta_pct(
    *,
    entry_zone_low: Decimal | None,
    entry_zone_high: Decimal | None,
    current_price: Decimal | None,
) -> Decimal | None:
    if current_price is None or current_price <= 0:
        return None
    if entry_zone_low is None and entry_zone_high is None:
        return None
    if entry_zone_low is not None and entry_zone_high is not None:
        low = min(entry_zone_low, entry_zone_high)
        high = max(entry_zone_low, entry_zone_high)
        if low <= current_price <= high:
            return Decimal("0")
        if current_price < low:
            return pct_delta(low, current_price)
        return pct_delta(high, current_price)
    return pct_delta(entry_zone_low or entry_zone_high, current_price)


def midpoint_or_edge(low: Decimal | None, high: Decimal | None) -> Decimal | None:
    if low is not None and high is not None:
        return (low + high) / Decimal("2")
    if low is not None:
        return low
    return high


def pct_cell(value: Decimal | None, class_name: str | None = None) -> str:
    text = signed_pct_text(value)
    if not text:
        return "<td class='num'></td>"
    pill_class_name = class_name or pct_class(value)
    return f"<td class='num'><span class='pill {pill_class_name}'>{esc(text)}</span></td>"


def entry_distance_cell(
    *,
    leg_direction: Any,
    entry_zone_low: Decimal | None,
    entry_zone_high: Decimal | None,
    current_price: Decimal | None,
) -> str:
    if current_price is None or current_price <= 0:
        return "<td class='num'></td>"
    if entry_zone_low is None and entry_zone_high is None:
        return "<td class='num'></td>"

    low = entry_zone_low
    high = entry_zone_high
    if low is not None and high is not None:
        low, high = min(low, high), max(low, high)
    reference_low = low or high
    reference_high = high or low
    if reference_low is None or reference_high is None:
        return "<td class='num'></td>"

    leg = str(leg_direction or "").upper()
    zone_name = "reaction" if leg == "DOWN" else "entry"

    if reference_low <= current_price <= reference_high:
        return f"<td class='num'><span class='pill ok'>inside {zone_name}</span></td>"

    if current_price > reference_high:
        pct = ((current_price / reference_high) - Decimal("1")) * Decimal("100")
        css = "muted" if leg == "DOWN" else "warn"
        return (
            f"<td class='num'><span class='pill {css}'>"
            f"above {zone_name} {esc(signed_pct_text(pct))}</span></td>"
        )

    pct = ((current_price / reference_low) - Decimal("1")) * Decimal("100")
    css = "warn" if leg == "DOWN" else "muted"
    return (
        f"<td class='num'><span class='pill {css}'>"
        f"below {zone_name} {esc(signed_pct_text(pct))}</span></td>"
    )


def price_age_min(snapshot: MarketPriceSnapshot | None, *, now_utc: datetime) -> Decimal | None:
    if snapshot is None:
        return None
    return age_minutes(snapshot.observed_ts_utc, now_utc=now_utc)


def position_valuation(row: Any, current_price: Decimal | None) -> PositionValuation:
    quantity = row.quantity_base
    if quantity is None:
        return PositionValuation(value_eur=None, source="POSITION_QUANTITY_MISSING")
    if current_price is not None:
        return PositionValuation(
            value_eur=quantity * current_price,
            source="MARKET_PRICE_SNAPSHOT",
        )
    if row.position_mark_price_eur is not None:
        return PositionValuation(
            value_eur=quantity * row.position_mark_price_eur,
            source="ACCOUNT_POSITION_MARK_FALLBACK",
        )
    return PositionValuation(value_eur=None, source="VALUATION_UNKNOWN")


def now_local_label() -> str:
    now_utc = datetime.now(UTC)
    local = now_utc.astimezone(ZoneInfo("Europe/Amsterdam"))
    return local.strftime("%Y-%m-%d %H:%M:%S %Z")


def pill_class(text: str | None) -> str:
    value = (text or "").upper()
    if (
        "REDUCE" in value
        or "AVOID" in value
        or "DO_NOT_ADD" in value
        or "HIGH" in value
        or "HARD_BLOCK" in value
        or "CRITICAL_DATA_MISSING" in value
    ):
        return pill_classes("bad", value)
    if (
        "CAUTION" in value
        or "WATCH" in value
        or "REVIEW" in value
        or "MODERATE" in value
        or "TARGET_REACHED" in value
        or "TARGET_OVERSHOT" in value
        or "RISK_NEAR" in value
        or "INVALIDATION_NEAR" in value
        or "RECLAIM_NEAR" in value
        or "RECLAIM_CONFIRMED" in value
        or "DOWN_MAP_INVALIDATED_BY_RECLAIM" in value
        or "UP_MAP_INVALIDATED_BY_BREAKDOWN" in value
        or "ENTRY_ZONE_REACHED" in value
        or "REACTION_ZONE_REACHED" in value
        or "IN_ENTRY_ZONE" in value
        or "IN_REACTION_ZONE" in value
        or "ENTRY_ZONE_NEAR" in value
        or "REACTION_ZONE_NEAR" in value
        or "CONFIRMATION_PENDING" in value
        or "POST_ENTRY_PROGRESS" in value
        or "TARGET_APPROACHING" in value
        or "TARGET_NEAR" in value
        or "ENTRY_WINDOW_PASSED" in value
        or "CHASE_RISK" in value
        or "LATE_ENTRY_REVIEW" in value
        or "REACTION_PROGRESS" in value
        or "DOWNSIDE_TARGET_APPROACHING" in value
        or "DOWNSIDE_TARGET_NEAR" in value
        or "UPSIDE_EXTENSION_PREVIEW" in value
        or "DOWNSIDE_EXTENSION_PREVIEW" in value
        or "RECLAIM_RETEST_SUPPORT" in value
        or "NEXT_UPSIDE_REACTION_TARGET" in value
        or "TARGET_RETEST_SUPPORT" in value
        or "NEXT_UPSIDE_EXTENSION" in value
        or "DOWNSIDE_TARGET_SUPPORT_RETEST" in value
        or "NEXT_DOWNSIDE_EXTENSION" in value
        or "BREAKDOWN_RETEST_RESISTANCE" in value
        or "NEXT_DOWNSIDE_REACTION_TARGET" in value
        or "MOMENTUM_EXTENSION_REVIEW" in value
        or "RECLAIM_REVIEW" in value
        or "WAIT_FOR_RECLAIM" in value
        or "WAIT_FOR_PULLBACK" in value
        or "OPPORTUNITY_REVIEW" in value
        or "REFRESH_NEEDED_REVIEW" in value
        or "TARGET_REACHED_WAIT_FOR_REMAP" in value
        or "EXTENSION_REVIEW_NO_CHASE" in value
        or "WAIT_FOR_NEW_MAP" in value
        or "BLOCK_MARKET_DAMAGE" in value
        or "BLOCK_SETUP_FILTER_FAIL" in value
        or "BLOCK_RECOMPUTE_PENDING" in value
        or "BLOCK_CHASE_RISK" in value
        or "INTRABAR_TARGET_TOUCHED" in value
        or "INTRABAR_RECLAIM_TOUCHED" in value
        or "INTRABAR_EXTENSION_CONTINUING" in value
        or "INTRABAR_MONITOR_RECOMPUTE" in value
        or "MEDIUM_CONFIDENCE_DESTINATION" in value
        or "LOW_CONFIDENCE_DESTINATION" in value
        or "MARKET_ONLY_DESTINATION" in value
        or "MISSING_APLUS_CONTEXT" in value
        or "MISSING_CURVE_CONTEXT" in value
        or "MARKET_BREATH_UNKNOWN" in value
        or "STALE_APLUS_CONTEXT" in value
        or "APLUS_AVOID_OR_DISTORTED" in value
        or "WEAK_CURVE_STRUCTURE" in value
        or "WEAK_MARKET_BREATH_CONFIDENCE" in value
        or "WEAK_RELATIVE_STRENGTH" in value
        or "WEAK_MOMENTUM" in value
        or "CURVE_NEUTRAL" in value
        or "CURVE_WEAK" in value
    ):
        return pill_classes("warn", value)
    if (
        "INVALIDATION_TOUCHED" in value
        or "MAP_RECOMPUTE_NEEDED" in value
        or "RECLAIM_NEXT_ZONE_PREVIEW" in value
        or "BREAKDOWN_NEXT_ZONE_PREVIEW" in value
        or "NEXT_ZONE_UNKNOWN" in value
        or "CURVE_DOWN_PRESSURE" in value
        or "CURVE_FAILED_RECLAIM" in value
        or "CURVE_NO_UP_SIGNAL" in value
    ):
        return pill_classes("bad", value)
    if (
        "BLOCK_SELECTION_NOT_ELIGIBLE" in value
        or "BLOCK_INSUFFICIENT_SAMPLE" in value
        or "LEGACY_CONTEXT_ONLY" in value
        or "READ_ONLY_APLUS_AVOID_CONTEXT" in value
    ):
        return pill_classes("muted", value)
    if (
        "HOLD" in value
        or "CORE" in value
        or "FRESH" in value
        or "RISK_OK" in value
        or "ACTIVE_MAP" in value
        or "CURRENT_MAP_ACTIVE" in value
        or "MARKET_PRICE_SNAPSHOT" in value
        or "CONTEXT_ONLY" in value
        or "ACTIVE_REVIEW_CONTEXT" in value
        or "INTRABAR_ACTIVE" in value
        or "PRICE_SNAPSHOT_FRESH" in value
        or "LTF_CANDLES_FRESH" in value
        or "NO_INTRABAR_RECOMPUTE_HINT" in value
        or "HIGH_CONFIDENCE_DESTINATION" in value
        or "CURVE_UP_CONFIRMED" in value
    ):
        return pill_classes("ok", value)
    if (
        "SOFT_BLOCK" in value
        or "STALE_APLUS_CONTEXT" in value
        or "NO_CHASE_WITHOUT_NEW_ZONE" in value
        or "CURRENT_CAUTION_CONTEXT" in value
        or "INTRABAR_TARGET_OVERSHOT" in value
        or "INTRABAR_RECLAIM_CONFIRMED" in value
        or "INTRABAR_RECOMPUTE_REVIEW" in value
        or "PRICE_SNAPSHOT_STALE" in value
        or "LTF_CANDLES_STALE" in value
        or "LTF_HISTORY_SHORT" in value
    ):
        return pill_classes("warn", value)
    if (
        "INTRABAR_INVALIDATION_TOUCHED" in value
        or "INTRABAR_UNKNOWN" in value
        or "LTF_MISSING" in value
        or "STRUCTURAL_MAP_MISSING" in value
        or "NO_STRUCTURAL_MAP" in value
    ):
        return pill_classes("bad", value)
    if "ACCOUNT_POSITION_MARK_FALLBACK" in value:
        return pill_classes("warn", value)
    return pill_classes("muted", value)


TP_HARVEST_REVIEW_STATES = {
    "PARTIAL_TP_REVIEW",
    "TARGET_REACHED_REVIEW",
    "REDUCE_REVIEW_TARGET_REACHED",
}

TARGET_REACHED_LIFECYCLE_STATES = {
    "TARGET_REACHED",
    "TARGET_OVERSHOT",
    "TARGET_REACHED_STALE",
}

STALE_LIFECYCLE_STATES = {
    "MAP_RECOMPUTE_NEEDED",
    "TARGET_REACHED_STALE",
    "TARGET_OVERSHOT",
    "INVALIDATION_TOUCHED",
}

WARNING_LIFECYCLE_STATES = {
    "TARGET_REACHED",
    "INVALIDATION_NEAR",
    "RECLAIM_NEAR",
}

SOFT_POST_REFRESH_STATES = {
    "REFRESHED_THIS_RUN",
    "REFRESHED_RECENTLY",
    "COOLDOWN_MONITOR",
    "NO_REFRESH_NEEDED",
}

ACTIONABLE_POST_REFRESH_STATES = {
    "REFRESH_NEEDED",
    "RECOMPUTED_BUT_STILL_TRIGGERING",
    "REFRESH_FAILED_OR_STALE",
}

FRESH_MAP_THRESHOLD = timedelta(hours=6)


def has_target_reached_context(row: Any, lifecycle_state: str) -> bool:
    return (
        str(row.target_state or "").upper() == "TARGET_REACHED"
        or str(row.rotation_state or "").upper() in TP_HARVEST_REVIEW_STATES
        or lifecycle_state in TARGET_REACHED_LIFECYCLE_STATES
    )


def is_up_target_review_row(row: Any, lifecycle_state: str) -> bool:
    return str(row.leg_direction or "").upper() == "UP" and has_target_reached_context(
        row, lifecycle_state
    )


def is_downside_target_review_row(row: Any, lifecycle_state: str) -> bool:
    return str(row.leg_direction or "").upper() == "DOWN" and has_target_reached_context(
        row, lifecycle_state
    )


def is_reduce_exit_row(row: Any) -> bool:
    rotation_state = str(row.rotation_state or "").upper()
    return (
        rotation_state in {"EXIT_CANDIDATE", "REDUCE_CANDIDATE"}
        or "REDUCE" in rotation_state
        or "EXIT" in rotation_state
    )


def tp_zone_text(advice_or_row: Any) -> str:
    if isinstance(advice_or_row, dict):
        low = dec(advice_or_row.get("tp_zone_low"))
        high = dec(advice_or_row.get("tp_zone_high"))
    else:
        low = advice_or_row.tp_zone_low
        high = advice_or_row.tp_zone_high
    if low is None and high is None:
        return ""
    return f"{dec_text(low, '0.000000')}..{dec_text(high, '0.000000')}"


def as_utc_naive(ts: Any) -> datetime | None:
    if ts is None or not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(UTC).replace(tzinfo=None)


def fresh_map_badge(asof_ts: Any, *, now_utc: datetime, lifecycle_state: str) -> str:
    if lifecycle_state.upper() != "ACTIVE_MAP":
        return ""
    normalized = as_utc_naive(asof_ts)
    if normalized is None:
        return ""
    age = now_utc.replace(tzinfo=None) - normalized
    if timedelta(0) <= age <= FRESH_MAP_THRESHOLD:
        return "FRESH_MAP"
    return ""


def workflow_row_class(
    *,
    lifecycle_state: str,
    recompute_needed: bool,
    fresh_badge: str,
) -> str:
    state = lifecycle_state.upper()
    if recompute_needed or state in STALE_LIFECYCLE_STATES:
        return "stale-map"
    if state in WARNING_LIFECYCLE_STATES:
        return "warning-map"
    if fresh_badge:
        return "fresh-map"
    return ""


def lifecycle_badges_html(lifecycle_state: str, fresh_badge: str) -> str:
    badges = [
        f"<span class='pill {pill_class(lifecycle_state)}'>{esc(lifecycle_state)}</span>"
    ]
    if fresh_badge:
        badges.append(f"<span class='pill ok'>{esc(fresh_badge)}</span>")
    return "".join(badges)


def next_zone_html(preview: NextZonePreview) -> str:
    display_state = preview.next_zone_state
    display_reason = preview.next_zone_reason
    if preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}:
        display_state = "WAIT_RECOMPUTE"
        display_reason = "old map invalidated; wait for fresh map/advice"
    parts = [
        f"<span class='pill {pill_class(display_state)}'>{esc(display_state)}</span>"
    ]
    if preview.next_reaction_zone_label and preview.next_reaction_zone:
        parts.append(
            "<div class='small'>"
            f"<span class='pill {pill_class(preview.next_reaction_zone_label)}'>{esc(preview.next_reaction_zone_label)}</span> "
            f"<span class='zone-value'>{esc(format_zone(preview.next_reaction_zone))}</span>"
            "</div>"
        )
    if preview.next_target_zone_label and preview.next_target_zone:
        parts.append(
            "<div class='small'>"
            f"<span class='pill {pill_class(preview.next_target_zone_label)}'>{esc(preview.next_target_zone_label)}</span> "
            f"<span class='zone-value'>{esc(format_zone(preview.next_target_zone))}</span>"
            "</div>"
        )
    if display_reason:
        parts.append(f"<div class='muted small'>{esc(display_reason)}</div>")
    if preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}:
        parts.append("<div class='muted small'>Market context, not permission.</div>")
    return "".join(parts)


def has_retest_word(*values: str | None) -> bool:
    text = " ".join(str(value or "").upper() for value in values)
    return "RETEST" in text or "SUPPORT" in text


def explicit_reduce_context(
    *,
    row: Any,
    lifecycle_state: str,
    next_preview: NextZonePreview,
    intrabar_row: Any | None = None,
) -> bool:
    reason_codes = {str(code or "").upper() for code in getattr(row, "reason_codes", [])}
    rotation_state = str(row.rotation_state or "").upper()
    hold_context = str(row.hold_context_label or "").upper()
    intrabar_state = "" if intrabar_row is None else str(intrabar_row.intrabar_lifecycle_state or "").upper()
    return (
        str(row.target_state or "").upper() == "TARGET_REACHED"
        or str(row.risk_state or "").upper() in {"RISK_NEAR", "RECLAIM_CONFIRMED"}
        or lifecycle_state.upper() in {"TARGET_REACHED", "TARGET_REACHED_STALE", "TARGET_OVERSHOT", "INVALIDATION_NEAR"}
        or next_preview.next_zone_state == "UPSIDE_EXTENSION_PREVIEW"
        or intrabar_state == "TARGET_TOUCHED_RECENTLY"
        or rotation_state in TP_HARVEST_REVIEW_STATES
        or hold_context == "TARGET_REACHED_REVIEW"
        or "TARGET_REACHED" in reason_codes
    )


def explicit_exit_context(
    *,
    row: Any,
    lifecycle_state: str,
    next_preview: NextZonePreview,
) -> bool:
    reason_codes = {str(code or "").upper() for code in getattr(row, "reason_codes", [])}
    return (
        str(row.risk_state or "").upper() == "RECLAIM_CONFIRMED"
        or lifecycle_state.upper() == "INVALIDATION_TOUCHED"
        or next_preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}
        or "DOWN_MAP_INVALIDATED_BY_RECLAIM" in reason_codes
        or "UP_MAP_INVALIDATED_BY_BREAKDOWN" in reason_codes
    )


def intrabar_target_touch_active(intrabar_row: Any | None) -> bool:
    if intrabar_row is None:
        return False
    return str(intrabar_row.intrabar_lifecycle_state or "").upper() == "TARGET_TOUCHED_RECENTLY"


def intrabar_pullback_after_touch(intrabar_row: Any | None) -> bool:
    if intrabar_row is None:
        return False
    return str(intrabar_row.target_touch_context_label or "").upper() == "PULLBACK_AFTER_TARGET_TOUCH"


def intrabar_stale_for_decision(intrabar_row: Any | None) -> bool:
    if intrabar_row is None:
        return False
    return "STALE_FOR_INTRABAR_DECISION" in str(intrabar_row.data_quality_state or "").upper()


def display_context_state(raw_context: str | None, intrabar_row: Any | None = None) -> tuple[str, str]:
    if intrabar_target_touch_active(intrabar_row):
        if intrabar_pullback_after_touch(intrabar_row):
            helper = "target touched intrabar; current price may already have pulled back"
            if intrabar_stale_for_decision(intrabar_row):
                helper += " · stale for intrabar decision"
            return "PULLBACK_AFTER_TARGET_TOUCH", helper
        helper = "target touched intrabar on latest 15m candle"
        if intrabar_stale_for_decision(intrabar_row):
            helper += " · stale for intrabar decision"
        return "TARGET_TOUCHED_RECENTLY", helper
    value = str(raw_context or "").upper()
    if value == "HOLD_WITH_REACTION_TARGET_PENDING":
        return "HOLD_MONITOR_TARGET", "hold and monitor reaction/target context"
    if value == "TARGET_REACHED_REVIEW":
        return "TARGET_REACHED_CONTEXT", "target reached context; downstream permission still required"
    if not value:
        return "NONE", ""
    return value, ""


def display_increase_state(
    *,
    add_permission_state: str | None,
    add_block_reason: str | None,
    entry_display_state: str,
    intrabar_row: Any | None = None,
) -> tuple[str, str]:
    if intrabar_target_touch_active(intrabar_row):
        helper = "target touched intrabar; current price may already have pulled back"
        if intrabar_stale_for_decision(intrabar_row):
            helper += " · stale for intrabar decision"
        return "NO_INCREASE", helper
    raw_state = str(add_permission_state or "").upper()
    entry_state = str(entry_display_state or "").upper()
    if raw_state == "DO_NOT_ADD":
        return "NO_INCREASE", "do not increase this position"
    if raw_state == "ADD_REVIEW_AFTER_RECOMPUTE":
        return "WAIT_RECOMPUTE_FOR_INCREASE", "wait for fresh map/advice"
    if raw_state == "ADD_REVIEW":
        if entry_state in {"IN_ENTRY_ZONE", "IN_REACTION_ZONE", "ENTRY_ZONE_NEAR", "REACTION_ZONE_NEAR"}:
            return "INCREASE_CANDIDATE", "increase requires downstream permission"
        return "WAIT_RETEST", "wait for price to return to support/entry zone"
    if str(add_block_reason or "").upper() == "RECLAIM_CONFIRMED":
        return "WAIT_RECOMPUTE_FOR_INCREASE", "wait for fresh map/advice"
    return "NO_INCREASE", "do not increase this position"


def display_action_state(
    *,
    row: Any,
    lifecycle_state: str,
    next_preview: NextZonePreview,
    intrabar_row: Any | None = None,
) -> tuple[str, str]:
    raw_state = str(row.rotation_state or "").upper()
    if intrabar_target_touch_active(intrabar_row):
        helper = "target touched intrabar; current price may already have pulled back"
        if intrabar_stale_for_decision(intrabar_row):
            helper += " · stale for intrabar decision"
        return "MANUAL_REDUCE_CHECK", helper
    if raw_state == "RECLAIM_CONFIRMED_REVIEW" or next_preview.next_zone_state in {
        "RECLAIM_NEXT_ZONE_PREVIEW",
        "BREAKDOWN_NEXT_ZONE_PREVIEW",
    }:
        return "WAIT_RECOMPUTE", "wait for fresh map/advice"
    if raw_state == "EXIT_CANDIDATE":
        if explicit_exit_context(row=row, lifecycle_state=lifecycle_state, next_preview=next_preview):
            return "MANUAL_EXIT_CHECK", "manual decision required, not automatic sell"
        if explicit_reduce_context(
            row=row,
            lifecycle_state=lifecycle_state,
            next_preview=next_preview,
            intrabar_row=intrabar_row,
        ):
            return "MANUAL_REDUCE_CHECK", "manual decision required, not automatic sell"
        return "HOLD_DEFENSIVE", "keep existing position, defensive context"
    if raw_state == "REDUCE_CANDIDATE":
        if explicit_reduce_context(
            row=row,
            lifecycle_state=lifecycle_state,
            next_preview=next_preview,
            intrabar_row=intrabar_row,
        ):
            return "MANUAL_REDUCE_CHECK", "manual decision required, not automatic sell"
        return "HOLD_DEFENSIVE", "keep existing position, defensive context"
    if raw_state in TP_HARVEST_REVIEW_STATES:
        return "MANUAL_REDUCE_CHECK", "manual decision required, not automatic sell"
    if raw_state in {"HOLD_REVIEW_STALE_SOURCE", "REDUCE_REVIEW_CANDIDATE_STALE_SOURCE", "NO_POSITION_CONTEXT"}:
        return "WAIT_RECOMPUTE", "wait for fresh map/advice"
    if "REVIEW" in raw_state:
        return "HOLD_DEFENSIVE", "keep existing position, defensive context"
    return "HOLD_DEFENSIVE", "keep existing position, defensive context"


def display_group_label(*, action_label: str, increase_label: str) -> str:
    if action_label == "MANUAL_EXIT_CHECK":
        return "EXIT CANDIDATES"
    if action_label == "MANUAL_REDUCE_CHECK":
        return "MANUAL CHECK"
    if action_label.startswith("WAIT_") or increase_label.startswith("WAIT_"):
        return "WAIT"
    if increase_label == "INCREASE_CANDIDATE":
        return "INCREASE CANDIDATES"
    return "HOLD"


def target_display_label(
    *,
    current_price: Decimal | None,
    zone: tuple[Decimal, Decimal] | None,
    next_preview: NextZonePreview,
) -> tuple[str, str]:
    if next_preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}:
        return "WAIT_RECOMPUTE", "old map invalidated; wait for fresh map/advice"
    if zone is None or current_price is None:
        return "TARGET", ""
    midpoint = (zone[0] + zone[1]) / Decimal("2")
    if midpoint <= current_price:
        label = (
            "RETEST_ZONE_BELOW"
            if has_retest_word(next_preview.next_reaction_zone_label, next_preview.next_target_zone_label)
            else "SUPPORT_BELOW"
        )
        return label, "below-price support/retest context, not TP"
    return "UPSIDE_REACTION_TARGET", "above-price reaction target context"


def target_alignment_display_label(
    *,
    alignment_label: str | None,
    current_price: Decimal | None,
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    next_preview: NextZonePreview,
) -> tuple[str, str]:
    zone_values = [value for value in (zone_low, zone_high) if value is not None]
    if not zone_values:
        return str(alignment_label or "TARGET_UNKNOWN"), "target context"
    zone = (
        min(zone_values),
        max(zone_values),
    )
    return target_display_label(current_price=current_price, zone=zone, next_preview=next_preview)


def relevant_target_html(
    *,
    leg_direction: Any,
    tp_zone_low: Decimal | None,
    tp_zone_high: Decimal | None,
    current_price: Decimal | None,
    next_preview: NextZonePreview,
    delta_target_pct: Decimal | None,
    intrabar_row: Any | None = None,
) -> str:
    if next_preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}:
        return (
            "<div><span class='pill warn'>WAIT_RECOMPUTE</span></div>"
            "<div class='muted small'>old map invalidated; wait for fresh map/advice</div>"
        )
    if intrabar_target_touch_active(intrabar_row):
        details: list[str] = [
            "<div><span class='pill warn'>TARGET_TOUCHED_RECENTLY</span></div>",
            "<div><span class='pill warn'>EXTENSION_TOUCHED_INTRABAR</span></div>",
        ]
        if intrabar_pullback_after_touch(intrabar_row):
            details.append("<div><span class='pill warn'>PULLBACK_AFTER_TARGET_TOUCH</span></div>")
        touched_value = None if intrabar_row is None else intrabar_row.touched_high_or_low
        touch_age = None if intrabar_row is None else intrabar_row.target_touch_age_minutes
        meta_parts: list[str] = []
        if touched_value is not None:
            meta_parts.append(f"touched high/low {dec_text(touched_value, '0.000000')}")
        if touch_age is not None:
            meta_parts.append(f"age {dec_text(touch_age, '0.1')} min")
        if intrabar_stale_for_decision(intrabar_row):
            meta_parts.append("STALE_FOR_INTRABAR_DECISION")
        details.append("<div class='muted small'>target touched intrabar; current price may already have pulled back</div>")
        if meta_parts:
            details.append(f"<div class='muted small'>{esc(' · '.join(meta_parts))}</div>")
        return "".join(details)

    if next_preview.next_target_zone_label and next_preview.next_target_zone:
        zone = next_preview.next_target_zone
        distance_text = signed_pct_text(
            pct_delta(
                (zone[0] + zone[1]) / Decimal("2"),
                current_price,
            )
        )
    else:
        zone_values = [value for value in (tp_zone_low, tp_zone_high) if value is not None]
        zone_text = tp_zone_text({"tp_zone_low": tp_zone_low, "tp_zone_high": tp_zone_high})
        if not zone_text:
            return "<span class='muted'>—</span>"
        zone = None if not zone_values else (min(zone_values), max(zone_values))
        distance_text = signed_pct_text(delta_target_pct)
    zone_text = format_zone(zone) if zone is not None else zone_text
    label, helper = target_display_label(
        current_price=current_price,
        zone=zone,
        next_preview=next_preview,
    )

    distance_html = "" if not distance_text else f"<div class='muted small'>distance: {esc(distance_text)}</div>"
    return (
        f"<div><span class='pill {pill_class(label)}'>{esc(label)}</span></div>"
        f"<div class='zone-value'>{esc(zone_text)}</div>"
        f"<div class='muted small'>{esc(helper)}</div>"
        f"{distance_html}"
    )


def severity_html(severity: Any) -> str:
    return (
        f"<div><span class='pill {pill_class(severity.advice_severity)}'>{esc(severity.advice_severity)}</span></div>"
        f"<div><span class='pill {pill_class(severity.advice_substate)}'>{esc(severity.advice_substate)}</span></div>"
        f"<div class='muted small'>{esc(severity.display_note)}</div>"
    )


def intrabar_html(row: Any | None) -> str:
    if row is None:
        return "<span class='muted small'>not available</span>"
    quality = "".join(
        f"<span class='pill {pill_class(part)}'>{esc(part)}</span>"
        for part in str(row.data_quality_state or "").split(";")
        if part
    )
    touch = ""
    if row.target_touch_label:
        touch += f"<div><span class='pill {pill_class(row.target_touch_label)}'>{esc(row.target_touch_label)}</span></div>"
    if row.target_touch_context_label:
        touch += f"<div><span class='pill {pill_class(row.target_touch_context_label)}'>{esc(row.target_touch_context_label)}</span></div>"
    if row.touched_high_or_low is not None or row.target_touch_age_minutes is not None:
        meta_parts: list[str] = []
        if row.touched_high_or_low is not None:
            meta_parts.append(f"touched high/low={dec_text(row.touched_high_or_low, '0.000000')}")
        if row.target_touch_age_minutes is not None:
            meta_parts.append(f"touch age={dec_text(row.target_touch_age_minutes, '0.1')}m")
        touch += f"<div class='muted small'>{esc(' · '.join(meta_parts))}</div>"
    return (
        f"<div><span class='pill {pill_class(row.intrabar_lifecycle_state)}'>{esc(row.intrabar_lifecycle_state)}</span></div>"
        f"<div><span class='pill {pill_class(row.intrabar_recompute_hint)}'>{esc(row.intrabar_recompute_hint)}</span></div>"
        f"{touch}"
        f"<div class='muted small'>source={esc(row.price_source)} · 15m={esc(row.latest_15m_close_ts_utc or 'missing')}</div>"
        f"<div>{quality}</div>"
        "<div class='muted small'>Intrabar context, not trade advice.</div>"
    )


def alignment_html(
    *,
    label: str | None,
    distance_pct: Decimal | None,
    band_flag: bool,
    note: str,
) -> str:
    if not label:
        return "<span class='muted small'>unknown</span>"
    details: list[str] = []
    if distance_pct is not None:
        details.append(f"fib dist {dec_text(distance_pct, '0.01')}%")
    if band_flag:
        details.append("band match")
    details.append(note)
    detail_html = ""
    if details:
        detail_html = f"<div class='muted small'>{esc(' · '.join(details))}</div>"
    return f"<span class='pill {pill_class(label)}'>{esc(label)}</span>{detail_html}"


def fetch_latest_eur_balance_snapshot(
    conn: Any,
    *,
    trading_account_id: int,
) -> EurBalanceSnapshot | None:
    sql = """
    SELECT
        available_amount,
        reserved_amount,
        total_amount,
        snapshot_ts_utc
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %(trading_account_id)s
      AND currency_code = 'EUR'
    ORDER BY snapshot_ts_utc DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"trading_account_id": int(trading_account_id)})
        row = cur.fetchone()
    if not row:
        return None
    return EurBalanceSnapshot(
        available_amount=dec(row.get("available_amount")) or Decimal("0"),
        reserved_amount=dec(row.get("reserved_amount")) or Decimal("0"),
        total_amount=dec(row.get("total_amount")) or Decimal("0"),
        snapshot_ts_utc=row.get("snapshot_ts_utc"),
    )


def render_html(
    rows: list[Any],
    *,
    venue: str,
    quote_currency: str,
    interval: str,
    account_id: int,
    price_by_symbol: dict[str, MarketPriceSnapshot],
    eur_balance: EurBalanceSnapshot | None,
    advice_by_symbol: dict[str, dict[str, Any]],
    market_breath_by_symbol: dict[str, dict[str, Any]] | None = None,
    intrabar_by_symbol: dict[str, Any] | None = None,
) -> str:
    local_ts = now_local_label()
    now_utc = datetime.now(UTC)

    current_price_by_symbol = {
        symbol: snapshot.price
        for symbol, snapshot in price_by_symbol.items()
    }
    valuation_by_symbol = {
        row.position_symbol: position_valuation(
            row,
            current_price_by_symbol.get(row.position_symbol),
        )
        for row in rows
    }
    known_position_values = [
        valuation.value_eur
        for valuation in valuation_by_symbol.values()
        if valuation.value_eur is not None
    ]
    positions_value_current = sum(known_position_values, Decimal("0"))
    total_eur_cash = None if eur_balance is None else eur_balance.total_amount
    indicative_account_value = (
        None
        if total_eur_cash is None
        else positions_value_current + total_eur_cash
    )
    position_snapshot_age_days = age_days(
        max(
            (row.position_snapshot_ts_utc for row in rows if row.position_snapshot_ts_utc is not None),
            default=None,
        ),
        now_utc=now_utc,
    )
    balance_snapshot_age_min = None if eur_balance is None else age_minutes(
        eur_balance.snapshot_ts_utc,
        now_utc=now_utc,
    )

    def lifecycle_for_row(row: Any) -> Any:
        return classify_fast_lifecycle(
            leg_direction=row.leg_direction,
            current_price=current_price_by_symbol.get(row.position_symbol),
            tp_zone_low=row.tp_zone_low,
            tp_zone_high=row.tp_zone_high,
            invalidation_price=row.invalidation_price,
        )

    held_row_by_symbol = {row.position_symbol: row for row in rows}
    ranked_candidates = rank_market_candidates(advice_by_symbol, current_price_by_symbol)
    recompute_rows = build_recompute_rows(
        list(advice_by_symbol.values()),
        venue=venue,
        interval=interval,
        price_by_symbol=price_by_symbol,
    )
    recompute_row_by_symbol = {row.symbol.upper(): row for row in recompute_rows}

    post_refresh_counts: dict[str, int] = {}
    display_severity_counts: dict[str, int] = {}
    for row in recompute_rows:
        post_refresh_counts[row.post_refresh_state] = post_refresh_counts.get(row.post_refresh_state, 0) + 1
        display_severity_counts[row.display_severity] = display_severity_counts.get(row.display_severity, 0) + 1

    def recompute_row_for_symbol(symbol: str) -> Any | None:
        return recompute_row_by_symbol.get(str(symbol or "").upper())

    def post_refresh_is_soft(row: Any | None) -> bool:
        if row is None:
            return False
        return (
            row.post_refresh_state in SOFT_POST_REFRESH_STATES
            and row.display_severity in {"DISPLAY_CONTEXT", "DISPLAY_WATCH", "DISPLAY_MUTED"}
        )

    def effective_recompute_context(symbol: str, lifecycle: Any) -> tuple[str, bool, str]:
        refresh_row = recompute_row_for_symbol(symbol)
        if post_refresh_is_soft(refresh_row):
            return "ACTIVE_MAP", False, refresh_row.post_refresh_state
        return lifecycle.lifecycle_state, lifecycle.recompute_needed, lifecycle.recompute_reason

    def recompute_label_for_symbol(symbol: str, lifecycle: Any) -> str:
        refresh_row = recompute_row_for_symbol(symbol)
        if post_refresh_is_soft(refresh_row) or (
            refresh_row is not None and refresh_row.post_refresh_state in ACTIONABLE_POST_REFRESH_STATES
        ):
            return refresh_row.post_refresh_state
        return "MAP_RECOMPUTE_NEEDED" if lifecycle.recompute_needed else "ACTIVE_MAP"

    def lifecycle_badges_for_symbol(symbol: str, lifecycle_state: str, fresh_badge: str) -> str:
        refresh_row = recompute_row_for_symbol(symbol)
        badges = lifecycle_badges_html(lifecycle_state, fresh_badge)
        if refresh_row is not None:
            badges += (
                f"<div><span class='pill {pill_class(refresh_row.post_refresh_state)}'>"
                f"{esc(refresh_row.post_refresh_state)}</span></div>"
            )
        return badges

    def display_state_for_row(row: Any) -> HoldingDisplayState:
        current_price = current_price_by_symbol.get(row.position_symbol)
        intrabar_row = (intrabar_by_symbol or {}).get(row.position_symbol)
        lifecycle = lifecycle_for_row(row)
        effective_lifecycle_state, effective_recompute_needed, effective_recompute_reason = effective_recompute_context(
            row.position_symbol, lifecycle
        )
        fresh_badge = fresh_map_badge(
            row.paper_asof_ts_utc,
            now_utc=now_utc,
            lifecycle_state=effective_lifecycle_state,
        )
        price_progress = classify_price_progress_state(
            leg_direction=row.leg_direction,
            current_price=current_price,
            entry_zone_low=row.entry_zone_low,
            entry_zone_high=row.entry_zone_high,
            tp_zone_low=row.tp_zone_low,
            tp_zone_high=row.tp_zone_high,
            in_position_context=True,
        )
        entry_display_state = semantic_entry_display_state(
            entry_state=classify_entry_zone_state(
                leg_direction=row.leg_direction,
                current_price=current_price,
                entry_zone_low=row.entry_zone_low,
                entry_zone_high=row.entry_zone_high,
            ),
            price_progress_state=price_progress.progress_state,
            price_progress_labels=price_progress.labels,
        )
        next_preview = preview_next_zones(
            symbol=row.position_symbol,
            leg_direction=row.leg_direction,
            current_price=current_price,
            entry_zone_low=row.entry_zone_low,
            entry_zone_high=row.entry_zone_high,
            tp_zone_low=row.tp_zone_low,
            tp_zone_high=row.tp_zone_high,
            invalidation_price=row.invalidation_price,
            lifecycle_state=lifecycle.lifecycle_state,
            lifecycle_reason=lifecycle.recompute_reason,
            target_state=row.target_state,
            price_progress_state=price_progress.progress_state,
        )
        action_label, action_helper = display_action_state(
            row=row,
            lifecycle_state=effective_lifecycle_state,
            next_preview=next_preview,
            intrabar_row=intrabar_row,
        )
        increase_label, increase_helper = display_increase_state(
            add_permission_state=row.add_permission_state,
            add_block_reason=row.add_block_reason,
            entry_display_state=entry_display_state,
            intrabar_row=intrabar_row,
        )
        context_label, context_helper = display_context_state(row.hold_context_label, intrabar_row)
        group_label = display_group_label(
            action_label=action_label,
            increase_label=increase_label,
        )
        return HoldingDisplayState(
            action_label=action_label,
            action_helper=action_helper,
            increase_label=increase_label,
            increase_helper=increase_helper,
            context_label=context_label,
            context_helper=context_helper,
            group_label=group_label,
            entry_display_state=entry_display_state,
            next_preview=next_preview,
            lifecycle_state=effective_lifecycle_state,
            recompute_needed=effective_recompute_needed,
            recompute_reason=effective_recompute_reason,
            fresh_badge=fresh_badge,
        )

    display_state_by_symbol = {
        row.position_symbol: display_state_for_row(row)
        for row in rows
    }
    group_counts: dict[str, int] = {}
    for row in rows:
        group = display_state_by_symbol[row.position_symbol].group_label
        group_counts[group] = group_counts.get(group, 0) + 1

    hold_rows = [r for r in rows if display_state_by_symbol[r.position_symbol].group_label == "HOLD"]
    wait_rows = [r for r in rows if display_state_by_symbol[r.position_symbol].group_label == "WAIT"]
    manual_rows = [r for r in rows if display_state_by_symbol[r.position_symbol].group_label == "MANUAL CHECK"]
    increase_rows = [
        r for r in rows if display_state_by_symbol[r.position_symbol].group_label == "INCREASE CANDIDATES"
    ]
    exit_rows = [
        r for r in rows if display_state_by_symbol[r.position_symbol].group_label == "EXIT CANDIDATES"
    ]

    def destination_eligibility_for_candidate(symbol: str) -> DestinationEligibility:
        context = candidate_destination_context(symbol)
        block_display = classify_policy_block_display(
            context.advice,
            lifecycle_state=context.effective_lifecycle_state,
            recompute_needed=context.effective_recompute_needed,
            recompute_reason=context.effective_recompute_reason,
            target_state=context.target_state,
            entry_state=context.entry_display_state,
            price_progress_state=context.price_progress.progress_state,
            market_breath_row=(market_breath_by_symbol or {}).get(symbol),
        )
        return evaluate_rotation_destination_eligibility(
            context.advice,
            current_price=context.current_price,
            target_state=context.target_state,
            risk_state=context.risk_state,
            lifecycle_state=context.effective_lifecycle_state,
            recompute_needed=context.effective_recompute_needed,
            recompute_reason=context.effective_recompute_reason,
            policy_label=None if block_display is None else block_display.display_policy_label,
            action_label=context.action_display,
            entry_state=context.entry_display_state,
            price_progress_state=context.price_progress.progress_state,
            price_progress_labels=context.price_progress.labels,
            next_zone_state=context.next_preview.next_zone_state,
            next_reaction_zone_label=context.next_preview.next_reaction_zone_label,
            next_target_zone_label=context.next_preview.next_target_zone_label,
            next_target_zone=context.next_preview.next_target_zone,
            intrabar_lifecycle_state=(
                None if context.intrabar_row is None else context.intrabar_row.intrabar_lifecycle_state
            ),
            intrabar_recompute_hint=(
                None if context.intrabar_row is None else context.intrabar_row.intrabar_recompute_hint
            ),
            intrabar_data_quality_state=(
                None if context.intrabar_row is None else context.intrabar_row.data_quality_state
            ),
        )

    def candidate_destination_context(symbol: str) -> CandidateDestinationContext:
        advice = advice_by_symbol.get(symbol)
        latest_price = price_by_symbol.get(symbol)
        current_price = None if latest_price is None else latest_price.price
        target_state = target_state_for_advice(advice, current_price)
        risk_state = risk_state_for_advice(advice, current_price)
        entry_state = classify_entry_zone_state(
            leg_direction=None if not advice else advice.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=None if not advice else advice.get("entry_zone_low"),
            entry_zone_high=None if not advice else advice.get("entry_zone_high"),
        )
        price_progress = classify_price_progress_state(
            leg_direction=None if not advice else advice.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=None if not advice else advice.get("entry_zone_low"),
            entry_zone_high=None if not advice else advice.get("entry_zone_high"),
            tp_zone_low=None if not advice else advice.get("tp_zone_low"),
            tp_zone_high=None if not advice else advice.get("tp_zone_high"),
            in_position_context=held_row_by_symbol.get(symbol) is not None,
        )
        entry_display_state = semantic_entry_display_state(
            entry_state=entry_state,
            price_progress_state=price_progress.progress_state,
            price_progress_labels=price_progress.labels,
        )
        confirmation_state = confirmation_display_state(
            advice_action=None if not advice else advice.get("advice_action"),
            policy_decision=None if not advice else advice.get("policy_decision"),
            entry_state=entry_state,
            price_progress_state=price_progress.progress_state,
            price_progress_labels=price_progress.labels,
        )
        invalidation_price = None if not advice else dec(advice.get("invalidation_price"))
        lifecycle = classify_fast_lifecycle(
            leg_direction=None if not advice else advice.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=None if not advice else advice.get("tp_zone_low"),
            tp_zone_high=None if not advice else advice.get("tp_zone_high"),
            invalidation_price=invalidation_price,
        )
        effective_lifecycle_state, effective_recompute_needed, effective_recompute_reason = effective_recompute_context(
            symbol, lifecycle
        )
        next_preview = preview_next_zones(
            symbol=symbol,
            leg_direction=None if not advice else advice.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=None if not advice else advice.get("entry_zone_low"),
            entry_zone_high=None if not advice else advice.get("entry_zone_high"),
            tp_zone_low=None if not advice else advice.get("tp_zone_low"),
            tp_zone_high=None if not advice else advice.get("tp_zone_high"),
            invalidation_price=invalidation_price,
            lifecycle_state=lifecycle.lifecycle_state,
            lifecycle_reason=lifecycle.recompute_reason,
            target_state=target_state,
            price_progress_state=price_progress.progress_state,
        )
        intrabar_row = (intrabar_by_symbol or {}).get(symbol)
        action_display = semantic_advice_action_display(
            advice_action=None if not advice else advice.get("advice_action"),
            lifecycle_state=lifecycle.lifecycle_state,
            intrabar_state=None if intrabar_row is None else intrabar_row.intrabar_lifecycle_state,
        )
        return CandidateDestinationContext(
            advice=advice,
            current_price=current_price,
            target_state=target_state,
            risk_state=risk_state,
            entry_state=entry_state,
            entry_display_state=entry_display_state,
            price_progress=price_progress,
            lifecycle=lifecycle,
            effective_lifecycle_state=effective_lifecycle_state,
            effective_recompute_needed=effective_recompute_needed,
            effective_recompute_reason=effective_recompute_reason,
            next_preview=next_preview,
            intrabar_row=intrabar_row,
            action_display=action_display,
            confirmation_state=confirmation_state,
        )

    def destination_confidence_for_candidate(symbol: str) -> DestinationConfidence:
        context = candidate_destination_context(symbol)
        return destination_confidence(
            context.advice,
            market_breath_row=(market_breath_by_symbol or {}).get(symbol),
            target_state=context.target_state,
            risk_state=context.risk_state,
            lifecycle_state=context.effective_lifecycle_state,
            recompute_reason=context.effective_recompute_reason,
            price_progress_state=context.price_progress.progress_state,
            price_progress_labels=context.price_progress.labels,
            next_zone_state=context.next_preview.next_zone_state,
            next_reaction_zone_label=context.next_preview.next_reaction_zone_label,
            next_target_zone_label=context.next_preview.next_target_zone_label,
            confirmation_state=context.confirmation_state,
        )

    def destination_confidence_html(confidence: DestinationConfidence) -> str:
        evidence = "".join(
            f"<span class='pill {pill_class(label)}'>{esc(label)}</span>"
            for label in confidence.evidence_labels
        )
        return (
            f"<span class='pill {pill_class(confidence.confidence_label)}'>"
            f"{esc(confidence.confidence_label)}</span>"
            "<div class='small'>"
            f"<span class='pill {pill_class(confidence.curve_sanity_label)}'>"
            f"{esc(confidence.curve_sanity_label)}</span>"
            "</div>"
            f"<div>{evidence}</div>"
        )

    def strict_rotation_destinations_for_row(row: Any, *, max_items: int = 3) -> list[str]:
        current_quality = market_candidate_quality_score(
            advice_by_symbol.get(row.position_symbol)
        )
        destinations: list[str] = []
        for symbol, candidate_score in ranked_candidates:
            if symbol == row.position_symbol:
                continue
            if candidate_score <= current_quality:
                continue
            eligibility = destination_eligibility_for_candidate(symbol)
            confidence = destination_confidence_for_candidate(symbol)
            if eligibility.eligible and confidence.clean_actionable:
                destinations.append(
                    f"{symbol}:{candidate_score.quantize(Decimal('0.01'))}:{confidence.confidence_label}/{confidence.curve_sanity_label}"
                )
            if len(destinations) >= max_items:
                break
        return destinations

    def table_rows(table_rows: list[Any]) -> str:
        out = []
        for row in table_rows:
            review_refs = ", ".join(row.review_references[:3]) if row.review_references else ""
            strict_destinations = strict_rotation_destinations_for_row(row)
            destinations = ", ".join(strict_destinations) if strict_destinations else ""
            destinations_html = (
                esc(destinations)
                if destinations
                else "<span class='muted'>No actionable destination</span>"
            )
            latest_price = price_by_symbol.get(row.position_symbol)
            current_price = None if latest_price is None else latest_price.price
            latest_price_age_min = price_age_min(latest_price, now_utc=now_utc)
            valuation = valuation_by_symbol.get(
                row.position_symbol,
                PositionValuation(value_eur=None, source="VALUATION_UNKNOWN"),
            )
            delta_tp_pct = pct_delta(
                midpoint_or_edge(row.tp_zone_low, row.tp_zone_high),
                current_price,
            )
            delta_invalidation_pct = pct_delta(row.invalidation_price, current_price)
            context = distance_context(row)
            display_state = display_state_by_symbol[row.position_symbol]
            lifecycle = lifecycle_for_row(row)
            effective_lifecycle_state = display_state.lifecycle_state
            effective_recompute_needed = display_state.recompute_needed
            effective_recompute_reason = display_state.recompute_reason
            fresh_badge = display_state.fresh_badge
            row_class = workflow_row_class(
                lifecycle_state=effective_lifecycle_state,
                recompute_needed=effective_recompute_needed,
                fresh_badge=fresh_badge,
            )
            price_progress = classify_price_progress_state(
                leg_direction=row.leg_direction,
                current_price=current_price,
                entry_zone_low=row.entry_zone_low,
                entry_zone_high=row.entry_zone_high,
                tp_zone_low=row.tp_zone_low,
                tp_zone_high=row.tp_zone_high,
                in_position_context=True,
            )
            entry_display_state = display_state.entry_display_state
            progress_labels = "".join(
                f"<span class='pill {pill_class(label)}'>{esc(label)}</span>"
                for label in price_progress.labels
            )
            progress_html = (
                f"<span class='pill {pill_class(price_progress.progress_state)}'>{esc(price_progress.progress_state)}</span>"
                f"{progress_labels}"
            )
            next_preview = display_state.next_preview
            severity = calibrate_paper_advice_severity(
                row,
                market_breath_row=(market_breath_by_symbol or {}).get(row.position_symbol),
                lifecycle_state=effective_lifecycle_state,
                recompute_needed=effective_recompute_needed,
                recompute_reason=effective_recompute_reason,
                target_state=row.target_state,
                risk_state=row.risk_state,
                price_progress_state=price_progress.progress_state,
            )
            intrabar_row = (intrabar_by_symbol or {}).get(row.position_symbol)
            action_display = semantic_advice_action_display(
                advice_action=row.advice_action,
                lifecycle_state=lifecycle.lifecycle_state,
                intrabar_state=None if intrabar_row is None else intrabar_row.intrabar_lifecycle_state,
            )
            block_display = classify_policy_block_display(
                row,
                lifecycle_state=effective_lifecycle_state,
                recompute_needed=effective_recompute_needed,
                recompute_reason=effective_recompute_reason,
                target_state=row.target_state,
                entry_state=entry_display_state,
                price_progress_state=price_progress.progress_state,
                market_breath_row=(market_breath_by_symbol or {}).get(row.position_symbol),
                extra_reason_codes=list(row.reason_codes),
            )
            action_label = action_display
            action_class = pill_class(action_display)
            action_detail = f"policy/action: {esc(row.advice_action)}"
            if block_display is not None:
                action_label = block_display.display_policy_label
                action_class = pill_class(block_display.display_policy_label)
                action_detail = block_reason_summary_text(block_display)
            target_html = relevant_target_html(
                leg_direction=row.leg_direction,
                tp_zone_low=row.tp_zone_low,
                tp_zone_high=row.tp_zone_high,
                current_price=current_price,
                next_preview=next_preview,
                delta_target_pct=delta_tp_pct,
                intrabar_row=intrabar_row,
            )
            target_alignment_label, target_alignment_note = target_alignment_display_label(
                alignment_label=row.tp_alignment_label,
                current_price=current_price,
                zone_low=row.tp_zone_low,
                zone_high=row.tp_zone_high,
                next_preview=next_preview,
            )
            raw_action_detail = f"raw: {row.position_management_state} / {row.rotation_state}"
            raw_increase_detail = f"raw: {row.add_permission_state}"
            if row.add_block_reason:
                raw_increase_detail += f" · {row.add_block_reason}"
            raw_context_detail = f"raw: {row.hold_context_label or 'NONE'}"

            out.append(
                f"<tr class='{row_class}'>"
                f"<td class='sticky-symbol'><strong>{esc(row.position_symbol)}</strong></td>"
                f"<td class='num'>{esc(dec_text(valuation.value_eur, '0.01'))}</td>"
                f"<td><span class='pill {pill_class(valuation.source)}'>{esc(valuation.source)}</span></td>"
                f"<td class='num'>{esc(dec_text(row.quantity_base, '0.000000'))}</td>"
                f"<td><span class='pill {pill_class(row.position_source_state)}'>{esc(row.position_source_state)}</span></td>"
                f"<td class='num'>{esc(dec_text(row.position_source_age_days, '0.01'))}</td>"
                f"<td>{esc(row.selection_state)}</td>"
                f"<td><span class='pill {pill_class(row.setup_filter_reason)}'>{esc(row.setup_filter_reason)}</span></td>"
                f"<td>{esc(row.leg_direction)}</td>"
                f"<td><span class='pill {action_class}'>{esc(action_label)}</span><div class='muted small'>{esc(action_detail)}</div></td>"
                f"<td><span class='pill {pill_class(row.aplus_bucket)}'>{esc(row.aplus_bucket)}</span></td>"
                f"<td>{severity_html(severity)}</td>"
                f"<td>{intrabar_html(intrabar_row)}</td>"
                f"<td class='num sticky-price'>{esc(dec_text(current_price, '0.000000'))}</td>"
                f"<td class='num'>{esc(dec_text(latest_price_age_min, '0.1'))}</td>"
                f"<td><span class='pill {pill_class(entry_display_state)}'>{esc(entry_display_state)}</span><div>{progress_html}</div></td>"
                f"<td><span class='pill {pill_class(row.target_state)}'>{esc(row.target_state)}</span></td>"
                f"<td><span class='pill {pill_class(row.risk_state)}'>{esc(row.risk_state)}</span></td>"
                f"<td>{lifecycle_badges_for_symbol(row.position_symbol, lifecycle.lifecycle_state, fresh_badge)}</td>"
                f"<td><span class='pill {pill_class(recompute_label_for_symbol(row.position_symbol, lifecycle))}'>{esc(recompute_label_for_symbol(row.position_symbol, lifecycle))}</span></td>"
                f"<td class='small'>{esc(effective_recompute_reason)}</td>"
                f"<td><span class='pill {pill_class(display_state.action_label)}'>{esc(display_state.action_label)}</span><div class='muted small'>{esc(display_state.action_helper)}</div><div class='muted small'>{esc(raw_action_detail)}</div></td>"
                f"<td><span class='pill {pill_class(display_state.increase_label)}'>{esc(display_state.increase_label)}</span><div class='muted small'>{esc(display_state.increase_helper)}</div><div class='muted small'>{esc(raw_increase_detail)}</div></td>"
                f"<td><span class='pill {pill_class(display_state.context_label)}'>{esc(display_state.context_label)}</span><div class='muted small'>{esc(display_state.context_helper)}</div><div class='muted small'>{esc(raw_context_detail)}</div></td>"
                f"<td>{alignment_html(label=row.entry_alignment_label, distance_pct=row.entry_fib_distance_pct, band_flag=bool(row.entry_is_fib_band), note='fib-based entry zone' if row.entry_alignment_label == 'ENTRY_FIB_PRIMARY_0500_0618' else 'entry context')}</td>"
                f"<td>{alignment_html(label=target_alignment_label, distance_pct=row.tp_fib_distance_pct, band_flag=bool(row.tp_is_fib_extension_band), note=target_alignment_note)}</td>"
                f"<td>{next_zone_html(next_preview)}</td>"
                f"{entry_distance_cell(leg_direction=row.leg_direction, entry_zone_low=row.entry_zone_low, entry_zone_high=row.entry_zone_high, current_price=current_price)}"
                f"{pct_cell(delta_tp_pct, target_pct_class(delta_tp_pct, context))}"
                f"{pct_cell(delta_invalidation_pct, risk_pct_class(delta_invalidation_pct, context))}"
                f"<td class='zone-value sticky-target'>{target_html}</td>"
                f"<td><span class='pill {pill_class(display_state.group_label)}'>{esc(display_state.group_label)}</span><div class='muted small'>raw: {esc(row.rotation_state)}</div></td>"
                f"<td class='num'>{esc(row.rotation_pressure_score)}</td>"
                f"<td class='small'>{esc(review_refs)}</td>"
                f"<td class='small'>{destinations_html}</td>"
                "</tr>"
            )
        return "\n".join(out)

    def candidate_diagnostic_rows() -> str:
        out = []
        for rank, (symbol, candidate_score) in enumerate(ranked_candidates, start=1):
            advice = advice_by_symbol.get(symbol)
            held_row = held_row_by_symbol.get(symbol)
            latest_price = price_by_symbol.get(symbol)
            current_price = None if latest_price is None else latest_price.price
            target_state = target_state_for_advice(advice, current_price)
            risk_state = risk_state_for_advice(advice, current_price)
            entry_state = classify_entry_zone_state(
                leg_direction=None if not advice else advice.get("leg_direction"),
                current_price=current_price,
                entry_zone_low=None if not advice else advice.get("entry_zone_low"),
                entry_zone_high=None if not advice else advice.get("entry_zone_high"),
            )
            price_progress = classify_price_progress_state(
                leg_direction=None if not advice else advice.get("leg_direction"),
                current_price=current_price,
                entry_zone_low=None if not advice else advice.get("entry_zone_low"),
                entry_zone_high=None if not advice else advice.get("entry_zone_high"),
                tp_zone_low=None if not advice else advice.get("tp_zone_low"),
                tp_zone_high=None if not advice else advice.get("tp_zone_high"),
                in_position_context=held_row is not None,
            )
            progress_labels = "".join(
                f"<span class='pill {pill_class(label)}'>{esc(label)}</span>"
                for label in price_progress.labels
            )
            progress_html = (
                f"<span class='pill {pill_class(price_progress.progress_state)}'>{esc(price_progress.progress_state)}</span>"
                f"{progress_labels}"
            )
            entry_display_state = semantic_entry_display_state(
                entry_state=entry_state,
                price_progress_state=price_progress.progress_state,
                price_progress_labels=price_progress.labels,
            )
            confirm_state = confirmation_display_state(
                advice_action=None if not advice else advice.get("advice_action"),
                policy_decision=None if not advice else advice.get("policy_decision"),
                entry_state=entry_state,
                price_progress_state=price_progress.progress_state,
                price_progress_labels=price_progress.labels,
            )
            eligibility = destination_eligibility_for_candidate(symbol)
            confidence = destination_confidence_for_candidate(symbol)
            exclusions = eligibility.exclusion_reasons
            eligible = eligibility.eligible
            held_valuation = (
                None
                if held_row is None
                else valuation_by_symbol.get(
                    held_row.position_symbol,
                    PositionValuation(value_eur=None, source="VALUATION_UNKNOWN"),
                )
            )
            held_value = None if held_valuation is None else held_valuation.value_eur
            held_rotation_state = "" if held_row is None else held_row.rotation_state
            invalidation_price = None if not advice else dec(advice.get("invalidation_price"))
            lifecycle = classify_fast_lifecycle(
                leg_direction=None if not advice else advice.get("leg_direction"),
                current_price=current_price,
                tp_zone_low=None if not advice else advice.get("tp_zone_low"),
                tp_zone_high=None if not advice else advice.get("tp_zone_high"),
                invalidation_price=invalidation_price,
            )
            effective_lifecycle_state, effective_recompute_needed, effective_recompute_reason = effective_recompute_context(
                symbol, lifecycle
            )
            fresh_badge = fresh_map_badge(
                None if not advice else advice.get("asof_ts_utc"),
                now_utc=now_utc,
                lifecycle_state=effective_lifecycle_state,
            )
            row_class = workflow_row_class(
                lifecycle_state=effective_lifecycle_state,
                recompute_needed=effective_recompute_needed,
                fresh_badge=fresh_badge,
            )
            next_preview = preview_next_zones(
                symbol=symbol,
                leg_direction=None if not advice else advice.get("leg_direction"),
                current_price=current_price,
                entry_zone_low=None if not advice else advice.get("entry_zone_low"),
                entry_zone_high=None if not advice else advice.get("entry_zone_high"),
                tp_zone_low=None if not advice else advice.get("tp_zone_low"),
                tp_zone_high=None if not advice else advice.get("tp_zone_high"),
                invalidation_price=invalidation_price,
                lifecycle_state=lifecycle.lifecycle_state,
                lifecycle_reason=lifecycle.recompute_reason,
                target_state=target_state,
                price_progress_state=price_progress.progress_state,
            )
            severity = calibrate_paper_advice_severity(
                advice,
                market_breath_row=(market_breath_by_symbol or {}).get(symbol),
                lifecycle_state=effective_lifecycle_state,
                recompute_needed=effective_recompute_needed,
                recompute_reason=effective_recompute_reason,
                target_state=target_state,
                risk_state=risk_state,
                entry_state=entry_state,
                price_progress_state=price_progress.progress_state,
            )
            intrabar_row = (intrabar_by_symbol or {}).get(symbol)
            action_display = semantic_advice_action_display(
                advice_action=None if not advice else advice.get("advice_action"),
                lifecycle_state=lifecycle.lifecycle_state,
                intrabar_state=None if intrabar_row is None else intrabar_row.intrabar_lifecycle_state,
            )
            candidate_block_display = classify_policy_block_display(
                advice,
                lifecycle_state=effective_lifecycle_state,
                recompute_needed=effective_recompute_needed,
                recompute_reason=effective_recompute_reason,
                target_state=target_state,
                entry_state=entry_display_state,
                price_progress_state=price_progress.progress_state,
                market_breath_row=(market_breath_by_symbol or {}).get(symbol),
                extra_reason_codes=exclusions,
            )
            candidate_action_label = action_display
            candidate_action_class = pill_class(action_display)
            candidate_action_detail = f"policy/action: {esc(None if not advice else advice.get('advice_action'))}"
            candidate_policy_html = esc(None if not advice else advice.get("advice_state"))
            if candidate_block_display is not None:
                candidate_action_label = candidate_block_display.display_policy_label
                candidate_action_class = pill_class(candidate_block_display.display_policy_label)
                candidate_action_detail = block_reason_summary_text(candidate_block_display)
                candidate_policy_html = (
                    f"<span class='pill {pill_class(candidate_block_display.display_policy_label)}'>{esc(candidate_block_display.display_policy_label)}</span>"
                    f"<div class='muted small'>raw: {esc(candidate_block_display.raw_policy_state)}</div>"
                    f"<div class='muted small'>cause: {esc(candidate_block_display.block_primary_reason)}</div>"
                    f"<div class='muted small'>unblock: {esc(candidate_block_display.unblock_condition_label)}</div>"
                )
            candidate_target_html = relevant_target_html(
                leg_direction=None if not advice else advice.get("leg_direction"),
                tp_zone_low=None if not advice else dec(advice.get("tp_zone_low")),
                tp_zone_high=None if not advice else dec(advice.get("tp_zone_high")),
                current_price=current_price,
                next_preview=next_preview,
                delta_target_pct=pct_delta(
                    midpoint_or_edge(
                        None if not advice else dec(advice.get("tp_zone_low")),
                        None if not advice else dec(advice.get("tp_zone_high")),
                    ),
                    current_price,
                ),
                intrabar_row=intrabar_row,
            )

            out.append(
                f"<tr class='{row_class}'>"
                f"<td class='num'>{rank}</td>"
                f"<td class='sticky-symbol'><strong>{esc(symbol)}</strong></td>"
                f"<td class='num'>{esc(dec_text(candidate_score, '0.01'))}</td>"
                f"<td><span class='pill {'ok' if eligible else 'bad'}'>{'YES' if eligible else 'NO'}</span></td>"
                f"<td>{destination_confidence_html(confidence)}</td>"
                f"<td class='small'>{esc(', '.join(exclusions))}</td>"
                f"<td>{esc(None if not advice else advice.get('selection_state'))}</td>"
                f"<td>{esc(None if not advice else advice.get('setup_filter_state'))}</td>"
                f"<td><span class='pill {pill_class(None if not advice else advice.get('setup_filter_reason'))}'>{esc(None if not advice else advice.get('setup_filter_reason'))}</span></td>"
                f"<td>{candidate_policy_html}</td>"
                f"<td><span class='pill {candidate_action_class}'>{esc(candidate_action_label)}</span><div class='muted small'>{esc(candidate_action_detail)}</div></td>"
                f"<td>{severity_html(severity)}</td>"
                f"<td>{intrabar_html(intrabar_row)}</td>"
                f"<td>{esc(None if not advice else advice.get('leg_direction'))}</td>"
                f"<td><span class='pill {pill_class(entry_display_state)}'>{esc(entry_display_state)}</span><div class='muted small'>raw: {esc(entry_state)}</div></td>"
                f"<td>{progress_html}</td>"
                f"<td><span class='pill {pill_class(confirm_state)}'>{esc(confirm_state)}</span></td>"
                f"<td><span class='pill {pill_class(target_state)}'>{esc(target_state)}</span></td>"
                f"<td><span class='pill {pill_class(risk_state)}'>{esc(risk_state)}</span></td>"
                f"<td class='num sticky-price'>{esc(dec_text(current_price, '0.000000'))}</td>"
                f"<td>{lifecycle_badges_for_symbol(symbol, lifecycle.lifecycle_state, fresh_badge)}</td>"
                f"<td><span class='pill {pill_class(recompute_label_for_symbol(symbol, lifecycle))}'>{esc(recompute_label_for_symbol(symbol, lifecycle))}</span></td>"
                f"<td class='small'>{esc(effective_recompute_reason)}</td>"
                f"<td>{next_zone_html(next_preview)}</td>"
                f"<td class='zone-value sticky-target'>{candidate_target_html}</td>"
                f"<td class='num zone-value'>{esc(dec_text(invalidation_price, '0.000000'))}</td>"
                f"<td><span class='pill {'ok' if held_row is not None else 'muted'}'>{'YES' if held_row is not None else 'NO'}</span></td>"
                f"<td class='num'>{esc(dec_text(held_value, '0.01'))}</td>"
                f"<td><span class='pill {pill_class(held_rotation_state)}'>{esc(held_rotation_state)}</span></td>"
                "</tr>"
            )
        return "\n".join(out)

    def candidate_diagnostics_section() -> str:
        return f"""
        <section class="card priority">
          <h2>Rotation candidate diagnostics <span class="muted">({len(ranked_candidates)})</span></h2>
          <div class="table-wrap">
            <table class="sticky-table">
              <thead class="sticky-header">
                <tr>
                  <th>Rank</th>
                  <th class="sticky-symbol">Symbol</th>
                  <th>Market ref score</th>
                  <th>Destination eligible</th>
                  <th>Destination confidence</th>
                  <th>Exclusion reasons</th>
                  <th>Selection</th>
                  <th>Setup</th>
                  <th>Setup reason</th>
                  <th>Policy</th>
                  <th>Status</th>
                  <th>Severity / Substate</th>
                  <th>Intrabar lifecycle</th>
                  <th>Leg</th>
                  <th>Entry state</th>
                  <th>Price progress</th>
                  <th>Confirmation</th>
                  <th>Target state</th>
                  <th>Risk state</th>
                  <th class="sticky-price">Current price</th>
                  <th>Lifecycle state</th>
                  <th>Recompute needed</th>
                  <th>Recompute reason</th>
                  <th>Next zones</th>
                  <th class="sticky-target">Relevant target</th>
                  <th>Invalidation</th>
                  <th>Held</th>
                  <th>Held value €</th>
                  <th>Held rotation state</th>
                </tr>
              </thead>
              <tbody>
                {candidate_diagnostic_rows()}
              </tbody>
            </table>
          </div>
        </section>
        """

    def recompute_lifecycle_section() -> str:
        return f"""
        <section class="card priority">
          <h2>Maps needing refresh <span class="muted">({len(recompute_rows)})</span></h2>
          <p class="muted small">Refresh candidate, not trade advice. Market-only worklist for stale, finished, reclaimed, or invalidated maps.</p>
          {render_recompute_rows_table(recompute_rows, limit=20)}
        </section>
        """

    def section(title: str, table_rows_data: list[Any], class_name: str = "") -> str:
        section_class = f"card {class_name}".strip()
        return f"""
        <section class="{esc(section_class)}">
          <h2>{esc(title)} <span class="muted">({len(table_rows_data)})</span></h2>
          <div class="table-wrap">
            <table class="sticky-table">
              <thead class="sticky-header">
                <tr>
                  <th class="sticky-symbol">Symbol</th>
                  <th>Value €</th>
                  <th>Valuation source</th>
                  <th>Qty</th>
                  <th>Source</th>
                  <th>Age d</th>
                  <th>Selection</th>
                  <th>Setup reason</th>
                  <th>Leg</th>
                  <th>Policy</th>
                  <th>A+</th>
                  <th>Severity / Substate</th>
                  <th>Intrabar lifecycle</th>
                  <th class="sticky-price">Current price</th>
                  <th>Price age min</th>
                  <th>Price progress</th>
                  <th>Target state</th>
                  <th>Risk state</th>
                  <th>Lifecycle state</th>
                  <th>Recompute needed</th>
                  <th>Recompute reason</th>
                  <th>Status</th>
                  <th>Increase</th>
                  <th>Context</th>
                  <th>Entry align</th>
                  <th>Target align</th>
                  <th>Next zones</th>
                  <th>Entry distance</th>
                  <th>Δ target %</th>
                  <th>Δ risk %</th>
                  <th class="sticky-target">Relevant target</th>
                  <th>Group</th>
                  <th>Rotation score</th>
                  <th>Market review refs</th>
                  <th>Rotation destinations</th>
                </tr>
              </thead>
              <tbody>
                {table_rows(table_rows_data)}
              </tbody>
            </table>
          </div>
        </section>
        """

    counts_html = "".join(
        f"<span class='pill {pill_class(k)}'>{esc(k)}: {v}</span>"
        for k, v in sorted(group_counts.items())
    )
    post_refresh_counts_html = "".join(
        f"<span class='pill {pill_class(k)}'>{esc(k)}: {v}</span>"
        for k, v in sorted(post_refresh_counts.items())
    )
    display_severity_counts_html = "".join(
        f"<span class='pill {pill_class(k)}'>{esc(k)}: {v}</span>"
        for k, v in sorted(display_severity_counts.items())
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Portfolio Cockpit</title>
  <style>
    {cockpit_base_css(min_table_width=2450)}
  </style>
</head>
<body>
  <header>
    <h1>Portfolio Cockpit</h1>
    <div class="muted">Rendered {esc(local_ts)} Amsterdam time</div>
    <div class="muted">portefeuille / rotatie / huidige holdings</div>
    <div class="muted">venue={esc(venue)} · quote={esc(quote_currency)} · interval={esc(interval)} · trading_account_id={esc(account_id)}</div>
    {cockpit_nav()}
    <div class="legend">
      <div><strong>Read-only dashboard. No row is an order instruction. Sell/increase requires downstream permission. MANUAL CHECK means user decision needed; HOLD/WAIT means no manual trade action implied.</strong></div>
      <div><strong>HOLD_DEFENSIVE</strong> = keep existing position, defensive context</div>
      <div><strong>HOLD_MONITOR_TARGET</strong> = hold and monitor reaction/target context</div>
      <div><strong>TARGET_TOUCHED_RECENTLY</strong> = latest 15m wick touched the target zone; current price may no longer be at the touch level.</div>
      <div><strong>PULLBACK_AFTER_TARGET_TOUCH</strong> = latest 15m wick touched the target zone and current price is back away from it.</div>
      <div><strong>EXTENSION_TOUCHED_INTRABAR</strong> = intrabar wick reached the mapped extension/target zone.</div>
      <div><strong>STALE_FOR_INTRABAR_DECISION</strong> = latest 15m target-touch context is older than 5 minutes and should be treated cautiously.</div>
      <div><strong>NO_INCREASE</strong> = do not increase this position</div>
      <div><strong>WAIT_RECOMPUTE</strong> = wait for fresh map/advice</div>
      <div><strong>WAIT_RETEST</strong> = wait for price to return to support/entry zone</div>
      <div><strong>SUPPORT_BELOW / RETEST_ZONE_BELOW</strong> = below-price support/retest context, not TP</div>
      <div><strong>MANUAL_REDUCE_CHECK</strong> = manual decision required, not automatic sell</div>
      <div><strong>MANUAL_EXIT_CHECK</strong> = manual decision required, not automatic sell</div>
      <div><strong>UP target reached</strong> = upside target context for existing long/upside maps.</div>
      <div><strong>DOWN target reached</strong> = downside target/support reached; not long TP.</div>
      <div><strong>Rotation score</strong> = account-position review pressure score.</div>
      <div><strong>Market review refs</strong> = market-only comparison scores, not buy advice.</div>
      <div><strong>Rotation destinations</strong> = stricter filtered candidates.</div>
      <div><strong>Market review refs are broad comparison assets. Rotation destinations are stricter actionable-review candidates, not trade advice.</strong></div>
      <div><strong>Rotation destination confidence includes market structure plus available A+/curve context. Missing A+ lowers confidence; it is not trade advice.</strong></div>
      <div><strong>Curve sanity checks whether the destination has visible up-confirmation. Weak/down-pressure curves lower destination confidence; not trade advice.</strong></div>
      <div><strong>Market ref score</strong> = market-only comparison score.</div>
      <div><strong>Destination eligible</strong> = strict candidate after paper/setup/risk/account-position filters.</div>
      <div><strong>Exclusion reasons</strong> explain why a strong reference is not a destination.</div>
      <div><strong>Target reached rows</strong> are harvest/review candidates, not automatic sell orders.</div>
      <div><strong>ENTRY_ZONE_REACHED</strong> is separate from target state and is not buy permission.</div>
      <div><strong>Entry distance</strong> is leg-aware display context. Above-entry BUY gaps are warnings, not green opportunity labels.</div>
      <div><strong>Price progress</strong> shows where current price sits between entry/reaction zone and target. TARGET_PENDING can still be true while TARGET_NEAR is shown.</div>
      <div><strong>ACTIVE_MAP</strong> means the map is still valid, not that entry or target was reached.</div>
      <div><strong>Fast lifecycle candles</strong> check whether the existing map is touched, stale, invalidated, or near reclaim. They do not create a new strategy map.</div>
      <div><strong>Recompute needed</strong> means the existing map may be stale. It is not a trade instruction, does not imply buy/sell, and indicates the strategy/advice map should be refreshed.</div>
      <div><strong>Fresh green rows</strong> = newly updated/fresh map context.</div>
      <div><strong>Red rows</strong> = stale, invalidated, or recompute-needed map context.</div>
      <div><strong>Dimmed labels</strong> in red/stale rows are old-map context; bright red/orange labels are the current lifecycle/recompute reason.</div>
      <div><strong>Next zones</strong>: Next zones are market-only preview zones after a map is stale, reclaimed, invalidated, or target-finished. They are not orders, allocation advice, or execution intent.</div>
      <div><strong>Market context is not trade permission.</strong> Policy blocks and next-zone previews can coexist.</div>
      <div><strong>Positions value</strong> uses latest market_price_snapshot when available, with ACCOUNT_POSITION_MARK_FALLBACK only when current market price is missing. Asset positions only; excludes EUR cash.</div>
      <div><strong>Maps needing refresh</strong> are refresh candidates, not trade advice.</div>
      <div><strong>Post-refresh state</strong> separates old trigger labels from current display state. Refreshed and cooldown rows stay visible as context/watch, while failed, stale, and still-triggering rows remain critical.</div>
      <div><strong>Severity / Substate</strong> separates hard blocks, stale A+ context, reclaim review, wait-for-reclaim, and momentum-extension review. These labels are review context, not trade advice.</div>
      <div><strong>Intrabar lifecycle</strong> is a 15m/current-price overlay against the current 4h structural map. It is context only and does not change decisions or execution.</div>
    </div>
    <div class="grid">
      <div class="metric"><div class="muted">Rows</div><h2>{len(rows)}</h2></div>
      <div class="metric"><div class="muted">Positions value</div><h2>{eur_html(positions_value_current)}</h2><div class="muted small">Asset positions only; excludes EUR cash. Position snapshot age: {esc(dec_text(position_snapshot_age_days, '0.01'))} d</div></div>
      <div class="metric"><div class="muted">Free EUR cash</div><h2>{eur_html(None if eur_balance is None else eur_balance.available_amount)}</h2><div class="muted small">Balance snapshot age: {esc(dec_text(balance_snapshot_age_min, '0.1'))} min</div></div>
      <div class="metric"><div class="muted">Reserved EUR cash</div><h2>{eur_html(None if eur_balance is None else eur_balance.reserved_amount)}</h2></div>
      <div class="metric"><div class="muted">Total EUR cash</div><h2>{eur_html(total_eur_cash)}</h2></div>
      <div class="metric"><div class="muted">Indicative account value</div><h2>{eur_html(indicative_account_value)}</h2><div class="muted small">Positions value + Total EUR cash when EUR balance is known.</div></div>
      <div class="metric"><div class="muted">Display groups</div>{counts_html}</div>
      <div class="metric"><div class="muted">Recompute state counts</div><h2>{len(recompute_rows)}</h2><div>{post_refresh_counts_html}</div><div class="muted small">{display_severity_counts_html}</div></div>
      <div class="metric"><div class="muted">Safety</div><span class="pill ok">broker_private_calls=0</span><span class="pill ok">broker_writes=0</span><span class="pill ok">order_submission=0</span><span class="pill ok">executor=none</span></div>
    </div>
  </header>
  <main>
    {recompute_lifecycle_section()}
    {candidate_diagnostics_section()}
    {section("EXIT CANDIDATES", exit_rows)}
    {section("MANUAL CHECK", manual_rows)}
    {section("WAIT", wait_rows, "downside")}
    {section("INCREASE CANDIDATES", increase_rows, "priority")}
    {section("HOLD", hold_rows, "harvest")}
  </main>
</body>
</html>
"""


def write_index(output_dir: Path) -> Path:
    local_ts = now_local_label()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "index.html"
    target.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Cockpit</title>
  <style>
    body {{ margin:0; background:#0b1020; color:#e7edf8; font-family:system-ui,-apple-system,Segoe UI,sans-serif; }}
    main {{ padding:32px; max-width:1000px; margin:auto; }}
    h1 {{ margin-top:0; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; }}
    .card {{ background:#121a2f; border:1px solid #273657; border-radius:16px; padding:20px; box-shadow:0 12px 40px rgba(0,0,0,.22); }}
    a {{ color:#7aa2ff; font-size:20px; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .muted {{ color:#8ea0bf; }}
    .pill {{ display:inline-block; border-radius:999px; padding:4px 9px; margin:4px 4px 0 0; border:1px solid #273657; color:#55d6a7; }}
    .cockpit-nav {{ display:flex; flex-wrap:wrap; gap:14px; margin:14px 0 18px; }}
    .cockpit-nav a {{ font-size:16px; }}
  </style>
</head>
<body>
  <main>
    <h1>Synth MVP Read-only Cockpit</h1>
    <p class="muted">Rendered {esc(local_ts)} Amsterdam time</p>
    {cockpit_nav()}
    <p><span class="pill">broker_private_calls=0</span><span class="pill">broker_writes=0</span><span class="pill">order_submission=0</span><span class="pill">executor=none</span></p>
    <div class="grid">
      <div class="card">
        <a href="/synth/paper-advice.html">Paper Advice</a>
        <p class="muted">Market/setup/A+ context and paper navigation.</p>
      </div>
      <div class="card">
        <a href="/synth/entry-candidates.html">Entry Candidates</a>
        <p class="muted">Market-only setup candidates and readiness groups.</p>
      </div>
      <div class="card">
        <a href="/synth/rotation-preview.html">Rotation Preview</a>
        <p class="muted">Account-aware read-only HOLD / WAIT / manual-check dashboard.</p>
      </div>
    </div>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return target


def main() -> int:
    args = parse_args()

    conn = get_connection()
    try:
        position_rows = fetch_latest_position_rows(
            conn,
            venue=args.venue,
            trading_account_id=args.trading_account_id,
            limit=args.limit,
        )
        advice_by_symbol = fetch_latest_paper_advice_rows(
            conn,
            venue=args.venue,
            interval=args.interval,
        )
        price_symbols = sorted(
            {
                *(str(row["symbol"]).upper() for row in position_rows),
                *advice_by_symbol.keys(),
            }
        )
        price_by_symbol = fetch_latest_prices_by_symbol(
            conn,
            venue=args.venue,
            quote_currency=args.quote,
            symbols=price_symbols,
        )
        market_breath_rows = build_market_breath_context_rows(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            symbols=price_symbols,
        )
        market_breath_by_symbol = market_breath_rows_by_symbol(market_breath_rows)
        intrabar_rows = build_intrabar_lifecycle_context_rows(
            conn,
            venue=args.venue,
            quote_currency=args.quote,
            structural_interval_code=args.interval,
            symbols=price_symbols,
        )
        intrabar_by_symbol = intrabar_rows_by_symbol(intrabar_rows)
        zone_fib_context_by_symbol = fetch_zone_fib_context_by_symbol(
            conn,
            position_rows=position_rows,
            advice_by_symbol=advice_by_symbol,
            venue=args.venue,
            interval=args.interval,
        )
        eur_balance = fetch_latest_eur_balance_snapshot(
            conn,
            trading_account_id=args.trading_account_id,
        )
    finally:
        conn.close()

    rows = build_rows(
        position_rows,
        advice_by_symbol,
        stale_days=args.stale_days,
        current_price_by_symbol={
            symbol: snapshot.price
            for symbol, snapshot in price_by_symbol.items()
        },
        zone_fib_context_by_symbol=zone_fib_context_by_symbol,
    )

    output_path = Path(args.output_html)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_html(
            rows,
            venue=args.venue,
            quote_currency=args.quote.upper(),
            interval=args.interval,
            account_id=args.trading_account_id,
            price_by_symbol=price_by_symbol,
            eur_balance=eur_balance,
            advice_by_symbol=advice_by_symbol,
            market_breath_by_symbol=market_breath_by_symbol,
            intrabar_by_symbol=intrabar_by_symbol,
        ),
        encoding="utf-8",
    )
    index_path = write_index(output_path.parent)

    if args.output == "summary":
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print("scope=read-only account-aware static dashboard")
        print("broker_private_calls=0 broker_writes=0 order_submission=0 executor=none")
        print(f"market_price_snapshot_rows={len(price_by_symbol)} quote={args.quote.upper()}")
        print(f"rows={len(rows)} output_html={output_path}")
        print(f"index_html={index_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
