from __future__ import annotations

from decimal import Decimal

from src.plan_lifecycle.models import LifecyclePlanRow, LifecycleResult
from src.plan_lifecycle.repository import PlanLifecycleRepository


def process_releasable_plan(
    plan: LifecyclePlanRow,
    repository: PlanLifecycleRepository,
) -> LifecycleResult:
    symbol = repository.fetch_symbol(plan.asset_id)
    released_amount = repository.release_reservation_for_plan(plan)
    reservation_released = released_amount > Decimal("0")

    return LifecycleResult(
        execution_plan_id=plan.execution_plan_id,
        asset_id=plan.asset_id,
        symbol=symbol,
        old_plan_state=plan.plan_state,
        new_plan_state=plan.plan_state,
        reservation_released=reservation_released,
        released_amount_eur=released_amount,
        reason=f"PLAN_STATE_{plan.plan_state}_RELEASE_CHECK",
    )
