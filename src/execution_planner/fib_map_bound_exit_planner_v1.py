"""Issue #753 Phase B3: pure planner from a typed map-bound exit decision to a SELL plan.

Consumes exactly one already-evaluated, in-memory
``FibMapBoundExitDecisionV1`` (#753 Phase B2,
``src/decision_gate/fib_map_bound_exit_decision_v1.py``) together with the
exact ``FibMapBoundTradeV1`` binding it was evaluated against, and produces
an immutable single-leg SELL execution plan.

This module never re-evaluates exit policy, never re-derives target price or
decision quantity, and never infers ownership from broker wallet balance --
``decision.decision_quantity_base`` and ``decision.target_price`` are taken
exactly as decided. It only performs venue-aware rounding and structural
validation, exactly like ``automatic_exit_planner_v1`` (#392) for the
existing automatic-exit lane. ``execution_planner`` remains the sole owner
of execution intent; this module does not call the broker, does not touch
the executor, and does not write to the database.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from src.decision_gate.fib_map_bound_exit_decision_v1 import (
    REASON_OK,
    STATE_PARTIAL_PROFIT_TARGET,
    STATE_PROTECTIVE_EXIT,
    FibMapBoundExitDecisionV1,
)
from src.decision_gate.fib_map_bound_trade_v1 import (
    FibMapBoundTradeError,
    FibMapBoundTradeV1,
    validate_fib_map_bound_trade_v1,
)
from src.execution_planner.canonical_rounding_v1 import round_leg_for_side
from src.market_rules.venue_execution_constraints_v1 import (
    DEFAULT_MAX_METADATA_AGE_SECONDS,
    STATUS_FRESH,
    VenueExecutionConstraints,
)

PLANNER_VERSION: Final[str] = "fib_map_bound_exit_planner_v1"
SIDE_SELL: Final[str] = "SELL"

_ACTIONABLE_DECISION_STATES: Final[frozenset[str]] = frozenset(
    {STATE_PARTIAL_PROFIT_TARGET, STATE_PROTECTIVE_EXIT}
)


class FibMapBoundExitPlanningError(ValueError):
    """Fail-closed planning rejection with a stable machine reason."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class FibMapBoundExitPlanningContextV1:
    """Current public planning facts for one exact map-bound exit decision."""

    venue_constraints: VenueExecutionConstraints
    planning_ts_utc: datetime


@dataclass(frozen=True)
class FibMapBoundExitPlanLegV1:
    leg_index: int
    side: str
    limit_price: Decimal
    quantity_base: Decimal
    quote_notional: Decimal
    post_only: bool
    time_in_force: str


@dataclass(frozen=True)
class FibMapBoundExitPlanV1:
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    binding_id: str
    decision_id: str
    decision_state: str
    target_index: int | None
    side: str
    final_quantity_base: Decimal
    legs: tuple[FibMapBoundExitPlanLegV1, ...]
    planner_version: str
    planning_ts_utc: datetime


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _reject(condition: bool, reason_code: str) -> None:
    if condition:
        raise FibMapBoundExitPlanningError(reason_code)


def _validate_decision_and_binding(
    decision: FibMapBoundExitDecisionV1,
    binding: FibMapBoundTradeV1,
    context: FibMapBoundExitPlanningContextV1,
) -> None:
    _reject(
        not isinstance(decision, FibMapBoundExitDecisionV1),
        "DECISION_INVALID",
    )
    _reject(decision.state not in _ACTIONABLE_DECISION_STATES, "DECISION_NOT_ACTIONABLE")
    _reject(decision.reason_code != REASON_OK, "DECISION_REASON_NOT_OK")

    _reject(not isinstance(binding, FibMapBoundTradeV1), "BINDING_INVALID")
    try:
        validate_fib_map_bound_trade_v1(binding)
    except FibMapBoundTradeError:
        raise FibMapBoundExitPlanningError("BINDING_INVALID") from None

    _reject(
        decision.binding_id != binding.binding_id or decision.trade_id != binding.trade_id,
        "DECISION_BINDING_IDENTITY_MISMATCH",
    )
    _reject(
        not isinstance(decision.decision_quantity_base, Decimal)
        or not decision.decision_quantity_base.is_finite()
        or decision.decision_quantity_base <= 0,
        "DECISION_QUANTITY_INVALID",
    )
    _reject(
        not isinstance(decision.target_price, Decimal)
        or not decision.target_price.is_finite()
        or decision.target_price <= 0,
        "DECISION_TARGET_PRICE_INVALID",
    )

    _reject(not _aware(context.planning_ts_utc), "PLANNING_CONTEXT_INVALID")
    constraints = context.venue_constraints
    _reject(constraints.status != STATUS_FRESH, "VENUE_CONSTRAINTS_NOT_FRESH")
    _reject(not _aware(constraints.metadata_synced_ts_utc), "VENUE_CONSTRAINTS_TIMESTAMP_INVALID")
    metadata_age = context.planning_ts_utc - constraints.metadata_synced_ts_utc
    _reject(
        metadata_age < timedelta(0) or metadata_age > timedelta(seconds=DEFAULT_MAX_METADATA_AGE_SECONDS),
        "VENUE_CONSTRAINTS_TIMESTAMP_STALE_OR_FUTURE",
    )
    _reject(
        constraints.venue.strip().lower() != binding.venue.strip().lower()
        or constraints.market.strip().upper().replace("/", "-") != binding.market.strip().upper().replace("/", "-"),
        "VENUE_CONSTRAINTS_IDENTITY_MISMATCH",
    )
    normalized_order_types = frozenset(value.strip().lower() for value in constraints.supported_order_types)
    normalized_tif = frozenset(value.strip().lower() for value in constraints.supported_time_in_force)
    _reject("limit" not in normalized_order_types, "VENUE_LIMIT_ORDER_UNSUPPORTED")
    _reject("gtc" not in normalized_tif, "VENUE_GTC_UNSUPPORTED")
    _reject(
        constraints.tick_size <= 0
        or constraints.qty_step_size <= 0
        or constraints.min_base_quantity < 0
        or constraints.min_quote_notional < 0,
        "VENUE_CONSTRAINTS_INVALID",
    )


def build_fib_map_bound_exit_plan_v1(
    *,
    decision: FibMapBoundExitDecisionV1,
    binding: FibMapBoundTradeV1,
    context: FibMapBoundExitPlanningContextV1,
) -> FibMapBoundExitPlanV1:
    """Build an immutable single-leg SELL plan from one actionable decision.

    Fails closed on any decision/binding identity mismatch or non-actionable
    decision state (``NO_ACTION`` / ``FAIL_CLOSED``). Never recomputes
    ``decision_quantity_base`` or ``target_price``: this planner only
    performs venue-aware rounding of the exact values the decision already
    produced, so a partial profit-target decision plans exactly its decided
    bounded quantity and a protective-exit decision plans exactly the full
    remaining owned quantity the decision already computed.
    """
    _validate_decision_and_binding(decision, binding, context)
    constraints = context.venue_constraints

    rounded = round_leg_for_side(
        side=SIDE_SELL,
        raw_price=decision.target_price,
        raw_quantity_base=decision.decision_quantity_base,
        constraints=constraints,
    )
    _reject(not rounded.is_valid, f"PLAN_LEG_INVALID:{','.join(rounded.rejection_reasons)}")

    leg = FibMapBoundExitPlanLegV1(
        leg_index=1,
        side=SIDE_SELL,
        limit_price=rounded.rounded_price,
        quantity_base=rounded.rounded_quantity_base,
        quote_notional=rounded.rounded_notional_quote,
        post_only=True,
        time_in_force="GTC",
    )
    _reject(leg.quantity_base > decision.decision_quantity_base, "PLANNED_QUANTITY_EXCEEDS_DECISION_QUANTITY")

    return FibMapBoundExitPlanV1(
        trading_account_id=binding.trading_account_id,
        venue=binding.venue,
        market=binding.market,
        strategy_bucket_id=binding.strategy_bucket_id,
        strategy_id=binding.strategy_id,
        strategy_version=binding.strategy_version,
        trade_id=binding.trade_id,
        binding_id=binding.binding_id,
        decision_id=decision.decision_id,
        decision_state=decision.state,
        target_index=decision.target_index,
        side=SIDE_SELL,
        final_quantity_base=leg.quantity_base,
        legs=(leg,),
        planner_version=PLANNER_VERSION,
        planning_ts_utc=context.planning_ts_utc,
    )
