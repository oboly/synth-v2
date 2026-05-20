from __future__ import annotations

from decimal import Decimal
from typing import Any


DEFAULT_ENTRY_NEAR_PCT = Decimal("2.0")


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


def confirmation_state(*, advice_action: Any, policy_decision: Any) -> str:
    action = str(advice_action or "").upper()
    policy = str(policy_decision or "").upper()
    if action == "WATCH_FOR_SETUP_CONFIRMATION" or policy in {"WATCH", "WATCH_ONLY", "LONG_HORIZON_ONLY"}:
        return "CONFIRMATION_PENDING"
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
