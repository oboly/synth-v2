"""
execution_leg_v1 -- side-neutral per-leg crash-safe broker submission
identity and state machine shared by algorithmic SELL (#392) and
algorithmic BUY (#399) (Issue #206).

Layer: executor-only. One canonical row per
(executor_execution_handoff_id, leg_index)
(db/migrations/20260815_algorithmic_executor_boundary_v1.sql).

Generalizes src.executor.manual_execution_submission_leg_v1: identical
concurrency/idempotency authority (see that module's docstring for the
full argument), but:

  - side is BUY or SELL, not hardcoded to SELL;
  - resolved states are the venue-neutral canonical broker-ack vocabulary
    from src.executor.broker_ack_classification_v1 (ACTIVE,
    PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED) instead of the
    manual lane's SUBMITTED/OPEN/CANCELLED, so a canceled/expired/rejected
    broker response can never be represented as an accepted submission;
  - adds RECONCILIATION_REQUIRED (Issue #206 P0-B): reached only when a
    broker lookup definitively confirms no such order exists after
    SUBMISSION_UNCERTAIN. The orchestrator in
    src.executor.execution_submission_orchestrator_v1 NEVER automatically
    leaves this state -- unlike the manual lane's
    manual_execution_submission_leg_v1.reset_to_prepared (which the manual
    orchestrator calls automatically on confirmed-absent), moving a leg
    back to PREPARED from RECONCILIATION_REQUIRED requires the separate,
    explicitly-audited rearm_after_reconciliation() call below, which
    records who performed it. This is a deliberate divergence from the
    manual lane, not an oversight -- see
    docs/architecture/algorithmic_executor_boundary_v1.md.

This module never calls a broker and never stores secret credential
material or arbitrary raw broker payloads -- only normalized non-secret
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

from src.executor._trusted_clock_v1 import utc_now
from src.executor.broker_ack_classification_v1 import ACCEPTED_ACK_STATES
from src.executor.execution_plan_reference_v1 import VALID_SIDES


STATE_PREPARED: Final[str] = "PREPARED"
STATE_SUBMISSION_UNCERTAIN: Final[str] = "SUBMISSION_UNCERTAIN"
STATE_RECONCILIATION_REQUIRED: Final[str] = "RECONCILIATION_REQUIRED"
STATE_ACTIVE: Final[str] = "ACTIVE"
STATE_PARTIALLY_FILLED: Final[str] = "PARTIALLY_FILLED"
STATE_FILLED: Final[str] = "FILLED"
STATE_CANCELED: Final[str] = "CANCELED"
STATE_EXPIRED: Final[str] = "EXPIRED"
STATE_REJECTED: Final[str] = "REJECTED"
STATE_FAILED: Final[str] = "FAILED"

ALL_STATES: Final[frozenset[str]] = frozenset(
    {
        STATE_PREPARED,
        STATE_SUBMISSION_UNCERTAIN,
        STATE_RECONCILIATION_REQUIRED,
        STATE_ACTIVE,
        STATE_PARTIALLY_FILLED,
        STATE_FILLED,
        STATE_CANCELED,
        STATE_EXPIRED,
        STATE_REJECTED,
        STATE_FAILED,
    }
)

# States meaning "the broker has confirmed this order exists (or is fully
# filled)"; the orchestrator may advance to the next leg once the current
# leg lands here. Identical vocabulary to broker_ack_classification's
# ACCEPTED_ACK_STATES by construction (asserted below) so the two modules
# can never silently drift apart.
ACCEPTED_STATES: Final[frozenset[str]] = frozenset(ACCEPTED_ACK_STATES)
assert ACCEPTED_STATES == {STATE_ACTIVE, STATE_PARTIALLY_FILLED, STATE_FILLED}

# States meaning this leg's outcome is definitively unfavorable/closed; the
# orchestrator stops the ladder (never attempts later legs) on reaching one.
# CANCELED/EXPIRED/REJECTED are broker-confirmed closed outcomes; FAILED is
# an application-level give-up (never a broker acknowledgement).
TERMINAL_FAILURE_STATES: Final[frozenset[str]] = frozenset(
    {STATE_CANCELED, STATE_EXPIRED, STATE_REJECTED, STATE_FAILED}
)

# Once a leg reaches one of these states no further submission_state change
# is legitimate for V1 -- mirrors the DB trigger trg_eel_identity_immutable.
HARD_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {STATE_FILLED, STATE_CANCELED, STATE_EXPIRED, STATE_REJECTED, STATE_FAILED}
)


class SubmissionLegConflictError(RuntimeError):
    """A retried/concurrent claim disagrees with the already-persisted leg,
    or attempted a transition the state machine does not allow."""


@dataclass(frozen=True)
class ExecutionLeg:
    execution_leg_id: int | None
    handoff_id: int
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
    reconciled_by: str | None
    safe_error_code: str | None
    created_ts_utc: datetime | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _row_to_leg(row: Any) -> ExecutionLeg:
    return ExecutionLeg(
        execution_leg_id=int(row["executor_execution_leg_id"]),
        handoff_id=int(row["executor_execution_handoff_id"]),
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
        reconciled_by=row.get("reconciled_by"),
        safe_error_code=row.get("safe_error_code"),
        created_ts_utc=row.get("created_ts_utc"),
    )


@dataclass
class ExecutionLegRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def find_by_handoff_and_leg(
        self, *, handoff_id: int, leg_index: int
    ) -> ExecutionLeg | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM executor_execution_leg "
                "WHERE executor_execution_handoff_id = %s AND leg_index = %s",
                [handoff_id, leg_index],
            )
            row = cursor.fetchone()
            return _row_to_leg(row) if row else None

    def find_by_id(self, execution_leg_id: int) -> ExecutionLeg | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM executor_execution_leg WHERE executor_execution_leg_id = %s",
                [execution_leg_id],
            )
            row = cursor.fetchone()
            return _row_to_leg(row) if row else None

    def claim_prepared(
        self,
        *,
        handoff_id: int,
        leg_index: int,
        trading_account_id: int,
        venue: str,
        market: str,
        side: str,
        client_order_id: str,
        operator_id: int,
        immutable_price: Decimal,
        immutable_quantity: Decimal,
    ) -> tuple[ExecutionLeg, bool]:
        """Claim origination of exactly one leg row via a plain INSERT.

        Returns (leg, created). created=True means this call originated the
        row (DB constraint authority, not a read-then-write race). On a
        duplicate-key conflict, created=False and the already-persisted row
        is returned instead -- the caller must treat that as a resume, never
        a fresh submission. Raises SubmissionLegConflictError if a
        conflicting row exists whose immutable identity disagrees with this
        call's inputs (a corrupted/forged retry, never a legitimate resume).
        """
        if side not in VALID_SIDES:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        if immutable_price <= 0:
            raise ValueError("immutable_price must be > 0")
        if immutable_quantity <= 0:
            raise ValueError("immutable_quantity must be > 0")

        try:
            with self.cursor_factory(commit=True) as db_obj:
                cursor = _unwrap_cursor(db_obj)
                cursor.execute(
                    """
                    INSERT INTO executor_execution_leg (
                        executor_execution_handoff_id, leg_index,
                        trading_account_id, venue, market, side,
                        client_order_id, operator_id, immutable_price, immutable_quantity,
                        submission_state
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        handoff_id,
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
                    "SELECT * FROM executor_execution_leg WHERE executor_execution_leg_id = %s",
                    [new_id],
                )
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("execution leg insert did not return a canonical row")
                return _row_to_leg(row), True
        except pymysql.err.IntegrityError:
            existing = self.find_by_handoff_and_leg(handoff_id=handoff_id, leg_index=leg_index)
            if existing is None:
                raise
            expected = {
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
                        f"canonical execution leg conflicts with retry identity: {field_name} "
                        f"handoff_id={handoff_id} leg_index={leg_index}"
                    ) from None
            return existing, False

    def begin_attempt(self, execution_leg_id: int) -> tuple[ExecutionLeg, bool]:
        """Atomically transition PREPARED -> SUBMISSION_UNCERTAIN before any
        broker call, recording attempt_started_ts_utc. Conservative,
        safety-first: from this point on the leg is officially ambiguous
        until an explicit resolution is persisted, so a crash at any point
        after this commits is always recoverable by reconciling via
        clientOrderId rather than blindly resubmitting.

        Returns (leg, won). won=False means another process already holds
        (or has resolved) this attempt; the caller must not call the broker.
        """
        started = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE executor_execution_leg
                SET submission_state = %s, attempt_started_ts_utc = %s
                WHERE executor_execution_leg_id = %s AND submission_state = %s
                """,
                [STATE_SUBMISSION_UNCERTAIN, started, execution_leg_id, STATE_PREPARED],
            )
            won = cursor.rowcount == 1
        leg = self.find_by_id(execution_leg_id)
        if leg is None:
            raise LookupError(f"EXECUTION_LEG_NOT_FOUND: {execution_leg_id}")
        return leg, won

    def resolve_accepted(
        self,
        execution_leg_id: int,
        *,
        new_state: str,
        broker_order_id: str,
        broker_status: str,
    ) -> ExecutionLeg:
        """Persist a definitive, canonically-classified broker acceptance,
        transitioning out of SUBMISSION_UNCERTAIN. Only permitted from
        SUBMISSION_UNCERTAIN -- the orchestrator always passes through
        begin_attempt first, so a direct PREPARED -> accepted transition is
        never legitimate. new_state must be one of ACCEPTED_STATES (never a
        raw venue status string) -- the caller (orchestrator) is responsible
        for classifying through broker_ack_classification_v1 first."""
        if new_state not in ACCEPTED_STATES:
            raise ValueError(f"not an accepted state: {new_state}")
        return self._resolve_from_uncertain(
            execution_leg_id,
            new_state=new_state,
            broker_order_id=broker_order_id,
            broker_status=broker_status,
            safe_error_code=None,
        )

    def resolve_closed(
        self,
        execution_leg_id: int,
        *,
        new_state: str,
        safe_error_code: str,
        broker_order_id: str | None = None,
        broker_status: str | None = None,
    ) -> ExecutionLeg:
        """Persist a definitive, canonically-classified non-active broker
        outcome (CANCELED, EXPIRED, or REJECTED -- a real response was
        received). Never used for AMBIGUOUS; ambiguous acknowledgements
        must leave the leg in SUBMISSION_UNCERTAIN instead."""
        if new_state not in (STATE_CANCELED, STATE_EXPIRED, STATE_REJECTED):
            raise ValueError(f"not a closed state: {new_state}")
        return self._resolve_from_uncertain(
            execution_leg_id,
            new_state=new_state,
            broker_order_id=broker_order_id,
            broker_status=broker_status,
            safe_error_code=safe_error_code,
        )

    def _resolve_from_uncertain(
        self,
        execution_leg_id: int,
        *,
        new_state: str,
        broker_order_id: str | None,
        broker_status: str | None,
        safe_error_code: str | None,
    ) -> ExecutionLeg:
        now = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE executor_execution_leg
                SET submission_state = %s, broker_order_id = %s, broker_status = %s,
                    broker_ack_ts_utc = %s, safe_error_code = %s
                WHERE executor_execution_leg_id = %s AND submission_state = %s
                """,
                [
                    new_state,
                    broker_order_id,
                    broker_status,
                    now,
                    safe_error_code,
                    execution_leg_id,
                    STATE_SUBMISSION_UNCERTAIN,
                ],
            )
            won = cursor.rowcount == 1
        leg = self.find_by_id(execution_leg_id)
        if leg is None:
            raise LookupError(f"EXECUTION_LEG_NOT_FOUND: {execution_leg_id}")
        if not won and leg.submission_state != new_state:
            raise SubmissionLegConflictError(
                f"EXECUTION_LEG_RESOLUTION_CONFLICT: execution_leg_id={execution_leg_id} "
                f"expected_prior_state={STATE_SUBMISSION_UNCERTAIN} "
                f"actual_state={leg.submission_state}"
            )
        return leg

    def mark_reconciliation_required(self, execution_leg_id: int) -> ExecutionLeg:
        """Issue #206 P0-B fail-closed transition: SUBMISSION_UNCERTAIN ->
        RECONCILIATION_REQUIRED once a broker lookup has definitively
        confirmed no such order exists. Deliberately does NOT reset to
        PREPARED and does NOT re-attempt submission -- unlike the manual
        lane's reset_to_prepared, this never enables an automatic second
        POST. Only rearm_after_reconciliation() (an explicit, separately
        audited action) may move the leg forward from here."""
        now = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE executor_execution_leg
                SET submission_state = %s, last_reconciled_ts_utc = %s
                WHERE executor_execution_leg_id = %s AND submission_state = %s
                """,
                [STATE_RECONCILIATION_REQUIRED, now, execution_leg_id, STATE_SUBMISSION_UNCERTAIN],
            )
            won = cursor.rowcount == 1
        leg = self.find_by_id(execution_leg_id)
        if leg is None:
            raise LookupError(f"EXECUTION_LEG_NOT_FOUND: {execution_leg_id}")
        if not won and leg.submission_state != STATE_RECONCILIATION_REQUIRED:
            raise SubmissionLegConflictError(
                f"EXECUTION_LEG_RECONCILIATION_CONFLICT: execution_leg_id={execution_leg_id} "
                f"actual_state={leg.submission_state}"
            )
        return leg

    def mark_still_uncertain(self, execution_leg_id: int) -> None:
        """Record a reconciliation attempt that itself could not resolve
        the ambiguity (e.g. the lookup call raised). The leg remains
        SUBMISSION_UNCERTAIN -- fail closed, never guess."""
        now = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "UPDATE executor_execution_leg SET last_reconciled_ts_utc = %s "
                "WHERE executor_execution_leg_id = %s",
                [now, execution_leg_id],
            )

    def rearm_after_reconciliation(
        self, execution_leg_id: int, *, reconciled_by: str
    ) -> tuple[ExecutionLeg, bool]:
        """The single explicit, separately-audited action that may move a
        leg RECONCILIATION_REQUIRED -> PREPARED, permitted only after an
        operator/reconciliation job has independently re-verified broker
        absence. Never called by
        src.executor.execution_submission_orchestrator_v1 itself -- that is
        the entire point of P0-B. reconciled_by is a required, non-secret
        audit identity (never inferred, never defaulted)."""
        if not reconciled_by.strip():
            raise ValueError("reconciled_by is required")
        now = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE executor_execution_leg
                SET submission_state = %s, reconciled_by = %s, last_reconciled_ts_utc = %s
                WHERE executor_execution_leg_id = %s AND submission_state = %s
                """,
                [STATE_PREPARED, reconciled_by, now, execution_leg_id, STATE_RECONCILIATION_REQUIRED],
            )
            won = cursor.rowcount == 1
        leg = self.find_by_id(execution_leg_id)
        if leg is None:
            raise LookupError(f"EXECUTION_LEG_NOT_FOUND: {execution_leg_id}")
        return leg, won
