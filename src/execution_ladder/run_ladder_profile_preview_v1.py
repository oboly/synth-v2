"""
run_ladder_profile_preview_v1 — read-only ladder profile preview runner.

Resolves a ladder profile and prints per-leg preview without writing to the
database, placing orders, or calling any broker API.

NOT an authoritative manual-execution path: this runner uses the raw
resolve_ladder_preview() path, never calls decision_gate, and has no
executor consumer — see
docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
bypass-list item 4. Route real manual SELL execution requests through
src.manual_execution.manual_execution_service_v1.process() instead.

Usage:
    python -m src.execution_ladder.run_ladder_profile_preview_v1 \\
        --trading-account-id 1 \\
        --profile-code SELL_PPP_RECOVERY_V1 \\
        --anchor-high-price 1.00 \\
        --quote-amount 10.00
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation

from src.execution_ladder.models import LadderProfile, LadderLeg
from src.execution_ladder.repository import fetch_profile, fetch_active_legs
from src.execution_ladder.resolver import resolve_anchor_price, resolve_ladder_preview

RUNNER_NAME = "run_ladder_profile_preview_v1"
RUNNER_VERSION = "1.0"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only ladder profile preview. No orders placed."
    )
    parser.add_argument(
        "--trading-account-id",
        required=True,
        type=int,
        help="trading_account.trading_account_id scope for the profile lookup.",
    )
    parser.add_argument(
        "--profile-code",
        required=True,
        type=str,
        help="Profile code to resolve (e.g. SELL_PPP_RECOVERY_V1).",
    )
    parser.add_argument(
        "--anchor-high-price",
        required=True,
        type=str,
        help="NativeShortContextRow.anchor_high_price for the target symbol.",
    )
    parser.add_argument(
        "--quote-amount",
        required=True,
        type=str,
        help="Final user-selected quote notional amount (e.g. 10.00).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    print(
        "[BLOCKED] direct ladder profile preview is disabled; "
        "use src.manual_execution.manual_execution_service_v1.process()"
    )
    return 2

    # Unreachable compatibility implementation retained until the profile
    # reader is migrated to the canonical request/service path.
    print(f"runner={RUNNER_NAME}")
    print(f"version={RUNNER_VERSION}")
    print(f"trading_account_id={args.trading_account_id}")
    print(f"profile_code={args.profile_code}")
    print("STARTED")

    # Safety markers — verified by test
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("decision_gate=none")
    print("executor=none")

    try:
        anchor_high_price = Decimal(args.anchor_high_price)
    except InvalidOperation:
        print(f"ERROR: --anchor-high-price is not a valid decimal: {args.anchor_high_price!r}",
              file=sys.stderr)
        return 1

    try:
        quote_amount = Decimal(args.quote_amount)
    except InvalidOperation:
        print(f"ERROR: --quote-amount is not a valid decimal: {args.quote_amount!r}",
              file=sys.stderr)
        return 1

    profile = fetch_profile(args.trading_account_id, args.profile_code)
    if profile is None:
        print(
            f"ERROR: profile {args.profile_code!r} not found for "
            f"trading_account_id={args.trading_account_id}",
            file=sys.stderr,
        )
        return 1

    if not profile.is_enabled:
        print(f"ERROR: profile {args.profile_code!r} is disabled", file=sys.stderr)
        return 1

    legs = fetch_active_legs(profile.ladder_profile_id, profile.current_version)

    try:
        anchor_price = resolve_anchor_price(
            profile.anchor_type,
            anchor_high_price=anchor_high_price,
        )
        preview = resolve_ladder_preview(profile, legs, anchor_price, quote_amount)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\nprofile={preview.profile_code}  version={preview.profile_version}")
    print(f"side={preview.side}  anchor_type={preview.anchor_type}")
    print(f"anchor_price={preview.anchor_price}")
    print(f"quote_amount={preview.quote_amount}")
    print(f"total_allocation_bps={preview.total_allocation_bps}")
    print(f"estimated_total_base_quantity={preview.estimated_total_base_quantity}")
    print(f"\nlegs ({len(preview.legs)}):")
    for leg in preview.legs:
        print(
            f"  leg {leg.leg_number}: "
            f"offset={leg.price_offset_bps:+d}bps  "
            f"alloc={leg.allocation_bps}bps  "
            f"quote={leg.allocated_quote_notional}  "
            f"limit_price={leg.limit_price}  "
            f"base_qty={leg.estimated_base_quantity}  "
            f"{leg.order_type}/{leg.time_in_force}"
        )

    print("\nFINISHED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
