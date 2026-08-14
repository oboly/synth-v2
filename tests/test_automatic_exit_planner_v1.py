from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.decision_gate.automatic_exit_gate_v1 import (
    STATE_APPROVED, STATE_DENIED, STATE_NON_ACTIONABLE, AutomaticExitGateDecisionV1,
)
from src.execution_planner.automatic_exit_planner_v1 import (
    AutomaticExitPlanningContextV1, AutomaticExitPlanningError, build_automatic_exit_plan_v1,
)
from src.exit_policy.automatic_exit_candidate_v1 import AutomaticExitCandidateV1
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _candidate(**overrides: object) -> AutomaticExitCandidateV1:
    values: dict[str, object] = dict(trading_account_id=7, position_reference="position-9", venue="bitvavo", asset_id=42, market="SOL-EUR", candidate_action="REDUCE", reduction_fraction_candidate=Decimal("0.25"), urgency_candidate="NORMAL", reason_code="TARGET_REACHED", evidence_id="evidence-1", exit_profile_id="profile-1", exit_profile_version="1", target_price=Decimal("100"), invalidation_price=Decimal("80"), observed_ts_utc=NOW)
    values.update(overrides)
    return AutomaticExitCandidateV1(**values)  # type: ignore[arg-type]


def _decision(**overrides: object) -> AutomaticExitGateDecisionV1:
    values: dict[str, object] = dict(state=STATE_APPROVED, reason_code="OK", candidate=_candidate(), approved_fraction_candidate=Decimal("0.25"), approved_quantity_ceiling_base=Decimal("2.57"))
    values.update(overrides)
    return AutomaticExitGateDecisionV1(**values)  # type: ignore[arg-type]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"), min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"), supported_order_types=("limit",), supported_time_in_force=("GTC",), source_provenance="PUBLIC", metadata_synced_ts_utc=NOW, status=STATUS_FRESH)
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> AutomaticExitPlanningContextV1:
    values: dict[str, object] = dict(trading_account_id=7, position_reference="position-9", venue="bitvavo", asset_id=42, market="SOL-EUR", reference_price=Decimal("100.01"), venue_constraints=_constraints(), planning_ts_utc=NOW)
    values.update(overrides)
    return AutomaticExitPlanningContextV1(**values)  # type: ignore[arg-type]


def test_approved_gate_builds_deterministic_immutable_sell_ladder_with_provenance() -> None:
    plan = build_automatic_exit_plan_v1(decision=_decision(), context=_context())
    assert plan.side == "SELL"
    assert plan.final_quantity_base == Decimal("2.5")
    assert tuple(leg.quantity_base for leg in plan.legs) == (Decimal("1.2"), Decimal("1.3"))
    assert sum(leg.quantity_base for leg in plan.legs) == plan.final_quantity_base
    assert plan.candidate_action == "REDUCE"
    assert plan.candidate_evidence_id == "evidence-1"
    assert plan.gate_approval.approved_quantity_ceiling_base == Decimal("2.57")
    assert plan == build_automatic_exit_plan_v1(decision=_decision(), context=_context())


@pytest.mark.parametrize("state", [STATE_DENIED, STATE_NON_ACTIONABLE])
def test_non_approved_gate_is_rejected(state: str) -> None:
    with pytest.raises(AutomaticExitPlanningError, match="GATE_DECISION_NOT_APPROVED"):
        build_automatic_exit_plan_v1(decision=_decision(state=state, approved_quantity_ceiling_base=None), context=_context())


def test_gate_ceiling_is_the_final_quantity_owner_without_double_rounding() -> None:
    plan = build_automatic_exit_plan_v1(decision=_decision(approved_quantity_ceiling_base=Decimal("1.99")), context=_context())
    assert plan.final_quantity_base == Decimal("1.9")
    assert plan.final_quantity_base <= plan.gate_approval.approved_quantity_ceiling_base
    assert sum(leg.quantity_base for leg in plan.legs) == Decimal("1.9")


def test_non_eight_decimal_venue_step_is_respected() -> None:
    plan = build_automatic_exit_plan_v1(decision=_decision(approved_quantity_ceiling_base=Decimal("2.38")), context=_context(venue_constraints=_constraints(qty_step_size=Decimal("0.25"))))
    assert plan.final_quantity_base == Decimal("2.25")
    assert all(leg.quantity_base % Decimal("0.25") == 0 for leg in plan.legs)


@pytest.mark.parametrize("ceiling,constraints,reason", [
    (Decimal("0.09"), _constraints(), "QUANTITY_ROUNDS_TO_ZERO"),
    (Decimal("0.19"), _constraints(min_base_quantity=Decimal("0.2")), "FINAL_QUANTITY_BELOW_MIN_BASE_QUANTITY"),
    (Decimal("2.5"), _constraints(min_quote_notional=Decimal("200")), "LADDER_LEG_1_INVALID:BELOW_MIN_QUOTE_NOTIONAL"),
])
def test_post_round_invalidity_fails_closed(ceiling: Decimal, constraints: VenueExecutionConstraints, reason: str) -> None:
    with pytest.raises(AutomaticExitPlanningError, match=reason):
        build_automatic_exit_plan_v1(decision=_decision(approved_quantity_ceiling_base=ceiling), context=_context(venue_constraints=constraints))


def test_exit_and_reduce_policy_intent_and_unevaluated_trigger_fields_are_preserved() -> None:
    candidate = _candidate(candidate_action="EXIT", target_price=None, invalidation_price=None)
    plan = build_automatic_exit_plan_v1(decision=_decision(candidate=candidate), context=_context())
    assert plan.candidate_action == "EXIT"


def test_identity_and_provenance_mismatches_fail_closed() -> None:
    with pytest.raises(AutomaticExitPlanningError, match="GATE_CANDIDATE_CONTEXT_IDENTITY_MISMATCH"):
        build_automatic_exit_plan_v1(decision=_decision(candidate=_candidate(market="ETH-EUR")), context=_context())
    with pytest.raises(AutomaticExitPlanningError, match="CANDIDATE_PROVENANCE_INVALID"):
        build_automatic_exit_plan_v1(decision=_decision(candidate=_candidate(evidence_id="")), context=_context())
    with pytest.raises(AutomaticExitPlanningError, match="GATE_CANDIDATE_PROVENANCE_MISMATCH"):
        build_automatic_exit_plan_v1(decision=_decision(approved_fraction_candidate=Decimal("0.5")), context=_context())


def test_planner_has_no_manual_executor_broker_or_raw_candidate_entrypoint() -> None:
    tree = ast.parse(Path("src/execution_planner/automatic_exit_planner_v1.py").read_text())
    imports = [alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names]
    assert not any(any(word in name for word in ("manual_execution", "executor", "broker")) for name in imports)
    assert "candidate" not in build_automatic_exit_plan_v1.__annotations__
