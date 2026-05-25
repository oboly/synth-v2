from __future__ import annotations

from dataclasses import dataclass


UNKNOWN_LABEL_DESCRIPTION = "No description registered yet."


@dataclass(frozen=True)
class LabelDescription:
    label: str
    description: str


_REGISTRY: dict[str, LabelDescription] = {
    item.label: item
    for item in [
        LabelDescription("REDUCE_CANDIDATE", "Review pressure for an existing holding. Not an automatic sell instruction."),
        LabelDescription("EXIT_CANDIDATE", "Stronger review pressure for an existing holding. Downstream permission is still required."),
        LabelDescription("HOLD_REVIEW", "Existing holding can be monitored. No manual trade action is implied."),
        LabelDescription("HOLD_DEFENSIVE", "Keep existing position under defensive context. Not a buy or sell instruction."),
        LabelDescription("MANUAL_REDUCE_CHECK", "Manual review needed after target/risk context. Not an automatic sell."),
        LabelDescription("MANUAL_CHECK", "User review needed. No automatic trade action."),
        LabelDescription("TARGET_REACHED", "Mapped target or reaction zone has been reached or touched."),
        LabelDescription("TARGET_PENDING", "Mapped target has not been reached yet."),
        LabelDescription("TARGET_REACHED_STALE", "Target reached context exists, but the map may need refresh before relying on it."),
        LabelDescription("TARGET_TOUCHED_RECENTLY", "Latest lower-timeframe candle touched the target zone; price may already have moved away."),
        LabelDescription("EXTENSION_TOUCHED_INTRABAR", "Intrabar high/low touched the mapped extension or target zone."),
        LabelDescription("PULLBACK_AFTER_TARGET_TOUCH", "Target was touched intrabar and current price has pulled back from the touch."),
        LabelDescription("STALE_FOR_INTRABAR_DECISION", "Intrabar decision context is older than the freshness threshold; verify live chart before acting."),
        LabelDescription("RISK_NEAR", "Price is near a mapped risk/invalidation zone."),
        LabelDescription("RECLAIM_NEAR", "Price is near a reclaim or invalidation boundary; fresh recompute may be needed."),
        LabelDescription("RECLAIM_CONFIRMED", "Price has reclaimed a previous invalidation/reclaim level."),
        LabelDescription("MARKET_DAMAGE_CAUTION", "Market context is in caution band; blocks or limits new exposure depending on downstream rules."),
        LabelDescription("MARKET_DAMAGE_RISK", "Market context is damaged; new exposure is blocked by risk context."),
        LabelDescription("APLUS_AVOID", "External A+ context marks this asset as avoid/caution. It is context, not an order."),
        LabelDescription("APLUS_ANCHOR_CONTEXT", "External A+ context marks this as anchor/core context. It is not trade permission."),
        LabelDescription("APLUS_CANONICAL_CORE", "External A+ context marks this as stronger/core context. It is not trade permission."),
        LabelDescription("DO_NOT_ADD", "Do not increase this existing position under current context."),
        LabelDescription("NO_INCREASE", "Do not add to this existing position under current context."),
        LabelDescription("NO_NEW_BUY", "No new buy is allowed under current context."),
        LabelDescription("BLOCKED_NO_NEW_BUY", "New buy is blocked. Check cause/unblock text."),
        LabelDescription("SETUP_FAILED", "Setup filter did not pass. This is not an entry."),
        LabelDescription("SETUP_FAIL", "Setup filter did not pass. This is not an entry."),
        LabelDescription("PAPER_BUY_READY", "Research/paper candidate only. Not live permission."),
        LabelDescription("WATCH_FOR_CONFIRMATION", "Candidate needs confirmation before any paper/live consideration."),
        LabelDescription("ZONE_RECOMPUTE_NEEDED", "Current zone/map should be refreshed before relying on it."),
        LabelDescription("WAIT_RECOMPUTE", "Wait for a fresh zone/advice recompute before interpreting the row."),
        LabelDescription("WAIT_RECOMPUTE_FOR_INCREASE", "Do not increase until recompute confirms a fresh map/advice."),
        LabelDescription("SUPPORT_BELOW", "Below-price support/retest context. Not a take-profit target."),
        LabelDescription("RETEST_ZONE_BELOW", "Below-price retest/support context. Not a take-profit target."),
        LabelDescription("UPSIDE_REACTION_TARGET", "Above-price reaction target context. Not trade permission."),
        LabelDescription("UPSIDE_EXTENSION_PREVIEW", "Possible upside extension context. Requires fresh map/advice before action."),
        LabelDescription("ENTRY_FIB_PRIMARY_0500_0618", "Entry zone aligns with primary Fibonacci retracement band."),
        LabelDescription("TP_SR_ONLY", "Target is support/resistance only; historically weaker than near-fib extension context."),
        LabelDescription("TP_NEAR_FIB_EXTENSION", "Target is near a Fibonacci extension band; research scoreboard shows stronger separation than SR-only."),
    ]
}


def get_label_description(label: str) -> str:
    normalized = str(label or "").strip().upper()
    if not normalized:
        return UNKNOWN_LABEL_DESCRIPTION
    return _REGISTRY.get(normalized, LabelDescription(normalized, UNKNOWN_LABEL_DESCRIPTION)).description


def get_label_aria_label(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return UNKNOWN_LABEL_DESCRIPTION
    return f"{text}: {get_label_description(text)}"
