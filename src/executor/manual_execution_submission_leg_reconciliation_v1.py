"""
manual_execution_submission_leg_reconciliation_v1 — read-only evidence
accessor wiring a resolved manual_execution_submission_leg
(broker_order_id/client_order_id) to the existing broker order-snapshot and
SELL reservation reconciliation infrastructure (Issue #369).

Layer: executor. This module makes evidence *available* to the existing
canonical reconciliation path; it deliberately does not build a second
reconciliation stack:

    account_open_order_snapshot        (db/migrations/20260603_account_open_order_snapshot_v1.sql)
        -- already the read-authority table for broker open orders, already
           carries client_order_id; populated by the existing wallet-refresh
           snapshot job (src.account.run_account_wallet_refresh_v1), not by
           this module.
    src.decision_gate.sell_reservation_v1.reconcile_reservation_state
        -- the single permitted reservation-state-transition entrypoint.

A manual SELL ladder's decision_gate reservation
(src.decision_gate.sell_reservation_v1) is one row per approved *request*
(the full approved quantity), not one row per ladder leg — so mapping many
resolved legs onto that single reservation's state machine is a decision
this module intentionally leaves to the caller (an operator/reconciliation
job) rather than guessing: reconcile_reservation_state already fails closed
(AmbiguousBrokerStateError) unless the caller states it matched exactly one
broker row, so this module only ever hands the caller normalized evidence,
never a decision.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class OpenOrderSnapshotMatch:
    snapshot_id: int
    broker_order_id: str
    client_order_id: str | None
    broker_status: str
    filled_quantity: str
    remaining_quantity: str
    snapshot_ts_utc: Any


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def find_open_order_snapshot_matches(
    *,
    trading_account_id: int,
    venue: str,
    broker_order_id: str | None,
    client_order_id: str,
    cursor_factory: Callable[..., Any] = _legacy_db_cursor,
) -> list[OpenOrderSnapshotMatch]:
    """Read-only lookup against the existing account_open_order_snapshot
    read-authority table, matched by broker_order_id (if known) or by the
    leg's deterministic client_order_id. Returns the most recent snapshot
    row per broker_order_id; never writes."""
    with cursor_factory() as db_obj:
        cursor = _unwrap_cursor(db_obj)
        if broker_order_id:
            cursor.execute(
                """
                SELECT snapshot_id, broker_order_id, client_order_id, broker_status,
                       filled_quantity, remaining_quantity, snapshot_ts_utc
                FROM account_open_order_snapshot
                WHERE trading_account_id = %s AND venue = %s
                  AND (broker_order_id = %s OR client_order_id = %s)
                ORDER BY snapshot_ts_utc DESC
                """,
                [trading_account_id, venue, broker_order_id, client_order_id],
            )
        else:
            cursor.execute(
                """
                SELECT snapshot_id, broker_order_id, client_order_id, broker_status,
                       filled_quantity, remaining_quantity, snapshot_ts_utc
                FROM account_open_order_snapshot
                WHERE trading_account_id = %s AND venue = %s AND client_order_id = %s
                ORDER BY snapshot_ts_utc DESC
                """,
                [trading_account_id, venue, client_order_id],
            )
        rows = cursor.fetchall()

    seen_broker_order_ids: set[str] = set()
    matches: list[OpenOrderSnapshotMatch] = []
    for row in rows:
        row_broker_order_id = str(row["broker_order_id"])
        if row_broker_order_id in seen_broker_order_ids:
            continue
        seen_broker_order_ids.add(row_broker_order_id)
        matches.append(
            OpenOrderSnapshotMatch(
                snapshot_id=int(row["snapshot_id"]),
                broker_order_id=row_broker_order_id,
                client_order_id=row.get("client_order_id"),
                broker_status=str(row["broker_status"]),
                filled_quantity=str(row["filled_quantity"]),
                remaining_quantity=str(row["remaining_quantity"]),
                snapshot_ts_utc=row["snapshot_ts_utc"],
            )
        )
    return matches
