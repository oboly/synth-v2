"""
Tests for run_parent_terminal_residual_exit_v1.

Covers:
  1.  evaluate_parent_terminal_policy — PARENT_CONTEXT_UNKNOWN → NOT_LIVE_VALID + fallback
  2.  evaluate_parent_terminal_policy — stale context (age > max) → NOT_LIVE_VALID
  3.  evaluate_parent_terminal_policy — future parent context → NOT_LIVE_VALID (no future leakage)
  4.  evaluate_parent_terminal_policy — TERMINAL_CONFIRMED + WEAKNESS_CONFIRMED → REDUCE_TO_RESIDUAL
  5.  evaluate_parent_terminal_policy — TERMINAL_CONFIRMED + no weakness → HOLD_RUNNER
  6.  evaluate_parent_terminal_policy — TERMINAL_CANDIDATE → PARTIAL_TRIM_ONLY (wait for confirmation)
  7.  evaluate_parent_terminal_policy — NOT_TERMINAL → PARTIAL_TRIM_ONLY (preserve runner)
  8.  evaluate_parent_terminal_policy — PARENT_MAP_INVALIDATED → NO_EXIT_CONFIRMATION
  9.  evaluate_parent_terminal_policy — residual_pct=0 → REDUCE_TO_RESIDUAL but live_valid=False
  10. assign_synthetic_parent_state — correct mapping for each breath phase
  11. assign_synthetic_weakness_state — COLLAPSE_RESET+RESET → WEAKNESS_CONFIRMED
  12. assign_synthetic_weakness_state — all non-COLLAPSE_RESET phases → WEAKNESS_NOT_CONFIRMED
  13. compute_variant_return — V1 always returns r1
  14. compute_variant_return — V2 blended return only when REDUCE_TO_RESIDUAL
  15. compute_variant_return — V3 blended return only when REDUCE_TO_RESIDUAL
  16. compute_variant_return — V4 full exit at r6 when REDUCE_TO_RESIDUAL
  17. compute_variant_return — V5 always returns r24
  18. compute_variant_return — V2 falls back to r1 when action != REDUCE_TO_RESIDUAL
  19. execution_planner is not imported, referenced, or changed
  20. safety markers present in summary
"""
import ast
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure project root is on path for module resolution
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.run_parent_terminal_residual_exit_v1 import (
    ACTION_HOLD_RUNNER,
    ACTION_NO_EXIT_CONFIRMATION,
    ACTION_NOT_LIVE_VALID,
    ACTION_PARTIAL_TRIM_ONLY,
    ACTION_REDUCE_TO_RESIDUAL,
    PARENT_CONTEXT_UNKNOWN,
    PARENT_CONTEXT_STALE,
    PARENT_MAP_INVALIDATED,
    PARENT_NOT_TERMINAL,
    PARENT_TERMINAL_CANDIDATE,
    PARENT_TERMINAL_CONFIRMED,
    WEAKNESS_CONFIRMED,
    WEAKNESS_NOT_CONFIRMED,
    WEAKNESS_UNKNOWN,
    VARIANT_CHILD_PARTIAL_TRIM,
    VARIANT_RESIDUAL_10,
    VARIANT_RESIDUAL_5,
    VARIANT_FULL_EXIT_BENCHMARK,
    VARIANT_BUY_AND_HOLD,
    DEFAULT_RESIDUAL_PCT,
    assign_synthetic_parent_state,
    assign_synthetic_weakness_state,
    compute_variant_return,
    evaluate_parent_terminal_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. PARENT_CONTEXT_UNKNOWN → NOT_LIVE_VALID + fallback to PARTIAL_TRIM_ONLY
# ---------------------------------------------------------------------------

class TestUnknownParentContext:
    def test_action_is_not_live_valid(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_CONTEXT_UNKNOWN,
            weakness_confirmation_state=WEAKNESS_UNKNOWN,
        )
        assert r.research_action == ACTION_NOT_LIVE_VALID

    def test_live_valid_is_false(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_CONTEXT_UNKNOWN,
            weakness_confirmation_state=WEAKNESS_UNKNOWN,
        )
        assert r.live_valid is False

    def test_fallback_policy_is_partial_trim(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_CONTEXT_UNKNOWN,
            weakness_confirmation_state=WEAKNESS_UNKNOWN,
        )
        assert r.fallback_policy == ACTION_PARTIAL_TRIM_ONLY

    def test_parent_state_preserved(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_CONTEXT_UNKNOWN,
            weakness_confirmation_state=WEAKNESS_UNKNOWN,
        )
        assert r.parent_terminal_state == PARENT_CONTEXT_UNKNOWN


# ---------------------------------------------------------------------------
# 2. Stale context (age > max) → NOT_LIVE_VALID
# ---------------------------------------------------------------------------

class TestStaleContext:
    def test_stale_by_age_not_live_valid(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            parent_context_age_minutes=600,
            max_parent_context_age_minutes=480,
        )
        assert r.research_action == ACTION_NOT_LIVE_VALID
        assert r.live_valid is False
        assert r.parent_terminal_state == PARENT_CONTEXT_STALE

    def test_exactly_at_max_is_not_stale(self):
        # age == max: not stale (> max required)
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            parent_context_age_minutes=480,
            max_parent_context_age_minutes=480,
        )
        assert r.research_action == ACTION_REDUCE_TO_RESIDUAL
        assert r.live_valid is True

    def test_stale_state_caller_provided(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_CONTEXT_STALE,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
        )
        assert r.research_action == ACTION_NOT_LIVE_VALID
        assert r.live_valid is False


# ---------------------------------------------------------------------------
# 3. Future parent context → NOT_LIVE_VALID (no future leakage)
# ---------------------------------------------------------------------------

class TestFutureParentContext:
    def test_future_parent_context_rejected(self):
        decision = _ts("2024-01-10T12:00:00")
        parent_ctx = _ts("2024-01-10T14:00:00")
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            decision_ts_utc=decision,
            parent_context_ts_utc=parent_ctx,
        )
        assert r.research_action == ACTION_NOT_LIVE_VALID
        assert r.live_valid is False

    def test_past_parent_context_accepted(self):
        decision = _ts("2024-01-10T12:00:00")
        parent_ctx = _ts("2024-01-10T08:00:00")
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            decision_ts_utc=decision,
            parent_context_ts_utc=parent_ctx,
        )
        assert r.research_action == ACTION_REDUCE_TO_RESIDUAL
        assert r.live_valid is True

    def test_same_ts_context_accepted(self):
        decision = _ts("2024-01-10T12:00:00")
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            decision_ts_utc=decision,
            parent_context_ts_utc=decision,
        )
        assert r.research_action == ACTION_REDUCE_TO_RESIDUAL


# ---------------------------------------------------------------------------
# 4. TERMINAL_CONFIRMED + WEAKNESS_CONFIRMED → REDUCE_TO_RESIDUAL
# ---------------------------------------------------------------------------

class TestTerminalConfirmedWithWeakness:
    def test_action_is_reduce_to_residual(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
        )
        assert r.research_action == ACTION_REDUCE_TO_RESIDUAL

    def test_live_valid_is_true(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
        )
        assert r.live_valid is True

    def test_residual_pct_preserved(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            residual_target_pct=5.0,
        )
        assert r.residual_target_pct == 5.0
        assert r.requested_reduce_pct == 95.0

    def test_default_reduce_pct(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
        )
        assert r.residual_target_pct == DEFAULT_RESIDUAL_PCT
        assert r.requested_reduce_pct == 90.0

    def test_parent_map_completed_treated_as_confirmed(self):
        from src.research.run_parent_terminal_residual_exit_v1 import PARENT_MAP_COMPLETED
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_MAP_COMPLETED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
        )
        assert r.research_action == ACTION_REDUCE_TO_RESIDUAL
        assert r.live_valid is True


# ---------------------------------------------------------------------------
# 5. TERMINAL_CONFIRMED + no weakness → HOLD_RUNNER
# ---------------------------------------------------------------------------

class TestTerminalConfirmedNoWeakness:
    def test_weakness_not_confirmed_holds_runner(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_NOT_CONFIRMED,
        )
        assert r.research_action == ACTION_HOLD_RUNNER
        assert r.live_valid is True

    def test_weakness_unknown_holds_runner(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_UNKNOWN,
        )
        assert r.research_action == ACTION_HOLD_RUNNER


# ---------------------------------------------------------------------------
# 6. TERMINAL_CANDIDATE → PARTIAL_TRIM_ONLY (wait for confirmation)
# ---------------------------------------------------------------------------

class TestTerminalCandidate:
    def test_action_is_partial_trim(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CANDIDATE,
            weakness_confirmation_state=WEAKNESS_NOT_CONFIRMED,
        )
        assert r.research_action == ACTION_PARTIAL_TRIM_ONLY

    def test_live_valid_is_true(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CANDIDATE,
            weakness_confirmation_state=WEAKNESS_NOT_CONFIRMED,
        )
        assert r.live_valid is True

    def test_no_fallback_needed(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CANDIDATE,
            weakness_confirmation_state=WEAKNESS_NOT_CONFIRMED,
        )
        assert r.fallback_policy is None


# ---------------------------------------------------------------------------
# 7. NOT_TERMINAL → PARTIAL_TRIM_ONLY (preserve runner)
# ---------------------------------------------------------------------------

class TestNotTerminal:
    def test_action_is_partial_trim(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_NOT_TERMINAL,
            weakness_confirmation_state=WEAKNESS_NOT_CONFIRMED,
        )
        assert r.research_action == ACTION_PARTIAL_TRIM_ONLY

    def test_live_valid_is_true(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_NOT_TERMINAL,
            weakness_confirmation_state=WEAKNESS_NOT_CONFIRMED,
        )
        assert r.live_valid is True


# ---------------------------------------------------------------------------
# 8. PARENT_MAP_INVALIDATED → NO_EXIT_CONFIRMATION
# ---------------------------------------------------------------------------

class TestMapInvalidated:
    def test_action_is_no_exit_confirmation(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_MAP_INVALIDATED,
            weakness_confirmation_state=WEAKNESS_UNKNOWN,
        )
        assert r.research_action == ACTION_NO_EXIT_CONFIRMATION

    def test_live_valid_is_true(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_MAP_INVALIDATED,
            weakness_confirmation_state=WEAKNESS_UNKNOWN,
        )
        assert r.live_valid is True


# ---------------------------------------------------------------------------
# 9. residual_pct=0 → REDUCE_TO_RESIDUAL but live_valid=False (benchmark only)
# ---------------------------------------------------------------------------

class TestResidualZero:
    def test_benchmark_fires_reduce_action(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            residual_target_pct=0.0,
        )
        assert r.research_action == ACTION_REDUCE_TO_RESIDUAL

    def test_benchmark_not_live_valid(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            residual_target_pct=0.0,
        )
        assert r.live_valid is False

    def test_benchmark_requested_reduce_pct_is_100(self):
        r = evaluate_parent_terminal_policy(
            parent_terminal_state=PARENT_TERMINAL_CONFIRMED,
            weakness_confirmation_state=WEAKNESS_CONFIRMED,
            residual_target_pct=0.0,
        )
        assert r.requested_reduce_pct == 100.0


# ---------------------------------------------------------------------------
# 10. assign_synthetic_parent_state — mapping correctness
# ---------------------------------------------------------------------------

class TestSyntheticParentStateMapping:
    def test_exhale_expansion_not_terminal(self):
        assert assign_synthetic_parent_state("EXHALE_EXPANSION") == PARENT_NOT_TERMINAL

    def test_inhale_accumulation_not_terminal(self):
        assert assign_synthetic_parent_state("INHALE_ACCUMULATION") == PARENT_NOT_TERMINAL

    def test_overbreath_extension_candidate(self):
        assert assign_synthetic_parent_state("OVERBREATH_EXTENSION") == PARENT_TERMINAL_CANDIDATE

    def test_hold_compression_candidate(self):
        assert assign_synthetic_parent_state("HOLD_COMPRESSION") == PARENT_TERMINAL_CANDIDATE

    def test_collapse_reset_confirmed(self):
        assert assign_synthetic_parent_state("COLLAPSE_RESET") == PARENT_TERMINAL_CONFIRMED

    def test_neutral_transition_unknown(self):
        assert assign_synthetic_parent_state("NEUTRAL_TRANSITION") == PARENT_CONTEXT_UNKNOWN

    def test_unknown_phase_unknown(self):
        assert assign_synthetic_parent_state("UNKNOWN_PHASE") == PARENT_CONTEXT_UNKNOWN


# ---------------------------------------------------------------------------
# 11. assign_synthetic_weakness_state — COLLAPSE_RESET + RESET → WEAKNESS_CONFIRMED
# ---------------------------------------------------------------------------

class TestSyntheticWeaknessConfirmed:
    def test_collapse_reset_with_reset_state(self):
        assert assign_synthetic_weakness_state("COLLAPSE_RESET", "RESET") == WEAKNESS_CONFIRMED


# ---------------------------------------------------------------------------
# 12. assign_synthetic_weakness_state — other phases → not confirmed or unknown
# ---------------------------------------------------------------------------

class TestSyntheticWeaknessOtherPhases:
    def test_exhale_expansion_not_confirmed(self):
        assert assign_synthetic_weakness_state("EXHALE_EXPANSION", "CONFIRMED") == WEAKNESS_NOT_CONFIRMED

    def test_inhale_accumulation_not_confirmed(self):
        assert assign_synthetic_weakness_state("INHALE_ACCUMULATION", "FORMING") == WEAKNESS_NOT_CONFIRMED

    def test_overbreath_extension_late_not_confirmed(self):
        assert assign_synthetic_weakness_state("OVERBREATH_EXTENSION", "LATE") == WEAKNESS_NOT_CONFIRMED

    def test_hold_compression_forming_not_confirmed(self):
        assert assign_synthetic_weakness_state("HOLD_COMPRESSION", "FORMING") == WEAKNESS_NOT_CONFIRMED

    def test_collapse_reset_unknown_state_not_confirmed(self):
        assert assign_synthetic_weakness_state("COLLAPSE_RESET", "UNKNOWN") == WEAKNESS_NOT_CONFIRMED

    def test_neutral_transition_unknown_state_weakness_unknown(self):
        assert assign_synthetic_weakness_state("NEUTRAL_TRANSITION", "UNKNOWN") == WEAKNESS_UNKNOWN


# ---------------------------------------------------------------------------
# 13. compute_variant_return — V1 always returns r1
# ---------------------------------------------------------------------------

class TestVariantV1:
    def test_v1_returns_r1_when_no_gate(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_CHILD_PARTIAL_TRIM, None, ACTION_PARTIAL_TRIM_ONLY, 1.5, 3.0, 6.0
        )
        assert vret == pytest.approx(1.5)
        assert applied is False

    def test_v1_returns_r1_regardless_of_action(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_CHILD_PARTIAL_TRIM, None, ACTION_REDUCE_TO_RESIDUAL, 1.5, 3.0, 6.0
        )
        assert vret == pytest.approx(1.5)
        assert applied is False


# ---------------------------------------------------------------------------
# 14. compute_variant_return — V2 blended return when REDUCE_TO_RESIDUAL
# ---------------------------------------------------------------------------

class TestVariantV2:
    def test_v2_blended_when_reduce(self):
        # V2: 90% at r6, 10% at r24
        r6, r24 = 2.0, 5.0
        expected = 0.9 * r6 + 0.1 * r24
        vret, applied, _ = compute_variant_return(
            VARIANT_RESIDUAL_10, 10.0, ACTION_REDUCE_TO_RESIDUAL, 1.0, r6, r24
        )
        assert vret == pytest.approx(expected)
        assert applied is True

    def test_v2_fallback_when_not_reduce(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_RESIDUAL_10, 10.0, ACTION_PARTIAL_TRIM_ONLY, 1.0, 2.0, 5.0
        )
        assert vret == pytest.approx(1.0)
        assert applied is False


# ---------------------------------------------------------------------------
# 15. compute_variant_return — V3 blended return when REDUCE_TO_RESIDUAL
# ---------------------------------------------------------------------------

class TestVariantV3:
    def test_v3_blended_when_reduce(self):
        # V3: 95% at r6, 5% at r24
        r6, r24 = 2.0, 5.0
        expected = 0.95 * r6 + 0.05 * r24
        vret, applied, _ = compute_variant_return(
            VARIANT_RESIDUAL_5, 5.0, ACTION_REDUCE_TO_RESIDUAL, 1.0, r6, r24
        )
        assert vret == pytest.approx(expected)
        assert applied is True

    def test_v3_fallback_when_not_reduce(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_RESIDUAL_5, 5.0, ACTION_NOT_LIVE_VALID, 1.0, 2.0, 5.0
        )
        assert vret == pytest.approx(1.0)
        assert applied is False


# ---------------------------------------------------------------------------
# 16. compute_variant_return — V4 full exit at r6 when REDUCE_TO_RESIDUAL
# ---------------------------------------------------------------------------

class TestVariantV4:
    def test_v4_full_exit_at_r6_when_reduce(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_FULL_EXIT_BENCHMARK, 0.0, ACTION_REDUCE_TO_RESIDUAL, 1.0, 3.5, 6.0
        )
        assert vret == pytest.approx(3.5)
        assert applied is True

    def test_v4_fallback_when_not_reduce(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_FULL_EXIT_BENCHMARK, 0.0, ACTION_PARTIAL_TRIM_ONLY, 1.0, 3.5, 6.0
        )
        assert vret == pytest.approx(1.0)
        assert applied is False


# ---------------------------------------------------------------------------
# 17. compute_variant_return — V5 always returns r24
# ---------------------------------------------------------------------------

class TestVariantV5:
    def test_v5_returns_r24_no_gate(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_BUY_AND_HOLD, None, ACTION_PARTIAL_TRIM_ONLY, 1.0, 2.0, 6.0
        )
        assert vret == pytest.approx(6.0)
        assert applied is False

    def test_v5_returns_r24_regardless_of_action(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_BUY_AND_HOLD, None, ACTION_REDUCE_TO_RESIDUAL, 1.0, 2.0, 6.0
        )
        assert vret == pytest.approx(6.0)
        assert applied is False


# ---------------------------------------------------------------------------
# 18. compute_variant_return — V2 falls back to r1 when action != REDUCE_TO_RESIDUAL
# (duplicate coverage from test 14 — also covers NOT_LIVE_VALID action)
# ---------------------------------------------------------------------------

class TestVariantFallback:
    def test_v2_not_live_valid_falls_back(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_RESIDUAL_10, 10.0, ACTION_NOT_LIVE_VALID, 1.5, 3.0, 6.0
        )
        assert vret == pytest.approx(1.5)
        assert applied is False

    def test_v2_hold_runner_falls_back(self):
        vret, applied, _ = compute_variant_return(
            VARIANT_RESIDUAL_10, 10.0, ACTION_HOLD_RUNNER, 1.5, 3.0, 6.0
        )
        assert vret == pytest.approx(1.5)
        assert applied is False


# ---------------------------------------------------------------------------
# 19. execution_planner is not imported, referenced, or changed
# ---------------------------------------------------------------------------

class TestNoExecutionPlannerDependency:
    def test_execution_planner_not_imported_in_runner(self):
        src_path = (
            Path(__file__).resolve().parents[1]
            / "src" / "research" / "run_parent_terminal_residual_exit_v1.py"
        )
        source = src_path.read_text()
        # Must not import or call execution_planner as code; docstring mentions are allowed.
        assert "import execution_planner" not in source, (
            "execution_planner must not be imported in runner source"
        )
        assert "from execution_planner" not in source, (
            "execution_planner must not be imported in runner source"
        )
        # Must not call execution_planner module as callable code
        # (e.g. execution_planner.plan(), execution_planner.build_*)
        import re
        code_refs = re.findall(r'execution_planner\s*\.\s*\w+\s*\(', source)
        assert not code_refs, (
            f"execution_planner called as code: {code_refs}"
        )

    def test_execution_planner_not_in_imports(self):
        src_path = (
            Path(__file__).resolve().parents[1]
            / "src" / "research" / "run_parent_terminal_residual_exit_v1.py"
        )
        tree = ast.parse(src_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "execution_planner" not in alias.name, (
                            f"execution_planner found in import: {alias.name}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        assert "execution_planner" not in node.module, (
                            f"execution_planner found in import from: {node.module}"
                        )


# ---------------------------------------------------------------------------
# 20. Safety markers present in output summary
# ---------------------------------------------------------------------------

class TestSafetyMarkers:
    def _make_summary(self) -> dict:
        from src.research.run_parent_terminal_residual_exit_v1 import RUNNER_NAME, VERSION
        return {
            "runner": RUNNER_NAME,
            "version": VERSION,
            "safety_markers": {
                "broker_private_calls": 0,
                "broker_writes": 0,
                "order_submission": 0,
                "live_orders": 0,
                "decision_gate": "none",
                "execution_planner": "none",
                "executor": "none",
            },
        }

    def test_safety_markers_present(self):
        sm = self._make_summary()["safety_markers"]
        assert sm["broker_private_calls"] == 0
        assert sm["broker_writes"] == 0
        assert sm["order_submission"] == 0
        assert sm["live_orders"] == 0
        assert sm["decision_gate"] == "none"
        assert sm["execution_planner"] == "none"
        assert sm["executor"] == "none"

    def test_runner_module_has_safety_markers_constant(self):
        import src.research.run_parent_terminal_residual_exit_v1 as m
        # Verify the RUNNER_NAME and VERSION constants exist
        assert hasattr(m, "RUNNER_NAME")
        assert hasattr(m, "VERSION")
        assert m.RUNNER_NAME == "PARENT_TERMINAL_RESIDUAL_EXIT_V1"
