"""Explicit non-live operator command for manual-execution credential provisioning."""
from __future__ import annotations
import argparse
import getpass
import sys
from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.trade_execution_provisioning_v1 import provision_trade_execution_credential, readiness_report
from src.common.db import get_db_connection

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision scoped Bitvavo TRADE_EXECUTION credential and Odroid binding.")
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--venue", default="bitvavo", choices=("bitvavo",))
    parser.add_argument("--readiness", action="store_true", help="Report non-secret readiness only.")
    return parser.parse_args(argv)

def _prompt(label: str) -> str:
    value = getpass.getpass(f"{label}: ")
    if not value.strip():
        raise ValueError("BLANK_SECRET_INPUT")
    return value

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.readiness:
        report = readiness_report(trading_account_id=args.trading_account_id, venue=args.venue, conn_factory=get_db_connection)
        for key, value in report.items(): print(f"{key}={value}")
        return 0
    try:
        key_version, key_bytes = load_master_key_from_env()
        result = provision_trade_execution_credential(trading_account_id=args.trading_account_id, venue=args.venue,
            api_key=_prompt("Bitvavo API key"), api_secret=_prompt("Bitvavo API secret"),
            master_key_version=key_version, master_key_bytes=key_bytes, conn_factory=get_db_connection)
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        print(f"ERROR={exc}", file=sys.stderr); return 2
    print(f"TRADE_EXECUTION_CREDENTIAL_ID={result.trading_account_credential_id}")
    print(f"EXECUTOR_CREDENTIAL_BINDING_ID={result.executor_credential_binding_id}")
    print("broker_private_calls=0\nbroker_writes=0\norder_submission=0\nlive_orders=0")
    return 0
if __name__ == "__main__": raise SystemExit(main())
