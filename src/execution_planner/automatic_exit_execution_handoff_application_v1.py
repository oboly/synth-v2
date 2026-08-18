"""Issue #392 Phase 6 blocker A: handoff application seam.

Composes the pure adapter (``automatic_exit_execution_handoff_adapter_v1``)
with the shared #206 executor handoff repository. This is the only module
that selects between ``ExecutionHandoffRepositoryV1.intake`` (DRY_RUN/PAPER)
and ``.intake_live_authorized`` (LIVE); it never duplicates the executor
mode permission logic, credential binding, LIVE authority, or kill-switch
checks that ``ExecutionHandoffRepositoryV1`` already owns.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from typing import Final

from src.execution_planner.automatic_exit_execution_handoff_adapter_v1 import (
    adapt_automatic_exit_plan_to_approved_execution_plan_v1,
)
from src.execution_planner.automatic_exit_planner_v1 import AutomaticExitPlanV1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_DRY_RUN,
    RUNTIME_MODE_LIVE,
    RUNTIME_MODE_PAPER,
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)

ACCOUNT_MODE_PAPER: Final[str] = "paper"
ACCOUNT_MODE_LIVE: Final[str] = "live"

# The #392 runtime's account_mode is a decision_gate-facing candidate
# eligibility flag (paper vs live intent); it is never treated as executor
# operational LIVE authority. DRY_RUN is not derivable from account_mode --
# it is an explicit non-production runtime mode a caller selects directly.
_ACCOUNT_MODE_TO_EXECUTOR_MODE: Final[dict[str, str]] = {
    ACCOUNT_MODE_PAPER: RUNTIME_MODE_PAPER,
    ACCOUNT_MODE_LIVE: RUNTIME_MODE_LIVE,
}

_SUPPORTED_EXECUTOR_MODES: Final[frozenset[str]] = frozenset(
    {RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER, RUNTIME_MODE_LIVE}
)


class AutomaticExitExecutorModeError(ValueError):
    """Fail-closed rejection for an unsupported/unmapped executor mode."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def resolve_automatic_exit_executor_mode_v1(account_mode: str) -> str:
    """Map the #392 runtime's account_mode to a #206 executor_mode.

    Fails closed on any account_mode outside the exact set the #392 gate
    already supports (``decision_gate.automatic_exit_gate_v1.
    SUPPORTED_ACCOUNT_MODES``). This mapping does not grant executor
    operational LIVE authority: LIVE still requires
    ``intake_live_authorized`` to independently pass credential binding,
    LIVE authority, and kill-switch checks.
    """
    try:
        return _ACCOUNT_MODE_TO_EXECUTOR_MODE[account_mode]
    except KeyError:
        raise AutomaticExitExecutorModeError("UNSUPPORTED_ACCOUNT_MODE_FOR_EXECUTOR_HANDOFF") from None


def submit_automatic_exit_plan_to_execution_handoff_v1(
    *,
    plan: AutomaticExitPlanV1,
    executor_mode: str,
    executor_identity: str,
    runtime_owner: str,
    handoff_repository: ExecutionHandoffRepositoryV1,
) -> ExecutionHandoffV1:
    """Adapt an approved in-memory AutomaticExitPlanV1 and hand it off.

    Consumes the in-memory plan produced by ``build_automatic_exit_plan_v1``
    in the same evaluation cycle -- never a value reconstructed from the
    ``automatic_exit_evaluation_audit_v1`` audit table. Performs exactly two
    steps: (1) pure adapter conversion, (2) selection of the existing #206
    handoff method for ``executor_mode``. Fails closed on any unsupported
    mode. Does not pre-check LIVE authority, kill switch, or credential
    scope -- those remain exclusively #206 executor substrate
    responsibilities inside ``ExecutionHandoffRepositoryV1``.
    """
    if executor_mode not in _SUPPORTED_EXECUTOR_MODES:
        raise AutomaticExitExecutorModeError("UNSUPPORTED_EXECUTOR_MODE")

    approved_plan = adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)

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
