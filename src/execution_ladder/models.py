from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


# ---------------------------------------------------------------------------
# DB-backed configuration rows (read from execution_ladder_* tables)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SizingVariableRef:
    variable_key: str
    display_label: str
    description: str
    value_unit: str
    allowed_side: str
    is_active: bool
    display_order: int


@dataclass(frozen=True)
class SizingRule:
    sizing_rule_id: int
    trading_account_id: int
    rule_code: str
    display_label: str
    description: str
    rule_type: str                       # MANUAL_ONLY | FIXED_QUOTE | PCT_OF_VARIABLE
    source_variable_key: str | None
    multiplier_bps: int | None
    fixed_quote_amount: Decimal | None
    floor_quote_amount: Decimal | None
    cap_quote_amount: Decimal | None
    is_enabled: bool
    version: int


@dataclass(frozen=True)
class LadderProfile:
    ladder_profile_id: int
    trading_account_id: int
    profile_code: str
    display_label: str
    description: str
    side: str                            # BUY | SELL
    anchor_type: str                     # NATIVE_SHORT_ANCHOR_HIGH (v1 only)
    default_sizing_rule_id: int | None
    is_enabled: bool
    current_version: int


@dataclass(frozen=True)
class LadderLeg:
    ladder_leg_id: int
    ladder_profile_id: int
    profile_version: int
    leg_number: int
    price_offset_bps: int
    allocation_bps: int
    order_type: str
    time_in_force: str
    is_enabled: bool


# ---------------------------------------------------------------------------
# Resolved preview (no DB writes, no broker calls)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LadderLegPreview:
    leg_number: int
    price_offset_bps: int
    allocation_bps: int
    allocated_quote_notional: Decimal
    limit_price: Decimal
    estimated_base_quantity: Decimal
    order_type: str
    time_in_force: str


@dataclass(frozen=True)
class LadderPreview:
    profile_code: str
    profile_version: int
    side: str
    anchor_type: str
    anchor_price: Decimal
    quote_amount: Decimal
    legs: tuple[LadderLegPreview, ...]
    total_allocation_bps: int
    estimated_total_base_quantity: Decimal
