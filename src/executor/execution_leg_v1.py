"""Persisted shared executor leg state machine. It has no rearm/delete API."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from pymysql.err import IntegrityError

from src.executor import _trusted_clock_v1 as trusted_clock

PREPARED = "PREPARED"
SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
ACTIVE = "ACTIVE"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"
CANCELED = "CANCELED"
EXPIRED = "EXPIRED"
REJECTED = "REJECTED"
FAILED = "FAILED"
ACCEPTED_STATES = frozenset({ACTIVE, PARTIALLY_FILLED, FILLED})
CLOSED_STATES = frozenset({CANCELED, EXPIRED, REJECTED})


class ExecutionLegConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionLegV1:
    execution_leg_id: int | None
    handoff_id: int
    leg_index: int
    trading_account_id: int
    venue: str
    market: str
    side: str
    client_order_id: str
    operator_id: int
    price: Decimal
    quantity: Decimal
    state: str = PREPARED
    broker_order_id: str | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)


def _cursor(value: Any) -> Any:
    return value[1] if isinstance(value, tuple) else value


def _row_to_leg(row: Any) -> ExecutionLegV1:
    return ExecutionLegV1(
        execution_leg_id=int(row["executor_execution_leg_id"]),
        handoff_id=int(row["executor_execution_handoff_id"]),
        leg_index=int(row["leg_index"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        market=str(row["market"]),
        side=str(row["side"]),
        client_order_id=str(row["client_order_id"]),
        operator_id=int(row["operator_id"]),
        price=Decimal(str(row["price"])),
        quantity=Decimal(str(row["quantity"])),
        state=str(row["state"]),
        broker_order_id=(
            None if row.get("broker_order_id") is None else str(row["broker_order_id"])
        ),
    )


def _validate_leg(leg: ExecutionLegV1) -> None:
    for name, value in (
        ("handoff_id", leg.handoff_id),
        ("leg_index", leg.leg_index),
        ("trading_account_id", leg.trading_account_id),
        ("operator_id", leg.operator_id),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if leg.side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    for name, value in (("venue", leg.venue), ("market", leg.market), ("client_order_id", leg.client_order_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} required")
    for name, value in (("price", leg.price), ("quantity", leg.quantity)):
        if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise ValueError(f"{name} must be a finite positive Decimal")


def _same_identity(left: ExecutionLegV1, right: ExecutionLegV1) -> bool:
    return (
        left.handoff_id,
        left.leg_index,
        left.trading_account_id,
        left.venue,
        left.market,
        left.side,
        left.client_order_id,
        left.operator_id,
        left.price,
        left.quantity,
    ) == (
        right.handoff_id,
        right.leg_index,
        right.trading_account_id,
        right.venue,
        right.market,
        right.side,
        right.client_order_id,
        right.operator_id,
        right.price,
        right.quantity,
    )


@dataclass
class ExecutionLegRepositoryV1:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False)

    def persist_prepared(self, leg: ExecutionLegV1) -> tuple[ExecutionLegV1, bool]:
        _validate_leg(leg)
        try:
            with self.cursor_factory(commit=True) as db_obj:
                cursor = _cursor(db_obj)
                cursor.execute(
                    "INSERT INTO executor_execution_leg "
                    "(executor_execution_handoff_id, leg_index, trading_account_id, "
                    "venue, market, side, client_order_id, operator_id, price, quantity, "
                    "state, created_ts_utc) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        leg.handoff_id,
                        leg.leg_index,
                        leg.trading_account_id,
                        leg.venue,
                        leg.market,
                        leg.side,
                        leg.client_order_id,
                        leg.operator_id,
                        leg.price,
                        leg.quantity,
                        PREPARED,
                        trusted_clock.utc_now(),
                    ],
                )
                return replace_leg_id(leg, int(cursor.lastrowid)), True
        except IntegrityError:
            existing = self.find_by_handoff_and_index(leg.handoff_id, leg.leg_index)
            if existing is None:
                raise
            if not _same_identity(existing, leg):
                raise ExecutionLegConflictError("EXECUTION_LEG_IDENTITY_CONFLICT")
            return existing, False

    def claim_submission(self, leg_id: int) -> tuple[ExecutionLegV1, bool]:
        return self._transition(leg_id, PREPARED, SUBMISSION_UNCERTAIN)

    def mark_reconciliation_required(self, leg_id: int) -> ExecutionLegV1:
        leg, won = self._transition(leg_id, SUBMISSION_UNCERTAIN, RECONCILIATION_REQUIRED)
        if won or leg.state == RECONCILIATION_REQUIRED:
            return leg
        raise ExecutionLegConflictError("RECONCILIATION_REQUIRED_TRANSITION_CONFLICT")

    def mark_uncertain(self, leg_id: int) -> ExecutionLegV1:
        leg = self.find(leg_id)
        if leg is None:
            raise LookupError("EXECUTION_LEG_NOT_FOUND")
        if leg.state != SUBMISSION_UNCERTAIN:
            raise ExecutionLegConflictError("SUBMISSION_UNCERTAIN_TRANSITION_CONFLICT")
        return leg

    def persist_accepted(self, leg_id: int, state: str, broker_order_id: str) -> ExecutionLegV1:
        if state not in ACCEPTED_STATES or not isinstance(broker_order_id, str) or not broker_order_id.strip():
            raise ValueError("accepted acknowledgement requires state and broker_order_id")
        return self._resolved_transition(leg_id, state, broker_order_id)

    def persist_closed(self, leg_id: int, state: str, broker_order_id: str | None = None) -> ExecutionLegV1:
        if state not in CLOSED_STATES and state != FAILED:
            raise ValueError("not a closed state")
        return self._resolved_transition(leg_id, state, broker_order_id)

    def _resolved_transition(self, leg_id: int, state: str, broker_order_id: str | None) -> ExecutionLegV1:
        leg, won = self._transition(leg_id, SUBMISSION_UNCERTAIN, state, broker_order_id)
        if won or leg.state == state:
            return leg
        raise ExecutionLegConflictError("EXECUTION_LEG_RESOLUTION_CONFLICT")

    def _transition(self, leg_id: int, old: str, new: str, broker_order_id: str | None = None) -> tuple[ExecutionLegV1, bool]:
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute("UPDATE executor_execution_leg SET state=%s, broker_order_id=COALESCE(%s, broker_order_id), updated_ts_utc=%s WHERE executor_execution_leg_id=%s AND state=%s", [new, broker_order_id, trusted_clock.utc_now(), leg_id, old])
            won = cursor.rowcount == 1
        leg = self.find(leg_id)
        if leg is None:
            raise LookupError("EXECUTION_LEG_NOT_FOUND")
        return leg, won

    def find_by_handoff_and_index(self, handoff_id: int, leg_index: int) -> ExecutionLegV1 | None:
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute("SELECT * FROM executor_execution_leg WHERE executor_execution_handoff_id=%s AND leg_index=%s", [handoff_id, leg_index])
            row = cursor.fetchone()
            return None if row is None else _row_to_leg(row)

    def find(self, leg_id: int) -> ExecutionLegV1 | None:
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute("SELECT * FROM executor_execution_leg WHERE executor_execution_leg_id=%s", [leg_id])
            row = cursor.fetchone()
            return None if row is None else _row_to_leg(row)


ExecutionLegRepository = ExecutionLegRepositoryV1


def replace_leg_id(leg: ExecutionLegV1, leg_id: int) -> ExecutionLegV1:
    return ExecutionLegV1(
        execution_leg_id=leg_id,
        handoff_id=leg.handoff_id,
        leg_index=leg.leg_index,
        trading_account_id=leg.trading_account_id,
        venue=leg.venue,
        market=leg.market,
        side=leg.side,
        client_order_id=leg.client_order_id,
        operator_id=leg.operator_id,
        price=leg.price,
        quantity=leg.quantity,
        state=leg.state,
        broker_order_id=leg.broker_order_id,
    )
