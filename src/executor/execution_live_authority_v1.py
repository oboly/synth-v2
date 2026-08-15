"""
execution_live_authority_v1 -- the shared, bounded, revocable, auditable
LIVE-submission permission consumable by algorithmic SELL (#392) and
algorithmic BUY (#399) without any manual/typed trade-confirmation artifact
(Issue #206, P0-D).

Layer: executor-only. Deny-by-default: absence of a matching row is the
default and is what keeps every DRY_RUN/PAPER handoff from ever being
usable for a real broker write, independent of any environment variable
and independent of runtime startup.

This is a deliberate generalization, not a reuse, of
src.executor.manual_execution_live_authority_v1: that module binds
authority to one specific already-claimed handoff_id (created only after a
manual request/approval/plan_snapshot chain exists) and its LIVE submission
entrypoint additionally requires
src.executor.manual_live_authorization_v1.require_manual_live_authorization
-- an env-var gate keyed to one exact handoff_id, i.e. a typed, per-order
manual confirmation. Issue #206 explicitly requires the algorithmic lanes
be able to check LIVE authority *before* any specific plan/handoff exists,
and explicitly forbids a typed manual-confirmation dependency, so this
module is scoped to (trading_account_id, venue, side[, market]) instead --
see docs/architecture/algorithmic_executor_boundary_v1.md.

Both this module's persisted authority AND the global kill switch
(src.executor.execution_kill_switch_v1) are independently required before a
LIVE broker call -- require_live_authority() below composes both, in that
order, so neither location can be checked in isolation and forgotten.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Final

from src.executor._trusted_clock_v1 import utc_now
from src.executor.execution_kill_switch_v1 import ExecutionKillSwitchRepository
from src.executor.execution_plan_reference_v1 import VALID_SIDES


class LiveAuthorityDeniedError(PermissionError):
    """Fail-closed: no persisted, currently-effective, non-revoked LIVE
    authority row matches this exact scope (the default state), or the
    global kill switch is engaged."""


@dataclass(frozen=True)
class LiveAuthorityGrant:
    live_authority_id: int
    trading_account_id: int
    venue: str
    side: str
    market: str | None
    executor_identity: str
    runtime_owner: str
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime
    revoked_ts_utc: datetime | None
    revoked_by: str | None
    authorized_by: str
    authorization_reason: str
    created_ts_utc: datetime | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _row_to_grant(row: Any) -> LiveAuthorityGrant:
    return LiveAuthorityGrant(
        live_authority_id=int(row["executor_live_authority_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        side=str(row["side"]),
        market=row.get("market"),
        executor_identity=str(row["executor_identity"]),
        runtime_owner=str(row["runtime_owner"]),
        effective_from_ts_utc=row["effective_from_ts_utc"],
        effective_until_ts_utc=row["effective_until_ts_utc"],
        revoked_ts_utc=row.get("revoked_ts_utc"),
        revoked_by=row.get("revoked_by"),
        authorized_by=str(row["authorized_by"]),
        authorization_reason=str(row["authorization_reason"]),
        created_ts_utc=row.get("created_ts_utc"),
    )


_MAX_GRANT_WINDOW_SECONDS: Final[int] = 7 * 24 * 3600  # 7 days -- "bounded" is enforced, not advisory.


@dataclass
class ExecutionLiveAuthorityRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def grant(
        self,
        *,
        trading_account_id: int,
        venue: str,
        side: str,
        market: str | None,
        executor_identity: str,
        runtime_owner: str,
        effective_from_ts_utc: datetime,
        effective_until_ts_utc: datetime,
        authorized_by: str,
        authorization_reason: str,
    ) -> LiveAuthorityGrant:
        """The single explicit, deliberate action that creates a bounded
        LIVE authority grant for one exact (account, venue, side[, market])
        scope. Never called implicitly by a submission attempt. The window
        must be bounded to at most _MAX_GRANT_WINDOW_SECONDS -- an
        open-ended or excessively long grant is rejected."""
        if side not in VALID_SIDES:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        if not venue.strip():
            raise ValueError("venue is required")
        if trading_account_id <= 0:
            raise ValueError("trading_account_id must be a persisted positive ID")
        if not executor_identity.strip():
            raise ValueError("executor_identity is required")
        if not runtime_owner.strip():
            raise ValueError("runtime_owner is required")
        if not authorized_by.strip():
            raise ValueError("authorized_by is required")
        if not authorization_reason.strip():
            raise ValueError("authorization_reason is required")
        if effective_until_ts_utc <= effective_from_ts_utc:
            raise ValueError("effective_until_ts_utc must be after effective_from_ts_utc")
        window = (effective_until_ts_utc - effective_from_ts_utc).total_seconds()
        if window > _MAX_GRANT_WINDOW_SECONDS:
            raise ValueError(
                f"LIVE_AUTHORITY_WINDOW_EXCEEDS_BOUND: {window}s > {_MAX_GRANT_WINDOW_SECONDS}s"
            )

        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                INSERT INTO executor_live_authority (
                    trading_account_id, venue, side, market,
                    executor_identity, runtime_owner,
                    effective_from_ts_utc, effective_until_ts_utc,
                    authorized_by, authorization_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    trading_account_id,
                    venue,
                    side,
                    market,
                    executor_identity,
                    runtime_owner,
                    effective_from_ts_utc,
                    effective_until_ts_utc,
                    authorized_by,
                    authorization_reason,
                ],
            )
            new_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM executor_live_authority WHERE executor_live_authority_id = %s",
                [new_id],
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("live authority insert did not return a canonical row")
            return _row_to_grant(row)

    def revoke(self, live_authority_id: int, *, revoked_by: str) -> LiveAuthorityGrant:
        """Explicit early revocation, independent of the grant's own
        expiry. Idempotent: revoking an already-revoked grant leaves its
        original revoked_ts_utc/revoked_by unchanged."""
        if not revoked_by.strip():
            raise ValueError("revoked_by is required")
        now = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "UPDATE executor_live_authority SET revoked_ts_utc = %s, revoked_by = %s "
                "WHERE executor_live_authority_id = %s AND revoked_ts_utc IS NULL",
                [now, revoked_by, live_authority_id],
            )
            cursor.execute(
                "SELECT * FROM executor_live_authority WHERE executor_live_authority_id = %s",
                [live_authority_id],
            )
            row = cursor.fetchone()
        if not row:
            raise LookupError(f"LIVE_AUTHORITY_NOT_FOUND: {live_authority_id}")
        return _row_to_grant(row)

    def find_effective_grant(
        self,
        *,
        trading_account_id: int,
        venue: str,
        side: str,
        market: str,
        executor_identity: str,
        runtime_owner: str,
        as_of_ts_utc: datetime,
    ) -> LiveAuthorityGrant | None:
        """Read-only resolution: the most recent non-revoked grant whose
        window covers as_of_ts_utc and whose scope matches (an exact-market
        row, or a NULL-market "all markets" row). Returns None (deny) if no
        such row exists -- this is the deny-by-default authority."""
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                SELECT * FROM executor_live_authority
                WHERE trading_account_id = %s AND venue = %s AND side = %s
                  AND executor_identity = %s AND runtime_owner = %s
                  AND (market IS NULL OR market = %s)
                  AND revoked_ts_utc IS NULL
                  AND effective_from_ts_utc <= %s
                  AND effective_until_ts_utc > %s
                ORDER BY effective_from_ts_utc DESC
                LIMIT 1
                """,
                [
                    trading_account_id, venue, side, executor_identity, runtime_owner,
                    market, as_of_ts_utc, as_of_ts_utc,
                ],
            )
            row = cursor.fetchone()
            return _row_to_grant(row) if row else None


def require_live_authority(
    *,
    trading_account_id: int,
    venue: str,
    side: str,
    market: str,
    executor_identity: str,
    runtime_owner: str,
    live_authority_repository: ExecutionLiveAuthorityRepository | None = None,
    kill_switch_repository: ExecutionKillSwitchRepository | None = None,
) -> LiveAuthorityGrant:
    """The single composed LIVE-submission gate every algorithmic lane must
    call before reaching a broker write boundary. Denies first on an
    engaged kill switch (the emergency override), then on a missing
    effective per-scope grant -- both are independently required, and this
    is the only function that combines them so neither can be checked in
    isolation and forgotten."""
    kill_switch_repo = kill_switch_repository or ExecutionKillSwitchRepository()
    if kill_switch_repo.is_engaged():
        raise LiveAuthorityDeniedError("LIVE_AUTHORITY_DENIED_KILL_SWITCH_ENGAGED")

    authority_repo = live_authority_repository or ExecutionLiveAuthorityRepository()
    grant = authority_repo.find_effective_grant(
        trading_account_id=trading_account_id,
        venue=venue,
        side=side,
        market=market,
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
        as_of_ts_utc=utc_now(),
    )
    if grant is None:
        raise LiveAuthorityDeniedError(
            "LIVE_AUTHORITY_NOT_GRANTED: "
            f"trading_account_id={trading_account_id} venue={venue} side={side} market={market}"
        )
    return grant
