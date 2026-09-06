"""Issue #752 B3: reconcile cumulative broker fill evidence to ownership deltas.

Broker/order snapshots are cumulative evidence only. This module never infers
strategy ownership from wallet balances; callers must provide the exact lineage
carried by the execution path. Facts are append-only and replay-safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Iterable

from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1


class StrategyOwnedFillReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class StrategyOwnedFillLineageV1:
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    source_execution_plan_id: str
    source_order_id: str
    side: str


@dataclass(frozen=True)
class BrokerCumulativeFillEvidenceV1:
    source_snapshot_id: str
    cumulative_filled_base_quantity: Decimal
    observed_ts_utc: datetime


@dataclass(frozen=True)
class StrategyOwnedFillReconciliationFactV1:
    fact_id: str
    source_snapshot_id: str
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    source_execution_plan_id: str
    source_order_id: str
    side: str
    cumulative_filled_base_quantity: Decimal
    attributed_delta_base_quantity: Decimal
    emitted_event_id: str | None
    observed_ts_utc: datetime


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{sha256(payload.encode('utf-8')).hexdigest()}"


def _validate(lineage: StrategyOwnedFillLineageV1, evidence: BrokerCumulativeFillEvidenceV1) -> None:
    if lineage.trading_account_id <= 0:
        raise StrategyOwnedFillReconciliationError("INVALID_TRADING_ACCOUNT_ID")
    for value in (
        lineage.venue, lineage.market, lineage.strategy_bucket_id, lineage.strategy_id,
        lineage.strategy_version, lineage.trade_id, lineage.source_execution_plan_id,
        lineage.source_order_id, evidence.source_snapshot_id,
    ):
        if not _nonempty(value):
            raise StrategyOwnedFillReconciliationError("INVALID_FILL_RECONCILIATION_IDENTITY")
    if lineage.side not in {"BUY", "SELL"}:
        raise StrategyOwnedFillReconciliationError("INVALID_FILL_RECONCILIATION_SIDE")
    qty = evidence.cumulative_filled_base_quantity
    if not isinstance(qty, Decimal) or not qty.is_finite() or qty < 0:
        raise StrategyOwnedFillReconciliationError("INVALID_CUMULATIVE_FILLED_QUANTITY")
    if not _aware(evidence.observed_ts_utc):
        raise StrategyOwnedFillReconciliationError("INVALID_FILL_RECONCILIATION_TIMESTAMP")


def _same_lineage(fact: StrategyOwnedFillReconciliationFactV1, lineage: StrategyOwnedFillLineageV1) -> bool:
    return (
        fact.trading_account_id == lineage.trading_account_id
        and fact.venue == lineage.venue
        and fact.market == lineage.market
        and fact.strategy_bucket_id == lineage.strategy_bucket_id
        and fact.strategy_id == lineage.strategy_id
        and fact.strategy_version == lineage.strategy_version
        and fact.trade_id == lineage.trade_id
        and fact.source_execution_plan_id == lineage.source_execution_plan_id
        and fact.source_order_id == lineage.source_order_id
        and fact.side == lineage.side
    )


def reconcile_cumulative_fill_v1(
    prior_facts: Iterable[StrategyOwnedFillReconciliationFactV1],
    *,
    lineage: StrategyOwnedFillLineageV1,
    evidence: BrokerCumulativeFillEvidenceV1,
) -> tuple[StrategyOwnedFillReconciliationFactV1, StrategyOwnedInventoryEventV1 | None]:
    """Return one append-only reconciliation fact and optional ownership delta.

    Repeating the same snapshot is idempotent. A later snapshot with unchanged
    cumulative fill emits no inventory event. Cumulative fill moving backwards,
    or one broker order being rebound to a different strategy lineage, fails closed.
    """
    _validate(lineage, evidence)
    facts = tuple(prior_facts)
    matching_order = tuple(
        fact for fact in facts
        if fact.trading_account_id == lineage.trading_account_id
        and fact.venue == lineage.venue
        and fact.source_order_id == lineage.source_order_id
    )
    for fact in matching_order:
        if not _same_lineage(fact, lineage):
            raise StrategyOwnedFillReconciliationError("SOURCE_ORDER_LINEAGE_CONFLICT")
        if fact.source_snapshot_id == evidence.source_snapshot_id:
            if fact.cumulative_filled_base_quantity != evidence.cumulative_filled_base_quantity:
                raise StrategyOwnedFillReconciliationError("SOURCE_SNAPSHOT_RESTATEMENT_CONFLICT")
            return fact, None

    previous = max(
        (fact.cumulative_filled_base_quantity for fact in matching_order),
        default=Decimal("0"),
    )
    cumulative = evidence.cumulative_filled_base_quantity
    if cumulative < previous:
        raise StrategyOwnedFillReconciliationError("CUMULATIVE_FILL_MOVED_BACKWARDS")
    delta = cumulative - previous
    event_id = None if delta == 0 else _stable_id(
        "inventory_event", lineage.trading_account_id, lineage.venue,
        lineage.source_order_id, evidence.source_snapshot_id, cumulative,
    )
    fact = StrategyOwnedFillReconciliationFactV1(
        fact_id=_stable_id("fill_reconciliation", lineage.trading_account_id, lineage.venue,
                           lineage.source_order_id, evidence.source_snapshot_id),
        source_snapshot_id=evidence.source_snapshot_id,
        trading_account_id=lineage.trading_account_id, venue=lineage.venue, market=lineage.market,
        strategy_bucket_id=lineage.strategy_bucket_id, strategy_id=lineage.strategy_id,
        strategy_version=lineage.strategy_version, trade_id=lineage.trade_id,
        source_execution_plan_id=lineage.source_execution_plan_id,
        source_order_id=lineage.source_order_id, side=lineage.side,
        cumulative_filled_base_quantity=cumulative,
        attributed_delta_base_quantity=delta, emitted_event_id=event_id,
        observed_ts_utc=evidence.observed_ts_utc,
    )
    if delta == 0:
        return fact, None
    event = StrategyOwnedInventoryEventV1(
        event_id=event_id or "", trading_account_id=lineage.trading_account_id,
        venue=lineage.venue, market=lineage.market,
        strategy_bucket_id=lineage.strategy_bucket_id, strategy_id=lineage.strategy_id,
        strategy_version=lineage.strategy_version, trade_id=lineage.trade_id,
        source_execution_plan_id=lineage.source_execution_plan_id,
        source_fill_id=_stable_id("broker_fill", lineage.trading_account_id, lineage.venue,
                                  lineage.source_order_id, evidence.source_snapshot_id),
        side=lineage.side, filled_base_quantity=delta, fill_notional_eur=None,
        occurred_ts_utc=evidence.observed_ts_utc,
    )
    return fact, event
