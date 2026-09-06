"""Issue #753 Phase B3: pure planner tests.

Covers partial-target SELL sizing, invalidation exiting the full remainder,
exact strategy/trade lineage propagation into the plan, decision/binding
identity mismatch fail-closed, and non-actionable decision rejection. No DB,
no executor, no broker.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.decision_gate.fib_map_bound_exit_decision_v1 import (
    REASON_OK,
    STATE_NO_ACTION,
    STATE_PARTIAL_PROFIT_TARGET,
    STATE_PROTECTIVE_EXIT,
    FibMapBoundExitDecisionV1,
    FibMapBoundExitMarketEvidenceV1,
    FibMapBoundExitProgressionV1,
    evaluate_fib_map_bound_exit_decision_v1,
)
from src.decision_gate.fib_map_bound_trade_v1 import FibMapBoundTradeV1
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryPositionV1
from src.execution_planner.fib_map_bound_exit_planner_v1 import (
    FibMapBoundExitPlanningContextV1,
    FibMapBoundExitPlanningError,
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


def _decision_for(binding: FibMapBoundTradeV1, owned: StrategyOwnedInventoryPositionV1, price: Decimal) -> FibMapBoundExitDecisionV1:
    return evaluate_fib_map_bound_exit_decision_v1(
        binding=binding,
        owned_position=owned,
        progression=FibMapBoundExitProgressionV1(consumed_target_indices=frozenset()),
        market_evidence=FibMapBoundExitMarketEvidenceV1(current_price=price, price_observed_ts_utc=NOW),
        evaluation_ts_utc=NOW,
    )


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


# --- Partial profit target ------------------------------------------------


def test_partial_target_plans_exactly_the_decided_bounded_quantity() -> None:
    binding = _binding()
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("220"))
    assert decision.state == STATE_PARTIAL_PROFIT_TARGET
    assert decision.decision_quantity_base == Decimal("3")  # 9 / 3 targets

    plan = build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())
    assert plan.side == "SELL"
    assert plan.final_quantity_base == Decimal("3")
    assert plan.final_quantity_base < owned.owned_base_quantity
    assert len(plan.legs) == 1
    assert plan.legs[0].quantity_base == Decimal("3")
    assert plan.legs[0].limit_price >= decision.target_price


def test_partial_target_never_exceeds_decision_quantity_after_rounding() -> None:
    binding = _binding()
    owned = _owned(binding, owned_base_quantity=Decimal("9.03"), bought_base_quantity=Decimal("9.03"))
    decision = _decision_for(binding, owned, price=Decimal("220"))
    plan = build_fib_map_bound_exit_plan_v1(
        decision=decision, binding=binding, context=_context(venue_constraints=_constraints(qty_step_size=Decimal("0.1"))),
    )
    assert plan.final_quantity_base <= decision.decision_quantity_base


# --- Invalidation exits the full remainder --------------------------------


def test_invalidation_plans_the_full_remaining_owned_quantity() -> None:
    binding = _binding()
    owned = _owned(binding, owned_base_quantity=Decimal("6.4"), bought_base_quantity=Decimal("9"))
    decision = _decision_for(binding, owned, price=Decimal("90"))
    assert decision.state == STATE_PROTECTIVE_EXIT
    assert decision.decision_quantity_base == owned.owned_base_quantity

    plan = build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())
    assert plan.final_quantity_base == Decimal("6.4")
    assert plan.decision_state == STATE_PROTECTIVE_EXIT


# --- Lineage propagation ---------------------------------------------------


def test_exact_strategy_trade_lineage_survives_into_the_plan() -> None:
    binding = _binding(strategy_bucket_id="BUCKET_X", strategy_id="strat_x", strategy_version="7", trade_id="trade-99")
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("220"))
    plan = build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())
    assert plan.trading_account_id == binding.trading_account_id
    assert plan.venue == binding.venue
    assert plan.market == binding.market
    assert plan.strategy_bucket_id == "BUCKET_X"
    assert plan.strategy_id == "strat_x"
    assert plan.strategy_version == "7"
    assert plan.trade_id == "trade-99"
    assert plan.binding_id == binding.binding_id
    assert plan.decision_id == decision.decision_id


# --- Mismatch fail-closed ---------------------------------------------------


def test_decision_binding_identity_mismatch_fails_closed() -> None:
    binding = _binding()
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("220"))
    other_binding = _binding(binding_id="bind-2", trade_id="trade-2")
    with pytest.raises(FibMapBoundExitPlanningError, match="DECISION_BINDING_IDENTITY_MISMATCH"):
        build_fib_map_bound_exit_plan_v1(decision=decision, binding=other_binding, context=_context())


def test_non_actionable_decision_states_are_rejected() -> None:
    binding = _binding()
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("150"))  # above invalidation, below every target
    assert decision.state == STATE_NO_ACTION
    with pytest.raises(FibMapBoundExitPlanningError, match="DECISION_NOT_ACTIONABLE"):
        build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())


def test_fail_closed_decision_is_rejected() -> None:
    binding = _binding()
    fail_closed = FibMapBoundExitDecisionV1(
        decision_id="bind-1:FAIL_CLOSED:X", state="FAIL_CLOSED", reason_code="X",
        binding_id=binding.binding_id, trade_id=binding.trade_id, target_index=None,
        target_price=None, decision_quantity_base=None, remaining_owned_after_base=None,
    )
    with pytest.raises(FibMapBoundExitPlanningError, match="DECISION_NOT_ACTIONABLE"):
        build_fib_map_bound_exit_plan_v1(decision=fail_closed, binding=binding, context=_context())


def test_invalid_binding_fails_closed() -> None:
    binding = _binding()
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("220"))
    from dataclasses import replace

    bad_binding = replace(binding, invalidation_price=Decimal("-1"))
    with pytest.raises(FibMapBoundExitPlanningError, match="BINDING_INVALID"):
        build_fib_map_bound_exit_plan_v1(decision=decision, binding=bad_binding, context=_context())


# --- Venue constraints freshness / capability guardrails --------------------


def test_stale_venue_constraints_fail_closed() -> None:
    binding = _binding()
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("220"))
    with pytest.raises(FibMapBoundExitPlanningError, match="VENUE_CONSTRAINTS_TIMESTAMP_STALE_OR_FUTURE"):
        build_fib_map_bound_exit_plan_v1(
            decision=decision, binding=binding,
            context=_context(venue_constraints=_constraints(metadata_synced_ts_utc=NOW - timedelta(days=30))),
        )


def test_wrong_venue_market_constraints_fail_closed() -> None:
    binding = _binding()
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("220"))
    with pytest.raises(FibMapBoundExitPlanningError, match="VENUE_CONSTRAINTS_IDENTITY_MISMATCH"):
        build_fib_map_bound_exit_plan_v1(
            decision=decision, binding=binding,
            context=_context(venue_constraints=_constraints(market="ETH-EUR")),
        )


# --- Determinism -------------------------------------------------------------


def test_plan_is_deterministic_for_identical_inputs() -> None:
    binding = _binding()
    owned = _owned(binding)
    decision = _decision_for(binding, owned, price=Decimal("220"))
    plan_a = build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())
    plan_b = build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())
    assert plan_a == plan_b
