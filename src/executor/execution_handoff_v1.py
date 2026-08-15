"""
execution_handoff_v1 -- the one canonical, side-neutral executor handoff for
an already-approved, already-immutable BUY or SELL execution plan, shared by
algorithmic SELL (#392) and algorithmic BUY (#399) (Issue #206).

Layer: executor intake boundary, downstream of whichever lane approved and
snapshotted the plan (decision_gate + execution_planner for manual;
src.decision_gate.automatic_exit_gate_v1 + src.execution_planner.automatic_exit_planner_v1
for #392; an equivalent pair for #399), upstream of the shared submission
orchestrator.

This module intentionally does NOT foreign-key into a specific upstream
plan table the way src.executor.manual_execution_handoff_v1 foreign-keys
into manual_execution_request/approval/plan_snapshot: #392 and #399 own
their own plan persistence/audit trail, and requiring them to conform to
the manual lane's schema would violate the "side-neutral" requirement.
Instead ExecutionHandoffRepository.intake() takes one
src.executor.execution_plan_reference_v1.ApprovedExecutionPlanV1 -- an
in-memory, side-neutral description of the exact approved plan -- computes
its content hash, and binds the handoff to (plan_source, plan_reference_id,
plan_content_hash). A retried intake for the same (plan_source,
plan_reference_id) whose plan_content_hash disagrees with the
already-persisted row is a fail-closed identity conflict, never a silent
overwrite.

Fails closed unless: the plan passes ApprovedExecutionPlanV1 structural
validation; executor_mode is DRY_RUN or PAPER (LIVE_DISABLED and any
unknown mode are always denied at intake, never inferred -- see
src.executor.manual_execution_handoff_v1 for why this posture is preserved
unchanged); and a deny-by-default TRADE_EXECUTION credential scope is bound
to the exact (trading_account_id, venue, executor_identity, runtime_owner)
tuple. Credential resolution is reused directly from
src.executor.manual_execution_credential_scope_v1 -- that module has no
manual-workflow coupling at all (it resolves purely on account/venue/
executor identity), so it is SHARED_GENERIC as-is; see
docs/architecture/algorithmic_executor_boundary_v1.md for the full audit.

Single-writer/duplicate protection: the DB UNIQUE KEY on
(plan_source, plan_reference_id) is the authority for "one handoff per
approved plan" -- intake() is an idempotent insert-and-return against that
key, never an application-level read-then-insert race. Consumption
(claim_state CLAIMED -> CONSUMED | FAILED) is a single conditional UPDATE
guarded by ``WHERE claim_state = 'CLAIMED'``; only the transaction whose
UPDATE actually matches a row (cursor.rowcount == 1) has claimed
consumption authority -- identical pattern to
src.executor.manual_execution_handoff_v1.ExecutorHandoffRepository.

This module never places, cancels, or monitors broker orders and never
imports broker/exchange client code. It records only non-secret audit
evidence (outcome_code/outcome_detail); no credential material is ever
read, logged, or stored here.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Final

from src.executor._trusted_clock_v1 import utc_now
from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanV1,
    compute_plan_content_hash,
)
from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
)


RUNTIME_MODE_DRY_RUN: Final[str] = "DRY_RUN"
RUNTIME_MODE_PAPER: Final[str] = "PAPER"
RUNTIME_MODE_LIVE_DISABLED: Final[str] = "LIVE_DISABLED"
VALID_RUNTIME_MODES: Final[frozenset[str]] = frozenset(
    {RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER, RUNTIME_MODE_LIVE_DISABLED}
)

# Live trading permission is NOT_GRANTED (AGENTS.md). LIVE_DISABLED is never
# claimable by intake, no matter what a caller passes; this set is the only
# authority for which modes may be handed to an executor at all.
ALLOWED_EXECUTOR_INTAKE_MODES: Final[frozenset[str]] = frozenset(
    {RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER}
)

CLAIM_STATE_CLAIMED: Final[str] = "CLAIMED"
CLAIM_STATE_CONSUMED: Final[str] = "CONSUMED"
CLAIM_STATE_FAILED: Final[str] = "FAILED"
_TERMINAL_CLAIM_STATES: Final[frozenset[str]] = frozenset({CLAIM_STATE_CONSUMED, CLAIM_STATE_FAILED})

OUTCOME_DRY_RUN_ACKNOWLEDGED: Final[str] = "DRY_RUN_ACKNOWLEDGED"
OUTCOME_PAPER_ACKNOWLEDGED: Final[str] = "PAPER_ACKNOWLEDGED"


class ExecutionHandoffDeniedError(PermissionError):
    """Fail-closed: intake preconditions were not satisfied."""


class ExecutionHandoffIdentityConflictError(RuntimeError):
    """A retried intake call disagrees with the already-persisted handoff
    (including a plan_content_hash mismatch for the same plan reference)."""


class DuplicateExecutionHandoffClaimError(RuntimeError):
    """A handoff has already been consumed/failed and cannot be re-claimed."""


@dataclass(frozen=True)
class ExecutionHandoff:
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
    claim_state: str
    claimed_ts_utc: datetime
    consumed_ts_utc: datetime | None
    outcome_code: str | None
    outcome_detail: str | None
    created_ts_utc: datetime | None = None


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


def _row_to_handoff(row: Any) -> ExecutionHandoff:
    return ExecutionHandoff(
        handoff_id=int(row["executor_execution_handoff_id"]),
        plan_source=str(row["plan_source"]),
        plan_reference_id=str(row["plan_reference_id"]),
        plan_content_hash=str(row["plan_content_hash"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        market=str(row["market"]),
        side=str(row["side"]),
        executor_mode=str(row["executor_mode"]),
        executor_identity=str(row["executor_identity"]),
        runtime_owner=str(row["runtime_owner"]),
        executor_credential_binding_id=int(row["executor_credential_binding_id"]),
        claim_state=str(row["claim_state"]),
        claimed_ts_utc=row["claimed_ts_utc"],
        consumed_ts_utc=row.get("consumed_ts_utc"),
        outcome_code=row.get("outcome_code"),
        outcome_detail=row.get("outcome_detail"),
        created_ts_utc=row.get("created_ts_utc"),
    )


@dataclass
class ExecutionHandoffRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)
    credential_scope_repository: ExecutorCredentialScopeRepository | None = None

    def __post_init__(self) -> None:
        if self.credential_scope_repository is None:
            self.credential_scope_repository = ExecutorCredentialScopeRepository(
                cursor_factory=self.cursor_factory
            )

    def intake(
        self,
        *,
        plan: ApprovedExecutionPlanV1,
        executor_mode: str,
        executor_identity: str,
        runtime_owner: str,
    ) -> ExecutionHandoff:
        """The single authoritative executor-intake entrypoint shared by
        every algorithmic and manual lane. Fails closed on every missing/
        mismatched/unauthorized precondition; never upgrades executor_mode
        and never infers LIVE authority."""
        if executor_mode not in VALID_RUNTIME_MODES:
            raise ExecutionHandoffDeniedError(f"UNKNOWN_EXECUTOR_MODE: {executor_mode}")
        if executor_mode not in ALLOWED_EXECUTOR_INTAKE_MODES:
            raise ExecutionHandoffDeniedError(
                f"EXECUTOR_MODE_NOT_PERMITTED_FOR_INTAKE: {executor_mode}"
            )
        if not executor_identity.strip():
            raise ExecutionHandoffDeniedError("EXECUTOR_IDENTITY_REQUIRED")
        if not runtime_owner.strip():
            raise ExecutionHandoffDeniedError("RUNTIME_OWNER_REQUIRED")

        # Validates plan structure/identity and raises
        # ApprovedExecutionPlanValidationError (a ValueError) on any
        # violation -- deliberately not caught here, this is a caller bug,
        # not a permission denial.
        plan_content_hash = compute_plan_content_hash(plan)

        assert self.credential_scope_repository is not None
        try:
            credential_binding = self.credential_scope_repository.resolve(
                trading_account_id=plan.trading_account_id,
                venue=plan.venue,
                executor_identity=executor_identity,
                runtime_owner=runtime_owner,
            )
        except CredentialScopeDeniedError as exc:
            raise ExecutionHandoffDeniedError(str(exc)) from exc

        return self._insert_idempotent(
            plan=plan,
            plan_content_hash=plan_content_hash,
            executor_mode=executor_mode,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
            credential_binding=credential_binding,
        )

    def _insert_idempotent(
        self,
        *,
        plan: ApprovedExecutionPlanV1,
        plan_content_hash: str,
        executor_mode: str,
        executor_identity: str,
        runtime_owner: str,
        credential_binding: CredentialScopeBinding,
    ) -> ExecutionHandoff:
        claimed_ts_utc = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                INSERT INTO executor_execution_handoff (
                    plan_source, plan_reference_id, plan_content_hash,
                    trading_account_id, venue, market, side, executor_mode,
                    executor_identity, runtime_owner,
                    executor_credential_binding_id, claim_state, claimed_ts_utc
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    executor_execution_handoff_id = LAST_INSERT_ID(executor_execution_handoff_id)
                """,
                [
                    plan.plan_source,
                    plan.plan_reference_id,
                    plan_content_hash,
                    plan.trading_account_id,
                    plan.venue,
                    plan.market,
                    plan.side,
                    executor_mode,
                    executor_identity,
                    runtime_owner,
                    credential_binding.executor_credential_binding_id,
                    CLAIM_STATE_CLAIMED,
                    claimed_ts_utc,
                ],
            )
            handoff_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM executor_execution_handoff "
                "WHERE executor_execution_handoff_id = %s",
                [handoff_id],
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("execution handoff insert did not return a canonical row")
            persisted = _row_to_handoff(row)

        expected = {
            "plan_content_hash": plan_content_hash,
            "executor_mode": executor_mode,
            "executor_identity": executor_identity,
            "runtime_owner": runtime_owner,
            "executor_credential_binding_id": credential_binding.executor_credential_binding_id,
            "trading_account_id": plan.trading_account_id,
            "venue": plan.venue,
            "market": plan.market,
            "side": plan.side,
        }
        for field_name, expected_value in expected.items():
            if getattr(persisted, field_name) != expected_value:
                raise ExecutionHandoffIdentityConflictError(
                    f"canonical execution handoff conflicts with retry identity: {field_name} "
                    f"plan_source={plan.plan_source} plan_reference_id={plan.plan_reference_id}"
                )
        return persisted

    def find_by_id(self, handoff_id: int) -> ExecutionHandoff | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM executor_execution_handoff "
                "WHERE executor_execution_handoff_id = %s",
                [handoff_id],
            )
            row = cursor.fetchone()
            return _row_to_handoff(row) if row else None

    def _resolve_claim(
        self,
        handoff_id: int,
        *,
        new_claim_state: str,
        outcome_code: str,
        outcome_detail: str,
    ) -> ExecutionHandoff:
        if new_claim_state not in _TERMINAL_CLAIM_STATES:
            raise ValueError(f"unsupported terminal claim_state: {new_claim_state}")
        resolved_now = utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE executor_execution_handoff
                SET claim_state = %s, consumed_ts_utc = %s,
                    outcome_code = %s, outcome_detail = %s
                WHERE executor_execution_handoff_id = %s
                  AND claim_state = %s
                """,
                [new_claim_state, resolved_now, outcome_code, outcome_detail, handoff_id, CLAIM_STATE_CLAIMED],
            )
            won_claim = cursor.rowcount == 1
            cursor.execute(
                "SELECT * FROM executor_execution_handoff "
                "WHERE executor_execution_handoff_id = %s",
                [handoff_id],
            )
            row = cursor.fetchone()

        if not row:
            raise LookupError(f"EXECUTION_HANDOFF_NOT_FOUND: {handoff_id}")
        persisted = _row_to_handoff(row)

        if won_claim:
            return persisted

        # This transaction did not win the CLAIMED -> terminal transition.
        # A same-outcome retry against an already-terminal row is treated as
        # an idempotent duplicate; any other observed state is a fail-closed
        # duplicate-claim conflict -- process memory is never the authority,
        # the WHERE claim_state = 'CLAIMED' UPDATE above is.
        if (
            persisted.claim_state == new_claim_state
            and persisted.outcome_code == outcome_code
        ):
            return persisted
        raise DuplicateExecutionHandoffClaimError(
            f"EXECUTION_HANDOFF_ALREADY_CLAIMED: handoff_id={handoff_id} "
            f"claim_state={persisted.claim_state} outcome_code={persisted.outcome_code}"
        )

    def consume(
        self,
        handoff_id: int,
        *,
        outcome_code: str,
        outcome_detail: str = "",
    ) -> ExecutionHandoff:
        return self._resolve_claim(
            handoff_id,
            new_claim_state=CLAIM_STATE_CONSUMED,
            outcome_code=outcome_code,
            outcome_detail=outcome_detail,
        )

    def fail(
        self,
        handoff_id: int,
        *,
        outcome_code: str,
        outcome_detail: str = "",
    ) -> ExecutionHandoff:
        return self._resolve_claim(
            handoff_id,
            new_claim_state=CLAIM_STATE_FAILED,
            outcome_code=outcome_code,
            outcome_detail=outcome_detail,
        )
