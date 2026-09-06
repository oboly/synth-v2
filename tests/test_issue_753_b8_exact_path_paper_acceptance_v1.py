"""Issue #753 B8 exact-path PAPER acceptance.

Acceptance-only composition of already-reviewed B4-B7.5 and B1-B3 seams.
No production trading semantics are introduced here.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from src.decision_gate.fib_map_bound_exit_decision_v1 import (
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
    bind_fib_map_bound_trade_on_first_fill_v1,
    verify_first_buy_fill_v1,
)
from src.decision_gate.fib_map_bound_trade_repository_v1 import (
    FibMapBoundTradeConflictError,
    FibMapBoundTradeRepositoryV1,
)
from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    load_strategy_owned_inventory_events_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import project_strategy_owned_inventory_v1
from src.execution_planner.fib_map_bound_exit_execution_handoff_application_v1 import (
    submit_fib_map_bound_exit_plan_to_execution_handoff_v1,
)
from src.execution_planner.fib_map_bound_exit_planner_v1 import (
    FibMapBoundExitPlanningContextV1,
    build_fib_map_bound_exit_plan_v1,
)
from src.executor.execution_handoff_v1 import RUNTIME_MODE_PAPER
from src.executor.paper_order_adapter_v1 import PaperMarketQuoteV1
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints
from tests.test_automatic_buy_paper_fill_execution_v1 import (
    ACCOUNT_ID,
    NOW,
    MemoryLegRepository,
    MemoryPlacementRepository,
    _handoff as automatic_buy_handoff,
    _plan as automatic_buy_plan,
    _run as run_automatic_buy_paper,
)
from tests.test_fib_map_bound_exit_execution_handoff_application_v1 import (
    MemoryDatabase as ExitHandoffMemoryDatabase,
    _repository as exit_handoff_repository,
)
from tests.test_fib_map_bound_trade_first_fill_binding_adapter_v1 import (
    MemoryDatabase as FibBindingMemoryDatabase,
)


def _resting_quote() -> PaperMarketQuoteV1:
    return PaperMarketQuoteV1(
        market="BTC-EUR",
        best_bid=Decimal("90"),
        best_ask=Decimal("110"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )


def _through_quote() -> PaperMarketQuoteV1:
    return PaperMarketQuoteV1(
        market="BTC-EUR",
        best_bid=Decimal("98"),
        best_ask=Decimal("99"),
        observed_ts_utc=NOW - timedelta(seconds=3),
    )


def _map_evidence(fill_ts) -> CanonicalFibMapEvidenceV1:
    return CanonicalFibMapEvidenceV1(
        venue="bitvavo",
        market="BTC-EUR",
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


def _exit_context() -> FibMapBoundExitPlanningContextV1:
    return FibMapBoundExitPlanningContextV1(
        venue_constraints=VenueExecutionConstraints(
            venue="bitvavo",
            market="BTC-EUR",
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
        planning_ts_utc=NOW,
    )


def test_b8_exact_path_paper_closed_loop_acceptance() -> None:
    plan = automatic_buy_plan()
    handoff = automatic_buy_handoff(plan)
    inventory_conn = __import__(
        "tests.automatic_buy_account_allocation_evidence_fixtures_v1",
        fromlist=["FakeConnection"],
    ).FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_repository = MemoryPlacementRepository()

    # 1. Real B5.5 placement: passive post-only BUY rests ACTIVE. No fake fill,
    # no ownership mutation, and exactly one durable PAPER placement identity.
    first = run_automatic_buy_paper(
        plan,
        handoff,
        leg_repository=leg_repository,
        conn=inventory_conn,
        quote=_resting_quote(),
        placement_repository=placement_repository,
    )
    assert first.submission.leg_states == ("ACTIVE",)
    assert first.fills == ()
    assert load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    ) == ()
    assert len(placement_repository.rows) == 1

    # 2. Real B7.5 later invocation: strict price-through transitions persisted
    # ACTIVE -> FILLED and the unchanged B5/#752 bridge emits exactly one BUY.
    second = run_automatic_buy_paper(
        plan,
        handoff,
        leg_repository=leg_repository,
        conn=inventory_conn,
        quote=_through_quote(),
        placement_repository=placement_repository,
    )
    assert second.submission.leg_states == ("ACTIVE",)
    assert second.fills and second.fills[0].event is not None
    inventory_events = load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    )
    assert len(inventory_events) == 1
    buy_event = inventory_events[0]
    assert buy_event.side == "BUY"
    assert leg_repository.rows[1].state == "FILLED"

    # 3. B7 verifies earliest BUY from authoritative #752 persistence, then B6
    # freezes the full canonical map ladder/invalidation on that exact fill.
    verified_fill = verify_first_buy_fill_v1(
        fill_event=buy_event,
        inventory_conn=inventory_conn,
    )
    fib_database = FibBindingMemoryDatabase()
    fib_repository = FibMapBoundTradeRepositoryV1(cursor_factory=fib_database.cursor_factory)
    map_evidence = _map_evidence(buy_event.occurred_ts_utc)
    binding = bind_fib_map_bound_trade_on_first_fill_v1(
        verified_first_fill=verified_fill,
        map_evidence=map_evidence,
        repository=fib_repository,
    )
    assert binding.source_buy_fill_id == buy_event.source_fill_id
    assert binding.target_levels == map_evidence.target_levels
    assert binding.invalidation_price == map_evidence.invalidation_price
    assert len(fib_database.by_binding_id) == 1

    # 4. B2 consumes only #752 strategy-owned quantity. B3 may round down but
    # can never increase it. No wallet/broker balance participates in this API.
    owned_position = project_strategy_owned_inventory_v1(inventory_events)[0]
    target_decision = evaluate_fib_map_bound_exit_decision_v1(
        binding=binding,
        owned_position=owned_position,
        progression=FibMapBoundExitProgressionV1(consumed_target_indices=frozenset()),
        market_evidence=FibMapBoundExitMarketEvidenceV1(
            current_price=Decimal("120"), price_observed_ts_utc=NOW
        ),
        evaluation_ts_utc=NOW,
    )
    assert target_decision.state == STATE_PARTIAL_PROFIT_TARGET
    assert target_decision.decision_quantity_base is not None
    assert target_decision.decision_quantity_base <= owned_position.owned_base_quantity

    exit_plan = build_fib_map_bound_exit_plan_v1(
        decision=target_decision,
        binding=binding,
        context=_exit_context(),
    )
    assert exit_plan.side == "SELL"
    assert exit_plan.final_quantity_base <= owned_position.owned_base_quantity
    assert exit_plan.final_quantity_base <= target_decision.decision_quantity_base

    exit_handoff_database = ExitHandoffMemoryDatabase()
    exit_handoff_repo = exit_handoff_repository(database=exit_handoff_database)
    exit_handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=exit_plan,
        executor_mode=RUNTIME_MODE_PAPER,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        handoff_repository=exit_handoff_repo,
    )
    assert exit_handoff.executor_mode == RUNTIME_MODE_PAPER
    assert exit_handoff.side == "SELL"
    assert len(exit_handoff_database.rows) == 1

    # 5. Invalidation wins and uses only the full remaining owned quantity.
    protective = evaluate_fib_map_bound_exit_decision_v1(
        binding=binding,
        owned_position=owned_position,
        progression=FibMapBoundExitProgressionV1(consumed_target_indices=frozenset()),
        market_evidence=FibMapBoundExitMarketEvidenceV1(
            current_price=Decimal("70"), price_observed_ts_utc=NOW
        ),
        evaluation_ts_utc=NOW,
    )
    assert protective.state == STATE_PROTECTIVE_EXIT
    assert protective.decision_quantity_base == owned_position.owned_base_quantity

    # 6. A later canonical map cannot rewrite an already-bound trade.
    rolled_map = replace(
        map_evidence,
        native_map_id="native-map-b8-2",
        map_cycle_id="cycle-b8-2",
        map_structure_hash="b8-map-structure-2",
        target_levels=(Decimal("125"), Decimal("135"), Decimal("145")),
    )
    with pytest.raises(FibMapBoundTradeConflictError):
        bind_fib_map_bound_trade_on_first_fill_v1(
            verified_first_fill=verified_fill,
            map_evidence=rolled_map,
            repository=fib_repository,
        )
    assert fib_repository.load_by_binding_id(binding_id=binding.binding_id) == binding

    # 7. Restart/replay: new repository objects over the same persisted stores
    # recover the exact binding and deterministic exit handoff identity.
    restarted_fib_repository = FibMapBoundTradeRepositoryV1(
        cursor_factory=fib_database.cursor_factory
    )
    assert restarted_fib_repository.load_by_binding_id(binding_id=binding.binding_id) == binding
    restarted_exit_repo = exit_handoff_repository(database=exit_handoff_database)
    replay_exit_handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=exit_plan,
        executor_mode=RUNTIME_MODE_PAPER,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        handoff_repository=restarted_exit_repo,
    )
    assert replay_exit_handoff == exit_handoff
    assert len(exit_handoff_database.rows) == 1

    # 8. Cross-bucket/account lineage cannot consume this ownership/binding.
    wrong_bucket = replace(owned_position, strategy_bucket_id="OTHER_BUCKET")
    denied = evaluate_fib_map_bound_exit_decision_v1(
        binding=binding,
        owned_position=wrong_bucket,
        progression=FibMapBoundExitProgressionV1(consumed_target_indices=frozenset()),
        market_evidence=FibMapBoundExitMarketEvidenceV1(
            current_price=Decimal("120"), price_observed_ts_utc=NOW
        ),
        evaluation_ts_utc=NOW,
    )
    assert denied.state == STATE_FAIL_CLOSED
    assert denied.reason_code == REASON_OWNERSHIP_MISMATCH
    assert restarted_fib_repository.load_by_lineage(
        trading_account_id=ACCOUNT_ID + 1,
        venue=binding.venue,
        market=binding.market,
        strategy_bucket_id=binding.strategy_bucket_id,
        strategy_id=binding.strategy_id,
        strategy_version=binding.strategy_version,
        trade_id=binding.trade_id,
    ) is None

    # 9. Duplicate cycle/replay: no duplicate placement, ownership, binding,
    # or exit handoff is created.
    replay_buy = run_automatic_buy_paper(
        plan,
        handoff,
        leg_repository=leg_repository,
        conn=inventory_conn,
        quote=_through_quote(),
        placement_repository=placement_repository,
    )
    assert replay_buy.fills[0].event is None
    assert len(placement_repository.rows) == 1
    assert len(load_strategy_owned_inventory_events_v1(
        inventory_conn, trading_account_id=ACCOUNT_ID
    )) == 1
    rebound = bind_fib_map_bound_trade_on_first_fill_v1(
        verified_first_fill=verified_fill,
        map_evidence=map_evidence,
        repository=restarted_fib_repository,
    )
    assert rebound == binding
    assert len(fib_database.by_binding_id) == 1
    assert len(exit_handoff_database.rows) == 1
