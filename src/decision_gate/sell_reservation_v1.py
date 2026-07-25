"""
sell_reservation_v1 — canonical SELL-side base-quantity reservation model.

Layer: decision_gate. Account-aware. This is the single reservation truth
for SELL-side base quantity — see
docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
finding F9. Do not create a parallel reservation path; every SELL-side
reservation for manual execution must be written and read through this
module and the execution_sell_reservation table.

State machine (each quantity reserved once and only once):

    APPROVED_NOT_SUBMITTED
        -> SUBMITTED_AWAITING_RECONCILIATION
        -> OPEN
        -> PARTIALLY_FILLED
        -> {FILLED, CANCELLED, REJECTED, EXPIRED}   (terminal; reservation released)

Only this module's reconcile_reservation_state() may transition a
reservation out of APPROVED_NOT_SUBMITTED, and only according to
_ALLOWED_TRANSITIONS. No other module writes reservation_state.

Idempotency: create_reservation_idempotent() is keyed on a caller-supplied
idempotency_key with a UNIQUE DB constraint; a retried call with the same
key returns the existing row rather than creating a duplicate.

Ambiguous broker state fails closed: reconcile_reservation_state() requires
the caller to state how many broker order-snapshot rows this reservation
was matched against; anything other than exactly 1 raises
AmbiguousBrokerStateError rather than guessing.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Final


STATE_APPROVED_NOT_SUBMITTED: Final[str] = "APPROVED_NOT_SUBMITTED"
STATE_SUBMITTED_AWAITING_RECONCILIATION: Final[str] = "SUBMITTED_AWAITING_RECONCILIATION"
STATE_OPEN: Final[str] = "OPEN"
STATE_PARTIALLY_FILLED: Final[str] = "PARTIALLY_FILLED"
STATE_FILLED: Final[str] = "FILLED"
STATE_CANCELLED: Final[str] = "CANCELLED"
STATE_REJECTED: Final[str] = "REJECTED"
STATE_EXPIRED: Final[str] = "EXPIRED"

NON_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {
        STATE_APPROVED_NOT_SUBMITTED,
        STATE_SUBMITTED_AWAITING_RECONCILIATION,
        STATE_OPEN,
        STATE_PARTIALLY_FILLED,
    }
)

TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {STATE_FILLED, STATE_CANCELLED, STATE_REJECTED, STATE_EXPIRED}
)

ALL_STATES: Final[frozenset[str]] = NON_TERMINAL_STATES | TERMINAL_STATES

# Deterministic allowed transitions, enforced by reconcile_reservation_state.
_ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    STATE_APPROVED_NOT_SUBMITTED: frozenset(
        {STATE_SUBMITTED_AWAITING_RECONCILIATION, STATE_CANCELLED, STATE_EXPIRED}
    ),
    STATE_SUBMITTED_AWAITING_RECONCILIATION: frozenset(
        {STATE_OPEN, STATE_PARTIALLY_FILLED, STATE_FILLED, STATE_CANCELLED, STATE_REJECTED}
    ),
    STATE_OPEN: frozenset({STATE_PARTIALLY_FILLED, STATE_FILLED, STATE_CANCELLED}),
    STATE_PARTIALLY_FILLED: frozenset({STATE_PARTIALLY_FILLED, STATE_FILLED, STATE_CANCELLED}),
}


class AmbiguousBrokerStateError(RuntimeError):
    """A reservation's broker order state could not be confidently resolved
    to exactly one outcome. Callers must fail closed, never guess."""


class InvalidReservationTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class SellReservation:
    reservation_id: int | None
    trading_account_id: int
    venue: str
    asset_id: int
    symbol: str
    idempotency_key: str
    quantity_base: Decimal
    reservation_state: str
    manual_execution_request_id: int | None = None
    execution_plan_id: int | None = None
    leg_number: int | None = None
    broker_order_id: str | None = None
    created_ts_utc: datetime | None = None
    updated_ts_utc: datetime | None = None
    terminal_ts_utc: datetime | None = None
    notes: str | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


def _row_to_reservation(row: Any) -> SellReservation:
    return SellReservation(
        reservation_id=int(row["reservation_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        asset_id=int(row["asset_id"]),
        symbol=str(row["symbol"]),
        idempotency_key=str(row["idempotency_key"]),
        quantity_base=Decimal(str(row["quantity_base"])),
        reservation_state=str(row["reservation_state"]),
        manual_execution_request_id=row.get("manual_execution_request_id"),
        execution_plan_id=row.get("execution_plan_id"),
        leg_number=row.get("leg_number"),
        broker_order_id=row.get("broker_order_id"),
        created_ts_utc=row.get("created_ts_utc"),
        updated_ts_utc=row.get("updated_ts_utc"),
        terminal_ts_utc=row.get("terminal_ts_utc"),
        notes=row.get("notes"),
    )


@dataclass
class SellReservationRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def create_reservation_idempotent(
        self,
        *,
        trading_account_id: int,
        venue: str,
        asset_id: int,
        symbol: str,
        idempotency_key: str,
        quantity_base: Decimal,
        manual_execution_request_id: int | None = None,
        execution_plan_id: int | None = None,
        leg_number: int | None = None,
        notes: str | None = None,
    ) -> SellReservation:
        if quantity_base <= 0:
            raise ValueError("quantity_base must be > 0")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")

        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM execution_sell_reservation WHERE idempotency_key = %s",
                [idempotency_key],
            )
            existing = cursor.fetchone()
            if existing:
                return _row_to_reservation(existing)

            cursor.execute(
                """
                INSERT INTO execution_sell_reservation (
                    trading_account_id, venue, asset_id, symbol,
                    idempotency_key, quantity_base, reservation_state,
                    manual_execution_request_id, execution_plan_id, leg_number,
                    notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    trading_account_id,
                    venue,
                    asset_id,
                    symbol,
                    idempotency_key,
                    quantity_base,
                    STATE_APPROVED_NOT_SUBMITTED,
                    manual_execution_request_id,
                    execution_plan_id,
                    leg_number,
                    notes,
                ],
            )
            reservation_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM execution_sell_reservation WHERE reservation_id = %s",
                [reservation_id],
            )
            row = cursor.fetchone()
            return _row_to_reservation(row)

    def sum_approved_not_submitted(
        self, *, trading_account_id: int, venue: str, asset_id: int
    ) -> Decimal:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                SELECT COALESCE(SUM(quantity_base), 0) AS total
                FROM execution_sell_reservation
                WHERE trading_account_id = %s AND venue = %s AND asset_id = %s
                  AND reservation_state = %s
                """,
                [trading_account_id, venue, asset_id, STATE_APPROVED_NOT_SUBMITTED],
            )
            row = cursor.fetchone()
        return Decimal(str(row["total"])) if row else Decimal("0")

    def count_reconciliation_pending(
        self, *, trading_account_id: int, venue: str, asset_id: int
    ) -> int:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM execution_sell_reservation
                WHERE trading_account_id = %s AND venue = %s AND asset_id = %s
                  AND reservation_state = %s
                """,
                [trading_account_id, venue, asset_id, STATE_SUBMITTED_AWAITING_RECONCILIATION],
            )
            row = cursor.fetchone()
        return int(row["n"]) if row else 0

    def reconcile_reservation_state(
        self,
        *,
        reservation_id: int,
        new_state: str,
        broker_order_id: str | None,
        matching_broker_rows: int,
    ) -> SellReservation:
        """The only permitted state-transition entrypoint. `matching_broker_rows`
        is the count of broker order-snapshot rows this reservation was
        matched against by the caller (a reconciliation job); anything other
        than exactly 1 is ambiguous broker state and fails closed.
        """
        if matching_broker_rows != 1:
            raise AmbiguousBrokerStateError(
                f"reservation_id={reservation_id} matched {matching_broker_rows} "
                "broker rows; exactly 1 required to reconcile"
            )
        if new_state not in ALL_STATES:
            raise ValueError(f"unknown reservation_state: {new_state}")

        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM execution_sell_reservation WHERE reservation_id = %s FOR UPDATE",
                [reservation_id],
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"reservation_id={reservation_id} not found")

            current_state = str(row["reservation_state"])
            allowed = _ALLOWED_TRANSITIONS.get(current_state, frozenset())
            if new_state != current_state and new_state not in allowed:
                raise InvalidReservationTransitionError(
                    f"reservation_id={reservation_id} cannot transition "
                    f"{current_state} -> {new_state}"
                )

            if new_state in TERMINAL_STATES:
                cursor.execute(
                    """
                    UPDATE execution_sell_reservation
                    SET reservation_state = %s,
                        broker_order_id = COALESCE(%s, broker_order_id),
                        updated_ts_utc = UTC_TIMESTAMP(),
                        terminal_ts_utc = UTC_TIMESTAMP()
                    WHERE reservation_id = %s
                    """,
                    [new_state, broker_order_id, reservation_id],
                )
            else:
                cursor.execute(
                    """
                    UPDATE execution_sell_reservation
                    SET reservation_state = %s,
                        broker_order_id = COALESCE(%s, broker_order_id),
                        updated_ts_utc = UTC_TIMESTAMP()
                    WHERE reservation_id = %s
                    """,
                    [new_state, broker_order_id, reservation_id],
                )

            cursor.execute(
                "SELECT * FROM execution_sell_reservation WHERE reservation_id = %s",
                [reservation_id],
            )
            updated = cursor.fetchone()
            return _row_to_reservation(updated)
