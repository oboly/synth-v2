"""Injected one-cycle composition root for the generic shared executor.

This module deliberately constructs no venue client. Deployment supplies an
adapter after its own runtime/authority wiring; tests supply a fake adapter.
"""
from __future__ import annotations

from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1
from src.executor.execution_leg_v1 import ExecutionLegRepositoryV1
from src.executor.execution_submission_orchestrator_v1 import OrderPlacementAdapter
from src.executor.shared_execution_consumer_v1 import (
    SharedExecutionConsumerResultV1,
    SharedExecutionConsumerV1,
)


def run_shared_execution_consumer_once_v1(
    *,
    handoff_repository: ExecutionHandoffRepositoryV1,
    leg_repository: ExecutionLegRepositoryV1,
    adapter: OrderPlacementAdapter,
    operator_id: int,
    worker_id: str,
    runtime_owner: str,
    executor_mode: str = "DRY_RUN",
    limit: int = 100,
) -> tuple[SharedExecutionConsumerResultV1, ...]:
    return SharedExecutionConsumerV1(
        handoff_repository=handoff_repository,
        leg_repository=leg_repository,
        adapter=adapter,
        operator_id=operator_id,
        worker_id=worker_id,
        runtime_owner=runtime_owner,
    ).consume_once(executor_mode=executor_mode, limit=limit)
