"""Issue #588: operator CLI for the canonical automatic-exit LIVE
decision-gate permission grant.

Grants decision-gate LIVE permission only -- never executor operational LIVE
authority, never a credential/binding change, never the kill switch, and
never a broker/order action. All eligibility, idempotency, and conflict
validation happens in ``automatic_exit_live_permission_grant_v1.py``; this
CLI only parses arguments, opens the DB connection, and prints the result.

Modes:
  --check   Read-only. Reports whether a grant would succeed. No DB writes.
  --apply   Performs the append-only grant (or reports ALREADY_GRANTED).

Does NOT grant permission in production as a side effect of running this
file -- it only runs when explicitly invoked with ``--apply`` against a
target database by an operator.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=automatic_exit_live_permission_grant_v1
execution_planner=none
executor=none
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Final

from src.common.db import get_db_connection
from src.decision_gate.automatic_exit_live_permission_contract_v1 import PERMISSION_CONTRACT_VERSION
from src.decision_gate.automatic_exit_live_permission_grant_v1 import (
    CHECK_STATE_ALREADY_GRANTED,
    CHECK_STATE_READY_TO_GRANT,
    AutomaticExitLivePermissionGrantError,
    AutomaticExitLivePermissionGrantRequestV1,
    apply_automatic_exit_live_permission_grant_v1,
    check_automatic_exit_live_permission_grant_v1,
)

RUNNER_NAME: Final[str] = "run_grant_automatic_exit_live_permission_v1"
DEFAULT_SOURCE_PROVENANCE: Final[str] = "operator_cli_grant_v1"
SAFETY_MARKERS: Final[str] = (
    "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
    "credential_mutation=0 kill_switch_mutation=0 executor_live_authority_grant=0"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Canonical automatic-exit LIVE decision-gate permission grant (Issue #588).",
    )
    parser.add_argument("--trading-account-id", required=True, type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--source-provenance", default=DEFAULT_SOURCE_PROVENANCE)
    parser.add_argument("--permission-version", default=PERMISSION_CONTRACT_VERSION)
    return parser.parse_args(argv)


def _request_from_args(args: argparse.Namespace, *, requested_ts_utc: datetime) -> AutomaticExitLivePermissionGrantRequestV1:
    return AutomaticExitLivePermissionGrantRequestV1(
        trading_account_id=args.trading_account_id,
        requested_ts_utc=requested_ts_utc,
        permission_version=args.permission_version,
        source_provenance=args.source_provenance,
    )


def run(args: argparse.Namespace) -> int:
    mode = "check" if args.check else "apply"
    print(f"STARTED runner={RUNNER_NAME} mode={mode} trading_account_id={args.trading_account_id} worker_count=1", flush=True)
    print(SAFETY_MARKERS, flush=True)

    requested_ts_utc = datetime.now(UTC)
    try:
        conn = get_db_connection()
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr)
        return 1

    try:
        request = _request_from_args(args, requested_ts_utc=requested_ts_utc)
        if args.check:
            result = check_automatic_exit_live_permission_grant_v1(conn, request=request)
            print(f"TRADING_ACCOUNT_ID={result.trading_account_id}")
            print(f"CHECK_STATE={result.check_state}")
            print(f"REASON_CODE={result.reason_code}")
            print(f"EXISTING_PERMISSION_ID={result.existing_permission_id}")
            print(SAFETY_MARKERS)
            if result.check_state in (CHECK_STATE_READY_TO_GRANT, CHECK_STATE_ALREADY_GRANTED):
                print(f"FINISHED runner={RUNNER_NAME} result=ok")
                return 0
            print(f"FINISHED runner={RUNNER_NAME} result=blocked")
            return 1

        try:
            result = apply_automatic_exit_live_permission_grant_v1(conn, request=request)
        except AutomaticExitLivePermissionGrantError as exc:
            conn.rollback()
            print(f"FAILED runner={RUNNER_NAME} result=grant_rejected detail={exc}", file=sys.stderr)
            return 1
        conn.commit()
        print(f"TRADING_ACCOUNT_ID={result.trading_account_id}")
        print(f"PERMISSION_ID={result.permission_id}")
        print(f"IDEMPOTENT={result.idempotent}")
        print(SAFETY_MARKERS)
        print(f"FINISHED runner={RUNNER_NAME} result=ok")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
