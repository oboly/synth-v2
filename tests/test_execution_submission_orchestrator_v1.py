from __future__ import annotations

import threading
from dataclasses import replace
from decimal import Decimal

import pytest

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1
from src.executor.execution_handoff_v1 import ExecutionHandoffV1
from src.executor.execution_leg_v1 import (
    ACCEPTED_STATES,
    ACTIVE,
    CANCELED,
    EXPIRED,
    FILLED,
    PARTIALLY_FILLED,
    PREPARED,
    RECONCILIATION_REQUIRED,
    REJECTED,
    SUBMISSION_UNCERTAIN,
    ExecutionLegConflictError,
    ExecutionLegV1,
)
from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanV1,
    ExecutionPlanLegV1,
)
from src.executor.execution_submission_orchestrator_v1 import submit_execution_plan
from src.executor.stub_order_adapter_v1 import StubOrderPlacementAdapterV1


class MemoryHandoffRepository:
    def __init__(self, handoff: ExecutionHandoffV1) -> None:
        self.handoff = handoff

    def find(self, handoff_id: int) -> ExecutionHandoffV1 | None:
        return self.handoff if self.handoff.handoff_id == handoff_id else None


class MemoryLegRepository:
    """Thread-safe test double with the production repository's CAS semantics."""

    def __init__(self) -> None:
        self.rows: dict[int, ExecutionLegV1] = {}
        self.ids_by_key: dict[tuple[int, int], int] = {}
        self.next_id = 1
        self.lock = threading.Lock()

    def persist_prepared(self, leg: ExecutionLegV1) -> tuple[ExecutionLegV1, bool]:
        with self.lock:
            key = (leg.handoff_id, leg.leg_index)
            existing_id = self.ids_by_key.get(key)
            if existing_id is not None:
                existing = self.rows[existing_id]
                identity_fields = (
                    "handoff_id",
                    "leg_index",
                    "trading_account_id",
                    "venue",
                    "market",
                    "side",
                    "client_order_id",
                    "operator_id",
                    "price",
                    "quantity",
                )
                if any(
                    getattr(existing, field_name) != getattr(leg, field_name)
                    for field_name in identity_fields
                ):
                    raise ExecutionLegConflictError("EXECUTION_LEG_IDENTITY_CONFLICT")
                return existing, False
            leg_id = self.next_id
            self.next_id += 1
            persisted = replace(leg, execution_leg_id=leg_id)
            self.rows[leg_id] = persisted
            self.ids_by_key[key] = leg_id
            return persisted, True

    def claim_submission(self, leg_id: int) -> tuple[ExecutionLegV1, bool]:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state != PREPARED:
                return leg, False
            claimed = replace(leg, state=SUBMISSION_UNCERTAIN)
            self.rows[leg_id] = claimed
            return claimed, True

    def mark_reconciliation_required(self, leg_id: int) -> ExecutionLegV1:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state == RECONCILIATION_REQUIRED:
                return leg
            if leg.state != SUBMISSION_UNCERTAIN:
                raise ExecutionLegConflictError("RECONCILIATION_REQUIRED_TRANSITION_CONFLICT")
            resolved = replace(leg, state=RECONCILIATION_REQUIRED)
            self.rows[leg_id] = resolved
            return resolved

    def mark_uncertain(self, leg_id: int) -> ExecutionLegV1:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state != SUBMISSION_UNCERTAIN:
                raise ExecutionLegConflictError("SUBMISSION_UNCERTAIN_TRANSITION_CONFLICT")
            return leg

    def persist_accepted(
        self, leg_id: int, state: str, broker_order_id: str
    ) -> ExecutionLegV1:
        assert state in ACCEPTED_STATES
        return self._resolve(leg_id, state, broker_order_id)

    def persist_closed(
        self, leg_id: int, state: str, broker_order_id: str | None = None
    ) -> ExecutionLegV1:
        return self._resolve(leg_id, state, broker_order_id)

    def _resolve(
        self, leg_id: int, state: str, broker_order_id: str | None
    ) -> ExecutionLegV1:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state == state:
                return leg
            if leg.state != SUBMISSION_UNCERTAIN:
                raise ExecutionLegConflictError("EXECUTION_LEG_RESOLUTION_CONFLICT")
            resolved = replace(leg, state=state, broker_order_id=broker_order_id)
            self.rows[leg_id] = resolved
            return resolved

    def find(self, leg_id: int) -> ExecutionLegV1 | None:
        with self.lock:
            return self.rows.get(leg_id)

    def by_client_order_id(self, client_order_id: str) -> ExecutionLegV1:
        with self.lock:
            return next(
                leg for leg in self.rows.values() if leg.client_order_id == client_order_id
            )


def make_plan(side: str = "BUY", leg_count: int = 1) -> ApprovedExecutionPlanV1:
    return ApprovedExecutionPlanV1(
        plan_source="AUTOMATIC_TEST_PLAN_V1",
        plan_reference_id=f"{side.lower()}-plan-1",
        trading_account_id=17,
        venue="bitvavo",
        market="BTC-EUR",
        side=side,
        legs=tuple(
            ExecutionPlanLegV1(
                leg_index=index,
                side=side,
                price=Decimal("100") + index,
                quantity=Decimal("0.01"),
            )
            for index in range(1, leg_count + 1)
        ),
    )


def make_handoff(plan: ApprovedExecutionPlanV1) -> ExecutionHandoffV1:
    return ExecutionHandoffV1(
        handoff_id=41,
        plan_source=plan.plan_source,
        plan_reference_id=plan.plan_reference_id,
        plan_content_hash=plan.content_hash,
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        side=plan.side,
        executor_mode="PAPER",
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        executor_credential_binding_id=9,
    )


def submit(
    plan: ApprovedExecutionPlanV1,
    leg_repository: MemoryLegRepository,
    adapter: object,
    handoff: ExecutionHandoffV1 | None = None,
):
    canonical_handoff = handoff or make_handoff(plan)
    return submit_execution_plan(
        handoff=canonical_handoff,
        plan=plan,
        operator_id=73,
        handoff_repository=MemoryHandoffRepository(make_handoff(plan)),
        leg_repository=leg_repository,
        adapter=adapter,
    )


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_buy_and_sell_use_the_same_orchestrator(side: str) -> None:
    adapter = StubOrderPlacementAdapterV1()
    result = submit(make_plan(side), MemoryLegRepository(), adapter)
    assert result.leg_states == (ACTIVE,)
    assert adapter.place_call_count == 1


@pytest.mark.parametrize(
    ("ack_state", "persisted_state"),
    [
        (BrokerAckStateV1.ACTIVE, ACTIVE),
        (BrokerAckStateV1.PARTIALLY_FILLED, PARTIALLY_FILLED),
        (BrokerAckStateV1.FILLED, FILLED),
    ],
)
def test_only_accepted_ack_states_continue(
    ack_state: BrokerAckStateV1, persisted_state: str
) -> None:
    plan = make_plan(leg_count=2)
    repository = MemoryLegRepository()
    adapter = StubOrderPlacementAdapterV1()
    # The first client ID is discovered on the first place call, so use an adapter wrapper.
    original = adapter.place_order

    def place(**kwargs):
        if adapter.place_call_count == 0:
            adapter.place_call_count += 1
            return OrderAckV1("accepted-1", ack_state)
        return original(**kwargs)

    adapter.place_order = place  # type: ignore[method-assign]
    result = submit(plan, repository, adapter)
    assert result.leg_states == (persisted_state, ACTIVE)
    assert result.stopped_reason is None
    assert adapter.place_call_count == 2


@pytest.mark.parametrize(
    "ack_state", [BrokerAckStateV1.CANCELED, BrokerAckStateV1.EXPIRED, BrokerAckStateV1.REJECTED]
)
def test_closed_ack_stops_later_legs_and_is_not_active(
    ack_state: BrokerAckStateV1,
) -> None:
    plan = make_plan(leg_count=2)
    adapter = StubOrderPlacementAdapterV1()

    def closed(**_kwargs):
        adapter.place_call_count += 1
        return OrderAckV1("closed-1", ack_state)

    adapter.place_order = closed  # type: ignore[method-assign]
    result = submit(plan, MemoryLegRepository(), adapter)
    assert result.leg_states == (ack_state.value,)
    assert result.stopped_reason == ack_state.value
    assert adapter.place_call_count == 1


@pytest.mark.parametrize(
    "ack",
    [OrderAckV1(None, BrokerAckStateV1.AMBIGUOUS), OrderAckV1("", BrokerAckStateV1.ACTIVE)],
)
def test_ambiguous_or_malformed_ack_remains_uncertain(ack: OrderAckV1) -> None:
    adapter = StubOrderPlacementAdapterV1()

    def ambiguous(**_kwargs):
        adapter.place_call_count += 1
        return ack

    adapter.place_order = ambiguous  # type: ignore[method-assign]
    result = submit(make_plan(leg_count=2), MemoryLegRepository(), adapter)
    assert result.leg_states == (SUBMISSION_UNCERTAIN,)
    assert adapter.place_call_count == 1


def test_adapter_failure_leaves_uncertain_and_stops_ladder() -> None:
    adapter = StubOrderPlacementAdapterV1()

    def fail(**_kwargs):
        adapter.place_call_count += 1
        raise TimeoutError("ambiguous transport failure")

    adapter.place_order = fail  # type: ignore[method-assign]
    result = submit(make_plan(leg_count=2), MemoryLegRepository(), adapter)
    assert result.leg_states == (SUBMISSION_UNCERTAIN,)
    assert adapter.place_call_count == 1


def test_prepared_is_persisted_uncertain_before_place_order() -> None:
    plan = make_plan()
    repository = MemoryLegRepository()

    class InspectingAdapter(StubOrderPlacementAdapterV1):
        def place_order(self, **kwargs):
            assert repository.by_client_order_id(kwargs["client_order_id"]).state == SUBMISSION_UNCERTAIN
            return super().place_order(**kwargs)

    adapter = InspectingAdapter()
    submit(plan, repository, adapter)
    assert adapter.place_call_count == 1


def test_found_order_reconciles_without_a_second_post() -> None:
    plan = make_plan()
    repository = MemoryLegRepository()
    class TimeoutThenFound(StubOrderPlacementAdapterV1):
        def place_order(self, **kwargs):
            self.place_call_count += 1
            raise TimeoutError("ambiguous post")

        def find_order_by_client_order_id(self, **kwargs):
            self.lookup_call_count += 1
            return OrderAckV1("found-order", BrokerAckStateV1.ACTIVE)

    adapter = TimeoutThenFound()
    assert submit(plan, repository, adapter).stopped_reason == SUBMISSION_UNCERTAIN
    result = submit(plan, repository, adapter)
    assert result.leg_states == (ACTIVE,)
    assert adapter.place_call_count == 1
    assert adapter.lookup_call_count == 1


def test_confirmed_absent_requires_reconciliation_and_never_posts_again() -> None:
    plan = make_plan(leg_count=2)
    repository = MemoryLegRepository()

    class TimeoutThenAbsent(StubOrderPlacementAdapterV1):
        def place_order(self, **kwargs):
            self.place_call_count += 1
            raise TimeoutError("ambiguous post")

    adapter = TimeoutThenAbsent()
    assert submit(plan, repository, adapter).stopped_reason == SUBMISSION_UNCERTAIN
    assert submit(plan, repository, adapter).stopped_reason == RECONCILIATION_REQUIRED
    lookups_after_absence = adapter.lookup_call_count
    assert submit(plan, repository, adapter).stopped_reason == RECONCILIATION_REQUIRED
    assert adapter.place_call_count == 1
    assert adapter.lookup_call_count == lookups_after_absence
    assert len(repository.rows) == 1


def test_repeated_or_concurrent_invocation_cannot_post_twice() -> None:
    plan = make_plan()
    repository = MemoryLegRepository()
    entered = threading.Event()
    release = threading.Event()

    class BlockingAdapter(StubOrderPlacementAdapterV1):
        def place_order(self, **kwargs):
            self.place_call_count += 1
            entered.set()
            assert release.wait(timeout=2)
            return OrderAckV1("one-order", BrokerAckStateV1.ACTIVE)

        def find_order_by_client_order_id(self, **kwargs):
            self.lookup_call_count += 1
            raise TimeoutError("first POST still unresolved")

    adapter = BlockingAdapter()
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            submit(plan, repository, adapter)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    first = threading.Thread(target=invoke)
    first.start()
    assert entered.wait(timeout=2)
    second = threading.Thread(target=invoke)
    second.start()
    second.join(timeout=2)
    release.set()
    first.join(timeout=2)
    assert not errors
    assert adapter.place_call_count == 1

    # An accepted retry is also a no-op.
    submit(plan, repository, adapter)
    assert adapter.place_call_count == 1


def test_concurrent_confirmed_absence_wins_fail_closed_over_late_ack() -> None:
    plan = make_plan()
    repository = MemoryLegRepository()
    entered = threading.Event()
    release = threading.Event()

    class BlockingAdapter(StubOrderPlacementAdapterV1):
        def place_order(self, **kwargs):
            self.place_call_count += 1
            entered.set()
            assert release.wait(timeout=2)
            return OrderAckV1("late-order", BrokerAckStateV1.ACTIVE)

        def find_order_by_client_order_id(self, **kwargs):
            self.lookup_call_count += 1
            return None

    adapter = BlockingAdapter()
    results = []
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            results.append(submit(plan, repository, adapter))
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    winner = threading.Thread(target=invoke)
    winner.start()
    assert entered.wait(timeout=2)
    retry = threading.Thread(target=invoke)
    retry.start()
    retry.join(timeout=2)
    release.set()
    winner.join(timeout=2)

    assert not errors
    assert adapter.place_call_count == 1
    assert adapter.lookup_call_count == 1
    assert {result.stopped_reason for result in results} == {RECONCILIATION_REQUIRED}
    assert next(iter(repository.rows.values())).state == RECONCILIATION_REQUIRED


def test_concurrent_confirmed_absence_wins_over_late_adapter_exception() -> None:
    plan = make_plan()
    repository = MemoryLegRepository()
    entered = threading.Event()
    release = threading.Event()

    class BlockingAdapter(StubOrderPlacementAdapterV1):
        def place_order(self, **kwargs):
            self.place_call_count += 1
            entered.set()
            assert release.wait(timeout=2)
            raise TimeoutError("late ambiguous failure")

        def find_order_by_client_order_id(self, **kwargs):
            self.lookup_call_count += 1
            return None

    adapter = BlockingAdapter()
    results = []
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            results.append(submit(plan, repository, adapter))
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    winner = threading.Thread(target=invoke)
    winner.start()
    assert entered.wait(timeout=2)
    retry = threading.Thread(target=invoke)
    retry.start()
    retry.join(timeout=2)
    release.set()
    winner.join(timeout=2)

    assert not errors
    assert adapter.place_call_count == 1
    assert adapter.lookup_call_count == 1
    assert {result.stopped_reason for result in results} == {RECONCILIATION_REQUIRED}
    assert next(iter(repository.rows.values())).state == RECONCILIATION_REQUIRED


def test_operator_id_is_immutable_leg_identity() -> None:
    plan = make_plan()
    repository = MemoryLegRepository()
    adapter = StubOrderPlacementAdapterV1()
    submit(plan, repository, adapter)
    with pytest.raises(ExecutionLegConflictError, match="IDENTITY_CONFLICT"):
        submit_execution_plan(
            handoff=make_handoff(plan),
            plan=plan,
            operator_id=74,
            handoff_repository=MemoryHandoffRepository(make_handoff(plan)),
            leg_repository=repository,
            adapter=adapter,
        )
    assert adapter.place_call_count == 1


def test_forged_handoff_is_rejected_before_leg_or_adapter_work() -> None:
    plan = make_plan()
    persisted = make_handoff(plan)
    forged = replace(persisted, executor_identity="other-executor")

    class NoLegRepository:
        def persist_prepared(self, _leg):
            raise AssertionError("must not persist a forged handoff")

    class NoAdapter:
        def place_order(self, **_kwargs):
            raise AssertionError("must not place a forged handoff")

        def find_order_by_client_order_id(self, **_kwargs):
            raise AssertionError("must not look up a forged handoff")

    with pytest.raises(ValueError, match="HANDOFF_OBJECT_IDENTITY_MISMATCH"):
        submit_execution_plan(
            handoff=forged,
            plan=plan,
            operator_id=73,
            handoff_repository=MemoryHandoffRepository(persisted),
            leg_repository=NoLegRepository(),
            adapter=NoAdapter(),
        )
