from __future__ import annotations

import argparse
import html
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.common.db import get_connection
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
from src.reporting.next_zone_preview_v1 import (
    NextZonePreview,
    format_zone,
    preview_next_zones,
)
from src.reporting.policy_block_reason_display_v1 import (
    block_reason_summary_text,
    classify_policy_block_display,
)


REPORT_NAME = "entry_candidate_static_dashboard_v1"
REPORT_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "/var/www/html/synth/entry-candidates.html"

CANDIDATE_GROUPS = [
    "PAPER_BUY_READY",
    "WATCH_FOR_CONFIRMATION",
    "RECLAIM_NEAR",
    "BLOCKED_NO_NEW_BUY",
    "CONTEXT_ONLY",
    "INSUFFICIENT_SAMPLE",
]

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

FRESH_MAP_THRESHOLD = timedelta(hours=6)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render market-only entry/setup candidates to a static read-only HTML dashboard."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output", choices=("summary", "json", "none"), default="summary")
    return parser.parse_args()


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def dec_text(value: Any, places: str = "0.000000") -> str:
    dec = to_decimal(value)
    if dec is None:
        return ""
    try:
        return str(dec.quantize(Decimal(places)))
    except Exception:
        return str(dec)


def pct_text(value: Any) -> str:
    dec = to_decimal(value)
    if dec is None:
        return ""
    return f"{(dec * Decimal('100')).quantize(Decimal('0.1'))}%"


def bool_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "YES" if value else "NO"
    text = str(value).strip().upper()
    if text in {"1", "TRUE", "YES", "Y"}:
        return "YES"
    if text in {"0", "FALSE", "NO", "N"}:
        return "NO"
    return text


def parse_reason_codes(raw: Any) -> list[str]:
    if raw is None:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return [str(raw)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    if isinstance(parsed, dict):
        return [f"{key}={value}" for key, value in parsed.items()]
    return [str(parsed)]


def fmt_zone(low: Any, high: Any) -> str:
    left = dec_text(low)
    right = dec_text(high)
    if not left and not right:
        return ""
    if left == right:
        return left
    return f"{left}..{right}"


def has_required_zones(row: dict[str, Any]) -> bool:
    return (
        (row.get("entry_zone_low") is not None or row.get("entry_zone_high") is not None)
        and (row.get("tp_zone_low") is not None or row.get("tp_zone_high") is not None)
        and row.get("invalidation_price") is not None
    )


def css_class(value: str | None) -> str:
    normalized = (value or "").upper()
    if normalized in {"PAPER_BUY_READY", "PASS", "UP", "WATCHLIST", "YES", "BUY_READY", "ALLOW"}:
        return pill_classes("ok", normalized)
    if normalized in {
        "WATCH_FOR_CONFIRMATION",
        "RECLAIM_NEAR",
        "WATCH",
        "WATCH_ONLY",
        "MODERATE",
        "BLOCK_MARKET_DAMAGE",
        "BLOCK_SETUP_FILTER_FAIL",
        "BLOCK_RECOMPUTE_PENDING",
        "BLOCK_CHASE_RISK",
    }:
        return pill_classes("warn", normalized)
    if normalized in {
        "TARGET_REACHED",
        "TARGET_OVERSHOT",
        "TARGET_REACHED_STALE",
        "INVALIDATION_NEAR",
        "RECLAIM_NEAR",
        "ENTRY_ZONE_REACHED",
        "REACTION_ZONE_REACHED",
        "IN_ENTRY_ZONE",
        "IN_REACTION_ZONE",
        "ENTRY_ZONE_NEAR",
        "REACTION_ZONE_NEAR",
        "CONFIRMATION_PENDING",
        "POST_ENTRY_PROGRESS",
        "TARGET_APPROACHING",
        "TARGET_NEAR",
        "ENTRY_WINDOW_PASSED",
        "CHASE_RISK",
        "LATE_ENTRY_REVIEW",
        "REACTION_PROGRESS",
        "DOWNSIDE_TARGET_APPROACHING",
        "DOWNSIDE_TARGET_NEAR",
    }:
        return pill_classes("warn", normalized)
    if normalized in {
        "BLOCKED_NO_NEW_BUY",
        "FAIL",
        "AVOID",
        "APLUS_AVOID",
        "DO_NOT_ADD",
        "AVOID_NO_NEW_BUY",
        "MARKET_DAMAGE_RISK",
        "HIGH",
        "ELEVATED",
        "DOWN",
        "NO",
        "INVALIDATION_TOUCHED",
        "RECLAIM_CONFIRMED",
        "MAP_RECOMPUTE_NEEDED",
        "DOWN_MAP_INVALIDATED_BY_RECLAIM",
        "UP_MAP_INVALIDATED_BY_BREAKDOWN",
        "RECLAIM_NEXT_ZONE_PREVIEW",
        "BREAKDOWN_NEXT_ZONE_PREVIEW",
        "NEXT_ZONE_UNKNOWN",
        "BLOCK_POLICY_UNCLASSIFIED",
    }:
        return pill_classes("bad", normalized)
    if normalized in {
        "UPSIDE_EXTENSION_PREVIEW",
        "DOWNSIDE_EXTENSION_PREVIEW",
        "RECLAIM_RETEST_SUPPORT",
        "NEXT_UPSIDE_REACTION_TARGET",
        "TARGET_RETEST_SUPPORT",
        "NEXT_UPSIDE_EXTENSION",
        "DOWNSIDE_TARGET_SUPPORT_RETEST",
        "NEXT_DOWNSIDE_EXTENSION",
        "BREAKDOWN_RETEST_RESISTANCE",
        "NEXT_DOWNSIDE_REACTION_TARGET",
        "TARGET_REACHED_WAIT_FOR_REMAP",
        "EXTENSION_REVIEW_NO_CHASE",
        "NO_CHASE_WITHOUT_NEW_ZONE",
        "WAIT_FOR_NEW_MAP",
    }:
        return pill_classes("warn", normalized)
    if normalized in {"TARGET_REACHED", "DOWNSIDE_TARGET_REACHED"}:
        return pill_classes("warn", normalized)
    if normalized in {"ACTIVE_MAP", "CURRENT_MAP_ACTIVE"}:
        return pill_classes("ok", normalized)
    if normalized in {
        "BLOCK_SELECTION_NOT_ELIGIBLE",
        "BLOCK_INSUFFICIENT_SAMPLE",
        "LEGACY_CONTEXT_ONLY",
        "READ_ONLY_APLUS_AVOID_CONTEXT",
    }:
        return pill_classes("muted", normalized)
    if normalized in {"CONTEXT_ONLY", "CORE_CONTEXT", "CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP"}:
        return pill_classes("context", normalized)
    return pill_classes("muted", normalized)


def as_utc_naive(ts: Any) -> datetime | None:
    if ts is None or not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(UTC).replace(tzinfo=None)


def fresh_map_badge(asof_ts: Any, *, now_utc: datetime, lifecycle_state: str) -> str:
    if str(lifecycle_state or "").upper() != "ACTIVE_MAP":
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
    state = str(lifecycle_state or "").upper()
    if recompute_needed or state in STALE_LIFECYCLE_STATES:
        return "stale-map"
    if state in WARNING_LIFECYCLE_STATES:
        return "warning-map"
    if fresh_badge:
        return "fresh-map"
    return ""


def lifecycle_badges_html(lifecycle_state: str, fresh_badge: str) -> str:
    badges = [
        f"<span class='pill {css_class(lifecycle_state)}'>{esc(lifecycle_state)}</span>"
    ]
    if fresh_badge:
        badges.append(f"<span class='pill ok'>{esc(fresh_badge)}</span>")
    return "".join(badges)


def next_zone_html(preview: NextZonePreview) -> str:
    parts = [
        f"<span class='pill {css_class(preview.next_zone_state)}'>{esc(preview.next_zone_state)}</span>"
    ]
    if preview.next_reaction_zone_label and preview.next_reaction_zone:
        parts.append(
            "<div class='small'>"
            f"<span class='pill {css_class(preview.next_reaction_zone_label)}'>{esc(preview.next_reaction_zone_label)}</span> "
            f"<span class='zone-value'>{esc(format_zone(preview.next_reaction_zone))}</span>"
            "</div>"
        )
    if preview.next_target_zone_label and preview.next_target_zone:
        parts.append(
            "<div class='small'>"
            f"<span class='pill {css_class(preview.next_target_zone_label)}'>{esc(preview.next_target_zone_label)}</span> "
            f"<span class='zone-value'>{esc(format_zone(preview.next_target_zone))}</span>"
            "</div>"
        )
    if preview.next_zone_reason:
        parts.append(f"<div class='muted small'>{esc(preview.next_zone_reason)}</div>")
    if preview.next_zone_state in {"RECLAIM_NEXT_ZONE_PREVIEW", "BREAKDOWN_NEXT_ZONE_PREVIEW"}:
        parts.append("<div class='muted small'>Market context, not permission.</div>")
    return "".join(parts)


def _zone_midpoint(low: Any, high: Any) -> Decimal | None:
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
        zone_text = fmt_zone(row.get("tp_zone_low"), row.get("tp_zone_high"))
        if not zone_text:
            return "<span class='muted'>—</span>"
        leg = str(row.get("leg_direction") or "").upper()
        label = "TP / upside target" if leg == "UP" else "Downside target" if leg == "DOWN" else "Target"
        target_mid = _zone_midpoint(row.get("tp_zone_low"), row.get("tp_zone_high"))

    distance = _target_distance_text(target_mid, row.get("current_price"))
    distance_html = "" if not distance else f"<div class='muted small'>distance: {esc(distance)}</div>"
    return (
        f"<div><span class='pill {css_class(label)}'>{esc(label)}</span></div>"
        f"<div class='zone-value'>{esc(zone_text)}</div>"
        f"{distance_html}"
    )


def local_label(value: datetime | None) -> str:
    if value is None:
        return "not available"
    local = value.replace(tzinfo=UTC).astimezone(ZoneInfo("Europe/Amsterdam"))
    return local.strftime("%Y-%m-%d %H:%M:%S %Z Amsterdam time")


def now_local_label() -> str:
    return local_label(datetime.now(UTC).replace(tzinfo=None))


def fetch_latest_rows(
    conn: Any,
    *,
    venue: str,
    interval: str,
    limit: int,
) -> tuple[datetime | None, list[dict[str, Any]]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH ranked_advice AS (
                SELECT
                    symbol,
                    priority_rank,
                    selection_state,
                    selection_score,
                    setup_filter_state,
                    setup_filter_reason,
                    policy_decision,
                    allowed_now,
                    advice_state,
                    advice_action,
                    leg_direction,
                    aplus_bucket,
                    confidence_score,
                    risk_label,
                    entry_zone_low,
                    entry_zone_high,
                    tp_zone_low,
                    tp_zone_high,
                    invalidation_price,
                    reason_codes_json,
                    asof_ts_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY asset_id
                        ORDER BY asof_ts_utc DESC, updated_ts_utc DESC
                    ) AS rn
                FROM paper_advice_observation
                WHERE venue = %(venue)s
                  AND interval_code = %(interval)s
            )
            SELECT
                symbol,
                priority_rank,
                selection_state,
                selection_score,
                setup_filter_state,
                setup_filter_reason,
                policy_decision,
                allowed_now,
                advice_state,
                advice_action,
                leg_direction,
                aplus_bucket,
                confidence_score,
                risk_label,
                entry_zone_low,
                entry_zone_high,
                tp_zone_low,
                tp_zone_high,
                invalidation_price,
                reason_codes_json,
                asof_ts_utc
            FROM ranked_advice
            WHERE rn = 1
            ORDER BY
                priority_rank IS NULL,
                priority_rank ASC,
                confidence_score DESC,
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

    latest_asof = max(
        (row.get("asof_ts_utc") for row in rows if isinstance(row.get("asof_ts_utc"), datetime)),
        default=None,
    )
    return latest_asof, rows


def classify_candidate(row: dict[str, Any]) -> tuple[str, list[str]]:
    selection_state = str(row.get("selection_state") or "").upper()
    setup_state = str(row.get("setup_filter_state") or "").upper()
    setup_reason = str(row.get("setup_filter_reason") or "").upper()
    policy_decision = str(row.get("policy_decision") or "").upper()
    allowed_now = bool_text(row.get("allowed_now"))
    advice_state = str(row.get("advice_state") or "").upper()
    advice_action = str(row.get("advice_action") or "").upper()
    leg_direction = str(row.get("leg_direction") or "").upper()
    aplus_bucket = str(row.get("aplus_bucket") or "").upper()
    risk_label = str(row.get("risk_label") or "").upper()
    reason_codes = [code.upper() for code in parse_reason_codes(row.get("reason_codes_json"))]
    reasons: list[str] = []

    explicit_insufficient = (
        "INSUFFICIENT_SAMPLE" in setup_reason
        or "INSUFFICIENT_SAMPLE" in policy_decision
        or any("INSUFFICIENT_SAMPLE" in code for code in reason_codes)
    )
    if explicit_insufficient or not has_required_zones(row):
        if explicit_insufficient:
            reasons.append("INSUFFICIENT_SAMPLE")
        if not has_required_zones(row):
            reasons.append("MISSING_REQUIRED_ZONE_DATA")
        return "INSUFFICIENT_SAMPLE", reasons

    hard_blocks = []
    if aplus_bucket == "APLUS_AVOID":
        hard_blocks.append("APLUS_AVOID")
    if advice_action in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY"}:
        hard_blocks.append(advice_action)
    if setup_reason == "MARKET_DAMAGE_RISK":
        hard_blocks.append("MARKET_DAMAGE_RISK")
    if selection_state == "AVOID":
        hard_blocks.append("SELECTION_AVOID")
    if setup_state == "FAIL":
        hard_blocks.append("SETUP_FAIL")
    if hard_blocks:
        return "BLOCKED_NO_NEW_BUY", hard_blocks

    if advice_action == "CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP" or advice_state in {"CORE_CONTEXT", "CONTEXT"}:
        return "CONTEXT_ONLY", ["CONTEXT_ONLY"]

    allowed = allowed_now == "YES" or policy_decision in {"ALLOW", "BUY_READY", "BUY", "WATCH_CORE"}
    action_allows = advice_action in {"BUY_READY", "ACCUMULATE", "BUY"}
    if (
        setup_state == "PASS"
        and selection_state in {"WATCHLIST", "WATCH_CORE", "STRONG_WATCHLIST"}
        and (allowed or action_allows)
        and advice_action not in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY", "CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP"}
        and aplus_bucket != "APLUS_AVOID"
        and setup_reason != "MARKET_DAMAGE_RISK"
        and leg_direction == "UP"
    ):
        return "PAPER_BUY_READY", ["SETUP_PASS", "MARKET_ONLY_READY"]

    if (
        leg_direction == "DOWN"
        and setup_state in {"PASS", "NEAR_PASS", "WATCH"}
        and advice_action in {"WAIT_FOR_MARKET_RECLAIM", "WATCH_FOR_SETUP_CONFIRMATION", "WATCH_ONLY"}
        and risk_label in {"HIGH", "ELEVATED", "MODERATE", "RISK_NEAR"}
    ):
        return "RECLAIM_NEAR", ["DOWN_LEG_RECLAIM_WATCH"]

    if (
        setup_state == "PASS"
        and (
            advice_action in {"WATCH_ONLY", "WATCH_FOR_SETUP_CONFIRMATION"}
            or policy_decision in {"WATCH", "WATCH_ONLY"}
        )
    ):
        return "WATCH_FOR_CONFIRMATION", ["SETUP_PASS_WAITING_CONFIRMATION"]

    if setup_state == "PASS":
        return "WATCH_FOR_CONFIRMATION", ["SETUP_PASS_NOT_BUY_READY"]

    return "CONTEXT_ONLY", ["NOT_ACTIONABLE"]


def enriched_rows(
    rows: list[dict[str, Any]],
    *,
    price_by_symbol: dict[str, MarketPriceSnapshot],
) -> list[dict[str, Any]]:
    output = []
    now_utc = datetime.now(UTC)
    for row in rows:
        group, reasons = classify_candidate(row)
        symbol = str(row.get("symbol") or "").upper()
        snapshot = price_by_symbol.get(symbol)
        current_price = None if snapshot is None else snapshot.price
        lifecycle = classify_fast_lifecycle(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
        )
        if group == "RECLAIM_NEAR" and lifecycle.lifecycle_state == "RECLAIM_CONFIRMED":
            group = "CONTEXT_ONLY"
            reasons = reasons + ["RECLAIM_CONFIRMED", "DOWN_MAP_INVALIDATED_BY_RECLAIM"]
        enriched = dict(row)
        enriched["candidate_group"] = group
        enriched["candidate_reason_codes"] = reasons + parse_reason_codes(row.get("reason_codes_json"))
        enriched["current_price"] = current_price
        enriched["lifecycle_state"] = lifecycle.lifecycle_state
        enriched["recompute_needed"] = lifecycle.recompute_needed
        enriched["recompute_reason"] = lifecycle.recompute_reason
        enriched["entry_state"] = classify_entry_zone_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
        )
        enriched["target_state"] = classify_target_state(
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
        enriched["price_progress_state"] = price_progress.progress_state
        enriched["price_progress_labels"] = list(price_progress.labels)
        enriched["entry_display_state"] = semantic_entry_display_state(
            entry_state=enriched["entry_state"],
            price_progress_state=price_progress.progress_state,
            price_progress_labels=price_progress.labels,
        )
        enriched["advice_action_display"] = semantic_advice_action_display(
            advice_action=row.get("advice_action"),
            lifecycle_state=lifecycle.lifecycle_state,
        )
        enriched["confirmation_state"] = confirmation_display_state(
            advice_action=row.get("advice_action"),
            policy_decision=row.get("policy_decision"),
            entry_state=enriched["entry_state"],
            price_progress_state=price_progress.progress_state,
            price_progress_labels=price_progress.labels,
        )
        enriched["next_zone_preview"] = preview_next_zones(
            symbol=symbol,
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
            lifecycle_state=lifecycle.lifecycle_state,
            lifecycle_reason=lifecycle.recompute_reason,
            target_state=enriched["target_state"],
            price_progress_state=price_progress.progress_state,
        )
        if str(enriched["entry_state"]).endswith("_REACHED") and group != "PAPER_BUY_READY":
            enriched["promotion_blockers"] = promotion_blockers(
                enriched,
                candidate_group=group,
            )
        else:
            enriched["promotion_blockers"] = []
        enriched["fresh_map_badge"] = fresh_map_badge(
            row.get("asof_ts_utc"),
            now_utc=now_utc,
            lifecycle_state=lifecycle.lifecycle_state,
        )
        output.append(enriched)

    order = {group: index for index, group in enumerate(CANDIDATE_GROUPS)}
    output.sort(
        key=lambda row: (
            order.get(str(row["candidate_group"]), 99),
            row.get("priority_rank") is None,
            row.get("priority_rank") or 999999,
            -(to_decimal(row.get("confidence_score")) or Decimal("0")),
            str(row.get("symbol") or ""),
        )
    )
    return output


def render_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No rows.</div>'

    body = []
    for row in rows:
        rank = row.get("priority_rank")
        rank_text = "" if rank is None else str(rank)
        group = str(row.get("candidate_group") or "")
        allowed_now = bool_text(row.get("allowed_now"))
        reason_codes = ", ".join(str(code) for code in row.get("candidate_reason_codes", []))
        blockers = ", ".join(str(code) for code in row.get("promotion_blockers", []))
        next_preview = row.get("next_zone_preview")
        next_preview_html = next_zone_html(next_preview) if isinstance(next_preview, NextZonePreview) else ""
        target_html = (
            relevant_target_html(row, next_preview)
            if isinstance(next_preview, NextZonePreview)
            else "<span class='muted'>—</span>"
        )
        progress_labels = "".join(
            f"<span class='pill {css_class(str(label))}'>{esc(label)}</span>"
            for label in row.get("price_progress_labels", [])
        )
        progress_html = (
            f"<span class='pill {css_class(row.get('price_progress_state'))}'>{esc(row.get('price_progress_state'))}</span>"
            f"{progress_labels}"
        )
        row_class = workflow_row_class(
            lifecycle_state=str(row.get("lifecycle_state") or ""),
            recompute_needed=bool(row.get("recompute_needed")),
            fresh_badge=str(row.get("fresh_map_badge") or ""),
        )
        block_display = classify_policy_block_display(
            row,
            candidate_group=group,
            lifecycle_state=str(row.get("lifecycle_state") or ""),
            recompute_needed=bool(row.get("recompute_needed")),
            recompute_reason=str(row.get("recompute_reason") or ""),
            target_state=str(row.get("target_state") or ""),
            entry_state=str(row.get("entry_state") or ""),
            price_progress_state=str(row.get("price_progress_state") or ""),
            extra_reason_codes=list(row.get("candidate_reason_codes", [])),
        )
        policy_html = f"{esc(row.get('policy_decision'))}"
        if block_display is not None:
            policy_html = (
                f"<span class='pill {css_class(block_display.display_policy_label)}'>{esc(block_display.display_policy_label)}</span>"
                f"<div class='muted small'>raw: {esc(block_display.raw_policy_state)}</div>"
                f"<div class='muted small'>cause: {esc(block_display.block_primary_reason)}</div>"
                f"<div class='muted small'>unblock: {esc(block_display.unblock_condition_label)}</div>"
            )
        action_label = row.get("advice_action_display")
        action_class = css_class(str(action_label))
        action_detail = f"policy/action: {esc(row.get('advice_action'))}"
        if block_display is not None:
            action_label = block_display.display_policy_label
            action_class = css_class(block_display.display_policy_label)
            action_detail = block_reason_summary_text(block_display)
        body.append(
            f"<tr class='{row_class}'>"
            f"<td class='num'>{esc(rank_text)}</td>"
            f"<td class='sticky-symbol'><strong>{esc(row.get('symbol'))}</strong></td>"
            f"<td><span class='pill {css_class(group)}'>{esc(group)}</span></td>"
            f"<td>{esc(row.get('selection_state'))}</td>"
            f"<td class='num'>{esc(dec_text(row.get('selection_score'), '0.0000'))}</td>"
            f"<td><span class='pill {css_class(row.get('setup_filter_state'))}'>{esc(row.get('setup_filter_state'))}</span></td>"
            f"<td><span class='pill {css_class(row.get('setup_filter_reason'))}'>{esc(row.get('setup_filter_reason'))}</span></td>"
            f"<td>{policy_html}</td>"
            f"<td><span class='pill {css_class(allowed_now)}'>{esc(allowed_now)}</span></td>"
            f"<td>{esc(row.get('advice_state'))}</td>"
            f"<td><span class='pill {action_class}'>{esc(action_label)}</span><div class='muted small'>{esc(action_detail)}</div></td>"
            f"<td><span class='pill {css_class(row.get('leg_direction'))}'>{esc(row.get('leg_direction'))}</span></td>"
            f"<td><span class='pill {css_class(row.get('aplus_bucket'))}'>{esc(row.get('aplus_bucket'))}</span></td>"
            f"<td class='num'>{esc(pct_text(row.get('confidence_score')))}</td>"
            f"<td><span class='pill {css_class(row.get('risk_label'))}'>{esc(row.get('risk_label'))}</span></td>"
            f"<td class='num sticky-price'>{esc(dec_text(row.get('current_price')))}</td>"
            f"<td><span class='pill {css_class(row.get('entry_display_state'))}'>{esc(row.get('entry_display_state'))}</span><div class='muted small'>raw: {esc(row.get('entry_state'))}</div></td>"
            f"<td>{progress_html}</td>"
            f"<td><span class='pill {css_class(row.get('target_state'))}'>{esc(row.get('target_state'))}</span></td>"
            f"<td><span class='pill {css_class(row.get('confirmation_state'))}'>{esc(row.get('confirmation_state'))}</span></td>"
            f"<td class='small'>{esc(blockers)}</td>"
            f"<td>{lifecycle_badges_html(str(row.get('lifecycle_state') or ''), str(row.get('fresh_map_badge') or ''))}</td>"
            f"<td><span class='pill {css_class('MAP_RECOMPUTE_NEEDED' if row.get('recompute_needed') else 'ACTIVE_MAP')}'>{'YES' if row.get('recompute_needed') else 'NO'}</span></td>"
            f"<td class='small'>{esc(row.get('recompute_reason'))}</td>"
            f"<td>{next_preview_html}</td>"
            f"<td class='num zone-value'>{esc(fmt_zone(row.get('entry_zone_low'), row.get('entry_zone_high')))}</td>"
            f"<td class='num zone-value sticky-target'>{target_html}</td>"
            f"<td class='num zone-value'>{esc(dec_text(row.get('invalidation_price')))}</td>"
            f"<td class='small'>{esc(reason_codes)}</td>"
            "</tr>"
        )

    return f"""
    <div class="table-wrap">
      <table class="sticky-table">
        <thead class="sticky-header">
          <tr>
            <th>Rank</th>
            <th class="sticky-symbol">Symbol</th>
            <th>Group</th>
            <th>Selection</th>
            <th>Selection score</th>
            <th>Setup</th>
            <th>Setup reason</th>
            <th>Policy</th>
            <th>Allowed now</th>
            <th>Advice state</th>
            <th>Action</th>
            <th>Leg</th>
            <th>A+</th>
            <th>Confidence</th>
            <th>Risk label</th>
            <th class="sticky-price">Current price</th>
            <th>Entry state</th>
            <th>Price progress</th>
            <th>Target state</th>
            <th>Confirmation</th>
            <th>Promotion blockers</th>
            <th>Lifecycle state</th>
            <th>Recompute needed</th>
            <th>Recompute reason</th>
            <th>Next zones</th>
            <th>Entry / reaction zone</th>
            <th class="sticky-target">Relevant target</th>
            <th>Invalidation</th>
            <th>Reason codes</th>
          </tr>
        </thead>
        <tbody>
          {''.join(body)}
        </tbody>
      </table>
    </div>
    """


def render_group_section(group: str, rows: list[dict[str, Any]]) -> str:
    group_rows = [row for row in rows if row.get("candidate_group") == group]
    priority_class = " priority" if group in {"PAPER_BUY_READY", "RECLAIM_NEAR"} else ""
    return f"""
    <section class="card{priority_class}">
      <h2>{esc(group)} <span class="muted">({len(group_rows)})</span></h2>
      {render_table(group_rows)}
    </section>
    """


def render_html(
    *,
    venue: str,
    interval: str,
    latest_asof: datetime | None,
    rows: list[dict[str, Any]],
) -> str:
    generated_text = now_local_label()
    latest_text = local_label(latest_asof)
    counts = {
        group: sum(1 for row in rows if row.get("candidate_group") == group)
        for group in CANDIDATE_GROUPS
    }
    counts_html = "".join(
        f"<span class='pill {css_class(group)}'>{esc(group)}: {count}</span>"
        for group, count in counts.items()
    )
    sections = "\n".join(render_group_section(group, rows) for group in CANDIDATE_GROUPS)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Entry Candidates</title>
  <style>
    {cockpit_base_css(min_table_width=2300)}
  </style>
</head>
<body>
  <header>
    <h1>Entry Candidates</h1>
    <div class="muted">Rendered {esc(generated_text)}</div>
    <div class="muted">latest advice snapshot: {esc(latest_text)} · venue={esc(venue)} · interval={esc(interval)}</div>
    {cockpit_nav()}
    <div class="legend">
      <div><strong>Entry candidates</strong> are market-only and account-agnostic.</div>
      <div><strong>PAPER_BUY_READY</strong> is not an order.</div>
      <div><strong>RECLAIM_NEAR</strong> means watch for map invalidation/reclaim, not automatic buy.</div>
      <div><strong>ENTRY_ZONE_REACHED</strong> means price is in the entry/reaction zone; it is separate from target state and is not buy permission.</div>
      <div><strong>Entry state precedence</strong>: target touched, post-entry progress, and entry-window-passed labels take precedence over near-entry labels.</div>
      <div><strong>CONFIRMATION_PENDING</strong> means setup is in-zone but still waiting for policy/advice confirmation.</div>
      <div><strong>Price progress</strong> shows where current price sits between entry/reaction zone and target. TARGET_PENDING can still be true while TARGET_NEAR is shown.</div>
      <div><strong>ACTIVE_MAP</strong> means the map is still valid, not that entry or target was reached.</div>
      <div><strong>Fast lifecycle candles</strong> check whether the existing map is touched, stale, invalidated, or near reclaim. They do not create a new strategy map.</div>
      <div><strong>Account sizing/permission</strong> belongs later in decision_gate.</div>
      <div><strong>Rotation preview</strong> remains for existing positions only.</div>
      <div><strong>Recompute needed</strong> means the existing map may be stale. It is not a trade instruction, does not imply buy/sell, and indicates the strategy/advice map should be refreshed.</div>
      <div><strong>Fresh green rows</strong> = newly updated/fresh map context.</div>
      <div><strong>Red rows</strong> = stale, invalidated, or recompute-needed map context.</div>
      <div><strong>Dimmed labels</strong> in red/stale rows are old-map context; bright red/orange labels are the current lifecycle/recompute reason.</div>
      <div><strong>Next zones</strong>: Next zones are market-only preview zones after a map is stale, reclaimed, invalidated, or target-finished. They are not orders, allocation advice, or execution intent.</div>
      <div><strong>Market context is not trade permission.</strong> Policy blocks and next-zone previews can coexist.</div>
    </div>
    <div class="grid">
      <div class="metric"><div class="muted">Rows</div><h2>{len(rows)}</h2></div>
      <div class="metric"><div class="muted">Candidate groups</div>{counts_html}</div>
      <div class="metric"><div class="muted">Safety</div><span class="pill ok">broker_private_calls=0</span><span class="pill ok">broker_writes=0</span><span class="pill ok">order_submission=0</span><span class="pill ok">executor=none</span><span class="pill ok">account_awareness=0</span></div>
    </div>
  </header>
  <main>
    {sections}
  </main>
</body>
</html>
"""


def write_html(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def main() -> int:
    args = parse_args()
    conn = get_connection()
    try:
        latest_asof, rows = fetch_latest_rows(
            conn,
            venue=str(args.venue),
            interval=str(args.interval),
            limit=int(args.limit),
        )
        price_by_symbol = fetch_latest_prices_by_symbol(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            symbols=sorted({str(row.get("symbol") or "").upper() for row in rows}),
        )
    finally:
        conn.close()

    rows = enriched_rows(rows, price_by_symbol=price_by_symbol)
    output_path = Path(args.output_html)
    write_html(
        output_path,
        render_html(
            venue=str(args.venue),
            interval=str(args.interval),
            latest_asof=latest_asof,
            rows=rows,
        ),
    )

    if args.output == "summary":
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print("scope=market-only account-agnostic static dashboard")
        print("broker_private_calls=0 broker_writes=0 order_submission=0 executor=none account_awareness=0")
        print(f"market_price_snapshot_rows={len(price_by_symbol)} quote={str(args.quote).upper()}")
        print(f"rows={len(rows)} output_html={output_path}")
        for group in CANDIDATE_GROUPS:
            count = sum(1 for row in rows if row.get("candidate_group") == group)
            print(f"{group}={count}")
    elif args.output == "json":
        print(
            json.dumps(
                {
                    "report": REPORT_NAME,
                    "version": REPORT_VERSION,
                    "rows": len(rows),
                    "output_html": str(output_path),
                    "broker_private_calls": 0,
                    "broker_writes": 0,
                    "order_submission": 0,
                    "executor": "none",
                    "account_awareness": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
