"""Explicit operator command: provision a LIVE execution trading_account row.

Scope: the ``trading_account`` row only. Does not provision credentials,
executor bindings, decision-gate LIVE permission, kill-switch state, or
runtime capability activation -- those are separate, later steps.

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

from src.account_provisioning.live_execution_trading_account_provisioning_v1 import (
    BITVAVO_VENUE,
    LiveExecutionTradingAccountProvisioningError,
    provision_live_execution_trading_account,
)
from src.common.db import get_db_connection


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision (or verify) a canonical LIVE execution trading_account row."
    )
    parser.add_argument("--account-code", required=True)
    parser.add_argument(
        "--source-trading-account-id",
        type=int,
        required=True,
        help="trading_account_id of the paired live_readonly snapshot-source account.",
    )
    parser.add_argument("--venue", default=BITVAVO_VENUE, choices=(BITVAVO_VENUE,))
    parser.add_argument(
        "--description",
        default=None,
        help="Defaults to the canonical description referencing --source-trading-account-id.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Read-only: resolve and report, never mutate.")
    mode.add_argument("--apply", action="store_true", help="Explicit mutation: insert the row if absent.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = provision_live_execution_trading_account(
            account_code=args.account_code,
            venue=args.venue,
            source_trading_account_id=args.source_trading_account_id,
            description=args.description,
            apply=args.apply,
            conn_factory=get_db_connection,
        )
    except LiveExecutionTradingAccountProvisioningError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2

    print(f"MODE={'APPLY' if args.apply else 'CHECK'}")
    print(f"STATUS={result.status}")
    print(f"ACCOUNT_CODE={result.account_code}")
    print(f"SOURCE_TRADING_ACCOUNT_ID={result.source_trading_account_id}")
    print(f"TRADING_ACCOUNT_ID={result.trading_account_id}")
    print(f"CREATED={result.created}")
    print(
        "broker_private_calls=0\nbroker_writes=0\norder_submission=0\nlive_orders=0\n"
        "credential_mutation=0\nlive_permission_mutation=0\nkill_switch_mutation=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
