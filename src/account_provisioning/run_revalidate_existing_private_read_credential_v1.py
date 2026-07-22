"""CLI for canonical revalidation of one existing encrypted binding.

No credential, encrypted envelope, master key, or fingerprint is printed.
This command authorizes private reads only; it has no broker-write path.
"""
from __future__ import annotations

import argparse
from typing import Sequence

from src.account_provisioning.bitvavo_credential_validator_v1 import (
    RealBitvavoCredentialValidator,
)
from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.existing_credential_revalidation_service_v1 import (
    ExistingCredentialRevalidationResult,
    ExistingCredentialRevalidationService,
    RESULT_BLOCKED,
    RESULT_INVALID,
    RESULT_SUCCESS,
    SUPPORTED_VENUE,
)
from src.common.db import get_db_connection

EXIT_SUCCESS = 0
EXIT_INVALID = 2
EXIT_UNAVAILABLE = 3
EXIT_STRUCTURAL_FAILURE = 4


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Revalidate one exact existing ACTIVE db_encrypted "
            "READ_ONLY_PRIVATE Bitvavo credential binding."
        )
    )
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--trading-account-id", type=int)
    identity.add_argument("--account-code")
    identity.add_argument("--profile-code")
    parser.add_argument("--venue", choices=(SUPPORTED_VENUE,), default=SUPPORTED_VENUE)
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    service: ExistingCredentialRevalidationService | None = None,
) -> int:
    args = parse_args(argv)
    if service is None:
        try:
            _key_version, master_key_bytes = load_master_key_from_env()
        except ValueError:
            result = ExistingCredentialRevalidationResult(
                result=RESULT_BLOCKED,
                profile_code=args.profile_code,
                venue=args.venue,
                safe_error_code="MISSING_MASTER_KEY",
            )
            _print_result(result)
            return EXIT_STRUCTURAL_FAILURE
        service = ExistingCredentialRevalidationService(
            master_key_bytes=master_key_bytes,
            validator=RealBitvavoCredentialValidator(),
            conn_factory=get_db_connection,
        )

    try:
        result = service.revalidate(
            trading_account_id=args.trading_account_id,
            account_code=args.account_code,
            profile_code=args.profile_code,
            venue=args.venue,
        )
    except Exception:
        result = ExistingCredentialRevalidationResult(
            result=RESULT_BLOCKED,
            profile_code=args.profile_code,
            venue=args.venue,
            safe_error_code="UNEXPECTED_REVALIDATION_FAILURE",
        )
    _print_result(result)
    if result.result == RESULT_SUCCESS:
        return EXIT_SUCCESS
    if result.result == RESULT_INVALID:
        return EXIT_INVALID
    if result.safe_error_code == "VALIDATION_UNAVAILABLE":
        return EXIT_UNAVAILABLE
    return EXIT_STRUCTURAL_FAILURE


def _print_result(result: ExistingCredentialRevalidationResult) -> None:
    print(f"result={result.result}")
    print(f"trading_account_id={_value(result.trading_account_id)}")
    print(f"account_code={_value(result.account_code)}")
    if result.profile_code is not None:
        print(f"profile_code={result.profile_code}")
    print(f"venue={result.venue}")
    print(
        "trading_account_credential_id="
        f"{_value(result.trading_account_credential_id)}"
    )
    print(f"credential_source={_value(result.credential_source)}")
    print(f"permission_scope={_value(result.permission_scope)}")
    print(
        "previous_validation_state="
        f"{_value(result.previous_validation_state)}"
    )
    print(f"new_validation_state={_value(result.new_validation_state)}")
    print(
        "validated_ts_utc_present="
        f"{str(result.validated_ts_utc_present).lower()}"
    )
    print(f"safe_error_code={_value(result.safe_error_code, none_value='none')}")
    print(f"broker_private_calls={result.broker_private_calls}")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")


def _value(value: object | None, *, none_value: str = "not_available") -> str:
    return none_value if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
