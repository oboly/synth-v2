"""
SYNTH v2
Module: synth_sleeves.selection_semantics
Purpose:
    Canonical mapping from raw selection-state semantics to sleeve-engine semantics.
"""

from __future__ import annotations

from decimal import Decimal


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def derive_canonical_selection_state(
    *,
    raw_selection_state: object,
    raw_selection_bias: object,
    selection_score: Decimal,
) -> str:
    state = normalize_text(raw_selection_state)
    bias = normalize_text(raw_selection_bias)

    # Pass-through for already canonical states.
    if state in {
        "WATCH",
        "PRE_ALIGNMENT",
        "EARLY_WATCH",
        "LONG_READY",
        "CONFIRMED_LONG",
        "ENTER_LONG",
        "TACTICAL",
        "SCALP_ONLY",
    }:
        return state

    # Strong structural candidate.
    if state == "STRONG_CANDIDATE" and bias == "LONG_BIAS":
        if selection_score >= Decimal("0.55"):
            return "LONG_READY"
        return "PRE_ALIGNMENT"

    # Trigger exists, but HTF confirmation is not fully there yet.
    if state == "TRIGGER_NO_HTF_CONFIRM":
        if selection_score >= Decimal("0.50"):
            return "PRE_ALIGNMENT"
        return "WATCH"

    # Mixed state: not dead, but not enough to act aggressively.
    if state == "MIXED_NEUTRAL":
        if bias == "LONG_BIAS" and selection_score >= Decimal("0.60"):
            return "EARLY_WATCH"
        return "WATCH"

    # Tactical-like states.
    if state in {"TACTICAL", "TACTICAL_LONG", "SCALP_ONLY"}:
        return "TACTICAL"

    if bias in {"TACTICAL", "SCALP_ONLY"}:
        return "TACTICAL"

    # Soft structural fallback.
    if bias == "LONG_BIAS":
        if selection_score >= Decimal("0.65"):
            return "PRE_ALIGNMENT"
        if selection_score >= Decimal("0.50"):
            return "EARLY_WATCH"
        return "WATCH"

    return "WATCH"
