"""One-cycle Issue #399 Phase 4 automatic BUY runtime entrypoint.

DB-local runtime-input reads plus append-only audit writes only. No executor,
broker, credential, order submission, service/timer activation, or LIVE
behavior is present.
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
from src.entry_policy.automatic_buy_runtime_audit_writer_v1 import (
    AutomaticBuyIdempotencyPayloadConflictError,
)
from src.entry_policy.automatic_buy_runtime_contract_v1 import AutomaticBuyRuntimeContractError
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import evaluate_automatic_buy_runtime_item_v1
from src.entry_policy.automatic_buy_runtime_repository_v1 import (
    AutomaticBuyRuntimeRepositoryError,
    build_runtime_item_v1,
    load_ready_runtime_inputs_v1,
)


RUNNER_NAME = "run_automatic_buy_policy_once_v1"
DEFAULT_VENUE = "bitvavo"
OWNERSHIP_REGISTRY_RELATIVE_PATH = Path("deploy/ownership/account_runtime_capability_ownership_v1.json")
OWNERSHIP_CAPABILITY_ID = "AUTOMATIC_BUY_POLICY_RUNTIME"
LOCK_FORBIDDEN_ROOTS = (Path("/tmp"), Path("/var/tmp"))

SAFETY_MARKERS = (
    "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
    "decision_gate=automatic_buy_gate_v1 execution_planner=automatic_buy_planner_v1 executor=none"
)


class RuntimeOwnershipError(RuntimeError):
    pass


def default_lock_path() -> Path:
    return Path.home() / ".local" / "state" / "synth" / "runtime" / "locks" / "automatic-buy-policy-runtime.lock"


def validate_lock_path(lock_path: Path) -> None:
    candidate = lock_path.expanduser()
    for forbidden in LOCK_FORBIDDEN_ROOTS:
        try:
            candidate.relative_to(forbidden)
        except ValueError:
            continue
        raise ValueError(f"lock_path={lock_path} resolves under forbidden runtime lock root {forbidden}")


def verify_runtime_ownership(*, repo_root: Path, expect_owner_host: str) -> None:
    registry_path = repo_root / OWNERSHIP_REGISTRY_RELATIVE_PATH
    try:
        payload = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeOwnershipError(f"OWNERSHIP_REGISTRY_UNREADABLE:{registry_path}") from exc
    capabilities = {entry.get("capability_id"): entry for entry in payload.get("capabilities", [])}
    entry = capabilities.get(OWNERSHIP_CAPABILITY_ID)
    if entry is None:
        raise RuntimeOwnershipError(f"OWNERSHIP_CAPABILITY_MISSING:{OWNERSHIP_CAPABILITY_ID}")
    if entry.get("owner_host") != expect_owner_host:
        raise RuntimeOwnershipError(
            f"OWNERSHIP_HOST_MISMATCH:expected={expect_owner_host}:registry={entry.get('owner_host')}"
        )


@dataclass
class CycleSummaryV1:
    inputs_considered: int = 0
    items_no_action: int = 0
    items_non_actionable: int = 0
    items_denied: int = 0
    items_planner_rejected: int = 0
    items_staged: int = 0
    items_failed: int = 0
    audit_rows_inserted: int = 0
    audit_rows_idempotent: int = 0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "inputs_considered": self.inputs_considered,
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
    summary = CycleSummaryV1()
    runtime_inputs = load_ready_runtime_inputs_v1(conn, venue=venue)
    for runtime_input in runtime_inputs:
        summary.inputs_considered += 1
        try:
            item = build_runtime_item_v1(conn, runtime_input=runtime_input, evaluation_ts_utc=now)
            outcome = evaluate_automatic_buy_runtime_item_v1(conn, item=item, evaluation_ts_utc=now)
            conn.commit()
        except (
            AutomaticBuyRuntimeRepositoryError,
            AutomaticBuyRuntimeContractError,
            AutomaticBuyIdempotencyPayloadConflictError,
        ) as exc:
            conn.rollback()
            summary.items_failed += 1
            summary.failures.append(
                "ITEM_FAILED "
                f"runtime_input_id={runtime_input.automatic_buy_runtime_input_id} "
                f"trading_account_id={runtime_input.trading_account_id} "
                f"market={runtime_input.market} reason={exc.args[0] if exc.args else exc}"
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
    parser = argparse.ArgumentParser(description="One-cycle automatic BUY policy runtime.")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expect-owner-host", default="gurkdb")
    parser.add_argument("--lock-file", type=Path, default=None)
    parser.add_argument("--skip-ownership-check", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    started_ts = datetime.now(UTC)
    print(f"STARTED runner={RUNNER_NAME} venue={args.venue} mode=one_cycle worker_count=1", flush=True)
    print(SAFETY_MARKERS, flush=True)
    if not args.skip_ownership_check:
        try:
            verify_runtime_ownership(repo_root=args.repo_root, expect_owner_host=args.expect_owner_host)
        except RuntimeOwnershipError as exc:
            print(f"FAILED runner={RUNNER_NAME} result=ownership_mismatch detail={exc}", file=sys.stderr)
            return 1

    lock_path = args.lock_file or default_lock_path()
    validate_lock_path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"FAILED runner={RUNNER_NAME} result=lock_unavailable", file=sys.stderr)
            return 1
        try:
            try:
                conn = get_db_connection()
            except Exception as exc:
                print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr)
                return 1
            try:
                summary = run_cycle(conn, venue=args.venue, now=datetime.now(UTC))
            except Exception as exc:
                conn.rollback()
                print(f"FAILED runner={RUNNER_NAME} result=cycle_failed detail={exc}", file=sys.stderr)
                return 1
            finally:
                conn.close()
            for failure in summary.failures:
                print(failure, file=sys.stderr)
            finished_ts = datetime.now(UTC)
            print(
                f"FINISHED runner={RUNNER_NAME} venue={args.venue} result=ok "
                f"elapsed_seconds={(finished_ts - started_ts).total_seconds():.3f} "
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
