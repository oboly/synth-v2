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
)
from src.reporting.fast_lifecycle_recompute_v1 import classify_fast_lifecycle
from src.reporting.next_zone_preview_v1 import (
    NextZonePreview,
    format_zone,
    preview_next_zones,
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
    if "REDUCE" in value or "AVOID" in value or "DO_NOT_ADD" in value or "HIGH" in value:
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
    ):
        return pill_classes("warn", value)
    if (
        "INVALIDATION_TOUCHED" in value
        or "MAP_RECOMPUTE_NEEDED" in value
        or "RECLAIM_NEXT_ZONE_PREVIEW" in value
        or "BREAKDOWN_NEXT_ZONE_PREVIEW" in value
        or "NEXT_ZONE_UNKNOWN" in value
    ):
        return pill_classes("bad", value)
    if (
        "HOLD" in value
        or "CORE" in value
        or "FRESH" in value
        or "RISK_OK" in value
        or "ACTIVE_MAP" in value
        or "CURRENT_MAP_ACTIVE" in value
        or "MARKET_PRICE_SNAPSHOT" in value
    ):
        return pill_classes("ok", value)
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


def held_rotation_exclusion(row: Any | None) -> str | None:
    if row is None:
        return None
    rotation_state = str(row.rotation_state or "").upper()
    risk_state = str(row.risk_state or "").upper()
    reason_codes = {str(reason).upper() for reason in row.reason_codes}
    if (
        "REDUCE" in rotation_state
        or "EXIT" in rotation_state
        or "TARGET_REACHED" in rotation_state
        or risk_state in {"RISK_NEAR", "RECLAIM_CONFIRMED"}
        or "RISK_NEAR" in reason_codes
        or "RECLAIM_CONFIRMED" in reason_codes
    ):
        return "HELD_ROTATION_REVIEW_PRESSURE"
    return None


def destination_diagnostic_exclusions(
    *,
    advice_row: dict[str, Any] | None,
    current_price: Decimal | None,
    held_row: Any | None,
) -> list[str]:
    if not advice_row:
        return ["ADVICE_MISSING"]

    reasons: list[str] = []
    target_state = target_state_for_advice(advice_row, current_price)
    risk_state = risk_state_for_advice(advice_row, current_price)
    setup_state = str(advice_row.get("setup_filter_state") or "").upper()
    setup_reason = str(advice_row.get("setup_filter_reason") or "").upper()
    advice_action = str(advice_row.get("advice_action") or "").upper()
    aplus_bucket = str(advice_row.get("aplus_bucket") or "").upper()

    if target_state == "TARGET_REACHED":
        reasons.append("TARGET_REACHED")
    if risk_state in {"RISK_NEAR", "RISK_UNKNOWN", "RECLAIM_CONFIRMED"}:
        reasons.append(risk_state)
    if aplus_bucket == "APLUS_AVOID":
        reasons.append("APLUS_AVOID")
    if advice_action in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY"}:
        reasons.append(advice_action)
    if setup_reason == "MARKET_DAMAGE_RISK":
        reasons.append("MARKET_DAMAGE_RISK")
    if setup_state != "PASS":
        reasons.append("SETUP_NOT_PASS")

    held_exclusion = held_rotation_exclusion(held_row)
    if held_exclusion:
        reasons.append(held_exclusion)

    return list(dict.fromkeys(reasons))


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
    parts = [
        f"<span class='pill {pill_class(preview.next_zone_state)}'>{esc(preview.next_zone_state)}</span>"
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
    if preview.next_zone_reason:
        parts.append(f"<div class='muted small'>{esc(preview.next_zone_reason)}</div>")
    return "".join(parts)


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
) -> str:
    local_ts = now_local_label()
    now_utc = datetime.now(UTC)

    state_counts: dict[str, int] = {}
    for row in rows:
        state_counts[row.rotation_state] = state_counts.get(row.rotation_state, 0) + 1

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

    lifecycle_state_by_symbol = {
        row.position_symbol: lifecycle_for_row(row).lifecycle_state
        for row in rows
    }

    tp_harvest_rows = [
        r for r in rows
        if is_up_target_review_row(r, lifecycle_state_by_symbol.get(r.position_symbol, ""))
    ]
    downside_target_rows = [
        r for r in rows
        if (
            r not in tp_harvest_rows
            and is_downside_target_review_row(r, lifecycle_state_by_symbol.get(r.position_symbol, ""))
        )
    ]
    reduce_rows = [
        r for r in rows
        if r not in tp_harvest_rows and r not in downside_target_rows and is_reduce_exit_row(r)
    ]
    review_rows = [
        r for r in rows
        if (
            r not in tp_harvest_rows
            and r not in downside_target_rows
            and r not in reduce_rows
            and "REVIEW" in str(r.rotation_state or "").upper()
            and str(r.target_state or "").upper() != "TARGET_REACHED"
        )
    ]
    hold_rows = [
        r for r in rows
        if (
            r not in tp_harvest_rows
            and r not in downside_target_rows
            and r not in reduce_rows
            and r not in review_rows
        )
    ]
    held_row_by_symbol = {row.position_symbol: row for row in rows}
    ranked_candidates = rank_market_candidates(advice_by_symbol, current_price_by_symbol)

    def table_rows(table_rows: list[Any]) -> str:
        out = []
        for row in table_rows:
            tp_zone = tp_zone_text(row)

            review_refs = ", ".join(row.review_references[:3]) if row.review_references else ""
            destinations = (
                ", ".join(row.rotation_destination_candidates[:3])
                if row.rotation_destination_candidates
                else ""
            )
            latest_price = price_by_symbol.get(row.position_symbol)
            current_price = None if latest_price is None else latest_price.price
            latest_price_age_min = price_age_min(latest_price, now_utc=now_utc)
            valuation = valuation_by_symbol.get(
                row.position_symbol,
                PositionValuation(value_eur=None, source="VALUATION_UNKNOWN"),
            )
            delta_entry_pct = entry_delta_pct(
                entry_zone_low=row.entry_zone_low,
                entry_zone_high=row.entry_zone_high,
                current_price=current_price,
            )
            delta_tp_pct = pct_delta(
                midpoint_or_edge(row.tp_zone_low, row.tp_zone_high),
                current_price,
            )
            delta_invalidation_pct = pct_delta(row.invalidation_price, current_price)
            context = distance_context(row)
            lifecycle = lifecycle_for_row(row)
            fresh_badge = fresh_map_badge(
                row.paper_asof_ts_utc,
                now_utc=now_utc,
                lifecycle_state=lifecycle.lifecycle_state,
            )
            row_class = workflow_row_class(
                lifecycle_state=lifecycle.lifecycle_state,
                recompute_needed=lifecycle.recompute_needed,
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
            progress_labels = "".join(
                f"<span class='pill {pill_class(label)}'>{esc(label)}</span>"
                for label in price_progress.labels
            )
            progress_html = (
                f"<span class='pill {pill_class(price_progress.progress_state)}'>{esc(price_progress.progress_state)}</span>"
                f"{progress_labels}"
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
                f"<td><span class='pill {pill_class(row.advice_action)}'>{esc(row.advice_action)}</span></td>"
                f"<td><span class='pill {pill_class(row.aplus_bucket)}'>{esc(row.aplus_bucket)}</span></td>"
                f"<td class='num sticky-price'>{esc(dec_text(current_price, '0.000000'))}</td>"
                f"<td class='num'>{esc(dec_text(latest_price_age_min, '0.1'))}</td>"
                f"<td>{progress_html}</td>"
                f"<td><span class='pill {pill_class(row.target_state)}'>{esc(row.target_state)}</span></td>"
                f"<td><span class='pill {pill_class(row.risk_state)}'>{esc(row.risk_state)}</span></td>"
                f"<td>{lifecycle_badges_html(lifecycle.lifecycle_state, fresh_badge)}</td>"
                f"<td><span class='pill {pill_class('MAP_RECOMPUTE_NEEDED' if lifecycle.recompute_needed else 'ACTIVE_MAP')}'>{'YES' if lifecycle.recompute_needed else 'NO'}</span></td>"
                f"<td class='small'>{esc(lifecycle.recompute_reason)}</td>"
                f"<td>{next_zone_html(next_preview)}</td>"
                f"{pct_cell(delta_entry_pct)}"
                f"{pct_cell(delta_tp_pct, target_pct_class(delta_tp_pct, context))}"
                f"{pct_cell(delta_invalidation_pct, risk_pct_class(delta_invalidation_pct, context))}"
                f"<td class='zone-value'>{esc(tp_zone)}</td>"
                f"<td><span class='pill {pill_class(row.rotation_state)}'>{esc(row.rotation_state)}</span></td>"
                f"<td class='num'>{esc(row.rotation_pressure_score)}</td>"
                f"<td class='small'>{esc(review_refs)}</td>"
                f"<td class='small'>{esc(destinations)}</td>"
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
            confirm_state = confirmation_display_state(
                advice_action=None if not advice else advice.get("advice_action"),
                policy_decision=None if not advice else advice.get("policy_decision"),
                entry_state=entry_state,
                price_progress_state=price_progress.progress_state,
                price_progress_labels=price_progress.labels,
            )
            exclusions = destination_diagnostic_exclusions(
                advice_row=advice,
                current_price=current_price,
                held_row=held_row,
            )
            eligible = not exclusions
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
            fresh_badge = fresh_map_badge(
                None if not advice else advice.get("asof_ts_utc"),
                now_utc=now_utc,
                lifecycle_state=lifecycle.lifecycle_state,
            )
            row_class = workflow_row_class(
                lifecycle_state=lifecycle.lifecycle_state,
                recompute_needed=lifecycle.recompute_needed,
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

            out.append(
                f"<tr class='{row_class}'>"
                f"<td class='num'>{rank}</td>"
                f"<td class='sticky-symbol'><strong>{esc(symbol)}</strong></td>"
                f"<td class='num'>{esc(dec_text(candidate_score, '0.01'))}</td>"
                f"<td><span class='pill {'ok' if eligible else 'bad'}'>{'YES' if eligible else 'NO'}</span></td>"
                f"<td class='small'>{esc(', '.join(exclusions))}</td>"
                f"<td>{esc(None if not advice else advice.get('selection_state'))}</td>"
                f"<td>{esc(None if not advice else advice.get('setup_filter_state'))}</td>"
                f"<td><span class='pill {pill_class(None if not advice else advice.get('setup_filter_reason'))}'>{esc(None if not advice else advice.get('setup_filter_reason'))}</span></td>"
                f"<td>{esc(None if not advice else advice.get('advice_state'))}</td>"
                f"<td><span class='pill {pill_class(None if not advice else advice.get('advice_action'))}'>{esc(None if not advice else advice.get('advice_action'))}</span></td>"
                f"<td>{esc(None if not advice else advice.get('leg_direction'))}</td>"
                f"<td><span class='pill {pill_class(entry_state)}'>{esc(entry_state)}</span></td>"
                f"<td>{progress_html}</td>"
                f"<td><span class='pill {pill_class(confirm_state)}'>{esc(confirm_state)}</span></td>"
                f"<td><span class='pill {pill_class(target_state)}'>{esc(target_state)}</span></td>"
                f"<td><span class='pill {pill_class(risk_state)}'>{esc(risk_state)}</span></td>"
                f"<td class='num sticky-price'>{esc(dec_text(current_price, '0.000000'))}</td>"
                f"<td>{lifecycle_badges_html(lifecycle.lifecycle_state, fresh_badge)}</td>"
                f"<td><span class='pill {pill_class('MAP_RECOMPUTE_NEEDED' if lifecycle.recompute_needed else 'ACTIVE_MAP')}'>{'YES' if lifecycle.recompute_needed else 'NO'}</span></td>"
                f"<td class='small'>{esc(lifecycle.recompute_reason)}</td>"
                f"<td>{next_zone_html(next_preview)}</td>"
                f"<td class='zone-value'>{esc(tp_zone_text(advice or {}))}</td>"
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
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th class="sticky-symbol">Symbol</th>
                  <th>Market ref score</th>
                  <th>Destination eligible</th>
                  <th>Exclusion reasons</th>
                  <th>Selection</th>
                  <th>Setup</th>
                  <th>Setup reason</th>
                  <th>Policy</th>
                  <th>Action</th>
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
                  <th>TP / target zone</th>
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

    def section(title: str, table_rows_data: list[Any], class_name: str = "") -> str:
        section_class = f"card {class_name}".strip()
        return f"""
        <section class="{esc(section_class)}">
          <h2>{esc(title)} <span class="muted">({len(table_rows_data)})</span></h2>
          <div class="table-wrap">
            <table>
              <thead>
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
                  <th>Action</th>
                  <th>A+</th>
                  <th class="sticky-price">Current price</th>
                  <th>Price age min</th>
                  <th>Price progress</th>
                  <th>Target state</th>
                  <th>Risk state</th>
                  <th>Lifecycle state</th>
                  <th>Recompute needed</th>
                  <th>Recompute reason</th>
                  <th>Next zones</th>
                  <th>Δ entry %</th>
                  <th>Δ target %</th>
                  <th>Δ risk %</th>
                  <th>TP / target zone</th>
                  <th>Rotation</th>
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
        for k, v in sorted(state_counts.items())
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Rotation Preview</title>
  <style>
    {cockpit_base_css(min_table_width=2450)}
  </style>
</head>
<body>
  <header>
    <h1>Position Rotation Preview</h1>
    <div class="muted">Rendered {esc(local_ts)} Amsterdam time</div>
    <div class="muted">venue={esc(venue)} · quote={esc(quote_currency)} · interval={esc(interval)} · trading_account_id={esc(account_id)}</div>
    {cockpit_nav()}
    <div class="legend">
      <div><strong>UP target reached</strong> = TP / harvest / reduce review for existing long/upside maps.</div>
      <div><strong>DOWN target reached</strong> = downside target/support reached; not long TP.</div>
      <div><strong>Rotation score</strong> = account-position review pressure score.</div>
      <div><strong>Market review refs</strong> = market-only comparison scores, not buy advice.</div>
      <div><strong>Rotation destinations</strong> = stricter filtered candidates.</div>
      <div><strong>Market ref score</strong> = market-only comparison score.</div>
      <div><strong>Destination eligible</strong> = strict candidate after paper/setup/risk/account-position filters.</div>
      <div><strong>Exclusion reasons</strong> explain why a strong reference is not a destination.</div>
      <div><strong>Target reached rows</strong> are harvest/review candidates, not automatic sell orders.</div>
      <div><strong>ENTRY_ZONE_REACHED</strong> is separate from target state and is not buy permission.</div>
      <div><strong>Price progress</strong> shows where current price sits between entry/reaction zone and target. TARGET_PENDING can still be true while TARGET_NEAR is shown.</div>
      <div><strong>ACTIVE_MAP</strong> means the map is still valid, not that entry or target was reached.</div>
      <div><strong>Fast lifecycle candles</strong> check whether the existing map is touched, stale, invalidated, or near reclaim. They do not create a new strategy map.</div>
      <div><strong>Recompute needed</strong> means the existing map may be stale. It is not a trade instruction, does not imply buy/sell, and indicates the strategy/advice map should be refreshed.</div>
      <div><strong>Fresh green rows</strong> = newly updated/fresh map context.</div>
      <div><strong>Red rows</strong> = stale, invalidated, or recompute-needed map context.</div>
      <div><strong>Dimmed labels</strong> in red/stale rows are old-map context; bright red/orange labels are the current lifecycle/recompute reason.</div>
      <div><strong>Next zones</strong>: Next zones are market-only preview zones after a map is stale, reclaimed, invalidated, or target-finished. They are not orders, allocation advice, or execution intent.</div>
      <div><strong>Positions value</strong> uses latest market_price_snapshot when available, with ACCOUNT_POSITION_MARK_FALLBACK only when current market price is missing. Asset positions only; excludes EUR cash.</div>
    </div>
    <div class="grid">
      <div class="metric"><div class="muted">Rows</div><h2>{len(rows)}</h2></div>
      <div class="metric"><div class="muted">Positions value</div><h2>{eur_html(positions_value_current)}</h2><div class="muted small">Asset positions only; excludes EUR cash. Position snapshot age: {esc(dec_text(position_snapshot_age_days, '0.01'))} d</div></div>
      <div class="metric"><div class="muted">Free EUR cash</div><h2>{eur_html(None if eur_balance is None else eur_balance.available_amount)}</h2><div class="muted small">Balance snapshot age: {esc(dec_text(balance_snapshot_age_min, '0.1'))} min</div></div>
      <div class="metric"><div class="muted">Reserved EUR cash</div><h2>{eur_html(None if eur_balance is None else eur_balance.reserved_amount)}</h2></div>
      <div class="metric"><div class="muted">Total EUR cash</div><h2>{eur_html(total_eur_cash)}</h2></div>
      <div class="metric"><div class="muted">Indicative account value</div><h2>{eur_html(indicative_account_value)}</h2><div class="muted small">Positions value + Total EUR cash when EUR balance is known.</div></div>
      <div class="metric"><div class="muted">State counts</div>{counts_html}</div>
      <div class="metric"><div class="muted">Safety</div><span class="pill ok">broker_private_calls=0</span><span class="pill ok">broker_writes=0</span><span class="pill ok">order_submission=0</span><span class="pill ok">executor=none</span></div>
    </div>
  </header>
  <main>
    {candidate_diagnostics_section()}
    {section("TP / harvest / reduce review", tp_harvest_rows, "harvest")}
    {section("Downside target / support / recompute review", downside_target_rows, "downside")}
    {section("Reduce / exit review candidates", reduce_rows)}
    {section("Hold review", review_rows)}
    {section("Hold / other", hold_rows)}
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
        <p class="muted">Account-aware read-only HOLD / REDUCE review dashboard.</p>
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
