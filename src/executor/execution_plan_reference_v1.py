"""
execution_plan_reference_v1 -- the canonical, side-neutral shape of an
already-approved, already-immutable execution plan that any upstream lane
(manual execution, algorithmic SELL #392, future algorithmic BUY #399) may
hand to the shared executor boundary (Issue #206).

Layer: executor intake boundary, pure/no DB access, no broker calls.

This module defines the *contract*, not persistence: ApprovedExecutionPlanV1
is an in-memory dataclass, never itself a DB row. Ownership of persisting
and auditing the upstream plan (manual_execution_plan_snapshot for the
manual lane; whatever #392/#399 define for their own lanes) stays entirely
with the upstream lane -- src.executor.execution_handoff_v1 binds to it
only through (plan_source, plan_reference_id) identity plus a
plan_content_hash computed here, never through a cross-schema foreign key
into a table this issue does not own.

compute_plan_content_hash is deterministic and order-sensitive on leg_index
(legs are hashed in leg_index order regardless of input order), so the
exact same approved plan content always yields the exact same hash and any
difference in account/venue/market/side/leg content changes it. This is
the mechanism that lets a retried handoff intake for the same
(plan_source, plan_reference_id) be verified as content-identical rather
than blindly trusted.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

SIDE_BUY: Final[str] = "BUY"
SIDE_SELL: Final[str] = "SELL"
VALID_SIDES: Final[frozenset[str]] = frozenset({SIDE_BUY, SIDE_SELL})


class ApprovedExecutionPlanValidationError(ValueError):
    """Fail-closed: an ApprovedExecutionPlanV1 failed a structural/identity
    invariant before it could be hashed or handed to intake()."""


@dataclass(frozen=True)
class ApprovedExecutionPlanLegV1:
    leg_index: int
    side: str
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class ApprovedExecutionPlanV1:
    """The side-neutral shape every upstream lane converges on before
    calling src.executor.execution_handoff_v1.ExecutionHandoffRepository.intake().
    """

    plan_source: str
    plan_reference_id: str
    trading_account_id: int
    venue: str
    market: str
    side: str
    legs: tuple[ApprovedExecutionPlanLegV1, ...]


def _validate(plan: ApprovedExecutionPlanV1) -> None:
    if not plan.plan_source.strip():
        raise ApprovedExecutionPlanValidationError("PLAN_SOURCE_REQUIRED")
    if not plan.plan_reference_id.strip():
        raise ApprovedExecutionPlanValidationError("PLAN_REFERENCE_ID_REQUIRED")
    if plan.trading_account_id <= 0:
        raise ApprovedExecutionPlanValidationError("TRADING_ACCOUNT_ID_INVALID")
    if not plan.venue.strip():
        raise ApprovedExecutionPlanValidationError("VENUE_REQUIRED")
    if not plan.market.strip():
        raise ApprovedExecutionPlanValidationError("MARKET_REQUIRED")
    if plan.side not in VALID_SIDES:
        raise ApprovedExecutionPlanValidationError(f"SIDE_INVALID: {plan.side}")
    if not plan.legs:
        raise ApprovedExecutionPlanValidationError("PLAN_HAS_NO_LEGS")
    seen_indices: set[int] = set()
    for leg in plan.legs:
        if leg.side != plan.side:
            raise ApprovedExecutionPlanValidationError(
                f"LEG_SIDE_MISMATCH: leg_index={leg.leg_index} leg.side={leg.side} plan.side={plan.side}"
            )
        if leg.leg_index <= 0:
            raise ApprovedExecutionPlanValidationError(
                f"LEG_INDEX_INVALID: {leg.leg_index}"
            )
        if leg.leg_index in seen_indices:
            raise ApprovedExecutionPlanValidationError(
                f"DUPLICATE_LEG_INDEX: {leg.leg_index}"
            )
        seen_indices.add(leg.leg_index)
        if leg.price <= 0:
            raise ApprovedExecutionPlanValidationError(
                f"LEG_PRICE_NOT_POSITIVE: leg_index={leg.leg_index}"
            )
        if leg.quantity <= 0:
            raise ApprovedExecutionPlanValidationError(
                f"LEG_QUANTITY_NOT_POSITIVE: leg_index={leg.leg_index}"
            )


def compute_plan_content_hash(plan: ApprovedExecutionPlanV1) -> str:
    """Deterministic sha256 hex over the plan's full identity and leg
    content, legs sorted by leg_index. Raises
    ApprovedExecutionPlanValidationError on any structural/identity
    invariant violation before hashing."""
    _validate(plan)
    ordered_legs = sorted(plan.legs, key=lambda leg: leg.leg_index)
    parts = [
        f"plan_source={plan.plan_source.strip()}",
        f"plan_reference_id={plan.plan_reference_id.strip()}",
        f"trading_account_id={plan.trading_account_id}",
        f"venue={plan.venue.strip().lower()}",
        f"market={plan.market.strip().upper()}",
        f"side={plan.side}",
    ]
    for leg in ordered_legs:
        parts.append(
            f"leg={leg.leg_index}:{leg.side}:{leg.price!s}:{leg.quantity!s}"
        )
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
