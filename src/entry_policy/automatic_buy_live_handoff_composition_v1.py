"""Issue #399 Phase 7B: dormant automatic BUY runtime -> shared handoff seam.

Consumes one canonical repository-built ``RuntimeItemV1``, evaluates the
existing candidate -> decision_gate -> planner runtime exactly once, and if a
typed in-memory plan is staged, forwards that exact plan to the existing #206
shared handoff application seam.

No audit JSON is reconstructed into execution input. No credential, authority,
kill-switch, broker, submission, service, or timer state is created here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.entry_policy.automatic_buy_execution_handoff_application_v1 import (
    submit_automatic_buy_plan_to_shared_handoff_v1,
)
from src.entry_policy.automatic_buy_runtime_contract_v1 import (
    RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
)
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import (
    AutomaticBuyRuntimeItemOutcomeV1,
    PLANNER_STATE_STAGED,
    evaluate_automatic_buy_runtime_item_v1,
)
from src.entry_policy.automatic_buy_runtime_repository_v1 import RuntimeItemV1
from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1, ExecutionHandoffV1


class AutomaticBuyLiveHandoffCompositionError(ValueError):
    pass


@dataclass(frozen=True)
class AutomaticBuyRuntimeHandoffOutcomeV1:
    runtime_outcome: AutomaticBuyRuntimeItemOutcomeV1
    handoff: ExecutionHandoffV1 | None


def evaluate_and_handoff_automatic_buy_runtime_item_v1(
    conn: Any,
    *,
    item: RuntimeItemV1,
    executor_identity: str,
    runtime_owner: str,
    handoff_repository: ExecutionHandoffRepositoryV1,
    executor_mode_override: str | None = None,
) -> AutomaticBuyRuntimeHandoffOutcomeV1:
    """Evaluate one canonical item and hand off only its exact staged plan."""
    value = item.runtime_input
    if value.account_mode == "live" and value.input_contract_version != RUNTIME_INPUT_LIVE_CONTRACT_VERSION:
        raise AutomaticBuyLiveHandoffCompositionError("LIVE_HANDOFF_REQUIRES_RUNTIME_INPUT_V2")

    runtime_outcome = evaluate_automatic_buy_runtime_item_v1(conn, item=item)
    if runtime_outcome.planner_state != PLANNER_STATE_STAGED:
        if runtime_outcome.plan is not None:
            raise AutomaticBuyLiveHandoffCompositionError("NON_STAGED_RUNTIME_OUTCOME_CARRIES_PLAN")
        return AutomaticBuyRuntimeHandoffOutcomeV1(runtime_outcome=runtime_outcome, handoff=None)
    if runtime_outcome.plan is None:
        raise AutomaticBuyLiveHandoffCompositionError("STAGED_RUNTIME_OUTCOME_MISSING_PLAN")

    handoff = submit_automatic_buy_plan_to_shared_handoff_v1(
        plan=runtime_outcome.plan,
        account_mode=value.account_mode,
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
        handoff_repository=handoff_repository,
        executor_mode_override=executor_mode_override,
    )
    return AutomaticBuyRuntimeHandoffOutcomeV1(
        runtime_outcome=runtime_outcome,
        handoff=handoff,
    )
