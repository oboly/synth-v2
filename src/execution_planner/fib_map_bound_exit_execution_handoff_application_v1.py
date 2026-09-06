"""Issue #753 Phase B3: handoff application seam, mirroring #392's exit lane.

Composes the pure adapter
(``fib_map_bound_exit_execution_handoff_adapter_v1``) with the shared #206
executor handoff repository. Reuses the existing generic account_mode ->
executor_mode mapping (``resolve_automatic_exit_executor_mode_v1``) rather
than duplicating a second copy of that mapping: the mapping is side-neutral
runtime-mode selection logic, not automatic-exit-specific policy. This
module never duplicates the executor mode permission logic, credential
binding, LIVE authority, or kill-switch checks that
``ExecutionHandoffRepositoryV1`` already owns.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from typing import Final

from src.execution_planner.automatic_exit_execution_handoff_application_v1 import (
    resolve_automatic_exit_executor_mode_v1,
)
from src.execution_planner.fib_map_bound_exit_execution_handoff_adapter_v1 import (
    adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1,
)
from src.execution_planner.fib_map_bound_exit_planner_v1 import FibMapBoundExitPlanV1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_DRY_RUN,
    RUNTIME_MODE_LIVE,
    RUNTIME_MODE_PAPER,
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)

# Re-exported for callers so this module remains the single fib-map-bound
# import site for account_mode -> executor_mode resolution, without a
# second parallel implementation of the mapping.
resolve_fib_map_bound_exit_executor_mode_v1 = resolve_automatic_exit_executor_mode_v1

_SUPPORTED_EXECUTOR_MODES: Final[frozenset[str]] = frozenset(
    {RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER, RUNTIME_MODE_LIVE}
)


class FibMapBoundExitExecutorModeError(ValueError):
    """Fail-closed rejection for an unsupported/unmapped executor mode."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
    *,
    plan: FibMapBoundExitPlanV1,
    executor_mode: str,
    executor_identity: str,
    runtime_owner: str,
    handoff_repository: ExecutionHandoffRepositoryV1,
) -> ExecutionHandoffV1:
    """Adapt an approved in-memory FibMapBoundExitPlanV1 and hand it off.

    Consumes the in-memory plan produced by ``build_fib_map_bound_exit_plan_v1``
    in the same evaluation cycle. Performs exactly two steps: (1) pure
    adapter conversion, (2) selection of the existing #206 handoff method
    for ``executor_mode``. Fails closed on any unsupported mode. Because the
    adapter derives a deterministic ``plan_reference_id`` from the exact
    decision/binding lineage, a duplicate evaluation of the same decision
    resolves to the same handoff row via the shared repository's existing
    identity-conflict/dedup path instead of creating a duplicate executable
    handoff. Does not pre-check LIVE authority, kill switch, or credential
    scope -- those remain exclusively #206 executor substrate
    responsibilities inside ``ExecutionHandoffRepositoryV1``.
    """
    if executor_mode not in _SUPPORTED_EXECUTOR_MODES:
        raise FibMapBoundExitExecutorModeError("UNSUPPORTED_EXECUTOR_MODE")

    approved_plan = adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)

    if executor_mode == RUNTIME_MODE_LIVE:
        return handoff_repository.intake_live_authorized(
            plan=approved_plan,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
        )
    return handoff_repository.intake(
        plan=approved_plan,
        executor_mode=executor_mode,
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
    )
