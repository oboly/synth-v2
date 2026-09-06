from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    append_strategy_owned_inventory_event_v1,
    load_strategy_owned_inventory_events_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import (
    StrategyOwnedInventoryEventV1,
    project_strategy_owned_inventory_v1,
)
from src.execution_planner.fib_map_bound_exit_execution_handoff_application_v1 import (
    submit_fib_map_bound_exit_plan_to_execution_handoff_v1,
)
from src.orchestration.fib_map_bound_exit_paper_fill_execution_v1 import (
    FibMapBoundExitPaperFillExecutionError,
    submit_and_reconcile_fib_map_bound_exit_paper_plan_v1,
)
from src.executor.paper_order_adapter_v1 import PaperMarketQuoteV1
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection
from tests.test_automatic_buy_paper_fill_execution_v1 import (
    NOW,
    FixedQuoteProvider,
    MemoryHandoffRepository,
    MemoryLegRepository,
    MemoryPlacementRepository,
)
from tests.test_fib_map_bound_exit_execution_handoff_application_v1 import (
    MemoryDatabase,
    _plan,
    _repository,
)


def _seed_buy(conn: FakeConnection, *, qty: Decimal = Decimal("9")) -> None:
    append_strategy_owned_inventory_event_v1(
        conn,
        event=StrategyOwnedInventoryEventV1(
            event_id="seed-buy-event",
            trading_account_id=1,
            venue="bitvavo",
            market="SOL-EUR",
            strategy_bucket_id="AUTO_SHORTTF_FIB",
            strategy_id="shorttf_fib",
            strategy_version="1",
            trade_id="trade-1",
            source_execution_plan_id="seed-buy-plan",
            source_fill_id="seed-buy-fill",
            side="BUY",
            filled_base_quantity=qty,
            fill_notional_eur=None,
            occurred_ts_utc=NOW - timedelta(minutes=10),
        ),
    )


def _position(conn: FakeConnection):
    events = load_strategy_owned_inventory_events_v1(conn, trading_account_id=1)
    positions = project_strategy_owned_inventory_v1(events)
    matches = [p for p in positions if p.trade_id == "trade-1"]
    assert len(matches) == 1
    return matches[0]


def _setup():
    plan = _plan()
    handoff_db = MemoryDatabase()
    handoff_repo = _repository(database=handoff_db)
    handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=plan,
        executor_mode="PAPER",
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        handoff_repository=handoff_repo,
    )
    return plan, handoff


def _run(plan, handoff, *, conn, leg_repo, placement_repo, quote):
    return submit_and_reconcile_fib_map_bound_exit_paper_plan_v1(
        plan=plan,
        handoff=handoff,
        operator_id=73,
        handoff_repository=MemoryHandoffRepository(handoff),
        leg_repository=leg_repo,
        conn=conn,
        quote_provider=FixedQuoteProvider(quote),
        max_quote_age_seconds=30,
        now_fn=lambda: NOW,
        placement_repository=placement_repo,
    )


def test_real_paper_sell_rests_then_fills_and_reduces_owned_quantity_once() -> None:
    plan, handoff = _setup()
    conn = FakeConnection()
    _seed_buy(conn)
    leg_repo = MemoryLegRepository()
    placement_repo = MemoryPlacementRepository()
    price = plan.legs[0].limit_price

    resting = PaperMarketQuoteV1(
        market=plan.market,
        best_bid=price - Decimal("1"),
        best_ask=price,
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    first = _run(
        plan, handoff, conn=conn, leg_repo=leg_repo,
        placement_repo=placement_repo, quote=resting,
    )
    assert first.submission.leg_states == ("ACTIVE",)
    assert first.fills == ()
    assert _position(conn).owned_base_quantity == Decimal("9")
    assert len(placement_repo.rows) == 1

    through = PaperMarketQuoteV1(
        market=plan.market,
        best_bid=price + Decimal("1"),
        best_ask=price + Decimal("2"),
        observed_ts_utc=NOW - timedelta(seconds=3),
    )
    second = _run(
        plan, handoff, conn=conn, leg_repo=leg_repo,
        placement_repo=placement_repo, quote=through,
    )
    assert len(second.fills) == 1
    assert second.fills[0].event is not None
    assert second.fills[0].event.side == "SELL"
    assert second.fills[0].event.filled_base_quantity == plan.final_quantity_base
    assert _position(conn).owned_base_quantity == Decimal("9") - plan.final_quantity_base

    third = _run(
        plan, handoff, conn=conn, leg_repo=leg_repo,
        placement_repo=placement_repo, quote=through,
    )
    assert len(third.fills) == 1
    assert third.fills[0].event is None
    assert _position(conn).owned_base_quantity == Decimal("9") - plan.final_quantity_base
    assert len(placement_repo.rows) == 1


def test_newly_placed_active_sell_cannot_fill_in_same_invocation() -> None:
    plan, handoff = _setup()
    conn = FakeConnection()
    _seed_buy(conn)
    leg_repo = MemoryLegRepository()
    placement_repo = MemoryPlacementRepository()
    price = plan.legs[0].limit_price
    # Non-crossing at placement. The orchestration may only reconcile ACTIVE
    # legs captured before submit, never the leg it just created.
    quote = PaperMarketQuoteV1(
        market=plan.market,
        best_bid=price - Decimal("0.01"),
        best_ask=price + Decimal("1"),
        observed_ts_utc=NOW - timedelta(seconds=1),
    )
    result = _run(
        plan, handoff, conn=conn, leg_repo=leg_repo,
        placement_repo=placement_repo, quote=quote,
    )
    assert result.submission.leg_states == ("ACTIVE",)
    assert result.fills == ()
    assert _position(conn).owned_base_quantity == Decimal("9")


def test_non_paper_handoff_fails_before_submission() -> None:
    plan, handoff = _setup()
    bad = type(handoff)(**{**handoff.__dict__, "executor_mode": "LIVE"})
    with pytest.raises(FibMapBoundExitPaperFillExecutionError, match="HANDOFF_NOT_PAPER_MODE"):
        _run(
            plan,
            bad,
            conn=FakeConnection(),
            leg_repo=MemoryLegRepository(),
            placement_repo=MemoryPlacementRepository(),
            quote=PaperMarketQuoteV1(
                market=plan.market,
                best_bid=Decimal("1"),
                best_ask=Decimal("2"),
                observed_ts_utc=NOW,
            ),
        )
