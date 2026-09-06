"""Issue #753 B5.5 review fix (PR #776): durable, replay-safe PAPER
order-placement identity for ``src/executor/paper_order_adapter_v1.py``.

The reviewed defect: ``PaperOrderPlacementAdapterV1.place_order`` could
acknowledge ``ACTIVE`` without recording that acknowledgement anywhere. If
the process crashed after the broker-shaped ACTIVE ack but before
``execution_submission_orchestrator_v1.py`` persisted it onto
``executor_execution_leg``, the leg stayed ``SUBMISSION_UNCERTAIN`` and the
next attempt called ``find_order_by_client_order_id``, which always returned
``None`` -- truthfully reporting "no order was ever recorded", but silently
dead-lettering an order this adapter itself already acknowledged ``ACTIVE``
to ``RECONCILIATION_REQUIRED``.

This module is the minimal durable fix: one executor-owned table,
``executor_paper_order_placement``, that ``place_order`` writes to *before*
returning its acknowledgement, and that ``find_order_by_client_order_id``
reads from afterward. It is not a second leg-state machine and never
produces or transitions ``FILLED``/``PARTIALLY_FILLED``: it only remembers
the ``ACTIVE``/``REJECTED`` placement decision this adapter already made, so
a later retry recovers the exact same decision instead of losing it.

Uniqueness and immutability come from the migration
(``db/migrations/20260906_paper_order_placement_v1.sql``): one row per
``(market, client_order_id)``, no update, no delete. ``client_order_id`` is
already a globally unique, deterministic UUIDv5
(``derive_execution_client_order_id``), so this is not a new identity
scheme -- it durably remembers the one decision this adapter made for an
identity that already existed.

Conflict handling is fail-closed: replaying the exact same
``(market, client_order_id, side, price, quantity)`` returns the
already-recorded acknowledgement (idempotent retry, no new INSERT, no
re-evaluation against possibly different current market evidence). Reusing
``(market, client_order_id)`` for a *different* order identity raises
``PaperOrderPlacementConflictError`` instead of guessing, which the shared
submission orchestrator's existing generic-exception handling already turns
into ``SUBMISSION_UNCERTAIN``/no state change -- never a silent overwrite.

No network, credential, or broker call is made anywhere in this module.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from pymysql.err import IntegrityError

from src.executor import _trusted_clock_v1 as trusted_clock
from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1

_RECORDABLE_ACK_STATES = frozenset({BrokerAckStateV1.ACTIVE, BrokerAckStateV1.REJECTED})


class PaperOrderPlacementConflictError(RuntimeError):
    """``client_order_id`` was reused for a different order identity."""


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)


def _cursor(value: Any) -> Any:
    return value[1] if isinstance(value, tuple) else value


def _row_to_ack(row: Any) -> OrderAckV1:
    return OrderAckV1(
        broker_order_id=(None if row["broker_order_id"] is None else str(row["broker_order_id"])),
        state=BrokerAckStateV1(str(row["state"])),
        broker_raw_status=(None if row["broker_raw_status"] is None else str(row["broker_raw_status"])),
    )


def _same_identity(row: Any, *, side: str, price: Decimal, quantity: Decimal) -> bool:
    return (
        str(row["side"]) == side
        and Decimal(str(row["price"])) == price
        and Decimal(str(row["quantity"])) == quantity
    )


@dataclass
class PaperOrderPlacementRepositoryV1:
    """One row per ``(market, client_order_id)``. Never updated, never
    deleted (enforced by the migration's triggers); ``record_placement`` is
    the only write path and is idempotent for the identical identity."""

    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False)

    def record_placement(
        self,
        *,
        market: str,
        client_order_id: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        ack: OrderAckV1,
    ) -> OrderAckV1:
        if not isinstance(ack, OrderAckV1) or ack.state not in _RECORDABLE_ACK_STATES:
            raise ValueError("PAPER_PLACEMENT_ACK_STATE_NOT_RECORDABLE")
        try:
            with self.cursor_factory(commit=True) as db_obj:
                cursor = _cursor(db_obj)
                cursor.execute(
                    "INSERT INTO executor_paper_order_placement "
                    "(market, client_order_id, side, price, quantity, state, "
                    "broker_order_id, broker_raw_status, created_ts_utc) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        market,
                        client_order_id,
                        side,
                        price,
                        quantity,
                        ack.state.value,
                        ack.broker_order_id,
                        ack.broker_raw_status,
                        trusted_clock.utc_now(),
                    ],
                )
            return ack
        except IntegrityError:
            row = self._find_row(market=market, client_order_id=client_order_id)
            if row is None:
                raise
            if not _same_identity(row, side=side, price=price, quantity=quantity):
                raise PaperOrderPlacementConflictError(
                    "PAPER_ORDER_CLIENT_ORDER_ID_IDENTITY_CONFLICT"
                ) from None
            return _row_to_ack(row)


    def recover_existing_placement(
        self, *, market: str, client_order_id: str, side: str, price: Decimal, quantity: Decimal
    ) -> OrderAckV1 | None:
        row = self._find_row(market=market, client_order_id=client_order_id)
        if row is None:
            return None
        if not _same_identity(row, side=side, price=price, quantity=quantity):
            raise PaperOrderPlacementConflictError(
                "PAPER_ORDER_CLIENT_ORDER_ID_IDENTITY_CONFLICT"
            )
        return _row_to_ack(row)

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAckV1 | None:
        row = self._find_row(market=market, client_order_id=client_order_id)
        return None if row is None else _row_to_ack(row)

    def find_placement_created_ts_utc(
        self, *, market: str, client_order_id: str
    ) -> datetime | None:
        """Issue #753 B8: read-only lookup of this placement's own immutable
        ``created_ts_utc`` -- the authoritative resting-since time reused
        (no new schema) by ``paper_resting_order_reconciliation_v1.py``."""
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                "SELECT created_ts_utc FROM executor_paper_order_placement "
                "WHERE market=%s AND client_order_id=%s",
                [market, client_order_id],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        value = row["created_ts_utc"]
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    def _find_row(self, *, market: str, client_order_id: str) -> Any | None:
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                "SELECT side, price, quantity, state, broker_order_id, broker_raw_status "
                "FROM executor_paper_order_placement "
                "WHERE market=%s AND client_order_id=%s",
                [market, client_order_id],
            )
            return cursor.fetchone()
