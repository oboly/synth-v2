"""Acceptance tests for Profit Plan action-truth v2.

Covers:
- PR1 PPP v2 (Planning vs Actionable) — AERO-like waiting-for-reclaim case.
- PR2 HOT-like unverified map-rollover review gate.
- PR3 Fail-closed FIX_LADDER (LDO / NEAR / RED cases).
- PR4 Breathline demotion (action state invariant to breathline data).

Read-only reporting semantics only: no broker, decision_gate, execution_planner
or executor is touched.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import src.reporting.manual_short_trader_profit_plan_v1 as pp
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_MODE_POSITION_HELD,
    CardEvidence,
    FibExtContext,
    ReentryContext,
    TargetHistoryCandle,
    build_profit_plan_card,
    render_plan_card,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _below_gate_fib() -> FibExtContext:
    return FibExtContext(
        local_reaction_price=Decimal("0.2500"),
        anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
        ext_1_272=Decimal("0.4500"),
        ext_1_618=Decimal("0.5200"),
        ext_2_000=Decimal("0.8000"),
        breakout_gate=Decimal("0.3000"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )


def _reentry_above_current() -> ReentryContext:
    return ReentryContext(
        r382_price=Decimal("0.2100"),
        r500_price=Decimal("0.2000"),
        r618_price=Decimal("0.1800"),
        r786_price=Decimal("0.1400"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )


def _active_map_evidence(**overrides: str) -> CardEvidence:
    base = dict(
        map_cycle_id="AERO|SHORT|4h|demo",
        native_map_id="AERO-map-01",
        native_map_status="AVAILABLE",
        selected_map_reason="Single active map selected",
        selected_map_tier="CURRENT_ACTIVE_MAP",
        lifecycle_state="TARGET_ACTIVE",
        rollover_state="SINGLE_MAP",
        account_order_snapshot_status="FRESH",
        price_freshness_state="FRESH",
        anchor_start_ts_utc="2026-06-01T00:00:00Z",
        order_snapshot_ts_utc="2026-06-05T12:00:00Z",
        generation_ts_utc="2026-06-05T12:00:00Z",
    )
    base.update(overrides)
    return CardEvidence(**base)


_COMPLETED_MAP_CANDLES = (
    TargetHistoryCandle(
        close_ts_utc=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
        high_price=Decimal("0.4700"),
        low_price=Decimal("0.4300"),
    ),
    TargetHistoryCandle(
        close_ts_utc=datetime(2026, 6, 4, 16, 0, tzinfo=UTC),
        high_price=Decimal("0.7600"),
        low_price=Decimal("0.5000"),
    ),
)


# ---------------------------------------------------------------------------
# PR1 — AERO-like: planning PPP present, actionable PPP unavailable
# ---------------------------------------------------------------------------

def _aero_card() -> pp.ProfitPlanCard:
    return build_profit_plan_card(
        symbol="AERO",
        market="AERO-EUR",
        current_price=Decimal("0.1600"),
        fib_ext=_below_gate_fib(),
        reentry=_reentry_above_current(),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(),
    )


def test_aero_planning_ppp_present_but_actionable_ppp_unavailable() -> None:
    card = _aero_card()
    assert card.actionability_state == pp.CARD_ACTIONABILITY_ACTIVE
    assert pp._planning_ppp(card) is not None
    assert pp._actionable_ppp(card) is None


def test_aero_actionable_display_says_wait_for_reclaim() -> None:
    card = _aero_card()
    text = pp._format_actionable_ppp(card)
    assert "Entry above current — wait for reclaim" in text


def test_aero_does_not_rank_above_actionable_setups() -> None:
    aero = _aero_card()
    # A genuinely activated setup (first target passed via history) with valid actionable PPP.
    actionable = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.4600"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.3990"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.4544"),
            ext_1_618=Decimal("0.5156"),
            ext_2_000=Decimal("0.8000"),
            breakout_gate=Decimal("0.3800"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        history_high_since_activation=Decimal("0.4700"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(map_cycle_id="WLD|SHORT|4h|demo"),
    )
    assert pp._actionable_ppp(actionable) is not None
    assert pp._workflow_sort_bucket(actionable) == 0
    assert pp._workflow_sort_bucket(aero) == 1
    assert pp._workflow_sort_bucket(actionable) < pp._workflow_sort_bucket(aero)


def test_aero_does_not_show_buy_ready_or_fix_ladder() -> None:
    card = _aero_card()
    action = pp._effective_workflow_action(card)
    assert action != "FIX LADDER"
    html = render_plan_card(card)
    assert "BUY_READY" not in html
    assert "BUY READY" not in html
    assert "FIX LADDER" not in html
    assert "Entry above current — wait for reclaim" in html


# ---------------------------------------------------------------------------
# PR2 — HOT-like: transient rollover text is non-canonical reference only
# ---------------------------------------------------------------------------

def _hot_card() -> pp.ProfitPlanCard:
    return build_profit_plan_card(
        symbol="HOT",
        market="HOT-EUR",
        current_price=Decimal("0.4600"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.3990"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.4544"),
            ext_1_618=Decimal("0.5156"),
            ext_2_000=Decimal("0.8000"),
            breakout_gate=Decimal("0.3800"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        reentry=None,
        history_high_since_activation=Decimal("0.4700"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=CardEvidence(
            map_cycle_id="HOT|SHORT|4h|new",
            native_map_id="DATA_UNAVAILABLE",
            native_map_status="DATA_UNAVAILABLE",
            selected_map_reason="Newer active map selected; older completed map is historical reference",
            selected_map_tier="CURRENT_ACTIVE_MAP",
            lifecycle_state="TARGET_REACHED_OR_PASSED",
            rollover_state="CASE_A_NEWER_ACTIVE_SELECTED",
            previous_map_cycle_id="DATA_UNAVAILABLE",
            previous_map_lifecycle_state="DATA_UNAVAILABLE",
            account_order_snapshot_status="DATA_UNAVAILABLE",
        ),
    )


def test_hot_unavailable_native_truth_does_not_claim_map_switch_review() -> None:
    card = _hot_card()
    assert pp._selected_map_indicates_rollover(card) is True  # preserved raw bridge reference
    assert pp._rollover_verified(card) is False
    assert pp._map_switch_review_required(card) is False
    assert card.scenario_type == "CONTEXT_UNAVAILABLE"
    assert card.event_state == "CONTEXT_UNAVAILABLE"
    assert card.actionability_state == pp.CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE
    assert pp._effective_workflow_action(card) == "REVIEW CONTEXT"


def test_hot_renders_review_language_and_no_fix_ladder() -> None:
    card = _hot_card()
    html = render_plan_card(card)
    assert "MAP SWITCH REVIEW" not in html
    assert "REVIEW CONTEXT" in html
    assert "Transient SHORT context (non-canonical reference)" in html
    assert "FIX LADDER" not in html
    # No account/order repair action must be enabled.
    assert "Fix selected" not in html or "disabled" in html


def test_hot_actionable_ppp_unavailable_for_unverified_rollover() -> None:
    card = _hot_card()
    assert pp._actionable_ppp(card) is None
    assert pp._fix_ladder_allowed(card) is False


def test_verified_rollover_does_not_trigger_review() -> None:
    card = replace(
        _hot_card(),
        evidence=CardEvidence(
            map_cycle_id="HOT|SHORT|4h|new",
            native_map_id="HOT-map-02",
            native_map_status="AVAILABLE",
            selected_map_reason="Newer active map selected; older completed map is historical reference",
            selected_map_tier="CURRENT_ACTIVE_MAP",
            lifecycle_state="TARGET_ACTIVE",
            rollover_state="CASE_A_NEWER_ACTIVE_SELECTED",
            previous_map_cycle_id="HOT|SHORT|4h|old",
            previous_map_lifecycle_state="MAP_COMPLETED",
            account_order_snapshot_status="FRESH",
        ),
    )
    assert pp._rollover_verified(card) is True
    assert pp._map_switch_review_required(card) is False


# ---------------------------------------------------------------------------
# PR3 — Fail-closed FIX_LADDER
# ---------------------------------------------------------------------------

def _active_ladder_missing_card(evidence: CardEvidence) -> pp.ProfitPlanCard:
    base = build_profit_plan_card(
        symbol="LDO",
        market="LDO-EUR",
        current_price=Decimal("0.4600"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.3990"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.4544"),
            ext_1_618=Decimal("0.5156"),
            ext_2_000=Decimal("0.8000"),
            breakout_gate=Decimal("0.3800"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        history_high_since_activation=Decimal("0.4700"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=evidence,
    )
    return replace(
        base,
        actionability_state=pp.CARD_ACTIONABILITY_ACTIVE,
        ladder_states=("LADDER_MISSING",),
        buy_zone=(Decimal("0.4000"),),
        reload_reentry_zone=(Decimal("0.4000"),),
    )


def test_ldo_unavailable_truth_renders_review_context_not_fix_ladder() -> None:
    card = _active_ladder_missing_card(
        CardEvidence(
            map_cycle_id="LDO|SHORT|4h|demo",
            native_map_id="DATA_UNAVAILABLE",
            native_map_status="DATA_UNAVAILABLE",
            selected_map_tier="CURRENT_ACTIVE_MAP",
            rollover_state="SINGLE_MAP",
            account_order_snapshot_status="DATA_UNAVAILABLE",
        )
    )
    assert pp._fix_ladder_allowed(card) is False
    assert pp._effective_workflow_action(card) == "REVIEW CONTEXT"
    html = render_plan_card(card)
    assert "FIX LADDER" not in html


def test_ldo_fresh_full_truth_allows_fix_ladder() -> None:
    card = _active_ladder_missing_card(_active_map_evidence(map_cycle_id="LDO|SHORT|4h|demo"))
    assert pp._fix_ladder_allowed(card) is True
    assert pp._effective_workflow_action(card) == "FIX LADDER"


def test_ldo_placeholder_account_snapshot_suppresses_fix_ladder() -> None:
    card = _active_ladder_missing_card(
        _active_map_evidence(
            map_cycle_id="LDO|SHORT|4h|demo",
            account_order_snapshot_status="DATA_UNAVAILABLE",
        )
    )
    assert pp._fix_ladder_allowed(card) is False
    assert pp._effective_workflow_action(card) == "REVIEW CONTEXT"


def test_ldo_raw_current_price_above_target_is_not_activation_proof() -> None:
    card = replace(
        _active_ladder_missing_card(_active_map_evidence(map_cycle_id="LDO|SHORT|4h|demo")),
        history_high_since_activation=None,
    )

    assert card.current_price > card.target_level_statuses[0].level
    assert pp._entry_activation_proof(card) is False
    assert pp._fix_ladder_allowed(card) is False


def test_ldo_previous_cycle_crossing_is_not_activation_proof() -> None:
    base = _active_ladder_missing_card(_active_map_evidence(map_cycle_id="LDO|SHORT|4h|demo"))
    card = replace(
        base,
        history_high_since_activation=None,
        target_level_statuses=tuple(
            replace(level, first_cross_ts_utc=datetime(2026, 5, 31, 23, 59, tzinfo=UTC))
            for level in base.target_level_statuses
        ),
    )

    assert pp._entry_activation_proof(card) is False
    assert pp._fix_ladder_allowed(card) is False


def test_ldo_native_map_unavailable_suppresses_fix_ladder() -> None:
    card = _active_ladder_missing_card(
        _active_map_evidence(
            map_cycle_id="LDO|SHORT|4h|demo",
            native_map_id="DATA_UNAVAILABLE",
            native_map_status="DATA_UNAVAILABLE",
        )
    )

    assert pp._fix_ladder_allowed(card) is False


def test_ldo_unverified_rollover_suppresses_fix_ladder() -> None:
    card = _active_ladder_missing_card(
        _active_map_evidence(
            map_cycle_id="LDO|SHORT|4h|new",
            selected_map_reason="Newer active map selected",
            rollover_state="CASE_A_NEWER_ACTIVE_SELECTED",
            previous_map_cycle_id="DATA_UNAVAILABLE",
            previous_map_lifecycle_state="DATA_UNAVAILABLE",
        )
    )

    assert pp._map_switch_review_required(card) is True
    assert pp._fix_ladder_allowed(card) is False


def test_near_map_expired_stays_needs_recompute_not_fix_ladder() -> None:
    card = build_profit_plan_card(
        symbol="NEAR",
        market="NEAR-EUR",
        current_price=Decimal("0.7600"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.3990"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.4544"),
            ext_1_618=Decimal("0.5156"),
            ext_2_000=Decimal("0.6200"),
            breakout_gate=Decimal("0.3800"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(map_cycle_id="NEAR|SHORT|4h|demo"),
    )
    assert card.all_sell_targets_completed is True
    assert card.actionability_state == pp.CARD_ACTIONABILITY_NEEDS_RECOMPUTE
    action = pp._effective_workflow_action(card)
    assert action == "MAP EXPIRED"
    assert pp._fix_ladder_allowed(card) is False
    html = render_plan_card(card)
    assert "FIX LADDER" not in html


def test_red_extension_target_without_entry_is_wait_for_entry() -> None:
    # Extension card: sell target present, no re-entry levels loaded.
    base = build_profit_plan_card(
        symbol="RED",
        market="RED-EUR",
        current_price=Decimal("0.4600"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.3990"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.4544"),
            ext_1_618=Decimal("0.5156"),
            ext_2_000=Decimal("0.8000"),
            breakout_gate=Decimal("0.3800"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(map_cycle_id="RED|SHORT|4h|demo"),
    )
    card = replace(
        base,
        actionability_state=pp.CARD_ACTIONABILITY_ACTIVE,
        ladder_states=("LADDER_MISSING",),
        buy_zone=(),
        reload_reentry_zone=(),
        target_exit_zone=(Decimal("0.5156"),),
    )
    assert pp._card_has_loaded_entry(card) is False
    assert pp._fix_ladder_allowed(card) is False
    assert pp._effective_workflow_action(card) == "WAIT FOR ENTRY"
    html = render_plan_card(card)
    assert "FIX LADDER" not in html


def test_uncovered_target_alone_is_not_a_broken_ladder() -> None:
    # Same as RED: an uncovered target with no loaded entry must not claim FIX LADDER.
    base = build_profit_plan_card(
        symbol="RED",
        market="RED-EUR",
        current_price=Decimal("0.4600"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.3990"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.4544"),
            ext_1_618=Decimal("0.5156"),
            ext_2_000=Decimal("0.8000"),
            breakout_gate=Decimal("0.3800"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(map_cycle_id="RED|SHORT|4h|demo"),
    )
    card = replace(
        base,
        actionability_state=pp.CARD_ACTIONABILITY_ACTIVE,
        ladder_states=("LADDER_MISSING",),
        buy_zone=(),
        reload_reentry_zone=(),
    )
    assert pp._effective_workflow_action(card) != "FIX LADDER"


# ---------------------------------------------------------------------------
# PR4 — Breathline demotion: action state invariant to breathline data
# ---------------------------------------------------------------------------

def _breath_payload() -> dict:
    return {
        "availability_state": "AVAILABLE",
        "phase_marker": "MID_EXPANSION",
        "phase_offset_band": "ON_TIME",
        "template_match_score": 0.87,
        "current_checkpoint": "EXPANSION",
        "next_checkpoint": "PEAK",
        "next_target_expected_ts_utc": "2026-06-10T00:00:00Z",
        "freshness_label": "FRESH",
        "source_candle_ts_utc": "2026-06-05T12:00:00Z",
    }


def _card_with_breath(breath: dict | None) -> pp.ProfitPlanCard:
    return build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.4600"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.3990"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.4544"),
            ext_1_618=Decimal("0.5156"),
            ext_2_000=Decimal("0.8000"),
            breakout_gate=Decimal("0.3800"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        history_high_since_activation=Decimal("0.4700"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        breath_curve=breath,
        evidence=_active_map_evidence(map_cycle_id="WLD|SHORT|4h|demo"),
    )


def test_breathline_data_does_not_change_any_action_state() -> None:
    with_breath = _card_with_breath(_breath_payload())
    without_breath = _card_with_breath(None)

    def signature(card: pp.ProfitPlanCard) -> tuple:
        return (
            pp._effective_workflow_action(card),
            pp._actionable_ppp(card),
            pp._planning_ppp(card),
            pp._workflow_sort_bucket(card),
            card.ladder_states,
            card.setup_state,
            card.primary_state,
            card.actionability_state,
            pp._fix_ladder_allowed(card),
            pp._map_switch_review_required(card),
        )

    assert signature(with_breath) == signature(without_breath)


def test_breathline_is_hidden_from_normal_operator_card() -> None:
    """Breathline is research-only/disabled (weights 0). Issue #347 requires it
    hidden from the normal operator card entirely, without deleting the
    underlying data-bc-* attribute contract other consumers may still read."""
    html = render_plan_card(_card_with_breath(_breath_payload()))
    assert "Breathline context" not in html
    assert "breath-curve-disabled" not in html
    assert "data-bc-availability=" in html
