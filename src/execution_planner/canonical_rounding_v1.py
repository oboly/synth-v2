"""
canonical_rounding_v1 — the single venue-aware execution rounding service.

Layer: execution_planner. Account-agnostic, broker-call-free, DB-write-free.

This module exists because three independent ladder-building code paths
(execution_planner.contract_preview_v1, execution.limit_sell_ladder_v1,
execution_ladder.resolver) previously rounded prices with their own
unconditional ROUND_DOWN quantizers, which is unsafe for SELL legs — see
docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
finding F3. All three now delegate here; see each module's docstring for
the exact redirect.

Rounding semantics:

  Price:
    SELL -> ROUND_UP   (never place a sell limit below the analytical target)
    BUY  -> ROUND_DOWN (never place a buy limit above the analytical rebuy)

  Quantity:
    Always ROUND_DOWN regardless of side — a rounded quantity must never
    exceed the caller's approved/available amount.

  Minimum-quantity and minimum-notional checks run strictly AFTER rounding,
  against the rounded values, never the raw ones. Any post-rounding invalid
  leg is rejected with a deterministic reason code, never silently dropped
  or silently allowed through.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Final

from src.market_rules.venue_execution_constraints_v1 import VenueExecutionConstraints


VALID_SIDES: Final[frozenset[str]] = frozenset({"BUY", "SELL"})

REJECTION_BELOW_MIN_BASE_QUANTITY: Final[str] = "BELOW_MIN_BASE_QUANTITY"
REJECTION_BELOW_MIN_QUOTE_NOTIONAL: Final[str] = "BELOW_MIN_QUOTE_NOTIONAL"
REJECTION_QUANTITY_NOT_POSITIVE: Final[str] = "QUANTITY_NOT_POSITIVE_AFTER_ROUNDING"
REJECTION_PRICE_NOT_POSITIVE: Final[str] = "PRICE_NOT_POSITIVE_AFTER_ROUNDING"
REJECTION_VENUE_CONSTRAINTS_NOT_USABLE: Final[str] = "VENUE_CONSTRAINTS_STALE_OR_MISSING"


@dataclass(frozen=True)
class RoundedLeg:
    raw_price: Decimal
    raw_quantity_base: Decimal
    rounded_price: Decimal
    rounded_quantity_base: Decimal
    rounded_notional_quote: Decimal
    is_valid: bool
    rejection_reasons: tuple[str, ...]


def _normalize_side(side: str) -> str:
    normalized = side.strip().upper()
    if normalized not in VALID_SIDES:
        raise ValueError(f"side must be one of {sorted(VALID_SIDES)}")
    return normalized


def _quantize(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    if step <= 0:
        raise ValueError("step must be > 0")
    steps = (value / step).to_integral_value(rounding=rounding)
    result = steps * step
    # Re-quantize to step's own exponent so display precision is stable
    # (e.g. an amount step of 0.00000001 always yields 8 decimal places),
    # matching the pattern already used in
    # src.market_rules.price_tick_normalization_v1.normalize_price_to_tick.
    return result.quantize(step, rounding=rounding)


def round_price_for_side(price: Decimal, tick_size: Decimal, side: str) -> Decimal:
    """Side-aware price rounding: SELL rounds up, BUY rounds down."""
    side = _normalize_side(side)
    rounding = ROUND_UP if side == "SELL" else ROUND_DOWN
    return _quantize(price, tick_size, rounding)


def round_quantity_down(quantity: Decimal, qty_step_size: Decimal) -> Decimal:
    """Quantity rounding is never side-aware: always round down so the
    result never exceeds the caller's approved/available amount."""
    return _quantize(quantity, qty_step_size, ROUND_DOWN)


def round_leg_for_side(
    *,
    side: str,
    raw_price: Decimal,
    raw_quantity_base: Decimal,
    constraints: VenueExecutionConstraints,
) -> RoundedLeg:
    """Round one execution-plan leg using the single canonical service.

    constraints.status must be FRESH; a STALE or MISSING constraints object
    still produces a rounded result using whatever tick/step values it
    carries (zero for MISSING), but is always marked invalid via
    REJECTION_VENUE_CONSTRAINTS_NOT_USABLE so callers cannot accidentally
    treat a fail-closed metadata gap as a passing leg.
    """
    side = _normalize_side(side)
    reasons: list[str] = []

    if constraints.status != "FRESH":
        reasons.append(REJECTION_VENUE_CONSTRAINTS_NOT_USABLE)
        return RoundedLeg(
            raw_price=raw_price,
            raw_quantity_base=raw_quantity_base,
            rounded_price=Decimal("0"),
            rounded_quantity_base=Decimal("0"),
            rounded_notional_quote=Decimal("0"),
            is_valid=False,
            rejection_reasons=tuple(reasons),
        )

    rounded_price = round_price_for_side(raw_price, constraints.tick_size, side)
    rounded_quantity = round_quantity_down(raw_quantity_base, constraints.qty_step_size)
    rounded_notional = rounded_price * rounded_quantity

    if rounded_price <= 0:
        reasons.append(REJECTION_PRICE_NOT_POSITIVE)
    if rounded_quantity <= 0:
        reasons.append(REJECTION_QUANTITY_NOT_POSITIVE)
    if rounded_quantity > 0 and rounded_quantity < constraints.min_base_quantity:
        reasons.append(REJECTION_BELOW_MIN_BASE_QUANTITY)
    if rounded_notional > 0 and rounded_notional < constraints.min_quote_notional:
        reasons.append(REJECTION_BELOW_MIN_QUOTE_NOTIONAL)

    return RoundedLeg(
        raw_price=raw_price,
        raw_quantity_base=raw_quantity_base,
        rounded_price=rounded_price,
        rounded_quantity_base=rounded_quantity,
        rounded_notional_quote=rounded_notional,
        is_valid=not reasons,
        rejection_reasons=tuple(reasons),
    )
