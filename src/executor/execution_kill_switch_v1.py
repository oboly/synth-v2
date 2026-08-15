"""
execution_kill_switch_v1 -- the global emergency LIVE-submission override
shared by algorithmic SELL (#392) and algorithmic BUY (#399) (Issue #206,
P0-D).

Layer: executor-only. Append-only
(db/migrations/20260815_algorithmic_executor_boundary_v1.sql): the most
recently created row is authoritative. No row means NOT engaged -- the
deny-by-default posture for LIVE submission already comes from the absence
of a matching src.executor.execution_live_authority_v1 grant; this table's
only job is the emergency override that can force-deny regardless of any
already-granted per-account authority, independent of runtime startup
(persisted in the DB, never an environment variable or process flag) and
independent of any specific handoff/plan.

is_kill_switch_engaged() must be checked by every LIVE submission call site
alongside (never instead of) require_live_authority() -- see
src.executor.execution_live_authority_v1.require_live_authority.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Final


@dataclass(frozen=True)
class KillSwitchState:
    kill_switch_id: int
    engaged: bool
    reason: str
    engaged_by: str
    created_ts_utc: datetime


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _row_to_state(row: Any) -> KillSwitchState:
    return KillSwitchState(
        kill_switch_id=int(row["executor_kill_switch_id"]),
        engaged=bool(row["engaged"]),
        reason=str(row["reason"]),
        engaged_by=str(row["engaged_by"]),
        created_ts_utc=row["created_ts_utc"],
    )


_ENGAGED: Final[int] = 1
_DISENGAGED: Final[int] = 0


@dataclass
class ExecutionKillSwitchRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def current_state(self) -> KillSwitchState | None:
        """Returns the most recent row, or None if the kill switch has
        never been touched (equivalent to NOT engaged)."""
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM executor_kill_switch "
                "ORDER BY executor_kill_switch_id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return _row_to_state(row) if row else None

    def is_engaged(self) -> bool:
        state = self.current_state()
        return state.engaged if state is not None else False

    def engage(self, *, reason: str, engaged_by: str) -> KillSwitchState:
        """Explicitly engage the global kill switch. Blocks every LIVE
        submission call site regardless of any granted
        execution_live_authority row, until disengage() is called."""
        return self._append(engaged=True, reason=reason, engaged_by=engaged_by)

    def disengage(self, *, reason: str, engaged_by: str) -> KillSwitchState:
        """Explicitly disengage the kill switch. Does NOT itself grant any
        LIVE authority -- per-account authority is independently required
        via execution_live_authority_v1."""
        return self._append(engaged=False, reason=reason, engaged_by=engaged_by)

    def _append(self, *, engaged: bool, reason: str, engaged_by: str) -> KillSwitchState:
        if not reason.strip():
            raise ValueError("reason is required")
        if not engaged_by.strip():
            raise ValueError("engaged_by is required")
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "INSERT INTO executor_kill_switch (engaged, reason, engaged_by) "
                "VALUES (%s, %s, %s)",
                [_ENGAGED if engaged else _DISENGAGED, reason, engaged_by],
            )
            new_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM executor_kill_switch WHERE executor_kill_switch_id = %s",
                [new_id],
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("kill switch insert did not return a canonical row")
            return _row_to_state(row)
