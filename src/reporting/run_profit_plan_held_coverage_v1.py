from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.reporting.account_dashboard_profile_access_v1 import resolve_dashboard_profile_access
from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_VENUE,
    classify_market_prices_by_market,
    default_page_paths,
    load_account_scoped_short_dashboard_context,
    validate_profile_slug,
)
from src.reporting.account_wallet_dashboard_v1 import classify_wallet_freshness
from src.reporting.profit_plan_held_coverage_v1 import audit_profit_plan_held_coverage
from src.reporting.run_manual_short_trader_profit_plan_v1 import held_amount_and_value_by_symbol


REPORT_NAME = "run_profit_plan_held_coverage_v1"
REPORT_VERSION = "0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Profit Plan held-token coverage invariant. Compares the latest "
            "persisted account balance snapshot with an already-rendered Profit Plan JSON."
        )
    )
    parser.add_argument("--account-profile", required=True, metavar="PROFILE")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Synth web root used to resolve accounts/<profile>/profit-plan.json.",
    )
    parser.add_argument(
        "--input-json",
        default=None,
        metavar="PATH",
        help="Optional explicit Profit Plan JSON path.",
    )
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def _fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    value_utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value_utc.isoformat().replace("+00:00", "Z")


def _payload(report: object) -> dict[str, object]:
    problems = getattr(report, "problems")
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "status": "PASS" if getattr(report, "ok") else "FAIL",
        "held_count": getattr(report, "held_count"),
        "rendered_wallet_held_count": getattr(report, "rendered_wallet_held_count"),
        "held_symbols": list(getattr(report, "held_symbols")),
        "rendered_wallet_held_symbols": list(getattr(report, "rendered_wallet_held_symbols")),
        "problems": [
            {
                "symbol": problem.symbol,
                "code": problem.code,
                "detail": problem.detail,
            }
            for problem in problems
        ],
        "research_only": False,
        "reporting_only": True,
        "broker_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate": "none",
        "execution_planner": "none",
        "executor": "none",
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_profile_slug(args.account_profile)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    try:
        access = resolve_dashboard_profile_access(
            account_profile=args.account_profile,
            venue=args.venue,
        )
        context = load_account_scoped_short_dashboard_context(
            profile=args.account_profile,
            account_code=access.trading_account_stable_ref,
            venue=args.venue,
        )
    except Exception as exc:
        print(f"[error] persisted account scope load failed: {exc}", file=sys.stderr)
        return 2

    default_json = default_page_paths(
        output_root=Path(args.output_root),
        profile=args.account_profile,
        page_stem="profit-plan",
    )[1]
    input_json = Path(args.input_json) if args.input_json else default_json
    try:
        snapshot = json.loads(input_json.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[error] Profit Plan JSON read failed: {input_json}: {exc}", file=sys.stderr)
        return 2

    now_utc = datetime.now(UTC)
    price_display_by_market = classify_market_prices_by_market(context=context, now_utc=now_utc)
    prices = {
        market: display.safe_price
        for market, display in price_display_by_market.items()
        if display.safe_price is not None
    }
    held_amount_by_symbol, held_eur_value_by_symbol = held_amount_and_value_by_symbol(
        balances=list(context.balances),
        prices=prices,
    )
    wallet_status = classify_wallet_freshness(
        context.latest_balance_snapshot_ts_utc,
        now_utc=now_utc,
    )

    report = audit_profit_plan_held_coverage(
        snapshot=snapshot,
        held_amount_by_symbol=held_amount_by_symbol,
        held_eur_value_by_symbol=held_eur_value_by_symbol,
        expected_account_snapshot_ts_utc=_fmt_ts(context.latest_balance_snapshot_ts_utc),
        expected_wallet_snapshot_status=wallet_status,
    )
    payload = _payload(report)

    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"status={payload['status']} held={payload['held_count']} "
            f"rendered_wallet_held={payload['rendered_wallet_held_count']} "
            f"problems={len(payload['problems'])}"
        )
        for problem in report.problems:
            print(f"{problem.symbol}\t{problem.code}\t{problem.detail}")
        print(
            "reporting_only=true broker_calls=0 broker_writes=0 order_submission=0 "
            "decision_gate=none execution_planner=none executor=none"
        )

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
