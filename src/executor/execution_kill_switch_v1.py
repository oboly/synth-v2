"""Append-only global emergency kill switch for canonical executor LIVE operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Final

from src.executor import _trusted_clock_v1 as trusted_clock


KILL_SWITCH_ENGAGED: Final[str] = "ENGAGED"
KILL_SWITCH_DISENGAGED: Final[str] = "DISENGAGED"
_VALID_STATES: Final[frozenset[str]] = frozenset(
    {KILL_SWITCH_ENGAGED, KILL_SWITCH_DISENGAGED}
)


class ExecutionKillSwitchError(RuntimeError):
    """The persisted kill-switch state could not be trusted."""


@dataclass(frozen=True)
class ExecutionKillSwitchEventV1:
    event_id: int | None
    state: str
    actor: str
    reason: str
    created_ts_utc: datetime


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _validate_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _row_to_event(row: Any) -> ExecutionKillSwitchEventV1:
    state = str(row["state"])
    if state not in _VALID_STATES:
        raise ExecutionKillSwitchError("EXECUTION_KILL_SWITCH_INVALID_STATE")
    try:
        event_id = int(row["executor_kill_switch_event_id"])
        created_ts_utc = row["created_ts_utc"]
        actor = _validate_text(str(row["actor"]), "actor")
        reason = _validate_text(str(row["reason"]), "reason")
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionKillSwitchError("EXECUTION_KILL_SWITCH_INVALID_EVENT") from exc
    if event_id <= 0 or not isinstance(created_ts_utc, datetime):
        raise ExecutionKillSwitchError("EXECUTION_KILL_SWITCH_INVALID_EVENT")
    return ExecutionKillSwitchEventV1(
        event_id=event_id,
        state=state,
        actor=actor,
        reason=reason,
        created_ts_utc=created_ts_utc,
    )


@dataclass
class ExecutionKillSwitchRepositoryV1:
    cursor_factory: Callable[..., Any] = field(
        default=_legacy_db_cursor, repr=False, compare=False
    )

    def append_event(
        self,
        *,
        state: str,
        actor: str,
        reason: str,
        created_ts_utc: datetime | None = None,
    ) -> ExecutionKillSwitchEventV1:
        if state not in _VALID_STATES:
            raise ValueError("state must be ENGAGED or DISENGAGED")
        actor = _validate_text(actor, "actor")
        reason = _validate_text(reason, "reason")
        created_ts_utc = created_ts_utc or trusted_clock.utc_now()
        if not isinstance(created_ts_utc, datetime):
            raise ValueError("created_ts_utc must be a datetime")

        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "INSERT INTO executor_kill_switch_event "
                "(state, actor, reason, created_ts_utc) VALUES (%s, %s, %s, %s)",
                [state, actor, reason, created_ts_utc],
            )
            event_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM executor_kill_switch_event "
                "WHERE executor_kill_switch_event_id=%s",
                [event_id],
            )
            row = cursor.fetchone()
            if not row:
                raise ExecutionKillSwitchError(
                    "EXECUTION_KILL_SWITCH_EVENT_INSERT_NOT_FOUND"
                )
            return _row_to_event(row)

    def latest_event(self) -> ExecutionKillSwitchEventV1 | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM executor_kill_switch_event "
                "ORDER BY executor_kill_switch_event_id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return _row_to_event(row) if row else None

    def is_engaged(self) -> bool:
        latest = self.latest_event()
        return latest is not None and latest.state == KILL_SWITCH_ENGAGED
