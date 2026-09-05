"""Issue #752: DB-local read/append boundary for
``strategy_owned_inventory_ledger_v1``.

No ownership/authority computation lives here -- that is
``strategy_owned_inventory_ledger_v1`` (pure functions over already-loaded
events). This module only loads raw rows and appends new ones. No broker,
executor, planner, or execution import.

The ledger table is append-only and trigger-enforced (no UPDATE, ever), so
idempotent duplicate handling cannot use ``ON DUPLICATE KEY UPDATE`` (that
would fire the table's own BEFORE UPDATE trigger and always fail). Instead,
``record_strategy_owned_fill_event_v1`` attempts a plain INSERT and treats
the DB's own unique-key rejection on ``order_identity`` as the idempotency
signal: a duplicate insert of an identical event is a no-op; a duplicate
insert whose fields disagree with the already-persisted row is a
:class:`StrategyOwnedInventoryLedgerConflictError` (fail closed), never a
silent overwrite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.decision_gate.strategy_owned_inventory_ledger_v1 import (
    StrategyOwnedFillEventV1,
    StrategyOwnershipLineageV1,
    validate_fill_event_v1,
)


class StrategyOwnedInventoryLedgerRepositoryError(RuntimeError):
    """Persisted ledger data is unavailable or malformed."""


class StrategyOwnedInventoryLedgerConflictError(StrategyOwnedInventoryLedgerRepositoryError):
    """A row already exists for this ``order_identity`` with different fields."""


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _row_to_event(row: dict[str, Any]) -> StrategyOwnedFillEventV1:
    try:
        lineage = StrategyOwnershipLineageV1(
            trading_account_id=int(row["trading_account_id"]),
            venue=str(row["venue"]),
            market=str(row["market"]),
            strategy_bucket_id=str(row["strategy_bucket_id"]),
            strategy_id=str(row["strategy_id"]),
            strategy_version=str(row["strategy_version"]),
            setup_id=str(row["setup_id"]),
        )
        return StrategyOwnedFillEventV1(
            lineage=lineage,
            order_identity=str(row["order_identity"]),
            execution_plan_reference_id=str(row["execution_plan_reference_id"]),
            side=str(row["side"]),
            base_quantity=Decimal(str(row["base_quantity"])),
            quote_notional=Decimal(str(row["quote_notional"])),
            occurred_ts_utc=_aware(row["occurred_ts_utc"]),
            source_provenance=str(row["source_provenance"]),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise StrategyOwnedInventoryLedgerRepositoryError("INVALID_PERSISTED_LEDGER_ROW") from exc


def load_strategy_owned_fill_events_v1(
    conn: Any, *, lineage: StrategyOwnershipLineageV1,
) -> tuple[StrategyOwnedFillEventV1, ...]:
    """Load every persisted fill event for exactly one lineage, oldest first."""
    if (
        lineage.trading_account_id <= 0
        or not lineage.venue
        or not lineage.market
        or not lineage.strategy_bucket_id
        or not lineage.strategy_id
        or not lineage.strategy_version
        or not lineage.setup_id
    ):
        raise StrategyOwnedInventoryLedgerRepositoryError("INVALID_LINEAGE")
    sql = """
    SELECT trading_account_id, venue, market, strategy_bucket_id, strategy_id,
           strategy_version, setup_id, execution_plan_reference_id, order_identity,
           side, base_quantity, quote_notional, occurred_ts_utc, source_provenance
    FROM strategy_owned_inventory_ledger_v1
    WHERE trading_account_id = %s AND venue = %s AND market = %s
      AND strategy_bucket_id = %s AND strategy_id = %s AND strategy_version = %s
      AND setup_id = %s
    ORDER BY occurred_ts_utc, strategy_owned_inventory_ledger_id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                lineage.trading_account_id, lineage.venue, lineage.market,
                lineage.strategy_bucket_id, lineage.strategy_id, lineage.strategy_version,
                lineage.setup_id,
            ),
        )
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_event(row) for row in rows)


def load_strategy_owned_fill_events_for_bucket_v1(
    conn: Any, *, trading_account_id: int, strategy_bucket_id: str,
) -> tuple[StrategyOwnedFillEventV1, ...]:
    """Load every persisted fill event for one bucket across all lineages.

    Wider than :func:`load_strategy_owned_fill_events_v1` (one exact
    trade/strategy lineage): this is the bucket-wide scope
    ``strategy_owned_inventory_ledger_v1.compute_bucket_owned_exposure_eur_v1``
    aggregates over, matching the scope a bucket's percentage/absolute
    ceiling is defined over in ``strategy_bucket_capacity_v1``.
    """
    if trading_account_id <= 0 or not strategy_bucket_id:
        raise StrategyOwnedInventoryLedgerRepositoryError("INVALID_BUCKET_LOOKUP")
    sql = """
    SELECT trading_account_id, venue, market, strategy_bucket_id, strategy_id,
           strategy_version, setup_id, execution_plan_reference_id, order_identity,
           side, base_quantity, quote_notional, occurred_ts_utc, source_provenance
    FROM strategy_owned_inventory_ledger_v1
    WHERE trading_account_id = %s AND strategy_bucket_id = %s
    ORDER BY occurred_ts_utc, strategy_owned_inventory_ledger_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, strategy_bucket_id))
        rows = [dict(row) for row in cur.fetchall()]
    return tuple(_row_to_event(row) for row in rows)


def record_strategy_owned_fill_event_v1(conn: Any, *, event: StrategyOwnedFillEventV1) -> bool:
    """Append one fill event; idempotent on duplicate ``order_identity``.

    Returns ``True`` if a new row was inserted, ``False`` if an identical
    row already existed (idempotent no-op). Raises
    :class:`StrategyOwnedInventoryLedgerConflictError` if a row already
    exists for this ``order_identity`` with different fields -- a duplicate
    reconciliation event must never silently overwrite a prior attribution
    fact. Caller owns the DB transaction boundary (commit/rollback).
    """
    validate_fill_event_v1(event)
    insert_sql = """
    INSERT INTO strategy_owned_inventory_ledger_v1 (
        trading_account_id, venue, market, strategy_bucket_id, strategy_id,
        strategy_version, setup_id, execution_plan_reference_id, order_identity,
        side, base_quantity, quote_notional, occurred_ts_utc, source_provenance
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        event.lineage.trading_account_id, event.lineage.venue, event.lineage.market,
        event.lineage.strategy_bucket_id, event.lineage.strategy_id, event.lineage.strategy_version,
        event.lineage.setup_id, event.execution_plan_reference_id, event.order_identity,
        event.side, event.base_quantity, event.quote_notional, event.occurred_ts_utc,
        event.source_provenance,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(insert_sql, params)
        return True
    except Exception as exc:  # noqa: BLE001 -- DB driver-specific IntegrityError types vary
        if not _is_duplicate_key_error(exc):
            raise
        existing = _load_by_order_identity(
            conn,
            trading_account_id=event.lineage.trading_account_id,
            venue=event.lineage.venue,
            market=event.lineage.market,
            order_identity=event.order_identity,
        )
        if existing is None:
            # The unique key rejected the insert but no row is now readable
            # for it -- an inconsistent read (e.g. wrong isolation level) is
            # itself a fail-closed condition, never silently treated as
            # idempotent.
            raise StrategyOwnedInventoryLedgerConflictError(
                "DUPLICATE_KEY_REJECTED_BUT_ROW_UNREADABLE"
            ) from exc
        if existing != event:
            raise StrategyOwnedInventoryLedgerConflictError(
                "CONFLICTING_DUPLICATE_ORDER_IDENTITY"
            ) from exc
        return False


def _is_duplicate_key_error(exc: Exception) -> bool:
    name = type(exc).__name__
    return "IntegrityError" in name or "UniqueViolation" in name


def _load_by_order_identity(
    conn: Any, *, trading_account_id: int, venue: str, market: str, order_identity: str,
) -> StrategyOwnedFillEventV1 | None:
    sql = """
    SELECT trading_account_id, venue, market, strategy_bucket_id, strategy_id,
           strategy_version, setup_id, execution_plan_reference_id, order_identity,
           side, base_quantity, quote_notional, occurred_ts_utc, source_provenance
    FROM strategy_owned_inventory_ledger_v1
    WHERE trading_account_id = %s AND venue = %s AND market = %s AND order_identity = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, market, order_identity))
        rows = [dict(row) for row in cur.fetchall()]
    if not rows:
        return None
    if len(rows) != 1:
        raise StrategyOwnedInventoryLedgerRepositoryError("AMBIGUOUS_ORDER_IDENTITY")
    return _row_to_event(rows[0])
