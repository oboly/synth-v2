"""
run_migrate_credential_to_db_v1 — Migrate a legacy profile-env credential to encrypted DB storage.

Reads API key + secret interactively via getpass (never from args, env, or files).
Encrypts the credential using the same AESGCM-256 path as account provisioning.
Inserts into trading_account_credential for the profile's linked trading account.

Prerequisites:
  1. app_profile row exists for the profile.
  2. app_profile_trading_account_link row is ACTIVE + is_primary=1 for the profile+venue.
     If missing: run run_app_profile_trading_account_link_v1 first.
  3. SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY is set (same key as provisioning service).
  4. No ACTIVE credential already exists for the account+venue (refuses to duplicate).

After successful migration:
  Remove the systemd drop-in that forces profile-env credential source.
  The service will then use the default credential_source=db path.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import UTC, datetime

from src.account.linked_account_resolver_v1 import resolve_primary_linked_account
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
    load_master_key_from_env,
)
from src.account_provisioning.credential_repository_v1 import (
    CREDENTIAL_KIND_API_KEY_SECRET,
    CredentialRepository,
)
from src.common.db import get_db_connection

RUNNER_NAME = "run_migrate_credential_to_db_v1"
RUNNER_VERSION = "0.1"
_DEFAULT_VENUE = "bitvavo"


def _prompt_secret(label: str) -> str:
    """Read a secret via getpass. Fails closed on blank input."""
    value = getpass.getpass(f"{label}: ")
    if not value or not value.strip():
        raise ValueError(f"BLANK_INPUT: {label} must not be empty")
    return value


def migrate_credential_to_db(
    *,
    profile_code: str,
    venue: str,
    api_key: str,
    api_secret: str,
    master_key_version: str,
    master_key_bytes: bytes,
    conn_factory,
    cred_repo_factory=CredentialRepository,
    now_utc: datetime | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Core migration logic. Testable without getpass or DB side-effects when dry_run=True.

    Returns a result dict with keys:
      ok, account_code, trading_account_id, venue, fingerprint_prefix, error_code
    """
    now = now_utc or datetime.now(UTC)
    conn = conn_factory()
    try:
        identity = resolve_primary_linked_account(conn, profile_code=profile_code, venue=venue)
    except ValueError as exc:
        conn.close()
        return {"ok": False, "error_code": str(exc)}

    trading_account_id = identity.trading_account_id
    account_code = identity.account_code

    cred_repo = cred_repo_factory(conn)
    existing = cred_repo.load_active_encrypted_credential(
        trading_account_id=trading_account_id,
        venue=venue,
    )
    if existing is not None:
        conn.close()
        return {
            "ok": False,
            "error_code": f"ACTIVE_CREDENTIAL_EXISTS: trading_account_id={trading_account_id} venue={venue!r}",
            "account_code": account_code,
            "trading_account_id": trading_account_id,
        }

    plain = PlainBitvavoCredential(venue=venue, api_key=api_key, api_secret=api_secret)
    fingerprint = compute_fingerprint(venue, api_key, master_key_bytes)

    if dry_run:
        conn.close()
        return {
            "ok": True,
            "dry_run": True,
            "account_code": account_code,
            "trading_account_id": trading_account_id,
            "venue": venue,
            "fingerprint_prefix": fingerprint[:8],
        }

    envelope = encrypt_credential(plain, trading_account_id, master_key_version, master_key_bytes)
    try:
        cred_repo.insert_active_credential(
            trading_account_id=trading_account_id,
            venue=venue,
            credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
            encrypted_envelope=envelope.to_json(),
            encryption_algorithm=envelope.alg,
            key_version=envelope.kv,
            credential_fingerprint=fingerprint,
            now_utc=now,
            validation_state="UNVALIDATED",
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "ok": True,
        "dry_run": False,
        "account_code": account_code,
        "trading_account_id": trading_account_id,
        "venue": venue,
        "fingerprint_prefix": fingerprint[:8],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate a legacy profile-env Bitvavo credential to encrypted DB storage. "
            "Reads API key and secret interactively. No broker calls. No order submission."
        )
    )
    parser.add_argument("--profile", required=True, help="app_profile.profile_code")
    parser.add_argument("--venue", default=_DEFAULT_VENUE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Verify account link and master key without writing to DB or prompting for credentials",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"STARTED {RUNNER_NAME} version={RUNNER_VERSION}")
    print(f"profile={args.profile} venue={args.venue} dry_run={args.dry_run}")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("decision_gate=none execution_planner=none executor=none")

    try:
        master_key_version, master_key_bytes = load_master_key_from_env()
    except ValueError as exc:
        print(f"[error] master key: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        result = migrate_credential_to_db(
            profile_code=args.profile,
            venue=args.venue,
            api_key="dry-run-placeholder",
            api_secret="dry-run-placeholder",
            master_key_version=master_key_version,
            master_key_bytes=master_key_bytes,
            conn_factory=get_db_connection,
            dry_run=True,
        )
        if not result.get("ok"):
            print(f"[error] {result.get('error_code', 'UNKNOWN')}", file=sys.stderr)
            return 1
        print(f"dry_run=ok account_code={result['account_code']}")
        print(f"trading_account_id={result['trading_account_id']}")
        print(f"venue={result['venue']}")
        print("No DB writes (dry run). Ready to migrate.")
        print(f"FINISHED {RUNNER_NAME}")
        return 0

    print()
    print("Enter Bitvavo API credentials for this account.")
    print("Input is not echoed. Nothing is logged or stored in shell history.")
    print()

    try:
        api_key = _prompt_secret("Bitvavo API key")
        api_secret = _prompt_secret("Bitvavo API secret")
    except (ValueError, KeyboardInterrupt, EOFError) as exc:
        print(f"\n[error] credential input: {exc}", file=sys.stderr)
        return 1

    result = migrate_credential_to_db(
        profile_code=args.profile,
        venue=args.venue,
        api_key=api_key,
        api_secret=api_secret,
        master_key_version=master_key_version,
        master_key_bytes=master_key_bytes,
        conn_factory=get_db_connection,
    )

    if not result.get("ok"):
        print(f"[error] {result.get('error_code', 'UNKNOWN')}", file=sys.stderr)
        return 1

    print()
    print(f"migration=ok account_code={result['account_code']}")
    print(f"trading_account_id={result['trading_account_id']}")
    print(f"venue={result['venue']}")
    print(f"credential_fingerprint_prefix={result['fingerprint_prefix']}...")
    print("validation_state=UNVALIDATED (will be confirmed on first wallet refresh)")
    print()
    print("Next step: remove the systemd credential-source drop-in, then reload and verify.")
    print(f"FINISHED {RUNNER_NAME}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
