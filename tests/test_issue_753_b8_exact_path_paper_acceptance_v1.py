"""Issue #753 B8 exact-path PAPER acceptance matrix.

Acceptance-only composition of reviewed production seams. No fixture mutates a
leg directly to FILLED and no wallet/broker balance is used as SELL authority.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from src.decision_gate.automatic_buy_gate_v1 import (
    STATE_APPROVED,
    evaluate_automatic_buy_candidate_permission_v1,
)
from src.decision_gate.fib_map_bound_exit_decision_v1 import (
    REASON_MISSING_BINDING,
    REASON_OWNERSHIP_MISMATCH,
    STATE_FAIL_CLOSED,
    STATE_PARTIAL_PROFIT_TARGET,
    STATE_PROTECTIVE_EXIT,
    FibMapBoundExitMarketEvidenceV1,
    FibMapBoundExitProgressionV1,
    evaluate_fib_map_bound_exit_decision_v1,
)
from src.decision_gate.fib_map_bound_trade_first_fill_binding_adapter_v1 import (
    CanonicalFibMapEvidenceV1,
    FibMapBoundTradeBindingAdapterError,
    bind_fib_map_bound_trade_on_first_fill_v1,
    build_fib_map_bound_trade_v1_from_first_fill,
    verify_first_buy_fill_v1,
)
from src.decision_gate.fib_map_bound_trade_repository_v1 import (
    FibMapBoundTradeConflictError,
    FibMapBoundTradeRepositoryV1,
)
from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    append_strategy_owned_inventory_event_v1,
    load_strategy_owned_inventory_events_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import project_strategy_owned_inventory_v1
from src.entry_policy.automatic_buy_candidate_v1 import (
    AutomaticBuySetupContextV1,
    evaluate_automatic_buy_candidate_v1,
)
from src.execution_planner.automatic_buy_planner_v1 import build_automatic_buy_plan_v1
from src.execution_planner.fib_map_bound_exit_execution_handoff_application_v1 import (
    submit_fib_map_bound_exit_plan_to_execution_handoff_v1,
)
from src.execution_planner.fib_map_bound_exit_planner_v1 import (
    FibMapBoundExitPlanningContextV1,
    build_fib_map_bound_exit_plan_v1,
)
from src.executor.execution_handoff_v1 import RUNTIME_MODE_PAPER
from src.executor.paper_order_adapter_v1 import PaperMarketQuoteV1
from src.orchestration.fib_map_bound_exit_paper_fill_execution_v1 import (
    submit_and_reconcile_fib_map_bound_exit_paper_plan_v1,
)
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection
from tests.test_automatic_buy_paper_fill_execution_v1 import (
    MemoryHandoffRepository,
    MemoryLegRepository,
    MemoryPlacementRepository,
    FixedQuoteProvider,
    _handoff as automatic_buy_handoff,
    _run as run_automatic_buy_paper,
)
from tests.test_automatic_buy_plan_handoff_identity_v1 import (
    NOW,
    _context as automatic_buy_gate_context,
    _planning_context as automatic_buy_planning_context,
)
from tests.test_fib_map_bound_exit_execution_handoff_application_v1 import (
    MemoryDatabase as ExitHandoffMemoryDatabase,
    _repository as exit_handoff_repository,
)
from tests.test_fib_map_bound_trade_first_fill_binding_adapter_v1 import (
    MemoryDatabase as FibBindingMemoryDatabase,
)

ACCOUNT_ID = 7
MARKET = "SOL-EUR"
BUCKET = "SHORT_TERM_ROTATION"


def _candidate_gate_plan():
    setup = AutomaticBuySetupContextV1(
        venue="bitvavo",
        asset_id=42,
        market=MARKET,
        strategy_id="strat-1",
        strategy_version="1",
        setup_id="setup-1",
        setup_ready=True,
        current_price=Decimal("95"),
        entry_zone_low=Decimal("90"),
        entry_zone_high=Decimal("100"),
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        evidence_id="evidence-1",
        observed_ts_utc=NOW,
    )
    candidate_eval = evaluate_automatic_buy_candidate_v1(
        setup_context=setup,
        evaluation_ts_utc=NOW,
    )
    assert candidate_eval.candidate is not None
    gate = evaluate_automatic_buy_candidate_permission_v1(
        candidate=candidate_eval.candidate,
        context=automatic_buy_gate_context(),
    )
    assert gate.state == STATE_APPROVED
    plan = build_automatic_buy_plan_v1(
        decision=gate,
        context=automatic_buy_planning_context(),
    )
    return candidate_eval.candidate, gate, plan


def _buy_resting_quote() -> PaperMarketQuoteV1:
    return PaperMarketQuoteV1(
        market=MARKET,
        best_bid=Decimal("90"),
        best_ask=Decimal("110"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )


def _buy_through_quote() -> PaperMarketQuoteV1:
    return PaperMarketQuoteV1(
        market=MARKET,
        best_bid=Decimal("89"),
        best_ask=Decimal("90"),
        observed_ts_utc=NOW - timedelta(seconds=3),
    )


def _map_evidence(fill_ts) -> CanonicalFibMapEvidenceV1:
    return CanonicalFibMapEvidenceV1(
        venue="bitvavo",
        market=MARKET,
        native_map_id="native-map-b8-1",
        map_cycle_id="cycle-b8-1",
        map_structure_hash="b8-map-structure-1",
        map_source_name="native_short_fib_context_snapshot_v1",
        map_source_version="0.1",
        map_asof_ts_utc=fill_ts,
        map_published_at_utc=fill_ts,
        anchor_start_ts_utc=fill_ts - timedelta(days=3),
        anchor_end_ts_utc=fill_ts,
        anchor_low_price=Decimal("80"),
        anchor_high_price=Decimal("100"),
        breakout_gate_price=Decimal("105"),
        invalidation_price=Decimal("75"),
        target_levels=(Decimal("120"), Decimal("130"), Decimal("140")),
        target_ladder_semantics_version="FIB_MAP_BOUND_V1",
    )


def _exit_context(at=NOW) -> FibMapBoundExitPlanningContextV1:
    return FibMapBoundExitPlanningContextV1(
        venue_constraints=VenueExecutionConstraints(
            venue="bitvavo",
            market=MARKET,
            tick_size=Decimal("0.01"),
            qty_step_size=Decimal("0.0001"),
            min_base_quantity=Decimal("0.0001"),
            min_quote_notional=Decimal("0.01"),
            supported_order_types=("limit",),
            supported_time_in_force=("GTC",),
            source_provenance="PUBLIC",
            metadata_synced_ts_utc=NOW,
            status=STATUS_FRESH,
        ),
        planning_ts_utc=at,
    )


def _decision(binding, owned, *, price: Decimal, consumed=(), at=NOW):
    return evaluate_fib_map_bound_exit_decision_v1(
        binding=binding,
        owned_position=owned,
        progression=FibMapBoundExitProgressionV1(
            consumed_target_indices=frozenset(consumed)
        ),
        market_evidence=FibMapBoundExitMarketEvidenceV1(
            current_price=price,
            price_observed_ts_utc=at,
        ),
        evaluation_ts_utc=at,
    )


def _execute_paper_sell(
    *,
    exit_plan,
    exit_handoff_repo,
    inventory_conn,
    at,
):
    handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=exit_plan,
        executor_mode=RUNTIME_MODE_PAPER,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        handoff_repository=exit_handoff_repo,
    )
    leg_repo = MemoryLegRepository()
    placement_repo = MemoryPlacementRepository()
    handoff_repo = MemoryHandoffRepository(handoff)

    resting_quote = PaperMarketQuoteV1(
        market=MARKET,
        best_bid=exit_plan.legs[0].limit_price - Decimal("1"),
        best_ask=exit_plan.legs[0].limit_price,
        observed_ts_utc=at - timedelta(milliseconds=200),
    )
    first = submit_and_reconcile_fib_map_bound_exit_paper_plan_v1(
        plan=exit_plan,
        handoff=handoff,
        operator_id=73,
        handoff_repository=handoff_repo,
        leg_repository=leg_repo,
        conn=inventory_conn,
        quote_provider=FixedQuoteProvider(resting_quote),
        max_quote_age_seconds=30,
        now_fn=lambda: at,
        placement_repository=placement_repo,
    )
    assert first.submission.leg_states == ("ACTIVE",)
    assert first.fills == ()

    leg = leg_repo.find_by_handoff_and_index(handoff.handoff_id or 0, 1)
    assert leg is not None and leg.state == "ACTIVE"
    through_quote = PaperMarketQuoteV1(
        market=MARKET,
        best_bid=leg.price + Decimal("1"),
        best_ask=leg.price + Decimal("2"),
        observed_ts_utc=at - timedelta(milliseconds=50),
    )
    second = submit_and_reconcile_fib_map_bound_exit_paper_plan_v1(
        plan=exit_plan,
        handoff=handoff,
        operator_id=73,
        handoff_repository=handoff_repo,
        leg_repository=leg_repo,
        conn=inventory_conn,
        quote_provider=FixedQuoteProvider(through_quote),
        max_quote_age_seconds=30,
        now_fn=lambda: at,
        placement_repository=placement_repo,
    )
    assert second.fills and second.fills[0].event is not None
    filled = leg_repo.find_by_handoff_and_index(handoff.handoff_id or 0, 1)
    assert filled is not None and filled.state == "FILLED"

    replay = submit_and_reconcile_fib_map_bound_exit_paper_plan_v1(
        plan=exit_plan,
        handoff=handoff,
        operator_id=73,
        handoff_repository=handoff_repo,
        leg_repository=leg_repo,
        conn=inventory_conn,
        quote_provider=FixedQuoteProvider(through_quote),
        max_quote_age_seconds=30,
        now_fn=lambda: at,
        placement_repository=placement_repo,
    )
    assert replay.fills and replay.fills[0].event is None
    assert len(placement_repo.rows) == 1
    return handoff, filled, second.fills[0].fact


def _position(events, *, bucket=BUCKET, trade_id=None):
    positions = project_strategy_owned_inventory_v1(events)
    matches = [p for p in positions if p.strategy_bucket_id == bucket]
    if trade_id is not None:
        matches = [p for p in matches if p.trade_id == trade_id]
    assert len(matches) == 1
    return matches[0]


def test_b8_exact_path_paper_acceptance_matrix() -> None:
    # Case 1: valid setup -> BUY candidate -> decision_gate -> BUY plan ->
    # real PAPER ACTIVE -> later FILLED -> immutable first-fill map binding.
    candidate, gate, plan = _candidate_gate_plan()
    assert candidate.market == MARKET
    assert gate.strategy_bucket_id == BUCKET
    assert plan.trade_id and plan.strategy_bucket_id == BUCKET
    handoff = automatic_buy_handoff(plan)
    inventory_conn = FakeConnection()
    buy_leg_repo = MemoryLegRepository()
    buy_placement_repo = MemoryPlacementRepository()

    first = run_automatic_buy_paper(
        plan,
        handoff,
        leg_repository=buy_leg_repo,
        conn=inventory_conn,
        quote=_buy_resting_quote(),
        placement_repository=buy_placement_repo,
    )
    assert all(state == "ACTIVE" for state in first.submission.leg_states)
    assert first.fills == ()
    assert load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    ) == ()

    second = run_automatic_buy_paper(
        plan,
        handoff,
        leg_repository=buy_leg_repo,
        conn=inventory_conn,
        quote=_buy_through_quote(),
        placement_repository=buy_placement_repo,
    )
    assert second.fills and all(outcome.event is not None for outcome in second.fills)
    buy_events = load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    )
    assert len(buy_events) == len(plan.legs)
    earliest_buy = min(buy_events, key=lambda e: (e.occurred_ts_utc, e.event_id))
    verified = verify_first_buy_fill_v1(
        fill_event=earliest_buy,
        inventory_conn=inventory_conn,
    )

    fib_db = FibBindingMemoryDatabase()
    fib_repo = FibMapBoundTradeRepositoryV1(cursor_factory=fib_db.cursor_factory)
    map_evidence = _map_evidence(earliest_buy.occurred_ts_utc)
    binding = bind_fib_map_bound_trade_on_first_fill_v1(
        verified_first_fill=verified,
        map_evidence=map_evidence,
        repository=fib_repo,
    )
    assert binding.target_levels == map_evidence.target_levels
    assert binding.invalidation_price == map_evidence.invalidation_price

    owned_before_exit = _position(buy_events, trade_id=binding.trade_id)
    assert owned_before_exit.owned_base_quantity == plan.final_quantity_base

    # Case 2: target 1 creates a partial SELL and that SELL really rests,
    # fills through PAPER reconciliation, and reduces #752-owned quantity.
    target1 = _decision(binding, owned_before_exit, price=Decimal("120"))
    assert target1.state == STATE_PARTIAL_PROFIT_TARGET
    assert target1.target_index == 0
    target1_plan = build_fib_map_bound_exit_plan_v1(
        decision=target1,
        binding=binding,
        context=_exit_context(NOW + timedelta(seconds=1)),
    )
    assert target1_plan.final_quantity_base <= owned_before_exit.owned_base_quantity
    exit_handoff_db = ExitHandoffMemoryDatabase()
    exit_repo = exit_handoff_repository(database=exit_handoff_db)
    target1_handoff, target1_filled, _ = _execute_paper_sell(
        exit_plan=target1_plan,
        exit_handoff_repo=exit_repo,
        inventory_conn=inventory_conn,
        at=NOW + timedelta(seconds=1),
    )
    after_target_events = load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    )
    owned_after_target = _position(after_target_events, trade_id=binding.trade_id)
    assert owned_after_target.owned_base_quantity == (
        owned_before_exit.owned_base_quantity - target1_filled.quantity
    )
    assert owned_after_target.owned_base_quantity > 0

    # Case 3: multiple targets progress in frozen deterministic ladder order.
    target2 = _decision(
        binding,
        owned_after_target,
        price=Decimal("130"),
        consumed=(0,),
        at=NOW + timedelta(seconds=1),
    )
    assert target2.state == STATE_PARTIAL_PROFIT_TARGET
    assert target2.target_index == 1
    assert target2.target_price == binding.target_levels[1]

    # Case 4: invalidation before any target wins over all future targets.
    before_target_invalidation = _decision(
        binding,
        owned_before_exit,
        price=Decimal("70"),
    )
    assert before_target_invalidation.state == STATE_PROTECTIVE_EXIT
    assert before_target_invalidation.decision_quantity_base == owned_before_exit.owned_base_quantity

    # Case 5: after target-1 actually filled, invalidation exits exactly the
    # remaining strategy-owned quantity and reaches terminal owned=0.
    protective = _decision(
        binding,
        owned_after_target,
        price=Decimal("70"),
        consumed=(0,),
        at=NOW + timedelta(seconds=2),
    )
    assert protective.state == STATE_PROTECTIVE_EXIT
    assert protective.decision_quantity_base == owned_after_target.owned_base_quantity
    protective_plan = build_fib_map_bound_exit_plan_v1(
        decision=protective,
        binding=binding,
        context=_exit_context(NOW + timedelta(seconds=2)),
    )
    protective_handoff, _, _ = _execute_paper_sell(
        exit_plan=protective_plan,
        exit_handoff_repo=exit_repo,
        inventory_conn=inventory_conn,
        at=NOW + timedelta(seconds=2),
    )
    terminal_events = load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    )
    terminal_position = _position(terminal_events, trade_id=binding.trade_id)
    assert terminal_position.owned_base_quantity == 0

    # Case 6: a new canonical map cannot rewrite the still-bound old-map trade.
    rolled_map = replace(
        map_evidence,
        native_map_id="native-map-b8-2",
        map_cycle_id="cycle-b8-2",
        map_structure_hash="b8-map-structure-2",
        target_levels=(Decimal("125"), Decimal("135"), Decimal("145")),
    )
    with pytest.raises(FibMapBoundTradeConflictError):
        bind_fib_map_bound_trade_on_first_fill_v1(
            verified_first_fill=verified,
            map_evidence=rolled_map,
            repository=fib_repo,
        )
    assert fib_repo.load_by_binding_id(binding_id=binding.binding_id) == binding

    # Case 7: restart/replay over the same persisted stores preserves both the
    # immutable map binding and remaining/terminal #752 quantity.
    restarted_fib_repo = FibMapBoundTradeRepositoryV1(cursor_factory=fib_db.cursor_factory)
    assert restarted_fib_repo.load_by_binding_id(binding_id=binding.binding_id) == binding
    restarted_position = _position(
        load_strategy_owned_inventory_events_v1(
            inventory_conn, trading_account_id=ACCOUNT_ID
        ),
        trade_id=binding.trade_id,
    )
    assert restarted_position.owned_base_quantity == 0
    restarted_exit_repo = exit_handoff_repository(database=exit_handoff_db)
    assert submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=target1_plan,
        executor_mode=RUNTIME_MODE_PAPER,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        handoff_repository=restarted_exit_repo,
    ) == target1_handoff

    # Case 8: missing, stale, and conflicting bound-map evidence all fail closed.
    missing = evaluate_fib_map_bound_exit_decision_v1(
        binding=None,
        owned_position=owned_before_exit,
        progression=FibMapBoundExitProgressionV1(consumed_target_indices=frozenset()),
        market_evidence=FibMapBoundExitMarketEvidenceV1(
            current_price=Decimal("120"), price_observed_ts_utc=NOW
        ),
        evaluation_ts_utc=NOW,
    )
    assert missing.state == STATE_FAIL_CLOSED
    assert missing.reason_code == REASON_MISSING_BINDING
    stale_map = replace(
        map_evidence,
        map_asof_ts_utc=earliest_buy.occurred_ts_utc - timedelta(hours=13),
        map_published_at_utc=earliest_buy.occurred_ts_utc - timedelta(hours=13),
    )
    with pytest.raises(FibMapBoundTradeBindingAdapterError, match="FIB_MAP_EVIDENCE_STALE"):
        build_fib_map_bound_trade_v1_from_first_fill(
            verified_first_fill=verified,
            map_evidence=stale_map,
        )
    with pytest.raises(FibMapBoundTradeConflictError):
        bind_fib_map_bound_trade_on_first_fill_v1(
            verified_first_fill=verified,
            map_evidence=rolled_map,
            repository=restarted_fib_repo,
        )

    # Case 9: a second bucket may own the same asset but cannot authorize a
    # SELL against this binding; its owned quantity survives this trade's exit.
    other_bucket_buy = replace(
        earliest_buy,
        event_id="b8-other-bucket-buy-event",
        strategy_bucket_id="LONG_TERM_MOONSHOT",
        trade_id="b8-other-bucket-trade",
        source_execution_plan_id="b8-other-bucket-plan",
        source_fill_id="b8-other-bucket-fill",
        filled_base_quantity=Decimal("0.2"),
        occurred_ts_utc=NOW + timedelta(milliseconds=500),
    )
    append_strategy_owned_inventory_event_v1(inventory_conn, event=other_bucket_buy)
    isolated_events = load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    )
    other_position = _position(
        isolated_events,
        bucket="LONG_TERM_MOONSHOT",
        trade_id="b8-other-bucket-trade",
    )
    denied = _decision(binding, other_position, price=Decimal("120"))
    assert denied.state == STATE_FAIL_CLOSED
    assert denied.reason_code == REASON_OWNERSHIP_MISMATCH
    assert other_position.owned_base_quantity == Decimal("0.2")
    assert restarted_fib_repo.load_by_lineage(
        trading_account_id=ACCOUNT_ID,
        venue=binding.venue,
        market=binding.market,
        strategy_bucket_id="LONG_TERM_MOONSHOT",
        strategy_id=binding.strategy_id,
        strategy_version=binding.strategy_version,
        trade_id=binding.trade_id,
    ) is None

    # Case 10: duplicate runtime cycles cannot duplicate exit plans/orders.
    target1_replay_handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=target1_plan,
        executor_mode=RUNTIME_MODE_PAPER,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        handoff_repository=restarted_exit_repo,
    )
    protective_replay_handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=protective_plan,
        executor_mode=RUNTIME_MODE_PAPER,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        handoff_repository=restarted_exit_repo,
    )
    assert target1_replay_handoff == target1_handoff
    assert protective_replay_handoff == protective_handoff
    assert len(exit_handoff_db.rows) == 2
    assert len(buy_placement_repo.rows) == len(plan.legs)
