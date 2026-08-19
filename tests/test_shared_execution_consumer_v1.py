from dataclasses import replace
from decimal import Decimal

import pytest

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1
from src.executor.execution_handoff_v1 import ExecutionHandoffPlanLegV1, ExecutionHandoffV1
from src.executor.execution_leg_v1 import ACTIVE, PREPARED, SUBMISSION_UNCERTAIN, ExecutionLegV1
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1, ExecutionPlanLegV1
from src.executor.run_shared_execution_consumer_once_v1 import run_shared_execution_consumer_once_v1
from src.executor.shared_execution_consumer_v1 import hydrate_approved_execution_plan


def plan(reference: str = "p1") -> ApprovedExecutionPlanV1:
    return ApprovedExecutionPlanV1("SOURCE", reference, 7, "bitvavo", "BTC-EUR", "SELL", (
        ExecutionPlanLegV1(1, "SELL", Decimal("101.20"), Decimal("0.11")),
        ExecutionPlanLegV1(2, "SELL", Decimal("102.30"), Decimal("0.22")),
    ))


def handoff(value: ApprovedExecutionPlanV1, ident: int = 1) -> ExecutionHandoffV1:
    return ExecutionHandoffV1(ident, value.plan_source, value.plan_reference_id, value.content_hash, 7, "bitvavo", "BTC-EUR", "SELL", "DRY_RUN", "worker", "devlap", 2)


class FakeHandoffs:
    def __init__(self, values: list[ExecutionHandoffV1]) -> None:
        self.values = values
        self.claimed: set[int] = set()
        self.finished: list[tuple[int, bool]] = []

    def find(self, ident: int):
        return next((item for item in self.values if item.handoff_id == ident), None)

    def discover_eligible(self, *, executor_mode, runtime_owner, limit):
        assert executor_mode == "DRY_RUN" and runtime_owner == "devlap"
        return tuple(sorted(self.values, key=lambda item: item.handoff_id or 0)[:limit])

    def claim(self, *, handoff_id, **_kwargs):
        if handoff_id in self.claimed:
            return False
        self.claimed.add(handoff_id)
        return True

    def renew_claim(self, *, handoff_id, **_kwargs):
        return handoff_id in self.claimed

    def finish_claim(self, *, handoff_id, completed, **_kwargs):
        self.finished.append((handoff_id, completed))
        if not completed:
            self.claimed.discard(handoff_id)
        return True

    def load_immutable_legs(self, handoff_id):
        item = self.find(handoff_id)
        assert item is not None
        source = plan(item.plan_reference_id)
        return tuple(
            ExecutionHandoffPlanLegV1(handoff_id, leg.leg_index, source.trading_account_id, source.venue, source.market, leg.side, leg.price, leg.quantity)
            for leg in reversed(source.legs)
        )


class FakeLegs:
    def __init__(self) -> None:
        self.rows = {}
        self.next_id = 1

    def persist_prepared(self, leg):
        key = (leg.handoff_id, leg.leg_index)
        if key in self.rows:
            return self.rows[key], False
        saved = replace(leg, execution_leg_id=self.next_id)
        self.next_id += 1
        self.rows[key] = saved
        return saved, True

    def claim_submission(self, ident):
        key = next(key for key, leg in self.rows.items() if leg.execution_leg_id == ident)
        leg = self.rows[key]
        if leg.state != PREPARED:
            return leg, False
        self.rows[key] = replace(leg, state=SUBMISSION_UNCERTAIN)
        return self.rows[key], True

    def mark_uncertain(self, ident): return self.find(ident)
    def mark_reconciliation_required(self, ident): return self.find(ident)
    def find(self, ident): return next((leg for leg in self.rows.values() if leg.execution_leg_id == ident), None)
    def persist_accepted(self, ident, state, broker_order_id, **_kwargs):
        key = next(key for key, leg in self.rows.items() if leg.execution_leg_id == ident)
        self.rows[key] = replace(self.rows[key], state=state, broker_order_id=broker_order_id)
        return self.rows[key]
    def persist_closed(self, ident, state, broker_order_id=None, **_kwargs): return self.persist_accepted(ident, state, broker_order_id or "closed")


class FakeAdapter:
    def __init__(self, *, timeout_once=False): self.timeout_once, self.place_calls, self.lookup_calls = timeout_once, [], []
    def place_order(self, **kwargs):
        self.place_calls.append(kwargs)
        if self.timeout_once and len(self.place_calls) == 1: raise TimeoutError("synthetic only")
        return OrderAckV1("fake-" + kwargs["client_order_id"], BrokerAckStateV1.ACTIVE)
    def find_order_by_client_order_id(self, **kwargs):
        self.lookup_calls.append(kwargs)
        return OrderAckV1("fake-found", BrokerAckStateV1.ACTIVE)


def test_hydration_preserves_ordered_immutable_fields_and_hash() -> None:
    value = plan()
    repo = FakeHandoffs([handoff(value)])
    hydrated = hydrate_approved_execution_plan(handoff=handoff(value), repository=repo)
    assert hydrated == value
    assert tuple(leg.leg_index for leg in hydrated.legs) == (1, 2)


def test_hash_mismatch_fails_closed() -> None:
    value = plan()
    repo = FakeHandoffs([replace(handoff(value), plan_content_hash="0" * 64)])
    with pytest.raises(ValueError, match="PLAN_HASH_MISMATCH"):
        hydrate_approved_execution_plan(handoff=repo.values[0], repository=repo)


def test_consumer_orders_handoffs_skips_claim_loser_and_reuses_submission() -> None:
    first, second = handoff(plan("p1"), 2), handoff(plan("p2"), 1)
    repo, legs, adapter = FakeHandoffs([first, second]), FakeLegs(), FakeAdapter()
    repo.claimed.add(2)
    outcomes = run_shared_execution_consumer_once_v1(handoff_repository=repo, leg_repository=legs, adapter=adapter, operator_id=9, worker_id="w", runtime_owner="devlap")
    assert [outcome.handoff_id for outcome in outcomes] == [1]
    assert len(adapter.place_calls) == 2
    assert repo.finished == [(1, True)]


def test_uncertain_restart_reconciles_without_duplicate_fake_post() -> None:
    value = handoff(plan(), 1)
    repo, legs, adapter = FakeHandoffs([value]), FakeLegs(), FakeAdapter(timeout_once=True)
    first = run_shared_execution_consumer_once_v1(handoff_repository=repo, leg_repository=legs, adapter=adapter, operator_id=9, worker_id="w", runtime_owner="devlap")
    second = run_shared_execution_consumer_once_v1(handoff_repository=repo, leg_repository=legs, adapter=adapter, operator_id=9, worker_id="w", runtime_owner="devlap")
    assert first[0].stopped_reason == SUBMISSION_UNCERTAIN
    assert second[0].stopped_reason is None
    assert len(adapter.place_calls) == 2  # second leg only; first was lookup-resolved
    assert len(adapter.lookup_calls) == 1


def test_claim_loss_before_post_does_not_create_broker_uncertainty() -> None:
    value = handoff(plan(), 1)
    repo, legs, adapter = FakeHandoffs([value]), FakeLegs(), FakeAdapter()
    renewals = iter((True, False))
    repo.renew_claim = lambda **_kwargs: next(renewals)
    result = run_shared_execution_consumer_once_v1(handoff_repository=repo, leg_repository=legs, adapter=adapter, operator_id=9, worker_id="w", runtime_owner="devlap")
    assert result[0].stopped_reason == "EXECUTION_HANDOFF_CLAIM_LOST"
    assert adapter.place_calls == []
    assert legs.rows[(1, 1)].state == PREPARED


def test_claim_loss_before_reconciliation_lookup_does_not_call_delegate() -> None:
    value = handoff(plan(), 1)
    repo, legs, adapter = FakeHandoffs([value]), FakeLegs(), FakeAdapter(timeout_once=True)
    first = run_shared_execution_consumer_once_v1(handoff_repository=repo, leg_repository=legs, adapter=adapter, operator_id=9, worker_id="w", runtime_owner="devlap")
    assert first[0].stopped_reason == SUBMISSION_UNCERTAIN
    renewals = iter((True, False))
    repo.renew_claim = lambda **_kwargs: next(renewals)
    second = run_shared_execution_consumer_once_v1(handoff_repository=repo, leg_repository=legs, adapter=adapter, operator_id=9, worker_id="w", runtime_owner="devlap")
    assert second[0].stopped_reason == "EXECUTION_HANDOFF_CLAIM_LOST"
    assert adapter.lookup_calls == []
    assert legs.rows[(1, 1)].state == SUBMISSION_UNCERTAIN
