from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.reporting.policy_block_reason_display_v1 import PolicyBlockDisplay


HARD_BLOCK = "HARD_BLOCK"
SOFT_BLOCK = "SOFT_BLOCK"
OPPORTUNITY_REVIEW = "OPPORTUNITY_REVIEW"
MOMENTUM_EXTENSION_REVIEW = "MOMENTUM_EXTENSION_REVIEW"
RECLAIM_REVIEW = "RECLAIM_REVIEW"
WAIT_FOR_RECLAIM = "WAIT_FOR_RECLAIM"
WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
CONTEXT_ONLY = "CONTEXT_ONLY"

CONSTRUCTIVE_MARKET_BREATH_CONTEXTS = {
    "MARKET_BREATH_EXPANSION_CONTEXT",
    "MARKET_BREATH_ACCUMULATION_CONTEXT",
    "MARKET_BREATH_NEUTRAL_CONTEXT",
}

TARGET_REVIEW_STATES = {
    "TARGET_REACHED",
    "TARGET_OVERSHOT",
    "TARGET_REACHED_STALE",
}

RECLAIM_STATES = {
    "RECLAIM_CONFIRMED",
    "RECLAIM_NEAR",
}


@dataclass(frozen=True)
class PaperAdviceSeverity:
    advice_severity: str
    advice_substate: str
    reason_codes: list[str]
    display_label: str
    display_note: str
    policy_block: PolicyBlockDisplay | None = None


def _value(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _reason_codes(row: Any) -> list[str]:
    raw = _value(row, "reason_codes")
    if isinstance(raw, list):
        return [_norm(item) for item in raw if _norm(item)]

    raw_json = _value(row, "reason_codes_json")
    if raw_json:
        try:
            parsed = json.loads(str(raw_json))
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            return [_norm(item) for item in parsed if _norm(item)]

    return []


def _market_breath_context(market_breath_row: dict[str, Any] | None) -> str:
    return _norm(None if market_breath_row is None else market_breath_row.get("market_breath_context_state"))


def _aplus_freshness(market_breath_row: dict[str, Any] | None) -> str:
    return _norm(None if market_breath_row is None else market_breath_row.get("aplus_legacy_freshness_state"))


def _has_recompute_reason(recompute_reason: str, *needles: str) -> bool:
    normalized = _norm(recompute_reason)
    return any(needle in normalized for needle in needles)


def calibrate_paper_advice_severity(
    row: Any,
    *,
    market_breath_row: dict[str, Any] | None = None,
    lifecycle_state: str | None = None,
    recompute_needed: bool = False,
    recompute_reason: str | None = None,
    target_state: str | None = None,
    risk_state: str | None = None,
    entry_state: str | None = None,
    price_progress_state: str | None = None,
) -> PaperAdviceSeverity:
    advice_action = _norm(_value(row, "advice_action"))
    aplus_bucket = _norm(_value(row, "aplus_bucket"))
    selection_state = _norm(_value(row, "selection_state"))
    setup_state = _norm(_value(row, "setup_filter_state"))
    setup_reason = _norm(_value(row, "setup_filter_reason"))
    leg_direction = _norm(_value(row, "leg_direction"))
    lifecycle = _norm(lifecycle_state)
    target = _norm(target_state)
    risk = _norm(risk_state)
    entry = _norm(entry_state)
    price_progress = _norm(price_progress_state)
    recompute_text = recompute_reason or ""
    reasons = _reason_codes(row)
    market_context = _market_breath_context(market_breath_row)
    aplus_freshness = _aplus_freshness(market_breath_row)
    stale_aplus_avoid = aplus_bucket == "APLUS_AVOID" and aplus_freshness in {"STALE", "VERY_STALE"}
    constructive_market = market_context in CONSTRUCTIVE_MARKET_BREATH_CONTEXTS
    severity_reasons: list[str] = []
    if stale_aplus_avoid:
        severity_reasons.append("STALE_APLUS_CONTEXT")
    if market_context:
        severity_reasons.append(market_context)
    if recompute_needed:
        severity_reasons.append("MAP_RECOMPUTE_NEEDED")

    if lifecycle in {"PRICE_UNKNOWN", "LIFECYCLE_UNKNOWN"}:
        return PaperAdviceSeverity(
            HARD_BLOCK,
            "CRITICAL_DATA_MISSING",
            reasons + severity_reasons + [lifecycle],
            "Hard block",
            "Critical market context is missing.",
        )

    if setup_reason == "MARKET_DAMAGE_RISK" or risk == "RISK_UNKNOWN":
        return PaperAdviceSeverity(
            HARD_BLOCK,
            "MARKET_DAMAGE_OR_UNKNOWN_RISK",
            reasons + severity_reasons,
            "Hard block",
            "Market risk context remains hard-blocked.",
        )

    if lifecycle == "INVALIDATION_TOUCHED" or _has_recompute_reason(
        recompute_text,
        "UP_MAP_INVALIDATED_BY_BREAKDOWN",
        "INVALIDATION_TOUCHED",
    ):
        return PaperAdviceSeverity(
            HARD_BLOCK,
            "STRUCTURAL_INVALIDATION",
            reasons + severity_reasons + ["STRUCTURAL_INVALIDATION"],
            "Hard block",
            "The map is structurally invalidated.",
        )

    if (
        lifecycle in TARGET_REVIEW_STATES
        or target in TARGET_REVIEW_STATES
        or _has_recompute_reason(recompute_text, "TARGET_REACHED", "TARGET_OVERSHOT")
    ):
        substate = "REFRESH_NEEDED_REVIEW" if recompute_needed else "NO_CHASE_WITHOUT_NEW_ZONE"
        return PaperAdviceSeverity(
            MOMENTUM_EXTENSION_REVIEW,
            substate,
            reasons + severity_reasons + ["MOMENTUM_EXTENSION_REVIEW"],
            "Momentum extension review",
            "Review context, not trade advice.",
        )

    if lifecycle in RECLAIM_STATES or _has_recompute_reason(
        recompute_text,
        "RECLAIM_CONFIRMED",
        "DOWN_MAP_INVALIDATED_BY_RECLAIM",
    ):
        return PaperAdviceSeverity(
            RECLAIM_REVIEW,
            "RECLAIM_REVIEW",
            reasons + severity_reasons + ["RECLAIM_REVIEW"],
            "Reclaim review",
            "Review reclaim context before any new map decision.",
        )

    if leg_direction == "DOWN" and (
        lifecycle == "RECLAIM_NEAR"
        or risk == "RECLAIM_CONFIRMED"
        or _has_recompute_reason(recompute_text, "RECLAIM_NEAR")
    ):
        return PaperAdviceSeverity(
            WAIT_FOR_RECLAIM,
            "WAIT_FOR_RECLAIM",
            reasons + severity_reasons + ["WAIT_FOR_RECLAIM"],
            "Wait for reclaim",
            "Soft caution, not permission.",
        )

    if stale_aplus_avoid:
        if leg_direction == "DOWN":
            severity = WAIT_FOR_RECLAIM if constructive_market else SOFT_BLOCK
            substate = "WAIT_FOR_RECLAIM" if constructive_market else "STALE_APLUS_CONTEXT"
        elif constructive_market:
            severity = RECLAIM_REVIEW if lifecycle in RECLAIM_STATES else SOFT_BLOCK
            substate = "STALE_APLUS_CONTEXT"
        else:
            severity = SOFT_BLOCK
            substate = "STALE_APLUS_CONTEXT"
        return PaperAdviceSeverity(
            severity,
            substate,
            reasons + severity_reasons,
            "Stale A+ context",
            "Stale A+ avoid is soft context, not a hard current veto by itself.",
        )

    if advice_action in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY"} or aplus_bucket == "APLUS_AVOID":
        severity = SOFT_BLOCK if market_context else HARD_BLOCK
        return PaperAdviceSeverity(
            severity,
            "CURRENT_CAUTION_CONTEXT",
            reasons + severity_reasons,
            "Soft caution" if severity == SOFT_BLOCK else "Hard block",
            "Soft caution, not permission." if severity == SOFT_BLOCK else "Current context remains blocked.",
        )

    if selection_state not in {"WATCHLIST", "ELIGIBLE", "PASS"} and constructive_market:
        return PaperAdviceSeverity(
            OPPORTUNITY_REVIEW,
            "MARKET_CONTEXT_REVIEW",
            reasons + severity_reasons + ["OPPORTUNITY_REVIEW"],
            "Opportunity review",
            "Market context is visible for review, not trade advice.",
        )

    if entry in {"ENTRY_WINDOW_PASSED", "CHASE_RISK"} or price_progress in {"CHASE_RISK", "TARGET_NEAR"}:
        return PaperAdviceSeverity(
            WAIT_FOR_PULLBACK,
            "WAIT_FOR_PULLBACK",
            reasons + severity_reasons + ["WAIT_FOR_PULLBACK"],
            "Wait for pullback",
            "Soft caution, not permission.",
        )

    if setup_state and setup_state != "PASS":
        return PaperAdviceSeverity(
            CONTEXT_ONLY,
            "SETUP_CONTEXT_ONLY",
            reasons + severity_reasons,
            "Context only",
            "Review context, not trade advice.",
        )

    return PaperAdviceSeverity(
        CONTEXT_ONLY,
        "ACTIVE_REVIEW_CONTEXT",
        reasons + severity_reasons,
        "Review context",
        "Review context, not trade advice.",
    )


def severity_summary_text(severity: PaperAdviceSeverity) -> str:
    return f"{severity.advice_severity} / {severity.advice_substate}"
