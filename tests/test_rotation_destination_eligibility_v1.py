from decimal import Decimal

from src.reporting.rotation_destination_eligibility_v1 import (
    destination_confidence,
    evaluate_rotation_destination_eligibility,
)


def base_advice(**overrides):
    row = {
        "selection_state": "WATCHLIST",
        "setup_filter_state": "PASS",
        "setup_filter_reason": "RANK_AND_MARKET_CONTEXT_OK",
        "advice_action": "WATCH_ONLY",
        "advice_state": "WATCH",
        "policy_decision": "WATCH",
        "leg_direction": "UP",
        "tp_zone_low": Decimal("120"),
        "tp_zone_high": Decimal("130"),
        "invalidation_price": Decimal("90"),
    }
    row.update(overrides)
    return row


def evaluate(row, **overrides):
    kwargs = {
        "current_price": Decimal("100"),
        "target_state": "TARGET_PENDING",
        "risk_state": "RISK_OK",
        "lifecycle_state": "ACTIVE_MAP",
        "recompute_needed": False,
        "recompute_reason": "",
        "policy_label": "",
        "action_label": "WATCH_ONLY",
        "entry_state": "ENTRY_ZONE_PENDING",
        "price_progress_state": "PRICE_PROGRESS_PENDING",
        "price_progress_labels": (),
        "next_zone_state": "CURRENT_MAP_ACTIVE",
        "next_reaction_zone_label": "",
        "next_target_zone_label": "",
        "next_target_zone": None,
    }
    kwargs.update(overrides)
    return evaluate_rotation_destination_eligibility(row, **kwargs)


def up_confirmed_curve_kwargs(**overrides):
    kwargs = {
        "target_state": "TARGET_PENDING",
        "risk_state": "RISK_OK",
        "lifecycle_state": "ACTIVE_MAP",
        "recompute_reason": "",
        "price_progress_state": "TARGET_APPROACHING",
        "price_progress_labels": ("POST_ENTRY_PROGRESS",),
        "next_zone_state": "CURRENT_MAP_ACTIVE",
        "next_reaction_zone_label": "RECLAIM_RETEST_SUPPORT",
        "next_target_zone_label": "NEXT_UPSIDE_REACTION_TARGET",
        "confirmation_state": "CONFIRMED",
    }
    kwargs.update(overrides)
    return kwargs


def test_down_setup_fail_candidate_is_excluded_with_compact_reasons():
    result = evaluate(
        base_advice(
            selection_state="NEUTRAL",
            setup_filter_state="FAIL",
            setup_filter_reason="SETUP_FILTER_FAIL_MARKET_DAMAGE_CAUTION",
            leg_direction="DOWN",
            tp_zone_low=Decimal("80"),
            tp_zone_high=Decimal("90"),
        ),
        current_price=Decimal("100"),
        policy_label="BLOCK_SETUP_FILTER_FAIL",
    )

    assert not result.eligible
    assert "EXCLUDED_SETUP_FAIL" in result.exclusion_reasons
    assert "EXCLUDED_DOWN_LEG_TARGET" in result.exclusion_reasons


def test_negative_long_target_distance_is_excluded():
    result = evaluate(
        base_advice(tp_zone_low=Decimal("80"), tp_zone_high=Decimal("90")),
        current_price=Decimal("100"),
    )

    assert not result.eligible
    assert "EXCLUDED_NEGATIVE_TARGET_DISTANCE" in result.exclusion_reasons


def test_clean_up_candidate_can_be_destination_eligible():
    result = evaluate(base_advice())

    assert result.eligible
    assert result.exclusion_reasons == []


def test_no_chase_and_recompute_pending_are_excluded():
    result = evaluate(
        base_advice(),
        policy_label="BLOCK_RECOMPUTE_PENDING",
        action_label="NO_CHASE_WITHOUT_NEW_ZONE",
        lifecycle_state="TARGET_REACHED_STALE",
        recompute_needed=True,
        recompute_reason="TARGET_REACHED_STALE",
    )

    assert not result.eligible
    assert "EXCLUDED_NO_CHASE" in result.exclusion_reasons
    assert "EXCLUDED_RECOMPUTE_PENDING" in result.exclusion_reasons


def test_destination_confidence_high_when_aplus_and_curve_context_are_clean():
    result = destination_confidence(
        base_advice(aplus_bucket="APLUS_BUY"),
        market_breath_row={
            "aplus_legacy_freshness_state": "FRESH",
            "aplus_legacy_block_strength": "NONE",
            "aplus_table1_strategic_bias": "buy",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.82"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(),
    )

    assert result.confidence_label == "HIGH_CONFIDENCE_DESTINATION"
    assert result.curve_sanity_label == "CURVE_UP_CONFIRMED"
    assert result.clean_actionable
    assert result.evidence_labels == []


def test_destination_confidence_missing_aplus_is_low_not_clean_actionable():
    result = destination_confidence(
        base_advice(aplus_bucket="APLUS_UNKNOWN"),
        market_breath_row={
            "aplus_legacy_freshness_state": "UNKNOWN",
            "aplus_legacy_block_strength": "UNKNOWN_LEGACY_CONTEXT",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.78"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(),
    )

    assert result.confidence_label == "LOW_CONFIDENCE_DESTINATION"
    assert result.curve_sanity_label == "CURVE_UP_CONFIRMED"
    assert not result.clean_actionable
    assert "MISSING_APLUS_CONTEXT" in result.evidence_labels


def test_destination_confidence_missing_market_breath_row_is_low_not_clean_actionable():
    result = destination_confidence(base_advice(aplus_bucket="APLUS_BUY"))

    assert result.confidence_label == "LOW_CONFIDENCE_DESTINATION"
    assert result.curve_sanity_label == "CURVE_NO_UP_SIGNAL"
    assert not result.clean_actionable
    assert "MISSING_APLUS_CONTEXT" in result.evidence_labels


def test_destination_confidence_stale_or_avoid_aplus_is_low_not_clean_actionable():
    stale = destination_confidence(
        base_advice(aplus_bucket="APLUS_BUY"),
        market_breath_row={
            "aplus_legacy_freshness_state": "VERY_STALE",
            "aplus_legacy_block_strength": "NONE",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.78"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(),
    )
    avoid = destination_confidence(
        base_advice(aplus_bucket="APLUS_AVOID"),
        market_breath_row={
            "aplus_legacy_freshness_state": "FRESH",
            "aplus_legacy_block_strength": "READ_ONLY_APLUS_AVOID",
            "aplus_table1_strategic_bias": "avoid",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.78"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(),
    )

    assert stale.confidence_label == "LOW_CONFIDENCE_DESTINATION"
    assert not stale.clean_actionable
    assert "STALE_APLUS_CONTEXT" in stale.evidence_labels
    assert avoid.confidence_label == "LOW_CONFIDENCE_DESTINATION"
    assert not avoid.clean_actionable
    assert "APLUS_AVOID_OR_DISTORTED" in avoid.evidence_labels


def test_destination_confidence_weak_curve_is_low_and_not_clean():
    result = destination_confidence(
        base_advice(aplus_bucket="APLUS_BUY"),
        market_breath_row={
            "aplus_legacy_freshness_state": "FRESH",
            "aplus_legacy_block_strength": "NONE",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.82"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(
            price_progress_state="PRICE_PROGRESS_PENDING",
            price_progress_labels=("ENTRY_ZONE_NEAR",),
            next_reaction_zone_label="",
            next_target_zone_label="",
            confirmation_state="CONFIRMATION_PENDING",
        ),
    )

    assert result.confidence_label == "LOW_CONFIDENCE_DESTINATION"
    assert result.curve_sanity_label == "CURVE_WEAK"
    assert not result.clean_actionable


def test_destination_confidence_failed_reclaim_is_market_only_not_clean():
    result = destination_confidence(
        base_advice(aplus_bucket="APLUS_BUY"),
        market_breath_row={
            "aplus_legacy_freshness_state": "FRESH",
            "aplus_legacy_block_strength": "NONE",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.82"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(
            price_progress_state="PRICE_PROGRESS_PENDING",
            price_progress_labels=("WAIT_FOR_RECLAIM",),
            next_zone_state="RECLAIM_NEXT_ZONE_PREVIEW",
            next_reaction_zone_label="RECLAIM_REVIEW",
            next_target_zone_label="",
            confirmation_state="CONFIRMATION_PENDING",
        ),
    )

    assert result.confidence_label == "MARKET_ONLY_DESTINATION"
    assert result.curve_sanity_label == "CURVE_FAILED_RECLAIM"
    assert not result.clean_actionable


def test_destination_confidence_down_pressure_is_market_only_not_clean():
    result = destination_confidence(
        base_advice(aplus_bucket="APLUS_BUY", leg_direction="DOWN"),
        market_breath_row={
            "aplus_legacy_freshness_state": "FRESH",
            "aplus_legacy_block_strength": "NONE",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.82"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(
            target_state="DOWNSIDE_TARGET_APPROACHING",
            risk_state="RISK_NEAR",
            next_zone_state="BREAKDOWN_NEXT_ZONE_PREVIEW",
            next_target_zone_label="NEXT_DOWNSIDE_EXTENSION",
            confirmation_state="CONFIRMATION_PENDING",
        ),
    )

    assert result.confidence_label == "MARKET_ONLY_DESTINATION"
    assert result.curve_sanity_label == "CURVE_DOWN_PRESSURE"
    assert not result.clean_actionable


def test_destination_confidence_up_confirmed_with_aging_aplus_is_medium_clean():
    result = destination_confidence(
        base_advice(aplus_bucket="APLUS_BUY"),
        market_breath_row={
            "aplus_legacy_freshness_state": "AGING",
            "aplus_legacy_block_strength": "NONE",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.82"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(),
    )

    assert result.confidence_label == "MEDIUM_CONFIDENCE_DESTINATION"
    assert result.curve_sanity_label == "CURVE_UP_CONFIRMED"
    assert result.clean_actionable


def test_destination_confidence_non_aplus_label_is_market_only_not_clean():
    result = destination_confidence(
        base_advice(aplus_bucket="CANONICAL_CORE"),
        market_breath_row={
            "aplus_legacy_freshness_state": "FRESH",
            "aplus_legacy_block_strength": "NONE",
            "market_breath_context_state": "MARKET_BREATH_EXPANSION_CONTEXT",
            "market_breath_confidence": Decimal("0.82"),
            "relative_strength_score": Decimal("0.4"),
            "momentum_score": Decimal("0.5"),
        },
        **up_confirmed_curve_kwargs(),
    )

    assert result.confidence_label == "MARKET_ONLY_DESTINATION"
    assert result.curve_sanity_label == "CURVE_UP_CONFIRMED"
    assert not result.clean_actionable
    assert "MARKET_ONLY_DESTINATION" in result.evidence_labels
