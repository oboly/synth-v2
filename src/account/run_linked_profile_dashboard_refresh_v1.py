"""
run_linked_profile_dashboard_refresh_v1.py

Discovers all active explicitly-linked profiles for a venue from the DB.
Used by the shell pipeline to loop over profiles without hardcoding names.

Read-only DB query. No broker calls. No rendering. No order submission.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from src.account.app_profile_trading_account_link_v1 import discover_active_linked_profiles


RUNNER_NAME = "run_linked_profile_dashboard_refresh_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"


def discover_linked_profiles(*, venue: str) -> list[dict]:
    """
    Return all active primary link rows for the given venue via the account layer.
    Delegates to the canonical account-layer discovery function.
    Each dict has profile_code, account_code, venue, display_timezone.
    Ordered by profile_code for deterministic output.
    Never infers account from profile name.
    """
    return discover_active_linked_profiles(venue=venue)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover all active explicitly linked profiles for a venue. "
            "Output as profile-list (one per line) or summary. "
            "Read-only. No broker calls. No order submission."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--output",
        choices=("profile-list", "summary", "none"),
        default="summary",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_ts = datetime.now(UTC)

    try:
        profiles = discover_linked_profiles(venue=args.venue)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if args.output == "profile-list":
        for p in profiles:
            print(p["profile_code"])
    elif args.output == "summary":
        ts_text = generated_ts.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(f"venue={args.venue}")
        print(f"generated_ts_utc={ts_text}")
        print(f"linked_profile_count={len(profiles)}")
        for p in profiles:
            print(
                f"linked_profile profile_code={p['profile_code']}"
                f" account_code={p['account_code']}"
            )
        print("broker_private_calls=0")
        print("broker_writes=0")
        print("order_submission=0")
        print("live_orders=0")
        print("decision_gate=none")
        print("execution_planner=none")
        print("executor=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
