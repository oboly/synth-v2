from __future__ import annotations

import argparse
import os
from typing import Any

import requests
from dotenv import load_dotenv

from src.account.private_read_credential_resolver_v1 import (
    PrivateReadCredentialResolutionError,
    resolve_private_read_bitvavo_client_from_env,
)
from src.account_provisioning.credential_crypto_v1 import MASTER_KEY_ENV_VAR
from src.common.db import get_db_connection


REPORT_NAME = "broker_balance_readonly_probe_v1"
REPORT_VERSION = "0.3"
DEFAULT_VENUE = "bitvavo"

PRIVATE_READ_PERMISSION_ENV = "SYNTH_BROKER_PRIVATE_READ_PERMISSION"
PRIVATE_READ_PERMISSION_GRANTED_VALUE = "I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA"
BROKER_WRITE_PERMISSION_ENV = "SYNTH_BROKER_WRITE_PERMISSION"
BROKER_WRITE_PERMISSION_GRANTED_VALUE = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"


def env_state(name: str, *, granted_value: str | None = None) -> str:
    value = os.getenv(name)

    if not value:
        return "MISSING"

    if granted_value is not None:
        return "GRANTED" if value == granted_value else "PRESENT_BUT_NOT_GRANTED"

    return "PRESENT"


def print_env_readiness() -> None:
    print("--- broker env readiness, values redacted ---")
    print(f"{MASTER_KEY_ENV_VAR}={env_state(MASTER_KEY_ENV_VAR)}")
    print(f"BITVAVO_REST_URL={env_state('BITVAVO_REST_URL')}")
    print(f"BITVAVO_BASE_URL={env_state('BITVAVO_BASE_URL')}")
    print(
        f"{PRIVATE_READ_PERMISSION_ENV}="
        f"{env_state(PRIVATE_READ_PERMISSION_ENV, granted_value=PRIVATE_READ_PERMISSION_GRANTED_VALUE)}"
    )
    print(
        f"{BROKER_WRITE_PERMISSION_ENV}="
        f"{env_state(BROKER_WRITE_PERMISSION_ENV, granted_value=BROKER_WRITE_PERMISSION_GRANTED_VALUE)}"
    )


def safe_error_payload(response: requests.Response | None) -> dict[str, Any]:
    if response is None:
        return {
            "status_code": None,
            "error_code": None,
            "error": "NO_RESPONSE_OBJECT",
            "message": None,
        }

    status_code = response.status_code

    try:
        payload = response.json()
    except Exception:
        return {
            "status_code": status_code,
            "error_code": None,
            "error": "NON_JSON_ERROR_RESPONSE",
            "message": response.text[:300],
        }

    return {
        "status_code": status_code,
        "error_code": payload.get("errorCode"),
        "error": payload.get("error"),
        "message": payload.get("errorMessage") or payload.get("message"),
    }


def print_balances(balances: list[dict[str, Any]]) -> None:
    print("--- balances ---")

    if not balances:
        print("(no positive balances returned)")
        return

    headers = ["symbol", "available", "inOrder"]
    rows: list[list[str]] = []

    for row in balances:
        rows.append(
            [
                str(row.get("symbol", "")),
                str(row.get("available", "")),
                str(row.get("inOrder", "")),
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)))


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("[INFO] read-only probe; no DB writes; no broker writes; no order submission")

    print_env_readiness()

    if not args.fetch_private_balance:
        print()
        print("[DONE] readiness_only=True private_balance_fetch=False")
        return 0

    print()
    print("--- private balance fetch ---")

    conn = get_db_connection()
    try:
        resolved = resolve_private_read_bitvavo_client_from_env(
            conn,
            trading_account_id=args.trading_account_id,
            account_code=args.account_code,
            profile_code=args.account_profile,
            venue=args.venue,
            timeout_seconds=args.timeout_seconds,
        )
        print(f"trading_account_id={resolved.identity.trading_account_id}")
        print(f"account_code={resolved.identity.account_code}")
        print(f"venue={resolved.identity.venue}")
        print(f"credential_profile_id={resolved.profile.trading_account_credential_id}")
        print(f"credential_fingerprint={resolved.profile.credential_fingerprint}")
        print(f"permission_scope={resolved.profile.permission_scope}")
        print(f"validation_state={resolved.profile.validation_state}")
        client = resolved.client
        balances = client.get_balance(symbol=args.symbol)
    except PrivateReadCredentialResolutionError as exc:
        print(f"[BLOCKED] credential_resolution={exc}")
        print("[DONE] private_balance_fetch=False reason=CREDENTIAL_RESOLUTION_FAILED")
        return 1
    except RuntimeError as exc:
        print(f"[BLOCKED] {exc}")
        print("[DONE] private_balance_fetch=False reason=PRIVATE_READ_PERMISSION_NOT_GRANTED")
        return 0
    except requests.exceptions.HTTPError as exc:
        payload = safe_error_payload(exc.response)
        print("[HTTP_ERROR] Bitvavo private balance request rejected")
        print(f"status_code={payload['status_code']}")
        print(f"error_code={payload['error_code']}")
        print(f"error={payload['error']}")
        print(f"message={payload['message']}")
        print("[DONE] private_balance_fetch=False reason=BITVAVO_HTTP_ERROR")
        return 1
    except requests.exceptions.RequestException as exc:
        print("[NETWORK_ERROR] Bitvavo private balance request failed")
        print(f"error_type={type(exc).__name__}")
        print(f"message={exc}")
        print("[DONE] private_balance_fetch=False reason=NETWORK_ERROR")
        return 1
    finally:
        conn.close()

    print_balances(balances)
    print()
    print("[DONE] private_balance_fetch=True db_writes=0 broker_writes=0 order_submission=0")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    identity = parser.add_mutually_exclusive_group(required=False)
    identity.add_argument("--trading-account-id", type=int, default=None)
    identity.add_argument("--account-code", default=None)
    identity.add_argument("--account-profile", default=None)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--fetch-private-balance", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
