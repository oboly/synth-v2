"""Issue #753: immutable V1 trade binding to canonical ShortTF Fib map truth."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable


class FibMapBoundTradeError(ValueError):
    pass


@dataclass(frozen=True)
class FibMapBoundTradeV1:
    binding_id: str
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    source_execution_plan_id: str
    source_buy_fill_id: str
    native_map_id: str
    map_cycle_id: str
    map_structure_hash: str
    map_source_name: str
    map_source_version: str
    map_asof_ts_utc: datetime
    map_published_at_utc: datetime
    anchor_start_ts_utc: datetime
    anchor_end_ts_utc: datetime
    anchor_low_price: Decimal
    anchor_high_price: Decimal
    breakout_gate_price: Decimal
    invalidation_price: Decimal
    target_levels: tuple[Decimal, ...]
    target_ladder_semantics_version: str
    bound_ts_utc: datetime


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def validate_fib_map_bound_trade_v1(value: FibMapBoundTradeV1) -> None:
    if value.trading_account_id <= 0:
        raise FibMapBoundTradeError("INVALID_TRADING_ACCOUNT_ID")
    identity = (
        value.binding_id, value.venue, value.market, value.strategy_bucket_id,
        value.strategy_id, value.strategy_version, value.trade_id,
        value.source_execution_plan_id, value.source_buy_fill_id,
        value.native_map_id, value.map_cycle_id, value.map_structure_hash,
        value.map_source_name, value.map_source_version,
        value.target_ladder_semantics_version,
    )
    if any(not _nonempty(item) for item in identity):
        raise FibMapBoundTradeError("INVALID_FIB_MAP_BINDING_IDENTITY")
    timestamps = (
        value.map_asof_ts_utc, value.map_published_at_utc,
        value.anchor_start_ts_utc, value.anchor_end_ts_utc, value.bound_ts_utc,
    )
    if any(not _aware(item) for item in timestamps):
        raise FibMapBoundTradeError("INVALID_FIB_MAP_BINDING_TIMESTAMP")
    if value.anchor_end_ts_utc < value.anchor_start_ts_utc:
        raise FibMapBoundTradeError("INVALID_FIB_MAP_ANCHOR_WINDOW")
    prices = (
        value.anchor_low_price, value.anchor_high_price,
        value.breakout_gate_price, value.invalidation_price,
    )
    if any((not isinstance(item, Decimal) or not item.is_finite() or item <= 0) for item in prices):
        raise FibMapBoundTradeError("INVALID_FIB_MAP_BINDING_PRICE")
    if value.anchor_high_price <= value.anchor_low_price:
        raise FibMapBoundTradeError("INVALID_FIB_MAP_ANCHOR_GEOMETRY")
    if not value.target_levels:
        raise FibMapBoundTradeError("FIB_MAP_TARGETS_REQUIRED")
    if any((not isinstance(item, Decimal) or not item.is_finite() or item <= 0) for item in value.target_levels):
        raise FibMapBoundTradeError("INVALID_FIB_MAP_TARGET_LEVEL")


def assert_fib_map_binding_set_immutable_v1(
    bindings: Iterable[FibMapBoundTradeV1],
) -> tuple[FibMapBoundTradeV1, ...]:
    """Reject conflicting map bindings for one exact strategy/trade lineage."""
    by_lineage: dict[tuple[int, str, str, str, str, str, str], FibMapBoundTradeV1] = {}
    by_binding_id: set[str] = set()
    ordered = tuple(bindings)
    for binding in ordered:
        validate_fib_map_bound_trade_v1(binding)
        if binding.binding_id in by_binding_id:
            raise FibMapBoundTradeError("DUPLICATE_FIB_MAP_BINDING_ID")
        by_binding_id.add(binding.binding_id)
        lineage = (
            binding.trading_account_id, binding.venue, binding.market,
            binding.strategy_bucket_id, binding.strategy_id,
            binding.strategy_version, binding.trade_id,
        )
        prior = by_lineage.get(lineage)
        if prior is not None:
            raise FibMapBoundTradeError("FIB_MAP_BINDING_ALREADY_EXISTS")
        by_lineage[lineage] = binding
    return ordered
