"""Issue #752 B3: fail-closed authorization for strategy-owned reductions."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryPositionV1


class StrategyOwnedReductionAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class StrategyOwnedReductionRequestV1:
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    requested_base_quantity: Decimal


@dataclass(frozen=True)
class StrategyOwnedReductionAuthorizationV1:
    requested_base_quantity: Decimal
    owned_base_quantity: Decimal
    remaining_after_reduction_base_quantity: Decimal


def authorize_strategy_owned_reduction_v1(
    positions: Iterable[StrategyOwnedInventoryPositionV1],
    *,
    request: StrategyOwnedReductionRequestV1,
) -> StrategyOwnedReductionAuthorizationV1:
    qty = request.requested_base_quantity
    if not isinstance(qty, Decimal) or not qty.is_finite() or qty <= 0:
        raise StrategyOwnedReductionAuthorizationError("INVALID_REDUCTION_QUANTITY")
    matches = tuple(
        position for position in positions
        if position.trading_account_id == request.trading_account_id
        and position.venue == request.venue
        and position.market == request.market
        and position.strategy_bucket_id == request.strategy_bucket_id
        and position.strategy_id == request.strategy_id
        and position.strategy_version == request.strategy_version
        and position.trade_id == request.trade_id
    )
    if len(matches) != 1:
        raise StrategyOwnedReductionAuthorizationError("STRATEGY_OWNED_INVENTORY_UNRESOLVED")
    owned = matches[0].owned_base_quantity
    if qty > owned:
        raise StrategyOwnedReductionAuthorizationError("REDUCTION_EXCEEDS_STRATEGY_OWNED_QUANTITY")
    return StrategyOwnedReductionAuthorizationV1(
        requested_base_quantity=qty,
        owned_base_quantity=owned,
        remaining_after_reduction_base_quantity=owned - qty,
    )
