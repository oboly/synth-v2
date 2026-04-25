from __future__ import annotations

import argparse
from decimal import Decimal

from src.plan_lifecycle.repository import PlanLifecycleRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run plan lifecycle: invalidate + release reservations"
    )
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--sleeve-code", default=None)
    parser.add_argument("--venue", default=None)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", choices=("table", "none"), default="table")
    return parser.parse_args()


def _print_table(rows: list[dict]) -> None:
    headers = [
        "plan_id",
        "asset",
        "old_state",
        "new_state",
        "released",
        "amount",
        "reason",
    ]

    widths = [len(h) for h in headers]
    for r in rows:
        vals = [
            str(r["plan_id"]),
            str(r["symbol"]),
            str(r["old_state"]),
            str(r["new_state"]),
            str(r["released"]),
            str(r["amount"]),
            str(r["reason"]),
        ]
        for i, v in enumerate(vals):
            widths[i] = max(widths[i], len(v))

    def fmt(vals):
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(vals))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))

    for r in rows:
        print(fmt([
            str(r["plan_id"]),
            str(r["symbol"]),
            str(r["old_state"]),
            str(r["new_state"]),
            str(r["released"]),
            str(r["amount"]),
            str(r["reason"]),
        ]))


def should_abort(plan) -> tuple[bool, str]:
    # --- CORE INVALIDATION LOGIC ---

    if plan.selection_state is None:
        return True, "NO_SELECTION_STATE"

    if plan.selection_state not in {"WATCHLIST", "PREPARE", "BUY_READY"}:
        return True, f"INVALID_SELECTION_STATE_{plan.selection_state}"

    score = plan.effective_selection_score or Decimal("0")

    # Watchlist preplan invalidation threshold
    if plan.selection_state == "WATCHLIST" and score < Decimal("0.50"):
        return True, "WATCHLIST_SCORE_DROPPED"

    # Prepare invalidation (stricter)
    if plan.selection_state == "PREPARE" and score < Decimal("0.48"):
        return True, "PREPARE_SCORE_DROPPED"

    return False, "OK"


def main() -> int:
    args = parse_args()

    repo = PlanLifecycleRepository()

    plans = repo.fetch_invalidatable_plans(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
        venue=args.venue,
        limit=args.limit,
    )

    output_rows = []

    for plan in plans:
        abort, reason = should_abort(plan)

        if not abort:
            continue

        old_state = plan.plan_state

        repo.abort_plan(plan=plan, reason=reason)
        released_amount = repo.release_reservation_for_plan(plan)

        output_rows.append({
            "plan_id": plan.execution_plan_id,
            "symbol": plan.symbol,
            "old_state": old_state,
            "new_state": "ABORTED",
            "released": released_amount > 0,
            "amount": str(released_amount),
            "reason": reason,
        })

    if args.output == "table":
        _print_table(output_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
