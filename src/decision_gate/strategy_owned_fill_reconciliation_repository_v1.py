"""Persistence boundary for #752 B3 cumulative fill reconciliation facts."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.decision_gate.strategy_owned_fill_reconciliation_v1 import StrategyOwnedFillReconciliationFactV1


class StrategyOwnedFillReconciliationRepositoryError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _row_to_fact(row: dict[str, Any]) -> StrategyOwnedFillReconciliationFactV1:
    try:
        return StrategyOwnedFillReconciliationFactV1(
            fact_id=str(row["fact_id"]), source_snapshot_id=str(row["source_snapshot_id"]),
            trading_account_id=int(row["trading_account_id"]), venue=str(row["venue"]),
            market=str(row["market"]), strategy_bucket_id=str(row["strategy_bucket_id"]),
            strategy_id=str(row["strategy_id"]), strategy_version=str(row["strategy_version"]),
            trade_id=str(row["trade_id"]), source_execution_plan_id=str(row["source_execution_plan_id"]),
            source_order_id=str(row["source_order_id"]), side=str(row["side"]),
            cumulative_filled_base_quantity=Decimal(str(row["cumulative_filled_base_quantity"])),
            attributed_delta_base_quantity=Decimal(str(row["attributed_delta_base_quantity"])),
            emitted_event_id=(str(row["emitted_event_id"]) if row["emitted_event_id"] is not None else None),
            observed_ts_utc=_aware(row["observed_ts_utc"]),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise StrategyOwnedFillReconciliationRepositoryError("INVALID_PERSISTED_FILL_RECONCILIATION_FACT") from exc


def append_strategy_owned_fill_reconciliation_fact_v1(
    conn: Any, *, fact: StrategyOwnedFillReconciliationFactV1,
) -> None:
    sql = """
    INSERT INTO strategy_owned_fill_reconciliation_fact_v1 (
        fact_id, source_snapshot_id, trading_account_id, venue, market,
        strategy_bucket_id, strategy_id, strategy_version, trade_id,
        source_execution_plan_id, source_order_id, side,
        cumulative_filled_base_quantity, attributed_delta_base_quantity,
        emitted_event_id, observed_ts_utc
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    params = (
        fact.fact_id, fact.source_snapshot_id, fact.trading_account_id, fact.venue,
        fact.market, fact.strategy_bucket_id, fact.strategy_id, fact.strategy_version,
        fact.trade_id, fact.source_execution_plan_id, fact.source_order_id, fact.side,
        fact.cumulative_filled_base_quantity, fact.attributed_delta_base_quantity,
        fact.emitted_event_id, fact.observed_ts_utc,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)


def load_strategy_owned_fill_reconciliation_facts_v1(
    conn: Any, *, trading_account_id: int, venue: str, source_order_id: str,
) -> tuple[StrategyOwnedFillReconciliationFactV1, ...]:
    if trading_account_id <= 0 or not venue.strip() or not source_order_id.strip():
        raise StrategyOwnedFillReconciliationRepositoryError("INVALID_FILL_RECONCILIATION_LOOKUP")
    sql = """
    SELECT fact_id, source_snapshot_id, trading_account_id, venue, market,
           strategy_bucket_id, strategy_id, strategy_version, trade_id,
           source_execution_plan_id, source_order_id, side,
           cumulative_filled_base_quantity, attributed_delta_base_quantity,
           emitted_event_id, observed_ts_utc
    FROM strategy_owned_fill_reconciliation_fact_v1
    WHERE trading_account_id = %s AND venue = %s AND source_order_id = %s
    ORDER BY observed_ts_utc, strategy_owned_fill_reconciliation_fact_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, source_order_id))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_fact(row) for row in rows)
