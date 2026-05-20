from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


FIB_LOW = Decimal("0.382")
FIB_HIGH = Decimal("0.618")
RETEST_BAND_PCT = Decimal("0.005")


@dataclass(frozen=True)
class NextZonePreview:
    next_zone_state: str
    next_reaction_zone: tuple[Decimal, Decimal] | None
    next_reaction_zone_label: str
    next_target_zone: tuple[Decimal, Decimal] | None
    next_target_zone_label: str
    next_zone_reason: str


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def midpoint(low: Any, high: Any) -> Decimal | None:
    low_dec = to_decimal(low)
    high_dec = to_decimal(high)
    if low_dec is not None and high_dec is not None:
        return (low_dec + high_dec) / Decimal("2")
    return low_dec if low_dec is not None else high_dec


def ordered_zone(low: Decimal, high: Decimal) -> tuple[Decimal, Decimal]:
    return (low, high) if low <= high else (high, low)


def existing_zone(low: Any, high: Any) -> tuple[Decimal, Decimal] | None:
    low_dec = to_decimal(low)
    high_dec = to_decimal(high)
    if low_dec is None and high_dec is None:
        return None
    if low_dec is None:
        low_dec = high_dec
    if high_dec is None:
        high_dec = low_dec
    if low_dec is None or high_dec is None:
        return None
    return ordered_zone(low_dec, high_dec)


def retest_band(price: Decimal) -> tuple[Decimal, Decimal]:
    width = abs(price) * RETEST_BAND_PCT
    if width == 0:
        width = Decimal("0.00000001")
    return ordered_zone(price - width, price + width)


def labels_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item).upper() for item in value if item is not None)
        else:
            parts.append(str(value).upper())
    return " ".join(parts)


def has_any_label(text: str, labels: set[str]) -> bool:
    return any(label in text for label in labels)


def active_preview(reason: str = "CURRENT_MAP_HAS_NO_NEXT_ZONE_PREVIEW") -> NextZonePreview:
    return NextZonePreview(
        next_zone_state="CURRENT_MAP_ACTIVE",
        next_reaction_zone=None,
        next_reaction_zone_label="",
        next_target_zone=None,
        next_target_zone_label="",
        next_zone_reason=reason,
    )


def unknown_preview(reason: str) -> NextZonePreview:
    return NextZonePreview(
        next_zone_state="NEXT_ZONE_UNKNOWN",
        next_reaction_zone=None,
        next_reaction_zone_label="",
        next_target_zone=None,
        next_target_zone_label="",
        next_zone_reason=reason,
    )


def preview_next_zones(
    *,
    symbol: str | None = None,
    leg_direction: Any,
    current_price: Any,
    entry_zone_low: Any,
    entry_zone_high: Any,
    tp_zone_low: Any,
    tp_zone_high: Any,
    invalidation_price: Any,
    lifecycle_state: Any = None,
    lifecycle_reason: Any = None,
    lifecycle_labels: Any = None,
    target_state: Any = None,
    price_progress_state: Any = None,
) -> NextZonePreview:
    del symbol
    leg = str(leg_direction or "").upper()
    current = to_decimal(current_price)
    invalidation = to_decimal(invalidation_price)
    entry_mid = midpoint(entry_zone_low, entry_zone_high)
    target_mid = midpoint(tp_zone_low, tp_zone_high)
    target_zone = existing_zone(tp_zone_low, tp_zone_high)
    text = labels_text(
        lifecycle_state,
        lifecycle_reason,
        lifecycle_labels,
        target_state,
        price_progress_state,
    )

    if leg not in {"UP", "DOWN"}:
        return unknown_preview("MISSING_LEG_DIRECTION")
    if current is None:
        return unknown_preview("MISSING_CURRENT_PRICE")

    if (
        leg == "DOWN"
        and invalidation is not None
        and current >= invalidation
        and has_any_label(text, {"RECLAIM_CONFIRMED", "DOWN_MAP_INVALIDATED_BY_RECLAIM"})
    ):
        if target_mid is None:
            return unknown_preview("MISSING_TARGET_FOR_RECLAIM_NEXT_ZONE")
        old_down_range = invalidation - target_mid
        if old_down_range <= 0:
            return unknown_preview("NONSENSICAL_DOWN_RANGE_FOR_RECLAIM_NEXT_ZONE")
        return NextZonePreview(
            next_zone_state="RECLAIM_NEXT_ZONE_PREVIEW",
            next_reaction_zone=retest_band(invalidation),
            next_reaction_zone_label="RECLAIM_RETEST_SUPPORT",
            next_target_zone=ordered_zone(
                invalidation + (FIB_LOW * old_down_range),
                invalidation + (FIB_HIGH * old_down_range),
            ),
            next_target_zone_label="NEXT_UPSIDE_REACTION_TARGET",
            next_zone_reason="DOWN_MAP_RECLAIMED_ABOVE_INVALIDATION",
        )

    if (
        leg == "UP"
        and invalidation is not None
        and current <= invalidation
        and has_any_label(text, {"INVALIDATION_TOUCHED", "UP_MAP_INVALIDATED_BY_BREAKDOWN"})
    ):
        reference = target_mid if target_mid is not None else entry_mid
        if reference is None:
            return unknown_preview("MISSING_REFERENCE_FOR_BREAKDOWN_NEXT_ZONE")
        old_up_range = abs(reference - invalidation)
        if old_up_range <= 0:
            return unknown_preview("NONSENSICAL_UP_RANGE_FOR_BREAKDOWN_NEXT_ZONE")
        return NextZonePreview(
            next_zone_state="BREAKDOWN_NEXT_ZONE_PREVIEW",
            next_reaction_zone=retest_band(invalidation),
            next_reaction_zone_label="BREAKDOWN_RETEST_RESISTANCE",
            next_target_zone=ordered_zone(
                invalidation - (FIB_HIGH * old_up_range),
                invalidation - (FIB_LOW * old_up_range),
            ),
            next_target_zone_label="NEXT_DOWNSIDE_REACTION_TARGET",
            next_zone_reason="UP_MAP_INVALIDATED_BY_BREAKDOWN",
        )

    if leg == "UP" and has_any_label(
        text,
        {"TARGET_REACHED", "TARGET_OVERSHOT", "TARGET_REACHED_STALE"},
    ):
        if target_mid is None or entry_mid is None:
            return unknown_preview("MISSING_ENTRY_OR_TARGET_FOR_UPSIDE_EXTENSION")
        old_up_range = target_mid - entry_mid
        if old_up_range <= 0:
            return unknown_preview("NONSENSICAL_UP_RANGE_FOR_UPSIDE_EXTENSION")
        return NextZonePreview(
            next_zone_state="UPSIDE_EXTENSION_PREVIEW",
            next_reaction_zone=target_zone,
            next_reaction_zone_label="TARGET_RETEST_SUPPORT",
            next_target_zone=ordered_zone(
                target_mid + (FIB_LOW * old_up_range),
                target_mid + (FIB_HIGH * old_up_range),
            ),
            next_target_zone_label="NEXT_UPSIDE_EXTENSION",
            next_zone_reason="UP_TARGET_FINISHED_OR_STALE",
        )

    if leg == "DOWN" and has_any_label(
        text,
        {"DOWNSIDE_TARGET_REACHED", "TARGET_REACHED", "TARGET_REACHED_STALE", "TARGET_OVERSHOT"},
    ):
        if target_mid is None or entry_mid is None:
            return unknown_preview("MISSING_ENTRY_OR_TARGET_FOR_DOWNSIDE_EXTENSION")
        old_down_range = entry_mid - target_mid
        if old_down_range <= 0:
            return unknown_preview("NONSENSICAL_DOWN_RANGE_FOR_DOWNSIDE_EXTENSION")
        return NextZonePreview(
            next_zone_state="DOWNSIDE_EXTENSION_PREVIEW",
            next_reaction_zone=target_zone,
            next_reaction_zone_label="DOWNSIDE_TARGET_SUPPORT_RETEST",
            next_target_zone=ordered_zone(
                target_mid - (FIB_HIGH * old_down_range),
                target_mid - (FIB_LOW * old_down_range),
            ),
            next_target_zone_label="NEXT_DOWNSIDE_EXTENSION",
            next_zone_reason="DOWN_TARGET_SUPPORT_FINISHED_OR_STALE",
        )

    if "UNKNOWN" in text:
        return unknown_preview("INSUFFICIENT_LIFECYCLE_CONTEXT")

    return active_preview()


def format_zone(zone: tuple[Decimal, Decimal] | None, places: str = "0.000000") -> str:
    if zone is None:
        return ""
    low, high = zone
    try:
        low_text = str(low.quantize(Decimal(places)))
        high_text = str(high.quantize(Decimal(places)))
    except Exception:
        low_text = str(low)
        high_text = str(high)
    if low_text == high_text:
        return low_text
    return f"{low_text}..{high_text}"
