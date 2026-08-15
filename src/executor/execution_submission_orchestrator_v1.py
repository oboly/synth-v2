"""One injected, side-neutral, crash-safe shared executor path."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from src.executor.broker_ack_classification_v1 import OrderAckV1
from src.executor.execution_client_order_id_v1 import derive_execution_client_order_id
from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1, ExecutionHandoffV1
from src.executor.execution_leg_v1 import (
    ACCEPTED_STATES,
    PREPARED,
    RECONCILIATION_REQUIRED,
    SUBMISSION_UNCERTAIN,
    ExecutionLegConflictError,
    ExecutionLegRepositoryV1,
    ExecutionLegV1,
)
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1
from src.executor.execution_order_reconciliation_v1 import persist_order_ack, reconcile_execution_leg


class OrderPlacementAdapter(Protocol):
    def place_order(
        self,
        *,
        market: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_order_id: str,
        operator_id: int,
    ) -> OrderAckV1: ...
    def find_order_by_client_order_id(self, *, market: str, client_order_id: str) -> OrderAckV1 | None: ...


@dataclass(frozen=True)
class ExecutionSubmissionResultV1:
    handoff_id: int
    leg_states: tuple[str, ...]
    stopped_reason: str | None


def _same_handoff(left: ExecutionHandoffV1, right: ExecutionHandoffV1) -> bool:
    return left == right


def _validated_persisted_handoff(handoff: ExecutionHandoffV1, plan: ApprovedExecutionPlanV1, repository: ExecutionHandoffRepositoryV1) -> ExecutionHandoffV1:
    if handoff.handoff_id is None:
        raise ValueError("HANDOFF_NOT_PERSISTED")
    persisted = repository.find(handoff.handoff_id)
    if persisted is None:
        raise ValueError("HANDOFF_NOT_FOUND")
    if not _same_handoff(handoff, persisted):
        raise ValueError("HANDOFF_OBJECT_IDENTITY_MISMATCH")
    recomputed = ApprovedExecutionPlanV1(plan.plan_source, plan.plan_reference_id, plan.trading_account_id, plan.venue, plan.market, plan.side, plan.legs)
    if plan.content_hash != recomputed.content_hash:
        raise ValueError("PLAN_HASH_INVALID")
    if (persisted.plan_source, persisted.plan_reference_id, persisted.plan_content_hash, persisted.trading_account_id, persisted.venue, persisted.market, persisted.side) != (plan.plan_source, plan.plan_reference_id, plan.content_hash, plan.trading_account_id, plan.venue, plan.market, plan.side):
        raise ValueError("HANDOFF_PLAN_IDENTITY_MISMATCH")
    return persisted


def submit_execution_plan(
    *,
    handoff: ExecutionHandoffV1,
    plan: ApprovedExecutionPlanV1,
    operator_id: int,
    handoff_repository: ExecutionHandoffRepositoryV1,
    leg_repository: ExecutionLegRepositoryV1,
    adapter: OrderPlacementAdapter,
) -> ExecutionSubmissionResultV1:
    if isinstance(operator_id, bool) or not isinstance(operator_id, int) or operator_id <= 0:
        raise ValueError("operator_id must be a positive integer")
    persisted = _validated_persisted_handoff(handoff, plan, handoff_repository)
    states: list[str] = []
    for item in plan.legs:
        client_order_id = derive_execution_client_order_id(
            handoff_id=persisted.handoff_id or 0,
            plan_source=plan.plan_source,
            plan_reference_id=plan.plan_reference_id,
            plan_content_hash=plan.content_hash,
            leg_index=item.leg_index,
            trading_account_id=plan.trading_account_id,
            venue=plan.venue,
            market=plan.market,
        )
        leg, _ = leg_repository.persist_prepared(
            ExecutionLegV1(
                None,
                persisted.handoff_id or 0,
                item.leg_index,
                plan.trading_account_id,
                plan.venue,
                plan.market,
                item.side,
                client_order_id,
                operator_id,
                item.price,
                item.quantity,
            )
        )
        leg = _resolve_leg(leg, adapter, leg_repository)
        states.append(leg.state)
        if leg.state not in ACCEPTED_STATES:
            return ExecutionSubmissionResultV1(persisted.handoff_id or 0, tuple(states), leg.state)
    return ExecutionSubmissionResultV1(persisted.handoff_id or 0, tuple(states), None)


def _resolve_leg(leg: ExecutionLegV1, adapter: OrderPlacementAdapter, repository: ExecutionLegRepositoryV1) -> ExecutionLegV1:
    if leg.state in ACCEPTED_STATES:
        return leg
    if leg.state in {SUBMISSION_UNCERTAIN, RECONCILIATION_REQUIRED}:
        return reconcile_execution_leg(leg=leg, adapter=adapter, repository=repository)
    if leg.state != PREPARED:
        return leg
    leg, won = repository.claim_submission(leg.execution_leg_id or 0)
    if not won:
        return leg
    try:
        ack = adapter.place_order(
            market=leg.market,
            side=leg.side,
            price=leg.price,
            quantity=leg.quantity,
            client_order_id=leg.client_order_id,
            operator_id=leg.operator_id,
        )
    except Exception:
        try:
            return repository.mark_uncertain(leg.execution_leg_id or 0)
        except ExecutionLegConflictError:
            current = repository.find(leg.execution_leg_id or 0)
            if current is not None and current.state == RECONCILIATION_REQUIRED:
                return current
            raise
    try:
        return persist_order_ack(leg=leg, ack=ack, repository=repository)
    except ExecutionLegConflictError:
        # A concurrent invocation is required to reconcile any persisted
        # SUBMISSION_UNCERTAIN leg. If its authoritative lookup reports no
        # order while this winner's POST is still in flight, the persisted
        # RECONCILIATION_REQUIRED dead end wins. Never overwrite that state
        # with a late acknowledgement and never issue a second POST.
        current = repository.find(leg.execution_leg_id or 0)
        if current is not None and current.state == RECONCILIATION_REQUIRED:
            return current
        raise
