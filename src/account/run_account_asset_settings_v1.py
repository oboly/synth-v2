from __future__ import annotations

import argparse
import json
import sys

from src.account.account_asset_settings_v1 import (
    ALLOWED_ACTIONS,
    DEFAULT_VENUE,
    dispatch_account_asset_action,
    normalize_market,
    utc_now_naive,
    MySqlAccountAssetSettingsRepo,
)
from src.common.db import get_connection


RUNNER_NAME = "account_asset_settings_v1"
RUNNER_VERSION = "0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Local-only account_asset settings runner. No broker reads, no broker writes, "
            "no order submission, no public auth endpoint."
        )
    )
    parser.add_argument("action", choices=sorted(ALLOWED_ACTIONS))
    parser.add_argument("--account-profile", required=True, metavar="PROFILE")
    parser.add_argument("--market", required=True, metavar="MARKET")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--account-code",
        default=None,
        metavar="CODE",
        help="trading_account.account_code. Defaults to bitvavo_<profile>_read.",
    )
    parser.add_argument("--output", choices=("summary", "json", "none"), default="summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    account_code = args.account_code or f"bitvavo_{args.account_profile}_read"
    conn = get_connection()
    try:
        repo = MySqlAccountAssetSettingsRepo(conn)
        result = dispatch_account_asset_action(
            repo,
            action=args.action,
            account_code=account_code,
            venue=args.venue,
            market=normalize_market(args.market),
            now_utc=utc_now_naive(),
        )
        conn.commit()
    except RuntimeError as exc:
        conn.rollback()
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if args.output == "summary":
        print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(f"action={result.action} status={result.status}")
        print(f"account_code={result.account_code} trading_account_id={result.trading_account_id}")
        print(f"venue={result.venue} market={result.market}")
        print(f"message={result.message}")
        print("broker_private_calls=0")
        print("broker_writes=0")
        print("order_submission=0")
        print("executor=none")
    elif args.output == "json":
        print(
            json.dumps(
                {
                    "runner": RUNNER_NAME,
                    "version": RUNNER_VERSION,
                    "action": result.action,
                    "status": result.status,
                    "account_code": result.account_code,
                    "trading_account_id": result.trading_account_id,
                    "venue": result.venue,
                    "market": result.market,
                    "source": result.source,
                    "message": result.message,
                    "broker_private_calls": 0,
                    "broker_writes": 0,
                    "order_submission": 0,
                    "executor": "none",
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
