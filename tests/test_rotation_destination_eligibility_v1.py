from decimal import Decimal

from src.reporting.rotation_destination_eligibility_v1 import (
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
