from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Any
from urllib.parse import urlparse
from wsgiref.simple_server import make_server

from src.web.web_auth_http_v1 import build_wsgi_app
from src.web.website_registration_v1 import (
    DEFAULT_PROFILE_TIMEZONE,
    MariaDbWebsiteRegistrationRepository,
    SqliteWebsiteRegistrationRepository,
    WebsiteRegistrationService,
    build_mailer_from_env,
    build_proof_of_human_provider_from_env,
    is_production_env,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8786
MIN_PEPPER_LENGTH = 32
DEFAULT_OUTPUT_ROOT = "/var/www/html/synth"


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the isolated SYNTH website registration HTTP service. "
            "No dashboard access gating, no broker calls, no trading-account provisioning."
        )
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--database", choices=("mariadb", "sqlite"), default="mariadb")
    parser.add_argument("--sqlite-path", default="/tmp/synth_website_registration_v1.sqlite3")
    parser.add_argument("--base-url", default=os.getenv("SYNTH_PUBLIC_BASE_URL", "https://synth.example"))
    parser.add_argument("--display-timezone", default=os.getenv("SYNTH_DEFAULT_PROFILE_TIMEZONE", DEFAULT_PROFILE_TIMEZONE))
    parser.add_argument(
        "--output-root",
        default=os.getenv("SYNTH_WEB_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
        help="Web output root for rendered dashboards (default: /var/www/html/synth).",
    )
    return parser.parse_args(args)


def _build_repository(args: argparse.Namespace):
    if args.database == "sqlite":
        sqlite_path = Path(args.sqlite_path)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(sqlite_path), check_same_thread=False)
        repo = SqliteWebsiteRegistrationRepository(conn)
        repo.create_schema()
        return repo
    return MariaDbWebsiteRegistrationRepository()


def _validate_production_base_url(base_url: str) -> str:
    """
    Validate and normalize SYNTH_PUBLIC_BASE_URL for production CSRF Origin enforcement.
    Accepts only HTTPS scheme + hostname + optional port.
    Rejects path, query, fragment, userinfo, and malformed values.
    Returns normalized origin (no trailing slash).
    Never prints the URL value in error messages.
    """
    if not base_url:
        raise RuntimeError("PRODUCTION_BASE_URL_REQUIRED")
    try:
        parsed = urlparse(base_url)
    except Exception:
        raise RuntimeError("PRODUCTION_BASE_URL_MALFORMED")
    if parsed.scheme != "https":
        raise RuntimeError("PRODUCTION_BASE_URL_MUST_BE_HTTPS")
    if not parsed.hostname:
        raise RuntimeError("PRODUCTION_BASE_URL_MALFORMED")
    if parsed.username or parsed.password:
        raise RuntimeError("PRODUCTION_BASE_URL_USERINFO_FORBIDDEN")
    if parsed.path and parsed.path != "/":
        raise RuntimeError("PRODUCTION_BASE_URL_PATH_FORBIDDEN")
    if parsed.query:
        raise RuntimeError("PRODUCTION_BASE_URL_QUERY_FORBIDDEN")
    if parsed.fragment:
        raise RuntimeError("PRODUCTION_BASE_URL_FRAGMENT_FORBIDDEN")
    port_part = f":{parsed.port}" if parsed.port else ""
    return f"https://{parsed.hostname}{port_part}"


def _validate_production_pepper(env: dict[str, str]) -> str:
    """
    In production, SYNTH_IP_HASH_PEPPER must be set and at least MIN_PEPPER_LENGTH chars.
    Refuses startup if absent or too short. Never prints the pepper value.
    """
    pepper = str(env.get("SYNTH_IP_HASH_PEPPER", "")).strip()
    if not pepper:
        raise RuntimeError("PRODUCTION_IP_HASH_PEPPER_REQUIRED")
    if len(pepper) < MIN_PEPPER_LENGTH:
        raise RuntimeError(
            f"PRODUCTION_IP_HASH_PEPPER_TOO_SHORT (minimum {MIN_PEPPER_LENGTH} characters)"
        )
    return pepper


def _validate_production_config(env: dict[str, str]) -> tuple[object, object]:
    proof_provider = build_proof_of_human_provider_from_env(env)
    proof_probe = proof_provider.validate(response="")
    if not proof_probe.valid and proof_probe.reason in {
        "PROOF_PROVIDER_NOT_CONFIGURED",
        "MOCK_PROOF_PROVIDER_FORBIDDEN",
    }:
        raise RuntimeError(proof_probe.reason)
    mailer = build_mailer_from_env(env)
    return proof_provider, mailer


def _build_connect_bitvavo(args: argparse.Namespace) -> Callable[..., Any] | None:
    """
    Build the connect_bitvavo callable for MariaDB mode.

    Returns None in SQLite mode — provisioning requires a persistent DB.
    Raises RuntimeError at startup if the master key env var is missing.

    Production: RealBitvavoCredentialValidator, never the mock.
    """
    if args.database != "mariadb":
        return None

    from src.account_provisioning.account_provisioning_service_v1 import AccountProvisioningService
    from src.account_provisioning.account_repository_v1 import MariaDbAccountRepository
    from src.account_provisioning.bitvavo_credential_validator_v1 import RealBitvavoCredentialValidator
    from src.account_provisioning.connect_bitvavo_v1 import build_connect_bitvavo
    from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
    from src.account_provisioning.credential_repository_v1 import CredentialRepository
    from src.common.db import get_db_connection
    from src.execution.bitvavo_client import BitvavoClient

    try:
        key_version, key_bytes = load_master_key_from_env()
    except ValueError as exc:
        raise RuntimeError(f"PROVISIONING_STARTUP_FAILED: {exc}") from exc

    provisioning_service = AccountProvisioningService(
        credential_validator=RealBitvavoCredentialValidator(),
        master_key_version=key_version,
        master_key_bytes=key_bytes,
        account_repo_factory=MariaDbAccountRepository,
        cred_repo_factory=CredentialRepository,
    )

    return build_connect_bitvavo(
        provisioning_service=provisioning_service,
        conn_factory=get_db_connection,
        master_key_bytes=key_bytes,
        cred_repo_factory=CredentialRepository,
        bitvavo_client_factory=lambda api_key, api_secret: BitvavoClient(
            api_key=api_key, api_secret=api_secret
        ),
        output_root=Path(args.output_root),
    )


def build_service(args: argparse.Namespace) -> WebsiteRegistrationService:
    env = dict(os.environ)
    if is_production_env(env):
        # Pepper must be validated before proof provider so no production startup
        # succeeds without it, regardless of proof provider outcome.
        ip_hash_pepper = _validate_production_pepper(env)
        proof_provider, mailer = _validate_production_config(env)
    else:
        proof_provider = build_proof_of_human_provider_from_env(env)
        mailer = build_mailer_from_env(env)
        ip_hash_pepper = str(env.get("SYNTH_IP_HASH_PEPPER", "")).strip()
    repository = _build_repository(args)
    return WebsiteRegistrationService(
        repository=repository,
        proof_provider=proof_provider,
        mailer=mailer,
        base_url=args.base_url,
        display_timezone=args.display_timezone,
        ip_hash_pepper=ip_hash_pepper,
    )


def main() -> int:
    args = parse_args()
    env = dict(os.environ)
    service = build_service(args)
    connect_bitvavo = _build_connect_bitvavo(args)
    allowed_origins: set[str] | None = None
    if is_production_env(env):
        raw_base_url = env.get("SYNTH_PUBLIC_BASE_URL", "")
        normalized_origin = _validate_production_base_url(raw_base_url)
        allowed_origins = {normalized_origin}
    app = build_wsgi_app(service=service, allowed_origins=allowed_origins, connect_bitvavo=connect_bitvavo)
    provisioning_status = "enabled" if connect_bitvavo is not None else "disabled"
    print(
        f"STARTED runner=website_registration_service_v1 host={args.host} port={args.port}"
        f" database={args.database} provisioning={provisioning_status}",
        flush=True,
    )
    print("broker_private_calls=0", flush=True)
    print("broker_writes=0", flush=True)
    print("order_submission=0", flush=True)
    print("live_orders=0", flush=True)
    print("decision_gate=none", flush=True)
    print("execution_planner=none", flush=True)
    print("executor=none", flush=True)
    try:
        with make_server(args.host, args.port, app) as httpd:
            print("phase=serve status=ready", flush=True)
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("INTERRUPTED runner=website_registration_service_v1", flush=True)
        return 130
    except Exception as exc:
        print(f"FAILED runner=website_registration_service_v1 error={type(exc).__name__}", flush=True)
        raise
    finally:
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
