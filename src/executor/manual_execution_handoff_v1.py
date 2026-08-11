"""
manual_execution_handoff_v1 — the one explicit immutable executor handoff
identity for a decision_gate-approved, execution_planner-snapshotted manual
execution plan (Issue #206).

Layer: executor intake boundary, downstream of decision_gate and
execution_planner, upstream of any future broker-order-handling executor.

Target architecture (see AGENTS.md):

    manual execution request
        -> decision_gate approval
        -> execution_planner immutable plan snapshot
        -> explicit executor handoff              <- this module
        -> executor
        -> broker orders later

ExecutorHandoffRepository.intake() is the single authoritative entrypoint
that turns one persisted, decision_gate-approved
ManualExecutionPlanSnapshot (src.execution_planner.manual_execution_plan_snapshot_v1)
into one immutable manual_execution_executor_handoff row
(db/migrations/20260812_manual_execution_executor_handoff_v1.sql). It fails
closed unless: the canonical request exists and is PLANNED; the canonical
approval exists and is APPROVED; the immutable plan snapshot exists;
account/venue/market/side identities match across all three; the executor
mode is DRY_RUN or PAPER (LIVE_DISABLED and any unknown mode are always
denied at intake, never inferred); and a deny-by-default TRADE_EXECUTION
credential scope is bound to the exact
(trading_account_id, venue, executor_identity, runtime_owner) tuple — see
src.executor.manual_execution_credential_scope_v1.

Single-writer/duplicate protection: the DB UNIQUE KEY on
manual_execution_plan_snapshot_id is the authority for "one handoff per
snapshot" — intake() is an idempotent insert-and-return against that key,
never an application-level read-then-insert race. Consumption
(claim_state CLAIMED -> CONSUMED | FAILED) is a single conditional UPDATE
guarded by ``WHERE claim_state = 'CLAIMED'``; only the transaction whose
UPDATE actually matches a row (cursor.rowcount == 1) has claimed
consumption authority. A second concurrent attempt observes rowcount == 0
and is resolved idempotently or fails closed — process memory is never the
authority.

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

from src.decision_gate.manual_execution_approval_v1 import (
    APPROVAL_STATE_APPROVED,
    resolve_persisted_manual_execution_authority,
)
from src.execution_planner.manual_execution_plan_snapshot_v1 import (
    ManualExecutionPlanSnapshot,
    ManualExecutionPlanSnapshotRepository,
)
from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
)
from src.manual_execution.manual_execution_request_v1 import (
    MODE_PAPER,
    REQUEST_STATE_PLANNED,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock


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


class ExecutorHandoffDeniedError(PermissionError):
    """Fail-closed: intake preconditions were not satisfied."""


class ExecutorHandoffIdentityConflictError(RuntimeError):
    """A retried intake call disagrees with the already-persisted handoff."""


class DuplicateExecutorHandoffClaimError(RuntimeError):
    """A handoff has already been consumed/failed and cannot be re-claimed."""


@dataclass(frozen=True)
class ManualExecutionExecutorHandoff:
    handoff_id: int | None
    request_id: int
    approval_id: int
    plan_snapshot_id: int
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


def _row_to_handoff(row: Any) -> ManualExecutionExecutorHandoff:
    return ManualExecutionExecutorHandoff(
        handoff_id=int(row["manual_execution_executor_handoff_id"]),
        request_id=int(row["manual_execution_request_id"]),
        approval_id=int(row["manual_execution_approval_id"]),
        plan_snapshot_id=int(row["manual_execution_plan_snapshot_id"]),
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


def _validate_identity_bindings(
    *,
    plan_snapshot: ManualExecutionPlanSnapshot,
    request: Any,
    approval: Any,
) -> None:
    """Pure fail-closed cross-check: request/approval/plan-snapshot identity
    must agree on account, venue, market, and side before a handoff may be
    created. No DB access."""
    if plan_snapshot.request_id != request.request_id:
        raise ExecutorHandoffDeniedError("PLAN_SNAPSHOT_REQUEST_MISMATCH")
    if plan_snapshot.approval_id != approval.approval_id:
        raise ExecutorHandoffDeniedError("PLAN_SNAPSHOT_APPROVAL_MISMATCH")
    if not (
        plan_snapshot.trading_account_id
        == request.trading_account_id
        == approval.trading_account_id
    ):
        raise ExecutorHandoffDeniedError("TRADING_ACCOUNT_ID_MISMATCH")
    if request.venue != approval.venue:
        raise ExecutorHandoffDeniedError("VENUE_MISMATCH")
    expected_market = f"{request.base_asset}-{request.quote_asset}"
    if plan_snapshot.market != expected_market:
        raise ExecutorHandoffDeniedError("MARKET_MISMATCH")
    if not (plan_snapshot.side == request.side == approval.side == "SELL"):
        raise ExecutorHandoffDeniedError("SIDE_MISMATCH")
    if request.mode != MODE_PAPER:
        raise ExecutorHandoffDeniedError("LIVE_TRADING_NOT_GRANTED")
    if request.request_state != REQUEST_STATE_PLANNED:
        raise ExecutorHandoffDeniedError(f"REQUEST_NOT_PLANNED: {request.request_state}")
    if approval.approval_state != APPROVAL_STATE_APPROVED:
        raise ExecutorHandoffDeniedError(f"APPROVAL_NOT_APPROVED: {approval.approval_state}")


@dataclass
class ExecutorHandoffRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)
    plan_snapshot_repository: ManualExecutionPlanSnapshotRepository | None = None
    credential_scope_repository: ExecutorCredentialScopeRepository | None = None

    def __post_init__(self) -> None:
        if self.plan_snapshot_repository is None:
            self.plan_snapshot_repository = ManualExecutionPlanSnapshotRepository(
                cursor_factory=self.cursor_factory
            )
        if self.credential_scope_repository is None:
            self.credential_scope_repository = ExecutorCredentialScopeRepository(
                cursor_factory=self.cursor_factory
            )

    def intake(
        self,
        *,
        plan_snapshot_id: int,
        executor_mode: str,
        executor_identity: str,
        runtime_owner: str,
    ) -> ManualExecutionExecutorHandoff:
        """The single authoritative executor-intake entrypoint. Fails closed
        on every missing/mismatched/unauthorized precondition; never
        upgrades executor_mode and never infers LIVE authority."""
        if executor_mode not in VALID_RUNTIME_MODES:
            raise ExecutorHandoffDeniedError(f"UNKNOWN_EXECUTOR_MODE: {executor_mode}")
        if executor_mode not in ALLOWED_EXECUTOR_INTAKE_MODES:
            raise ExecutorHandoffDeniedError(
                f"EXECUTOR_MODE_NOT_PERMITTED_FOR_INTAKE: {executor_mode}"
            )
        if not executor_identity.strip():
            raise ExecutorHandoffDeniedError("EXECUTOR_IDENTITY_REQUIRED")
        if not runtime_owner.strip():
            raise ExecutorHandoffDeniedError("RUNTIME_OWNER_REQUIRED")

        assert self.plan_snapshot_repository is not None
        plan_snapshot = self.plan_snapshot_repository.find_by_id(plan_snapshot_id)
        if plan_snapshot is None:
            raise ExecutorHandoffDeniedError(f"PLAN_SNAPSHOT_NOT_FOUND: {plan_snapshot_id}")

        authority = resolve_persisted_manual_execution_authority(
            request_id=plan_snapshot.request_id,
            approval_id=plan_snapshot.approval_id,
        )
        _validate_identity_bindings(
            plan_snapshot=plan_snapshot,
            request=authority.request,
            approval=authority.approval,
        )

        assert self.credential_scope_repository is not None
        try:
            credential_binding = self.credential_scope_repository.resolve(
                trading_account_id=plan_snapshot.trading_account_id,
                venue=authority.request.venue,
                executor_identity=executor_identity,
                runtime_owner=runtime_owner,
            )
        except CredentialScopeDeniedError as exc:
            raise ExecutorHandoffDeniedError(str(exc)) from exc

        return self._insert_idempotent(
            plan_snapshot=plan_snapshot,
            request=authority.request,
            executor_mode=executor_mode,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
            credential_binding=credential_binding,
        )

    def _insert_idempotent(
        self,
        *,
        plan_snapshot: ManualExecutionPlanSnapshot,
        request: Any,
        executor_mode: str,
        executor_identity: str,
        runtime_owner: str,
        credential_binding: CredentialScopeBinding,
    ) -> ManualExecutionExecutorHandoff:
        claimed_ts_utc = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                INSERT INTO manual_execution_executor_handoff (
                    manual_execution_request_id, manual_execution_approval_id,
                    manual_execution_plan_snapshot_id, trading_account_id, venue,
                    market, side, executor_mode, executor_identity, runtime_owner,
                    executor_credential_binding_id, claim_state, claimed_ts_utc
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    manual_execution_executor_handoff_id = LAST_INSERT_ID(manual_execution_executor_handoff_id)
                """,
                [
                    plan_snapshot.request_id,
                    plan_snapshot.approval_id,
                    plan_snapshot.plan_snapshot_id,
                    plan_snapshot.trading_account_id,
                    request.venue,
                    plan_snapshot.market,
                    plan_snapshot.side,
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
                "SELECT * FROM manual_execution_executor_handoff "
                "WHERE manual_execution_executor_handoff_id = %s",
                [handoff_id],
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("executor handoff insert did not return a canonical row")
            persisted = _row_to_handoff(row)

        expected = {
            "executor_mode": executor_mode,
            "executor_identity": executor_identity,
            "runtime_owner": runtime_owner,
            "executor_credential_binding_id": credential_binding.executor_credential_binding_id,
            "trading_account_id": plan_snapshot.trading_account_id,
            "venue": request.venue,
            "market": plan_snapshot.market,
            "side": plan_snapshot.side,
        }
        for field_name, expected_value in expected.items():
            if getattr(persisted, field_name) != expected_value:
                raise ExecutorHandoffIdentityConflictError(
                    f"canonical executor handoff conflicts with retry identity: {field_name}"
                )
        return persisted

    def find_by_id(self, handoff_id: int) -> ManualExecutionExecutorHandoff | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM manual_execution_executor_handoff "
                "WHERE manual_execution_executor_handoff_id = %s",
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
    ) -> ManualExecutionExecutorHandoff:
        if new_claim_state not in _TERMINAL_CLAIM_STATES:
            raise ValueError(f"unsupported terminal claim_state: {new_claim_state}")
        resolved_now = trusted_clock.utc_now()
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE manual_execution_executor_handoff
                SET claim_state = %s, consumed_ts_utc = %s,
                    outcome_code = %s, outcome_detail = %s
                WHERE manual_execution_executor_handoff_id = %s
                  AND claim_state = %s
                """,
                [new_claim_state, resolved_now, outcome_code, outcome_detail, handoff_id, CLAIM_STATE_CLAIMED],
            )
            won_claim = cursor.rowcount == 1
            cursor.execute(
                "SELECT * FROM manual_execution_executor_handoff "
                "WHERE manual_execution_executor_handoff_id = %s",
                [handoff_id],
            )
            row = cursor.fetchone()

        if not row:
            raise LookupError(f"EXECUTOR_HANDOFF_NOT_FOUND: {handoff_id}")
        persisted = _row_to_handoff(row)

        if won_claim:
            return persisted

        # This transaction did not win the CLAIMED -> terminal transition.
        # A same-outcome retry against an already-terminal row is treated as
        # an idempotent duplicate; any other observed state is a fail-closed
        # duplicate-claim conflict — process memory is never the authority,
        # the WHERE claim_state = 'CLAIMED' UPDATE above is.
        if (
            persisted.claim_state == new_claim_state
            and persisted.outcome_code == outcome_code
        ):
            return persisted
        raise DuplicateExecutorHandoffClaimError(
            f"EXECUTOR_HANDOFF_ALREADY_CLAIMED: handoff_id={handoff_id} "
            f"claim_state={persisted.claim_state} outcome_code={persisted.outcome_code}"
        )

    def consume(
        self,
        handoff_id: int,
        *,
        outcome_code: str,
        outcome_detail: str = "",
    ) -> ManualExecutionExecutorHandoff:
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
    ) -> ManualExecutionExecutorHandoff:
        return self._resolve_claim(
            handoff_id,
            new_claim_state=CLAIM_STATE_FAILED,
            outcome_code=outcome_code,
            outcome_detail=outcome_detail,
        )


def acknowledge_dry_run_or_paper_handoff(
    handoff: ManualExecutionExecutorHandoff,
    repository: ExecutorHandoffRepository,
) -> ManualExecutionExecutorHandoff:
    """Consume one CLAIMED handoff in DRY_RUN/PAPER mode only. Records a
    non-secret audit outcome; places no order and calls no broker."""
    if handoff.executor_mode not in ALLOWED_EXECUTOR_INTAKE_MODES:
        raise ExecutorHandoffDeniedError(
            f"EXECUTOR_MODE_NOT_PERMITTED_FOR_CONSUMPTION: {handoff.executor_mode}"
        )
    outcome_code = (
        OUTCOME_DRY_RUN_ACKNOWLEDGED
        if handoff.executor_mode == RUNTIME_MODE_DRY_RUN
        else OUTCOME_PAPER_ACKNOWLEDGED
    )
    assert handoff.handoff_id is not None
    return repository.consume(
        handoff.handoff_id,
        outcome_code=outcome_code,
        outcome_detail="broker_writes=0;order_submission=0",
    )
