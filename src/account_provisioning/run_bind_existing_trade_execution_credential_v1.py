"""Operator CLI for checking/applying an existing TRADE_EXECUTION binding.

No broker secrets, broker calls, credential mutation, runtime activation, or order writes.
"""
from __future__ import annotations

import argparse
import sys

from src.account_provisioning.existing_trade_execution_credential_binding_v1 import (
    bind_existing_trade_execution_credential,
)
from src.account_provisioning.trade_execution_provisioning_v1 import (
    SUPPORTED_EXECUTOR_BINDING_TUPLES,
)
from src.common.db import get_db_connection


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or explicitly apply an existing validated TRADE_EXECUTION credential binding. "
            "Never prompts for broker secrets."
        )
    )
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--trading-account-credential-id", type=int, required=True)
    parser.add_argument("--executor-identity", required=True)
    parser.add_argument("--runtime-owner", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only eligibility/binding check")
    mode.add_argument("--apply", action="store_true", help="Insert missing binding if eligible")
    args = parser.parse_args(argv)
    if not args.check and not args.apply:
        args.check = True
    if (args.executor_identity, args.runtime_owner) not in SUPPORTED_EXECUTOR_BINDING_TUPLES:
        parser.error(
            f"unsupported --executor-identity/--runtime-owner pair "
            f"({args.executor_identity!r}, {args.runtime_owner!r}); "
            f"must be one of {sorted(SUPPORTED_EXECUTOR_BINDING_TUPLES)}"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = bind_existing_trade_execution_credential(
            trading_account_id=args.trading_account_id,
            trading_account_credential_id=args.trading_account_credential_id,
            executor_identity=args.executor_identity,
            runtime_owner=args.runtime_owner,
            conn_factory=get_db_connection,
            apply=bool(args.apply),
        )
    except ValueError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2
    print(f"MODE={'APPLY' if args.apply else 'CHECK'}")
    print(f"TRADE_EXECUTION_CREDENTIAL_ID={result.trading_account_credential_id}")
    print(f"EXECUTOR_CREDENTIAL_BINDING_ID={result.executor_credential_binding_id}")
    print(f"EXECUTOR_IDENTITY={result.executor_identity}")
    print(f"RUNTIME_OWNER={result.runtime_owner}")
    print(f"VENUE={result.venue}")
    print(f"BINDING_EXISTS={int(result.binding_exists)}")
    print(f"CREATED_BINDING={int(result.created_binding)}")
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("withdrawal_calls=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
