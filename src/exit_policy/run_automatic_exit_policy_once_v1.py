"""One-cycle automatic-exit policy runtime entrypoint.

DB-local reads plus append-only audit writes only. No broker calls, no
credential resolution, no executor wiring, no order submission, no LIVE
authority. Terminates at an immutable staged AutomaticExitPlanV1 audit row;
never hands off to execution.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=automatic_exit_gate_v1 (called, not bypassed)
execution_planner=automatic_exit_planner_v1 (called, not bypassed)
executor=none
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.exit_policy.automatic_exit_runtime_contract_v1 import AutomaticExitRuntimeContractError
from src.exit_policy.automatic_exit_runtime_orchestrator_v1 import (
    RUNTIME_VERSION,
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


RUNNER_NAME = "run_automatic_exit_policy_once_v1"
DEFAULT_VENUE = "bitvavo"
OWNERSHIP_REGISTRY_RELATIVE_PATH = Path("deploy/ownership/account_runtime_capability_ownership_v1.json")
OWNERSHIP_CAPABILITY_ID = "AUTOMATIC_EXIT_POLICY_RUNTIME"

LOCK_FORBIDDEN_ROOTS = (Path("/tmp"), Path("/var/tmp"))

SAFETY_MARKERS = (
    "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
    "decision_gate=automatic_exit_gate_v1 execution_planner=automatic_exit_planner_v1 executor=none"
)


class RuntimeOwnershipError(RuntimeError):
    pass


def default_lock_path() -> Path:
    lock_root = Path.home() / ".local" / "state" / "synth" / "runtime" / "locks"
    return lock_root / "automatic-exit-policy-runtime.lock"


def validate_lock_path(lock_path: Path) -> None:
    candidate = lock_path.expanduser()
    for forbidden in LOCK_FORBIDDEN_ROOTS:
        try:
            candidate.relative_to(forbidden)
        except ValueError:
            continue
        raise ValueError(
            f"lock_path={lock_path} resolves under {forbidden}; /tmp and /var/tmp are not "
            "canonical runtime lock locations. Pass --lock-file under the shared home-state lock root"
        )


def verify_runtime_ownership(*, repo_root: Path, expect_owner_host: str) -> None:
    """Fail closed unless the ownership registry currently assigns this runtime to expect_owner_host.

    This is a config-consistency check against the checked-in registry, not a
    live hostname probe: the repository has no capability-authorization
    enforcement wired for account-runtime capabilities (unlike writer
    capabilities, which go through verify_writer_capability_authorization_v1).
    """
    registry_path = repo_root / OWNERSHIP_REGISTRY_RELATIVE_PATH
    try:
        payload = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeOwnershipError(f"OWNERSHIP_REGISTRY_UNREADABLE:{registry_path}") from exc
    capabilities = {entry.get("capability_id"): entry for entry in payload.get("capabilities", [])}
    entry = capabilities.get(OWNERSHIP_CAPABILITY_ID)
    if entry is None:
        raise RuntimeOwnershipError(f"OWNERSHIP_CAPABILITY_MISSING:{OWNERSHIP_CAPABILITY_ID}")
    owner_host = entry.get("owner_host")
    if owner_host != expect_owner_host:
        raise RuntimeOwnershipError(
            f"OWNERSHIP_HOST_MISMATCH:expected={expect_owner_host}:registry={owner_host}"
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
            "items_failed": self.items_failed,
            "audit_rows_inserted": self.audit_rows_inserted,
            "audit_rows_idempotent": self.audit_rows_idempotent,
        }


def run_cycle(conn: Any, *, venue: str, now: datetime) -> CycleSummaryV1:
    """Process every eligible account's positive positions; isolate item failures."""
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
            elif outcome.planner_state == "STAGED":
                summary.items_staged += 1
            elif outcome.planner_state == "REJECTED":
                summary.items_planner_rejected += 1
            elif outcome.gate_state is not None and outcome.gate_state != "APPROVED":
                summary.items_denied += 1
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-cycle automatic-exit policy runtime.")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expect-owner-host", default="gurkdb")
    parser.add_argument("--lock-file", type=Path, default=None)
    parser.add_argument("--skip-ownership-check", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    started_ts = datetime.now(UTC)
    print(f"STARTED runner={RUNNER_NAME} venue={args.venue} mode=one_cycle worker_count=1 started_ts_utc={started_ts.isoformat()}", flush=True)
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
            except Exception as exc:  # DB unavailable is a cycle-global failure.
                print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr, flush=True)
                return 1
            try:
                now = datetime.now(UTC)
                summary = run_cycle(conn, venue=args.venue, now=now)
            except Exception as exc:  # Unexpected cycle-global failure: schema drift, etc.
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
