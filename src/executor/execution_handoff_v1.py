"""Shared executor intake for immutable approved plans; LIVE is denied."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pymysql.err import IntegrityError

from src.executor import _trusted_clock_v1 as trusted_clock
from src.executor.execution_credential_scope_v1 import CredentialScopeDeniedError, ExecutorCredentialScopeRepository
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
    executor_credential_binding_id: int


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)


def _cursor(value: Any) -> Any:
    return value[1] if isinstance(value, tuple) else value


def _row_to_handoff(row: Any) -> ExecutionHandoffV1:
    return ExecutionHandoffV1(
        handoff_id=int(row["executor_execution_handoff_id"]),
        plan_source=str(row["plan_source"]),
        plan_reference_id=str(row["plan_reference_id"]),
        plan_content_hash=str(row["plan_content_hash"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]), market=str(row["market"]), side=str(row["side"]),
        executor_mode=str(row["executor_mode"]), executor_identity=str(row["executor_identity"]),
        runtime_owner=str(row["runtime_owner"]),
        executor_credential_binding_id=int(row["executor_credential_binding_id"]),
    )


def _candidate(plan: ApprovedExecutionPlanV1, mode: str, identity: str, owner: str, binding_id: int) -> ExecutionHandoffV1:
    return ExecutionHandoffV1(None, plan.plan_source, plan.plan_reference_id, plan.content_hash, plan.trading_account_id, plan.venue, plan.market, plan.side, mode, identity, owner, binding_id)


def _same_identity(left: ExecutionHandoffV1, right: ExecutionHandoffV1) -> bool:
    return left.__dict__.copy() | {"handoff_id": None} == right.__dict__.copy() | {"handoff_id": None}


@dataclass
class ExecutionHandoffRepositoryV1:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False)
    credential_scope_repository: ExecutorCredentialScopeRepository | None = None

    def __post_init__(self) -> None:
        if self.credential_scope_repository is None:
            self.credential_scope_repository = ExecutorCredentialScopeRepository(cursor_factory=self.cursor_factory)

    def intake(self, *, plan: ApprovedExecutionPlanV1, executor_mode: str, executor_identity: str, runtime_owner: str) -> ExecutionHandoffV1:
        if executor_mode not in ALLOWED_EXECUTOR_INTAKE_MODES:
            raise ExecutionHandoffDeniedError("EXECUTOR_MODE_NOT_PERMITTED_FOR_INTAKE")
        if not isinstance(executor_identity, str) or not isinstance(runtime_owner, str):
            raise ExecutionHandoffDeniedError("EXECUTOR_IDENTITY_AND_RUNTIME_OWNER_REQUIRED")
        identity = executor_identity.strip()
        owner = runtime_owner.strip()
        if not identity or not owner:
            raise ExecutionHandoffDeniedError("EXECUTOR_IDENTITY_AND_RUNTIME_OWNER_REQUIRED")
        assert self.credential_scope_repository is not None
        try:
            binding = self.credential_scope_repository.resolve(trading_account_id=plan.trading_account_id, venue=plan.venue, executor_identity=identity, runtime_owner=owner)
        except CredentialScopeDeniedError as exc:
            raise ExecutionHandoffDeniedError(str(exc)) from exc
        candidate = _candidate(plan, executor_mode, identity, owner, binding.executor_credential_binding_id)
        try:
            with self.cursor_factory(commit=True) as db_obj:
                cursor = _cursor(db_obj)
                cursor.execute("INSERT INTO executor_execution_handoff (plan_source, plan_reference_id, plan_content_hash, trading_account_id, venue, market, side, executor_mode, executor_identity, runtime_owner, executor_credential_binding_id, created_ts_utc) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", [candidate.plan_source, candidate.plan_reference_id, candidate.plan_content_hash, candidate.trading_account_id, candidate.venue, candidate.market, candidate.side, candidate.executor_mode, candidate.executor_identity, candidate.runtime_owner, candidate.executor_credential_binding_id, trusted_clock.utc_now()])
                return ExecutionHandoffV1(
                    handoff_id=int(cursor.lastrowid),
                    plan_source=candidate.plan_source,
                    plan_reference_id=candidate.plan_reference_id,
                    plan_content_hash=candidate.plan_content_hash,
                    trading_account_id=candidate.trading_account_id,
                    venue=candidate.venue,
                    market=candidate.market,
                    side=candidate.side,
                    executor_mode=candidate.executor_mode,
                    executor_identity=candidate.executor_identity,
                    runtime_owner=candidate.runtime_owner,
                    executor_credential_binding_id=candidate.executor_credential_binding_id,
                )
        except IntegrityError:
            existing = self.find_by_plan_reference(plan.plan_source, plan.plan_reference_id)
            if existing is None:
                raise
            if not _same_identity(existing, candidate):
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


ExecutionHandoffRepository = ExecutionHandoffRepositoryV1
