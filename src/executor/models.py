from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ExecutionPlanRow:
    execution_plan_id: int
    account_id: int
    trading_account_id: int | None
    asset_id: int
    asset_symbol: str
    sleeve_code: str
    venue: str
    market: str | None
    side: str
    desired_action: str
    execution_intent: str | None
    action_type: str | None
    requested_side: str | None
    execution_mode: str | None
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
    notes: str | None


@dataclass(frozen=True)
class CapitalReservationRow:
    capital_reservation_id: int
    execution_plan_id: int
    account_id: int
    sleeve_code: str
    asset_id: int
    reserved_amount_eur: Decimal
    reservation_state: str


@dataclass(frozen=True)
class ExecutorResult:
    execution_plan_id: int
    asset_id: int
    symbol: str | None
    desired_action: str
    old_plan_state: str
    new_plan_state: str
    event_type: str
    event_reason: str
    fill_price_eur: Decimal | None
    fill_qty: Decimal | None
    reservation_released: bool
    position_opened: bool
