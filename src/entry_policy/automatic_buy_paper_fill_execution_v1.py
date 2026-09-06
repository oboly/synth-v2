"""Issue #753 B5.5: submit an approved automatic-BUY PAPER plan through the
shared executor handoff path and, for each leg that truthfully fills, bridge
the result into #752/#753-B5 strategy-owned-inventory reconciliation.

This module composes three already-reviewed, unchanged seams:

- ``src/execution_planner/automatic_buy_execution_handoff_adapter_v1.py`` --
  the existing ``AutomaticBuyPlanV1`` -> ``ApprovedExecutionPlanV1`` adapter.
- ``src/executor/execution_submission_orchestrator_v1.py`` -- the existing,
  side-neutral shared submission path, unchanged, given the new
  ``src/executor/paper_order_adapter_v1.py`` PAPER adapter.
- ``src/decision_gate/automatic_buy_fill_reconciliation_persistence_v1.py`` --
  the existing #753-B5 bridge, unchanged.

It does not call ``src/executor/shared_execution_runtime_v1.py`` and does not
touch its ``PAPER_ADAPTER_NOT_CONFIGURED`` guard: that module composes the
fully decoupled, side-neutral shared-executor runtime, which deliberately has
no per-plan strategy identity available to reconcile ownership with. This
module is the opposite: a narrowly-scoped, automatic-BUY-specific caller that
already holds ``AutomaticBuyPlanV1`` identity and submits synchronously in the
same call, exactly as the existing DRY_RUN/LIVE intake seam
(``src/entry_policy/automatic_buy_execution_handoff_application_v1.py``)
already does for handoff *intake*. This module adds the missing *submission +
reconciliation* step for PAPER only.

It never routes automatic-BUY onto the legacy per-plan ``execution_plan``
PAPER simulator (``src/executor/repository.py``'s ``fill_passive_plan_paper``);
it uses only the shared ``executor_execution_handoff`` / ``executor_execution_leg``
contract B3/B4 already use.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged (calls existing #753 B5 bridge only)
execution_planner=unchanged
executor=extended (new PAPER adapter only; shared submission orchestrator unchanged)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from src.decision_gate.automatic_buy_fill_reconciliation_persistence_v1 import (
    reconcile_and_persist_automatic_buy_paper_fill_v1,
)
from src.decision_gate.automatic_buy_fill_reconciliation_v1 import AutomaticBuyFillPlanIdentityV1
from src.decision_gate.strategy_owned_fill_reconciliation_v1 import StrategyOwnedFillReconciliationFactV1
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1
from src.execution_planner.automatic_buy_execution_handoff_adapter_v1 import (
    adapt_automatic_buy_plan_to_approved_execution_plan_v1,
)
from src.execution_planner.automatic_buy_planner_v1 import AutomaticBuyPlanV1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_PAPER,
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)
from src.executor.execution_leg_v1 import FILLED, ExecutionLegRepositoryV1
from src.executor.execution_submission_orchestrator_v1 import (
    ExecutionSubmissionResultV1,
    submit_execution_plan,
)
from src.executor.paper_order_adapter_v1 import (
    PaperMarketQuoteProviderV1,
    PaperOrderPlacementAdapterV1,
    paper_broker_cumulative_fill_evidence_from_leg_v1,
)

SIDE_BUY = "BUY"


class AutomaticBuyPaperFillExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class AutomaticBuyPaperLegFillOutcomeV1:
    leg_index: int
    fact: StrategyOwnedFillReconciliationFactV1
    event: StrategyOwnedInventoryEventV1 | None


@dataclass(frozen=True)
class AutomaticBuyPaperFillExecutionResultV1:
    submission: ExecutionSubmissionResultV1
    fills: tuple[AutomaticBuyPaperLegFillOutcomeV1, ...]


def _plan_fill_identity_v1(
    plan: AutomaticBuyPlanV1, *, plan_reference_id: str, broker_order_id: str,
) -> AutomaticBuyFillPlanIdentityV1:
    return AutomaticBuyFillPlanIdentityV1(
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        strategy_bucket_id=plan.strategy_bucket_id,
        strategy_id=plan.strategy_id,
        strategy_version=plan.strategy_version,
        genesis_trade_id=plan.trade_id,
        source_execution_plan_id=plan_reference_id,
        source_order_id=broker_order_id,
    )


def submit_and_reconcile_automatic_buy_paper_plan_v1(
    *,
    plan: AutomaticBuyPlanV1,
    handoff: ExecutionHandoffV1,
    operator_id: int,
    handoff_repository: ExecutionHandoffRepositoryV1,
    leg_repository: ExecutionLegRepositoryV1,
    conn: Any,
    quote_provider: PaperMarketQuoteProviderV1,
    max_quote_age_seconds: int,
    now_fn: Callable[[], datetime],
) -> AutomaticBuyPaperFillExecutionResultV1:
    """Submit one approved automatic-BUY plan through the shared PAPER path.

    Fails closed before any submission attempt if the handoff is not exactly
    the PAPER handoff this plan produced (mode, plan identity). Submission
    itself is exactly the existing, unchanged shared orchestrator: replaying
    this call for an already-resolved handoff makes no duplicate placement
    (``submit_execution_plan`` is already claim-guarded) and reconciling an
    already-FILLED leg again is a no-op through #752's own idempotent replay
    guarantee, so this function is safe to call more than once for the same
    plan/handoff.
    """
    if plan.side != SIDE_BUY:
        raise AutomaticBuyPaperFillExecutionError("PLAN_SIDE_NOT_BUY")
    if any(leg.post_only is not True for leg in plan.legs):
        raise AutomaticBuyPaperFillExecutionError("PLAN_LEG_NOT_POST_ONLY")
    if handoff.executor_mode != RUNTIME_MODE_PAPER:
        raise AutomaticBuyPaperFillExecutionError("HANDOFF_NOT_PAPER_MODE")

    approved_plan = adapt_automatic_buy_plan_to_approved_execution_plan_v1(plan)
    if (
        handoff.plan_source != approved_plan.plan_source
        or handoff.plan_reference_id != approved_plan.plan_reference_id
    ):
        raise AutomaticBuyPaperFillExecutionError("HANDOFF_PLAN_IDENTITY_MISMATCH")

    adapter = PaperOrderPlacementAdapterV1(
        quote_provider=quote_provider,
        max_quote_age_seconds=max_quote_age_seconds,
        now_fn=now_fn,
    )
    submission = submit_execution_plan(
        handoff=handoff,
        plan=approved_plan,
        operator_id=operator_id,
        handoff_repository=handoff_repository,
        leg_repository=leg_repository,
        adapter=adapter,
    )

    fills: list[AutomaticBuyPaperLegFillOutcomeV1] = []
    for leg_index in range(1, len(approved_plan.legs) + 1):
        leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id or 0, leg_index)
        if leg is None or leg.state != FILLED:
            continue
        assert leg.broker_order_id is not None  # FILLED always carries broker_order_id
        identity = _plan_fill_identity_v1(
            plan, plan_reference_id=approved_plan.plan_reference_id,
            broker_order_id=leg.broker_order_id,
        )
        evidence = paper_broker_cumulative_fill_evidence_from_leg_v1(
            leg, observed_ts_utc=now_fn(),
        )
        fact, event = reconcile_and_persist_automatic_buy_paper_fill_v1(
            conn, identity=identity, evidence=evidence,
        )
        fills.append(AutomaticBuyPaperLegFillOutcomeV1(leg_index=leg_index, fact=fact, event=event))

    return AutomaticBuyPaperFillExecutionResultV1(submission=submission, fills=tuple(fills))
