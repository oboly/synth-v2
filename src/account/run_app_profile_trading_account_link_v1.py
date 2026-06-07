"""
run_app_profile_trading_account_link_v1.py

Account-layer CLI for explicit app_profile → trading_account linkage.

No credentials. No broker calls. DB write only to linkage table.

Usage:
    python -m src.account.run_app_profile_trading_account_link_v1 \
        --profile joost \
        --venue bitvavo \
        --account-code bitvavo_joost_read \
        --set-primary \
        --output summary
"""
from __future__ import annotations

import argparse
import sys

from src.account.app_profile_trading_account_link_v1 import AppProfileTradingAccountLinkRepository
from src.common.db import get_connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update an explicit app_profile → trading_account link. "
            "Idempotent. No broker calls. No credential reads."
        )
    )
    parser.add_argument("--profile", required=True, help="app_profile.profile_code")
    parser.add_argument("--venue", required=True, help="trading_account.venue")
    parser.add_argument("--account-code", required=True, help="trading_account.account_code")
    parser.add_argument(
        "--set-primary",
        action="store_true",
        default=False,
        help="Mark this link as the primary account for the profile",
    )
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = AppProfileTradingAccountLinkRepository(connection_factory=get_connection)
    print(f"STARTED run_app_profile_trading_account_link_v1 profile={args.profile} "
          f"venue={args.venue} account_code={args.account_code} set_primary={args.set_primary}")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("decision_gate=none execution_planner=none executor=none")
    try:
        result = repo.upsert_link(
            profile_code=args.profile,
            venue=args.venue,
            account_code=args.account_code,
            set_primary=args.set_primary,
        )
    except RuntimeError as exc:
        print(f"FAILED {exc}", file=sys.stderr)
        return 1
    if args.output == "summary":
        print(f"link_id={result['link_id']}")
        print(f"profile_code={result['profile_code']}")
        print(f"app_profile_id={result['app_profile_id']}")
        print(f"trading_account_id={result['trading_account_id']}")
        print(f"account_code={result['account_code']}")
        print(f"venue={result['venue']}")
        print(f"is_primary={result['is_primary']}")
        print(f"link_status={result['link_status']}")
        print(f"updated_ts_utc={result['updated_ts_utc']}")
    print("FINISHED run_app_profile_trading_account_link_v1")
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
