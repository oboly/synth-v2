"""Generic persisted-handoff consumer; it hydrates intent and never replans."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1, ExecutionHandoffV1
from src.executor.execution_claim_v1 import ExecutionClaimLostError
from src.executor.execution_leg_v1 import RECONCILIATION_REQUIRED, SUBMISSION_UNCERTAIN, ExecutionLegRepositoryV1
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1, ExecutionPlanLegV1
from src.executor.execution_submission_orchestrator_v1 import OrderPlacementAdapter, submit_execution_plan


class OrderPlacementAdapterFactory(Protocol):
    """Build an adapter for one exact persisted handoff after its claim wins."""

    def adapter_for_handoff(self, handoff: ExecutionHandoffV1) -> OrderPlacementAdapter: ...


def hydrate_approved_execution_plan(*, handoff: ExecutionHandoffV1, repository: ExecutionHandoffRepositoryV1) -> ApprovedExecutionPlanV1:
    if handoff.handoff_id is None:
        raise ValueError("HANDOFF_NOT_PERSISTED")
    legs = repository.load_immutable_legs(handoff.handoff_id)
    plan = ApprovedExecutionPlanV1(
        plan_source=handoff.plan_source, plan_reference_id=handoff.plan_reference_id,
        trading_account_id=handoff.trading_account_id, venue=handoff.venue,
        market=handoff.market, side=handoff.side,
        legs=tuple(
            ExecutionPlanLegV1(leg.leg_index, leg.side, leg.price, leg.quantity)
            for leg in sorted(legs, key=lambda leg: leg.leg_index)
        ),
    )
    if plan.content_hash != handoff.plan_content_hash:
        raise ValueError("PERSISTED_HANDOFF_PLAN_HASH_MISMATCH")
    return plan


@dataclass(frozen=True)
class SharedExecutionConsumerResultV1:
    handoff_id: int
    stopped_reason: str | None


@dataclass
class _ClaimHeartbeatAdapter:
    adapter: OrderPlacementAdapter
    handoff_repository: ExecutionHandoffRepositoryV1
    handoff_id: int
    claim_token: str
    lease_seconds: int

    def _renew(self) -> None:
        if not self.handoff_repository.renew_claim(
            handoff_id=self.handoff_id,
            claim_token=self.claim_token,
            lease_seconds=self.lease_seconds,
        ):
            raise ExecutionClaimLostError(ExecutionClaimLostError.reason_code)

    def place_order(self, **kwargs):
        self._renew()
        return self.adapter.place_order(**kwargs)

    def before_submission_attempt(self) -> None:
        self._renew()

    def find_order_by_client_order_id(self, **kwargs):
        self._renew()
        return self.adapter.find_order_by_client_order_id(**kwargs)


@dataclass
class SharedExecutionConsumerV1:
    handoff_repository: ExecutionHandoffRepositoryV1
    leg_repository: ExecutionLegRepositoryV1
    adapter: OrderPlacementAdapter | None
    operator_id: int
    worker_id: str
    runtime_owner: str
    executor_identity: str
    adapter_factory: OrderPlacementAdapterFactory | None = None

    def __post_init__(self) -> None:
        if (self.adapter is None) == (self.adapter_factory is None):
            raise ValueError("EXACTLY_ONE_ORDER_ADAPTER_OR_FACTORY_REQUIRED")

    def consume_once(self, *, executor_mode: str = "DRY_RUN", limit: int = 100, lease_seconds: int = 60) -> tuple[SharedExecutionConsumerResultV1, ...]:
        outcomes: list[SharedExecutionConsumerResultV1] = []
        for handoff in self.handoff_repository.discover_eligible(
            executor_mode=executor_mode,
            runtime_owner=self.runtime_owner,
            executor_identity=self.executor_identity,
            limit=limit,
        ):
            if handoff.handoff_id is None:
                continue
            if handoff.executor_identity != self.executor_identity:
                raise ValueError("PERSISTED_HANDOFF_EXECUTOR_IDENTITY_MISMATCH")
            token = str(uuid4())
            if not self.handoff_repository.claim(handoff_id=handoff.handoff_id, claim_token=token, claimed_by=self.worker_id):
                continue
            completed = False
            try:
                if not self.handoff_repository.renew_claim(handoff_id=handoff.handoff_id, claim_token=token, lease_seconds=lease_seconds):
                    raise ExecutionClaimLostError(ExecutionClaimLostError.reason_code)
                plan = hydrate_approved_execution_plan(handoff=handoff, repository=self.handoff_repository)
                adapter = (
                    self.adapter_factory.adapter_for_handoff(handoff)
                    if self.adapter_factory is not None
                    else self.adapter
                )
                if adapter is None:
                    raise AssertionError("adapter required after consumer validation")
                result = submit_execution_plan(handoff=handoff, plan=plan, operator_id=self.operator_id, handoff_repository=self.handoff_repository, leg_repository=self.leg_repository, adapter=_ClaimHeartbeatAdapter(adapter, self.handoff_repository, handoff.handoff_id, token, lease_seconds))
                outcomes.append(SharedExecutionConsumerResultV1(result.handoff_id, result.stopped_reason))
                completed = result.stopped_reason not in {SUBMISSION_UNCERTAIN, RECONCILIATION_REQUIRED}
            except ExecutionClaimLostError:
                outcomes.append(SharedExecutionConsumerResultV1(handoff.handoff_id, ExecutionClaimLostError.reason_code))
            finally:
                self.handoff_repository.finish_claim(handoff_id=handoff.handoff_id, claim_token=token, completed=completed)
        return tuple(outcomes)
