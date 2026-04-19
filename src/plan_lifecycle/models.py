from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class LifecyclePlanRow:
    execution_plan_id: int
    account_id: int
    asset_id: int
    sleeve_code: str
    venue: str
    desired_action: str
    execution_mode: str
    plan_state: str
    valid_until_ts_utc: datetime | None
    notes: str | None


@dataclass(frozen=True)
class LifecycleReservationRow:
    capital_reservation_id: int
    execution_plan_id: int
    account_id: int
    sleeve_code: str
    asset_id: int
    reserved_amount_eur: Decimal
    reservation_state: str


@dataclass(frozen=True)
class LifecycleResult:
    execution_plan_id: int
    asset_id: int
    symbol: str | None
    old_plan_state: str
    new_plan_state: str
    reservation_released: bool
    released_amount_eur: Decimal
    reason: str
