from __future__ import annotations

from dataclasses import dataclass


UNKNOWN_LABEL_DESCRIPTION = "No description registered yet."


@dataclass(frozen=True)
class LabelDescription:
    label: str
    description: str
    category: str = "general"
    axis_name: str | None = None
    axis_type: str | None = None
    axis_value: int | None = None
    human_label: str | None = None
    action_hint: str | None = None


def _entry(
    label: str,
    description: str,
    *,
    category: str = "general",
    axis_name: str | None = None,
    axis_type: str | None = None,
    axis_value: int | None = None,
    human_label: str | None = None,
    action_hint: str | None = None,
) -> LabelDescription:
    return LabelDescription(
        label=label,
        description=description,
        category=category,
        axis_name=axis_name,
        axis_type=axis_type,
        axis_value=axis_value,
        human_label=human_label,
        action_hint=action_hint,
    )


_REGISTRY: dict[str, LabelDescription] = {
    item.label: item
    for item in [
        _entry("REDUCE_CANDIDATE", "Review pressure for an existing holding. Not an automatic sell instruction.", category="position_review"),
        _entry("EXIT_CANDIDATE", "Stronger review pressure for an existing holding. Downstream permission is still required.", category="position_review"),
        _entry("HOLD_REVIEW", "Existing holding can be monitored. No manual trade action is implied.", category="position_review"),
        _entry("HOLD_DEFENSIVE", "Keep existing position under defensive context. Not a buy or sell instruction.", category="position_review"),
        _entry("MANUAL_REDUCE_CHECK", "Manual review needed after target/risk context. Not an automatic sell.", category="position_review"),
        _entry("MANUAL_CHECK", "User review needed. No automatic trade action.", category="position_review"),
        _entry("TARGET_REACHED", "Mapped target or reaction zone has been reached or touched.", category="target_lifecycle"),
        _entry("TARGET_PENDING", "Mapped target has not been reached yet.", category="target_lifecycle"),
        _entry("TARGET_REACHED_STALE", "Target reached context exists, but the map may need refresh before relying on it.", category="target_lifecycle"),
        _entry("TARGET_TOUCHED_RECENTLY", "Latest lower-timeframe candle touched the target zone; price may already have moved away.", category="target_lifecycle"),
        _entry("EXTENSION_TOUCHED_INTRABAR", "Intrabar high/low touched the mapped extension or target zone.", category="target_lifecycle"),
        _entry("PULLBACK_AFTER_TARGET_TOUCH", "Target was touched intrabar and current price has pulled back from the touch.", category="target_lifecycle"),
        _entry("STALE_FOR_INTRABAR_DECISION", "Intrabar decision context is older than the freshness threshold; verify live chart before acting.", category="target_lifecycle"),
        _entry("RISK_NEAR", "Price is near a mapped risk/invalidation zone.", category="risk_market"),
        _entry("RECLAIM_NEAR", "Price is near a reclaim or invalidation boundary; fresh recompute may be needed.", category="risk_market"),
        _entry("RECLAIM_CONFIRMED", "Price has reclaimed a previous invalidation/reclaim level.", category="risk_market"),
        _entry("MARKET_DAMAGE_CAUTION", "Market context is in caution band; blocks or limits new exposure depending on downstream rules.", category="risk_market"),
        _entry("MARKET_DAMAGE_RISK", "Market context is damaged; new exposure is blocked by risk context.", category="risk_market"),
        _entry("APLUS_AVOID", "External A+ context marks this asset as avoid/caution. It is context, not an order.", category="aplus_context"),
        _entry("APLUS_ANCHOR_CONTEXT", "External A+ context marks this as anchor/core context. It is not trade permission.", category="aplus_context"),
        _entry("APLUS_CANONICAL_CORE", "External A+ context marks this as stronger/core context. It is not trade permission.", category="aplus_context"),
        _entry("DO_NOT_ADD", "Do not increase this existing position under current context.", category="add_buy_setup"),
        _entry("NO_INCREASE", "Do not add to this existing position under current context.", category="add_buy_setup"),
        _entry("NO_NEW_BUY", "No new buy is allowed under current context.", category="add_buy_setup"),
        _entry(
            "BLOCKED_NO_NEW_BUY",
            "New buy is blocked. Check the displayed cause/unblock reason.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=-6,
            human_label="No new buy",
            action_hint="New buy blocked",
        ),
        _entry("SETUP_FAILED", "Setup filter did not pass. This is not an entry.", category="add_buy_setup"),
        _entry("SETUP_FAIL", "Setup filter did not pass. This is not an entry.", category="add_buy_setup"),
        _entry("PAPER_BUY_READY", "Research/paper candidate only. Not live permission.", category="candidate_readiness"),
        _entry(
            "BUY_READY",
            "Market/setup side is ready for entry evaluation. Not order permission; decision_gate and execution_planner remain downstream.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=10,
            human_label="Entry ready",
            action_hint="Market/setup ready only",
        ),
        _entry(
            "ENTRY_CANDIDATE",
            "Strong market/setup context for entry review, but not yet buy-ready.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=8,
            human_label="Entry candidate",
            action_hint="Needs downstream permission",
        ),
        _entry(
            "BUY_CANDIDATE",
            "Positive market/setup candidate for later entry evaluation, but not yet entry-ready.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=6,
            human_label="Buy candidate",
            action_hint="Positive context only",
        ),
        _entry(
            "WATCH_FOR_CONFIRMATION",
            "Candidate needs confirmation before any paper/live consideration.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=4,
            human_label="Watch for confirmation",
            action_hint="Await confirmation",
        ),
        _entry(
            "CORE_CONTEXT",
            "Structurally relevant asset for market or portfolio context. Positive context, but not an entry trigger.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=2,
            human_label="Core context",
            action_hint="Positive context only",
        ),
        _entry(
            "WAIT",
            "Neutral state. No active entry setup, but not a hard avoid.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=0,
            human_label="Wait / no setup yet",
            action_hint="Neutral wait",
        ),
        _entry(
            "WAIT_FOR_SETUP",
            "Neutral state. Setup is not active yet, but the asset is not blocked.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=0,
            human_label="Wait / no setup yet",
            action_hint="Neutral wait",
        ),
        _entry(
            "CAUTION",
            "Caution context. The asset is not a hard avoid, but setup/risk is not strong enough for entry readiness.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=-3,
            human_label="Caution",
            action_hint="Limited context",
        ),
        _entry(
            "AVOID",
            "Unfavorable context. No new buy. Not an automatic full exit.",
            category="candidate_readiness",
            axis_name="candidate_readiness_pressure",
            axis_type="signed_int",
            axis_value=-10,
            human_label="Avoid / do not add",
            action_hint="Avoid new exposure",
        ),
        _entry(
            "INSUFFICIENT_SAMPLE",
            "Not enough data/sample to determine candidate readiness reliably.",
            category="data_quality",
            human_label="Insufficient sample",
            action_hint="Data unknown",
        ),
        _entry("ZONE_RECOMPUTE_NEEDED", "Current zone/map should be refreshed before relying on it.", category="add_buy_setup"),
        _entry("WAIT_RECOMPUTE", "Wait for a fresh zone/advice recompute before interpreting the row.", category="add_buy_setup"),
        _entry("WAIT_RECOMPUTE_FOR_INCREASE", "Do not increase until recompute confirms a fresh map/advice.", category="add_buy_setup"),
        _entry("SUPPORT_BELOW", "Below-price support/retest context. Not a take-profit target.", category="zone_labels"),
        _entry("RETEST_ZONE_BELOW", "Below-price retest/support context. Not a take-profit target.", category="zone_labels"),
        _entry("UPSIDE_REACTION_TARGET", "Above-price reaction target context. Not trade permission.", category="zone_labels"),
        _entry("UPSIDE_EXTENSION_PREVIEW", "Possible upside extension context. Requires fresh map/advice before action.", category="zone_labels"),
        _entry("DOWNSIDE_EXTENSION_PREVIEW", "Possible downside extension context after breakdown/continuation. Requires fresh map/advice before action.", category="zone_labels"),
        _entry("RECLAIM_NEXT_ZONE_PREVIEW", "Next-zone preview after reclaim/invalidation context. Market-only map preview, not trade permission.", category="zone_labels"),
        _entry("BREAKDOWN_NEXT_ZONE_PREVIEW", "Next-zone preview after breakdown/invalidation context. Market-only map preview, not trade permission.", category="zone_labels"),
        _entry("ENTRY_FIB_PRIMARY_0500_0618", "Entry zone aligns with primary Fibonacci retracement band.", category="zone_labels"),
        _entry("TP_SR_ONLY", "Target is support/resistance only; historically weaker than near-fib extension context.", category="zone_labels"),
        _entry("TP_NEAR_FIB_EXTENSION", "Target is near a Fibonacci extension band; research scoreboard shows stronger separation than SR-only.", category="zone_labels"),
        _entry("DISPLAY_CRITICAL", "Highest review severity on the dashboard. The row still needs action now.", category="dashboard_display"),
        _entry("DISPLAY_WATCH", "Watch/cooldown severity on the dashboard. Refresh happened, but the row still needs monitoring.", category="dashboard_display"),
        _entry("DISPLAY_MUTED", "Muted display severity. Context is retained, but no active refresh action is implied now.", category="dashboard_display"),
        _entry("DISPLAY_CONTEXT", "Context-only dashboard severity. The row is shown for background reference.", category="dashboard_display"),
        _entry("ZONE_AND_ADVICE_RECOMPUTE", "Both the structural zone map and advice context should be refreshed.", category="recompute_lifecycle"),
        _entry("ADVICE_ONLY_REVIEW", "Advice context should be reviewed while structural zones can remain reference context.", category="recompute_lifecycle"),
        _entry("COOLDOWN_MONITOR", "This candle was already refreshed. Keep watching until the next 4h map can form.", category="recompute_lifecycle"),
        _entry("COOLDOWN_ALREADY_REFRESHED_THIS_CANDLE", "Refresh already ran for the current candle; do not treat age alone as a fresh action signal.", category="recompute_lifecycle"),
        _entry("RECOMPUTE_TRIGGER", "A lifecycle trigger requires a fresh recompute now.", category="recompute_lifecycle"),
        _entry("RECLAIM_OR_INVALIDATION_TRIGGER", "Reclaim or invalidation was touched, so a fresh zone/advice recompute is needed.", category="recompute_lifecycle"),
        _entry("TARGET_REACHED_STALE_TRIGGER", "Target reached on an old map; refresh before relying on any follow-through.", category="recompute_lifecycle"),
        _entry("TARGET_FINISHED_REVIEW", "Target was already finished; review context may still matter, but it is not a fresh entry map.", category="recompute_lifecycle"),
        _entry("FRESH_TARGET_REVIEW", "Target finished on a still-fresh map. Wait for the next candle before refreshing again.", category="recompute_lifecycle"),
        _entry("REFRESH_NEEDED", "Raw post-refresh classification: the row still needs refresh action.", category="recompute_lifecycle"),
        _entry("REFRESH_NEEDED_NOW", "Effective dashboard state: refresh action is still needed now.", category="recompute_lifecycle"),
        _entry("REFRESHED_RECENTLY", "A recent refresh was recorded; shown as background context unless the row is still triggering.", category="recompute_lifecycle"),
        _entry("REFRESHED_THIS_RUN", "The refresh pipeline updated this row in the current run.", category="recompute_lifecycle"),
        _entry("RECOMPUTED_BUT_STILL_TRIGGERING", "Refresh ran, but the row still immediately triggers the same recompute condition.", category="recompute_lifecycle"),
        _entry("STILL_TRIGGERING_AFTER_REFRESH", "Effective dashboard state: refresh already ran, but the trigger is still active.", category="recompute_lifecycle"),
        _entry("CURRENT_MAP_ACTIVE", "The current structural map is still active.", category="recompute_lifecycle"),
        _entry("ACTIVE_MAP", "Structural map remains active without recompute requirement.", category="recompute_lifecycle"),
        _entry("SKIP_ACTIVE_MAP", "No recompute work is needed because the current map is still active.", category="recompute_lifecycle"),
        _entry("NO_REFRESH_NEEDED", "Raw post-refresh classification: no refresh action is needed now.", category="recompute_lifecycle"),
        _entry("WAIT_FOR_NEXT_CANDLE", "Wait for the next candle before requesting another refresh.", category="recompute_lifecycle"),
        _entry("WAIT_NEXT_4H_MAP", "Effective dashboard state: this candle is already refreshed, so wait for the next 4h map.", category="recompute_lifecycle"),
        _entry("ALREADY_REFRESHED_THIS_CANDLE", "Effective dashboard state: this candle already has a refresh record.", category="recompute_lifecycle"),
        _entry("DOWN_MAP_INVALIDATED_BY_RECLAIM", "A down-leg map was invalidated by reclaim, so the map should be refreshed.", category="recompute_lifecycle"),
        _entry("MAP_RECOMPUTE_NEEDED", "Lifecycle context says the current map needs recompute.", category="recompute_lifecycle"),
        _entry("TARGET_OVERSHOT", "Price moved through the mapped target enough that the map should be reviewed/refreshed.", category="recompute_lifecycle"),
        _entry("INVALIDATION_TOUCHED", "Price touched the mapped invalidation boundary.", category="recompute_lifecycle"),
        _entry("UP_MAP_INVALIDATED_BY_BREAKDOWN", "An up-leg map was invalidated by breakdown.", category="recompute_lifecycle"),
        _entry("SKIP_UNKNOWN_DATA", "The row is skipped from refresh action because key context is unknown or missing.", category="recompute_lifecycle"),
        _entry("UNKNOWN_DATA", "Key map or price context is unknown.", category="recompute_lifecycle"),
        _entry("NO_REFRESH_TRIGGER", "No refresh trigger was found in the current row context.", category="recompute_lifecycle"),
        _entry("REFRESH_FAILED_OR_STALE", "Refresh did not land cleanly or the refreshed result is already stale.", category="recompute_lifecycle"),
        _entry("RECLAIM_CONFIRMED", "Reclaim condition was confirmed against the current map.", category="recompute_lifecycle"),
        _entry("DOWNSIDE_TARGET_REACHED", "Downside target/support was reached on the mapped move.", category="recompute_lifecycle"),
    ]
}


def get_label_metadata(label: str) -> LabelDescription:
    normalized = str(label or "").strip().upper()
    if not normalized:
        return LabelDescription("", UNKNOWN_LABEL_DESCRIPTION)
    return _REGISTRY.get(normalized, LabelDescription(normalized, UNKNOWN_LABEL_DESCRIPTION))


def get_label_description(label: str) -> str:
    return get_label_metadata(label).description


def get_label_aria_label(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return UNKNOWN_LABEL_DESCRIPTION
    return f"{text}: {get_label_description(text)}"


def get_label_human_label(label: str) -> str:
    metadata = get_label_metadata(label)
    return metadata.human_label or str(label or "").strip()


def get_label_axis_value(label: str, axis_name: str) -> int | None:
    metadata = get_label_metadata(label)
    if metadata.axis_name != axis_name:
        return None
    return metadata.axis_value


def is_label_registered(label: str) -> bool:
    normalized = str(label or "").strip().upper()
    return bool(normalized) and normalized in _REGISTRY
