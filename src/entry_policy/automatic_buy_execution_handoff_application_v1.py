"""Issue #399 shared automatic BUY -> #206 executor handoff application seam.

Phase 6 PAPER/DRY_RUN preview behavior is preserved. Phase 7B additionally
supports the exact typed in-memory ``AutomaticBuyPlanV1`` from the canonical
runtime cycle. Normal mode is derived only from account_mode; the sole explicit
override is DRY_RUN. LIVE uses the existing shared
``ExecutionHandoffRepositoryV1.intake_live_authorized`` path and therefore
cannot bypass credential-scope, finite LIVE authority, or kill-switch checks.

This module does not activate any of those states and performs no broker call.
"""
from __future__ import annotations

from typing import Final

from src.account.account_mode_contract_v1 import (
    ACCOUNT_MODE_LIVE,
    ACCOUNT_MODE_LIVE_READONLY,
    ACCOUNT_MODE_PAPER,
)
from src.entry_policy.automatic_buy_acceptance_dry_run_v1 import AutomaticBuyHandoffPreviewV1
from src.execution_planner.automatic_buy_execution_handoff_adapter_v1 import (
    adapt_automatic_buy_plan_to_approved_execution_plan_v1,
)
from src.execution_planner.automatic_buy_planner_v1 import AutomaticBuyPlanV1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_DRY_RUN,
    RUNTIME_MODE_LIVE,
    RUNTIME_MODE_PAPER,
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)

# Issue #551 account-mode split: `live_readonly` (real broker, read-only)
# is deliberately absent from this map. It must never resolve to any
# executor runtime mode -- resolve_automatic_buy_executor_mode_v1 rejects it
# explicitly, before the lookup, rather than relying on an accidental
# KeyError to fail closed.
_ACCOUNT_MODE_TO_EXECUTOR_MODE: Final[dict[str, str]] = {
    ACCOUNT_MODE_PAPER: RUNTIME_MODE_PAPER,
    ACCOUNT_MODE_LIVE: RUNTIME_MODE_LIVE,
}
_SUPPORTED_EXECUTOR_MODES: Final[frozenset[str]] = frozenset(
    {RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER, RUNTIME_MODE_LIVE}
)


class AutomaticBuyExecutorHandoffError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def resolve_automatic_buy_executor_mode_v1(
    *,
    account_mode: str,
    executor_mode_override: str | None = None,
) -> str:
    """Derive normal executor mode from account_mode; only DRY_RUN may override.

    ``live_readonly`` (real broker, read-only, never execution-eligible) is
    rejected explicitly and can never resolve to ``RUNTIME_MODE_LIVE`` or any
    other executor runtime mode, regardless of ``executor_mode_override``.
    """
    if account_mode == ACCOUNT_MODE_LIVE_READONLY:
        raise AutomaticBuyExecutorHandoffError("ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE")
    try:
        derived = _ACCOUNT_MODE_TO_EXECUTOR_MODE[account_mode]
    except KeyError:
        raise AutomaticBuyExecutorHandoffError("UNSUPPORTED_ACCOUNT_MODE_FOR_EXECUTOR_HANDOFF") from None
    if executor_mode_override is None:
        return derived
    if executor_mode_override != RUNTIME_MODE_DRY_RUN:
        raise AutomaticBuyExecutorHandoffError("EXECUTOR_MODE_OVERRIDE_NOT_PERMITTED")
    return RUNTIME_MODE_DRY_RUN


def submit_automatic_buy_plan_to_shared_handoff_v1(
    *,
    plan: AutomaticBuyPlanV1,
    account_mode: str,
    executor_identity: str,
    runtime_owner: str,
    handoff_repository: ExecutionHandoffRepositoryV1,
    executor_mode_override: str | None = None,
) -> ExecutionHandoffV1:
    """Submit an already-approved in-memory BUY plan to the canonical handoff.

    This function does not inspect or duplicate decision-gate permission,
    credential scope, LIVE authority, or kill-switch state. For LIVE it calls
    only the existing explicit shared authorized intake method.
    """
    executor_mode = resolve_automatic_buy_executor_mode_v1(
        account_mode=account_mode,
        executor_mode_override=executor_mode_override,
    )
    if executor_mode not in _SUPPORTED_EXECUTOR_MODES:
        raise AutomaticBuyExecutorHandoffError("EXECUTOR_MODE_UNSUPPORTED")

    approved_plan = adapt_automatic_buy_plan_to_approved_execution_plan_v1(plan)
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


def submit_automatic_buy_preview_to_shared_handoff_v1(
    *,
    preview: AutomaticBuyHandoffPreviewV1,
    account_mode: str,
    executor_identity: str,
    runtime_owner: str,
    handoff_repository: ExecutionHandoffRepositoryV1,
    executor_mode_override: str | None = None,
) -> ExecutionHandoffV1:
    """Preserve the Phase 6 preview seam strictly for PAPER/DRY_RUN.

    A Phase-5 ``PAPER_DRY_RUN`` preview is never valid LIVE evidence and may
    not be used to reach the LIVE handoff method. Phase 7B LIVE composition
    must use ``submit_automatic_buy_plan_to_shared_handoff_v1`` with the exact
    typed runtime-cycle plan.
    """
    if preview.mode != "PAPER_DRY_RUN":
        raise AutomaticBuyExecutorHandoffError("PHASE6_PREVIEW_MODE_INVALID")
    if account_mode != ACCOUNT_MODE_PAPER:
        raise AutomaticBuyExecutorHandoffError("PHASE6_PREVIEW_NON_PAPER_FORBIDDEN")

    plan = preview.plan
    if (
        preview.trading_account_id != plan.trading_account_id
        or preview.venue.lower() != plan.venue.lower()
        or preview.asset_id != plan.asset_id
        or preview.market.upper() != plan.market.upper()
    ):
        raise AutomaticBuyExecutorHandoffError("PHASE6_PREVIEW_PLAN_IDENTITY_MISMATCH")

    return submit_automatic_buy_plan_to_shared_handoff_v1(
        plan=plan,
        account_mode=account_mode,
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
        handoff_repository=handoff_repository,
        executor_mode_override=executor_mode_override,
    )
