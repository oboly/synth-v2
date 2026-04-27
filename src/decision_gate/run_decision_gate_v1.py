from __future__ import annotations

# Synth v2 — decision_gate CLI
# Layer: decision_gate
# Responsibility: dry-run/account permission visibility.

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig, DecisionResult
from src.decision_gate.repository import DecisionGateRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run decision_gate_v1 dry-run.")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", type=str, required=True)
    parser.add_argument("--venue", type=str, default="bitvavo")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-available-equity-eur", type=str, default="25.00")
    parser.add_argument("--setup-filter-database", type=str, default="synth_bt")
    parser.add_argument("--filter-name", type=str, default="trade_setup_filter_v1")
    parser.add_argument("--filter-version", type=str, default="1.0")
    parser.add_argument("--asset-suitability-mode", type=str, default="candidate_weak_set")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _print_json(results: list[DecisionResult]) -> None:
    payload = []
    for row in results:
        payload.append({key: _serialize_value(value) for key, value in asdict(row).items()})
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _print_table(results: list[DecisionResult]) -> None:
    headers = [
        "symbol",
        "selection_state",
        "setup_filter",
        "setup_reason",
        "decision_state",
        "execution_intent",
        "reason",
        "available_equity_eur",
        "active_plan",
        "open_position",
    ]

    rows: list[list[str]] = []
    for item in results:
        rows.append(
            [
                item.symbol,
                item.selection_state,
                item.setup_filter_state or "",
                item.setup_filter_reason or "",
                item.decision_state,
                item.execution_intent,
                item.decision_reason,
                str(item.available_equity_eur) if item.available_equity_eur is not None else "",
                "1" if item.has_active_plan else "0",
                "1" if item.has_open_position else "0",
            ]
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(v.ljust(widths[idx]) for idx, v in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))


def main() -> int:
    args = _parse_args()

    repo = DecisionGateRepository()
    cfg = DecisionGateConfig(
        min_available_equity_eur=Decimal(str(args.min_available_equity_eur))
    )

    selection_rows = repo.fetch_selection_rows(
        venue=args.venue,
        asset_id=args.asset_id,
        symbol=args.symbol,
        limit=args.limit,
        setup_filter_database=args.setup_filter_database,
        filter_name=args.filter_name,
        filter_version=args.filter_version,
        asset_suitability_mode=args.asset_suitability_mode,
    )

    sleeve_state = repo.fetch_sleeve_state(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
    )

    results: list[DecisionResult] = []

    for row in selection_rows:
        duplicate_state = repo.fetch_duplicate_state(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=row.asset_id,
            venue=row.venue,
        )

        has_open_order = repo.fetch_open_order_flag(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=row.asset_id,
            venue=row.venue,
        )

        result = evaluate_selection_for_account(
            row=row,
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            sleeve_state=sleeve_state,
            duplicate_state=duplicate_state,
            config=cfg,
            has_open_order=has_open_order,
        )
        results.append(result)

    if args.output == "json":
        _print_json(results)
    else:
        _print_table(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
