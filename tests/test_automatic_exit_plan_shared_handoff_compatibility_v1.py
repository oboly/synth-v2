"""Issue #392 Phase 6 audit: plan-shape compatibility with the #206 shared handoff.

This module does NOT introduce a production adapter. `src/exit_policy` and
`src/execution_planner` still have no import of `src/executor`, and this file
proves nothing about the actual missing link -- it only proves that the
canonical Phase 3 `AutomaticExitPlanV1` output (`src/execution_planner/
automatic_exit_planner_v1.py`) already carries every field the canonical
side-neutral `ApprovedExecutionPlanV1` reference (`src/executor/
execution_plan_reference_v1.py`) requires, with no loss, no side-recomputation,
and a stable content hash, once a future adapter maps field-for-field.

That mapping is written here, in test scope only, purely to demonstrate
compatibility. It must not be imported by production code. Building the real
adapter/intake boundary described by Issue #392 Phase 6 is separate,
explicitly-authorized implementation work.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.automatic_exit_gate_v1 import STATE_APPROVED, AutomaticExitGateDecisionV1
from src.execution_planner.automatic_exit_planner_v1 import (
    AutomaticExitPlanningContextV1,
    AutomaticExitPlanV1,
    build_automatic_exit_plan_v1,
)
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1, ExecutionPlanLegV1
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


def _staging_map_plan_to_shared_reference(plan: AutomaticExitPlanV1) -> ApprovedExecutionPlanV1:
    """Test-only field mapping; not a production adapter (see module docstring)."""
    return ApprovedExecutionPlanV1(
        plan_source="automatic_exit_planner_v1",
        plan_reference_id=f"{plan.trading_account_id}:{plan.position_reference}:{plan.candidate_evidence_id}",
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        side=plan.side,
        legs=tuple(
            ExecutionPlanLegV1(leg.leg_index, leg.side, leg.limit_price, leg.quantity_base)
            for leg in plan.legs
        ),
    )


@pytest.mark.parametrize("action,target_price,invalidation_price", [
    ("REDUCE", Decimal("100"), Decimal("80")),
    ("EXIT", None, None),
])
def test_reduce_and_exit_plans_map_losslessly_onto_shared_plan_reference(
    action: str, target_price: Decimal | None, invalidation_price: Decimal | None,
) -> None:
    plan = build_automatic_exit_plan_v1(
        decision=_decision(candidate=_candidate(candidate_action=action, target_price=target_price, invalidation_price=invalidation_price)),
        context=_context(),
    )
    shared = _staging_map_plan_to_shared_reference(plan)

    assert shared.side == plan.side == "SELL"
    assert shared.trading_account_id == plan.trading_account_id
    assert shared.venue == plan.venue
    assert shared.market == plan.market
    assert len(shared.legs) == len(plan.legs)
    for shared_leg, planner_leg in zip(shared.legs, plan.legs):
        assert shared_leg.leg_index == planner_leg.leg_index
        assert shared_leg.side == planner_leg.side == "SELL"
        assert shared_leg.price == planner_leg.limit_price
        assert shared_leg.quantity == planner_leg.quantity_base
    assert sum(leg.quantity for leg in shared.legs) == plan.final_quantity_base


def test_shared_plan_reference_content_hash_is_stable_for_identical_planner_output() -> None:
    plan = build_automatic_exit_plan_v1(decision=_decision(), context=_context())
    first = _staging_map_plan_to_shared_reference(plan)
    second = _staging_map_plan_to_shared_reference(plan)
    assert first.content_hash == second.content_hash


def test_shared_plan_reference_content_hash_changes_with_leg_affecting_planner_fields(
) -> None:
    baseline_plan = build_automatic_exit_plan_v1(decision=_decision(), context=_context())
    baseline_hash = _staging_map_plan_to_shared_reference(baseline_plan).content_hash

    higher_reference_price = build_automatic_exit_plan_v1(
        decision=_decision(), context=_context(reference_price=Decimal("101.00")),
    )
    assert _staging_map_plan_to_shared_reference(higher_reference_price).content_hash != baseline_hash

    smaller_ceiling = build_automatic_exit_plan_v1(
        decision=_decision(approved_quantity_ceiling_base=Decimal("1.10")), context=_context(),
    )
    assert _staging_map_plan_to_shared_reference(smaller_ceiling).content_hash != baseline_hash


def test_reduce_vs_exit_provenance_is_not_carried_by_the_shared_content_hash() -> None:
    """`ApprovedExecutionPlanV1` is deliberately side-neutral order-mechanics
    identity only (account/venue/market/side/legs): it has no REDUCE/EXIT or
    evidence field. Two staged plans with identical resulting legs therefore
    hash identically regardless of `candidate_action`. REDUCE/EXIT and
    evidence provenance instead survive in `plan_reference_id`, which a real
    adapter must derive from evidence that differs per evaluation cycle (this
    test reuses one evidence id on purpose, to isolate this exact property).
    A future adapter must not rely on the shared content hash to distinguish
    REDUCE from EXIT.
    """
    reduce_plan = build_automatic_exit_plan_v1(decision=_decision(), context=_context())
    exit_plan = build_automatic_exit_plan_v1(
        decision=_decision(candidate=_candidate(candidate_action="EXIT", reduction_fraction_candidate=Decimal("1"), target_price=None, invalidation_price=None), approved_fraction_candidate=Decimal("1")),
        context=_context(),
    )
    assert reduce_plan.candidate_action != exit_plan.candidate_action
    assert (
        _staging_map_plan_to_shared_reference(reduce_plan).content_hash
        == _staging_map_plan_to_shared_reference(exit_plan).content_hash
    )
