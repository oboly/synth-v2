"""Issue #753 Phase B3: pure lossless adapter, mirroring #392's exit adapter.

Translates an already-produced, already-approved, immutable in-memory
``FibMapBoundExitPlanV1`` (#753, ``fib_map_bound_exit_planner_v1``) into the
shared executor handoff contract ``ApprovedExecutionPlanV1`` (Issue #206),
with no re-evaluation of exit policy, no re-run of ``decision_gate``, no
quantity/price recompute or re-rounding, no broker/credential/authority/
kill-switch inspection, and no order submission.

This module is the sole deliberate map-bound-exit -> #206 import boundary,
exactly like ``automatic_exit_execution_handoff_adapter_v1`` is for the
existing automatic-exit lane. Reuses the same shared ``ApprovedExecutionPlanV1``
/ ``ExecutionPlanLegV1`` contract rather than introducing a parallel SELL
handoff shape.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Final

from src.execution_planner.fib_map_bound_exit_planner_v1 import (
    FibMapBoundExitPlanLegV1,
    FibMapBoundExitPlanV1,
)
from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanV1,
    ExecutionPlanLegV1,
)

# Stable source identifier for the shared executor handoff. This is the
# adapter's own source label, distinct from (and not derived from) the
# planner's own version string, so a future planner-version bump cannot
# silently change plan_source.
PLAN_SOURCE_FIB_MAP_BOUND_EXIT_V1: Final[str] = "fib_map_bound_exit_planner_v1"

SIDE_SELL: Final[str] = "SELL"

_PLAN_REFERENCE_ID_CONTRACT_VERSION: Final[str] = "fib_map_bound_exit_execution_handoff_adapter_v1"


class FibMapBoundExitPlanAdapterError(ValueError):
    """Fail-closed adapter rejection with a stable machine reason."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reject(condition: bool, reason_code: str) -> None:
    if condition:
        raise FibMapBoundExitPlanAdapterError(reason_code)


def _decimal_text(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if "." not in normalized:
        return normalized
    normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _validate_plan_structure(plan: FibMapBoundExitPlanV1) -> None:
    """Fail closed on any malformed or ambiguous FibMapBoundExitPlanV1.

    This validates internal consistency only. It never re-derives or
    re-approves anything; a structurally valid plan is passed through
    unchanged.
    """
    _reject(plan.trading_account_id <= 0, "PLAN_IDENTITY_NOT_POSITIVE")
    _reject(
        not all(
            _nonempty(value)
            for value in (
                plan.venue, plan.market, plan.strategy_bucket_id, plan.strategy_id,
                plan.strategy_version, plan.trade_id, plan.binding_id, plan.decision_id,
                plan.decision_state, plan.planner_version,
            )
        ),
        "PLAN_IDENTITY_FIELD_EMPTY",
    )
    _reject(plan.side != SIDE_SELL, "PLAN_SIDE_NOT_SELL")
    _reject(plan.final_quantity_base <= 0, "PLAN_FINAL_QUANTITY_NOT_POSITIVE")
    _reject(not isinstance(plan.legs, tuple) or not plan.legs, "PLAN_LEGS_EMPTY")
    _reject(len(plan.legs) != 1, "PLAN_LEGS_NOT_SINGLE_LEG")

    indices = tuple(leg.leg_index for leg in plan.legs)
    expected_indices = tuple(range(1, len(plan.legs) + 1))
    _reject(indices != expected_indices, "PLAN_LEG_INDICES_NOT_STRICTLY_ORDERED")

    leg_total = Decimal("0")
    for leg in plan.legs:
        _reject(leg.side != plan.side, "PLAN_LEG_SIDE_MISMATCH")
        _reject(leg.limit_price <= 0, "PLAN_LEG_PRICE_NOT_POSITIVE")
        _reject(leg.quantity_base <= 0, "PLAN_LEG_QUANTITY_NOT_POSITIVE")
        _reject(leg.quote_notional <= 0, "PLAN_LEG_NOTIONAL_NOT_POSITIVE")
        leg_total += leg.quantity_base
    _reject(leg_total != plan.final_quantity_base, "PLAN_LEG_QUANTITY_SUM_MISMATCH")


def _leg_reference_payload(leg: FibMapBoundExitPlanLegV1) -> dict[str, object]:
    return {
        "leg_index": leg.leg_index,
        "side": leg.side,
        "limit_price": _decimal_text(leg.limit_price),
        "quantity_base": _decimal_text(leg.quantity_base),
        "quote_notional": _decimal_text(leg.quote_notional),
        "post_only": leg.post_only,
        "time_in_force": leg.time_in_force,
    }


def _plan_identity_payload(plan: FibMapBoundExitPlanV1) -> dict[str, object]:
    """Canonical logical-identity payload used to derive plan_reference_id.

    Deliberately excludes ``planning_ts_utc`` (wall-clock, not part of
    logical intent) so retries and restarts of the same logical evaluation
    produce the same identity. Every field that identifies exactly which
    strategy/trade lineage and which exact decision this plan realizes --
    including ``binding_id``, ``decision_id``, ``decision_state``, and exact
    leg price/quantity -- is included so two logically distinct decisions
    never collide, even if their resulting SELL leg is numerically
    identical.
    """
    return {
        "contract_version": _PLAN_REFERENCE_ID_CONTRACT_VERSION,
        "trading_account_id": plan.trading_account_id,
        "venue": plan.venue,
        "market": plan.market,
        "strategy_bucket_id": plan.strategy_bucket_id,
        "strategy_id": plan.strategy_id,
        "strategy_version": plan.strategy_version,
        "trade_id": plan.trade_id,
        "binding_id": plan.binding_id,
        "decision_id": plan.decision_id,
        "decision_state": plan.decision_state,
        "side": plan.side,
        "final_quantity_base": _decimal_text(plan.final_quantity_base),
        "planner_version": plan.planner_version,
        "legs": [_leg_reference_payload(leg) for leg in plan.legs],
    }


def derive_fib_map_bound_exit_plan_reference_id_v1(plan: FibMapBoundExitPlanV1) -> str:
    """Deterministic, retry-stable, evidence-traceable plan_reference_id.

    Same logical plan (including on retry, process restart, or duplicate
    evaluation of the exact same decision) always derives the same id. Any
    change to lineage identity, binding, decision identity/state, or leg
    price/quantity changes the id.
    """
    payload = _plan_identity_payload(plan)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return (
        f"fib_map_bound_exit_v1:{plan.trading_account_id}:{plan.trade_id}:"
        f"{plan.decision_id}:{content_hash}"
    )


def adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1(
    plan: FibMapBoundExitPlanV1,
) -> ApprovedExecutionPlanV1:
    """Lossless, pure translation of an approved FibMapBoundExitPlanV1.

    Fails closed (FibMapBoundExitPlanAdapterError) on any structurally
    malformed or ambiguous input. Never recomputes quantity, price, or
    quote notional; never re-rounds; never reorders or splits legs; never
    rewrites side; never mutates the input plan.
    """
    _validate_plan_structure(plan)
    plan_reference_id = derive_fib_map_bound_exit_plan_reference_id_v1(plan)
    legs = tuple(
        ExecutionPlanLegV1(
            leg_index=leg.leg_index,
            side=leg.side,
            price=leg.limit_price,
            quantity=leg.quantity_base,
        )
        for leg in plan.legs
    )
    return ApprovedExecutionPlanV1(
        plan_source=PLAN_SOURCE_FIB_MAP_BOUND_EXIT_V1,
        plan_reference_id=plan_reference_id,
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        side=plan.side,
        legs=legs,
    )
