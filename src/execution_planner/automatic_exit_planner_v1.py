"""Pure Phase 3 planner from an approved automatic-exit gate to a SELL ladder.

This module is deliberately separate from the manual SELL planner.  It uses
the same canonical venue rounding service, but has no manual request,
approval, reservation, executor, broker, DB, or runtime dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Final

from src.decision_gate.automatic_exit_gate_v1 import (
    STATE_APPROVED,
    AutomaticExitGateDecisionV1,
)
from src.execution_planner.canonical_rounding_v1 import (
    round_leg_for_side,
    round_quantity_down,
)
from src.market_rules.venue_execution_constraints_v1 import (
    DEFAULT_MAX_METADATA_AGE_SECONDS,
    STATUS_FRESH,
    VenueExecutionConstraints,
)


PLANNER_VERSION: Final[str] = "automatic_exit_planner_v1"
SIDE_SELL: Final[str] = "SELL"

# Fixed V1 execution mechanics only: two passive SELL limits, equally sized,
# at reference and 25 bps above it.  This is not exit-policy selection.
DEFAULT_LADDER_MULTIPLIERS: Final[tuple[Decimal, ...]] = (
    Decimal("1.0000"),
    Decimal("1.0025"),
)


class AutomaticExitPlanningError(ValueError):
    """Fail-closed planning rejection with a stable machine reason."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class AutomaticExitPlanningContextV1:
    """Current public planning facts for one exact approved gate decision."""

    trading_account_id: int
    position_reference: str
    venue: str
    asset_id: int
    market: str
    reference_price: Decimal
    venue_constraints: VenueExecutionConstraints
    planning_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticExitPlanLegV1:
    leg_index: int
    side: str
    limit_price: Decimal
    quantity_base: Decimal
    quote_notional: Decimal
    post_only: bool
    time_in_force: str


@dataclass(frozen=True)
class AutomaticExitGateApprovalProvenanceV1:
    state: str
    reason_code: str
    approved_fraction_candidate: Decimal
    approved_quantity_ceiling_base: Decimal


@dataclass(frozen=True)
class AutomaticExitPlanV1:
    trading_account_id: int
    position_reference: str
    venue: str
    asset_id: int
    market: str
    side: str
    final_quantity_base: Decimal
    legs: tuple[AutomaticExitPlanLegV1, ...]
    candidate_action: str
    candidate_reason_code: str
    candidate_evidence_id: str
    exit_profile_id: str
    exit_profile_version: str
    gate_approval: AutomaticExitGateApprovalProvenanceV1
    planner_version: str
    planning_ts_utc: datetime


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _normalized_lower(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(value.strip().lower() for value in values)


def _reject(condition: bool, reason_code: str) -> None:
    if condition:
        raise AutomaticExitPlanningError(reason_code)


def _validate_gate_and_context(
    decision: AutomaticExitGateDecisionV1,
    context: AutomaticExitPlanningContextV1,
) -> Decimal:
    _reject(decision.state != STATE_APPROVED, "GATE_DECISION_NOT_APPROVED")
    ceiling = decision.approved_quantity_ceiling_base
    _reject(ceiling is None or ceiling <= 0, "APPROVED_QUANTITY_CEILING_INVALID")
    candidate = decision.candidate
    _reject(
        decision.approved_fraction_candidate is None
        or decision.approved_fraction_candidate != candidate.reduction_fraction_candidate
        or decision.approved_fraction_candidate <= 0
        or decision.approved_fraction_candidate > 1,
        "GATE_CANDIDATE_PROVENANCE_MISMATCH",
    )
    _reject(
        candidate.candidate_action not in {"REDUCE", "EXIT"}
        or not _nonempty(candidate.evidence_id)
        or not _nonempty(candidate.exit_profile_id)
        or not _nonempty(candidate.exit_profile_version),
        "CANDIDATE_PROVENANCE_INVALID",
    )
    _reject(
        not _aware(context.planning_ts_utc)
        or context.reference_price <= 0
        or context.trading_account_id <= 0
        or context.asset_id <= 0
        or not all(_nonempty(value) for value in (context.position_reference, context.venue, context.market)),
        "PLANNING_CONTEXT_INVALID",
    )
    _reject(
        (candidate.trading_account_id, candidate.position_reference, candidate.venue, candidate.asset_id, candidate.market)
        != (context.trading_account_id, context.position_reference, context.venue, context.asset_id, context.market),
        "GATE_CANDIDATE_CONTEXT_IDENTITY_MISMATCH",
    )
    constraints = context.venue_constraints
    _reject(constraints.status != STATUS_FRESH, "VENUE_CONSTRAINTS_NOT_FRESH")
    _reject(
        not _aware(constraints.metadata_synced_ts_utc),
        "VENUE_CONSTRAINTS_TIMESTAMP_INVALID",
    )
    metadata_age = context.planning_ts_utc - constraints.metadata_synced_ts_utc
    _reject(
        metadata_age < timedelta(0)
        or metadata_age > timedelta(seconds=DEFAULT_MAX_METADATA_AGE_SECONDS),
        "VENUE_CONSTRAINTS_TIMESTAMP_STALE_OR_FUTURE",
    )
    _reject(
        constraints.venue.strip().lower() != context.venue.strip().lower()
        or constraints.market.strip().upper().replace("/", "-") != context.market.strip().upper().replace("/", "-"),
        "VENUE_CONSTRAINTS_IDENTITY_MISMATCH",
    )
    _reject(
        "limit" not in _normalized_lower(constraints.supported_order_types),
        "VENUE_LIMIT_ORDER_UNSUPPORTED",
    )
    _reject(
        "gtc" not in _normalized_lower(constraints.supported_time_in_force),
        "VENUE_GTC_UNSUPPORTED",
    )
    _reject(
        constraints.tick_size <= 0
        or constraints.qty_step_size <= 0
        or constraints.min_base_quantity < 0
        or constraints.min_quote_notional < 0,
        "VENUE_CONSTRAINTS_INVALID",
    )
    return ceiling


def _allocate_quantity_steps(total: Decimal, step: Decimal) -> tuple[Decimal, ...]:
    """Allocate already-rounded quantity without changing its total exposure."""
    total_steps = int((total / step).to_integral_value(rounding=ROUND_DOWN))
    _reject(total_steps <= 0, "QUANTITY_ROUNDS_TO_ZERO")
    first_steps = total_steps // 2
    second_steps = total_steps - first_steps
    _reject(first_steps <= 0 or second_steps <= 0, "IMPOSSIBLE_LADDER_ALLOCATION")
    return (Decimal(first_steps) * step, Decimal(second_steps) * step)


def build_automatic_exit_plan_v1(
    *,
    decision: AutomaticExitGateDecisionV1,
    context: AutomaticExitPlanningContextV1,
) -> AutomaticExitPlanV1:
    """Build an immutable SELL ladder from exactly one APPROVED gate decision."""
    ceiling = _validate_gate_and_context(decision, context)
    constraints = context.venue_constraints

    # This is the sole total-quantity normalization.  Later leg round calls
    # validate venue legality; their raw quantities are already exact steps.
    final_quantity = round_quantity_down(ceiling, constraints.qty_step_size)
    _reject(final_quantity <= 0, "QUANTITY_ROUNDS_TO_ZERO")
    _reject(final_quantity > ceiling, "PLANNED_QUANTITY_EXCEEDS_GATE_CEILING")
    _reject(final_quantity < constraints.min_base_quantity, "FINAL_QUANTITY_BELOW_MIN_BASE_QUANTITY")

    quantities = _allocate_quantity_steps(final_quantity, constraints.qty_step_size)
    legs: list[AutomaticExitPlanLegV1] = []
    for index, (multiplier, quantity) in enumerate(zip(DEFAULT_LADDER_MULTIPLIERS, quantities), start=1):
        rounded = round_leg_for_side(
            side=SIDE_SELL,
            raw_price=context.reference_price * multiplier,
            raw_quantity_base=quantity,
            constraints=constraints,
        )
        _reject(not rounded.is_valid, f"LADDER_LEG_{index}_INVALID:{','.join(rounded.rejection_reasons)}")
        legs.append(AutomaticExitPlanLegV1(
            leg_index=index,
            side=SIDE_SELL,
            limit_price=rounded.rounded_price,
            quantity_base=rounded.rounded_quantity_base,
            quote_notional=rounded.rounded_notional_quote,
            post_only=True,
            time_in_force="GTC",
        ))

    planned_total = sum((leg.quantity_base for leg in legs), Decimal("0"))
    _reject(planned_total != final_quantity, "LADDER_TOTAL_DOES_NOT_MATCH_FINAL_QUANTITY")
    _reject(planned_total > ceiling, "PLANNED_QUANTITY_EXCEEDS_GATE_CEILING")
    candidate = decision.candidate
    return AutomaticExitPlanV1(
        trading_account_id=context.trading_account_id,
        position_reference=context.position_reference,
        venue=context.venue,
        asset_id=context.asset_id,
        market=context.market,
        side=SIDE_SELL,
        final_quantity_base=final_quantity,
        legs=tuple(legs),
        candidate_action=candidate.candidate_action,
        candidate_reason_code=candidate.reason_code,
        candidate_evidence_id=candidate.evidence_id,
        exit_profile_id=candidate.exit_profile_id,
        exit_profile_version=candidate.exit_profile_version,
        gate_approval=AutomaticExitGateApprovalProvenanceV1(
            state=decision.state,
            reason_code=decision.reason_code,
            approved_fraction_candidate=decision.approved_fraction_candidate,
            approved_quantity_ceiling_base=ceiling,
        ),
        planner_version=PLANNER_VERSION,
        planning_ts_utc=context.planning_ts_utc,
    )
