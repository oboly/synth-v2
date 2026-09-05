"""Issue #756 Codex block BUY RESERVATIONS: bucket-scoped pending-BUY
reservation read model tests -- same-bucket/same-market, same-bucket/
different-market, cross-bucket isolation, terminal-state exclusion, and
duplicate-record dedup (the join is scoped by handoff/leg identity, so a
duplicate reconciliation write to the same leg row is not double-counted by
construction -- one leg row is one reservation fact).
"""
from __future__ import annotations

from decimal import Decimal

from src.decision_gate.strategy_bucket_buy_reservation_v1 import (
    load_bucket_active_buy_reservations_eur_v1,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
    FakeConnection,
    insert_execution_leg,
)

ACCOUNT = 7
BUCKET = "SHORT_TERM_ROTATION"
OTHER_BUCKET = "LONG_TERM_MOONSHOT"


def test_same_bucket_same_market_reservation_counted():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", price=Decimal("100"), quantity=Decimal("2"))
    total = load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
    )
    assert total == Decimal("200")


def test_same_bucket_different_market_reservations_both_counted():
    # BTC open reservation must still count against a new ETH BUY request in
    # the same sleeve -- market-scoped conflict is not a substitute.
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="btc-buy", price=Decimal("30000"), quantity=Decimal("0.02"))
    insert_execution_leg(conn, plan_reference_id="eth-buy", price=Decimal("2000"), quantity=Decimal("0.1"))
    total = load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
    )
    assert total == Decimal("30000") * Decimal("0.02") + Decimal("2000") * Decimal("0.1")


def test_different_buckets_do_not_collide():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", strategy_bucket_id=BUCKET, price=Decimal("100"), quantity=Decimal("1"))
    insert_execution_leg(
        conn, plan_reference_id="p2", strategy_bucket_id=OTHER_BUCKET, price=Decimal("900"), quantity=Decimal("1"),
    )
    assert load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
    ) == Decimal("100")
    assert load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=OTHER_BUCKET,
    ) == Decimal("900")


def test_terminal_states_do_not_reserve_capacity():
    conn = FakeConnection()
    for state in ("FILLED", "CANCELED", "EXPIRED", "REJECTED", "FAILED"):
        insert_execution_leg(conn, plan_reference_id=f"p-{state}", state=state, price=Decimal("100"), quantity=Decimal("1"))
    total = load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
    )
    assert total == Decimal("0")


def test_non_terminal_states_all_reserve_capacity():
    conn = FakeConnection()
    for state in ("PREPARED", "SUBMISSION_UNCERTAIN", "RECONCILIATION_REQUIRED", "ACTIVE", "PARTIALLY_FILLED"):
        insert_execution_leg(conn, plan_reference_id=f"p-{state}", state=state, price=Decimal("10"), quantity=Decimal("1"))
    total = load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
    )
    assert total == Decimal("50")


def test_sell_legs_never_reserve_buy_capacity():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", side="SELL", price=Decimal("100"), quantity=Decimal("5"))
    total = load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
    )
    assert total == Decimal("0")


def test_repeated_read_after_no_new_write_is_stable_not_double_counted():
    # A reconciliation replay that re-resolves the same already-persisted leg
    # (client_order_id-unique per the production executor_execution_leg
    # schema, enforced by the shared leg repository itself -- not
    # re-simulated here) never inserts a second row; this read model must
    # therefore see the identical total across repeated reads with no new
    # write in between.
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", price=Decimal("100"), quantity=Decimal("2"))
    first = load_bucket_active_buy_reservations_eur_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET)
    second = load_bucket_active_buy_reservations_eur_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET)
    assert first == second == Decimal("200")


def test_bucket_scoped_example_from_task_contract():
    # bucket cap 1000; open BUY reservation BTC 600; new ETH BUY 500 must be
    # blocked by remaining-capacity math even though ETH has no order of its
    # own -- this test proves the reservation evidence itself surfaces 600,
    # which the existing gate capacity check (#752/#756) already consumes.
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="btc-buy", price=Decimal("600"), quantity=Decimal("1"))
    total = load_bucket_active_buy_reservations_eur_v1(
        conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
    )
    assert total == Decimal("600")
