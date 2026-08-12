"""
manual_execution_submission_leg_inmemory_v1 — the non-persistent per-leg
repository used for dry-run rehearsal (Issue #369 review follow-up).

Layer: executor-only, no DB access whatsoever.

src.executor.manual_execution_submission_orchestrator_v1.submit_manual_sell_ladder
is deliberately parameterized by a submission_leg_repository. Rehearsal
(the CLI's --mode dry-run) must exercise the exact same orchestration code
path but must NEVER create/resolve/poison the canonical
manual_execution_submission_leg row for a plan leg — that row's
(plan_snapshot_id, leg_index) identity is also what a later LIVE run
resumes from, so a dry-run writing to the real DB-backed repository would
make the real ladder appear already submitted and permanently block LIVE
submission. This class implements the exact same public method surface as
src.executor.manual_execution_submission_leg_v1.ManualExecutionSubmissionLegRepository
(claim_prepared / find_by_id / find_by_plan_and_leg / begin_attempt /
resolve_accepted / resolve_rejected / reset_to_prepared / mark_reconciled)
purely in local process memory, so the orchestrator's behavior is identical
while no MariaDB row is ever touched. There is still only one orchestrator.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.executor.manual_execution_submission_leg_v1 import (
    STATE_PREPARED,
    STATE_SUBMISSION_UNCERTAIN,
    ManualExecutionSubmissionLeg,
    SubmissionLegConflictError,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock


@dataclass
class InMemorySubmissionLegRepository:
    """Purely local, never persisted. Construct one fresh instance per
    dry-run invocation — never share across processes, never wire into a
    LIVE submission."""

    _rows_by_id: dict[int, ManualExecutionSubmissionLeg] = field(default_factory=dict)
    _rows_by_leg: dict[tuple[int, int], int] = field(default_factory=dict)
    _client_order_ids: set[str] = field(default_factory=set)
    _next_id: int = field(default=1)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def find_by_plan_and_leg(
        self, *, plan_snapshot_id: int, leg_index: int
    ) -> ManualExecutionSubmissionLeg | None:
        with self._lock:
            submission_leg_id = self._rows_by_leg.get((plan_snapshot_id, leg_index))
            return self._rows_by_id.get(submission_leg_id) if submission_leg_id else None

    def find_by_id(self, submission_leg_id: int) -> ManualExecutionSubmissionLeg | None:
        with self._lock:
            return self._rows_by_id.get(submission_leg_id)

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
        if side != "SELL":
            raise ValueError("manual execution submission legs are SELL-only")
        if immutable_price <= 0:
            raise ValueError("immutable_price must be > 0")
        if immutable_quantity <= 0:
            raise ValueError("immutable_quantity must be > 0")

        with self._lock:
            key = (plan_snapshot_id, leg_index)
            existing_id = self._rows_by_leg.get(key)
            if existing_id is not None:
                existing = self._rows_by_id[existing_id]
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
                        )
                return existing, False

            if client_order_id in self._client_order_ids:
                raise SubmissionLegConflictError(
                    f"client_order_id already claimed by a different leg: {client_order_id}"
                )

            new_id = self._next_id
            self._next_id += 1
            leg = ManualExecutionSubmissionLeg(
                submission_leg_id=new_id,
                handoff_id=handoff_id,
                plan_snapshot_id=plan_snapshot_id,
                leg_index=leg_index,
                trading_account_id=trading_account_id,
                venue=venue,
                market=market,
                side=side,
                client_order_id=client_order_id,
                operator_id=operator_id,
                immutable_price=Decimal(str(immutable_price)),
                immutable_quantity=Decimal(str(immutable_quantity)),
                submission_state=STATE_PREPARED,
                broker_order_id=None,
                broker_status=None,
                attempt_started_ts_utc=None,
                broker_ack_ts_utc=None,
                last_reconciled_ts_utc=None,
                safe_error_code=None,
                created_ts_utc=trusted_clock.utc_now(),
            )
            self._rows_by_id[new_id] = leg
            self._rows_by_leg[key] = new_id
            self._client_order_ids.add(client_order_id)
            return leg, True

    def begin_attempt(self, submission_leg_id: int) -> tuple[ManualExecutionSubmissionLeg, bool]:
        with self._lock:
            leg = self._rows_by_id.get(submission_leg_id)
            if leg is None:
                raise LookupError(f"SUBMISSION_LEG_NOT_FOUND: {submission_leg_id}")
            if leg.submission_state != STATE_PREPARED:
                return leg, False
            updated = _replace(
                leg,
                submission_state=STATE_SUBMISSION_UNCERTAIN,
                attempt_started_ts_utc=trusted_clock.utc_now(),
            )
            self._rows_by_id[submission_leg_id] = updated
            return updated, True

    def resolve_accepted(
        self, submission_leg_id: int, *, new_state: str, broker_order_id: str, broker_status: str
    ) -> ManualExecutionSubmissionLeg:
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
        from src.executor.manual_execution_submission_leg_v1 import STATE_REJECTED

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
        with self._lock:
            leg = self._rows_by_id.get(submission_leg_id)
            if leg is None:
                raise LookupError(f"SUBMISSION_LEG_NOT_FOUND: {submission_leg_id}")
            if leg.submission_state != STATE_SUBMISSION_UNCERTAIN:
                raise SubmissionLegConflictError(
                    f"SUBMISSION_LEG_RESOLUTION_CONFLICT: submission_leg_id={submission_leg_id} "
                    f"expected_prior_state={STATE_SUBMISSION_UNCERTAIN} actual_state={leg.submission_state}"
                )
            updated = _replace(
                leg,
                submission_state=new_state,
                broker_order_id=broker_order_id,
                broker_status=broker_status,
                broker_ack_ts_utc=trusted_clock.utc_now(),
                safe_error_code=safe_error_code,
            )
            self._rows_by_id[submission_leg_id] = updated
            return updated

    def reset_to_prepared(self, submission_leg_id: int) -> tuple[ManualExecutionSubmissionLeg, bool]:
        with self._lock:
            leg = self._rows_by_id.get(submission_leg_id)
            if leg is None:
                raise LookupError(f"SUBMISSION_LEG_NOT_FOUND: {submission_leg_id}")
            if leg.submission_state != STATE_SUBMISSION_UNCERTAIN:
                return leg, False
            updated = _replace(leg, submission_state=STATE_PREPARED)
            self._rows_by_id[submission_leg_id] = updated
            return updated, True

    def mark_reconciled(self, submission_leg_id: int) -> None:
        with self._lock:
            leg = self._rows_by_id.get(submission_leg_id)
            if leg is None:
                return
            self._rows_by_id[submission_leg_id] = _replace(
                leg, last_reconciled_ts_utc=trusted_clock.utc_now()
            )


def _replace(leg: ManualExecutionSubmissionLeg, **changes: Any) -> ManualExecutionSubmissionLeg:
    import dataclasses

    return dataclasses.replace(leg, **changes)
