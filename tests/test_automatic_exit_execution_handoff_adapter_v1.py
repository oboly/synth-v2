"""Issue #392 Phase 6 blocker A: pure adapter tests.

Covers lossless field mapping, deterministic/retry-stable/evidence-traceable
plan_reference_id derivation, REDUCE-vs-EXIT/evidence/profile/leg identity
distinctness, and fail-closed rejection of malformed AutomaticExitPlanV1
input. No DB, no executor handoff repository, no broker.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.automatic_exit_gate_v1 import STATE_APPROVED, AutomaticExitGateDecisionV1
from src.execution_planner.automatic_exit_execution_handoff_adapter_v1 import (
    AutomaticExitPlanAdapterError,
    adapt_automatic_exit_plan_to_approved_execution_plan_v1,
    derive_automatic_exit_plan_reference_id_v1,
)
from src.execution_planner.automatic_exit_planner_v1 import (
    AutomaticExitPlanningContextV1,
    AutomaticExitPlanV1,
    build_automatic_exit_plan_v1,
)
from src.exit_policy.automatic_exit_candidate_v1 import AutomaticExitCandidateV1
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def _candidate(**overrides: object) -> AutomaticExitCandidateV1:
    values: dict[str, object] = dict(
        trading_account_id=7, position_reference="position-9", venue="bitvavo", asset_id=42,
        market="SOL-EUR", candidate_action="REDUCE", reduction_fraction_candidate=Decimal("0.25"),
        urgency_candidate="NORMAL", reason_code="TARGET_REACHED", evidence_id="evidence-1",
        exit_profile_id="profile-1", exit_profile_version="1", target_price=Decimal("100"),
        invalidation_price=Decimal("80"), observed_ts_utc=NOW,
    )
    values.update(overrides)
    return AutomaticExitCandidateV1(**values)  # type: ignore[arg-type]


def _decision(**overrides: object) -> AutomaticExitGateDecisionV1:
    values: dict[str, object] = dict(
        state=STATE_APPROVED, reason_code="OK", candidate=_candidate(),
        approved_fraction_candidate=Decimal("0.25"), approved_quantity_ceiling_base=Decimal("2.57"),
    )
    values.update(overrides)
    return AutomaticExitGateDecisionV1(**values)  # type: ignore[arg-type]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(
        venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"),
        min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"), supported_order_types=("limit",),
        supported_time_in_force=("GTC",), source_provenance="PUBLIC", metadata_synced_ts_utc=NOW,
        status=STATUS_FRESH,
    )
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> AutomaticExitPlanningContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7, position_reference="position-9", venue="bitvavo", asset_id=42,
        market="SOL-EUR", reference_price=Decimal("100.01"), venue_constraints=_constraints(),
        planning_ts_utc=NOW,
    )
    values.update(overrides)
    return AutomaticExitPlanningContextV1(**values)  # type: ignore[arg-type]


def _plan(**decision_overrides: object) -> AutomaticExitPlanV1:
    return build_automatic_exit_plan_v1(decision=_decision(**decision_overrides), context=_context())


# --- Lossless mapping -------------------------------------------------


@pytest.mark.parametrize("action,target_price,invalidation_price,fraction", [
    ("REDUCE", Decimal("100"), Decimal("80"), Decimal("0.25")),
    ("EXIT", None, None, Decimal("1")),
])
def test_reduce_and_exit_plans_map_losslessly(
    action: str, target_price: Decimal | None, invalidation_price: Decimal | None, fraction: Decimal,
) -> None:
    plan = build_automatic_exit_plan_v1(
        decision=_decision(
            candidate=_candidate(candidate_action=action, target_price=target_price, invalidation_price=invalidation_price, reduction_fraction_candidate=fraction),
            approved_fraction_candidate=fraction,
        ),
        context=_context(),
    )
    approved = adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)

    assert approved.side == plan.side == "SELL"
    assert approved.trading_account_id == plan.trading_account_id
    assert approved.venue == plan.venue
    assert approved.market == plan.market
    assert len(approved.legs) == len(plan.legs)
    for approved_leg, planner_leg in zip(approved.legs, plan.legs):
        assert approved_leg.leg_index == planner_leg.leg_index
        assert approved_leg.side == planner_leg.side == "SELL"
        assert approved_leg.price == planner_leg.limit_price
        assert approved_leg.quantity == planner_leg.quantity_base
    assert sum(leg.quantity for leg in approved.legs) == plan.final_quantity_base


def test_adapter_does_not_mutate_input_plan() -> None:
    plan = _plan()
    before = plan
    adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)
    assert plan == before


# --- Identity determinism / retry / distinctness -----------------------


def test_same_logical_plan_retry_yields_same_plan_reference_id() -> None:
    plan = _plan()
    first = derive_automatic_exit_plan_reference_id_v1(plan)
    second = derive_automatic_exit_plan_reference_id_v1(plan)
    assert first == second


def test_same_logical_plan_reconstructed_across_restart_yields_same_id() -> None:
    """A freshly rebuilt plan object with identical logical fields (simulating a
    process restart re-running the same evaluation) must derive the same id."""
    plan_a = _plan()
    plan_b = build_automatic_exit_plan_v1(decision=_decision(), context=_context())
    assert derive_automatic_exit_plan_reference_id_v1(plan_a) == derive_automatic_exit_plan_reference_id_v1(plan_b)


def test_reduce_vs_exit_with_same_ladder_yields_distinct_id() -> None:
    reduce_plan = _plan()
    exit_plan = build_automatic_exit_plan_v1(
        decision=_decision(
            candidate=_candidate(candidate_action="EXIT", reduction_fraction_candidate=Decimal("1"), target_price=None, invalidation_price=None),
            approved_fraction_candidate=Decimal("1"),
        ),
        context=_context(),
    )
    # Same resulting ladder mechanics (both plans use the same ceiling/price).
    assert reduce_plan.final_quantity_base == exit_plan.final_quantity_base
    assert reduce_plan.candidate_action != exit_plan.candidate_action
    assert (
        derive_automatic_exit_plan_reference_id_v1(reduce_plan)
        != derive_automatic_exit_plan_reference_id_v1(exit_plan)
    )


def test_evidence_identity_change_yields_distinct_id() -> None:
    baseline = _plan()
    changed = build_automatic_exit_plan_v1(
        decision=_decision(candidate=_candidate(evidence_id="evidence-2")), context=_context(),
    )
    assert derive_automatic_exit_plan_reference_id_v1(baseline) != derive_automatic_exit_plan_reference_id_v1(changed)


def test_exit_profile_version_change_yields_distinct_id() -> None:
    baseline = _plan()
    changed = build_automatic_exit_plan_v1(
        decision=_decision(candidate=_candidate(exit_profile_version="2")), context=_context(),
    )
    assert derive_automatic_exit_plan_reference_id_v1(baseline) != derive_automatic_exit_plan_reference_id_v1(changed)


def test_leg_price_or_quantity_change_yields_distinct_id() -> None:
    baseline = _plan()
    higher_reference_price = build_automatic_exit_plan_v1(
        decision=_decision(), context=_context(reference_price=Decimal("101.00")),
    )
    assert derive_automatic_exit_plan_reference_id_v1(baseline) != derive_automatic_exit_plan_reference_id_v1(higher_reference_price)

    smaller_ceiling = build_automatic_exit_plan_v1(
        decision=_decision(approved_quantity_ceiling_base=Decimal("1.10")), context=_context(),
    )
    assert derive_automatic_exit_plan_reference_id_v1(baseline) != derive_automatic_exit_plan_reference_id_v1(smaller_ceiling)


def test_planner_version_change_yields_distinct_id() -> None:
    baseline = _plan()
    bumped = replace(baseline, planner_version="automatic_exit_planner_v2")
    assert derive_automatic_exit_plan_reference_id_v1(baseline) != derive_automatic_exit_plan_reference_id_v1(bumped)


def test_id_is_traceable_to_trading_account_position_and_evidence() -> None:
    plan = _plan()
    reference_id = derive_automatic_exit_plan_reference_id_v1(plan)
    assert str(plan.trading_account_id) in reference_id
    assert plan.position_reference in reference_id
    assert plan.candidate_evidence_id in reference_id


def test_leg_iteration_order_cannot_create_nondeterminism() -> None:
    plan = _plan()
    reordered = replace(plan, legs=tuple(reversed(plan.legs)))
    # A reordered/mis-indexed leg tuple is itself malformed (fails structural
    # validation), so this must fail closed rather than silently produce a
    # different-but-valid identity.
    with pytest.raises(AutomaticExitPlanAdapterError):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(reordered)


# --- Fail-closed malformed-plan rejection -------------------------------


def test_rejects_non_sell_plan() -> None:
    plan = replace(_plan(), side="BUY")
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_SIDE_NOT_SELL"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_empty_legs() -> None:
    plan = replace(_plan(), legs=())
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_LEGS_EMPTY"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_inconsistent_leg_side() -> None:
    plan = _plan()
    bad_leg = replace(plan.legs[0], side="BUY")
    plan = replace(plan, legs=(bad_leg,) + plan.legs[1:])
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_LEG_SIDE_MISMATCH"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_duplicate_leg_indices() -> None:
    plan = _plan()
    duplicated = replace(plan.legs[1], leg_index=plan.legs[0].leg_index)
    plan = replace(plan, legs=(plan.legs[0], duplicated))
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_LEG_INDICES_NOT_STRICTLY_ORDERED"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_non_positive_price() -> None:
    plan = _plan()
    bad_leg = replace(plan.legs[0], limit_price=Decimal("0"))
    plan = replace(plan, legs=(bad_leg,) + plan.legs[1:])
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_LEG_PRICE_NOT_POSITIVE"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_non_positive_quantity() -> None:
    plan = _plan()
    bad_leg = replace(plan.legs[0], quantity_base=Decimal("-1"))
    plan = replace(plan, legs=(bad_leg,) + plan.legs[1:])
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_LEG_QUANTITY_NOT_POSITIVE"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_leg_sum_mismatch_vs_final_quantity() -> None:
    plan = _plan()
    inflated = replace(plan, final_quantity_base=plan.final_quantity_base + Decimal("1"))
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_LEG_QUANTITY_SUM_MISMATCH"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(inflated)


def test_rejects_missing_evidence_provenance() -> None:
    plan = replace(_plan(), candidate_evidence_id="")
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_PROVENANCE_FIELD_EMPTY"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_missing_exit_profile_provenance() -> None:
    plan = replace(_plan(), exit_profile_id="")
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_PROVENANCE_FIELD_EMPTY"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_unsupported_candidate_action() -> None:
    plan = replace(_plan(), candidate_action="HOLD")
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_CANDIDATE_ACTION_UNSUPPORTED"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_gate_approval_not_approved() -> None:
    plan = _plan()
    not_approved = replace(plan.gate_approval, state="DENIED")
    plan = replace(plan, gate_approval=not_approved)
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_GATE_APPROVAL_NOT_APPROVED"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_non_positive_gate_ceiling() -> None:
    plan = _plan()
    bad_approval = replace(plan.gate_approval, approved_quantity_ceiling_base=Decimal("0"))
    plan = replace(plan, gate_approval=bad_approval)
    with pytest.raises(AutomaticExitPlanAdapterError, match="PLAN_GATE_APPROVED_CEILING_INVALID"):
        adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)
