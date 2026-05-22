from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


WATCH_BUY_SELECTION_STATES = {
    "ELIGIBLE",
    "PASS",
    "WATCH",
    "WATCHLIST",
    "WATCH_CORE",
    "STRONG_WATCHLIST",
    "NEUTRAL",
    "BUY",
    "BUY_READY",
    "ACCUMULATE",
    "CANDIDATE",
}

TARGET_FINISHED_STATES = {
    "TARGET_REACHED",
    "TARGET_OVERSHOT",
    "TARGET_REACHED_STALE",
    "DOWNSIDE_TARGET_REACHED",
}

CRITICAL_CONTEXT_TOKENS = {
    "CRITICAL_DATA_MISSING",
    "MISSING_CURRENT_PRICE",
    "MISSING_LEG_DIRECTION",
    "MISSING_REQUIRED_ZONE_DATA",
    "MISSING_TARGET",
    "NEXT_ZONE_UNKNOWN",
    "PRICE_PROGRESS_UNKNOWN",
    "STRUCTURAL_MAP_MISSING",
    "NO_STRUCTURAL_MAP",
    "LTF_MISSING",
}


@dataclass(frozen=True)
class DestinationEligibility:
    eligible: bool
    exclusion_reasons: list[str]


@dataclass(frozen=True)
class DestinationConfidence:
    confidence_label: str
    evidence_labels: list[str]
    clean_actionable: bool


def norm(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()


def value(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def text_blob(*values: Any) -> str:
    parts: list[str] = []
    for item in values:
        if item is None:
            continue
        if isinstance(item, (list, tuple, set)):
            parts.extend(norm(part) for part in item if norm(part))
        else:
            parts.append(norm(item))
    return " ".join(part for part in parts if part)


def to_decimal(value_: Any) -> Decimal | None:
    if value_ is None:
        return None
    if isinstance(value_, Decimal):
        return value_
    try:
        return Decimal(str(value_))
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


def pct_delta(reference: Decimal | None, current_price: Decimal | None) -> Decimal | None:
    if reference is None or current_price is None or current_price <= 0:
        return None
    return ((reference / current_price) - Decimal("1")) * Decimal("100")


def destination_confidence(
    advice_row: dict[str, Any] | None,
    *,
    market_breath_row: dict[str, Any] | None = None,
) -> DestinationConfidence:
    if not advice_row:
        return DestinationConfidence(
            confidence_label="MISSING_APLUS_CONTEXT",
            evidence_labels=["MISSING_APLUS_CONTEXT"],
            clean_actionable=False,
        )

    evidence: list[str] = []
    aplus_bucket = norm(value(advice_row, "aplus_bucket"))
    aplus_freshness = norm(
        None if market_breath_row is None else market_breath_row.get("aplus_legacy_freshness_state")
    )
    aplus_block_strength = norm(
        None if market_breath_row is None else market_breath_row.get("aplus_legacy_block_strength")
    )
    strategic_bias = norm(
        None if market_breath_row is None else market_breath_row.get("aplus_table1_strategic_bias")
    )
    market_breath_context = norm(
        None if market_breath_row is None else market_breath_row.get("market_breath_context_state")
    )
    market_breath_confidence = to_decimal(
        None if market_breath_row is None else market_breath_row.get("market_breath_confidence")
    )
    relative_strength = to_decimal(
        None if market_breath_row is None else market_breath_row.get("relative_strength_score")
    )
    momentum = to_decimal(
        None if market_breath_row is None else market_breath_row.get("momentum_score")
    )

    if (
        not aplus_bucket
        or aplus_bucket == "APLUS_UNKNOWN"
        or not aplus_freshness
        or aplus_freshness == "UNKNOWN"
    ):
        evidence.append("MISSING_APLUS_CONTEXT")
    if aplus_freshness in {"STALE", "VERY_STALE"}:
        evidence.append("STALE_APLUS_CONTEXT")
    if aplus_bucket == "APLUS_AVOID" or aplus_block_strength in {
        "READ_ONLY_APLUS_AVOID",
        "LEGACY_CONTEXT_ONLY",
    } or strategic_bias == "AVOID":
        evidence.append("APLUS_AVOID_OR_DISTORTED")

    weak_curve = False
    if market_breath_row is None:
        weak_curve = True
    if market_breath_context in {"", "MARKET_BREATH_UNKNOWN"}:
        weak_curve = True
    if market_breath_confidence is not None and market_breath_confidence < Decimal("0.35"):
        weak_curve = True
    if relative_strength is not None and relative_strength <= Decimal("0"):
        weak_curve = True
    if momentum is not None and momentum <= Decimal("0"):
        weak_curve = True
    if weak_curve:
        evidence.append("WEAK_CURVE_STRUCTURE")

    evidence = list(dict.fromkeys(evidence))
    if any(
        label in evidence
        for label in {
            "MISSING_APLUS_CONTEXT",
            "STALE_APLUS_CONTEXT",
            "APLUS_AVOID_OR_DISTORTED",
        }
    ):
        label = "LOW_CONFIDENCE_DESTINATION"
    elif "WEAK_CURVE_STRUCTURE" in evidence:
        label = "MEDIUM_CONFIDENCE_DESTINATION"
    elif aplus_bucket.startswith("APLUS_") and aplus_freshness in {"FRESH", "AGING"}:
        label = "HIGH_CONFIDENCE_DESTINATION"
    else:
        label = "MARKET_ONLY_DESTINATION"

    if label == "MARKET_ONLY_DESTINATION":
        evidence.append("MARKET_ONLY_DESTINATION")

    return DestinationConfidence(
        confidence_label=label,
        evidence_labels=evidence,
        clean_actionable=label in {
            "HIGH_CONFIDENCE_DESTINATION",
            "MEDIUM_CONFIDENCE_DESTINATION",
        },
    )


def post_refresh_state_is_clean(
    *,
    lifecycle_state: Any,
    recompute_needed: bool,
    recompute_reason: Any,
    intrabar_recompute_hint: Any = None,
) -> bool:
    lifecycle = norm(lifecycle_state)
    recompute_text = text_blob(recompute_reason, intrabar_recompute_hint)
    if recompute_needed:
        return False
    if lifecycle not in {"ACTIVE_MAP", "CURRENT_MAP_ACTIVE"}:
        return False
    if any(
        token in recompute_text
        for token in {
            "RECOMPUTE",
            "INVALIDATION_TOUCHED",
            "RECOMPUTED_BUT_STILL_TRIGGERING",
            "TARGET_REACHED_STALE",
            "TARGET_OVERSHOT",
            "RECLAIM_CONFIRMED",
        }
    ):
        return False
    return True


def evaluate_rotation_destination_eligibility(
    advice_row: dict[str, Any] | None,
    *,
    current_price: Decimal | None,
    target_state: Any,
    risk_state: Any,
    lifecycle_state: Any,
    recompute_needed: bool,
    recompute_reason: Any,
    policy_label: Any = None,
    action_label: Any = None,
    entry_state: Any = None,
    price_progress_state: Any = None,
    price_progress_labels: tuple[str, ...] | list[str] = (),
    next_zone_state: Any = None,
    next_reaction_zone_label: Any = None,
    next_target_zone_label: Any = None,
    next_target_zone: tuple[Decimal, Decimal] | None = None,
    intrabar_lifecycle_state: Any = None,
    intrabar_recompute_hint: Any = None,
    intrabar_data_quality_state: Any = None,
) -> DestinationEligibility:
    if not advice_row:
        return DestinationEligibility(False, ["EXCLUDED_CRITICAL_CONTEXT"])

    reasons: list[str] = []
    setup_state = norm(value(advice_row, "setup_filter_state"))
    setup_reason = norm(value(advice_row, "setup_filter_reason"))
    selection_state = norm(value(advice_row, "selection_state"))
    advice_action = norm(value(advice_row, "advice_action"))
    advice_state = norm(value(advice_row, "advice_state"))
    policy_decision = norm(value(advice_row, "policy_decision"))
    leg_direction = norm(value(advice_row, "leg_direction"))
    target = norm(target_state)
    risk = norm(risk_state)
    lifecycle = norm(lifecycle_state)
    policy = norm(policy_label)
    action = norm(action_label)
    progress = norm(price_progress_state)
    entry = norm(entry_state)
    next_state = norm(next_zone_state)
    target_label = norm(next_target_zone_label)
    reaction_label = norm(next_reaction_zone_label)
    intrabar = norm(intrabar_lifecycle_state)
    all_context = text_blob(
        setup_state,
        setup_reason,
        selection_state,
        advice_action,
        advice_state,
        policy_decision,
        leg_direction,
        target,
        risk,
        lifecycle,
        recompute_reason,
        policy,
        action,
        entry,
        progress,
        price_progress_labels,
        next_state,
        target_label,
        reaction_label,
        intrabar,
        intrabar_recompute_hint,
        intrabar_data_quality_state,
    )

    if setup_state != "PASS" or "SETUP_FILTER_FAIL" in setup_reason or policy == "BLOCK_SETUP_FILTER_FAIL":
        reasons.append("EXCLUDED_SETUP_FAIL")

    if not selection_state or selection_state not in WATCH_BUY_SELECTION_STATES:
        reasons.append("EXCLUDED_SELECTION_NOT_ELIGIBLE")

    if leg_direction == "DOWN":
        reasons.append("EXCLUDED_DOWN_LEG_TARGET")

    target_reference = (
        (next_target_zone[0] + next_target_zone[1]) / Decimal("2")
        if next_target_zone is not None
        else midpoint_or_edge(value(advice_row, "tp_zone_low"), value(advice_row, "tp_zone_high"))
    )
    target_distance = pct_delta(target_reference, current_price)
    if leg_direction == "UP" and target_distance is not None and target_distance < 0:
        reasons.append("EXCLUDED_NEGATIVE_TARGET_DISTANCE")

    if "NO_CHASE_WITHOUT_NEW_ZONE" in all_context:
        reasons.append("EXCLUDED_NO_CHASE")

    if policy == "BLOCK_RECOMPUTE_PENDING" and not post_refresh_state_is_clean(
        lifecycle_state=lifecycle,
        recompute_needed=recompute_needed,
        recompute_reason=recompute_reason,
        intrabar_recompute_hint=intrabar_recompute_hint,
    ):
        reasons.append("EXCLUDED_RECOMPUTE_PENDING")

    has_fresh_continuation_or_retest = any(
        token in all_context
        for token in {
            "CONTINUATION",
            "RETEST",
            "NEXT_UPSIDE_EXTENSION",
            "RECLAIM_RETEST_SUPPORT",
            "TARGET_RETEST_SUPPORT",
        }
    )
    if (
        target in TARGET_FINISHED_STATES
        or lifecycle in TARGET_FINISHED_STATES
        or progress in TARGET_FINISHED_STATES
    ) and not has_fresh_continuation_or_retest:
        reasons.append("EXCLUDED_TARGET_ALREADY_REACHED")

    if (
        current_price is None
        or current_price <= 0
        or leg_direction not in {"UP", "DOWN"}
        or target_reference is None
        or target == "TARGET_UNKNOWN"
        or risk == "RISK_UNKNOWN"
        or any(token in all_context for token in CRITICAL_CONTEXT_TOKENS)
    ):
        reasons.append("EXCLUDED_CRITICAL_CONTEXT")

    if any(
        token in all_context
        for token in {
            "INVALIDATION_TOUCHED",
            "RECOMPUTED_BUT_STILL_TRIGGERING",
            "INTRABAR_INVALIDATION_TOUCHED",
        }
    ):
        reasons.append("EXCLUDED_CRITICAL_CONTEXT")

    return DestinationEligibility(
        eligible=not reasons,
        exclusion_reasons=list(dict.fromkeys(reasons)),
    )
