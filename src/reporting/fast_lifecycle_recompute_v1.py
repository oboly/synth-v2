from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


DEFAULT_NEAR_PCT = Decimal("2.0")
DEFAULT_OVERSHOOT_PCT = Decimal("1.0")
DEFAULT_STALE_AFTER_TARGET_PCT = Decimal("1.0")


@dataclass(frozen=True)
class LifecycleRecomputeStatus:
    lifecycle_state: str
    recompute_needed: bool
    recompute_reason: str


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def midpoint_or_edge(low: Any, high: Any) -> Decimal | None:
    low_dec = to_decimal(low)
    high_dec = to_decimal(high)
    if low_dec is not None and high_dec is not None:
        return (low_dec + high_dec) / Decimal("2")
    if low_dec is not None:
        return low_dec
    return high_dec


def pct_distance(reference: Decimal, current_price: Decimal) -> Decimal:
    if reference <= 0 or current_price <= 0:
        return Decimal("0")
    return abs((current_price / reference) - Decimal("1")) * Decimal("100")


def classify_fast_lifecycle(
    *,
    leg_direction: str | None,
    current_price: Any,
    tp_zone_low: Any,
    tp_zone_high: Any,
    invalidation_price: Any,
    near_pct: Decimal = DEFAULT_NEAR_PCT,
    overshoot_pct: Decimal = DEFAULT_OVERSHOOT_PCT,
    stale_after_target_pct: Decimal = DEFAULT_STALE_AFTER_TARGET_PCT,
) -> LifecycleRecomputeStatus:
    price = to_decimal(current_price)
    target = midpoint_or_edge(tp_zone_low, tp_zone_high)
    invalidation = to_decimal(invalidation_price)
    leg = (leg_direction or "").upper()

    if price is None or price <= 0:
        return LifecycleRecomputeStatus("PRICE_UNKNOWN", False, "CURRENT_PRICE_MISSING")
    if leg not in {"UP", "DOWN"}:
        return LifecycleRecomputeStatus("LIFECYCLE_UNKNOWN", False, "LEG_DIRECTION_MISSING")

    reasons: list[str] = []
    target_reached = False
    target_overshot = False
    target_stale = False
    invalidation_near = False
    invalidation_touched = False
    reclaim_near = False

    if target is not None and target > 0:
        if leg == "UP":
            target_reached = price >= target
            target_overshot = price >= target * (Decimal("1") + overshoot_pct / Decimal("100"))
            target_stale = price >= target * (Decimal("1") + stale_after_target_pct / Decimal("100"))
        else:
            target_reached = price <= target
            target_overshot = price <= target * (Decimal("1") - overshoot_pct / Decimal("100"))
            target_stale = price <= target * (Decimal("1") - stale_after_target_pct / Decimal("100"))

    if invalidation is not None and invalidation > 0:
        if leg == "UP":
            invalidation_touched = price <= invalidation
            invalidation_near = price > invalidation and pct_distance(invalidation, price) <= near_pct
        else:
            invalidation_touched = price >= invalidation
            invalidation_near = price < invalidation and pct_distance(invalidation, price) <= near_pct
            reclaim_near = invalidation_touched or invalidation_near

    if target_reached:
        reasons.append("TARGET_REACHED")
    if target_overshot:
        reasons.append("TARGET_OVERSHOT")
    if target_stale:
        reasons.append("TARGET_REACHED_STALE")
    if invalidation_near:
        reasons.append("INVALIDATION_NEAR")
    if invalidation_touched:
        reasons.append("INVALIDATION_TOUCHED")
    if reclaim_near:
        reasons.append("RECLAIM_NEAR")

    recompute_needed = target_stale or invalidation_touched or reclaim_near
    if recompute_needed:
        reasons.append("MAP_RECOMPUTE_NEEDED")

    if invalidation_touched:
        state = "INVALIDATION_TOUCHED"
    elif target_stale:
        state = "TARGET_REACHED_STALE"
    elif target_overshot:
        state = "TARGET_OVERSHOT"
    elif target_reached:
        state = "TARGET_REACHED"
    elif reclaim_near:
        state = "RECLAIM_NEAR"
    elif invalidation_near:
        state = "INVALIDATION_NEAR"
    else:
        state = "ACTIVE_MAP"
        reasons.append("MAP_ACTIVE")

    return LifecycleRecomputeStatus(
        lifecycle_state=state,
        recompute_needed=recompute_needed,
        recompute_reason=", ".join(dict.fromkeys(reasons)),
    )
