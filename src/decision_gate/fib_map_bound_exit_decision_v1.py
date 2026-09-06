"""Issue #753 Phase B2: pure typed map-bound exit decision layer.

Combines the immutable Fib-map trade binding (#766,
``src/decision_gate/fib_map_bound_trade_v1.py``) with the exact
strategy-owned remaining quantity (#752,
``src/decision_gate/strategy_owned_inventory_v1.py``) and current market
price evidence to produce a deterministic, ordered exit decision.

This module is a pure decision contract only:

- it does not create orders, call the broker, or grant LIVE authority
- it does not mutate account permission or execution state
- ``execution_planner`` remains the sole owner of execution intent/plans
- ``executor`` remains the sole owner of order handling

Target-ladder progression (which target indices have already been
realized) is caller-owned evidence, exactly like
``account_protection_evaluation`` in ``automatic_exit_gate_v1``: this
module never infers ownership or fill history itself, it only validates
the binding it is given against the shape it requires.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from src.decision_gate.fib_map_bound_trade_v1 import (
    FibMapBoundTradeError,
    FibMapBoundTradeV1,
    validate_fib_map_bound_trade_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryPositionV1

STATE_NO_ACTION: Final[str] = "NO_ACTION"
STATE_PARTIAL_PROFIT_TARGET: Final[str] = "PARTIAL_PROFIT_TARGET"
STATE_PROTECTIVE_EXIT: Final[str] = "PROTECTIVE_EXIT"
STATE_FAIL_CLOSED: Final[str] = "FAIL_CLOSED"

REASON_OK: Final[str] = "OK"
REASON_NO_REMAINING_QUANTITY: Final[str] = "NO_REMAINING_STRATEGY_OWNED_QUANTITY"
REASON_NO_TARGET_CROSSED: Final[str] = "NO_TARGET_LEVEL_CROSSED"
REASON_ALL_TARGETS_CONSUMED: Final[str] = "ALL_TARGET_LEVELS_CONSUMED"
REASON_MISSING_BINDING: Final[str] = "MISSING_FIB_MAP_BOUND_TRADE"
REASON_INVALID_BINDING: Final[str] = "INVALID_FIB_MAP_BOUND_TRADE"
REASON_INVALID_TARGET_LADDER_ORDER: Final[str] = "NON_MONOTONIC_TARGET_LADDER"
REASON_UNSUPPORTED_TARGET_LADDER_SEMANTICS: Final[str] = "UNSUPPORTED_TARGET_LADDER_SEMANTICS_VERSION"
REASON_OWNERSHIP_MISMATCH: Final[str] = "STRATEGY_OWNERSHIP_LINEAGE_MISMATCH"
REASON_IMPOSSIBLE_INVENTORY_STATE: Final[str] = "IMPOSSIBLE_STRATEGY_INVENTORY_STATE"
REASON_INVALID_PRICE_EVIDENCE: Final[str] = "INVALID_MARKET_PRICE_EVIDENCE"
REASON_PRICE_EVIDENCE_STALE: Final[str] = "MARKET_PRICE_EVIDENCE_STALE"
REASON_INVALID_PROGRESSION: Final[str] = "INVALID_TARGET_PROGRESSION_STATE"
REASON_INVALID_EVALUATION_TIMESTAMP: Final[str] = "INVALID_EVALUATION_TIMESTAMP"

# Canonical target-ladder semantics accepted by this decision layer. A
# binding produced under an unrecognized ladder semantics version fails
# closed rather than being interpreted with assumed ordering/crossing
# rules (see fib_map_bound_trade_v1.target_ladder_semantics_version).
SUPPORTED_TARGET_LADDER_SEMANTICS_VERSIONS: Final[frozenset[str]] = frozenset({"FIB_MAP_BOUND_V1"})

DEFAULT_MAX_PRICE_AGE_SECONDS: Final[int] = 15 * 60


class FibMapBoundExitDecisionError(ValueError):
    pass


@dataclass(frozen=True)
class FibMapBoundExitMarketEvidenceV1:
    current_price: Decimal
    price_observed_ts_utc: datetime


@dataclass(frozen=True)
class FibMapBoundExitProgressionV1:
    """Caller-owned record of which ladder rungs were already realized.

    This module never infers progression from broker fills or wallet
    state; the caller (owner of realized-fill history) supplies exactly
    which target indices of ``binding.target_levels`` have already been
    consumed by a prior exit fill for this exact bound trade lineage.
    """

    consumed_target_indices: frozenset[int]


@dataclass(frozen=True)
class FibMapBoundExitDecisionV1:
    decision_id: str
    state: str
    reason_code: str
    binding_id: str
    trade_id: str
    target_index: int | None
    target_price: Decimal | None
    decision_quantity_base: Decimal | None
    remaining_owned_after_base: Decimal | None


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _fail(binding_id: str, trade_id: str, reason: str) -> FibMapBoundExitDecisionV1:
    return FibMapBoundExitDecisionV1(
        decision_id=f"{binding_id or 'UNBOUND'}:FAIL_CLOSED:{reason}",
        state=STATE_FAIL_CLOSED,
        reason_code=reason,
        binding_id=binding_id,
        trade_id=trade_id,
        target_index=None,
        target_price=None,
        decision_quantity_base=None,
        remaining_owned_after_base=None,
    )


def evaluate_fib_map_bound_exit_decision_v1(
    *,
    binding: FibMapBoundTradeV1 | None,
    owned_position: StrategyOwnedInventoryPositionV1,
    progression: FibMapBoundExitProgressionV1,
    market_evidence: FibMapBoundExitMarketEvidenceV1,
    evaluation_ts_utc: datetime,
    max_price_age_seconds: int = DEFAULT_MAX_PRICE_AGE_SECONDS,
) -> FibMapBoundExitDecisionV1:
    """Evaluate one exact bound-trade lineage into a typed exit decision.

    Deterministic and idempotent at decision-identity level: identical
    inputs always produce a decision with the same ``decision_id`` and
    field values. Invalidation always takes precedence over any
    unfilled/future profit target. A later or different canonical Fib
    map never influences this call because it never fetches a binding
    itself -- it only evaluates the exact, already-bound
    ``FibMapBoundTradeV1`` instance the caller supplies.
    """
    if binding is None:
        return _fail("", "", REASON_MISSING_BINDING)
    if not isinstance(binding, FibMapBoundTradeV1):
        return _fail("", "", REASON_INVALID_BINDING)

    try:
        validate_fib_map_bound_trade_v1(binding)
    except FibMapBoundTradeError:
        return _fail(binding.binding_id, binding.trade_id, REASON_INVALID_BINDING)

    if binding.target_ladder_semantics_version not in SUPPORTED_TARGET_LADDER_SEMANTICS_VERSIONS:
        return _fail(binding.binding_id, binding.trade_id, REASON_UNSUPPORTED_TARGET_LADDER_SEMANTICS)

    levels = binding.target_levels
    if any(levels[i] >= levels[i + 1] for i in range(len(levels) - 1)):
        return _fail(binding.binding_id, binding.trade_id, REASON_INVALID_TARGET_LADDER_ORDER)

    if not isinstance(progression, FibMapBoundExitProgressionV1) or any(
        not isinstance(index, int) or index < 0 or index >= len(levels)
        for index in progression.consumed_target_indices
    ):
        return _fail(binding.binding_id, binding.trade_id, REASON_INVALID_PROGRESSION)

    if not _aware(evaluation_ts_utc):
        return _fail(binding.binding_id, binding.trade_id, REASON_INVALID_EVALUATION_TIMESTAMP)

    if (
        not isinstance(market_evidence, FibMapBoundExitMarketEvidenceV1)
        or not isinstance(market_evidence.current_price, Decimal)
        or not market_evidence.current_price.is_finite()
        or market_evidence.current_price <= 0
        or not _aware(market_evidence.price_observed_ts_utc)
    ):
        return _fail(binding.binding_id, binding.trade_id, REASON_INVALID_PRICE_EVIDENCE)

    age = evaluation_ts_utc - market_evidence.price_observed_ts_utc
    if age < timedelta(0) or age > timedelta(seconds=max_price_age_seconds):
        return _fail(binding.binding_id, binding.trade_id, REASON_PRICE_EVIDENCE_STALE)

    if (
        owned_position.trading_account_id != binding.trading_account_id
        or owned_position.venue != binding.venue
        or owned_position.market != binding.market
        or owned_position.strategy_bucket_id != binding.strategy_bucket_id
        or owned_position.strategy_id != binding.strategy_id
        or owned_position.strategy_version != binding.strategy_version
        or owned_position.trade_id != binding.trade_id
    ):
        return _fail(binding.binding_id, binding.trade_id, REASON_OWNERSHIP_MISMATCH)

    owned = owned_position.owned_base_quantity
    bought = owned_position.bought_base_quantity
    if (
        not isinstance(owned, Decimal) or not owned.is_finite() or owned < 0
        or not isinstance(bought, Decimal) or not bought.is_finite() or bought <= 0
        or owned > bought
    ):
        return _fail(binding.binding_id, binding.trade_id, REASON_IMPOSSIBLE_INVENTORY_STATE)

    if owned == 0:
        return FibMapBoundExitDecisionV1(
            decision_id=f"{binding.binding_id}:NO_ACTION:ZERO_REMAINING",
            state=STATE_NO_ACTION,
            reason_code=REASON_NO_REMAINING_QUANTITY,
            binding_id=binding.binding_id,
            trade_id=binding.trade_id,
            target_index=None,
            target_price=None,
            decision_quantity_base=None,
            remaining_owned_after_base=Decimal("0"),
        )

    price = market_evidence.current_price

    # Invalidation always takes precedence over any future/unfilled
    # profit target, regardless of target-ladder progression.
    if price <= binding.invalidation_price:
        return FibMapBoundExitDecisionV1(
            decision_id=f"{binding.binding_id}:PROTECTIVE_EXIT",
            state=STATE_PROTECTIVE_EXIT,
            reason_code=REASON_OK,
            binding_id=binding.binding_id,
            trade_id=binding.trade_id,
            target_index=None,
            target_price=binding.invalidation_price,
            decision_quantity_base=owned,
            remaining_owned_after_base=Decimal("0"),
        )

    consumed = progression.consumed_target_indices
    unconsumed_indices = sorted(index for index in range(len(levels)) if index not in consumed)
    if not unconsumed_indices:
        return FibMapBoundExitDecisionV1(
            decision_id=f"{binding.binding_id}:NO_ACTION:ALL_TARGETS_CONSUMED",
            state=STATE_NO_ACTION,
            reason_code=REASON_ALL_TARGETS_CONSUMED,
            binding_id=binding.binding_id,
            trade_id=binding.trade_id,
            target_index=None,
            target_price=None,
            decision_quantity_base=None,
            remaining_owned_after_base=owned,
        )

    next_index = unconsumed_indices[0]
    target_price = levels[next_index]
    if price < target_price:
        return FibMapBoundExitDecisionV1(
            decision_id=f"{binding.binding_id}:NO_ACTION:TARGET_{next_index}",
            state=STATE_NO_ACTION,
            reason_code=REASON_NO_TARGET_CROSSED,
            binding_id=binding.binding_id,
            trade_id=binding.trade_id,
            target_index=None,
            target_price=None,
            decision_quantity_base=None,
            remaining_owned_after_base=owned,
        )

    rung_quantity = bought / Decimal(len(levels))
    decision_quantity = min(rung_quantity, owned)
    return FibMapBoundExitDecisionV1(
        decision_id=f"{binding.binding_id}:PARTIAL_PROFIT_TARGET:{next_index}",
        state=STATE_PARTIAL_PROFIT_TARGET,
        reason_code=REASON_OK,
        binding_id=binding.binding_id,
        trade_id=binding.trade_id,
        target_index=next_index,
        target_price=target_price,
        decision_quantity_base=decision_quantity,
        remaining_owned_after_base=owned - decision_quantity,
    )
