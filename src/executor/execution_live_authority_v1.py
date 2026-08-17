"""Bounded, revocable, deny-by-default operational authority for LIVE execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Final

from src.executor import _trusted_clock_v1 as trusted_clock
from src.executor.execution_kill_switch_v1 import ExecutionKillSwitchRepositoryV1


MAX_LIVE_AUTHORITY_WINDOW: Final[timedelta] = timedelta(days=7)
_VALID_SIDES: Final[frozenset[str]] = frozenset({"BUY", "SELL"})


class ExecutionLiveAuthorityDeniedError(PermissionError):
    """No trustworthy effective authority permits this exact LIVE operation."""


class ExecutionLiveAuthorityAmbiguousError(ExecutionLiveAuthorityDeniedError):
    """More than one effective grant matched at the same precedence."""


class ExecutionLiveAuthorityConflictError(RuntimeError):
    """An idempotent append retry conflicts with the immutable persisted fact."""


@dataclass(frozen=True)
class ExecutionLiveAuthorityGrantV1:
    grant_id: int | None
    trading_account_id: int
    venue: str
    side: str
    market: str | None
    executor_identity: str
    runtime_owner: str
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime
    authorized_by: str
    authorization_reason: str
    created_ts_utc: datetime | None = None


@dataclass(frozen=True)
class ExecutionLiveAuthorityRevocationV1:
    revocation_id: int | None
    grant_id: int
    revoked_ts_utc: datetime
    revoked_by: str
    revocation_reason: str
    created_ts_utc: datetime | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _normalize_utc_datetime(value: datetime, field_name: str) -> datetime:
    """Return an aware UTC datetime for executor *_utc contracts.

    MariaDB DATETIME carries no timezone and PyMySQL decodes it as a naive
    ``datetime``. Executor persistence defines all ``*_ts_utc`` columns as UTC,
    so naive DB values are interpreted as UTC at this repository boundary.
    Aware caller values are converted to UTC before SQL serialization so their
    wall-clock value is correct even though DATETIME itself stores no offset.
    """
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid UTC datetime") from exc


def _normalize_optional_utc_datetime(
    value: datetime | None,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None
    return _normalize_utc_datetime(value, field_name)


def _validated_scope(
    *,
    trading_account_id: int,
    venue: str,
    side: str,
    market: str | None,
    executor_identity: str,
    runtime_owner: str,
) -> tuple[int, str, str, str | None, str, str]:
    if not isinstance(trading_account_id, int) or isinstance(trading_account_id, bool):
        raise ValueError("trading_account_id must be a positive integer")
    if trading_account_id <= 0:
        raise ValueError("trading_account_id must be a positive integer")
    venue = _required_text(venue, "venue")
    if side not in _VALID_SIDES:
        raise ValueError("side must be BUY or SELL")
    if market is not None:
        market = _required_text(market, "market")
    executor_identity = _required_text(executor_identity, "executor_identity")
    runtime_owner = _required_text(runtime_owner, "runtime_owner")
    return (
        trading_account_id,
        venue,
        side,
        market,
        executor_identity,
        runtime_owner,
    )


def _validated_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start_utc = _normalize_utc_datetime(start, "effective_from_ts_utc")
    end_utc = _normalize_utc_datetime(end, "effective_until_ts_utc")
    duration = end_utc - start_utc
    if duration <= timedelta(0):
        raise ValueError("effective_until_ts_utc must be after effective_from_ts_utc")
    if duration > MAX_LIVE_AUTHORITY_WINDOW:
        raise ValueError("LIVE authority duration exceeds MAX_LIVE_AUTHORITY_WINDOW")
    return start_utc, end_utc


def _row_to_grant(row: Any) -> ExecutionLiveAuthorityGrantV1:
    try:
        grant = ExecutionLiveAuthorityGrantV1(
            grant_id=int(row["executor_live_authority_grant_id"]),
            trading_account_id=int(row["trading_account_id"]),
            venue=str(row["venue"]),
            side=str(row["side"]),
            market=None if row["market"] is None else str(row["market"]),
            executor_identity=str(row["executor_identity"]),
            runtime_owner=str(row["runtime_owner"]),
            effective_from_ts_utc=_normalize_utc_datetime(
                row["effective_from_ts_utc"], "effective_from_ts_utc"
            ),
            effective_until_ts_utc=_normalize_utc_datetime(
                row["effective_until_ts_utc"], "effective_until_ts_utc"
            ),
            authorized_by=str(row["authorized_by"]),
            authorization_reason=str(row["authorization_reason"]),
            created_ts_utc=_normalize_optional_utc_datetime(
                row.get("created_ts_utc"), "created_ts_utc"
            ),
        )
        _validated_scope(
            trading_account_id=grant.trading_account_id,
            venue=grant.venue,
            side=grant.side,
            market=grant.market,
            executor_identity=grant.executor_identity,
            runtime_owner=grant.runtime_owner,
        )
        _validated_window(
            grant.effective_from_ts_utc,
            grant.effective_until_ts_utc,
        )
        _required_text(grant.authorized_by, "authorized_by")
        _required_text(grant.authorization_reason, "authorization_reason")
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionLiveAuthorityDeniedError(
            "EXECUTION_LIVE_AUTHORITY_INVALID_GRANT"
        ) from exc
    if grant.grant_id is None or grant.grant_id <= 0:
        raise ExecutionLiveAuthorityDeniedError("EXECUTION_LIVE_AUTHORITY_INVALID_GRANT")
    return grant


def _row_to_revocation(row: Any) -> ExecutionLiveAuthorityRevocationV1:
    try:
        revocation = ExecutionLiveAuthorityRevocationV1(
            revocation_id=int(row["executor_live_authority_revocation_id"]),
            grant_id=int(row["executor_live_authority_grant_id"]),
            revoked_ts_utc=_normalize_utc_datetime(
                row["revoked_ts_utc"], "revoked_ts_utc"
            ),
            revoked_by=_required_text(str(row["revoked_by"]), "revoked_by"),
            revocation_reason=_required_text(
                str(row["revocation_reason"]), "revocation_reason"
            ),
            created_ts_utc=_normalize_optional_utc_datetime(
                row.get("created_ts_utc"), "created_ts_utc"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionLiveAuthorityConflictError(
            "EXECUTION_LIVE_AUTHORITY_INVALID_REVOCATION"
        ) from exc
    return revocation


def _require_resolved_grant_match(
    grant: ExecutionLiveAuthorityGrantV1,
    *,
    trading_account_id: int,
    venue: str,
    side: str,
    expected_market: str | None,
    executor_identity: str,
    runtime_owner: str,
    as_of_ts_utc: datetime,
) -> ExecutionLiveAuthorityGrantV1:
    if (
        grant.trading_account_id != trading_account_id
        or grant.venue != venue
        or grant.side != side
        or grant.market != expected_market
        or grant.executor_identity != executor_identity
        or grant.runtime_owner != runtime_owner
    ):
        raise ExecutionLiveAuthorityDeniedError(
            "EXECUTION_LIVE_AUTHORITY_RESOLUTION_IDENTITY_MISMATCH"
        )
    try:
        as_of_ts_utc = _normalize_utc_datetime(as_of_ts_utc, "as_of_ts_utc")
        effective = (
            grant.effective_from_ts_utc
            <= as_of_ts_utc
            < grant.effective_until_ts_utc
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionLiveAuthorityDeniedError(
            "EXECUTION_LIVE_AUTHORITY_INVALID_GRANT_TIME"
        ) from exc
    if not effective:
        raise ExecutionLiveAuthorityDeniedError(
            "EXECUTION_LIVE_AUTHORITY_NOT_EFFECTIVE"
        )
    return grant


_EFFECTIVE_SELECT: Final[str] = """
SELECT grant.*
FROM executor_live_authority_grant AS grant
WHERE grant.trading_account_id=%s
  AND grant.venue=%s
  AND grant.side=%s
  AND grant.executor_identity=%s
  AND grant.runtime_owner=%s
  AND grant.effective_from_ts_utc <= %s
  AND %s < grant.effective_until_ts_utc
  AND NOT EXISTS (
      SELECT 1 FROM executor_live_authority_revocation AS revocation
      WHERE revocation.executor_live_authority_grant_id=
            grant.executor_live_authority_grant_id
        AND revocation.revoked_ts_utc <= %s
  )
"""


@dataclass
class ExecutionLiveAuthorityRepositoryV1:
    cursor_factory: Callable[..., Any] = field(
        default=_legacy_db_cursor, repr=False, compare=False
    )

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
    ) -> ExecutionLiveAuthorityGrantV1:
        scope = _validated_scope(
            trading_account_id=trading_account_id,
            venue=venue,
            side=side,
            market=market,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
        )
        effective_from_ts_utc, effective_until_ts_utc = _validated_window(
            effective_from_ts_utc,
            effective_until_ts_utc,
        )
        authorized_by = _required_text(authorized_by, "authorized_by")
        authorization_reason = _required_text(
            authorization_reason, "authorization_reason"
        )
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                INSERT INTO executor_live_authority_grant (
                    trading_account_id, venue, side, market, executor_identity,
                    runtime_owner, effective_from_ts_utc, effective_until_ts_utc,
                    authorized_by, authorization_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    *scope,
                    effective_from_ts_utc,
                    effective_until_ts_utc,
                    authorized_by,
                    authorization_reason,
                ],
            )
            grant_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM executor_live_authority_grant "
                "WHERE executor_live_authority_grant_id=%s",
                [grant_id],
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("executor LIVE authority grant insert not found")
            return _row_to_grant(row)

    def revoke(
        self,
        *,
        grant_id: int,
        revoked_by: str,
        revocation_reason: str,
        revoked_ts_utc: datetime | None = None,
    ) -> ExecutionLiveAuthorityRevocationV1:
        if not isinstance(grant_id, int) or isinstance(grant_id, bool) or grant_id <= 0:
            raise ValueError("grant_id must be a positive integer")
        revoked_by = _required_text(revoked_by, "revoked_by")
        revocation_reason = _required_text(revocation_reason, "revocation_reason")
        timestamp_was_explicit = revoked_ts_utc is not None
        revoked_ts_utc = _normalize_utc_datetime(
            revoked_ts_utc or trusted_clock.utc_now(),
            "revoked_ts_utc",
        )

        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM executor_live_authority_revocation "
                "WHERE executor_live_authority_grant_id=%s",
                [grant_id],
            )
            existing_row = cursor.fetchone()
            if existing_row:
                existing = _row_to_revocation(existing_row)
                if (
                    existing.revoked_by == revoked_by
                    and existing.revocation_reason == revocation_reason
                    and (
                        not timestamp_was_explicit
                        or existing.revoked_ts_utc == revoked_ts_utc
                    )
                ):
                    return existing
                raise ExecutionLiveAuthorityConflictError(
                    "EXECUTION_LIVE_AUTHORITY_REVOCATION_CONFLICT"
                )
            cursor.execute(
                """
                INSERT INTO executor_live_authority_revocation (
                    executor_live_authority_grant_id, revoked_ts_utc,
                    revoked_by, revocation_reason
                ) VALUES (%s, %s, %s, %s)
                """,
                [grant_id, revoked_ts_utc, revoked_by, revocation_reason],
            )
            revocation_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM executor_live_authority_revocation "
                "WHERE executor_live_authority_revocation_id=%s",
                [revocation_id],
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("executor LIVE authority revocation insert not found")
            return _row_to_revocation(row)

    def resolve_effective(
        self,
        *,
        trading_account_id: int,
        venue: str,
        side: str,
        market: str,
        executor_identity: str,
        runtime_owner: str,
        as_of_ts_utc: datetime,
    ) -> ExecutionLiveAuthorityGrantV1:
        scope = _validated_scope(
            trading_account_id=trading_account_id,
            venue=venue,
            side=side,
            market=market,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
        )
        as_of_ts_utc = _normalize_utc_datetime(as_of_ts_utc, "as_of_ts_utc")
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            common_params = [scope[0], scope[1], scope[2], scope[4], scope[5]]
            time_params = [as_of_ts_utc, as_of_ts_utc, as_of_ts_utc]
            cursor.execute(
                _EFFECTIVE_SELECT + "  AND grant.market=%s LIMIT 2",
                [*common_params, *time_params, scope[3]],
            )
            exact_rows = cursor.fetchall()
            if len(exact_rows) > 1:
                raise ExecutionLiveAuthorityAmbiguousError(
                    "EXECUTION_LIVE_AUTHORITY_AMBIGUOUS_EXACT_MARKET"
                )
            if len(exact_rows) == 1:
                return _require_resolved_grant_match(
                    _row_to_grant(exact_rows[0]),
                    trading_account_id=scope[0],
                    venue=scope[1],
                    side=scope[2],
                    expected_market=scope[3],
                    executor_identity=scope[4],
                    runtime_owner=scope[5],
                    as_of_ts_utc=as_of_ts_utc,
                )

            cursor.execute(
                _EFFECTIVE_SELECT + "  AND grant.market IS NULL LIMIT 2",
                [*common_params, *time_params],
            )
            wildcard_rows = cursor.fetchall()
            if len(wildcard_rows) > 1:
                raise ExecutionLiveAuthorityAmbiguousError(
                    "EXECUTION_LIVE_AUTHORITY_AMBIGUOUS_WILDCARD_MARKET"
                )
            if len(wildcard_rows) == 1:
                return _require_resolved_grant_match(
                    _row_to_grant(wildcard_rows[0]),
                    trading_account_id=scope[0],
                    venue=scope[1],
                    side=scope[2],
                    expected_market=None,
                    executor_identity=scope[4],
                    runtime_owner=scope[5],
                    as_of_ts_utc=as_of_ts_utc,
                )
        raise ExecutionLiveAuthorityDeniedError("EXECUTION_LIVE_AUTHORITY_NOT_GRANTED")


def require_execution_live_authority_v1(
    *,
    trading_account_id: int,
    venue: str,
    side: str,
    market: str,
    executor_identity: str,
    runtime_owner: str,
    as_of_ts_utc: datetime | None = None,
    authority_repository: ExecutionLiveAuthorityRepositoryV1 | None = None,
    kill_switch_repository: ExecutionKillSwitchRepositoryV1 | None = None,
) -> ExecutionLiveAuthorityGrantV1:
    """Return one exact effective grant only when the global switch is clear.

    This is the sole canonical composed LIVE gate. Any repository, validation,
    ambiguity, persistence, or state failure is deliberately collapsed to a
    deny result at this boundary.
    """
    authority_repository = authority_repository or ExecutionLiveAuthorityRepositoryV1()
    kill_switch_repository = kill_switch_repository or ExecutionKillSwitchRepositoryV1()
    try:
        as_of_ts_utc = _normalize_utc_datetime(
            as_of_ts_utc or trusted_clock.utc_now(),
            "as_of_ts_utc",
        )
        if kill_switch_repository.is_engaged():
            raise ExecutionLiveAuthorityDeniedError(
                "EXECUTION_LIVE_AUTHORITY_KILL_SWITCH_ENGAGED"
            )
        return authority_repository.resolve_effective(
            trading_account_id=trading_account_id,
            venue=venue,
            side=side,
            market=market,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
            as_of_ts_utc=as_of_ts_utc,
        )
    except ExecutionLiveAuthorityDeniedError:
        raise
    except Exception as exc:
        raise ExecutionLiveAuthorityDeniedError(
            "EXECUTION_LIVE_AUTHORITY_CHECK_FAILED"
        ) from exc
