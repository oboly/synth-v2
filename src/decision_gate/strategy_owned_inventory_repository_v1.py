"""Persistence boundary for #752 strategy-owned inventory events."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1


class StrategyOwnedInventoryRepositoryError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _row_to_event(row: dict[str, Any]) -> StrategyOwnedInventoryEventV1:
    try:
        return StrategyOwnedInventoryEventV1(
            event_id=str(row["event_id"]), trading_account_id=int(row["trading_account_id"]),
            venue=str(row["venue"]), market=str(row["market"]),
            strategy_bucket_id=str(row["strategy_bucket_id"]), strategy_id=str(row["strategy_id"]),
            strategy_version=str(row["strategy_version"]), trade_id=str(row["trade_id"]),
            source_execution_plan_id=str(row["source_execution_plan_id"]), source_fill_id=str(row["source_fill_id"]),
            side=str(row["side"]), filled_base_quantity=Decimal(str(row["filled_base_quantity"])),
            fill_notional_eur=(Decimal(str(row["fill_notional_eur"])) if row["fill_notional_eur"] is not None else None),
            occurred_ts_utc=_aware(row["occurred_ts_utc"]),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise StrategyOwnedInventoryRepositoryError("INVALID_PERSISTED_STRATEGY_INVENTORY_EVENT") from exc


def append_strategy_owned_inventory_event_v1(conn: Any, *, event: StrategyOwnedInventoryEventV1) -> None:
    sql = """
    INSERT INTO strategy_owned_inventory_event_v1 (
        event_id, trading_account_id, venue, market, strategy_bucket_id,
        strategy_id, strategy_version, trade_id, source_execution_plan_id,
        source_fill_id, side, filled_base_quantity, fill_notional_eur, occurred_ts_utc
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    params = (
        event.event_id, event.trading_account_id, event.venue, event.market,
        event.strategy_bucket_id, event.strategy_id, event.strategy_version,
        event.trade_id, event.source_execution_plan_id, event.source_fill_id,
        event.side, event.filled_base_quantity, event.fill_notional_eur, event.occurred_ts_utc,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)


def load_strategy_owned_inventory_events_v1(
    conn: Any, *, trading_account_id: int,
) -> tuple[StrategyOwnedInventoryEventV1, ...]:
    if trading_account_id <= 0:
        raise StrategyOwnedInventoryRepositoryError("INVALID_TRADING_ACCOUNT_ID")
    sql = """
    SELECT event_id, trading_account_id, venue, market, strategy_bucket_id,
           strategy_id, strategy_version, trade_id, source_execution_plan_id,
           source_fill_id, side, filled_base_quantity, fill_notional_eur, occurred_ts_utc
    FROM strategy_owned_inventory_event_v1
    WHERE trading_account_id = %s
    ORDER BY occurred_ts_utc, strategy_owned_inventory_event_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_event(row) for row in rows)
