"""
operator_intent.operator_intent_service_v1 — the one operator-intent-owned
command/read boundary (Issue #262, Phase 1 of #254).

Reporting/UI and any other caller must go through this service. Nothing else
may write operator_intent / operator_intent_revision directly.

Architecture boundary:
  operator-intent command/service layer
  -> canonical persistence + append-only revision/audit history
  -> authorized read model

Operator intent expresses preference, never permission. No method here
grants trading permission, creates a ladder preview, creates execution
intent, or touches broker/order state. Status transitions driven by
decision/planning logic (e.g. ACTIVE -> READY_FOR_PLANNING) are NOT
simulated here — Phase 1 only persists whatever status a later phase
explicitly assigns via the same guarded update path, and only owns the
transitions that are purely this layer's own (create, operator-controlled
field updates, cancel, supersede, wall-clock expiration).

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence

from src.operator_intent.contracts_v1 import (
    OPEN_STATUSES,
    AuthenticatedProfileIdentity,
    DuplicateActiveIntent,
    IntentStatus,
    IntentType,
    InvalidLifecycleTransition,
    OperatorIntentRecord,
    OperatorIntentRevisionRecord,
    OptimisticConcurrencyConflict,
    UnauthorizedOperatorIntentAccess,
    UnresolvedCanonicalIdentity,
    validate_canonical_market,
    validate_venue,
)


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP_NOT_ALLOWED: caller must supply timezone-aware UTC datetimes")
    return value.astimezone(UTC)


def _record_from_row(row: Mapping[str, Any]) -> OperatorIntentRecord:
    return OperatorIntentRecord(
        operator_intent_id=int(row["operator_intent_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        canonical_market=str(row["canonical_market"]),
        intent_type=str(row["intent_type"]),
        priority=int(row["priority"]),
        status=str(row["status"]),
        reason=(str(row["reason"]) if row["reason"] is not None else None),
        source=str(row["source"]),
        created_by_app_user_id=int(row["created_by_app_user_id"]),
        created_ts_utc=row["created_ts_utc"],
        updated_by_app_user_id=int(row["updated_by_app_user_id"]),
        updated_ts_utc=row["updated_ts_utc"],
        expires_ts_utc=row["expires_ts_utc"],
        version=int(row["version"]),
        supersedes_intent_id=(int(row["supersedes_intent_id"]) if row["supersedes_intent_id"] is not None else None),
        superseded_by_intent_id=(
            int(row["superseded_by_intent_id"]) if row["superseded_by_intent_id"] is not None else None
        ),
    )


def _revision_from_row(row: Mapping[str, Any]) -> OperatorIntentRevisionRecord:
    return OperatorIntentRevisionRecord(
        operator_intent_revision_id=int(row["operator_intent_revision_id"]),
        operator_intent_id=int(row["operator_intent_id"]),
        revision_version=int(row["revision_version"]),
        event_type=str(row["event_type"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        canonical_market=str(row["canonical_market"]),
        intent_type=str(row["intent_type"]),
        priority=int(row["priority"]),
        status=str(row["status"]),
        reason=(str(row["reason"]) if row["reason"] is not None else None),
        source=str(row["source"]),
        actor_app_user_id=int(row["actor_app_user_id"]),
        event_ts_utc=row["event_ts_utc"],
        expires_ts_utc=row["expires_ts_utc"],
    )


@dataclass(frozen=True)
class ExpireDueIntentsResult:
    expired_intent_ids: tuple[int, ...]


class OperatorIntentService:
    """
    Owns the operator_intent / operator_intent_revision transaction boundary.

    repo_factory is a callable that accepts a connection and returns a
    repository instance (SqliteOperatorIntentRepository or
    MariaDbOperatorIntentRepository). The service commits on success and
    rolls back on any failure or exception; callers never commit/rollback.
    """

    def __init__(self, *, repo_factory: Callable[[Any], Any]) -> None:
        self._repo_factory = repo_factory

    # -- authorization -------------------------------------------------

    def _authorize_account_scope(
        self,
        repo: Any,
        *,
        identity: AuthenticatedProfileIdentity,
        trading_account_id: int,
        venue: str,
    ) -> Mapping[str, Any]:
        access = repo.find_user_profile_access(
            app_user_id=identity.app_user_id, app_profile_id=identity.app_profile_id
        )
        if access is None:
            raise UnauthorizedOperatorIntentAccess(
                f"UNAUTHORIZED_USER_PROFILE: app_user_id={identity.app_user_id} "
                f"app_profile_id={identity.app_profile_id}"
            )
        link = repo.find_active_account_link(
            app_profile_id=identity.app_profile_id, trading_account_id=trading_account_id
        )
        if link is None:
            raise UnauthorizedOperatorIntentAccess(
                f"UNAUTHORIZED_ACCOUNT_ACCESS: app_profile_id={identity.app_profile_id} "
                f"trading_account_id={trading_account_id}"
            )
        account = repo.get_trading_account(trading_account_id=trading_account_id)
        if account is None:
            raise UnresolvedCanonicalIdentity(f"UNRESOLVED_TRADING_ACCOUNT: trading_account_id={trading_account_id}")
        account_venue = str(account["venue"]).strip().lower()
        if account_venue != venue:
            raise UnresolvedCanonicalIdentity(
                f"VENUE_MISMATCH: trading_account_id={trading_account_id} "
                f"account_venue={account_venue!r} requested_venue={venue!r}"
            )
        return account

    # -- create ----------------------------------------------------------

    def create_intent(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        trading_account_id: int,
        venue: str,
        canonical_market: str,
        intent_type: str,
        priority: int = 0,
        status: str = IntentStatus.ACTIVE.value,
        reason: str | None = None,
        source: str = "OPERATOR_MANUAL",
        expires_ts_utc: datetime | None = None,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
    ) -> OperatorIntentRecord:
        venue = validate_venue(venue)
        canonical_market = validate_canonical_market(canonical_market)
        intent_type_value = IntentType(intent_type).value
        status_value = IntentStatus(status).value
        if IntentStatus(status_value) not in OPEN_STATUSES:
            raise InvalidLifecycleTransition(f"CANNOT_CREATE_IN_TERMINAL_STATUS: {status_value!r}")
        now_utc = _require_utc(now_utc)
        if expires_ts_utc is not None:
            expires_ts_utc = _require_utc(expires_ts_utc)

        conn = conn_factory()
        try:
            repo = self._repo_factory(conn)
            self._authorize_account_scope(repo, identity=identity, trading_account_id=trading_account_id, venue=venue)

            existing = repo.find_open_intent_for_scope(
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=canonical_market,
                intent_type=intent_type_value,
            )
            if existing is not None:
                conn.rollback()
                raise DuplicateActiveIntent(
                    f"DUPLICATE_ACTIVE_INTENT: trading_account_id={trading_account_id} venue={venue!r} "
                    f"canonical_market={canonical_market!r} intent_type={intent_type_value!r} "
                    f"existing_operator_intent_id={existing['operator_intent_id']}"
                )

            operator_intent_id = repo.insert_intent(
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=canonical_market,
                intent_type=intent_type_value,
                priority=priority,
                status=status_value,
                reason=reason,
                source=source,
                created_by_app_user_id=identity.app_user_id,
                created_ts_utc=now_utc,
                updated_by_app_user_id=identity.app_user_id,
                updated_ts_utc=now_utc,
                expires_ts_utc=expires_ts_utc,
                version=1,
            )
            repo.insert_revision(
                operator_intent_id=operator_intent_id,
                revision_version=1,
                event_type="CREATED",
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=canonical_market,
                intent_type=intent_type_value,
                priority=priority,
                status=status_value,
                reason=reason,
                source=source,
                actor_app_user_id=identity.app_user_id,
                event_ts_utc=now_utc,
                expires_ts_utc=expires_ts_utc,
            )
            conn.commit()
            return _record_from_row(repo.get_intent(operator_intent_id=operator_intent_id))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- update (operator-controlled fields only) -------------------------

    def update_intent(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        operator_intent_id: int,
        expected_version: int,
        priority: Any = UNSET,
        reason: Any = UNSET,
        expires_ts_utc: Any = UNSET,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
    ) -> OperatorIntentRecord:
        now_utc = _require_utc(now_utc)
        conn = conn_factory()
        try:
            repo = self._repo_factory(conn)
            row = repo.get_intent(operator_intent_id=operator_intent_id)
            if row is None:
                conn.rollback()
                raise UnresolvedCanonicalIdentity(f"INTENT_NOT_FOUND: operator_intent_id={operator_intent_id}")
            self._authorize_account_scope(
                repo,
                identity=identity,
                trading_account_id=int(row["trading_account_id"]),
                venue=str(row["venue"]),
            )
            if IntentStatus(str(row["status"])) not in OPEN_STATUSES:
                conn.rollback()
                raise InvalidLifecycleTransition(
                    f"CANNOT_UPDATE_TERMINAL_INTENT: operator_intent_id={operator_intent_id} status={row['status']!r}"
                )

            new_priority = int(row["priority"]) if priority is UNSET else int(priority)
            new_reason = row["reason"] if reason is UNSET else reason
            if expires_ts_utc is UNSET:
                new_expires = row["expires_ts_utc"]
            elif expires_ts_utc is None:
                new_expires = None
            else:
                new_expires = _require_utc(expires_ts_utc)

            new_version = int(row["version"]) + 1
            rowcount = repo.update_intent_versioned(
                operator_intent_id=operator_intent_id,
                expected_version=expected_version,
                new_version=new_version,
                priority=new_priority,
                reason=new_reason,
                expires_ts_utc=new_expires,
                updated_by_app_user_id=identity.app_user_id,
                updated_ts_utc=now_utc,
            )
            if rowcount == 0:
                conn.rollback()
                raise OptimisticConcurrencyConflict(
                    f"VERSION_CONFLICT: operator_intent_id={operator_intent_id} "
                    f"expected_version={expected_version} current_version={row['version']}"
                )

            repo.insert_revision(
                operator_intent_id=operator_intent_id,
                revision_version=new_version,
                event_type="UPDATED",
                trading_account_id=int(row["trading_account_id"]),
                venue=str(row["venue"]),
                canonical_market=str(row["canonical_market"]),
                intent_type=str(row["intent_type"]),
                priority=new_priority,
                status=str(row["status"]),
                reason=new_reason,
                source=str(row["source"]),
                actor_app_user_id=identity.app_user_id,
                event_ts_utc=now_utc,
                expires_ts_utc=new_expires,
            )
            conn.commit()
            return _record_from_row(repo.get_intent(operator_intent_id=operator_intent_id))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def set_expiration(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        operator_intent_id: int,
        expected_version: int,
        expires_ts_utc: datetime,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
    ) -> OperatorIntentRecord:
        return self.update_intent(
            identity=identity,
            operator_intent_id=operator_intent_id,
            expected_version=expected_version,
            expires_ts_utc=expires_ts_utc,
            conn_factory=conn_factory,
            now_utc=now_utc,
        )

    def clear_expiration(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        operator_intent_id: int,
        expected_version: int,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
    ) -> OperatorIntentRecord:
        return self.update_intent(
            identity=identity,
            operator_intent_id=operator_intent_id,
            expected_version=expected_version,
            expires_ts_utc=None,
            conn_factory=conn_factory,
            now_utc=now_utc,
        )

    # -- cancel ------------------------------------------------------------

    def cancel_intent(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        operator_intent_id: int,
        expected_version: int,
        reason: str | None = None,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
    ) -> OperatorIntentRecord:
        return self._terminate(
            identity=identity,
            operator_intent_id=operator_intent_id,
            expected_version=expected_version,
            terminal_status=IntentStatus.CANCELLED,
            event_type="CANCELLED",
            reason=reason,
            conn_factory=conn_factory,
            now_utc=now_utc,
        )

    def _terminate(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        operator_intent_id: int,
        expected_version: int,
        terminal_status: IntentStatus,
        event_type: str,
        reason: str | None,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
        extra_fields: Mapping[str, Any] | None = None,
    ) -> OperatorIntentRecord:
        now_utc = _require_utc(now_utc)
        conn = conn_factory()
        try:
            repo = self._repo_factory(conn)
            row = repo.get_intent(operator_intent_id=operator_intent_id)
            if row is None:
                conn.rollback()
                raise UnresolvedCanonicalIdentity(f"INTENT_NOT_FOUND: operator_intent_id={operator_intent_id}")
            self._authorize_account_scope(
                repo,
                identity=identity,
                trading_account_id=int(row["trading_account_id"]),
                venue=str(row["venue"]),
            )
            if IntentStatus(str(row["status"])) not in OPEN_STATUSES:
                conn.rollback()
                raise InvalidLifecycleTransition(
                    f"ALREADY_TERMINAL: operator_intent_id={operator_intent_id} status={row['status']!r}"
                )

            new_version = int(row["version"]) + 1
            new_reason = row["reason"] if reason is None else reason
            update_fields: dict[str, Any] = {
                "status": terminal_status.value,
                "reason": new_reason,
                "priority": int(row["priority"]),
                "expires_ts_utc": row["expires_ts_utc"],
                "updated_by_app_user_id": identity.app_user_id,
                "updated_ts_utc": now_utc,
            }
            if extra_fields:
                update_fields.update(extra_fields)

            rowcount = repo.update_intent_versioned(
                operator_intent_id=operator_intent_id,
                expected_version=expected_version,
                new_version=new_version,
                **update_fields,
            )
            if rowcount == 0:
                conn.rollback()
                raise OptimisticConcurrencyConflict(
                    f"VERSION_CONFLICT: operator_intent_id={operator_intent_id} "
                    f"expected_version={expected_version} current_version={row['version']}"
                )

            repo.insert_revision(
                operator_intent_id=operator_intent_id,
                revision_version=new_version,
                event_type=event_type,
                trading_account_id=int(row["trading_account_id"]),
                venue=str(row["venue"]),
                canonical_market=str(row["canonical_market"]),
                intent_type=str(row["intent_type"]),
                priority=int(row["priority"]),
                status=terminal_status.value,
                reason=new_reason,
                source=str(row["source"]),
                actor_app_user_id=identity.app_user_id,
                event_ts_utc=now_utc,
                expires_ts_utc=row["expires_ts_utc"],
            )
            conn.commit()
            return _record_from_row(repo.get_intent(operator_intent_id=operator_intent_id))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- supersede -----------------------------------------------------

    def supersede_intent(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        operator_intent_id: int,
        expected_version: int,
        new_intent_type: str,
        priority: int = 0,
        status: str = IntentStatus.ACTIVE.value,
        reason: str | None = None,
        source: str = "OPERATOR_MANUAL",
        expires_ts_utc: datetime | None = None,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
    ) -> OperatorIntentRecord:
        """Mark the given intent SUPERSEDED and create its explicit replacement."""
        new_intent_type_value = IntentType(new_intent_type).value
        status_value = IntentStatus(status).value
        if IntentStatus(status_value) not in OPEN_STATUSES:
            raise InvalidLifecycleTransition(f"CANNOT_CREATE_IN_TERMINAL_STATUS: {status_value!r}")
        now_utc = _require_utc(now_utc)
        if expires_ts_utc is not None:
            expires_ts_utc = _require_utc(expires_ts_utc)

        conn = conn_factory()
        try:
            repo = self._repo_factory(conn)
            old_row = repo.get_intent(operator_intent_id=operator_intent_id)
            if old_row is None:
                conn.rollback()
                raise UnresolvedCanonicalIdentity(f"INTENT_NOT_FOUND: operator_intent_id={operator_intent_id}")
            trading_account_id = int(old_row["trading_account_id"])
            venue = str(old_row["venue"])
            canonical_market = str(old_row["canonical_market"])
            self._authorize_account_scope(repo, identity=identity, trading_account_id=trading_account_id, venue=venue)
            if IntentStatus(str(old_row["status"])) not in OPEN_STATUSES:
                conn.rollback()
                raise InvalidLifecycleTransition(
                    f"ALREADY_TERMINAL: operator_intent_id={operator_intent_id} status={old_row['status']!r}"
                )

            new_version = int(old_row["version"]) + 1
            rowcount = repo.update_intent_versioned(
                operator_intent_id=operator_intent_id,
                expected_version=expected_version,
                new_version=new_version,
                status=IntentStatus.SUPERSEDED.value,
                reason=old_row["reason"],
                priority=int(old_row["priority"]),
                expires_ts_utc=old_row["expires_ts_utc"],
                updated_by_app_user_id=identity.app_user_id,
                updated_ts_utc=now_utc,
            )
            if rowcount == 0:
                conn.rollback()
                raise OptimisticConcurrencyConflict(
                    f"VERSION_CONFLICT: operator_intent_id={operator_intent_id} "
                    f"expected_version={expected_version} current_version={old_row['version']}"
                )
            repo.insert_revision(
                operator_intent_id=operator_intent_id,
                revision_version=new_version,
                event_type="SUPERSEDED",
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=canonical_market,
                intent_type=str(old_row["intent_type"]),
                priority=int(old_row["priority"]),
                status=IntentStatus.SUPERSEDED.value,
                reason=str(old_row["reason"]) if old_row["reason"] is not None else None,
                source=str(old_row["source"]),
                actor_app_user_id=identity.app_user_id,
                event_ts_utc=now_utc,
                expires_ts_utc=old_row["expires_ts_utc"],
            )

            existing = repo.find_open_intent_for_scope(
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=canonical_market,
                intent_type=new_intent_type_value,
            )
            if existing is not None:
                conn.rollback()
                raise DuplicateActiveIntent(
                    f"DUPLICATE_ACTIVE_INTENT: trading_account_id={trading_account_id} venue={venue!r} "
                    f"canonical_market={canonical_market!r} intent_type={new_intent_type_value!r} "
                    f"existing_operator_intent_id={existing['operator_intent_id']}"
                )

            new_operator_intent_id = repo.insert_intent(
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=canonical_market,
                intent_type=new_intent_type_value,
                priority=priority,
                status=status_value,
                reason=reason,
                source=source,
                created_by_app_user_id=identity.app_user_id,
                created_ts_utc=now_utc,
                updated_by_app_user_id=identity.app_user_id,
                updated_ts_utc=now_utc,
                expires_ts_utc=expires_ts_utc,
                version=1,
                supersedes_intent_id=operator_intent_id,
            )
            repo.insert_revision(
                operator_intent_id=new_operator_intent_id,
                revision_version=1,
                event_type="CREATED",
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=canonical_market,
                intent_type=new_intent_type_value,
                priority=priority,
                status=status_value,
                reason=reason,
                source=source,
                actor_app_user_id=identity.app_user_id,
                event_ts_utc=now_utc,
                expires_ts_utc=expires_ts_utc,
            )
            repo.link_superseded_by(
                operator_intent_id=operator_intent_id, superseded_by_intent_id=new_operator_intent_id
            )

            conn.commit()
            return _record_from_row(repo.get_intent(operator_intent_id=new_operator_intent_id))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- expiration (explicit wall-clock lifecycle event, not a decision) --

    def expire_due_intents(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        trading_account_id: int,
        venue: str,
        conn_factory: Callable[[], Any],
        now_utc: datetime,
    ) -> ExpireDueIntentsResult:
        venue = validate_venue(venue)
        now_utc = _require_utc(now_utc)
        conn = conn_factory()
        try:
            repo = self._repo_factory(conn)
            self._authorize_account_scope(repo, identity=identity, trading_account_id=trading_account_id, venue=venue)
            due = repo.find_expirable_intents(now_ts_utc=now_utc, trading_account_id=trading_account_id)
            expired_ids: list[int] = []
            for row in due:
                new_version = int(row["version"]) + 1
                rowcount = repo.update_intent_versioned(
                    operator_intent_id=int(row["operator_intent_id"]),
                    expected_version=int(row["version"]),
                    new_version=new_version,
                    status=IntentStatus.EXPIRED.value,
                    reason=row["reason"],
                    priority=int(row["priority"]),
                    expires_ts_utc=row["expires_ts_utc"],
                    updated_by_app_user_id=identity.app_user_id,
                    updated_ts_utc=now_utc,
                )
                if rowcount == 0:
                    # Raced with another writer; skip rather than silently overwrite.
                    continue
                repo.insert_revision(
                    operator_intent_id=int(row["operator_intent_id"]),
                    revision_version=new_version,
                    event_type="EXPIRED",
                    trading_account_id=int(row["trading_account_id"]),
                    venue=str(row["venue"]),
                    canonical_market=str(row["canonical_market"]),
                    intent_type=str(row["intent_type"]),
                    priority=int(row["priority"]),
                    status=IntentStatus.EXPIRED.value,
                    reason=str(row["reason"]) if row["reason"] is not None else None,
                    source=str(row["source"]),
                    actor_app_user_id=identity.app_user_id,
                    event_ts_utc=now_utc,
                    expires_ts_utc=row["expires_ts_utc"],
                )
                expired_ids.append(int(row["operator_intent_id"]))
            conn.commit()
            return ExpireDueIntentsResult(expired_intent_ids=tuple(expired_ids))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- reads -----------------------------------------------------------

    def read_current_intents(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        trading_account_id: int,
        venue: str,
        canonical_market: str | None = None,
        intent_type: str | None = None,
        conn_factory: Callable[[], Any],
    ) -> Sequence[OperatorIntentRecord]:
        venue = validate_venue(venue)
        normalized_market = validate_canonical_market(canonical_market) if canonical_market is not None else None
        normalized_type = IntentType(intent_type).value if intent_type is not None else None
        conn = conn_factory()
        try:
            repo = self._repo_factory(conn)
            self._authorize_account_scope(repo, identity=identity, trading_account_id=trading_account_id, venue=venue)
            rows = repo.list_intents_for_account(
                trading_account_id=trading_account_id,
                venue=venue,
                canonical_market=normalized_market,
                intent_type=normalized_type,
            )
            conn.commit()
            return tuple(_record_from_row(row) for row in rows)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def read_revision_history(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        operator_intent_id: int,
        conn_factory: Callable[[], Any],
    ) -> Sequence[OperatorIntentRevisionRecord]:
        conn = conn_factory()
        try:
            repo = self._repo_factory(conn)
            row = repo.get_intent(operator_intent_id=operator_intent_id)
            if row is None:
                conn.rollback()
                raise UnresolvedCanonicalIdentity(f"INTENT_NOT_FOUND: operator_intent_id={operator_intent_id}")
            self._authorize_account_scope(
                repo,
                identity=identity,
                trading_account_id=int(row["trading_account_id"]),
                venue=str(row["venue"]),
            )
            revisions = repo.list_revisions_for_intent(operator_intent_id=operator_intent_id)
            conn.commit()
            return tuple(_revision_from_row(r) for r in revisions)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
