"""Operator-only CLI for issue #589 TRADE_EXECUTION credential rotation."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import getpass
import json
import sys

from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.trade_execution_credential_rotation_v1 import (
    CHECK_READY,
    RESULT_ROTATED,
    check_trade_execution_credential_rotation_v1,
    rotate_trade_execution_credential_v1,
)
from src.common.db import get_db_connection


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or rotate one exact ACTIVE TRADE_EXECUTION credential in place."
    )
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--trading-account-credential-id", type=int, required=True)
    parser.add_argument("--venue", default="bitvavo", choices=("bitvavo",))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def _prompt_secret(label: str) -> str:
    value = getpass.getpass(f"{label}: ")
    if not value.strip():
        raise ValueError("BLANK_SECRET_INPUT")
    return value


def _print_payload(payload: object) -> None:
    print(json.dumps(asdict(payload), sort_keys=True, default=str))
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("withdrawal_calls=0")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.check:
        result = check_trade_execution_credential_rotation_v1(
            trading_account_id=args.trading_account_id,
            trading_account_credential_id=args.trading_account_credential_id,
            venue=args.venue,
            conn_factory=get_db_connection,
        )
        _print_payload(result)
        return 0 if result.check_state == CHECK_READY else 1

    try:
        key_version, key_bytes = load_master_key_from_env()
        api_key = _prompt_secret("Bitvavo API key")
        api_secret = _prompt_secret("Bitvavo API secret")
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2

    result = rotate_trade_execution_credential_v1(
        trading_account_id=args.trading_account_id,
        trading_account_credential_id=args.trading_account_credential_id,
        venue=args.venue,
        api_key=api_key,
        api_secret=api_secret,
        master_key_version=key_version,
        master_key_bytes=key_bytes,
        conn_factory=get_db_connection,
    )
    del api_key
    del api_secret
    del key_bytes
    _print_payload(result)
    return 0 if result.result == RESULT_ROTATED else 1


if __name__ == "__main__":
    raise SystemExit(main())
