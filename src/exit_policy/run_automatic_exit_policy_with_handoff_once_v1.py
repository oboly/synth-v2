"""Issue #392 Phase 6 blocker A: real runtime wiring to the #206 handoff.

This is the sole composition root that connects the real #392 candidate ->
gate -> planner runtime path to the shared #206 executor handoff
repository. It reuses the existing audit-only orchestrator/repository
modules unchanged and adds exactly one extra step per item: when the
orchestrator reports ``planner_state == STAGED``, the in-memory
``AutomaticExitPlanV1`` it returned in the *same* evaluation cycle
(``RuntimeItemOutcomeV1.plan``) is adapted and handed off through
``automatic_exit_execution_handoff_application_v1``. The append-only
``automatic_exit_evaluation_audit_v1`` table is never read as executor
input; it is written by the orchestrator as audit/replay evidence only, as
before.

This module is the intended import boundary between ``src.exit_policy``
runtime wiring and ``src.executor`` -- unlike
``run_automatic_exit_policy_once_v1.py``, which stays audit-only and is
guarded (see ``tests/test_automatic_exit_runtime_architecture_guards_v1.py``)
against ever importing ``src.executor``.

Executor mode is derived from the account's own ``account_mode``
(paper -> PAPER, live -> LIVE) via
``resolve_automatic_exit_executor_mode_v1``; DRY_RUN is only reachable via
an explicit ``--executor-mode DRY_RUN`` override, never inferred. Reaching
``decision_gate`` APPROVED for account_mode == "live" is not, by itself,
executor operational LIVE authority: ``intake_live_authorized`` remains the
independent operational gate (credential binding, LIVE authority, kill
switch) owned entirely by #206.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=automatic_exit_gate_v1 (called, not bypassed)
execution_planner=automatic_exit_planner_v1 (called, not bypassed)
executor=execution_handoff_v1 (intake / intake_live_authorized only; no submission)
"""
from __future__ import annotations

import argparse
import fcntl
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.execution_planner.automatic_exit_execution_handoff_application_v1 import (
    AutomaticExitExecutorModeError,
    resolve_automatic_exit_executor_mode_v1,
    submit_automatic_exit_plan_to_execution_handoff_v1,
)
from src.executor.execution_handoff_v1 import (
    ALLOWED_EXECUTOR_INTAKE_MODES,
    RUNTIME_MODE_LIVE,
    ExecutionHandoffDeniedError,
    ExecutionHandoffIdentityConflictError,
    ExecutionHandoffRepositoryV1,
)
from src.exit_policy.automatic_exit_runtime_contract_v1 import AutomaticExitRuntimeContractError
from src.exit_policy.automatic_exit_runtime_orchestrator_v1 import (
    evaluate_automatic_exit_runtime_item_v1,
)
from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import IdempotencyPayloadConflictError
from src.exit_policy.automatic_exit_runtime_repository_v1 import (
    AutomaticExitRuntimeRepositoryError,
    build_runtime_item_v1,
    load_eligible_trading_accounts,
    load_latest_complete_account_state_bundle,
    load_positive_positions,
)
from src.exit_policy.run_automatic_exit_policy_once_v1 import (
    RuntimeOwnershipError,
    default_lock_path,
    validate_lock_path,
    verify_runtime_ownership,
)


RUNNER_NAME = "run_automatic_exit_policy_with_handoff_once_v1"
DEFAULT_VENUE = "bitvavo"

SAFETY_MARKERS = (
    "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
    "decision_gate=automatic_exit_gate_v1 execution_planner=automatic_exit_planner_v1 "
    "executor=execution_handoff_v1(intake_only)"
)


@dataclass
class CycleSummaryV1:
    accounts_considered: int = 0
    accounts_skipped_no_evidence: int = 0
    items_considered: int = 0
    items_no_action: int = 0
    items_non_actionable: int = 0
    items_denied: int = 0
    items_planner_rejected: int = 0
    items_staged: int = 0
    items_handed_off: int = 0
    items_handoff_denied: int = 0
    items_failed: int = 0
    audit_rows_inserted: int = 0
    audit_rows_idempotent: int = 0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accounts_considered": self.accounts_considered,
            "accounts_skipped_no_evidence": self.accounts_skipped_no_evidence,
            "items_considered": self.items_considered,
            "items_no_action": self.items_no_action,
            "items_non_actionable": self.items_non_actionable,
            "items_denied": self.items_denied,
            "items_planner_rejected": self.items_planner_rejected,
            "items_staged": self.items_staged,
            "items_handed_off": self.items_handed_off,
            "items_handoff_denied": self.items_handoff_denied,
            "items_failed": self.items_failed,
            "audit_rows_inserted": self.audit_rows_inserted,
            "audit_rows_idempotent": self.audit_rows_idempotent,
        }


def run_cycle_with_handoff(
    conn: Any,
    *,
    venue: str,
    now: datetime,
    executor_identity: str,
    runtime_owner: str,
    handoff_repository: ExecutionHandoffRepositoryV1,
    executor_mode_override: str | None = None,
) -> CycleSummaryV1:
    """Process every eligible account's positive positions; hand off STAGED plans.

    ``executor_mode_override``, when given, must already be one of the
    #206 executor modes and is used verbatim instead of deriving the mode
    from the account's own account_mode -- intended only for an explicit
    DRY_RUN exercise, never for silently promoting a paper/live account.
    """
    summary = CycleSummaryV1()
    accounts = load_eligible_trading_accounts(conn, venue=venue)
    for account in accounts:
        summary.accounts_considered += 1
        try:
            bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=account.trading_account_id, venue=venue, now=now)
            positions = load_positive_positions(conn, bundle=bundle)
        except AutomaticExitRuntimeRepositoryError as exc:
            summary.accounts_skipped_no_evidence += 1
            summary.failures.append(
                f"ACCOUNT_EVIDENCE_FAILED trading_account_id={account.trading_account_id} venue={venue} reason={exc.args[0] if exc.args else exc}"
            )
            continue

        if not positions:
            continue

        if executor_mode_override is not None:
            executor_mode = executor_mode_override
        else:
            try:
                executor_mode = resolve_automatic_exit_executor_mode_v1(account.account_mode)
            except AutomaticExitExecutorModeError as exc:
                summary.accounts_skipped_no_evidence += 1
                summary.failures.append(
                    f"ACCOUNT_EXECUTOR_MODE_UNRESOLVED trading_account_id={account.trading_account_id} "
                    f"venue={venue} reason={exc.reason_code}"
                )
                continue

        for position in positions:
            summary.items_considered += 1
            try:
                item = build_runtime_item_v1(conn, account=account, bundle=bundle, position=position, now=now)
                outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=now)
                conn.commit()
            except (AutomaticExitRuntimeRepositoryError, AutomaticExitRuntimeContractError, IdempotencyPayloadConflictError) as exc:
                conn.rollback()
                summary.items_failed += 1
                summary.failures.append(
                    f"ITEM_FAILED trading_account_id={account.trading_account_id} venue={venue} "
                    f"asset_id={position.asset_id} symbol={position.symbol} reason={exc.args[0] if exc.args else exc}"
                )
                continue

            if outcome.audit_outcome == "inserted":
                summary.audit_rows_inserted += 1
            else:
                summary.audit_rows_idempotent += 1
            if outcome.candidate_state == "NO_ACTION":
                summary.items_no_action += 1
            elif outcome.candidate_state == "NON_ACTIONABLE":
                summary.items_non_actionable += 1
            elif outcome.planner_state == "REJECTED":
                summary.items_planner_rejected += 1
            elif outcome.planner_state == "STAGED":
                summary.items_staged += 1
                assert outcome.plan is not None
                try:
                    submit_automatic_exit_plan_to_execution_handoff_v1(
                        plan=outcome.plan,
                        executor_mode=executor_mode,
                        executor_identity=executor_identity,
                        runtime_owner=runtime_owner,
                        handoff_repository=handoff_repository,
                    )
                    summary.items_handed_off += 1
                except (ExecutionHandoffDeniedError, ExecutionHandoffIdentityConflictError) as exc:
                    summary.items_handoff_denied += 1
                    summary.failures.append(
                        f"HANDOFF_DENIED trading_account_id={account.trading_account_id} venue={venue} "
                        f"asset_id={position.asset_id} symbol={position.symbol} reason={exc}"
                    )
            elif outcome.gate_state is not None and outcome.gate_state != "APPROVED":
                summary.items_denied += 1
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-cycle automatic-exit policy runtime, wired to the shared #206 executor handoff intake."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expect-owner-host", default="gurkdb")
    parser.add_argument("--lock-file", type=Path, default=None)
    parser.add_argument("--skip-ownership-check", action="store_true")
    parser.add_argument("--executor-identity", required=True)
    parser.add_argument("--runtime-owner", required=True)
    parser.add_argument(
        "--executor-mode",
        choices=sorted(ALLOWED_EXECUTOR_INTAKE_MODES | {RUNTIME_MODE_LIVE}),
        default=None,
        help="Override the executor mode instead of deriving it from account_mode. "
        "Intended for an explicit DRY_RUN exercise only.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    started_ts = datetime.now(UTC)
    print(
        f"STARTED runner={RUNNER_NAME} venue={args.venue} mode=one_cycle worker_count=1 "
        f"executor_identity={args.executor_identity} runtime_owner={args.runtime_owner} "
        f"executor_mode_override={args.executor_mode} started_ts_utc={started_ts.isoformat()}",
        flush=True,
    )
    print(SAFETY_MARKERS, flush=True)

    if not args.skip_ownership_check:
        try:
            verify_runtime_ownership(repo_root=args.repo_root, expect_owner_host=args.expect_owner_host)
        except RuntimeOwnershipError as exc:
            print(f"FAILED runner={RUNNER_NAME} result=ownership_mismatch detail={exc}", file=sys.stderr, flush=True)
            return 1

    lock_path = args.lock_file
    if lock_path is None:
        lock_path = default_lock_path()
        validate_lock_path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"FAILED runner={RUNNER_NAME} result=lock_unavailable", file=sys.stderr, flush=True)
            return 1
        try:
            try:
                conn = get_db_connection()
            except Exception as exc:
                print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr, flush=True)
                return 1
            try:
                now = datetime.now(UTC)
                handoff_repository = ExecutionHandoffRepositoryV1()
                summary = run_cycle_with_handoff(
                    conn,
                    venue=args.venue,
                    now=now,
                    executor_identity=args.executor_identity,
                    runtime_owner=args.runtime_owner,
                    handoff_repository=handoff_repository,
                    executor_mode_override=args.executor_mode,
                )
            except Exception as exc:
                conn.rollback()
                print(f"FAILED runner={RUNNER_NAME} result=cycle_failed detail={exc}", file=sys.stderr, flush=True)
                return 1
            finally:
                conn.close()

            for failure in summary.failures:
                print(failure, file=sys.stderr, flush=True)

            finished_ts = datetime.now(UTC)
            print(
                f"FINISHED runner={RUNNER_NAME} venue={args.venue} result=ok "
                f"finished_ts_utc={finished_ts.isoformat()} elapsed_seconds={(finished_ts - started_ts).total_seconds():.3f} "
                + " ".join(f"{key}={value}" for key, value in summary.as_dict().items()),
                flush=True,
            )
            return 0
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
