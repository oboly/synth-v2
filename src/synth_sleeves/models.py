"""
SYNTH v2
Module: synth_sleeves.models
Purpose:
    Canonical dataclasses and enums for sleeve-aware targeting, PREPARE, and paper lots.
Boundary:
    - No DB I/O here
    - No exchange I/O here
    - Pure in-memory contracts only
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


DECIMAL_ZERO = Decimal("0")
DECIMAL_ONE = Decimal("1")


class SleeveCode(str, Enum):
    CORE = "CORE"
    SWING = "SWING"
    TACTICAL = "TACTICAL"
    EXPERIMENTAL = "EXPERIMENTAL"


class DecisionAction(str, Enum):
    AVOID = "AVOID"
    WATCH = "WATCH"
    PREPARE = "PREPARE"
    SCALP_ONLY = "SCALP_ONLY"
    ENTER_LONG = "ENTER_LONG"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    BLOCK = "BLOCK"


class EntryState(str, Enum):
    WATCH = "WATCH"
    PREPARE = "PREPARE"
    ENTER_LONG = "ENTER_LONG"
    SCALP_ONLY = "SCALP_ONLY"


@dataclass(slots=True)
class AgentSignalRow:
    asset_id: int
    symbol: str
    selection_state: str
    selection_score: Decimal
    selection_bias: str
    decision_hint: str | None = None
    regime_ok: bool = True
    htf_reject: bool = False
    liquidity_ok: bool = True
    latest_price_eur: Decimal = DECIMAL_ZERO
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentProposal:
    run_ts_utc: datetime
    asset_id: int
    symbol: str
    sleeve_code: SleeveCode
    strategy_name: str
    desired_action: DecisionAction
    requested_fraction: Decimal
    score: Decimal
    source_state: str
    reasoning: str
    latest_price_eur: Decimal
    entry_state: EntryState | None = None


@dataclass(slots=True)
class ApprovedTarget:
    run_ts_utc: datetime
    asset_id: int
    symbol: str
    sleeve_code: SleeveCode
    strategy_name: str
    desired_action: DecisionAction
    target_fraction: Decimal
    decision_strength: str
    source_state: str
    reasoning: str
    latest_price_eur: Decimal


@dataclass(slots=True)
class OpenLot:
    position_lot_id: int
    asset_id: int
    sleeve_code: SleeveCode
    strategy_name: str
    entry_state: EntryState
    open_ts_utc: datetime
    entry_price_eur: Decimal
    latest_price_eur: Decimal
    current_fraction: Decimal
    entry_notional_eur: Decimal
    current_notional_eur: Decimal
    quantity_units: Decimal
    realized_pnl_eur: Decimal = DECIMAL_ZERO
    unrealized_pnl_eur: Decimal = DECIMAL_ZERO
    entry_reason: str = ""
    last_transition_state: str | None = None


@dataclass(slots=True)
class PaperFillIntent:
    run_ts_utc: datetime
    asset_id: int
    symbol: str
    sleeve_code: SleeveCode
    strategy_name: str
    action: str
    delta_fraction: Decimal
    price_eur: Decimal
    reasoning: str


@dataclass(slots=True)
class SleeveConfig:
    sleeve_code: SleeveCode
    wallet_share: Decimal
    max_positions: int
    per_position_cap: Decimal
    allowed_actions: set[DecisionAction]
    agent_names: list[str]
    prepare_enabled: bool
    prepare_cap: Decimal
    prepare_max_positions: int
