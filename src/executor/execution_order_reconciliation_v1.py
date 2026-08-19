"""One side-neutral, query-only reconciliation path for executor legs."""
from __future__ import annotations

from typing import Protocol

from src.executor.broker_ack_classification_v1 import (
    ACCEPTED_ACK_STATES,
    CLOSED_ACK_STATES,
    BrokerAckStateV1,
    OrderAckV1,
)
from src.executor.execution_claim_v1 import ExecutionClaimLostError
from src.executor.execution_leg_v1 import (
    RECONCILIATION_REQUIRED,
    SUBMISSION_UNCERTAIN,
    ExecutionLegRepositoryV1,
    ExecutionLegV1,
)


class OrderLookupAdapter(Protocol):
    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAckV1 | None: ...


def reconcile_execution_leg(
    *,
    leg: ExecutionLegV1,
    adapter: OrderLookupAdapter,
    repository: ExecutionLegRepositoryV1,
) -> ExecutionLegV1:
    """Resolve an uncertain leg without ever rearming or posting it."""
    if leg.state not in {SUBMISSION_UNCERTAIN, RECONCILIATION_REQUIRED}:
        return leg
    try:
        found = adapter.find_order_by_client_order_id(
            market=leg.market,
            client_order_id=leg.client_order_id,
        )
    except ExecutionClaimLostError:
        raise
    except Exception:
        return _current(repository, leg)
    if found is None:
        if leg.state == SUBMISSION_UNCERTAIN:
            return repository.mark_reconciliation_required(leg.execution_leg_id or 0)
        return _current(repository, leg)
    return persist_order_ack(
        leg=leg,
        ack=found,
        repository=repository,
        from_reconciliation=True,
    )


def persist_order_ack(
    *,
    leg: ExecutionLegV1,
    ack: object,
    repository: ExecutionLegRepositoryV1,
    from_reconciliation: bool = False,
) -> ExecutionLegV1:
    if not isinstance(ack, OrderAckV1) or not isinstance(ack.state, BrokerAckStateV1):
        return _current(repository, leg) if from_reconciliation else repository.mark_uncertain(leg.execution_leg_id or 0)
    if ack.state in ACCEPTED_ACK_STATES:
        if not isinstance(ack.broker_order_id, str) or not ack.broker_order_id.strip():
            return _current(repository, leg) if from_reconciliation else repository.mark_uncertain(leg.execution_leg_id or 0)
        return repository.persist_accepted(
            leg.execution_leg_id or 0,
            ack.state.value,
            ack.broker_order_id,
            broker_raw_status=ack.broker_raw_status,
            restatement_reason=ack.restatement_reason,
            from_reconciliation=from_reconciliation,
        )
    if ack.state in CLOSED_ACK_STATES:
        return repository.persist_closed(
            leg.execution_leg_id or 0,
            ack.state.value,
            ack.broker_order_id,
            broker_raw_status=ack.broker_raw_status,
            restatement_reason=ack.restatement_reason,
            from_reconciliation=from_reconciliation,
        )
    return _current(repository, leg) if from_reconciliation else repository.mark_uncertain(leg.execution_leg_id or 0)


def _current(repository: ExecutionLegRepositoryV1, leg: ExecutionLegV1) -> ExecutionLegV1:
    current = repository.find(leg.execution_leg_id or 0)
    if current is None:
        raise LookupError("EXECUTION_LEG_NOT_FOUND")
    return current
