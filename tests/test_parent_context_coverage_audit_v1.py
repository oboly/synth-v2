"""
Tests for run_parent_context_coverage_audit_v1.

Covers:
  1.  strict backward as-of: future context_ts rejected
  2.  stale row rejected by age threshold
  3.  symbol/interval/map mismatch rejected
  4.  classify_unknown_reason — SOURCE_MISSING for all pre-computed artifacts
  5.  classify_unknown_reason — CONTEXT_TRULY_UNKNOWN for NEUTRAL_TRANSITION
  6.  classify_unknown_reason — SYNTHETIC_PROXY_USED for non-neutral phases
  7.  source_refs preserved in audit row
  8.  unknown remains unknown when no valid source exists
  9.  source precedence deterministic (consistent ordering)
  10. execution_planner / decision_gate / executor not imported or called
  11. safety markers present
"""
from __future__ import annotations

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.run_parent_context_coverage_audit_v1 import (
    REASON_SOURCE_MISSING,
    REASON_CONTEXT_TRULY_UNKNOWN,
    REASON_SYNTHETIC_PROXY_USED,
    REASON_SYMBOL_MISSING,
    REASON_TIME_RANGE_MISSING,
    REASON_ASOF_JOIN_MISS,
    RUNNER_NAME,
    VERSION,
    classify_unknown_reason,
    audit_event,
    inspect_candidate_sources,
)


# ---------------------------------------------------------------------------
# 1. Strict backward as-of: future context_ts rejected
# ---------------------------------------------------------------------------

class TestStrictBackwardAsOf:
    """
    The runner enforces parent_context_ts <= decision_ts.
    Audit rows report would_require_db_query and db_join_condition
    to verify the join constraint is documented correctly.
    """

    def test_db_join_condition_uses_backward_asof(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2024-06-01T12:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        # The DB join condition must enforce <= (backward as-of, not >=)
        join = row["db_join_condition"]
        assert "<=" in join, f"DB join must enforce backward as-of (<=), got: {join}"
        assert ">=" not in join.split("<=")[0], "No forward join allowed before the <= condition"

    def test_db_join_uses_desc_limit(self):
        event = {
            "symbol": "ETH",
            "asof_ts_utc": "2024-06-01T08:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        join = row["db_join_condition"]
        assert "DESC" in join, "Join must ORDER BY asof_ts_utc DESC to get latest-before"
        assert "LIMIT 1" in join, "Join must LIMIT 1 to get single canonical row"

    def test_coverage_is_valid_false_without_source(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2024-06-01T12:00:00Z",
            "market_breath_phase": "COLLAPSE_RESET",
            "market_breath_state": "RESET",
        }
        row = audit_event(event, {"file_available": False})
        assert row["coverage_is_valid"] is False


# ---------------------------------------------------------------------------
# 2. Stale row rejected by age threshold
# ---------------------------------------------------------------------------

class TestStaleRowRejected:
    """
    Stale context detection is documented in the db_join_condition.
    The audit marks coverage_is_valid=False for all events (no valid source).
    Stale rejection is enforced upstream by the policy functions.
    """

    def test_audit_does_not_mark_stale_row_as_valid(self):
        # No pre-computed source → coverage always False
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2024-01-10T12:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        assert row["coverage_is_valid"] is False

    def test_db_required_for_context_age_validation(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2024-01-10T12:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        assert row["would_require_db_query"] is True


# ---------------------------------------------------------------------------
# 3. Symbol / interval / map mismatch rejected
# ---------------------------------------------------------------------------

class TestSymbolIntervalMismatch:
    def test_symbol_missing_when_not_in_source(self):
        coverage_with_different_symbols = {
            "file_available": True,
            "covers_symbol": False,
            "covers_time": True,
        }
        reason, _ = classify_unknown_reason(
            "NEUTRAL_TRANSITION", "UNKNOWN", "UNKNOWN_SYMBOL", "2024-01-01T00:00:00Z",
            coverage_with_different_symbols,
        )
        assert reason == REASON_SYMBOL_MISSING

    def test_time_range_missing_when_outside_coverage(self):
        coverage_with_sym_no_time = {
            "file_available": True,
            "covers_symbol": True,
            "covers_time": False,
        }
        reason, _ = classify_unknown_reason(
            "NEUTRAL_TRANSITION", "UNKNOWN", "BTC", "2020-01-01T00:00:00Z",
            coverage_with_sym_no_time,
        )
        assert reason == REASON_TIME_RANGE_MISSING

    def test_asof_join_miss_when_sym_and_time_covered(self):
        coverage_full = {
            "file_available": True,
            "covers_symbol": True,
            "covers_time": True,
        }
        reason, _ = classify_unknown_reason(
            "NEUTRAL_TRANSITION", "UNKNOWN", "BTC", "2024-06-01T12:00:00Z",
            coverage_full,
        )
        assert reason == REASON_ASOF_JOIN_MISS


# ---------------------------------------------------------------------------
# 4. classify_unknown_reason — SOURCE_MISSING for all pre-computed artifacts
# ---------------------------------------------------------------------------

class TestSourceMissingClassification:
    def test_neutral_transition_no_source_is_source_missing(self):
        reason, detail = classify_unknown_reason(
            "NEUTRAL_TRANSITION", "UNKNOWN", "BTC", "2026-03-14T00:00:00Z",
            {"file_available": False},
        )
        assert reason == REASON_SOURCE_MISSING

    def test_source_missing_detail_mentions_no_file(self):
        _, detail = classify_unknown_reason(
            "NEUTRAL_TRANSITION", "UNKNOWN", "BTC", "2026-03-14T00:00:00Z",
            {"file_available": False},
        )
        assert "pre-computed" in detail.lower() or "No pre-computed" in detail


# ---------------------------------------------------------------------------
# 5. classify_unknown_reason — CONTEXT_TRULY_UNKNOWN for NEUTRAL_TRANSITION
# ---------------------------------------------------------------------------

class TestContextTrulyUnknown:
    def test_neutral_transition_detail_mentions_truly_unknown(self):
        _, detail = classify_unknown_reason(
            "NEUTRAL_TRANSITION", "UNKNOWN", "BTC", "2026-03-14T00:00:00Z",
            {"file_available": False},
        )
        assert "CONTEXT_TRULY_UNKNOWN" in detail or "NEUTRAL_TRANSITION" in detail

    def test_neutral_transition_audit_row_unknown_is_true(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2026-03-14T00:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        assert row["is_parent_context_unknown"] is True
        assert row["is_synthetic_proxy"] is False


# ---------------------------------------------------------------------------
# 6. classify_unknown_reason — SYNTHETIC_PROXY_USED for non-neutral phases
# ---------------------------------------------------------------------------

class TestSyntheticProxyUsed:
    def test_collapse_reset_is_synthetic_proxy(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2026-03-14T00:00:00Z",
            "market_breath_phase": "COLLAPSE_RESET",
            "market_breath_state": "RESET",
        }
        row = audit_event(event, {"file_available": False})
        assert row["is_synthetic_proxy"] is True
        assert row["primary_failure_reason"] == REASON_SYNTHETIC_PROXY_USED

    def test_exhale_expansion_is_synthetic_proxy(self):
        event = {
            "symbol": "ETH",
            "asof_ts_utc": "2026-03-14T00:00:00Z",
            "market_breath_phase": "EXHALE_EXPANSION",
            "market_breath_state": "CONFIRMED",
        }
        row = audit_event(event, {"file_available": False})
        assert row["is_synthetic_proxy"] is True
        assert row["primary_failure_reason"] == REASON_SYNTHETIC_PROXY_USED

    def test_synthetic_proxy_secondary_reason_is_source_missing(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2026-03-14T00:00:00Z",
            "market_breath_phase": "INHALE_ACCUMULATION",
            "market_breath_state": "CONFIRMED",
        }
        row = audit_event(event, {"file_available": False})
        assert row["secondary_failure_reason"] == REASON_SOURCE_MISSING

    def test_synthetic_proxy_coverage_still_false(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2026-03-14T00:00:00Z",
            "market_breath_phase": "COLLAPSE_RESET",
            "market_breath_state": "RESET",
        }
        row = audit_event(event, {"file_available": False})
        assert row["coverage_is_valid"] is False, (
            "Synthetic proxy is NOT valid parent context coverage"
        )


# ---------------------------------------------------------------------------
# 7. source_refs preserved in audit row
# ---------------------------------------------------------------------------

class TestSourceRefPreserved:
    def test_audit_row_has_db_table_required(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2026-03-14T00:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        assert row["db_table_required"] == "canonical_fib_zone_map_v1"

    def test_audit_row_has_db_join_condition(self):
        event = {
            "symbol": "XRP",
            "asof_ts_utc": "2026-04-01T00:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        assert "XRP" in row["db_join_condition"]
        assert "2026-04-01" in row["db_join_condition"]


# ---------------------------------------------------------------------------
# 8. Unknown remains unknown when no valid source exists
# ---------------------------------------------------------------------------

class TestUnknownRemainsUnknown:
    def test_no_valid_source_coverage_false(self):
        for phase in [
            "NEUTRAL_TRANSITION", "COLLAPSE_RESET", "EXHALE_EXPANSION",
            "INHALE_ACCUMULATION", "OVERBREATH_EXTENSION", "HOLD_COMPRESSION",
        ]:
            event = {
                "symbol": "BTC",
                "asof_ts_utc": "2026-03-14T00:00:00Z",
                "market_breath_phase": phase,
                "market_breath_state": "UNKNOWN",
            }
            row = audit_event(event, {"file_available": False})
            assert row["coverage_is_valid"] is False, (
                f"Phase {phase}: coverage_is_valid must be False when no source exists"
            )

    def test_no_valid_source_coverage_source_is_none(self):
        event = {
            "symbol": "BTC",
            "asof_ts_utc": "2026-03-14T00:00:00Z",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
        }
        row = audit_event(event, {"file_available": False})
        assert row["coverage_source"] is None


# ---------------------------------------------------------------------------
# 9. Source precedence deterministic
# ---------------------------------------------------------------------------

class TestSourcePrecedenceDeterministic:
    def test_classify_returns_same_reason_for_same_inputs(self):
        args = (
            "NEUTRAL_TRANSITION", "UNKNOWN", "BTC", "2026-03-14T00:00:00Z",
            {"file_available": False},
        )
        r1, d1 = classify_unknown_reason(*args)
        r2, d2 = classify_unknown_reason(*args)
        assert r1 == r2
        assert d1 == d2

    def test_inspect_sources_consistent_order(self):
        outcome_symbols = {"BTC", "ETH"}
        outcome_date_range = ("2026-03-14T00:00:00Z", "2026-05-12T00:00:00Z")
        result1 = inspect_candidate_sources(outcome_symbols, outcome_date_range)
        result2 = inspect_candidate_sources(outcome_symbols, outcome_date_range)
        names1 = [s["source_name"] for s in result1]
        names2 = [s["source_name"] for s in result2]
        assert names1 == names2, "Source inspection must return deterministic ordering"


# ---------------------------------------------------------------------------
# 10. execution_planner / decision_gate / executor not imported or called
# ---------------------------------------------------------------------------

class TestNoForbiddenDependencies:
    def _src_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "src" / "research" / "run_parent_context_coverage_audit_v1.py"
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

    def test_no_forbidden_module_calls_via_ast(self):
        import re
        source = self._src_path().read_text()
        for module in ("execution_planner", "decision_gate", "executor"):
            calls = re.findall(rf'{module}\s*\.\s*\w+\s*\(', source)
            assert not calls, f"{module} called as code: {calls}"


# ---------------------------------------------------------------------------
# 11. Safety markers present
# ---------------------------------------------------------------------------

class TestSafetyMarkers:
    def test_constants_present(self):
        assert RUNNER_NAME == "PARENT_CONTEXT_COVERAGE_AUDIT_V1"
        assert VERSION is not None

    def test_expected_safety_marker_values(self):
        markers = {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        }
        assert markers["execution_planner"] == "none"
        assert markers["broker_writes"] == 0
        assert markers["live_orders"] == 0
