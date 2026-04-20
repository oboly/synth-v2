from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from src.plan_lifecycle.plan_lifecycle_v1 import process_releasable_plan
from src.plan_lifecycle.repository import PlanLifecycleRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run plan_lifecycle_v1 for expiry and reservation release.")
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--sleeve-code", default=None)
    parser.add_argument("--venue", default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--skip-expire", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _print_json(rows: list[dict[str, Any]], expired_count: int) -> None:
    payload = {
        "expired_count": expired_count,
        "results": [{k: _serialize_value(v) for k, v in row.items()} for row in rows],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _print_table(rows: list[dict[str, Any]], expired_count: int) -> None:
    print(f"expired_count={expired_count}")
    headers = [
        "execution_plan_id",
        "symbol",
        "old_plan_state",
        "reservation_released",
        "released_amount_eur",
        "reason",
    ]

    printable = []
    for row in rows:
        printable.append([
            "" if row["execution_plan_id"] is None else str(row["execution_plan_id"]),
            "" if row["symbol"] is None else str(row["symbol"]),
            "" if row["old_plan_state"] is None else str(row["old_plan_state"]),
            "" if row["reservation_released"] is None else str(row["reservation_released"]),
            "" if row["released_amount_eur"] is None else str(row["released_amount_eur"]),
            "" if row["reason"] is None else str(row["reason"]),
        ])

    widths = [len(h) for h in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()
    repo = PlanLifecycleRepository()

    expired_count = 0
    if not args.skip_expire:
        expired_count = repo.expire_due_plans(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            venue=args.venue,
        )

    plans = repo.fetch_releasable_plans(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
        venue=args.venue,
        limit=args.limit,
    )

    results = [asdict(process_releasable_plan(plan, repo)) for plan in plans]

    if args.output == "json":
        _print_json(results, expired_count)
    else:
        _print_table(results, expired_count)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
