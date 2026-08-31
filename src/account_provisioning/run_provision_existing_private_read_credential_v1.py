"""Operator-only CLI: attach a new READ_ONLY_PRIVATE credential to an
already-existing, already-enabled trading_account_id + venue.

Never creates/mutates ``trading_account``, never touches
``app_profile_trading_account_link``, and never reads or mutates an existing
TRADE_EXECUTION row. ``--check`` is metadata-only (no decrypt, no broker
calls, no persistence). ``--apply`` is the only mode that prompts for
secrets (hidden echo only), decrypts nothing but encrypts the freshly
prompted secret, validates with the canonical real private-read validator,
and persists only on ``VALID_PRIVATE_READ``.

No API key, API secret, encrypted envelope, master key, or fingerprint is
ever printed or logged.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from typing import Sequence

from src.account_provisioning.bitvavo_credential_validator_v1 import (
    RealBitvavoCredentialValidator,
)
from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.existing_account_private_read_credential_provisioning_v1 import (
    STATUS_ALREADY_PROVISIONED,
    STATUS_BLOCKED,
    STATUS_CREATED,
    STATUS_READY,
    STATUS_VALIDATION_FAILED,
    STATUS_VALIDATION_UNAVAILABLE,
    check_readiness,
    provision_existing_private_read_credential,
)
from src.common.db import get_db_connection

EXIT_SUCCESS = 0
EXIT_BLOCKED = 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Attach a new READ_ONLY_PRIVATE credential to an existing, enabled "
            "trading_account_id + venue. Never prompts for secrets via argv."
        )
    )
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--venue", default="bitvavo", choices=("bitvavo",))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="Metadata-only readiness check (no broker calls)."
    )
    mode.add_argument(
        "--apply", action="store_true", help="Prompt, validate, and persist the new credential."
    )
    args = parser.parse_args(argv)
    if not args.check and not args.apply:
        args.check = True
    return args


def _prompt(label: str) -> str:
    value = getpass.getpass(f"{label}: ")
    if not value.strip():
        raise ValueError("BLANK_SECRET_INPUT")
    return value


def _print_check_safety_markers() -> None:
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("db_mutation=0")


def _print_apply_safety_markers(broker_private_calls: int) -> None:
    print(f"broker_private_calls={broker_private_calls}")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("live_authority_grant=0")
    print("kill_switch_mutation=0")
    print("service_mutation=0")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.check:
        readiness = check_readiness(
            trading_account_id=args.trading_account_id,
            venue=args.venue,
            conn_factory=get_db_connection,
        )
        print(f"STATUS={readiness.status}")
        print(f"TRADING_ACCOUNT_ID={readiness.trading_account_id}")
        print(f"VENUE={readiness.venue}")
        print(f"ACCOUNT_MODE={readiness.account_mode if readiness.account_mode else 'not_available'}")
        print(
            "TRADING_ACCOUNT_CREDENTIAL_ID="
            f"{readiness.trading_account_credential_id if readiness.trading_account_credential_id is not None else 'not_available'}"
        )
        print(f"BLOCKER={readiness.blocker if readiness.blocker else 'none'}")
        _print_check_safety_markers()
        return EXIT_SUCCESS if readiness.status != STATUS_BLOCKED else EXIT_BLOCKED

    # --apply: pre-check readiness before ever prompting for secrets.
    readiness = check_readiness(
        trading_account_id=args.trading_account_id,
        venue=args.venue,
        conn_factory=get_db_connection,
    )
    if readiness.status == STATUS_BLOCKED:
        print(f"ERROR={readiness.blocker}", file=sys.stderr)
        return EXIT_BLOCKED
    if readiness.status == STATUS_ALREADY_PROVISIONED:
        print(f"STATUS={STATUS_ALREADY_PROVISIONED}")
        print(f"TRADING_ACCOUNT_ID={readiness.trading_account_id}")
        print(f"VENUE={readiness.venue}")
        print(f"TRADING_ACCOUNT_CREDENTIAL_ID={readiness.trading_account_credential_id}")
        _print_apply_safety_markers(0)
        return EXIT_SUCCESS
    assert readiness.status == STATUS_READY

    try:
        key_version, key_bytes = load_master_key_from_env()
    except ValueError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return EXIT_BLOCKED

    try:
        api_key = _prompt("Bitvavo API key")
        api_secret = _prompt("Bitvavo API secret")
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return EXIT_BLOCKED

    try:
        result = provision_existing_private_read_credential(
            trading_account_id=args.trading_account_id,
            venue=args.venue,
            api_key=api_key,
            api_secret=api_secret,
            master_key_version=key_version,
            master_key_bytes=key_bytes,
            validator=RealBitvavoCredentialValidator(),
            conn_factory=get_db_connection,
        )
    except ValueError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return EXIT_BLOCKED
    finally:
        del api_key, api_secret

    print(f"STATUS={result.status}")
    print(f"TRADING_ACCOUNT_ID={result.trading_account_id}")
    print(f"VENUE={result.venue}")
    print(
        "TRADING_ACCOUNT_CREDENTIAL_ID="
        f"{result.trading_account_credential_id if result.trading_account_credential_id is not None else 'not_available'}"
    )
    print(f"VALIDATION_STATE={result.validation_state if result.validation_state else 'not_available'}")
    print(f"VALIDATED_TS_UTC_PRESENT={str(result.validated_ts_utc_present).lower()}")
    print(f"SAFE_ERROR_CODE={result.safe_error_code if result.safe_error_code else 'none'}")
    _print_apply_safety_markers(result.broker_private_calls)

    if result.status in (STATUS_CREATED, STATUS_ALREADY_PROVISIONED):
        return EXIT_SUCCESS
    assert result.status in (STATUS_VALIDATION_FAILED, STATUS_VALIDATION_UNAVAILABLE)
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
