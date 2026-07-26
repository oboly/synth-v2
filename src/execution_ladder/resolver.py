from __future__ import annotations

# broker_private_calls=0  broker_writes=0  order_submission=0
# live_orders=0  decision_gate=none  executor=none
#
# NOT an authoritative manual-execution path: this module never calls
# decision_gate and round_ladder_preview() is optional (raw
# resolve_ladder_preview() has no consumer that rejects invalid legs). See
# docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
# bypass-list items 3-4. Left unmodified in this change (A+ ladder quantity
# calculation is explicitly out of scope here) — route real manual SELL
# execution requests through
# src.manual_execution.manual_execution_service_v1.process() instead.

from decimal import Decimal

from src.execution_ladder.models import (
    LadderLeg,
    LadderLegPreview,
    LadderPreview,
    LadderProfile,
    SizingRule,
)
from src.execution_planner.canonical_rounding_v1 import RoundedLeg, round_leg_for_side
from src.market_rules.venue_execution_constraints_v1 import VenueExecutionConstraints

# ---------------------------------------------------------------------------
# Whitelists — code-owned; database content must never expand these
# ---------------------------------------------------------------------------

ALLOWED_VARIABLE_KEYS: frozenset[str] = frozenset({
    "MANUAL_QUOTE_AMOUNT",
    "FIXED_QUOTE_AMOUNT",
    "FREE_QUOTE_BALANCE",
    "TOTAL_WALLET_QUOTE_VALUE",
    "COIN_POSITION_QUOTE_VALUE",
    "FREE_BASE_QUANTITY",
})

ALLOWED_RULE_TYPES: frozenset[str] = frozenset({
    "MANUAL_ONLY",
    "FIXED_QUOTE",
    "PCT_OF_VARIABLE",
})

ALLOWED_ANCHOR_TYPES: frozenset[str] = frozenset({
    "NATIVE_SHORT_ANCHOR_HIGH",
})

_ALLOCATION_TOTAL_BPS = 10_000


# ---------------------------------------------------------------------------
# Variable key guard
# ---------------------------------------------------------------------------

def validate_variable_key(variable_key: str) -> str:
    if variable_key not in ALLOWED_VARIABLE_KEYS:
        raise ValueError(
            f"variable_key {variable_key!r} is not in the allowed whitelist. "
            f"Only {sorted(ALLOWED_VARIABLE_KEYS)} are permitted."
        )
    return variable_key


# ---------------------------------------------------------------------------
# Sizing rule resolution
# ---------------------------------------------------------------------------

def resolve_sizing_suggestion(
    rule: SizingRule,
    variable_values: dict[str, Decimal],
) -> Decimal | None:
    if rule.rule_type not in ALLOWED_RULE_TYPES:
        raise ValueError(
            f"rule_type {rule.rule_type!r} is not supported. "
            f"Only {sorted(ALLOWED_RULE_TYPES)} are permitted."
        )

    if rule.rule_type == "MANUAL_ONLY":
        return None

    if rule.rule_type == "FIXED_QUOTE":
        if rule.fixed_quote_amount is None:
            raise ValueError(
                f"sizing_rule {rule.sizing_rule_id}: FIXED_QUOTE requires fixed_quote_amount"
            )
        amount = rule.fixed_quote_amount

    elif rule.rule_type == "PCT_OF_VARIABLE":
        if rule.source_variable_key is None:
            raise ValueError(
                f"sizing_rule {rule.sizing_rule_id}: PCT_OF_VARIABLE requires source_variable_key"
            )
        validate_variable_key(rule.source_variable_key)
        if rule.multiplier_bps is None:
            raise ValueError(
                f"sizing_rule {rule.sizing_rule_id}: PCT_OF_VARIABLE requires multiplier_bps"
            )
        source_value = variable_values.get(rule.source_variable_key)
        if source_value is None:
            return None
        amount = source_value * Decimal(rule.multiplier_bps) / Decimal("10000")

    else:
        raise ValueError(f"unhandled rule_type {rule.rule_type!r}")

    if rule.floor_quote_amount is not None:
        amount = max(rule.floor_quote_amount, amount)
    if rule.cap_quote_amount is not None:
        amount = min(rule.cap_quote_amount, amount)

    return amount


# ---------------------------------------------------------------------------
# Anchor price resolution
# NATIVE_SHORT_ANCHOR_HIGH resolves to NativeShortContextRow.anchor_high_price.
# Pass anchor_high_price only. Do not pass fib extension levels (ext_1_272 /
# ext_1_618) or ProfitPlan card fields; those are above the buy zone and are
# not appropriate as recovery-exit anchors.
# ---------------------------------------------------------------------------

def resolve_anchor_price(
    anchor_type: str,
    *,
    anchor_high_price: Decimal | None,
) -> Decimal:
    if anchor_type not in ALLOWED_ANCHOR_TYPES:
        raise ValueError(
            f"anchor_type {anchor_type!r} is not supported. "
            f"Only {sorted(ALLOWED_ANCHOR_TYPES)} are permitted in v1."
        )

    if anchor_type == "NATIVE_SHORT_ANCHOR_HIGH":
        if anchor_high_price is None:
            raise ValueError(
                "anchor_type NATIVE_SHORT_ANCHOR_HIGH requires a non-null anchor_high_price. "
                "Ensure native short context is AVAILABLE before resolving an anchor."
            )
        if anchor_high_price <= Decimal("0"):
            raise ValueError(
                f"anchor_high_price must be > 0, got {anchor_high_price}"
            )
        return anchor_high_price

    raise ValueError(f"unhandled anchor_type {anchor_type!r}")


# ---------------------------------------------------------------------------
# Per-leg price and quantity
# ---------------------------------------------------------------------------

def resolve_leg_limit_price(
    anchor_price: Decimal,
    price_offset_bps: int,
) -> Decimal:
    return anchor_price * (Decimal("1") + Decimal(price_offset_bps) / Decimal("10000"))


def resolve_leg_base_quantity(
    allocated_quote_notional: Decimal,
    limit_price: Decimal,
) -> Decimal:
    if limit_price <= Decimal("0"):
        raise ValueError(f"limit_price must be > 0, got {limit_price}")
    return allocated_quote_notional / limit_price


# ---------------------------------------------------------------------------
# Full ladder preview
# ---------------------------------------------------------------------------

def resolve_ladder_preview(
    profile: LadderProfile,
    legs: list[LadderLeg],
    anchor_price: Decimal,
    quote_amount: Decimal,
) -> LadderPreview:
    if profile.side.strip().upper() == "SELL":
        raise PermissionError(
            "direct SELL ladder preview is disabled; route through "
            "manual_execution_service_v1.process()"
        )

    if not legs:
        raise ValueError(
            f"profile {profile.profile_code!r} has no active legs for version "
            f"{profile.current_version}; cannot build preview."
        )

    if quote_amount <= Decimal("0"):
        raise ValueError(f"quote_amount must be > 0, got {quote_amount}")

    total_allocation = sum(leg.allocation_bps for leg in legs)
    if total_allocation != _ALLOCATION_TOTAL_BPS:
        raise ValueError(
            f"active legs for profile {profile.profile_code!r} version "
            f"{profile.current_version} sum to {total_allocation} bps; "
            f"must sum to exactly {_ALLOCATION_TOTAL_BPS}."
        )

    leg_previews: list[LadderLegPreview] = []
    for leg in sorted(legs, key=lambda lg: lg.leg_number):
        allocated = quote_amount * Decimal(leg.allocation_bps) / Decimal(_ALLOCATION_TOTAL_BPS)
        limit_price = resolve_leg_limit_price(anchor_price, leg.price_offset_bps)
        base_qty = resolve_leg_base_quantity(allocated, limit_price)
        leg_previews.append(
            LadderLegPreview(
                leg_number=leg.leg_number,
                price_offset_bps=leg.price_offset_bps,
                allocation_bps=leg.allocation_bps,
                allocated_quote_notional=allocated,
                limit_price=limit_price,
                estimated_base_quantity=base_qty,
                order_type=leg.order_type,
                time_in_force=leg.time_in_force,
            )
        )

    total_base_qty = sum(lp.estimated_base_quantity for lp in leg_previews)

    return LadderPreview(
        profile_code=profile.profile_code,
        profile_version=profile.current_version,
        side=profile.side,
        anchor_type=profile.anchor_type,
        anchor_price=anchor_price,
        quote_amount=quote_amount,
        legs=tuple(leg_previews),
        total_allocation_bps=total_allocation,
        estimated_total_base_quantity=total_base_qty,
    )


# ---------------------------------------------------------------------------
# Venue-aware rounded preview
#
# resolve_ladder_preview() above returns raw, unquantized prices/quantities —
# it always has and existing callers/tests depend on that raw shape, so its
# signature is unchanged here. Any caller that intends to use a preview for
# anything beyond a raw estimate (i.e. anything that could become a real
# execution-plan leg) must additionally round it through this function,
# which delegates to the single canonical rounding service
# (src.execution_planner.canonical_rounding_v1) rather than re-implementing
# tick/step rounding here. See
# docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
# finding F3 (side-unaware rounding) and F4/F5 (missing min-qty/min-notional
# and tick/step metadata).
# ---------------------------------------------------------------------------

def round_ladder_preview(
    preview: LadderPreview,
    *,
    constraints: VenueExecutionConstraints,
) -> tuple[RoundedLeg, ...]:
    """Round every leg of a raw LadderPreview via the canonical rounding
    service. Returns one RoundedLeg per input leg, in the same order;
    callers must check RoundedLeg.is_valid per leg and must not submit an
    invalid leg."""
    if preview.side.strip().upper() == "SELL":
        raise PermissionError(
            "direct SELL ladder rounding is disabled; route through "
            "manual_execution_service_v1.process()"
        )
    return tuple(
        round_leg_for_side(
            side=preview.side,
            raw_price=leg.limit_price,
            raw_quantity_base=leg.estimated_base_quantity,
            constraints=constraints,
        )
        for leg in preview.legs
    )
