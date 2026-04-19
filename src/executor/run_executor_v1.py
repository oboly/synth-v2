from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from src.executor.executor_v1 import execute_plan_paper
from src.executor.repository import ExecutorRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run executor_v1 for paper execution plans.")
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--sleeve-code", default=None)
    parser.add_argument("--venue", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _print_json(rows: list[dict[str, Any]]) -> None:
    payload = []
    for row in rows:
        payload.append({k: _serialize_value(v) for k, v in row.items()})
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "execution_plan_id",
        "symbol",
        "desired_action",
        "old_plan_state",
        "new_plan_state",
        "event_type",
        "fill_price_eur",
        "fill_qty",
        "reservation_released",
        "position_opened",
    ]

    printable = []
    for row in rows:
        printable.append([
            "" if row["execution_plan_id"] is None else str(row["execution_plan_id"]),
            "" if row["symbol"] is None else str(row["symbol"]),
            "" if row["desired_action"] is None else str(row["desired_action"]),
            "" if row["old_plan_state"] is None else str(row["old_plan_state"]),
            "" if row["new_plan_state"] is None else str(row["new_plan_state"]),
            "" if row["event_type"] is None else str(row["event_type"]),
            "" if row["fill_price_eur"] is None else str(row["fill_price_eur"]),
            "" if row["fill_qty"] is None else str(row["fill_qty"]),
            "" if row["reservation_released"] is None else str(row["reservation_released"]),
            "" if row["position_opened"] is None else str(row["position_opened"]),
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
    repo = ExecutorRepository()

    plans = repo.fetch_open_plans(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
        venue=args.venue,
        limit=args.limit,
    )

    results = []
    for plan in plans:
        result = execute_plan_paper(plan, repo)
        results.append(asdict(result))

    if args.output == "json":
        _print_json(results)
    else:
        _print_table(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
