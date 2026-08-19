"""Pure Phase 3 planner from an approved automatic-BUY gate decision to a
BUY ladder.

Issue #399 Phase 3: the execution_planner owner of immutable automatic-BUY
execution intent. This module is deliberately separate from any manual BUY
workflow. It uses the same canonical venue rounding service the SELL-side
``automatic_exit_planner_v1`` uses, but has no manual request, approval,
reservation, executor, broker, DB, or runtime dependency.

It consumes exactly one APPROVED ``AutomaticBuyGateDecisionV1`` (Issue #399
Phase 2, ``src.decision_gate.automatic_buy_gate_v1``) and a caller-assembled
``AutomaticBuyPlanningContextV1`` carrying the account/market facts the
market-only ``AutomaticBuyCandidateV1`` never carries (trading account
identity, reference price). It never re-evaluates account permission,
allocation, protection, or entry/re-entry zone geometry -- those are owned
upstream by ``entry_policy.automatic_buy_candidate_v1`` and
``decision_gate.automatic_buy_gate_v1``.

The gate-approved ceiling for BUY is a EUR notional ceiling
(``approved_notional_ceiling_eur``), not a base-quantity ceiling like the
exit gate's ``approved_quantity_ceiling_base``. This planner converts that
notional ceiling to a base quantity using the supplied reference price,
then rounds down to the venue's quantity step -- so the resulting quantity
never implies more than the approved EUR ceiling at the reference price.
Total planned notional across all legs is independently re-checked against
the ceiling after rounding, since BUY price legs are placed at or below the
reference price (never above it, see below) and are never assumed safe by
construction alone.

Rounding semantics (delegated to ``canonical_rounding_v1``):

  BUY price  -> ROUND_DOWN (never place a buy limit above the analytical
                rebuy/entry target)
  quantity   -> ROUND_DOWN (never exceed the gate-approved ceiling)

Ladder legs are placed at the reference price and slightly below it
(never above), mirroring the SELL planner's placement of legs at the
reference price and slightly above it (never below) -- both directions are
the side-safe side for their respective side.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Final

from src.decision_gate.automatic_buy_gate_v1 import (
    STATE_APPROVED,
    AutomaticBuyGateDecisionV1,
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


PLANNER_VERSION: Final[str] = "automatic_buy_planner_v1"
SIDE_BUY: Final[str] = "BUY"

# Fixed V1 execution mechanics only: two passive BUY limits, equally sized,
# at reference and 25 bps below it. This is not entry-policy zone selection.
DEFAULT_LADDER_MULTIPLIERS: Final[tuple[Decimal, ...]] = (
    Decimal("1.0000"),
    Decimal("0.9975"),
)

SUPPORTED_CANDIDATE_ACTIONS: Final[frozenset[str]] = frozenset({"ENTER", "RE_ENTER"})


class AutomaticBuyPlanningError(ValueError):
    """Fail-closed planning rejection with a stable machine reason."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class AutomaticBuyPlanningContextV1:
    """Current public planning facts for one exact approved gate decision.

    ``trading_account_id`` and ``reference_price`` are account/market facts
    the market-only ``AutomaticBuyCandidateV1`` never carries by design; the
    caller assembles them fresh, the same way it assembled
    ``AutomaticBuyGateContextV1`` for the Phase 2 gate call.
    """

    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    reference_price: Decimal
    venue_constraints: VenueExecutionConstraints
    planning_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticBuyPlanLegV1:
    leg_index: int
    side: str
    limit_price: Decimal
    quantity_base: Decimal
    quote_notional: Decimal
    post_only: bool
    time_in_force: str


@dataclass(frozen=True)
class AutomaticBuyGateApprovalProvenanceV1:
    state: str
    reason_code: str
    approved_notional_ceiling_eur: Decimal


@dataclass(frozen=True)
class AutomaticBuyPlanV1:
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    side: str
    final_quantity_base: Decimal
    legs: tuple[AutomaticBuyPlanLegV1, ...]
    candidate_action: str
    candidate_reason_code: str
    candidate_evidence_id: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    gate_approval: AutomaticBuyGateApprovalProvenanceV1
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
        raise AutomaticBuyPlanningError(reason_code)


def _validate_gate_and_context(
    decision: AutomaticBuyGateDecisionV1,
    context: AutomaticBuyPlanningContextV1,
) -> Decimal:
    _reject(decision.state != STATE_APPROVED, "GATE_DECISION_NOT_APPROVED")
    ceiling = decision.approved_notional_ceiling_eur
    _reject(ceiling is None or ceiling <= 0, "APPROVED_NOTIONAL_CEILING_INVALID")
    candidate = decision.candidate
    _reject(
        candidate.candidate_action not in SUPPORTED_CANDIDATE_ACTIONS
        or not _nonempty(candidate.evidence_id)
        or not _nonempty(candidate.strategy_id)
        or not _nonempty(candidate.strategy_version)
        or not _nonempty(candidate.setup_id),
        "CANDIDATE_PROVENANCE_INVALID",
    )
    _reject(
        not _aware(context.planning_ts_utc)
        or context.reference_price <= 0
        or context.trading_account_id <= 0
        or context.asset_id <= 0
        or not all(_nonempty(value) for value in (context.venue, context.market)),
        "PLANNING_CONTEXT_INVALID",
    )
    _reject(
        (candidate.venue, candidate.asset_id, candidate.market)
        != (context.venue, context.asset_id, context.market),
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


def build_automatic_buy_plan_v1(
    *,
    decision: AutomaticBuyGateDecisionV1,
    context: AutomaticBuyPlanningContextV1,
) -> AutomaticBuyPlanV1:
    """Build an immutable BUY ladder from exactly one APPROVED gate decision.

    The gate ceiling is a EUR notional bound, not a base quantity: it is
    converted to a base quantity via ``context.reference_price``, rounded
    down to the venue quantity step, then never exceeded again -- both by
    quantity (each leg's rounded quantity sums back to the exact total) and
    by notional (the sum of rounded leg notionals is re-checked against the
    ceiling, since BUY legs price below reference and rounding is
    independent per field).
    """
    ceiling = _validate_gate_and_context(decision, context)
    constraints = context.venue_constraints

    raw_quantity_from_ceiling = ceiling / context.reference_price
    final_quantity = round_quantity_down(raw_quantity_from_ceiling, constraints.qty_step_size)
    _reject(final_quantity <= 0, "QUANTITY_ROUNDS_TO_ZERO")
    _reject(final_quantity < constraints.min_base_quantity, "FINAL_QUANTITY_BELOW_MIN_BASE_QUANTITY")
    _reject(final_quantity * context.reference_price > ceiling, "PLANNED_NOTIONAL_EXCEEDS_GATE_CEILING")

    quantities = _allocate_quantity_steps(final_quantity, constraints.qty_step_size)
    legs: list[AutomaticBuyPlanLegV1] = []
    for index, (multiplier, quantity) in enumerate(zip(DEFAULT_LADDER_MULTIPLIERS, quantities), start=1):
        rounded = round_leg_for_side(
            side=SIDE_BUY,
            raw_price=context.reference_price * multiplier,
            raw_quantity_base=quantity,
            constraints=constraints,
        )
        _reject(not rounded.is_valid, f"LADDER_LEG_{index}_INVALID:{','.join(rounded.rejection_reasons)}")
        legs.append(AutomaticBuyPlanLegV1(
            leg_index=index,
            side=SIDE_BUY,
            limit_price=rounded.rounded_price,
            quantity_base=rounded.rounded_quantity_base,
            quote_notional=rounded.rounded_notional_quote,
            post_only=True,
            time_in_force="GTC",
        ))

    planned_total_quantity = sum((leg.quantity_base for leg in legs), Decimal("0"))
    _reject(planned_total_quantity != final_quantity, "LADDER_TOTAL_DOES_NOT_MATCH_FINAL_QUANTITY")
    planned_total_notional = sum((leg.quote_notional for leg in legs), Decimal("0"))
    _reject(planned_total_notional > ceiling, "PLANNED_NOTIONAL_EXCEEDS_GATE_CEILING")

    candidate = decision.candidate
    return AutomaticBuyPlanV1(
        trading_account_id=context.trading_account_id,
        venue=context.venue,
        asset_id=context.asset_id,
        market=context.market,
        side=SIDE_BUY,
        final_quantity_base=final_quantity,
        legs=tuple(legs),
        candidate_action=candidate.candidate_action,
        candidate_reason_code=candidate.reason_code,
        candidate_evidence_id=candidate.evidence_id,
        strategy_id=candidate.strategy_id,
        strategy_version=candidate.strategy_version,
        setup_id=candidate.setup_id,
        gate_approval=AutomaticBuyGateApprovalProvenanceV1(
            state=decision.state,
            reason_code=decision.reason_code,
            approved_notional_ceiling_eur=ceiling,
        ),
        planner_version=PLANNER_VERSION,
        planning_ts_utc=context.planning_ts_utc,
    )
