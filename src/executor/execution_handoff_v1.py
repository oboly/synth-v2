"""Shared executor intake for immutable approved plans.

Ordinary intake permits DRY_RUN and PAPER only. The explicit LIVE method uses
the same immutable handoff path after the canonical operational gate permits it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable

from pymysql.err import IntegrityError

from src.executor import _trusted_clock_v1 as trusted_clock
from src.executor.execution_credential_scope_v1 import CredentialScopeDeniedError, ExecutorCredentialScopeRepository
from src.executor.execution_kill_switch_v1 import ExecutionKillSwitchRepositoryV1
from src.executor.execution_live_authority_v1 import (
    ExecutionLiveAuthorityDeniedError,
    ExecutionLiveAuthorityRepositoryV1,
    require_execution_live_authority_v1,
)
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1

RUNTIME_MODE_DRY_RUN = "DRY_RUN"
RUNTIME_MODE_PAPER = "PAPER"
RUNTIME_MODE_LIVE = "LIVE"
ALLOWED_EXECUTOR_INTAKE_MODES = frozenset({RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER})


class ExecutionHandoffDeniedError(PermissionError):
    pass


class ExecutionHandoffIdentityConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionHandoffPlanLegV1:
    """Immutable approved intent stored with a shared executor handoff."""

    handoff_id: int
    leg_index: int
    trading_account_id: int
    venue: str
    market: str
    side: str
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class ExecutionHandoffClaimV1:
    handoff_id: int
    claim_token: str
    claimed_by: str
    claim_expires_ts_utc: Any


@dataclass(frozen=True)
class ExecutionHandoffV1:
    handoff_id: int | None
    plan_source: str
    plan_reference_id: str
    plan_content_hash: str
    trading_account_id: int
    venue: str
    market: str
    side: str
    executor_mode: str
    executor_identity: str
    runtime_owner: str
    executor_credential_binding_id: int | None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)


def _cursor(value: Any) -> Any:
    return value[1] if isinstance(value, tuple) else value


def _row_to_handoff(row: Any) -> ExecutionHandoffV1:
    binding_id = row["executor_credential_binding_id"]
    return ExecutionHandoffV1(
        handoff_id=int(row["executor_execution_handoff_id"]),
        plan_source=str(row["plan_source"]),
        plan_reference_id=str(row["plan_reference_id"]),
        plan_content_hash=str(row["plan_content_hash"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]), market=str(row["market"]), side=str(row["side"]),
        executor_mode=str(row["executor_mode"]), executor_identity=str(row["executor_identity"]),
        runtime_owner=str(row["runtime_owner"]),
        executor_credential_binding_id=None if binding_id is None else int(binding_id),
    )


def _row_to_plan_leg(row: Any) -> ExecutionHandoffPlanLegV1:
    return ExecutionHandoffPlanLegV1(
        handoff_id=int(row["executor_execution_handoff_id"]),
        leg_index=int(row["leg_index"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]), market=str(row["market"]), side=str(row["side"]),
        price=Decimal(str(row["price"])), quantity=Decimal(str(row["quantity"])),
    )


def _handoff_value(
    plan: ApprovedExecutionPlanV1,
    mode: str,
    identity: str,
    owner: str,
    binding_id: int | None,
) -> ExecutionHandoffV1:
    return ExecutionHandoffV1(
        None,
        plan.plan_source,
        plan.plan_reference_id,
        plan.content_hash,
        plan.trading_account_id,
        plan.venue,
        plan.market,
        plan.side,
        mode,
        identity,
        owner,
        binding_id,
    )


def _same_identity(left: ExecutionHandoffV1, right: ExecutionHandoffV1) -> bool:
    return left.__dict__.copy() | {"handoff_id": None} == right.__dict__.copy() | {"handoff_id": None}


@dataclass
class ExecutionHandoffRepositoryV1:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False)
    credential_scope_repository: ExecutorCredentialScopeRepository | None = None
    live_authority_repository: ExecutionLiveAuthorityRepositoryV1 | None = None
    kill_switch_repository: ExecutionKillSwitchRepositoryV1 | None = None

    def __post_init__(self) -> None:
        if self.credential_scope_repository is None:
            self.credential_scope_repository = ExecutorCredentialScopeRepository(cursor_factory=self.cursor_factory)
        if self.live_authority_repository is None:
            self.live_authority_repository = ExecutionLiveAuthorityRepositoryV1(
                cursor_factory=self.cursor_factory
            )
        if self.kill_switch_repository is None:
            self.kill_switch_repository = ExecutionKillSwitchRepositoryV1(
                cursor_factory=self.cursor_factory
            )

    def intake(self, *, plan: ApprovedExecutionPlanV1, executor_mode: str, executor_identity: str, runtime_owner: str) -> ExecutionHandoffV1:
        if executor_mode not in ALLOWED_EXECUTOR_INTAKE_MODES:
            raise ExecutionHandoffDeniedError("EXECUTOR_MODE_NOT_PERMITTED_FOR_INTAKE")
        return self._intake_permitted(
            plan=plan,
            executor_mode=executor_mode,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
            require_live_authority=False,
        )

    def intake_live_authorized(
        self,
        *,
        plan: ApprovedExecutionPlanV1,
        executor_identity: str,
        runtime_owner: str,
    ) -> ExecutionHandoffV1:
        return self._intake_permitted(
            plan=plan,
            executor_mode=RUNTIME_MODE_LIVE,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
            require_live_authority=True,
        )

    def _intake_permitted(
        self,
        *,
        plan: ApprovedExecutionPlanV1,
        executor_mode: str,
        executor_identity: str,
        runtime_owner: str,
        require_live_authority: bool,
    ) -> ExecutionHandoffV1:
        if (executor_mode == RUNTIME_MODE_LIVE) != require_live_authority:
            raise ExecutionHandoffDeniedError(
                "EXECUTOR_LIVE_REQUIRES_AUTHORIZED_INTAKE"
            )
        if not isinstance(executor_identity, str) or not isinstance(runtime_owner, str):
            raise ExecutionHandoffDeniedError("EXECUTOR_IDENTITY_AND_RUNTIME_OWNER_REQUIRED")
        identity = executor_identity.strip()
        owner = runtime_owner.strip()
        if not identity or not owner:
            raise ExecutionHandoffDeniedError("EXECUTOR_IDENTITY_AND_RUNTIME_OWNER_REQUIRED")

        binding_id: int | None = None
        if executor_mode != RUNTIME_MODE_DRY_RUN:
            assert self.credential_scope_repository is not None
            try:
                binding = self.credential_scope_repository.resolve(
                    trading_account_id=plan.trading_account_id,
                    venue=plan.venue,
                    executor_identity=identity,
                    runtime_owner=owner,
                )
            except CredentialScopeDeniedError as exc:
                raise ExecutionHandoffDeniedError(str(exc)) from exc
            binding_id = binding.executor_credential_binding_id

        if require_live_authority:
            assert self.live_authority_repository is not None
            assert self.kill_switch_repository is not None
            try:
                require_execution_live_authority_v1(
                    trading_account_id=plan.trading_account_id,
                    venue=plan.venue,
                    side=plan.side,
                    market=plan.market,
                    executor_identity=identity,
                    runtime_owner=owner,
                    authority_repository=self.live_authority_repository,
                    kill_switch_repository=self.kill_switch_repository,
                )
            except ExecutionLiveAuthorityDeniedError as exc:
                raise ExecutionHandoffDeniedError(str(exc)) from None

        handoff_value = _handoff_value(
            plan,
            executor_mode,
            identity,
            owner,
            binding_id,
        )
        try:
            with self.cursor_factory(commit=True) as db_obj:
                cursor = _cursor(db_obj)
                cursor.execute("INSERT INTO executor_execution_handoff (plan_source, plan_reference_id, plan_content_hash, trading_account_id, venue, market, side, executor_mode, executor_identity, runtime_owner, executor_credential_binding_id, created_ts_utc) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", [handoff_value.plan_source, handoff_value.plan_reference_id, handoff_value.plan_content_hash, handoff_value.trading_account_id, handoff_value.venue, handoff_value.market, handoff_value.side, handoff_value.executor_mode, handoff_value.executor_identity, handoff_value.runtime_owner, handoff_value.executor_credential_binding_id, trusted_clock.utc_now()])
                handoff_id = int(cursor.lastrowid)
                for leg in plan.legs:
                    cursor.execute(
                        "INSERT INTO executor_execution_handoff_plan_leg (executor_execution_handoff_id, leg_index, trading_account_id, venue, market, side, price, quantity, created_ts_utc) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        [handoff_id, leg.leg_index, plan.trading_account_id, plan.venue, plan.market, leg.side, leg.price, leg.quantity, trusted_clock.utc_now()],
                    )
                cursor.execute(
                    "INSERT INTO executor_execution_handoff_consumption (executor_execution_handoff_id, state, created_ts_utc) VALUES (%s, 'PENDING', %s)",
                    [handoff_id, trusted_clock.utc_now()],
                )
                return ExecutionHandoffV1(
                    handoff_id=handoff_id,
                    plan_source=handoff_value.plan_source,
                    plan_reference_id=handoff_value.plan_reference_id,
                    plan_content_hash=handoff_value.plan_content_hash,
                    trading_account_id=handoff_value.trading_account_id,
                    venue=handoff_value.venue,
                    market=handoff_value.market,
                    side=handoff_value.side,
                    executor_mode=handoff_value.executor_mode,
                    executor_identity=handoff_value.executor_identity,
                    runtime_owner=handoff_value.runtime_owner,
                    executor_credential_binding_id=handoff_value.executor_credential_binding_id,
                )
        except IntegrityError:
            existing = self.find_by_plan_reference(plan.plan_source, plan.plan_reference_id)
            if existing is None:
                raise
            if not _same_identity(existing, handoff_value):
                raise ExecutionHandoffIdentityConflictError("EXECUTION_HANDOFF_IDENTITY_CONFLICT")
            return existing

    def find_by_plan_reference(self, plan_source: str, plan_reference_id: str) -> ExecutionHandoffV1 | None:
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute("SELECT * FROM executor_execution_handoff WHERE plan_source=%s AND plan_reference_id=%s", [plan_source, plan_reference_id])
            row = cursor.fetchone()
            return None if row is None else _row_to_handoff(row)

    def find(self, handoff_id: int) -> ExecutionHandoffV1 | None:
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute("SELECT * FROM executor_execution_handoff WHERE executor_execution_handoff_id=%s", [handoff_id])
            row = cursor.fetchone()
            return None if row is None else _row_to_handoff(row)

    def discover_eligible(
        self,
        *,
        executor_mode: str,
        runtime_owner: str,
        executor_identity: str,
        limit: int = 100,
    ) -> tuple[ExecutionHandoffV1, ...]:
        """Discover unclaimed/reclaimable handoffs in stable persisted order."""
        if executor_mode not in {RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER, RUNTIME_MODE_LIVE}:
            raise ValueError("EXECUTOR_MODE_INVALID")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if not isinstance(runtime_owner, str) or not runtime_owner.strip():
            raise ValueError("runtime_owner required")
        if not isinstance(executor_identity, str) or not executor_identity.strip():
            raise ValueError("executor_identity required")
        now = trusted_clock.utc_now()
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                "SELECT h.* FROM executor_execution_handoff h JOIN executor_execution_handoff_consumption c ON c.executor_execution_handoff_id=h.executor_execution_handoff_id WHERE h.executor_mode=%s AND h.runtime_owner=%s AND h.executor_identity=%s AND (c.state='PENDING' OR (c.state='CLAIMED' AND c.claim_expires_ts_utc <= %s)) ORDER BY h.executor_execution_handoff_id ASC LIMIT %s",
                [executor_mode, runtime_owner.strip(), executor_identity.strip(), now, limit],
            )
            rows = cursor.fetchall()
        return tuple(_row_to_handoff(row) for row in rows)

    def claim(self, *, handoff_id: int, claim_token: str, claimed_by: str, lease_seconds: int = 60) -> bool:
        """Persistently claim an eligible handoff with a token-guarded lease."""
        if not isinstance(handoff_id, int) or isinstance(handoff_id, bool) or handoff_id <= 0:
            raise ValueError("handoff_id must be a positive integer")
        if not isinstance(claim_token, str) or not claim_token.strip() or not isinstance(claimed_by, str) or not claimed_by.strip():
            raise ValueError("claim token and worker identity required")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        now = trusted_clock.utc_now()
        expires = now + timedelta(seconds=lease_seconds)
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                "UPDATE executor_execution_handoff_consumption SET state='CLAIMED', claim_token=%s, claimed_by=%s, claim_expires_ts_utc=%s, updated_ts_utc=%s WHERE executor_execution_handoff_id=%s AND (state='PENDING' OR (state='CLAIMED' AND claim_expires_ts_utc <= %s))",
                [claim_token, claimed_by, expires, now, handoff_id, now],
            )
            return cursor.rowcount == 1

    def renew_claim(
        self, *, handoff_id: int, claim_token: str, lease_seconds: int = 60
    ) -> bool:
        """Extend only this still-current, unexpired persisted claim.

        A stale worker must never revive an expired lease after another worker
        becomes eligible to reclaim the handoff.
        """
        if not isinstance(handoff_id, int) or isinstance(handoff_id, bool) or handoff_id <= 0:
            raise ValueError("handoff_id must be a positive integer")
        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("claim token required")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        now = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                "UPDATE executor_execution_handoff_consumption SET claim_expires_ts_utc=%s, updated_ts_utc=%s "
                "WHERE executor_execution_handoff_id=%s AND state='CLAIMED' AND claim_token=%s "
                "AND claim_expires_ts_utc > %s",
                [now + timedelta(seconds=lease_seconds), now, handoff_id, claim_token, now],
            )
            return cursor.rowcount == 1

    def load_immutable_legs(self, handoff_id: int) -> tuple[ExecutionHandoffPlanLegV1, ...]:
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                "SELECT * FROM executor_execution_handoff_plan_leg WHERE executor_execution_handoff_id=%s ORDER BY leg_index ASC",
                [handoff_id],
            )
            rows = cursor.fetchall()
        if not rows:
            raise LookupError("EXECUTION_HANDOFF_PLAN_LEGS_NOT_FOUND")
        return tuple(_row_to_plan_leg(row) for row in rows)

    def finish_claim(self, *, handoff_id: int, claim_token: str, completed: bool) -> bool:
        state = "COMPLETED" if completed else "PENDING"
        now = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                f"UPDATE executor_execution_handoff_consumption SET state='{state}', claim_token=NULL, claimed_by=NULL, claim_expires_ts_utc=NULL, updated_ts_utc=%s WHERE executor_execution_handoff_id=%s AND state='CLAIMED' AND claim_token=%s AND claim_expires_ts_utc > %s",
                [now, handoff_id, claim_token, now],
            )
            return cursor.rowcount == 1


ExecutionHandoffRepository = ExecutionHandoffRepositoryV1
