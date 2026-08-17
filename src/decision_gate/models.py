from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


WATCHLIST_SELECTION_STATE: Final[str] = "WATCHLIST"
PREPARE_SELECTION_STATE: Final[str] = "PREPARE"
BUY_READY_SELECTION_STATE: Final[str] = "BUY_READY"

ELIGIBLE_SELECTION_STATES: Final[set[str]] = {
    WATCHLIST_SELECTION_STATE,
    PREPARE_SELECTION_STATE,
    BUY_READY_SELECTION_STATE,
}

DIRECT_SELECTION_STATES: Final[set[str]] = {
    PREPARE_SELECTION_STATE,
    BUY_READY_SELECTION_STATE,
}

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

PASS_SETUP_FILTER_STATE: Final[str] = "PASS"


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

    allowed_sleeves: str | None
    summary_text: str | None
    regime_label_4h: str | None

    setup_filter_state: str | None
    setup_filter_reason: str | None
    target_horizon: str | None


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

    allowed_sleeves: str | None
    setup_filter_state: str | None
    setup_filter_reason: str | None
    target_horizon: str | None

    summary_text: str | None
    regime_label_4h: str | None

    # Read-only account-protection provenance. It is populated only by the
    # decision-gate composition wrapper and never grants permission.
    protection_decision_state: str | None = None
    protection_reason_code: str | None = None
    protection_code: str | None = None
