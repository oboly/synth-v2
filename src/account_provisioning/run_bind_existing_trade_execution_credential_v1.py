"""Operator CLI: bind an existing ACTIVE TRADE_EXECUTION credential to one
reviewed executor identity/runtime-owner tuple.

Unlike `run_provision_trade_execution_credential_v1.py`, this command never
prompts for or accepts broker API key/secret input. It only reads existing
`trading_account_credential` metadata and appends/reuses one
`executor_credential_binding` row for the exact requested tuple. The
credential row itself is never mutated.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
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
            "Bind an existing ACTIVE TRADE_EXECUTION credential to one reviewed "
            "executor identity/runtime-owner tuple. Never prompts for broker secrets."
        )
    )
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--trading-account-credential-id", type=int, required=True)
    parser.add_argument("--executor-identity", required=True)
    parser.add_argument("--runtime-owner", required=True)
    args = parser.parse_args(argv)
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
        )
    except ValueError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2
    print(f"TRADE_EXECUTION_CREDENTIAL_ID={result.trading_account_credential_id}")
    print(f"EXECUTOR_CREDENTIAL_BINDING_ID={result.executor_credential_binding_id}")
    print(f"EXECUTOR_IDENTITY={result.executor_identity}")
    print(f"RUNTIME_OWNER={result.runtime_owner}")
    print(f"VENUE={result.venue}")
    print(f"CREATED_BINDING={int(result.created_binding)}")
    print("broker_private_calls=0\nbroker_writes=0\norder_submission=0\nlive_orders=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
