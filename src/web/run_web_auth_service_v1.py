from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
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
    service = build_service(args)
    app = build_wsgi_app(service=service)
    print(
        f"STARTED runner=website_registration_service_v1 host={args.host} port={args.port} database={args.database}",
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
