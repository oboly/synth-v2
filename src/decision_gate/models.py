from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


ELIGIBLE_SELECTION_STATES: Final[set[str]] = {"PREPARE", "BUY_READY"}

ACTIVE_PLAN_STATES: Final[set[str]] = {
    "IDLE",
    "PLANNED",
    "PLACED",
    "MONITOR_QUEUE",
    "REPRICE_PENDING",
    "ESCALATED",
}

OPEN_POSITION_STATUSES: Final[set[str]] = {"OPEN"}

ACTIVE_SLEEVE_STATUSES: Final[set[str]] = {"ACTIVE"}


@dataclass(frozen=True)
class SelectionInputRow:
    selection_state_id: int
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: str | None
    selection_state: str
    selection_bias: str | None
    priority_rank: int | None
    effective_selection_score: Decimal | None
    summary_text: str | None


@dataclass(frozen=True)
class SleeveState:
    account_id: int
    sleeve_code: str
    sleeve_status: str
    target_weight: Decimal
    allocated_equity_eur: Decimal
    reserved_equity_eur: Decimal
    deployed_equity_eur: Decimal
    available_equity_eur: Decimal


@dataclass(frozen=True)
class DuplicateState:
    has_active_plan: bool
    has_open_position: bool


@dataclass(frozen=True)
class DecisionGateConfig:
    min_available_equity_eur: Decimal = Decimal("25.00")


@dataclass(frozen=True)
class DecisionResult:
    account_id: int
    sleeve_code: str
    selection_state_id: int
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: str | None
    selection_state: str
    decision_state: str
    decision_reason: str
    execution_intent: str
    min_available_equity_eur: Decimal
    available_equity_eur: Decimal | None
    has_active_plan: bool
    has_open_position: bool
    summary_text: str | None
