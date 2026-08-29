"""Operator CLI for Issue #584 TRADE_EXECUTION credential validation.

``--check`` is metadata-only and performs no broker call. ``--validate`` is an
explicit operator action that may perform exactly the existing two read-only
Bitvavo validation calls after all static credential checks pass.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from src.account_provisioning.bitvavo_credential_validator_v1 import (
    RealBitvavoCredentialValidator,
)
from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.trade_execution_credential_revalidation_v1 import (
    RESULT_BLOCKED,
    TradeExecutionCredentialRevalidationServiceV1,
    check_trade_execution_credential_validation_v1,
)
from src.common.db import get_db_connection


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or revalidate one existing Bitvavo TRADE_EXECUTION credential."
    )
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--venue", default="bitvavo", choices=("bitvavo",))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Read-only metadata check.")
    mode.add_argument(
        "--validate",
        action="store_true",
        help="Run the explicit read-only broker validation probe and persist its result.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check:
        result = check_trade_execution_credential_validation_v1(
            trading_account_id=args.trading_account_id,
            venue=args.venue,
            conn_factory=get_db_connection,
        )
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        print("broker_writes=0\norder_submission=0\nlive_orders=0")
        return 1 if result.check_state == "BLOCKED" else 0

    try:
        _, master_key_bytes = load_master_key_from_env()
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "result": RESULT_BLOCKED,
                    "safe_error_code": str(exc).split(":", 1)[0],
                    "trading_account_id": args.trading_account_id,
                    "venue": args.venue,
                },
                sort_keys=True,
            )
        )
        print("broker_private_calls=0\nbroker_writes=0\norder_submission=0\nlive_orders=0")
        return 2

    service = TradeExecutionCredentialRevalidationServiceV1(
        master_key_bytes=master_key_bytes,
        validator=RealBitvavoCredentialValidator(),
        conn_factory=get_db_connection,
    )
    result = service.revalidate(
        trading_account_id=args.trading_account_id,
        venue=args.venue,
    )
    print(json.dumps(asdict(result), sort_keys=True, default=str))
    print(
        f"broker_private_calls={result.broker_private_calls}\n"
        "broker_writes=0\norder_submission=0\nlive_orders=0"
    )
    return 1 if result.result == RESULT_BLOCKED else 0


if __name__ == "__main__":
    raise SystemExit(main())
