from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Any

from src.execution_planner.contract_preview_v1 import (
    ExecutionIntentPreview,
    ExecutionMarketContextPreview,
    build_execution_plan_preview,
    preview_to_dict,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only execution planner contract preview. No DB writes. No executor."
    )
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--asset-id", type=int, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--side", required=True, choices=("BUY", "SELL"))
    parser.add_argument(
        "--intent-type",
        required=True,
        choices=(
            "PREPARE_PLAN",
            "PLACE_PASSIVE_LIMIT",
            "PLACE_LADDER",
            "EXIT_PASSIVE_LIMIT",
            "EXIT_LADDER",
        ),
    )
    parser.add_argument("--max-notional-eur", default=None)
    parser.add_argument("--quantity-base", default=None)
    parser.add_argument("--decision-state", default="EXECUTION_ALLOWED")
    parser.add_argument("--decision-reason", default="CONTRACT_PREVIEW")
    parser.add_argument("--execution-mode", default="paper")

    parser.add_argument("--reference-price-eur", required=True)
    parser.add_argument("--best-bid-eur", required=True)
    parser.add_argument("--best-ask-eur", required=True)
    parser.add_argument("--tick-size", required=True)
    parser.add_argument("--spread-bps", default=None)
    parser.add_argument("--volatility-bucket", default=None)
    parser.add_argument("--regime-label", default=None)
    parser.add_argument("--execution-zone-low", default=None)
    parser.add_argument("--execution-zone-high", default=None)
    parser.add_argument("--invalidation-price-eur", default=None)
    parser.add_argument("--asset-exit-profile-hint", default=None)
    parser.add_argument("--context-asof-ts-utc", default=None)

    parser.add_argument("--output", choices=("json", "table"), default="json")
    return parser.parse_args()


def _optional_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    return Decimal(stripped)


def _print_table(row: dict[str, Any]) -> None:
    leg = row["legs"][0] if row["legs"] else {}

    table = [
        ("symbol", row["symbol"]),
        ("sleeve_code", row["sleeve_code"]),
        ("side", row["side"]),
        ("plan_type", row["plan_type"]),
        ("plan_state", row["plan_state"]),
        ("execution_mode", row["execution_mode"]),
        ("reference_price_eur", row["reference_price_eur"]),
        ("best_bid_eur", row["best_bid_eur"]),
        ("best_ask_eur", row["best_ask_eur"]),
        ("leg_type", leg.get("leg_type")),
        ("target_price_eur", leg.get("target_price_eur")),
        ("target_fraction", leg.get("target_fraction")),
        ("post_only", leg.get("post_only")),
        ("max_reprices", leg.get("max_reprices")),
        ("max_wait_seconds", leg.get("max_wait_seconds")),
        ("max_chase_bps", leg.get("max_chase_bps")),
        ("escalation_to_urgent_limit", leg.get("escalation_to_urgent_limit")),
        ("notes", row["notes"]),
    ]

    width = max(len(key) for key, _ in table)
    for key, value in table:
        print(f"{key.ljust(width)} : {value}")


def main() -> int:
    args = parse_args()

    intent = ExecutionIntentPreview(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
        asset_id=args.asset_id,
        symbol=args.symbol,
        venue=args.venue,
        side=args.side,
        intent_type=args.intent_type,
        max_notional_eur=_optional_decimal(args.max_notional_eur),
        quantity_base=_optional_decimal(args.quantity_base),
        decision_state=args.decision_state,
        decision_reason=args.decision_reason,
        execution_mode=args.execution_mode,
    )

    context = ExecutionMarketContextPreview(
        reference_price_eur=Decimal(args.reference_price_eur),
        best_bid_eur=Decimal(args.best_bid_eur),
        best_ask_eur=Decimal(args.best_ask_eur),
        tick_size=Decimal(args.tick_size),
        spread_bps=_optional_decimal(args.spread_bps),
        volatility_bucket=args.volatility_bucket,
        regime_label=args.regime_label,
        execution_zone_low=_optional_decimal(args.execution_zone_low),
        execution_zone_high=_optional_decimal(args.execution_zone_high),
        invalidation_price_eur=_optional_decimal(args.invalidation_price_eur),
        asset_exit_profile_hint=args.asset_exit_profile_hint,
        context_asof_ts_utc=args.context_asof_ts_utc,
    )

    plan = build_execution_plan_preview(intent=intent, context=context)
    row = preview_to_dict(plan)

    if args.output == "json":
        print(json.dumps(row, indent=2, ensure_ascii=False))
    else:
        _print_table(row)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
