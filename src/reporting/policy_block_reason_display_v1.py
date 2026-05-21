from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


BLOCK_STATES = {
    "BLOCK_24H",
    "BLOCK_FOR_24H",
    "BLOCKED_NO_NEW_BUY",
    "NO_NEW_BUY",
    "DO_NOT_ADD",
    "AVOID_NO_NEW_BUY",
}


@dataclass(frozen=True)
class PolicyBlockDisplay:
    raw_policy_state: str
    block_primary_reason: str
    block_reason_codes: list[str]
    block_ttl_label: str
    unblock_condition_label: str
    display_policy_label: str
    display_policy_severity: str


def _value(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()


def _reason_codes(row: Any) -> list[str]:
    raw = _value(row, "reason_codes")
    if isinstance(raw, list):
        return [_norm(item) for item in raw if _norm(item)]

    raw = _value(row, "reason_codes_json")
    if raw:
        try:
            parsed = json.loads(str(raw))
        except json.JSONDecodeError:
            parsed = raw
        if isinstance(parsed, list):
            return [_norm(item) for item in parsed if _norm(item)]
        if isinstance(parsed, dict):
            return [f"{_norm(key)}={_norm(value)}" for key, value in parsed.items()]
        return [_norm(parsed)] if _norm(parsed) else []

    raw = _value(row, "candidate_reason_codes")
    if isinstance(raw, list):
        return [_norm(item) for item in raw if _norm(item)]
    return []


def _text_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(_norm(item) for item in value if _norm(item))
        else:
            parts.append(_norm(value))
    return " ".join(part for part in parts if part)


def _raw_policy_state(row: Any, candidate_group: str | None = None) -> str:
    for name in ("advice_state", "policy_decision", "advice_action"):
        value = _norm(_value(row, name))
        if value in BLOCK_STATES:
            return value
    candidate = _norm(candidate_group or _value(row, "candidate_group"))
    return candidate if candidate in BLOCK_STATES else ""


def classify_policy_block_display(
    row: Any,
    *,
    candidate_group: str | None = None,
    lifecycle_state: str | None = None,
    recompute_needed: bool = False,
    recompute_reason: str | None = None,
    target_state: str | None = None,
    entry_state: str | None = None,
    price_progress_state: str | None = None,
    market_breath_row: dict[str, Any] | None = None,
    extra_reason_codes: list[str] | None = None,
) -> PolicyBlockDisplay | None:
    raw_policy = _raw_policy_state(row, candidate_group)
    advice_action = _norm(_value(row, "advice_action"))
    if not raw_policy and advice_action not in BLOCK_STATES:
        return None

    reasons = list(dict.fromkeys(_reason_codes(row) + [_norm(code) for code in (extra_reason_codes or []) if _norm(code)]))
    setup_state = _norm(_value(row, "setup_filter_state"))
    setup_reason = _norm(_value(row, "setup_filter_reason"))
    selection_state = _norm(_value(row, "selection_state"))
    aplus_bucket = _norm(_value(row, "aplus_bucket"))
    aplus_freshness = _norm(None if market_breath_row is None else market_breath_row.get("aplus_legacy_freshness_state"))
    lifecycle = _norm(lifecycle_state or _value(row, "lifecycle_state"))
    target = _norm(target_state or _value(row, "target_state"))
    entry = _norm(entry_state or _value(row, "entry_state"))
    price_progress = _norm(price_progress_state or _value(row, "price_progress_state"))
    text = _text_blob(
        raw_policy,
        advice_action,
        setup_state,
        setup_reason,
        selection_state,
        aplus_bucket,
        aplus_freshness,
        lifecycle,
        target,
        entry,
        price_progress,
        recompute_reason or _value(row, "recompute_reason"),
        candidate_group or _value(row, "candidate_group"),
        reasons,
    )

    primary = "POLICY_BLOCK_UNCLASSIFIED"
    label = "BLOCK_POLICY_UNCLASSIFIED"
    unblock = "review policy context on next refresh"
    severity = "warn"

    if "MARKET_DAMAGE_RISK" in text:
        primary = "MARKET_DAMAGE_RISK"
        label = "BLOCK_MARKET_DAMAGE"
        unblock = "until market damage clears on a market refresh"
        severity = "critical"
    elif "MARKET_DAMAGE_CAUTION" in text:
        primary = "MARKET_DAMAGE_CAUTION"
        label = "BLOCK_MARKET_DAMAGE"
        unblock = "until market damage clears on a market refresh"
        severity = "warn"
    elif any(token in text for token in {"INVALIDATION_TOUCHED", "RECOMPUTED_BUT_STILL_TRIGGERING"}):
        primary = "RECOMPUTED_STILL_TRIGGERING"
        label = "BLOCK_RECOMPUTE_PENDING"
        unblock = "after fresh zone/advice recompute clears the trigger"
        severity = "critical"
    elif any(
        token in text
        for token in {
            "MAP_RECOMPUTE_NEEDED",
            "TARGET_REACHED_STALE",
            "RECLAIM_CONFIRMED",
            "REFRESH_NEEDED",
        }
    ) or recompute_needed:
        primary = "RECOMPUTE_PENDING"
        label = "BLOCK_RECOMPUTE_PENDING"
        unblock = "after fresh zone/advice recompute or cooldown clears"
        severity = "warn"
    elif any(
        token in text
        for token in {
            "ENTRY_WINDOW_PASSED",
            "POST_ENTRY_PROGRESS",
            "TARGET_REACHED",
            "TARGET_OVERSHOT",
            "NO_CHASE_WITHOUT_NEW_ZONE",
        }
    ):
        primary = "ENTRY_WINDOW_PASSED" if "ENTRY_WINDOW_PASSED" in text else "CHASE_RISK"
        label = "BLOCK_CHASE_RISK"
        unblock = "wait for retest, new entry zone, or new map"
        severity = "warn"
    elif "INSUFFICIENT_SAMPLE" in text or "MISSING_REQUIRED_ZONE_DATA" in text:
        primary = "INSUFFICIENT_SAMPLE"
        label = "BLOCK_INSUFFICIENT_SAMPLE"
        unblock = "wait for more candles/data"
        severity = "muted"
    elif setup_state and setup_state != "PASS":
        primary = "SETUP_FILTER_FAIL"
        label = "BLOCK_SETUP_FILTER_FAIL"
        unblock = "when setup_filter passes on next refresh"
        severity = "warn"
    elif selection_state and selection_state not in {"WATCHLIST", "WATCH_CORE", "STRONG_WATCHLIST", "ELIGIBLE", "PASS"}:
        primary = "SELECTION_NOT_ELIGIBLE"
        label = "BLOCK_SELECTION_NOT_ELIGIBLE"
        unblock = "when selection engine ranks or qualifies the asset again"
        severity = "muted"
    elif aplus_bucket == "APLUS_AVOID" and aplus_freshness in {"STALE", "VERY_STALE"}:
        primary = "STALE_APLUS_CONTEXT"
        label = "LEGACY_CONTEXT_ONLY"
        unblock = "A+ is stale legacy context; use current market context"
        severity = "muted"
    elif aplus_bucket == "APLUS_AVOID":
        primary = "READ_ONLY_APLUS_AVOID_CONTEXT"
        label = "READ_ONLY_APLUS_AVOID_CONTEXT"
        unblock = "legacy A+ context only; not live permission"
        severity = "muted"

    return PolicyBlockDisplay(
        raw_policy_state=raw_policy or advice_action,
        block_primary_reason=primary,
        block_reason_codes=reasons,
        block_ttl_label="reason-driven",
        unblock_condition_label=unblock,
        display_policy_label=label,
        display_policy_severity=severity,
    )


def block_reason_summary_text(block: PolicyBlockDisplay | None) -> str:
    if block is None:
        return ""
    return (
        f"Raw policy: {block.raw_policy_state}; "
        f"Cause: {block.block_primary_reason}; "
        f"Unblock: {block.unblock_condition_label}"
    )
