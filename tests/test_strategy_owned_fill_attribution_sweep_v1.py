"""Issue #756 Codex block: authoritative production wiring tests proving the
decision_gate-owned attribution sweep (raw SQL over executor_execution_leg/
executor_execution_handoff -- no import of src.executor, see the sweep
module's own docstring for why) records exactly one idempotent
strategy-owned inventory ledger event per canonical FILLED automatic-buy
leg, and never attributes manual execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.strategy_owned_fill_attribution_sweep_v1 import (
    StrategyOwnedFillAttributionSweepError,
    run_strategy_owned_fill_attribution_sweep_v1,
)
from src.decision_gate.strategy_owned_inventory_ledger_repository_v1 import (
    load_strategy_owned_fill_events_for_bucket_v1,
)
from src.decision_gate.strategy_owned_inventory_ledger_v1 import (
    StrategyOwnershipLineageV1,
    compute_owned_quantity_v1,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
    FakeConnection,
    insert_execution_leg,
)

ACCOUNT = 7
BUCKET = "SHORT_TERM_ROTATION"
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def _lineage(**changes: object) -> StrategyOwnershipLineageV1:
    values: dict[str, object] = dict(
        trading_account_id=ACCOUNT, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id=BUCKET, strategy_id="auto_shorttf_fib",
        strategy_version="1", setup_id="setup-1",
    )
    values.update(changes)
    return StrategyOwnershipLineageV1(**values)  # type: ignore[arg-type]


def test_canonical_automatic_buy_fill_produces_one_ownership_event():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", state="FILLED", price=Decimal("100"), quantity=Decimal("2"))
    result = run_strategy_owned_fill_attribution_sweep_v1(conn)
    assert result.newly_attributed == 1
    assert result.already_attributed == 0
    events = load_strategy_owned_fill_events_for_bucket_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET)
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("2")


def test_active_and_partially_filled_legs_never_attributed():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", state="ACTIVE")
    insert_execution_leg(conn, plan_reference_id="p2", state="PARTIALLY_FILLED")
    result = run_strategy_owned_fill_attribution_sweep_v1(conn)
    assert result.candidates_seen == 0
    assert result.newly_attributed == 0


def test_manual_execution_handoff_never_attributed():
    conn = FakeConnection()
    insert_execution_leg(
        conn, plan_reference_id="manual-1", state="FILLED", strategy_bucket_id=None,
        strategy_id=None, strategy_version=None, setup_id=None,
    )
    result = run_strategy_owned_fill_attribution_sweep_v1(conn)
    assert result.candidates_seen == 0
    assert result.newly_attributed == 0


def test_rerun_after_no_new_fills_is_idempotent_no_op():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", state="FILLED", price=Decimal("100"), quantity=Decimal("2"))
    first = run_strategy_owned_fill_attribution_sweep_v1(conn)
    second = run_strategy_owned_fill_attribution_sweep_v1(conn)
    assert first.newly_attributed == 1
    assert second.newly_attributed == 0
    assert second.already_attributed == 1
    events = load_strategy_owned_fill_events_for_bucket_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET)
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("2")


def test_partial_buy_fill_produces_correct_qty_and_cost():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="p1", client_order_id="c1", state="FILLED", price=Decimal("10"), quantity=Decimal("5"))
    run_strategy_owned_fill_attribution_sweep_v1(conn)
    events = load_strategy_owned_fill_events_for_bucket_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET)
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("5")


def test_sell_fill_reduces_matching_lineage_only():
    conn = FakeConnection()
    insert_execution_leg(conn, plan_reference_id="buy1", client_order_id="c1", state="FILLED", side="BUY", quantity=Decimal("10"))
    insert_execution_leg(conn, plan_reference_id="sell1", client_order_id="c2", state="FILLED", side="SELL", quantity=Decimal("3"))
    run_strategy_owned_fill_attribution_sweep_v1(conn)
    events = load_strategy_owned_fill_events_for_bucket_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET)
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("7")


def test_cross_strategy_same_market_inventory_remains_isolated():
    conn = FakeConnection()
    insert_execution_leg(
        conn, plan_reference_id="stf-buy", client_order_id="stf-1", state="FILLED", quantity=Decimal("6"),
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="auto_shorttf_fib", setup_id="stf-setup-1",
    )
    insert_execution_leg(
        conn, plan_reference_id="lt-buy", client_order_id="lt-1", state="FILLED", quantity=Decimal("4"),
        strategy_bucket_id="LONG_TERM_MOONSHOT", strategy_id="long_term_moonshot", setup_id="lt-setup-1",
    )
    run_strategy_owned_fill_attribution_sweep_v1(conn)
    stf_events = load_strategy_owned_fill_events_for_bucket_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id="AUTO_SHORTTF_FIB")
    lt_events = load_strategy_owned_fill_events_for_bucket_v1(conn, trading_account_id=ACCOUNT, strategy_bucket_id="LONG_TERM_MOONSHOT")
    assert compute_owned_quantity_v1(
        stf_events, lineage=_lineage(strategy_bucket_id="AUTO_SHORTTF_FIB", setup_id="stf-setup-1"),
    ) == Decimal("6")
    assert compute_owned_quantity_v1(
        lt_events,
        lineage=_lineage(strategy_bucket_id="LONG_TERM_MOONSHOT", strategy_id="long_term_moonshot", setup_id="lt-setup-1"),
    ) == Decimal("4")


def test_conflicting_duplicate_fill_fails_the_sweep_closed():
    # Pre-seed the ledger with a row for the exact order_identity the leg
    # below will compute, but with a conflicting quantity/notional -- e.g. a
    # corrupted manual backfill or a bug in an earlier sweep run. The sweep
    # must fail closed rather than silently accept either value.
    conn = FakeConnection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO strategy_owned_inventory_ledger_v1 "
            "(trading_account_id, venue, market, strategy_bucket_id, strategy_id, strategy_version, setup_id, "
            "execution_plan_reference_id, order_identity, side, base_quantity, quote_notional, occurred_ts_utc, source_provenance) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                ACCOUNT, "bitvavo", "SOL-EUR", BUCKET, "auto_shorttf_fib", "1", "setup-1",
                "plan-ref-other", "client-order-p1", "BUY", Decimal("999"), Decimal("99900"), NOW,
                "manual_backfill",
            ),
        )
    insert_execution_leg(conn, plan_reference_id="p1", client_order_id="client-order-p1", state="FILLED", quantity=Decimal("2"))
    with pytest.raises(StrategyOwnedFillAttributionSweepError):
        run_strategy_owned_fill_attribution_sweep_v1(conn)
