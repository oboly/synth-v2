from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.executor.paper_contract_v1 import (
    CANONICAL_PAPER_PLAN_STATES,
    validate_canonical_paper_contract,
)
from src.executor.repository import ExecutorRepository


@dataclass(frozen=True)
class ExecutorResult:
    execution_plan_id: int
    asset_id: int
    symbol: str | None
    desired_action: str
    old_plan_state: str
    new_plan_state: str
    event_type: str
    fill_price_eur: Decimal | None
    fill_qty: Decimal | None
    reservation_released: bool
    position_opened: bool


def execute_plan_paper(plan, repo: ExecutorRepository) -> ExecutorResult:
    validate_canonical_paper_contract(
        plan,
        canonical_symbol=plan.asset_symbol,
        actionable_states=CANONICAL_PAPER_PLAN_STATES,
    )
    symbol = plan.asset_symbol

    if plan.desired_action == "SPREAD_CAPTURE_PASSIVE":
        latest_price = repo.fetch_latest_price_eur(
            asset_id=plan.asset_id,
            venue=plan.venue,
            interval_code="1h",
        )

        if latest_price is None:
            return ExecutorResult(
                execution_plan_id=plan.execution_plan_id,
                asset_id=plan.asset_id,
                symbol=symbol,
                desired_action=plan.desired_action,
                old_plan_state=plan.plan_state,
                new_plan_state=plan.plan_state,
                event_type="NO_PRICE",
                fill_price_eur=None,
                fill_qty=None,
                reservation_released=False,
                position_opened=False,
            )

        fill_qty, reservation_released = repo.fill_passive_plan_paper(
            plan=plan,
            fill_price_eur=latest_price,
        )

        return ExecutorResult(
            execution_plan_id=plan.execution_plan_id,
            asset_id=plan.asset_id,
            symbol=symbol,
            desired_action=plan.desired_action,
            old_plan_state=plan.plan_state,
            new_plan_state="FILLED",
            event_type="PAPER_FILL_PASSIVE",
            fill_price_eur=latest_price,
            fill_qty=fill_qty,
            reservation_released=reservation_released,
            position_opened=True,
        )

    if plan.desired_action == "CLOSE_POSITION_MARKET_PAPER":
        latest_price = repo.fetch_latest_price_eur(
            asset_id=plan.asset_id,
            venue=plan.venue,
            interval_code="1h",
        )

        if latest_price is None:
            return ExecutorResult(
                execution_plan_id=plan.execution_plan_id,
                asset_id=plan.asset_id,
                symbol=symbol,
                desired_action=plan.desired_action,
                old_plan_state=plan.plan_state,
                new_plan_state=plan.plan_state,
                event_type="NO_PRICE",
                fill_price_eur=None,
                fill_qty=None,
                reservation_released=False,
                position_opened=False,
            )

        fill_qty, realized_pnl_delta, closed = repo.fill_close_position_market_paper(
            plan=plan,
            fill_price_eur=latest_price,
        )

        return ExecutorResult(
            execution_plan_id=plan.execution_plan_id,
            asset_id=plan.asset_id,
            symbol=symbol,
            desired_action=plan.desired_action,
            old_plan_state=plan.plan_state,
            new_plan_state="FILLED" if closed else plan.plan_state,
            event_type="PAPER_FILL_CLOSE",
            fill_price_eur=latest_price,
            fill_qty=fill_qty,
            reservation_released=False,
            position_opened=False,
        )

    raise AssertionError("validated paper execution mapping has no executor path")
