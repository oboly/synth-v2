"""Issue #753 Phase B3: pure adapter tests.

Covers lossless field mapping, deterministic/retry-stable plan_reference_id
derivation, distinct ids across different strategy/trade lineages (no
cross-strategy quantity/identity bleed), and fail-closed rejection of
malformed FibMapBoundExitPlanV1 input. No DB, no executor handoff
repository, no broker.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.decision_gate.fib_map_bound_exit_decision_v1 import (
    FibMapBoundExitMarketEvidenceV1,
    FibMapBoundExitProgressionV1,
    evaluate_fib_map_bound_exit_decision_v1,
)
from src.decision_gate.fib_map_bound_trade_v1 import FibMapBoundTradeV1
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryPositionV1
from src.execution_planner.fib_map_bound_exit_execution_handoff_adapter_v1 import (
    FibMapBoundExitPlanAdapterError,
    adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1,
    derive_fib_map_bound_exit_plan_reference_id_v1,
)
from src.execution_planner.fib_map_bound_exit_planner_v1 import (
    FibMapBoundExitPlanningContextV1,
    build_fib_map_bound_exit_plan_v1,
)
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints

NOW = datetime(2026, 9, 6, 9, 45, tzinfo=UTC)


def _binding(**changes: object) -> FibMapBoundTradeV1:
    values: dict[str, object] = dict(
        binding_id="bind-1", trading_account_id=1, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="shorttf_fib",
        strategy_version="1", trade_id="trade-1", source_execution_plan_id="plan-1",
        source_buy_fill_id="fill-1", native_map_id="native-map-7", map_cycle_id="cycle-7",
        map_structure_hash="abc123", map_source_name="native_short_fib_context_snapshot_v1",
        map_source_version="0.1", map_asof_ts_utc=NOW, map_published_at_utc=NOW,
        anchor_start_ts_utc=NOW, anchor_end_ts_utc=NOW,
        anchor_low_price=Decimal("100"), anchor_high_price=Decimal("200"),
        breakout_gate_price=Decimal("210"), invalidation_price=Decimal("95"),
        target_levels=(Decimal("220"), Decimal("240"), Decimal("260")),
        target_ladder_semantics_version="FIB_MAP_BOUND_V1",
        bound_ts_utc=NOW,
    )
    values.update(changes)
    return FibMapBoundTradeV1(**values)  # type: ignore[arg-type]


def _owned(binding: FibMapBoundTradeV1, **changes: object) -> StrategyOwnedInventoryPositionV1:
    values: dict[str, object] = dict(
        trading_account_id=binding.trading_account_id, venue=binding.venue,
        market=binding.market, strategy_bucket_id=binding.strategy_bucket_id,
        strategy_id=binding.strategy_id, strategy_version=binding.strategy_version,
        trade_id=binding.trade_id, owned_base_quantity=Decimal("9"),
        bought_base_quantity=Decimal("9"), sold_base_quantity=Decimal("0"),
        cost_notional_eur=None,
    )
    values.update(changes)
    return StrategyOwnedInventoryPositionV1(**values)  # type: ignore[arg-type]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(
        venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"),
        min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"), supported_order_types=("limit",),
        supported_time_in_force=("GTC",), source_provenance="PUBLIC", metadata_synced_ts_utc=NOW,
        status=STATUS_FRESH,
    )
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> FibMapBoundExitPlanningContextV1:
    values: dict[str, object] = dict(venue_constraints=_constraints(), planning_ts_utc=NOW)
    values.update(overrides)
    return FibMapBoundExitPlanningContextV1(**values)  # type: ignore[arg-type]


def _plan(binding=None, price: Decimal = Decimal("220")):
    binding = binding or _binding()
    owned = _owned(binding)
    decision = evaluate_fib_map_bound_exit_decision_v1(
        binding=binding, owned_position=owned,
        progression=FibMapBoundExitProgressionV1(consumed_target_indices=frozenset()),
        market_evidence=FibMapBoundExitMarketEvidenceV1(current_price=price, price_observed_ts_utc=NOW),
        evaluation_ts_utc=NOW,
    )
    return build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())


# --- Lossless mapping -------------------------------------------------


def test_plan_maps_losslessly_to_approved_execution_plan() -> None:
    plan = _plan()
    approved = adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)
    assert approved.side == plan.side == "SELL"
    assert approved.trading_account_id == plan.trading_account_id
    assert approved.venue == plan.venue
    assert approved.market == plan.market
    assert len(approved.legs) == 1
    leg, approved_leg = plan.legs[0], approved.legs[0]
    assert approved_leg.leg_index == leg.leg_index
    assert approved_leg.side == leg.side == "SELL"
    assert approved_leg.price == leg.limit_price
    assert approved_leg.quantity == leg.quantity_base


def test_adapter_does_not_mutate_input_plan() -> None:
    plan = _plan()
    before = plan
    adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)
    assert plan == before


# --- Identity determinism / replay / distinctness -----------------------


def test_same_logical_plan_retry_yields_same_plan_reference_id() -> None:
    plan = _plan()
    assert derive_fib_map_bound_exit_plan_reference_id_v1(plan) == derive_fib_map_bound_exit_plan_reference_id_v1(plan)


def test_same_decision_reconstructed_across_restart_yields_same_id() -> None:
    """A freshly rebuilt plan from the exact same decision/binding (simulating a
    process restart re-running the same evaluation) must derive the same id --
    duplicate evaluation must never create a distinct executable plan."""
    plan_a = _plan()
    plan_b = _plan()
    assert derive_fib_map_bound_exit_plan_reference_id_v1(plan_a) == derive_fib_map_bound_exit_plan_reference_id_v1(plan_b)


def test_different_trade_lineage_yields_distinct_id_even_with_identical_ladder_mechanics() -> None:
    plan_trade_1 = _plan(binding=_binding(trade_id="trade-1"))
    plan_trade_2 = _plan(binding=_binding(trade_id="trade-2", binding_id="bind-2"))
    assert plan_trade_1.final_quantity_base == plan_trade_2.final_quantity_base
    assert (
        derive_fib_map_bound_exit_plan_reference_id_v1(plan_trade_1)
        != derive_fib_map_bound_exit_plan_reference_id_v1(plan_trade_2)
    )


def test_different_strategy_id_yields_distinct_id_no_cross_strategy_collision() -> None:
    plan_a = _plan(binding=_binding(strategy_id="strategy_a"))
    plan_b = _plan(binding=_binding(strategy_id="strategy_b"))
    assert (
        derive_fib_map_bound_exit_plan_reference_id_v1(plan_a)
        != derive_fib_map_bound_exit_plan_reference_id_v1(plan_b)
    )


def test_id_is_sensitive_to_trading_account_trade_and_decision_identity() -> None:
    plan = _plan()
    reference_id = derive_fib_map_bound_exit_plan_reference_id_v1(plan)
    assert derive_fib_map_bound_exit_plan_reference_id_v1(
        replace(plan, trading_account_id=plan.trading_account_id + 1)
    ) != reference_id
    assert derive_fib_map_bound_exit_plan_reference_id_v1(
        replace(plan, trade_id=plan.trade_id + "-other")
    ) != reference_id
    assert derive_fib_map_bound_exit_plan_reference_id_v1(
        replace(plan, decision_id=plan.decision_id + "-other")
    ) != reference_id


# --- Fail-closed malformed-plan rejection -------------------------------


def test_rejects_non_sell_plan() -> None:
    plan = replace(_plan(), side="BUY")
    with pytest.raises(FibMapBoundExitPlanAdapterError, match="PLAN_SIDE_NOT_SELL"):
        adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_empty_legs() -> None:
    plan = replace(_plan(), legs=())
    with pytest.raises(FibMapBoundExitPlanAdapterError, match="PLAN_LEGS_EMPTY"):
        adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_more_than_one_leg() -> None:
    plan = _plan()
    plan = replace(plan, legs=(plan.legs[0], replace(plan.legs[0], leg_index=2)))
    with pytest.raises(FibMapBoundExitPlanAdapterError, match="PLAN_LEGS_NOT_SINGLE_LEG"):
        adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_non_positive_price() -> None:
    plan = _plan()
    bad_leg = replace(plan.legs[0], limit_price=Decimal("0"))
    plan = replace(plan, legs=(bad_leg,))
    with pytest.raises(FibMapBoundExitPlanAdapterError, match="PLAN_LEG_PRICE_NOT_POSITIVE"):
        adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)


def test_rejects_leg_sum_mismatch_vs_final_quantity() -> None:
    plan = _plan()
    inflated = replace(plan, final_quantity_base=plan.final_quantity_base + Decimal("1"))
    with pytest.raises(FibMapBoundExitPlanAdapterError, match="PLAN_LEG_QUANTITY_SUM_MISMATCH"):
        adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(inflated)


def test_rejects_missing_lineage_identity() -> None:
    plan = replace(_plan(), trade_id="")
    with pytest.raises(FibMapBoundExitPlanAdapterError, match="PLAN_IDENTITY_FIELD_EMPTY"):
        adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)


def test_plan_reference_id_is_bounded_for_persistence_contract() -> None:
    binding = _binding(
        trade_id="trade-" + ("x" * 512),
        binding_id="binding-" + ("b" * 512),
    )
    plan = _plan(binding=binding)
    reference_id = derive_fib_map_bound_exit_plan_reference_id_v1(plan)
    assert reference_id.startswith("fib_map_bound_exit_v1:")
    assert len(reference_id) <= 128
    assert reference_id == derive_fib_map_bound_exit_plan_reference_id_v1(plan)
