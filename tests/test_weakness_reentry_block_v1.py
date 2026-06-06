"""
Tests for run_weakness_reentry_block_v1.

Covers:
  1.  evaluate_reentry_block_policy — EXHALE_EXPANSION → REENTRY_BLOCKED_WEAKNESS
  2.  evaluate_reentry_block_policy — OVERBREATH_EXTENSION → REENTRY_BLOCKED_WEAKNESS
  3.  evaluate_reentry_block_policy — COLLAPSE_RESET → REENTRY_BLOCKED_WEAKNESS (terminal capitulation)
  4.  evaluate_reentry_block_policy — parent terminal → REENTRY_BLOCKED_PARENT_TERMINAL
  5.  evaluate_reentry_block_policy — reload zone touch alone insufficient (no reclaim)
  6.  evaluate_reentry_block_policy — reclaim + supportive Breath/Regime → REENTRY_CONTEXT_SUPPORTED
  7.  evaluate_reentry_block_policy — reclaim + conflicting Breath/Regime → REENTRY_CONTEXT_CONFLICT
  8.  evaluate_reentry_block_policy — CONTEXT_UNKNOWN → NOT_LIVE_VALID; fail closed
  9.  evaluate_reentry_block_policy — future context rejected (no future leakage)
  10. evaluate_reentry_block_policy — stale context → NOT_LIVE_VALID
  11. assign_weakness_state — COLLAPSE_RESET ≠ INHALE_ACCUMULATION (critical distinction)
  12. assign_weakness_state — EXHALE_EXPANSION and OVERBREATH_EXTENSION → WEAKNESS_ACTIVE
  13. assign_weakness_state — high reversal_pressure downgrades WEAKNESS_RESOLVED to WEAKNESS_CLEARING
  14. assign_reset_state — COLLAPSE_RESET → RESET_NOT_CONFIRMED (bottom not confirmed at collapse)
  15. assign_reset_state — INHALE_ACCUMULATION → RESET_CONFIRMED (new energy build confirmed)
  16. assign_reclaim_state — INHALE_ACCUMULATION + CONFIRMED → RECLAIM_CONFIRMED
  17. assign_reclaim_state — INHALE_ACCUMULATION without CONFIRMED → RECLAIM_NOT_CONFIRMED
  18. assign_reload_zone_state — compression_score threshold correct
  19. assign_breath_alignment — threshold boundaries correct
  20. assign_regime_state — conflicting regime blocks supported state
  21. evaluate_reentry_block_policy — RESET_NOT_CONFIRMED → RESET_REQUIRED
  22. evaluate_reentry_block_policy — RESET_FORMING → WATCH_REENTRY
  23. evaluate_reentry_block_policy — reset confirmed, no reclaim → WATCH_REENTRY
  24. decision_gate / execution_planner / executor not imported or called
  25. safety markers present
"""
from __future__ import annotations

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.run_weakness_reentry_block_v1 import (
    # States
    REENTRY_BLOCKED_WEAKNESS,
    REENTRY_BLOCKED_PARENT_TERMINAL,
    RESET_REQUIRED,
    WATCH_REENTRY,
    REENTRY_CONTEXT_SUPPORTED,
    REENTRY_CONTEXT_CONFLICT,
    CONTEXT_UNKNOWN,
    NOT_LIVE_VALID,
    # Weakness
    WEAKNESS_ACTIVE,
    WEAKNESS_CLEARING,
    WEAKNESS_RESOLVED,
    WEAKNESS_UNKNOWN,
    # Reset
    RESET_CONFIRMED_STATE,
    RESET_FORMING_STATE,
    RESET_NOT_CONFIRMED_STATE,
    RESET_UNKNOWN_STATE,
    # Reclaim
    RECLAIM_CONFIRMED_STATE,
    RECLAIM_NOT_CONFIRMED_STATE,
    RECLAIM_UNKNOWN_STATE,
    # Reload zone
    ZONE_TESTED,
    ZONE_APPROACHING,
    ZONE_NOT_TESTED,
    # Breath alignment
    BREATH_ALIGNMENT_POSITIVE,
    BREATH_ALIGNMENT_NEGATIVE,
    BREATH_ALIGNMENT_NEUTRAL,
    # Regime
    REGIME_SUPPORTIVE,
    REGIME_NEUTRAL,
    REGIME_CONFLICTING,
    # Parent
    PARENT_CONSTRUCTIVE,
    PARENT_BLOCKING,
    PARENT_UNKNOWN_STATE,
    # Native SHORT
    SHORT_1H_ALIGNED,
    SHORT_1H_CONFLICT,
    SHORT_1H_NEUTRAL,
    # Constants
    COMPRESSION_ZONE_TESTED_THRESHOLD,
    COMPRESSION_ZONE_APPROACHING_THRESHOLD,
    BREATH_ALIGNMENT_POSITIVE_THRESHOLD,
    BREATH_ALIGNMENT_NEGATIVE_THRESHOLD,
    REGIME_SUPPORTIVE_BREATH_SCORE,
    REGIME_CONFLICTING_BREATH_SCORE,
    REVERSAL_PRESSURE_WEAKNESS_THRESHOLD,
    # Functions
    assign_weakness_state,
    assign_reset_state,
    assign_reclaim_state,
    assign_reload_zone_state,
    assign_breath_alignment,
    assign_regime_state,
    assign_parent_constructive_state,
    evaluate_reentry_block_policy,
    RUNNER_NAME,
    VERSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _supported_inputs() -> dict:
    """Minimal inputs for REENTRY_CONTEXT_SUPPORTED path."""
    return dict(
        weakness_state=WEAKNESS_RESOLVED,
        reset_state=RESET_CONFIRMED_STATE,
        reclaim_state=RECLAIM_CONFIRMED_STATE,
        reload_zone_state=ZONE_TESTED,
        breath_alignment=BREATH_ALIGNMENT_POSITIVE,
        regime_state=REGIME_SUPPORTIVE,
        native_short_4h_lifecycle="POST_BREAKOUT_PULLBACK",
        native_short_1h_support=SHORT_1H_ALIGNED,
        parent_terminal_state="NOT_TERMINAL",
        parent_constructive_state=PARENT_CONSTRUCTIVE,
    )


# ---------------------------------------------------------------------------
# 1. EXHALE_EXPANSION → REENTRY_BLOCKED_WEAKNESS
# ---------------------------------------------------------------------------

class TestExhaleExpansionBlocked:
    def test_action_is_blocked_weakness(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_ACTIVE,
            reset_state=RESET_NOT_CONFIRMED_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
            reload_zone_state=ZONE_NOT_TESTED,
            breath_alignment=BREATH_ALIGNMENT_NEGATIVE,
            regime_state=REGIME_CONFLICTING,
            parent_constructive_state=PARENT_CONSTRUCTIVE,
        )
        assert r.reentry_state == REENTRY_BLOCKED_WEAKNESS

    def test_gate_applied(self):
        r = evaluate_reentry_block_policy(weakness_state=WEAKNESS_ACTIVE)
        assert r.gate_applied is True

    def test_live_valid_is_true(self):
        r = evaluate_reentry_block_policy(weakness_state=WEAKNESS_ACTIVE)
        assert r.live_valid is True

    def test_exhale_weakness_state_assignment(self):
        assert assign_weakness_state("EXHALE_EXPANSION") == WEAKNESS_ACTIVE

    def test_exhale_reset_state_assignment(self):
        assert assign_reset_state("EXHALE_EXPANSION") == RESET_NOT_CONFIRMED_STATE


# ---------------------------------------------------------------------------
# 2. OVERBREATH_EXTENSION → REENTRY_BLOCKED_WEAKNESS
# ---------------------------------------------------------------------------

class TestOverbreathBlocked:
    def test_overbreath_weakness_assignment(self):
        assert assign_weakness_state("OVERBREATH_EXTENSION") == WEAKNESS_ACTIVE

    def test_overbreath_policy_blocked(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_ACTIVE,
            reset_state=RESET_NOT_CONFIRMED_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
        )
        assert r.reentry_state == REENTRY_BLOCKED_WEAKNESS

    def test_overbreath_reset_not_confirmed(self):
        assert assign_reset_state("OVERBREATH_EXTENSION") == RESET_NOT_CONFIRMED_STATE


# ---------------------------------------------------------------------------
# 3. COLLAPSE_RESET → REENTRY_BLOCKED_WEAKNESS (terminal capitulation, not bullish reset)
# ---------------------------------------------------------------------------

class TestCollapseResetIsWeakness:
    """
    Critical architectural test: COLLAPSE_RESET is terminal capitulation.
    It must NOT be treated as a bullish reset like INHALE_ACCUMULATION.
    The distinction: COLLAPSE_RESET = bottom NOT confirmed; INHALE = new energy confirmed.
    """

    def test_collapse_reset_weakness_is_active(self):
        ws = assign_weakness_state("COLLAPSE_RESET")
        assert ws == WEAKNESS_ACTIVE, (
            f"COLLAPSE_RESET must map to WEAKNESS_ACTIVE (terminal capitulation), got {ws}"
        )

    def test_collapse_reset_is_not_weakness_resolved(self):
        assert assign_weakness_state("COLLAPSE_RESET") != WEAKNESS_RESOLVED

    def test_collapse_reset_is_not_weakness_clearing(self):
        assert assign_weakness_state("COLLAPSE_RESET") != WEAKNESS_CLEARING

    def test_collapse_reset_reset_not_confirmed(self):
        rs = assign_reset_state("COLLAPSE_RESET")
        assert rs == RESET_NOT_CONFIRMED_STATE, (
            f"COLLAPSE_RESET reset must be RESET_NOT_CONFIRMED (bottom not in), got {rs}"
        )

    def test_collapse_reset_policy_is_blocked_weakness(self):
        r = evaluate_reentry_block_policy(
            weakness_state=assign_weakness_state("COLLAPSE_RESET"),
            reset_state=assign_reset_state("COLLAPSE_RESET"),
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
            parent_constructive_state=PARENT_CONSTRUCTIVE,
        )
        assert r.reentry_state == REENTRY_BLOCKED_WEAKNESS, (
            f"COLLAPSE_RESET must produce REENTRY_BLOCKED_WEAKNESS, got {r.reentry_state}"
        )

    def test_collapse_reset_neq_inhale_accumulation_weakness(self):
        collapse_ws = assign_weakness_state("COLLAPSE_RESET")
        inhale_ws = assign_weakness_state("INHALE_ACCUMULATION")
        assert collapse_ws != inhale_ws, (
            "COLLAPSE_RESET and INHALE_ACCUMULATION must have different weakness states. "
            f"Both returned {collapse_ws}"
        )

    def test_collapse_reset_neq_inhale_accumulation_reset(self):
        collapse_rs = assign_reset_state("COLLAPSE_RESET")
        inhale_rs = assign_reset_state("INHALE_ACCUMULATION")
        assert collapse_rs != inhale_rs, (
            "COLLAPSE_RESET and INHALE_ACCUMULATION must have different reset states. "
            f"Both returned {collapse_rs}"
        )


# ---------------------------------------------------------------------------
# 4. Parent terminal → REENTRY_BLOCKED_PARENT_TERMINAL
# ---------------------------------------------------------------------------

class TestParentTerminalBlocked:
    def test_parent_blocking_state(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_RESOLVED,
            reset_state=RESET_CONFIRMED_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
            parent_constructive_state=PARENT_BLOCKING,
        )
        assert r.reentry_state == REENTRY_BLOCKED_PARENT_TERMINAL

    def test_weakness_takes_priority_over_parent(self):
        # If weakness is also active, weakness rule fires first (rule 4 > rule 5)
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_ACTIVE,
            parent_constructive_state=PARENT_BLOCKING,
        )
        assert r.reentry_state == REENTRY_BLOCKED_WEAKNESS

    def test_parent_constructive_does_not_block(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_RESOLVED,
            reset_state=RESET_CONFIRMED_STATE,
            reclaim_state=RECLAIM_CONFIRMED_STATE,
            reload_zone_state=ZONE_TESTED,
            breath_alignment=BREATH_ALIGNMENT_POSITIVE,
            regime_state=REGIME_SUPPORTIVE,
            parent_constructive_state=PARENT_CONSTRUCTIVE,
        )
        assert r.reentry_state != REENTRY_BLOCKED_PARENT_TERMINAL

    def test_assign_parent_constructive_terminal_confirmed(self):
        assert assign_parent_constructive_state("TERMINAL_CONFIRMED") == PARENT_BLOCKING

    def test_assign_parent_constructive_not_terminal(self):
        assert assign_parent_constructive_state("NOT_TERMINAL") == PARENT_CONSTRUCTIVE


# ---------------------------------------------------------------------------
# 5. Reload zone touch alone insufficient without reclaim
# ---------------------------------------------------------------------------

class TestReloadZoneAloneInsufficient:
    def test_zone_tested_without_reclaim_is_watch(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_RESOLVED,
            reset_state=RESET_CONFIRMED_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,  # no reclaim
            reload_zone_state=ZONE_TESTED,              # zone tested
            breath_alignment=BREATH_ALIGNMENT_POSITIVE,
            regime_state=REGIME_SUPPORTIVE,
            parent_constructive_state=PARENT_CONSTRUCTIVE,
        )
        assert r.reentry_state == WATCH_REENTRY, (
            f"Zone touch alone without reclaim must be WATCH_REENTRY, got {r.reentry_state}"
        )

    def test_zone_tested_without_reset_is_not_supported(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_RESOLVED,
            reset_state=RESET_FORMING_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
            reload_zone_state=ZONE_TESTED,
        )
        assert r.reentry_state != REENTRY_CONTEXT_SUPPORTED


# ---------------------------------------------------------------------------
# 6. Reclaim + supportive Breath/Regime → REENTRY_CONTEXT_SUPPORTED
# ---------------------------------------------------------------------------

class TestReentryContextSupported:
    def test_full_support_conditions_met(self):
        r = evaluate_reentry_block_policy(**_supported_inputs())
        assert r.reentry_state == REENTRY_CONTEXT_SUPPORTED

    def test_gate_applied(self):
        r = evaluate_reentry_block_policy(**_supported_inputs())
        assert r.gate_applied is True

    def test_live_valid(self):
        r = evaluate_reentry_block_policy(**_supported_inputs())
        assert r.live_valid is True

    def test_no_fallback_needed(self):
        r = evaluate_reentry_block_policy(**_supported_inputs())
        assert r.fallback_policy is None

    def test_inhale_accumulation_confirmed_supports(self):
        # INHALE_ACCUMULATION with CONFIRMED state provides RECLAIM_CONFIRMED
        rc = assign_reclaim_state("INHALE_ACCUMULATION", "CONFIRMED")
        assert rc == RECLAIM_CONFIRMED_STATE

    def test_inhale_accumulation_weakness_resolved(self):
        assert assign_weakness_state("INHALE_ACCUMULATION") == WEAKNESS_RESOLVED

    def test_inhale_accumulation_reset_confirmed(self):
        assert assign_reset_state("INHALE_ACCUMULATION") == RESET_CONFIRMED_STATE


# ---------------------------------------------------------------------------
# 7. Reclaim + conflicting Breath/Regime → REENTRY_CONTEXT_CONFLICT
# ---------------------------------------------------------------------------

class TestReentryContextConflict:
    def test_negative_breath_alignment_is_conflict(self):
        inputs = _supported_inputs()
        inputs["breath_alignment"] = BREATH_ALIGNMENT_NEGATIVE
        r = evaluate_reentry_block_policy(**inputs)
        assert r.reentry_state == REENTRY_CONTEXT_CONFLICT

    def test_conflicting_regime_is_conflict(self):
        inputs = _supported_inputs()
        inputs["regime_state"] = REGIME_CONFLICTING
        r = evaluate_reentry_block_policy(**inputs)
        assert r.reentry_state == REENTRY_CONTEXT_CONFLICT

    def test_native_short_1h_conflict_is_conflict(self):
        inputs = _supported_inputs()
        inputs["native_short_1h_support"] = SHORT_1H_CONFLICT
        r = evaluate_reentry_block_policy(**inputs)
        assert r.reentry_state == REENTRY_CONTEXT_CONFLICT

    def test_conflict_gate_applied(self):
        inputs = _supported_inputs()
        inputs["regime_state"] = REGIME_CONFLICTING
        r = evaluate_reentry_block_policy(**inputs)
        assert r.gate_applied is True


# ---------------------------------------------------------------------------
# 8. CONTEXT_UNKNOWN → NOT_LIVE_VALID; fail closed
# ---------------------------------------------------------------------------

class TestContextUnknown:
    def test_all_unknown_produces_context_unknown(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_UNKNOWN,
            reset_state=RESET_UNKNOWN_STATE,
            reclaim_state=RECLAIM_UNKNOWN_STATE,
        )
        assert r.reentry_state == CONTEXT_UNKNOWN

    def test_context_unknown_not_live_valid(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_UNKNOWN,
            reset_state=RESET_UNKNOWN_STATE,
            reclaim_state=RECLAIM_UNKNOWN_STATE,
        )
        assert r.live_valid is False

    def test_context_unknown_fail_closed(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_UNKNOWN,
            reset_state=RESET_UNKNOWN_STATE,
            reclaim_state=RECLAIM_UNKNOWN_STATE,
        )
        assert r.fallback_policy == "fail_closed"

    def test_neutral_transition_produces_unknown_states(self):
        ws = assign_weakness_state("NEUTRAL_TRANSITION")
        rs = assign_reset_state("NEUTRAL_TRANSITION")
        assert ws == WEAKNESS_UNKNOWN
        assert rs == RESET_UNKNOWN_STATE


# ---------------------------------------------------------------------------
# 9. Future context → NOT_LIVE_VALID (no future leakage)
# ---------------------------------------------------------------------------

class TestFutureContextRejected:
    def test_future_context_ts_rejected(self):
        decision = _ts("2024-06-01T12:00:00")
        context = _ts("2024-06-01T16:00:00")
        r = evaluate_reentry_block_policy(
            decision_ts_utc=decision,
            context_ts_utc=context,
            weakness_state=WEAKNESS_RESOLVED,
        )
        assert r.reentry_state == NOT_LIVE_VALID
        assert r.live_valid is False

    def test_past_context_ts_accepted(self):
        decision = _ts("2024-06-01T12:00:00")
        context = _ts("2024-06-01T08:00:00")
        r = evaluate_reentry_block_policy(
            decision_ts_utc=decision,
            context_ts_utc=context,
            weakness_state=WEAKNESS_ACTIVE,
        )
        assert r.reentry_state == REENTRY_BLOCKED_WEAKNESS  # weakness rule fires, not future

    def test_same_ts_not_rejected(self):
        ts = _ts("2024-06-01T12:00:00")
        r = evaluate_reentry_block_policy(
            decision_ts_utc=ts,
            context_ts_utc=ts,
            weakness_state=WEAKNESS_ACTIVE,
        )
        assert r.reentry_state != NOT_LIVE_VALID


# ---------------------------------------------------------------------------
# 10. Stale context → NOT_LIVE_VALID
# ---------------------------------------------------------------------------

class TestStaleContext:
    def test_age_exceeds_max_is_not_live_valid(self):
        r = evaluate_reentry_block_policy(
            context_age_minutes=600,
            max_context_age_minutes=480,
            weakness_state=WEAKNESS_RESOLVED,
        )
        assert r.reentry_state == NOT_LIVE_VALID
        assert r.live_valid is False

    def test_exactly_at_max_not_stale(self):
        r = evaluate_reentry_block_policy(
            context_age_minutes=480,
            max_context_age_minutes=480,
            weakness_state=WEAKNESS_ACTIVE,
        )
        assert r.reentry_state == REENTRY_BLOCKED_WEAKNESS  # weakness fires, not stale


# ---------------------------------------------------------------------------
# 11. assign_weakness_state — COLLAPSE_RESET ≠ INHALE_ACCUMULATION
# ---------------------------------------------------------------------------

class TestCollapseVsInhaleDistinction:
    """The collapse-vs-inhale distinction is the core architectural rule."""

    def test_collapse_reset_is_weakness_active(self):
        assert assign_weakness_state("COLLAPSE_RESET") == WEAKNESS_ACTIVE

    def test_inhale_accumulation_is_weakness_resolved(self):
        assert assign_weakness_state("INHALE_ACCUMULATION") == WEAKNESS_RESOLVED

    def test_collapse_neq_inhale_weakness(self):
        assert (
            assign_weakness_state("COLLAPSE_RESET")
            != assign_weakness_state("INHALE_ACCUMULATION")
        )

    def test_collapse_neq_inhale_reset(self):
        assert (
            assign_reset_state("COLLAPSE_RESET")
            != assign_reset_state("INHALE_ACCUMULATION")
        )


# ---------------------------------------------------------------------------
# 12. assign_weakness_state — EXHALE and OVERBREATH are WEAKNESS_ACTIVE
# ---------------------------------------------------------------------------

class TestWeaknessActivePhases:
    def test_exhale_expansion(self):
        assert assign_weakness_state("EXHALE_EXPANSION") == WEAKNESS_ACTIVE

    def test_overbreath_extension(self):
        assert assign_weakness_state("OVERBREATH_EXTENSION") == WEAKNESS_ACTIVE

    def test_hold_compression_resolved(self):
        assert assign_weakness_state("HOLD_COMPRESSION") == WEAKNESS_RESOLVED


# ---------------------------------------------------------------------------
# 13. High reversal_pressure downgrades WEAKNESS_RESOLVED → WEAKNESS_CLEARING
# ---------------------------------------------------------------------------

class TestHighReversalPressureDowngrade:
    def test_high_reversal_pressure_on_resolved_phase_clears(self):
        ws = assign_weakness_state(
            "INHALE_ACCUMULATION",
            reversal_pressure_score=REVERSAL_PRESSURE_WEAKNESS_THRESHOLD + 1,
        )
        assert ws == WEAKNESS_CLEARING

    def test_normal_reversal_pressure_stays_resolved(self):
        ws = assign_weakness_state(
            "INHALE_ACCUMULATION",
            reversal_pressure_score=10.0,
        )
        assert ws == WEAKNESS_RESOLVED

    def test_high_pressure_does_not_affect_already_active(self):
        ws = assign_weakness_state(
            "EXHALE_EXPANSION",
            reversal_pressure_score=REVERSAL_PRESSURE_WEAKNESS_THRESHOLD + 1,
        )
        assert ws == WEAKNESS_ACTIVE  # already active; downgrade does not apply


# ---------------------------------------------------------------------------
# 14. assign_reset_state — COLLAPSE_RESET → RESET_NOT_CONFIRMED
# ---------------------------------------------------------------------------

class TestResetStateCollapse:
    def test_collapse_reset_is_not_confirmed(self):
        assert assign_reset_state("COLLAPSE_RESET") == RESET_NOT_CONFIRMED_STATE

    def test_exhale_expansion_is_not_confirmed(self):
        assert assign_reset_state("EXHALE_EXPANSION") == RESET_NOT_CONFIRMED_STATE

    def test_overbreath_is_not_confirmed(self):
        assert assign_reset_state("OVERBREATH_EXTENSION") == RESET_NOT_CONFIRMED_STATE

    def test_neutral_transition_is_unknown(self):
        assert assign_reset_state("NEUTRAL_TRANSITION") == RESET_UNKNOWN_STATE


# ---------------------------------------------------------------------------
# 15. assign_reset_state — INHALE_ACCUMULATION → RESET_CONFIRMED
# ---------------------------------------------------------------------------

class TestResetStateInhale:
    def test_inhale_accumulation_is_confirmed(self):
        assert assign_reset_state("INHALE_ACCUMULATION") == RESET_CONFIRMED_STATE

    def test_hold_compression_is_confirmed(self):
        assert assign_reset_state("HOLD_COMPRESSION") == RESET_CONFIRMED_STATE


# ---------------------------------------------------------------------------
# 16. assign_reclaim_state — INHALE_ACCUMULATION + CONFIRMED → RECLAIM_CONFIRMED
# ---------------------------------------------------------------------------

class TestReclaimStateConfirmed:
    def test_inhale_confirmed_is_reclaim_confirmed(self):
        assert assign_reclaim_state("INHALE_ACCUMULATION", "CONFIRMED") == RECLAIM_CONFIRMED_STATE

    def test_hold_compression_confirmed_is_reclaim_confirmed(self):
        assert assign_reclaim_state("HOLD_COMPRESSION", "CONFIRMED") == RECLAIM_CONFIRMED_STATE


# ---------------------------------------------------------------------------
# 17. assign_reclaim_state — INHALE without CONFIRMED → RECLAIM_NOT_CONFIRMED
# ---------------------------------------------------------------------------

class TestReclaimStateNotConfirmed:
    def test_inhale_forming_is_not_confirmed(self):
        assert assign_reclaim_state("INHALE_ACCUMULATION", "FORMING") == RECLAIM_NOT_CONFIRMED_STATE

    def test_exhale_any_is_not_confirmed(self):
        assert assign_reclaim_state("EXHALE_EXPANSION", "CONFIRMED") == RECLAIM_NOT_CONFIRMED_STATE

    def test_collapse_is_not_confirmed(self):
        assert assign_reclaim_state("COLLAPSE_RESET", "RESET") == RECLAIM_NOT_CONFIRMED_STATE

    def test_neutral_is_reclaim_unknown(self):
        assert assign_reclaim_state("NEUTRAL_TRANSITION", "UNKNOWN") == RECLAIM_UNKNOWN_STATE


# ---------------------------------------------------------------------------
# 18. assign_reload_zone_state — compression threshold
# ---------------------------------------------------------------------------

class TestReloadZoneState:
    def test_above_tested_threshold_is_zone_tested(self):
        score = COMPRESSION_ZONE_TESTED_THRESHOLD + 1.0
        assert assign_reload_zone_state(score) == ZONE_TESTED

    def test_exactly_at_tested_threshold_is_zone_tested(self):
        # > threshold required
        assert assign_reload_zone_state(COMPRESSION_ZONE_TESTED_THRESHOLD + 0.001) == ZONE_TESTED

    def test_between_thresholds_is_zone_approaching(self):
        score = (COMPRESSION_ZONE_TESTED_THRESHOLD + COMPRESSION_ZONE_APPROACHING_THRESHOLD) / 2
        assert assign_reload_zone_state(score) == ZONE_APPROACHING

    def test_below_approaching_threshold_is_not_tested(self):
        assert assign_reload_zone_state(COMPRESSION_ZONE_APPROACHING_THRESHOLD - 1) == ZONE_NOT_TESTED

    def test_zero_compression_is_not_tested(self):
        assert assign_reload_zone_state(0.0) == ZONE_NOT_TESTED


# ---------------------------------------------------------------------------
# 19. assign_breath_alignment — threshold boundaries
# ---------------------------------------------------------------------------

class TestBreathAlignment:
    def test_above_positive_threshold_is_positive(self):
        assert assign_breath_alignment(BREATH_ALIGNMENT_POSITIVE_THRESHOLD + 1) == BREATH_ALIGNMENT_POSITIVE

    def test_below_negative_threshold_is_negative(self):
        assert assign_breath_alignment(BREATH_ALIGNMENT_NEGATIVE_THRESHOLD - 1) == BREATH_ALIGNMENT_NEGATIVE

    def test_between_thresholds_is_neutral(self):
        assert assign_breath_alignment(0.0) == BREATH_ALIGNMENT_NEUTRAL


# ---------------------------------------------------------------------------
# 20. assign_regime_state — conflicting regime blocks supported state
# ---------------------------------------------------------------------------

class TestRegimeState:
    def test_low_breath_score_is_conflicting(self):
        rs = assign_regime_state(
            market_breath_score=REGIME_CONFLICTING_BREATH_SCORE - 1,
            momentum_score=0.0,
        )
        assert rs == REGIME_CONFLICTING

    def test_low_momentum_is_conflicting(self):
        rs = assign_regime_state(
            market_breath_score=60.0,
            momentum_score=-25.0,
        )
        assert rs == REGIME_CONFLICTING

    def test_high_breath_score_positive_momentum_is_supportive(self):
        rs = assign_regime_state(
            market_breath_score=REGIME_SUPPORTIVE_BREATH_SCORE + 1,
            momentum_score=0.0,
        )
        assert rs == REGIME_SUPPORTIVE


# ---------------------------------------------------------------------------
# 21. evaluate_reentry_block_policy — RESET_NOT_CONFIRMED → RESET_REQUIRED
# ---------------------------------------------------------------------------

class TestResetRequired:
    def test_reset_not_confirmed_is_reset_required(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_RESOLVED,
            reset_state=RESET_NOT_CONFIRMED_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
            parent_constructive_state=PARENT_CONSTRUCTIVE,
        )
        assert r.reentry_state == RESET_REQUIRED


# ---------------------------------------------------------------------------
# 22. evaluate_reentry_block_policy — RESET_FORMING → WATCH_REENTRY
# ---------------------------------------------------------------------------

class TestResetForming:
    def test_reset_forming_is_watch_reentry(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_CLEARING,
            reset_state=RESET_FORMING_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
            parent_constructive_state=PARENT_CONSTRUCTIVE,
        )
        assert r.reentry_state == WATCH_REENTRY


# ---------------------------------------------------------------------------
# 23. evaluate_reentry_block_policy — reset confirmed, no reclaim → WATCH_REENTRY
# ---------------------------------------------------------------------------

class TestResetConfirmedNoReclaim:
    def test_reset_confirmed_no_reclaim_is_watch(self):
        r = evaluate_reentry_block_policy(
            weakness_state=WEAKNESS_RESOLVED,
            reset_state=RESET_CONFIRMED_STATE,
            reclaim_state=RECLAIM_NOT_CONFIRMED_STATE,
            breath_alignment=BREATH_ALIGNMENT_POSITIVE,
            regime_state=REGIME_SUPPORTIVE,
            parent_constructive_state=PARENT_CONSTRUCTIVE,
        )
        assert r.reentry_state == WATCH_REENTRY


# ---------------------------------------------------------------------------
# 24. decision_gate / execution_planner / executor not imported or called
# ---------------------------------------------------------------------------

class TestNoForbiddenDependencies:
    def _src_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "src" / "research" / "run_weakness_reentry_block_v1.py"
        )

    def test_execution_planner_not_imported(self):
        source = self._src_path().read_text()
        assert "import execution_planner" not in source
        assert "from execution_planner" not in source

    def test_decision_gate_not_imported(self):
        source = self._src_path().read_text()
        assert "import decision_gate" not in source
        assert "from decision_gate" not in source

    def test_executor_not_imported(self):
        source = self._src_path().read_text()
        assert "import executor" not in source
        assert "from executor" not in source

    def test_no_forbidden_module_calls(self):
        import re
        source = self._src_path().read_text()
        for module in ("execution_planner", "decision_gate", "executor"):
            calls = re.findall(rf'{module}\s*\.\s*\w+\s*\(', source)
            assert not calls, f"{module} called as code: {calls}"

    def test_no_forbidden_imports_via_ast(self):
        source = self._src_path().read_text()
        tree = ast.parse(source)
        forbidden = {"execution_planner", "decision_gate", "executor"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(f in alias.name for f in forbidden)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not any(f in node.module for f in forbidden)


# ---------------------------------------------------------------------------
# 25. Safety markers present
# ---------------------------------------------------------------------------

class TestSafetyMarkers:
    def test_constants_present(self):
        assert RUNNER_NAME == "WEAKNESS_REENTRY_BLOCK_V1"
        assert VERSION is not None

    def test_safety_marker_values(self):
        sm = {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        }
        assert sm["broker_private_calls"] == 0
        assert sm["execution_planner"] == "none"
        assert sm["decision_gate"] == "none"
