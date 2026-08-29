"""Explicit non-live operator command for TRADE_EXECUTION credential and
executor-scoped binding provisioning.

Defaults to the manual-execution tuple (manual_execution_bitvavo_v1 / odroid)
for backward compatibility. `--executor-identity`/`--runtime-owner` must be
passed together and only as one of the canonical reviewed tuples in
`trade_execution_provisioning_v1.SUPPORTED_EXECUTOR_BINDING_TUPLES`.
"""
from __future__ import annotations
import argparse
import getpass
import sys
from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.trade_execution_provisioning_v1 import (
    MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
    MANUAL_EXECUTION_RUNTIME_OWNER,
    SUPPORTED_EXECUTOR_BINDING_TUPLES,
    provision_trade_execution_credential,
    readiness_report,
)
from src.common.db import get_db_connection

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision a scoped Bitvavo TRADE_EXECUTION credential and one executor-scoped binding.")
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--venue", default="bitvavo", choices=("bitvavo",))
    parser.add_argument("--executor-identity", default=MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
                         help="Executor identity to bind (default: manual_execution_bitvavo_v1).")
    parser.add_argument("--runtime-owner", default=MANUAL_EXECUTION_RUNTIME_OWNER,
                         help="Runtime owner host to bind (default: odroid).")
    parser.add_argument("--readiness", action="store_true", help="Report non-secret readiness only.")
    args = parser.parse_args(argv)
    if (args.executor_identity, args.runtime_owner) not in SUPPORTED_EXECUTOR_BINDING_TUPLES:
        parser.error(
            f"unsupported --executor-identity/--runtime-owner pair "
            f"({args.executor_identity!r}, {args.runtime_owner!r}); "
            f"must be one of {sorted(SUPPORTED_EXECUTOR_BINDING_TUPLES)}"
        )
    return args

def _prompt(label: str) -> str:
    value = getpass.getpass(f"{label}: ")
    if not value.strip():
        raise ValueError("BLANK_SECRET_INPUT")
    return value

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.readiness:
        report = readiness_report(trading_account_id=args.trading_account_id, venue=args.venue,
            executor_identity=args.executor_identity, runtime_owner=args.runtime_owner,
            conn_factory=get_db_connection)
        for key, value in report.items(): print(f"{key}={value}")
        return 0
    try:
        key_version, key_bytes = load_master_key_from_env()
        result = provision_trade_execution_credential(trading_account_id=args.trading_account_id, venue=args.venue,
            api_key=_prompt("Bitvavo API key"), api_secret=_prompt("Bitvavo API secret"),
            master_key_version=key_version, master_key_bytes=key_bytes,
            executor_identity=args.executor_identity, runtime_owner=args.runtime_owner,
            conn_factory=get_db_connection)
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        print(f"ERROR={exc}", file=sys.stderr); return 2
    print(f"TRADE_EXECUTION_CREDENTIAL_ID={result.trading_account_credential_id}")
    print(f"EXECUTOR_CREDENTIAL_BINDING_ID={result.executor_credential_binding_id}")
    print(f"EXECUTOR_IDENTITY={result.executor_identity}")
    print(f"RUNTIME_OWNER={result.runtime_owner}")
    print("broker_private_calls=0\nbroker_writes=0\norder_submission=0\nlive_orders=0")
    return 0
if __name__ == "__main__": raise SystemExit(main())
