from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


DEFAULT_ENTRY_NEAR_PCT = Decimal("2.0")


@dataclass(frozen=True)
class PriceProgress:
    progress_state: str
    labels: tuple[str, ...] = ()
    progress_pct: Decimal | None = None


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def zone_bounds(low: Any, high: Any) -> tuple[Decimal | None, Decimal | None]:
    values = [value for value in (to_decimal(low), to_decimal(high)) if value is not None]
    if not values:
        return None, None
    return min(values), max(values)


def pct_distance_to_zone(price: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if price <= 0:
        return Decimal("1000000")
    if low <= price <= high:
        return Decimal("0")
    reference = low if price < low else high
    if reference <= 0:
        return Decimal("1000000")
    return abs((price / reference) - Decimal("1")) * Decimal("100")


def classify_entry_zone_state(
    *,
    leg_direction: Any,
    current_price: Any,
    entry_zone_low: Any,
    entry_zone_high: Any,
    near_pct: Decimal = DEFAULT_ENTRY_NEAR_PCT,
) -> str:
    leg = str(leg_direction or "").upper()
    price = to_decimal(current_price)
    low, high = zone_bounds(entry_zone_low, entry_zone_high)

    prefix = "REACTION_ZONE" if leg == "DOWN" else "ENTRY_ZONE"
    if price is None or price <= 0 or low is None or high is None:
        return f"{prefix}_UNKNOWN"

    if low <= price <= high:
        return f"{prefix}_REACHED"
    if pct_distance_to_zone(price, low, high) <= near_pct:
        return f"{prefix}_NEAR"
    return f"{prefix}_PENDING"


def classify_target_state(
    *,
    leg_direction: Any,
    current_price: Any,
    tp_zone_low: Any,
    tp_zone_high: Any,
) -> str:
    leg = str(leg_direction or "").upper()
    price = to_decimal(current_price)
    target_low, target_high = zone_bounds(tp_zone_low, tp_zone_high)
    if price is None or price <= 0 or target_low is None or target_high is None or leg not in {"UP", "DOWN"}:
        return "TARGET_UNKNOWN"
    target = (target_low + target_high) / Decimal("2")
    if leg == "UP" and price >= target:
        return "TARGET_REACHED"
    if leg == "DOWN" and price <= target:
        return "TARGET_REACHED"
    return "TARGET_PENDING"


def classify_price_progress_state(
    *,
    leg_direction: Any,
    current_price: Any,
    entry_zone_low: Any,
    entry_zone_high: Any,
    tp_zone_low: Any,
    tp_zone_high: Any,
    in_position_context: bool = False,
) -> PriceProgress:
    leg = str(leg_direction or "").upper()
    price = to_decimal(current_price)
    entry_low, entry_high = zone_bounds(entry_zone_low, entry_zone_high)
    target_low, target_high = zone_bounds(tp_zone_low, tp_zone_high)

    if (
        price is None
        or price <= 0
        or entry_low is None
        or entry_high is None
        or target_low is None
        or target_high is None
        or leg not in {"UP", "DOWN"}
    ):
        return PriceProgress("PRICE_PROGRESS_UNKNOWN")

    entry_mid = (entry_low + entry_high) / Decimal("2")
    target_mid = (target_low + target_high) / Decimal("2")
    if leg == "UP":
        denominator = target_mid - entry_mid
        if denominator <= 0:
            return PriceProgress("PRICE_PROGRESS_UNKNOWN")
        if entry_low <= price <= entry_high:
            return PriceProgress("ENTRY_ZONE_ACTIVE", progress_pct=Decimal("0"))
        progress = (price - entry_mid) / denominator
        labels: list[str] = []
        if price > entry_high and price < target_mid:
            labels.append("ENTRY_WINDOW_PASSED")
        if progress >= Decimal("0.50") and price < target_mid and not in_position_context:
            labels.extend(["CHASE_RISK", "LATE_ENTRY_REVIEW"])
        if price >= target_mid:
            return PriceProgress("TARGET_REACHED", tuple(labels), progress)
        if progress >= Decimal("0.85"):
            return PriceProgress("TARGET_NEAR", tuple(labels), progress)
        if progress >= Decimal("0.50"):
            return PriceProgress("TARGET_APPROACHING", tuple(labels), progress)
        if price > entry_high:
            return PriceProgress("POST_ENTRY_PROGRESS", tuple(labels), progress)
        return PriceProgress("PRICE_PROGRESS_PENDING", progress_pct=progress)

    denominator = entry_mid - target_mid
    if denominator <= 0:
        return PriceProgress("PRICE_PROGRESS_UNKNOWN")
    if entry_low <= price <= entry_high:
        return PriceProgress("REACTION_ZONE_ACTIVE", progress_pct=Decimal("0"))
    progress = (entry_mid - price) / denominator
    if price <= target_mid:
        return PriceProgress("DOWNSIDE_TARGET_REACHED", progress_pct=progress)
    if progress >= Decimal("0.85"):
        return PriceProgress("DOWNSIDE_TARGET_NEAR", progress_pct=progress)
    if progress >= Decimal("0.50"):
        return PriceProgress("DOWNSIDE_TARGET_APPROACHING", progress_pct=progress)
    if price < entry_low:
        return PriceProgress("REACTION_PROGRESS", progress_pct=progress)
    return PriceProgress("PRICE_PROGRESS_PENDING", progress_pct=progress)


def confirmation_state(*, advice_action: Any, policy_decision: Any) -> str:
    action = str(advice_action or "").upper()
    policy = str(policy_decision or "").upper()
    if action == "WATCH_FOR_SETUP_CONFIRMATION" or policy in {"WATCH", "WATCH_ONLY", "LONG_HORIZON_ONLY"}:
        return "CONFIRMATION_PENDING"
    return ""


def confirmation_display_state(
    *,
    advice_action: Any,
    policy_decision: Any,
    entry_state: Any,
    price_progress_state: Any = None,
    price_progress_labels: tuple[str, ...] | list[str] = (),
) -> str:
    state = confirmation_state(advice_action=advice_action, policy_decision=policy_decision)
    if not state:
        return ""
    progress = str(price_progress_state or "").upper()
    labels = {str(label or "").upper() for label in price_progress_labels}
    if progress in {"TARGET_APPROACHING", "TARGET_NEAR"} or "ENTRY_WINDOW_PASSED" in labels:
        return ""
    normalized_entry = str(entry_state or "").upper()
    if normalized_entry in {
        "ENTRY_ZONE_REACHED",
        "ENTRY_ZONE_NEAR",
        "REACTION_ZONE_REACHED",
        "REACTION_ZONE_NEAR",
    }:
        return state
    return ""


def promotion_blockers(row: dict[str, Any], *, candidate_group: str | None = None) -> list[str]:
    blockers: list[str] = []
    action = str(row.get("advice_action") or "").upper()
    policy = str(row.get("policy_decision") or "").upper()
    allowed_now = row.get("allowed_now")
    aplus_bucket = str(row.get("aplus_bucket") or "").upper()
    setup_state = str(row.get("setup_filter_state") or "").upper()
    setup_reason = str(row.get("setup_filter_reason") or "").upper()

    if candidate_group == "PAPER_BUY_READY":
        return blockers
    if action == "WATCH_FOR_SETUP_CONFIRMATION":
        blockers.append("WATCH_FOR_SETUP_CONFIRMATION")
    if policy == "LONG_HORIZON_ONLY":
        blockers.append("LONG_HORIZON_ONLY")
    if bool_text(allowed_now) == "NO":
        blockers.append("allowed_now=NO")
    if aplus_bucket == "APLUS_AVOID":
        blockers.append("APLUS_AVOID")
    if setup_reason == "MARKET_DAMAGE_RISK":
        blockers.append("MARKET_DAMAGE_RISK")
    if setup_state and setup_state != "PASS":
        blockers.append("setup_filter_state!=PASS")
    return list(dict.fromkeys(blockers))


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
