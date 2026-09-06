from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.decision_gate.fib_map_bound_exit_decision_v1 import (
    REASON_ALL_TARGETS_CONSUMED,
    REASON_INVALID_BINDING,
    REASON_INVALID_PRICE_EVIDENCE,
    REASON_MISSING_BINDING,
    REASON_NO_REMAINING_QUANTITY,
    REASON_NO_TARGET_CROSSED,
    REASON_OK,
    REASON_OWNERSHIP_MISMATCH,
    STATE_FAIL_CLOSED,
    STATE_NO_ACTION,
    STATE_PARTIAL_PROFIT_TARGET,
    STATE_PROTECTIVE_EXIT,
    FibMapBoundExitMarketEvidenceV1,
    FibMapBoundExitProgressionV1,
    evaluate_fib_map_bound_exit_decision_v1,
)
from src.decision_gate.fib_map_bound_trade_v1 import FibMapBoundTradeV1
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryPositionV1

NOW = datetime(2026, 9, 6, 9, 45, tzinfo=UTC)


def _binding(**changes):
    values = dict(
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
    return FibMapBoundTradeV1(**values)


def _owned(binding: FibMapBoundTradeV1, **changes):
    values = dict(
        trading_account_id=binding.trading_account_id, venue=binding.venue,
        market=binding.market, strategy_bucket_id=binding.strategy_bucket_id,
        strategy_id=binding.strategy_id, strategy_version=binding.strategy_version,
        trade_id=binding.trade_id, owned_base_quantity=Decimal("9"),
        bought_base_quantity=Decimal("9"), sold_base_quantity=Decimal("0"),
        cost_notional_eur=None,
    )
    values.update(changes)
    return StrategyOwnedInventoryPositionV1(**values)


def _evidence(price: Decimal, ts: datetime = NOW) -> FibMapBoundExitMarketEvidenceV1:
    return FibMapBoundExitMarketEvidenceV1(current_price=price, price_observed_ts_utc=ts)


def _progression(*consumed: int) -> FibMapBoundExitProgressionV1:
    return FibMapBoundExitProgressionV1(consumed_target_indices=frozenset(consumed))


def _evaluate(binding, owned, progression, price, evaluation_ts_utc=NOW):
    return evaluate_fib_map_bound_exit_decision_v1(
        binding=binding,
        owned_position=owned,
        progression=progression,
        market_evidence=_evidence(price),
        evaluation_ts_utc=evaluation_ts_utc,
    )


def test_target1_crossed_yields_partial_profit_target():
    binding = _binding()
    owned = _owned(binding)
    decision = _evaluate(binding, owned, _progression(), Decimal("225"))
    assert decision.state == STATE_PARTIAL_PROFIT_TARGET
    assert decision.reason_code == REASON_OK
    assert decision.target_index == 0
    assert decision.target_price == Decimal("220")
    assert decision.decision_quantity_base == Decimal("3")
    assert decision.remaining_owned_after_base == Decimal("6")


def test_later_target_progression_after_target1_consumed():
    binding = _binding()
    owned = _owned(binding, owned_base_quantity=Decimal("6"))
    decision = _evaluate(binding, owned, _progression(0), Decimal("245"))
    assert decision.state == STATE_PARTIAL_PROFIT_TARGET
    assert decision.target_index == 1
    assert decision.target_price == Decimal("240")
    assert decision.decision_quantity_base == Decimal("3")
    assert decision.remaining_owned_after_base == Decimal("3")


def test_invalidation_overrides_unconsumed_future_target():
    binding = _binding()
    owned = _owned(binding)
    decision = _evaluate(binding, owned, _progression(), Decimal("90"))
    assert decision.state == STATE_PROTECTIVE_EXIT
    assert decision.reason_code == REASON_OK
    assert decision.target_index is None
    assert decision.target_price == binding.invalidation_price
    assert decision.decision_quantity_base == owned.owned_base_quantity
    assert decision.remaining_owned_after_base == Decimal("0")


def test_partial_target_then_invalidation_consumes_exact_remainder():
    binding = _binding()
    remaining = Decimal("6")
    owned = _owned(binding, owned_base_quantity=remaining)
    decision = _evaluate(binding, owned, _progression(0), Decimal("50"))
    assert decision.state == STATE_PROTECTIVE_EXIT
    assert decision.decision_quantity_base == remaining
    assert decision.remaining_owned_after_base == Decimal("0")


def test_same_market_two_lineages_are_evaluated_independently():
    binding_a = _binding(trade_id="trade-a", binding_id="bind-a")
    binding_b = _binding(trade_id="trade-b", binding_id="bind-b", invalidation_price=Decimal("150"))
    owned_a = _owned(binding_a)
    owned_b = _owned(binding_b)

    decision_a = _evaluate(binding_a, owned_a, _progression(), Decimal("225"))
    decision_b = _evaluate(binding_b, owned_b, _progression(), Decimal("140"))

    assert decision_a.state == STATE_PARTIAL_PROFIT_TARGET
    assert decision_a.trade_id == "trade-a"
    assert decision_b.state == STATE_PROTECTIVE_EXIT
    assert decision_b.trade_id == "trade-b"


def test_new_map_binding_does_not_mutate_old_bound_trade_decision():
    old_binding = _binding()
    old_owned = _owned(old_binding)
    old_decision = _evaluate(old_binding, old_owned, _progression(), Decimal("225"))

    new_binding = _binding(
        binding_id="bind-2", native_map_id="native-map-8", map_cycle_id="cycle-8",
        map_structure_hash="def456", target_levels=(Decimal("300"), Decimal("320")),
    )
    # Re-evaluating the exact same old binding instance after a newer map
    # exists elsewhere must reproduce the identical decision.
    replay_decision = _evaluate(old_binding, old_owned, _progression(), Decimal("225"))
    assert replay_decision == old_decision
    assert new_binding.binding_id != old_binding.binding_id


def test_zero_remaining_quantity_yields_no_action():
    binding = _binding()
    owned = _owned(binding, owned_base_quantity=Decimal("0"))
    decision = _evaluate(binding, owned, _progression(), Decimal("225"))
    assert decision.state == STATE_NO_ACTION
    assert decision.reason_code == REASON_NO_REMAINING_QUANTITY
    assert decision.remaining_owned_after_base == Decimal("0")


def test_missing_binding_fails_closed():
    owned = _owned(_binding())
    decision = evaluate_fib_map_bound_exit_decision_v1(
        binding=None, owned_position=owned, progression=_progression(),
        market_evidence=_evidence(Decimal("225")), evaluation_ts_utc=NOW,
    )
    assert decision.state == STATE_FAIL_CLOSED
    assert decision.reason_code == REASON_MISSING_BINDING


def test_invalid_binding_fails_closed():
    binding = _binding(target_levels=())
    owned = _owned(binding)
    decision = _evaluate(binding, owned, _progression(), Decimal("225"))
    assert decision.state == STATE_FAIL_CLOSED
    assert decision.reason_code == REASON_INVALID_BINDING


def test_conflicting_price_evidence_fails_closed():
    binding = _binding()
    owned = _owned(binding)
    decision = evaluate_fib_map_bound_exit_decision_v1(
        binding=binding, owned_position=owned, progression=_progression(),
        market_evidence=_evidence(Decimal("-1")), evaluation_ts_utc=NOW,
    )
    assert decision.state == STATE_FAIL_CLOSED
    assert decision.reason_code == REASON_INVALID_PRICE_EVIDENCE


def test_ownership_mismatch_fails_closed():
    binding = _binding()
    owned = _owned(binding, trade_id="different-trade")
    decision = _evaluate(binding, owned, _progression(), Decimal("225"))
    assert decision.state == STATE_FAIL_CLOSED
    assert decision.reason_code == REASON_OWNERSHIP_MISMATCH


def test_over_quantity_ownership_state_fails_closed():
    binding = _binding()
    owned = _owned(binding, owned_base_quantity=Decimal("50"), bought_base_quantity=Decimal("9"))
    decision = _evaluate(binding, owned, _progression(), Decimal("225"))
    assert decision.state == STATE_FAIL_CLOSED


def test_all_targets_consumed_yields_no_action():
    binding = _binding()
    owned = _owned(binding, owned_base_quantity=Decimal("0.5"))
    decision = _evaluate(binding, owned, _progression(0, 1, 2), Decimal("400"))
    assert decision.state == STATE_NO_ACTION
    assert decision.reason_code == REASON_ALL_TARGETS_CONSUMED


def test_price_below_next_target_yields_no_action():
    binding = _binding()
    owned = _owned(binding)
    decision = _evaluate(binding, owned, _progression(), Decimal("150"))
    assert decision.state == STATE_NO_ACTION
    assert decision.reason_code == REASON_NO_TARGET_CROSSED


def test_duplicate_inputs_produce_identical_deterministic_decision_id():
    binding = _binding()
    owned = _owned(binding)
    first = _evaluate(binding, owned, _progression(), Decimal("225"))
    second = _evaluate(binding, owned, _progression(), Decimal("225"))
    assert first == second
    assert first.decision_id == second.decision_id
