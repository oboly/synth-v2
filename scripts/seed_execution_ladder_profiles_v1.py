"""
seed_execution_ladder_profiles_v1 — seeds one SELL_PPP_RECOVERY_V1 ladder profile
for a specific trading account.

Idempotent: safe to re-run. Uses ON DUPLICATE KEY UPDATE for upsert semantics
on (trading_account_id, rule_code) and (trading_account_id, profile_code).
Leg upsert uses (ladder_profile_id, profile_version, leg_number).

This seed runner does NOT auto-discover eligible accounts. Pass --trading-account-id
explicitly. No --dry-run flag suppresses DB writes; add --dry-run to preview only.

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  executor=none
"""

from __future__ import annotations

import argparse
import sys

from src.common.db import get_connection


RUNNER_NAME = "seed_execution_ladder_profiles_v1"

_SIZING_RULE_CODE = "MANUAL_ONLY_DEFAULT"
_PROFILE_CODE = "SELL_PPP_RECOVERY_V1"
_PROFILE_VERSION = 1

_LEGS = [
    {"leg_number": 1, "price_offset_bps": -600, "allocation_bps": 5000},
    {"leg_number": 2, "price_offset_bps": -200, "allocation_bps": 5000},
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed one SELL_PPP_RECOVERY_V1 ladder profile for a specific trading account."
        )
    )
    parser.add_argument(
        "--trading-account-id",
        required=True,
        type=int,
        help="trading_account.trading_account_id to seed the profile for.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be inserted without writing to the database.",
    )
    return parser.parse_args()


def seed(trading_account_id: int, *, dry_run: bool = False) -> None:
    print(f"runner={RUNNER_NAME}")
    print(f"trading_account_id={trading_account_id}")
    print(f"dry_run={dry_run}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("decision_gate=none")
    print("executor=none")
    print("STARTED")

    if dry_run:
        print(f"\n[dry-run] would upsert sizing_rule: {_SIZING_RULE_CODE}")
        print(f"[dry-run] would upsert profile:      {_PROFILE_CODE} v{_PROFILE_VERSION}")
        for leg in _LEGS:
            print(
                f"[dry-run] would upsert leg {leg['leg_number']}: "
                f"offset={leg['price_offset_bps']:+d}bps "
                f"alloc={leg['allocation_bps']}bps  LIMIT/GTC"
            )
        print("FINISHED (dry-run, no DB writes)")
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 1. Upsert sizing rule
            cur.execute(
                """
                INSERT INTO execution_sizing_rule (
                    trading_account_id, rule_code, display_label, description,
                    rule_type, source_variable_key, multiplier_bps,
                    fixed_quote_amount, floor_quote_amount, cap_quote_amount,
                    is_enabled, version
                ) VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL, NULL, NULL, 1, 1)
                ON DUPLICATE KEY UPDATE
                    is_enabled = VALUES(is_enabled),
                    version    = version
                """,
                (
                    trading_account_id,
                    _SIZING_RULE_CODE,
                    "Manual amount (no suggestion)",
                    "No derived suggestion required; user must enter a quote amount before processing.",
                    "MANUAL_ONLY",
                ),
            )

            # 2. Resolve sizing rule ID
            cur.execute(
                """
                SELECT sizing_rule_id
                FROM execution_sizing_rule
                WHERE trading_account_id = %s AND rule_code = %s
                LIMIT 1
                """,
                (trading_account_id, _SIZING_RULE_CODE),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    f"sizing_rule {_SIZING_RULE_CODE!r} not found after upsert "
                    f"for trading_account_id={trading_account_id}"
                )
            sizing_rule_id = int(row["sizing_rule_id"])

            # 3. Upsert profile
            cur.execute(
                """
                INSERT INTO execution_ladder_profile (
                    trading_account_id, profile_code, display_label, description,
                    side, anchor_type, default_sizing_rule_id, is_enabled, current_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1)
                ON DUPLICATE KEY UPDATE
                    is_enabled      = VALUES(is_enabled),
                    current_version = current_version
                """,
                (
                    trading_account_id,
                    _PROFILE_CODE,
                    "Sell PPP recovery ladder",
                    (
                        "Split a user-selected sell trade amount into two equal limit sells "
                        "below the current native-short anchor high. The anchor price resolves "
                        "to NativeShortContextRow.anchor_high_price (swing high / breakout gate). "
                        "Intended for user-confirmed recovery exits only."
                    ),
                    "SELL",
                    "NATIVE_SHORT_ANCHOR_HIGH",
                    sizing_rule_id,
                ),
            )

            # 4. Resolve profile ID
            cur.execute(
                """
                SELECT ladder_profile_id
                FROM execution_ladder_profile
                WHERE trading_account_id = %s AND profile_code = %s
                LIMIT 1
                """,
                (trading_account_id, _PROFILE_CODE),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    f"profile {_PROFILE_CODE!r} not found after upsert "
                    f"for trading_account_id={trading_account_id}"
                )
            profile_id = int(row["ladder_profile_id"])

            # 5. Upsert legs
            for leg in _LEGS:
                cur.execute(
                    """
                    INSERT INTO execution_ladder_leg (
                        ladder_profile_id, profile_version, leg_number,
                        price_offset_bps, allocation_bps, order_type, time_in_force, is_enabled
                    ) VALUES (%s, %s, %s, %s, %s, 'LIMIT', 'GTC', 1)
                    ON DUPLICATE KEY UPDATE
                        is_enabled = VALUES(is_enabled)
                    """,
                    (
                        profile_id,
                        _PROFILE_VERSION,
                        leg["leg_number"],
                        leg["price_offset_bps"],
                        leg["allocation_bps"],
                    ),
                )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"  upserted sizing_rule: {_SIZING_RULE_CODE} (id={sizing_rule_id})")
    print(f"  upserted profile:     {_PROFILE_CODE} v{_PROFILE_VERSION} (id={profile_id})")
    for leg in _LEGS:
        print(
            f"  upserted leg {leg['leg_number']}: "
            f"offset={leg['price_offset_bps']:+d}bps "
            f"alloc={leg['allocation_bps']}bps  LIMIT/GTC"
        )
    print("FINISHED")


def main() -> int:
    args = _parse_args()
    try:
        seed(args.trading_account_id, dry_run=args.dry_run)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
