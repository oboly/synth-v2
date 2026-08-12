"""
manual_execution_submission_leg_v1 — per-leg crash-safe broker submission
identity and state machine for the manual SELL ladder submission
orchestrator (Issue #369).

Layer: executor-only. One canonical row per
(manual_execution_plan_snapshot_id, leg_index)
(db/migrations/20260813_manual_execution_submission_leg_v1.sql).

Concurrency/idempotency authority (see migration header for detail):

  - ``claim_prepared`` is a plain INSERT, never an upsert. The DB
    UNIQUE KEY on (plan_snapshot_id, leg_index) is the sole authority for
    "at most one process originates this leg row" — a second concurrent
    caller observes a duplicate-key error and is told it lost origination
    (``created=False``), never guesses from an in-memory flag.
  - ``begin_attempt`` is a single conditional UPDATE guarded by
    ``WHERE submission_state = 'PREPARED'``. Only the transaction whose
    UPDATE actually matches (cursor.rowcount == 1) may call the broker for
    that leg; this mirrors
    src.executor.manual_execution_handoff_v1.ExecutorHandoffRepository._resolve_claim
    and is what guarantees two executor processes can never both submit the
    same leg (and therefore never both submit the same handoff, since a
    later leg is only ever attempted after an earlier one resolves).

This module never calls a broker and never stores secret credential
material or arbitrary raw broker payloads — only normalized non-secret
evidence.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Final

import pymysql

from src.manual_execution import _trusted_clock_v1 as trusted_clock


STATE_PREPARED: Final[str] = "PREPARED"
STATE_SUBMISSION_UNCERTAIN: Final[str] = "SUBMISSION_UNCERTAIN"
STATE_SUBMITTED: Final[str] = "SUBMITTED"
STATE_OPEN: Final[str] = "OPEN"
STATE_PARTIALLY_FILLED: Final[str] = "PARTIALLY_FILLED"
STATE_FILLED: Final[str] = "FILLED"
STATE_CANCELLED: Final[str] = "CANCELLED"
STATE_REJECTED: Final[str] = "REJECTED"
STATE_FAILED: Final[str] = "FAILED"

ALL_STATES: Final[frozenset[str]] = frozenset(
    {
        STATE_PREPARED,
        STATE_SUBMISSION_UNCERTAIN,
        STATE_SUBMITTED,
        STATE_OPEN,
        STATE_PARTIALLY_FILLED,
        STATE_FILLED,
        STATE_CANCELLED,
        STATE_REJECTED,
        STATE_FAILED,
    }
)

# States meaning "the broker has confirmed this order exists"; the
# orchestrator may advance to the next leg once the current leg lands here.
ACCEPTED_STATES: Final[frozenset[str]] = frozenset(
    {STATE_SUBMITTED, STATE_OPEN, STATE_PARTIALLY_FILLED, STATE_FILLED}
)

# States meaning this leg's outcome is definitively unfavorable; the
# orchestrator stops the ladder (never attempts later legs) on reaching one.
TERMINAL_FAILURE_STATES: Final[frozenset[str]] = frozenset(
    {STATE_REJECTED, STATE_FAILED, STATE_CANCELLED}
)


class SubmissionLegConflictError(RuntimeError):
    """A retried/concurrent claim disagrees with the already-persisted leg,
    or attempted a transition the state machine does not allow."""


@dataclass(frozen=True)
class ManualExecutionSubmissionLeg:
    submission_leg_id: int | None
    handoff_id: int
    plan_snapshot_id: int
    leg_index: int
    trading_account_id: int
    venue: str
    market: str
    side: str
    client_order_id: str
    operator_id: int
    immutable_price: Decimal
    immutable_quantity: Decimal
    submission_state: str
    broker_order_id: str | None
    broker_status: str | None
    attempt_started_ts_utc: datetime | None
    broker_ack_ts_utc: datetime | None
    last_reconciled_ts_utc: datetime | None
    safe_error_code: str | None
    created_ts_utc: datetime | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _row_to_leg(row: Any) -> ManualExecutionSubmissionLeg:
    return ManualExecutionSubmissionLeg(
        submission_leg_id=int(row["submission_leg_id"]),
        handoff_id=int(row["manual_execution_executor_handoff_id"]),
        plan_snapshot_id=int(row["manual_execution_plan_snapshot_id"]),
        leg_index=int(row["leg_index"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        market=str(row["market"]),
        side=str(row["side"]),
        client_order_id=str(row["client_order_id"]),
        operator_id=int(row["operator_id"]),
        immutable_price=Decimal(str(row["immutable_price"])),
        immutable_quantity=Decimal(str(row["immutable_quantity"])),
        submission_state=str(row["submission_state"]),
        broker_order_id=row.get("broker_order_id"),
        broker_status=row.get("broker_status"),
        attempt_started_ts_utc=row.get("attempt_started_ts_utc"),
        broker_ack_ts_utc=row.get("broker_ack_ts_utc"),
        last_reconciled_ts_utc=row.get("last_reconciled_ts_utc"),
        safe_error_code=row.get("safe_error_code"),
        created_ts_utc=row.get("created_ts_utc"),
    )


@dataclass
class ManualExecutionSubmissionLegRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def find_by_plan_and_leg(
        self, *, plan_snapshot_id: int, leg_index: int
    ) -> ManualExecutionSubmissionLeg | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM manual_execution_submission_leg "
                "WHERE manual_execution_plan_snapshot_id = %s AND leg_index = %s",
                [plan_snapshot_id, leg_index],
            )
            row = cursor.fetchone()
            return _row_to_leg(row) if row else None

    def find_by_id(self, submission_leg_id: int) -> ManualExecutionSubmissionLeg | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM manual_execution_submission_leg WHERE submission_leg_id = %s",
                [submission_leg_id],
            )
            row = cursor.fetchone()
            return _row_to_leg(row) if row else None

    def claim_prepared(
        self,
        *,
        handoff_id: int,
        plan_snapshot_id: int,
        leg_index: int,
        trading_account_id: int,
        venue: str,
        market: str,
        side: str,
        client_order_id: str,
        operator_id: int,
        immutable_price: Decimal,
        immutable_quantity: Decimal,
    ) -> tuple[ManualExecutionSubmissionLeg, bool]:
        """Claim origination of exactly one leg row via a plain INSERT.

        Returns (leg, created). created=True means this call originated the
        row (DB constraint authority, not a read-then-write race). On a
        duplicate-key conflict, created=False and the already-persisted row
        is returned instead — the caller must treat that as a resume, never
        a fresh submission. Raises SubmissionLegConflictError if a
        conflicting row exists whose immutable identity disagrees with this
        call's inputs (a corrupted/forged retry, never a legitimate resume).
        """
        if side != "SELL":
            raise ValueError("manual execution submission legs are SELL-only")
        if immutable_price <= 0:
            raise ValueError("immutable_price must be > 0")
        if immutable_quantity <= 0:
            raise ValueError("immutable_quantity must be > 0")

        try:
            with self.cursor_factory(commit=True) as db_obj:
                cursor = _unwrap_cursor(db_obj)
                cursor.execute(
                    """
                    INSERT INTO manual_execution_submission_leg (
                        manual_execution_executor_handoff_id, manual_execution_plan_snapshot_id,
                        leg_index, trading_account_id, venue, market, side,
                        client_order_id, operator_id, immutable_price, immutable_quantity,
                        submission_state
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        handoff_id,
                        plan_snapshot_id,
                        leg_index,
                        trading_account_id,
                        venue,
                        market,
                        side,
                        client_order_id,
                        operator_id,
                        immutable_price,
                        immutable_quantity,
                        STATE_PREPARED,
                    ],
                )
                new_id = int(cursor.lastrowid)
                cursor.execute(
                    "SELECT * FROM manual_execution_submission_leg WHERE submission_leg_id = %s",
                    [new_id],
                )
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("submission leg insert did not return a canonical row")
                return _row_to_leg(row), True
        except pymysql.err.IntegrityError:
            existing = self.find_by_plan_and_leg(plan_snapshot_id=plan_snapshot_id, leg_index=leg_index)
            if existing is None:
                raise
            expected = {
                "handoff_id": handoff_id,
                "trading_account_id": trading_account_id,
                "venue": venue,
                "market": market,
                "side": side,
                "client_order_id": client_order_id,
                "operator_id": operator_id,
                "immutable_price": Decimal(str(immutable_price)),
                "immutable_quantity": Decimal(str(immutable_quantity)),
            }
            for field_name, expected_value in expected.items():
                if getattr(existing, field_name) != expected_value:
                    raise SubmissionLegConflictError(
                        f"canonical submission leg conflicts with retry identity: {field_name} "
                        f"plan_snapshot_id={plan_snapshot_id} leg_index={leg_index}"
                    ) from None
            return existing, False

    def begin_attempt(self, submission_leg_id: int) -> tuple[ManualExecutionSubmissionLeg, bool]:
        """Atomically transition PREPARED -> SUBMISSION_UNCERTAIN before any
        broker call, recording attempt_started_ts_utc. This is a
        conservative, safety-first transition: from this point on the leg
        is officially ambiguous until an explicit resolution is persisted,
        so a crash at any point after this commits is always recoverable by
        reconciling via clientOrderId rather than blindly resubmitting.

        Returns (leg, won). won=False means another process already holds
        (or has resolved) this attempt; the caller must not call the broker.
        """
        started = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE manual_execution_submission_leg
                SET submission_state = %s, attempt_started_ts_utc = %s
                WHERE submission_leg_id = %s AND submission_state = %s
                """,
                [STATE_SUBMISSION_UNCERTAIN, started, submission_leg_id, STATE_PREPARED],
            )
            won = cursor.rowcount == 1
        leg = self.find_by_id(submission_leg_id)
        if leg is None:
            raise LookupError(f"SUBMISSION_LEG_NOT_FOUND: {submission_leg_id}")
        return leg, won

    def resolve_accepted(
        self,
        submission_leg_id: int,
        *,
        new_state: str,
        broker_order_id: str,
        broker_status: str,
    ) -> ManualExecutionSubmissionLeg:
        """Persist a definitive broker acknowledgement, transitioning out of
        SUBMISSION_UNCERTAIN. Only permitted from SUBMISSION_UNCERTAIN — the
        orchestrator always passes through begin_attempt first, so a direct
        PREPARED -> accepted transition is never legitimate."""
        if new_state not in ACCEPTED_STATES:
            raise ValueError(f"not an accepted state: {new_state}")
        return self._resolve_from_uncertain(
            submission_leg_id,
            new_state=new_state,
            broker_order_id=broker_order_id,
            broker_status=broker_status,
            safe_error_code=None,
        )

    def resolve_rejected(
        self,
        submission_leg_id: int,
        *,
        safe_error_code: str,
        broker_order_id: str | None = None,
        broker_status: str | None = None,
    ) -> ManualExecutionSubmissionLeg:
        """Persist a definitive broker rejection (a real response was
        received; the order was never created)."""
        return self._resolve_from_uncertain(
            submission_leg_id,
            new_state=STATE_REJECTED,
            broker_order_id=broker_order_id,
            broker_status=broker_status,
            safe_error_code=safe_error_code,
        )

    def _resolve_from_uncertain(
        self,
        submission_leg_id: int,
        *,
        new_state: str,
        broker_order_id: str | None,
        broker_status: str | None,
        safe_error_code: str | None,
    ) -> ManualExecutionSubmissionLeg:
        now = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE manual_execution_submission_leg
                SET submission_state = %s, broker_order_id = %s, broker_status = %s,
                    broker_ack_ts_utc = %s, safe_error_code = %s
                WHERE submission_leg_id = %s AND submission_state = %s
                """,
                [
                    new_state,
                    broker_order_id,
                    broker_status,
                    now,
                    safe_error_code,
                    submission_leg_id,
                    STATE_SUBMISSION_UNCERTAIN,
                ],
            )
            won = cursor.rowcount == 1
        leg = self.find_by_id(submission_leg_id)
        if leg is None:
            raise LookupError(f"SUBMISSION_LEG_NOT_FOUND: {submission_leg_id}")
        if not won and leg.submission_state != new_state:
            raise SubmissionLegConflictError(
                f"SUBMISSION_LEG_RESOLUTION_CONFLICT: submission_leg_id={submission_leg_id} "
                f"expected_prior_state={STATE_SUBMISSION_UNCERTAIN} "
                f"actual_state={leg.submission_state}"
            )
        return leg

    def reset_to_prepared(self, submission_leg_id: int) -> tuple[ManualExecutionSubmissionLeg, bool]:
        """Atomically reset SUBMISSION_UNCERTAIN -> PREPARED, permitted only
        after the broker has definitively confirmed by clientOrderId that no
        such order exists. Only the winner of this conditional UPDATE
        (rowcount == 1) may proceed to attempt submission again via
        begin_attempt — this is the same single-writer-wins authority used
        throughout this module, so two processes reconciling the same
        uncertain leg concurrently can never both resubmit it."""
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE manual_execution_submission_leg
                SET submission_state = %s
                WHERE submission_leg_id = %s AND submission_state = %s
                """,
                [STATE_PREPARED, submission_leg_id, STATE_SUBMISSION_UNCERTAIN],
            )
            won = cursor.rowcount == 1
        leg = self.find_by_id(submission_leg_id)
        if leg is None:
            raise LookupError(f"SUBMISSION_LEG_NOT_FOUND: {submission_leg_id}")
        return leg, won

    def mark_reconciled(self, submission_leg_id: int) -> None:
        now = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "UPDATE manual_execution_submission_leg SET last_reconciled_ts_utc = %s "
                "WHERE submission_leg_id = %s",
                [now, submission_leg_id],
            )
