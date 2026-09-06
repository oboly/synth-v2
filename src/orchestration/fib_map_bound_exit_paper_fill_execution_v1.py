"""Issue #753 B7.6: PAPER SELL execution + #752 ownership bridge for Fib exits.

Orchestration only. execution_planner owns SELL intent, executor owns order state,
decision_gate owns strategy-owned reduction authorization/reconciliation.
No LIVE/broker/private API path is activated here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from src.decision_gate.fib_map_bound_exit_fill_reconciliation_persistence_v1 import (
    reconcile_and_persist_fib_map_bound_exit_paper_fill_v1,
)
from src.decision_gate.fib_map_bound_exit_fill_reconciliation_v1 import (
    FibMapBoundExitFillPlanIdentityV1,
)
from src.decision_gate.strategy_owned_fill_reconciliation_v1 import (
    StrategyOwnedFillReconciliationFactV1,
)
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1
from src.execution_planner.fib_map_bound_exit_execution_handoff_adapter_v1 import (
    adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1,
)
from src.execution_planner.fib_map_bound_exit_planner_v1 import FibMapBoundExitPlanV1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_PAPER,
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)
from src.executor.execution_leg_v1 import ACTIVE, FILLED, ExecutionLegRepositoryV1
from src.executor.execution_submission_orchestrator_v1 import (
    ExecutionSubmissionResultV1,
    submit_execution_plan,
)
from src.executor.paper_order_adapter_v1 import (
    PaperMarketEvidenceUnavailableError,
    PaperMarketQuoteProviderV1,
    PaperOrderPlacementAdapterV1,
    PaperOrderPlacementRepository,
    paper_broker_cumulative_fill_evidence_from_leg_v1,
)
from src.executor.paper_resting_order_reconciliation_v1 import (
    PaperRestingHandoffMismatchError,
    PaperRestingPlacementEvidenceError,
    reconcile_paper_resting_leg_v1,
)

SIDE_SELL = "SELL"


class FibMapBoundExitPaperFillExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class FibMapBoundExitPaperLegFillOutcomeV1:
    leg_index: int
    fact: StrategyOwnedFillReconciliationFactV1
    event: StrategyOwnedInventoryEventV1 | None


@dataclass(frozen=True)
class FibMapBoundExitPaperFillExecutionResultV1:
    submission: ExecutionSubmissionResultV1
    fills: tuple[FibMapBoundExitPaperLegFillOutcomeV1, ...]


def _fill_identity(
    plan: FibMapBoundExitPlanV1,
    *,
    plan_reference_id: str,
    broker_order_id: str,
) -> FibMapBoundExitFillPlanIdentityV1:
    return FibMapBoundExitFillPlanIdentityV1(
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        strategy_bucket_id=plan.strategy_bucket_id,
        strategy_id=plan.strategy_id,
        strategy_version=plan.strategy_version,
        trade_id=plan.trade_id,
        source_execution_plan_id=plan_reference_id,
        source_order_id=broker_order_id,
    )


def submit_and_reconcile_fib_map_bound_exit_paper_plan_v1(
    *,
    plan: FibMapBoundExitPlanV1,
    handoff: ExecutionHandoffV1,
    operator_id: int,
    handoff_repository: ExecutionHandoffRepositoryV1,
    leg_repository: ExecutionLegRepositoryV1,
    conn: Any,
    quote_provider: PaperMarketQuoteProviderV1,
    max_quote_age_seconds: int,
    now_fn: Callable[[], datetime],
    placement_repository: PaperOrderPlacementRepository,
) -> FibMapBoundExitPaperFillExecutionResultV1:
    if plan.side != SIDE_SELL:
        raise FibMapBoundExitPaperFillExecutionError("PLAN_SIDE_NOT_SELL")
    if any(leg.post_only is not True for leg in plan.legs):
        raise FibMapBoundExitPaperFillExecutionError("PLAN_LEG_NOT_POST_ONLY")
    if handoff.executor_mode != RUNTIME_MODE_PAPER:
        raise FibMapBoundExitPaperFillExecutionError("HANDOFF_NOT_PAPER_MODE")

    approved = adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(plan)
    if (
        handoff.plan_source != approved.plan_source
        or handoff.plan_reference_id != approved.plan_reference_id
        or handoff.trading_account_id != plan.trading_account_id
        or handoff.venue != plan.venue
        or handoff.market != plan.market
        or handoff.side != SIDE_SELL
    ):
        raise FibMapBoundExitPaperFillExecutionError("HANDOFF_PLAN_IDENTITY_MISMATCH")

    pre_submit_active_leg_indices: set[int] = set()
    for leg_index in range(1, len(approved.legs) + 1):
        existing = leg_repository.find_by_handoff_and_index(handoff.handoff_id or 0, leg_index)
        if existing is not None and existing.state == ACTIVE:
            pre_submit_active_leg_indices.add(leg_index)

    adapter = PaperOrderPlacementAdapterV1(
        quote_provider=quote_provider,
        max_quote_age_seconds=max_quote_age_seconds,
        now_fn=now_fn,
        placement_repository=placement_repository,
    )
    submission = submit_execution_plan(
        handoff=handoff,
        plan=approved,
        operator_id=operator_id,
        handoff_repository=handoff_repository,
        leg_repository=leg_repository,
        adapter=adapter,
    )

    fills: list[FibMapBoundExitPaperLegFillOutcomeV1] = []
    for leg_index in range(1, len(approved.legs) + 1):
        leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id or 0, leg_index)
        if leg is None:
            continue
        if leg.state == ACTIVE and leg_index in pre_submit_active_leg_indices:
            try:
                leg = reconcile_paper_resting_leg_v1(
                    leg,
                    handoff_repository=handoff_repository,
                    quote_provider=quote_provider,
                    placement_repository=placement_repository,
                    max_quote_age_seconds=max_quote_age_seconds,
                    now_fn=now_fn,
                    leg_repository=leg_repository,
                )
            except (
                PaperMarketEvidenceUnavailableError,
                PaperRestingPlacementEvidenceError,
                PaperRestingHandoffMismatchError,
            ):
                continue
        if leg.state != FILLED:
            continue
        if not isinstance(leg.broker_order_id, str) or not leg.broker_order_id.strip():
            raise FibMapBoundExitPaperFillExecutionError("FILLED_LEG_MISSING_BROKER_ORDER_ID")
        evidence = paper_broker_cumulative_fill_evidence_from_leg_v1(
            leg,
            observed_ts_utc=now_fn(),
        )
        fact, event = reconcile_and_persist_fib_map_bound_exit_paper_fill_v1(
            conn,
            identity=_fill_identity(
                plan,
                plan_reference_id=approved.plan_reference_id,
                broker_order_id=leg.broker_order_id,
            ),
            evidence=evidence,
        )
        fills.append(
            FibMapBoundExitPaperLegFillOutcomeV1(
                leg_index=leg_index,
                fact=fact,
                event=event,
            )
        )
    return FibMapBoundExitPaperFillExecutionResultV1(
        submission=submission,
        fills=tuple(fills),
    )
