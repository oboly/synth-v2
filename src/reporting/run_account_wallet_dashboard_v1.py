from __future__ import annotations

import argparse
import re
import sys
from datetime import timedelta
from pathlib import Path

from src.reporting.account_wallet_dashboard_v1 import (
    DEFAULT_FRESH_AFTER,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PRICE_FRESH_AFTER,
    REPORT_NAME,
    REPORT_VERSION,
    load_and_write_wallet_dashboard,
)
from src.reporting.account_dashboard_profile_access_v1 import resolve_dashboard_profile_access


DEFAULT_VENUE = "bitvavo"
_PROFILE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def validate_profile_slug(profile: str) -> None:
    if not _PROFILE_SLUG_RE.match(profile):
        raise ValueError(
            f"Invalid profile slug {profile!r}. Must match [a-z0-9][a-z0-9_-]{{0,62}}."
        )
    if ".." in profile or "/" in profile:
        raise ValueError(f"Path traversal rejected in profile slug: {profile!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render per-account wallet HTML/JSON from DB snapshots only. "
            "Read-only dashboard render. No broker writes, no order submission."
        )
    )
    parser.add_argument("--account-profile", required=True, metavar="PROFILE")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Synth web root. Outputs are written under accounts/<profile>/wallet.html and wallet.json.",
    )
    parser.add_argument(
        "--fresh-after-minutes",
        type=int,
        default=int(DEFAULT_FRESH_AFTER.total_seconds() // 60),
    )
    parser.add_argument(
        "--price-fresh-after-minutes",
        type=int,
        default=int(DEFAULT_PRICE_FRESH_AFTER.total_seconds() // 60),
    )
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_profile_slug(args.account_profile)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    try:
        access = resolve_dashboard_profile_access(
            account_profile=args.account_profile,
            venue=args.venue,
        )
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    try:
        payload, html_path, json_path = load_and_write_wallet_dashboard(
            profile=args.account_profile,
            account_code=access.trading_account_stable_ref,
            venue=args.venue,
            output_root=Path(args.output_root),
            fresh_after=timedelta(minutes=args.fresh_after_minutes),
            price_fresh_after=timedelta(minutes=args.price_fresh_after_minutes),
        )
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if args.output == "summary":
        print(f"runner={REPORT_NAME} version={REPORT_VERSION}")
        print(f"profile={payload.profile} account_code={payload.account_code}")
        print(f"trading_account_id={payload.trading_account_id} venue={payload.venue}")
        print(f"latest_wallet_refresh_ts_utc={payload.latest_wallet_refresh_ts_utc}")
        print(f"freshness={payload.freshness}")
        print(f"balance_count={payload.balance_count}")
        print(f"open_order_market_count={payload.open_order_market_count}")
        print(f"html_output={html_path}")
        print(f"json_output={json_path}")
        if payload.market_data_warning:
            print(f"market_data_warning={payload.market_data_warning}")
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
