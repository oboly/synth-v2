from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import pytest

import src.decision_gate.fib_map_bound_exit_fill_reconciliation_persistence_v1 as persistence
from src.decision_gate.fib_map_bound_exit_fill_reconciliation_v1 import (
    FibMapBoundExitFillPlanIdentityV1,
)
from src.decision_gate.strategy_owned_fill_reconciliation_repository_v1 import (
    load_strategy_owned_fill_reconciliation_facts_v1,
)
from src.decision_gate.strategy_owned_fill_reconciliation_v1 import (
    BrokerCumulativeFillEvidenceV1,
    StrategyOwnedFillReconciliationFactV1,
)
from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    append_strategy_owned_inventory_event_v1,
    load_strategy_owned_inventory_events_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1
from src.decision_gate.strategy_owned_reduction_authorization_v1 import (
    StrategyOwnedReductionAuthorizationError,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection
from tests.test_automatic_buy_paper_fill_execution_v1 import NOW


def _identity(*, order: str = "sell-order-1") -> FibMapBoundExitFillPlanIdentityV1:
    return FibMapBoundExitFillPlanIdentityV1(
        trading_account_id=1,
        venue="bitvavo",
        market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB",
        strategy_id="shorttf_fib",
        strategy_version="1",
        trade_id="trade-1",
        source_execution_plan_id=f"exit-plan-{order}",
        source_order_id=order,
    )


def _buy(qty: Decimal = Decimal("5")) -> StrategyOwnedInventoryEventV1:
    return StrategyOwnedInventoryEventV1(
        event_id="seed-buy-event",
        trading_account_id=1,
        venue="bitvavo",
        market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB",
        strategy_id="shorttf_fib",
        strategy_version="1",
        trade_id="trade-1",
        source_execution_plan_id="buy-plan",
        source_fill_id="buy-fill",
        side="BUY",
        filled_base_quantity=qty,
        fill_notional_eur=None,
        occurred_ts_utc=NOW - timedelta(minutes=5),
    )


def _evidence(*, order: str = "sell-order-1", qty: Decimal = Decimal("3")) -> BrokerCumulativeFillEvidenceV1:
    return BrokerCumulativeFillEvidenceV1(
        source_snapshot_id=f"snapshot-{order}",
        cumulative_filled_base_quantity=qty,
        observed_ts_utc=NOW,
    )


def test_failure_between_fact_and_event_rolls_back_both(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    append_strategy_owned_inventory_event_v1(conn, event=_buy())
    conn.commit()

    real_append_event = persistence.append_strategy_owned_inventory_event_v1

    def fail_after_fact(_conn, *, event):
        assert event.side == "SELL"
        raise RuntimeError("SIMULATED_EVENT_WRITE_FAILURE")

    monkeypatch.setattr(persistence, "append_strategy_owned_inventory_event_v1", fail_after_fact)
    with pytest.raises(RuntimeError, match="SIMULATED_EVENT_WRITE_FAILURE"):
        persistence.reconcile_and_persist_fib_map_bound_exit_paper_fill_v1(
            conn,
            identity=_identity(),
            evidence=_evidence(),
        )
    assert conn.rolled_back is True
    assert load_strategy_owned_fill_reconciliation_facts_v1(
        conn, trading_account_id=1, venue="bitvavo", source_order_id="sell-order-1",
    ) == ()
    events = load_strategy_owned_inventory_events_v1(conn, trading_account_id=1)
    assert events == (_buy(),)

    monkeypatch.setattr(persistence, "append_strategy_owned_inventory_event_v1", real_append_event)
    fact, event = persistence.reconcile_and_persist_fib_map_bound_exit_paper_fill_v1(
        conn,
        identity=_identity(),
        evidence=_evidence(),
    )
    assert fact.side == "SELL"
    assert event is not None
    assert conn.committed is True


@dataclass
class _SharedStore:
    lineage_lock: threading.Lock = field(default_factory=threading.Lock)
    mutex: threading.Lock = field(default_factory=threading.Lock)
    events: list[StrategyOwnedInventoryEventV1] = field(default_factory=lambda: [_buy()])
    facts: list[StrategyOwnedFillReconciliationFactV1] = field(default_factory=list)


class _LockCursor:
    def __init__(self, conn: "_TxConn") -> None:
        self.conn = conn
        self.lock_query = False

    def execute(self, sql: str, _params=()):
        if "FROM strategy_owned_inventory_event_v1" not in sql or "FOR UPDATE" not in sql:
            raise AssertionError(f"unexpected SQL in lock cursor: {sql}")
        self.conn.store.lineage_lock.acquire()
        self.conn.lock_held = True
        self.lock_query = True
        return self

    def fetchall(self):
        return [{"strategy_owned_inventory_event_id": 1}] if self.lock_query else []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _TxConn:
    def __init__(self, store: _SharedStore) -> None:
        self.store = store
        self.pending_events: list[StrategyOwnedInventoryEventV1] = []
        self.pending_facts: list[StrategyOwnedFillReconciliationFactV1] = []
        self.lock_held = False

    def cursor(self):
        return _LockCursor(self)

    def commit(self) -> None:
        with self.store.mutex:
            self.store.facts.extend(self.pending_facts)
            self.store.events.extend(self.pending_events)
        self.pending_facts.clear()
        self.pending_events.clear()
        self._release()

    def rollback(self) -> None:
        self.pending_facts.clear()
        self.pending_events.clear()
        self._release()

    def _release(self) -> None:
        if self.lock_held:
            self.lock_held = False
            self.store.lineage_lock.release()


def test_concurrent_reductions_serialize_and_second_sees_reduced_owned_quantity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _SharedStore()
    barrier = threading.Barrier(2)
    results: list[str] = []
    results_lock = threading.Lock()

    def load_facts(conn: _TxConn, **_kwargs):
        with store.mutex:
            return tuple(store.facts + conn.pending_facts)

    def load_events(conn: _TxConn, **_kwargs):
        with store.mutex:
            return tuple(store.events + conn.pending_events)

    def append_fact(conn: _TxConn, *, fact):
        conn.pending_facts.append(fact)

    def append_event(conn: _TxConn, *, event):
        conn.pending_events.append(event)

    monkeypatch.setattr(persistence, "load_strategy_owned_fill_reconciliation_facts_v1", load_facts)
    monkeypatch.setattr(persistence, "load_strategy_owned_inventory_events_v1", load_events)
    monkeypatch.setattr(persistence, "append_strategy_owned_fill_reconciliation_fact_v1", append_fact)
    monkeypatch.setattr(persistence, "append_strategy_owned_inventory_event_v1", append_event)

    def worker(order: str) -> None:
        conn = _TxConn(store)
        barrier.wait()
        try:
            persistence.reconcile_and_persist_fib_map_bound_exit_paper_fill_v1(
                conn,
                identity=_identity(order=order),
                evidence=_evidence(order=order, qty=Decimal("3")),
            )
        except StrategyOwnedReductionAuthorizationError:
            outcome = "DENIED"
        else:
            outcome = "COMMITTED"
        with results_lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=worker, args=("a",)),
        threading.Thread(target=worker, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert sorted(results) == ["COMMITTED", "DENIED"]
    sell_events = [event for event in store.events if event.side == "SELL"]
    assert len(sell_events) == 1
    assert sell_events[0].filled_base_quantity == Decimal("3")
