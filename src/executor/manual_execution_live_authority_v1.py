"""
manual_execution_live_authority_v1 — the canonical PERSISTED LIVE permission
record for one explicit #206 executor handoff (Issue #369 review follow-up).

Layer: executor-only. One row per manual_execution_executor_handoff
(db/migrations/20260814_manual_execution_live_authority_v1.sql). Its absence
is the default and is what keeps a DRY_RUN/PAPER handoff from ever being
usable for a real broker write, independent of any environment variable.

Two-layer LIVE gate (both required; neither is a substitute for the other —
see src.executor.manual_execution_live_submission_v1 for where they are
combined):

    1. THIS module          = the canonical persisted permission (WHO/WHAT
                               is allowed), bound to one exact handoff
                               identity. Created only by grant(), a distinct
                               explicit operator action — never implied by
                               running a submission, never inferred from
                               executor_mode, never auto-created.
    2. src.executor.manual_live_authorization_v1
                             = a same-process runtime activation env gate
                               (fresh intent at this moment). Reused
                               unchanged from the original implementation.

A #206 handoff's executor_mode is always DRY_RUN or PAPER (intake never
allows anything else) — this table is a separate, later, explicit
permission layered on top of an already-claimed handoff. There is no path
by which claiming/consuming a handoff, or setting only the env var, grants
this permission.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Final

from src.executor.manual_execution_handoff_v1 import ManualExecutionExecutorHandoff
from src.manual_execution import _trusted_clock_v1 as trusted_clock


class LiveAuthorityDeniedError(PermissionError):
    """Fail-closed: no persisted LIVE authority row exists for this exact
    handoff identity (the default state)."""


class LiveAuthorityConflictError(RuntimeError):
    """A retried grant() disagrees with the already-persisted authority
    row's identity — never legitimate, always a forged/corrupted retry."""


_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "handoff_id",
    "request_id",
    "approval_id",
    "plan_snapshot_id",
    "trading_account_id",
    "venue",
    "executor_identity",
    "runtime_owner",
    "executor_credential_binding_id",
)


@dataclass(frozen=True)
class ManualExecutionLiveAuthority:
    authority_id: int | None
    handoff_id: int
    request_id: int
    approval_id: int
    plan_snapshot_id: int
    trading_account_id: int
    venue: str
    executor_identity: str
    runtime_owner: str
    executor_credential_binding_id: int
    authorized_by: str
    authorized_ts_utc: datetime
    created_ts_utc: datetime | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _row_to_authority(row: Any) -> ManualExecutionLiveAuthority:
    return ManualExecutionLiveAuthority(
        authority_id=int(row["manual_execution_live_authority_id"]),
        handoff_id=int(row["manual_execution_executor_handoff_id"]),
        request_id=int(row["manual_execution_request_id"]),
        approval_id=int(row["manual_execution_approval_id"]),
        plan_snapshot_id=int(row["manual_execution_plan_snapshot_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        executor_identity=str(row["executor_identity"]),
        runtime_owner=str(row["runtime_owner"]),
        executor_credential_binding_id=int(row["executor_credential_binding_id"]),
        authorized_by=str(row["authorized_by"]),
        authorized_ts_utc=row["authorized_ts_utc"],
        created_ts_utc=row.get("created_ts_utc"),
    )


@dataclass
class ManualExecutionLiveAuthorityRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def find_by_handoff_id(self, handoff_id: int) -> ManualExecutionLiveAuthority | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM manual_execution_live_authority "
                "WHERE manual_execution_executor_handoff_id = %s",
                [handoff_id],
            )
            row = cursor.fetchone()
            return _row_to_authority(row) if row else None

    def grant(
        self, *, handoff: ManualExecutionExecutorHandoff, authorized_by: str
    ) -> ManualExecutionLiveAuthority:
        """The single explicit, deliberate action that creates persisted
        LIVE authority for one exact handoff. Never called implicitly by a
        submission attempt. Idempotent: a retried grant for the same
        handoff_id with the same identity returns the existing row; a
        retried grant that disagrees with the persisted identity fails
        closed (LiveAuthorityConflictError)."""
        if handoff.handoff_id is None:
            raise ValueError("handoff must be persisted")
        if not authorized_by.strip():
            raise ValueError("authorized_by is required")

        authorized_ts_utc = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                INSERT INTO manual_execution_live_authority (
                    manual_execution_executor_handoff_id, manual_execution_request_id,
                    manual_execution_approval_id, manual_execution_plan_snapshot_id,
                    trading_account_id, venue, executor_identity, runtime_owner,
                    executor_credential_binding_id, authorized_by, authorized_ts_utc
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    manual_execution_live_authority_id = LAST_INSERT_ID(manual_execution_live_authority_id)
                """,
                [
                    handoff.handoff_id,
                    handoff.request_id,
                    handoff.approval_id,
                    handoff.plan_snapshot_id,
                    handoff.trading_account_id,
                    handoff.venue,
                    handoff.executor_identity,
                    handoff.runtime_owner,
                    handoff.executor_credential_binding_id,
                    authorized_by,
                    authorized_ts_utc,
                ],
            )
            authority_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM manual_execution_live_authority "
                "WHERE manual_execution_live_authority_id = %s",
                [authority_id],
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("live authority insert did not return a canonical row")
            persisted = _row_to_authority(row)

        self._assert_identity_matches(persisted, handoff=handoff)
        return persisted

    def require_matching(self, handoff: ManualExecutionExecutorHandoff) -> ManualExecutionLiveAuthority:
        """Fail-closed lookup used immediately before a LIVE broker call.
        Denies unless a persisted authority row exists AND every identity
        field still matches the handoff's own current (immutable) values."""
        if handoff.handoff_id is None:
            raise ValueError("handoff must be persisted")
        authority = self.find_by_handoff_id(handoff.handoff_id)
        if authority is None:
            raise LiveAuthorityDeniedError(
                f"LIVE_AUTHORITY_NOT_GRANTED: handoff_id={handoff.handoff_id}"
            )
        self._assert_identity_matches(authority, handoff=handoff)
        return authority

    @staticmethod
    def _assert_identity_matches(
        authority: ManualExecutionLiveAuthority, *, handoff: ManualExecutionExecutorHandoff
    ) -> None:
        expected = {
            "handoff_id": handoff.handoff_id,
            "request_id": handoff.request_id,
            "approval_id": handoff.approval_id,
            "plan_snapshot_id": handoff.plan_snapshot_id,
            "trading_account_id": handoff.trading_account_id,
            "venue": handoff.venue,
            "executor_identity": handoff.executor_identity,
            "runtime_owner": handoff.runtime_owner,
            "executor_credential_binding_id": handoff.executor_credential_binding_id,
        }
        for field_name in _IDENTITY_FIELDS:
            if getattr(authority, field_name) != expected[field_name]:
                raise LiveAuthorityConflictError(
                    f"LIVE_AUTHORITY_IDENTITY_MISMATCH: field={field_name} "
                    f"handoff_id={handoff.handoff_id}"
                )
