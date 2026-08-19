"""Issue #399 Phase 6: PAPER/DRY_RUN handoff application seam.

Consumes the exact typed ``AutomaticBuyHandoffPreviewV1`` from Phase 5 and
routes its in-memory ``AutomaticBuyPlanV1`` into the existing #206 shared
``ExecutionHandoffRepositoryV1``. LIVE is deliberately unavailable here and
remains Phase 7.
"""
from __future__ import annotations

from typing import Final

from src.entry_policy.automatic_buy_acceptance_dry_run_v1 import AutomaticBuyHandoffPreviewV1
from src.execution_planner.automatic_buy_execution_handoff_adapter_v1 import (
    adapt_automatic_buy_plan_to_approved_execution_plan_v1,
)
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_DRY_RUN,
    RUNTIME_MODE_PAPER,
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)

ACCOUNT_MODE_PAPER: Final[str] = "paper"
_SUPPORTED_EXECUTOR_MODES: Final[frozenset[str]] = frozenset({RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER})


class AutomaticBuyExecutorHandoffError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def resolve_automatic_buy_executor_mode_v1(*, account_mode: str, executor_mode_override: str | None = None) -> str:
    """Resolve repository-safe Phase 6 mode.

    Normal automatic BUY handoff is PAPER because Phase 2 currently permits
    paper accounts only. The sole explicit override is DRY_RUN. LIVE cannot be
    expressed by this API.
    """
    if account_mode != ACCOUNT_MODE_PAPER:
        raise AutomaticBuyExecutorHandoffError("PHASE6_NON_PAPER_ACCOUNT_FORBIDDEN")
    if executor_mode_override is None:
        return RUNTIME_MODE_PAPER
    if executor_mode_override != RUNTIME_MODE_DRY_RUN:
        raise AutomaticBuyExecutorHandoffError("PHASE6_EXECUTOR_MODE_OVERRIDE_NOT_PERMITTED")
    return RUNTIME_MODE_DRY_RUN


def submit_automatic_buy_preview_to_shared_handoff_v1(
    *,
    preview: AutomaticBuyHandoffPreviewV1,
    account_mode: str,
    executor_identity: str,
    runtime_owner: str,
    handoff_repository: ExecutionHandoffRepositoryV1,
    executor_mode_override: str | None = None,
) -> ExecutionHandoffV1:
    """Persist one idempotent shared #206 handoff from the exact Phase 5 plan."""
    if preview.mode != "PAPER_DRY_RUN":
        raise AutomaticBuyExecutorHandoffError("PHASE6_PREVIEW_MODE_INVALID")
    plan = preview.plan
    if (
        preview.trading_account_id != plan.trading_account_id
        or preview.venue.lower() != plan.venue.lower()
        or preview.asset_id != plan.asset_id
        or preview.market.upper() != plan.market.upper()
    ):
        raise AutomaticBuyExecutorHandoffError("PHASE6_PREVIEW_PLAN_IDENTITY_MISMATCH")

    executor_mode = resolve_automatic_buy_executor_mode_v1(
        account_mode=account_mode,
        executor_mode_override=executor_mode_override,
    )
    if executor_mode not in _SUPPORTED_EXECUTOR_MODES:
        raise AutomaticBuyExecutorHandoffError("PHASE6_EXECUTOR_MODE_UNSUPPORTED")

    approved_plan = adapt_automatic_buy_plan_to_approved_execution_plan_v1(plan)
    return handoff_repository.intake(
        plan=approved_plan,
        executor_mode=executor_mode,
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
    )
