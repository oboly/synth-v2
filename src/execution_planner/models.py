from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final


PLANNABLE_DECISION_STATES: Final[set[str]] = {
    "WATCHLIST_PREPLAN_ALLOWED",
    "PREPARE_ALLOWED",
    "EXECUTION_ALLOWED",
}

PLANNABLE_EXECUTION_INTENTS: Final[set[str]] = {
    "PREPARE_PLAN",
    "PLACE_PASSIVE_LIMIT",
}


@dataclass(frozen=True)
class ExecutionPlannerConfig:
    execution_mode: str = "paper"
    watchlist_preplan_target_fraction: Decimal = Decimal("0.03300000")
    prepare_target_fraction: Decimal = Decimal("0.06600000")
    execute_target_fraction: Decimal = Decimal("0.06600000")
    max_notional_eur: Decimal = Decimal("25.0000000000")

    max_reprices: int = 5
    max_wait_seconds: int = 1800
    max_chase_bps: Decimal = Decimal("15.00000000")
    min_spread_bps_for_capture: Decimal = Decimal("3.00000000")
    escalation_to_urgent_limit: bool = True
    abort_if_signal_invalidates: bool = True

    planner_name: str = "execution_planner_v1"
    planner_version: str = "1.1"


@dataclass(frozen=True)
class PlannedExecution:
    account_id: int
    asset_id: int
    sleeve_code: str
    venue: str
    side: str
    desired_action: str
    execution_intent: str | None
    execution_mode: str
    plan_ts_utc: datetime
    valid_until_ts_utc: datetime | None
    target_fraction: Decimal
    max_notional_eur: Decimal | None
    reference_price_eur: Decimal | None
    passive_price_eur: Decimal | None
    urgent_limit_price_eur: Decimal | None
    max_reprices: int
    max_wait_seconds: int
    max_chase_bps: Decimal
    min_spread_bps_for_capture: Decimal
    escalation_to_urgent_limit: bool
    abort_if_signal_invalidates: bool
    plan_state: str
    notes: str


@dataclass(frozen=True)
class OpenPositionForExit:
    portfolio_position_id: int
    account_id: int
    sleeve_code: str
    asset_id: int
    venue: str
    qty: Decimal
    avg_entry_price: Decimal | None
    mark_price: Decimal | None
    market_value_eur: Decimal
    realized_pnl_eur: Decimal
    unrealized_pnl_eur: Decimal
    position_status: str
