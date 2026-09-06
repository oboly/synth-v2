"""Issue #752: strategy-owned inventory attribution and replay projection.

This module owns logical strategy quantity attribution only. Broker wallet
balances remain physical reconciliation facts and never imply ownership.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable


class StrategyOwnedInventoryError(ValueError):
    """Inventory attribution is malformed, ambiguous, or would over-reduce."""


@dataclass(frozen=True)
class StrategyOwnedInventoryEventV1:
    event_id: str
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    source_execution_plan_id: str
    source_fill_id: str
    side: str
    filled_base_quantity: Decimal
    fill_notional_eur: Decimal | None
    occurred_ts_utc: datetime


@dataclass(frozen=True)
class StrategyOwnedInventoryPositionV1:
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    owned_base_quantity: Decimal
    bought_base_quantity: Decimal
    sold_base_quantity: Decimal
    cost_notional_eur: Decimal | None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _validate_event(event: StrategyOwnedInventoryEventV1) -> None:
    if event.trading_account_id <= 0:
        raise StrategyOwnedInventoryError("INVALID_TRADING_ACCOUNT_ID")
    for value in (event.event_id, event.venue, event.market, event.strategy_bucket_id,
                  event.strategy_id, event.strategy_version, event.trade_id,
                  event.source_execution_plan_id, event.source_fill_id):
        if not _nonempty(value):
            raise StrategyOwnedInventoryError("INVALID_STRATEGY_INVENTORY_IDENTITY")
    if event.side not in {"BUY", "SELL"}:
        raise StrategyOwnedInventoryError("INVALID_STRATEGY_INVENTORY_SIDE")
    if (
        not isinstance(event.filled_base_quantity, Decimal)
        or not event.filled_base_quantity.is_finite()
        or event.filled_base_quantity <= 0
    ):
        raise StrategyOwnedInventoryError("INVALID_STRATEGY_INVENTORY_QUANTITY")
    if event.fill_notional_eur is not None and (
        not isinstance(event.fill_notional_eur, Decimal)
        or not event.fill_notional_eur.is_finite()
        or event.fill_notional_eur < 0
    ):
        raise StrategyOwnedInventoryError("INVALID_STRATEGY_INVENTORY_NOTIONAL")
    if not _aware(event.occurred_ts_utc):
        raise StrategyOwnedInventoryError("INVALID_STRATEGY_INVENTORY_TIMESTAMP")


def project_strategy_owned_inventory_v1(
    events: Iterable[StrategyOwnedInventoryEventV1],
) -> tuple[StrategyOwnedInventoryPositionV1, ...]:
    """Replay immutable fill-attribution events into owned quantities.

    Duplicate ``source_fill_id`` or ``event_id`` facts fail closed. SELL facts
    may only reduce the exact strategy/trade lineage they name and may never
    drive that lineage negative.
    """
    seen_event_ids: set[str] = set()
    seen_fill_ids: set[tuple[int, str, str]] = set()
    state: dict[tuple[int, str, str, str, str, str, str], dict[str, Decimal | None]] = {}
    for event in sorted(events, key=lambda item: (item.occurred_ts_utc, item.event_id)):
        _validate_event(event)
        if event.event_id in seen_event_ids:
            raise StrategyOwnedInventoryError("DUPLICATE_STRATEGY_INVENTORY_EVENT_ID")
        fill_key = (event.trading_account_id, event.venue, event.source_fill_id)
        if fill_key in seen_fill_ids:
            raise StrategyOwnedInventoryError("DUPLICATE_STRATEGY_INVENTORY_SOURCE_FILL")
        seen_event_ids.add(event.event_id)
        seen_fill_ids.add(fill_key)

        key = (
            event.trading_account_id, event.venue, event.market,
            event.strategy_bucket_id, event.strategy_id,
            event.strategy_version, event.trade_id,
        )
        row = state.setdefault(
            key,
            {"owned": Decimal("0"), "bought": Decimal("0"),
             "sold": Decimal("0"), "cost": Decimal("0")},
        )
        if event.side == "BUY":
            row["owned"] = row["owned"] + event.filled_base_quantity  # type: ignore[operator]
            row["bought"] = row["bought"] + event.filled_base_quantity  # type: ignore[operator]
            if event.fill_notional_eur is not None:
                row["cost"] = row["cost"] + event.fill_notional_eur  # type: ignore[operator]
        else:
            if event.filled_base_quantity > row["owned"]:  # type: ignore[operator]
                raise StrategyOwnedInventoryError("STRATEGY_INVENTORY_OVER_REDUCTION")
            row["owned"] = row["owned"] - event.filled_base_quantity  # type: ignore[operator]
            row["sold"] = row["sold"] + event.filled_base_quantity  # type: ignore[operator]

    positions: list[StrategyOwnedInventoryPositionV1] = []
    for key, row in sorted(state.items()):
        positions.append(
            StrategyOwnedInventoryPositionV1(
                trading_account_id=key[0], venue=key[1], market=key[2],
                strategy_bucket_id=key[3], strategy_id=key[4],
                strategy_version=key[5], trade_id=key[6],
                owned_base_quantity=row["owned"],  # type: ignore[arg-type]
                bought_base_quantity=row["bought"],  # type: ignore[arg-type]
                sold_base_quantity=row["sold"],  # type: ignore[arg-type]
                cost_notional_eur=row["cost"],  # type: ignore[arg-type]
            )
        )
    return tuple(positions)
