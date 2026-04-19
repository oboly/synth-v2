from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Any

from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig
from src.decision_gate.repository import DecisionGateRepository
from src.execution_planner.execution_planner_v1 import (
    build_execution_plan,
    build_exit_plan_from_position,
)
from src.execution_planner.models import ExecutionPlannerConfig, PlannedExecution
from src.execution_planner.repository import ExecutionPlannerRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run execution_planner_v1 from latest selection + in-memory decision gate."
    )
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--limit", type=int, default=20)

    parser.add_argument("--min-available-equity-eur", default="25.00")
    parser.add_argument("--execution-mode", default="paper")
    parser.add_argument("--prepare-target-fraction", default="0.06600000")
    parser.add_argument("--execute-target-fraction", default="0.06600000")
    parser.add_argument("--max-notional-eur", default="25.0000000000")

    parser.add_argument("--max-reprices", type=int, default=5)
    parser.add_argument("--max-wait-seconds", type=int, default=1800)
    parser.add_argument("--max-chase-bps", default="15.00000000")
    parser.add_argument("--min-spread-bps-for-capture", default="3.00000000")
    parser.add_argument("--escalation-to-urgent-limit", action="store_true")
    parser.add_argument("--no-abort-if-signal-invalidates", action="store_true")

    parser.add_argument("--plan-exit-symbol", default=None)
    parser.add_argument("--plan-exit-asset-id", type=int, default=None)

    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _planned_to_row(
    plan: PlannedExecution | None,
    *,
    symbol: str | None,
    selection_state: str | None,
    decision_state: str | None,
    execution_intent: str | None,
    decision_reason: str | None,
    execution_plan_id: int | None = None,
    capital_reservation_id: int | None = None,
    planner_action: str = "NONE",
) -> dict[str, Any]:
    if plan is None:
        return {
            "symbol": symbol,
            "selection_state": selection_state,
            "decision_state": decision_state,
            "execution_intent": execution_intent,
            "planner_action": planner_action,
            "desired_action": None,
            "plan_state": None,
            "target_fraction": None,
            "max_notional_eur": None,
            "reference_price_eur": None,
            "execution_plan_id": execution_plan_id,
            "capital_reservation_id": capital_reservation_id,
            "reason": decision_reason,
        }

    return {
        "symbol": symbol,
        "selection_state": selection_state,
        "decision_state": decision_state,
        "execution_intent": execution_intent,
        "planner_action": planner_action,
        "desired_action": plan.desired_action,
        "plan_state": plan.plan_state,
        "target_fraction": plan.target_fraction,
        "max_notional_eur": plan.max_notional_eur,
        "reference_price_eur": plan.reference_price_eur,
        "execution_plan_id": execution_plan_id,
        "capital_reservation_id": capital_reservation_id,
        "reason": decision_reason,
    }


def _print_json(rows: list[dict[str, Any]]) -> None:
    payload = []
    for row in rows:
        payload.append({k: _serialize_value(v) for k, v in row.items()})
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "symbol",
        "selection_state",
        "decision_state",
        "execution_intent",
        "planner_action",
        "desired_action",
        "plan_state",
        "target_fraction",
        "max_notional_eur",
        "reference_price_eur",
        "execution_plan_id",
        "capital_reservation_id",
        "reason",
    ]

    printable = []
    for row in rows:
        printable.append([
            "" if row["symbol"] is None else str(row["symbol"]),
            "" if row["selection_state"] is None else str(row["selection_state"]),
            "" if row["decision_state"] is None else str(row["decision_state"]),
            "" if row["execution_intent"] is None else str(row["execution_intent"]),
            "" if row["planner_action"] is None else str(row["planner_action"]),
            "" if row["desired_action"] is None else str(row["desired_action"]),
            "" if row["plan_state"] is None else str(row["plan_state"]),
            "" if row["target_fraction"] is None else str(row["target_fraction"]),
            "" if row["max_notional_eur"] is None else str(row["max_notional_eur"]),
            "" if row["reference_price_eur"] is None else str(row["reference_price_eur"]),
            "" if row["execution_plan_id"] is None else str(row["execution_plan_id"]),
            "" if row["capital_reservation_id"] is None else str(row["capital_reservation_id"]),
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

    planner_repo = ExecutionPlannerRepository()
    gate_repo = DecisionGateRepository()

    planner_config = ExecutionPlannerConfig(
        execution_mode=str(args.execution_mode),
        prepare_target_fraction=Decimal(str(args.prepare_target_fraction)),
        execute_target_fraction=Decimal(str(args.execute_target_fraction)),
        max_notional_eur=Decimal(str(args.max_notional_eur)),
        max_reprices=int(args.max_reprices),
        max_wait_seconds=int(args.max_wait_seconds),
        max_chase_bps=Decimal(str(args.max_chase_bps)),
        min_spread_bps_for_capture=Decimal(str(args.min_spread_bps_for_capture)),
        escalation_to_urgent_limit=bool(args.escalation_to_urgent_limit),
        abort_if_signal_invalidates=not bool(args.no_abort_if_signal_invalidates),
    )

    output_rows: list[dict[str, Any]] = []

    if args.plan_exit_symbol is not None or args.plan_exit_asset_id is not None:
        position = planner_repo.fetch_open_position_for_exit(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            venue=args.venue,
            asset_id=args.plan_exit_asset_id,
            symbol=args.plan_exit_symbol,
        )

        if position is None:
            output_rows.append(
                _planned_to_row(
                    None,
                    symbol=args.plan_exit_symbol,
                    selection_state=None,
                    decision_state=None,
                    execution_intent=None,
                    decision_reason="NO_OPEN_POSITION_FOR_EXIT",
                    planner_action="NONE",
                )
            )
        else:
            reference_price = planner_repo.fetch_reference_price_eur(
                asset_id=position.asset_id,
                venue=position.venue,
                interval_code="1h",
            )
            plan = build_exit_plan_from_position(
                position=position,
                config=planner_config,
                reference_price_eur=reference_price,
            )

            execution_plan_id = None
            if args.write_db:
                execution_plan_id = planner_repo.create_exit_plan_without_reservation(plan)

            output_rows.append(
                _planned_to_row(
                    plan,
                    symbol=args.plan_exit_symbol,
                    selection_state=None,
                    decision_state="EXIT_ALLOWED",
                    execution_intent="CLOSE_POSITION",
                    decision_reason="OPEN_POSITION_FOUND_FOR_EXIT",
                    execution_plan_id=execution_plan_id,
                    capital_reservation_id=None,
                    planner_action="EXIT_PLAN_CREATED" if args.write_db else "EXIT_PLAN_PREVIEW",
                )
            )
    else:
        gate_config = DecisionGateConfig(
            min_available_equity_eur=Decimal(str(args.min_available_equity_eur))
        )

        selection_rows = gate_repo.fetch_selection_rows(
            venue=args.venue,
            asset_id=args.asset_id,
            symbol=args.symbol,
            limit=args.limit,
        )
        sleeve_state = gate_repo.fetch_sleeve_state(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
        )

        for selection_row in selection_rows:
            duplicate_state = gate_repo.fetch_duplicate_state(
                account_id=args.account_id,
                sleeve_code=args.sleeve_code,
                asset_id=selection_row.asset_id,
                venue=selection_row.venue,
            )
            has_open_order = gate_repo.fetch_open_order_flag(
                account_id=args.account_id,
                sleeve_code=args.sleeve_code,
                asset_id=selection_row.asset_id,
                venue=selection_row.venue,
            )

            decision = evaluate_selection_for_account(
                row=selection_row,
                account_id=args.account_id,
                sleeve_code=args.sleeve_code,
                sleeve_state=sleeve_state,
                duplicate_state=duplicate_state,
                config=gate_config,
                has_open_order=has_open_order,
            )

            execution_plan_id = None
            capital_reservation_id = None
            planner_action = "NONE"
            plan = None

            if decision.execution_intent in {"PREPARE_PLAN", "PLACE_PASSIVE_LIMIT"} and decision.decision_state in {
                "PREPARE_ALLOWED",
                "EXECUTION_ALLOWED",
            }:
                reference_price = planner_repo.fetch_reference_price_eur(
                    asset_id=decision.asset_id,
                    venue=decision.venue,
                    interval_code="1h",
                )
                plan = build_execution_plan(
                    decision=decision,
                    config=planner_config,
                    reference_price_eur=reference_price,
                )

                if plan is not None and args.write_db:
                    execution_plan_id, capital_reservation_id = planner_repo.create_plan_with_reservation(plan)
                    planner_action = "PLAN_AND_RESERVATION_CREATED"
                elif plan is not None:
                    planner_action = "PLAN_PREVIEW"

            output_rows.append(
                _planned_to_row(
                    plan,
                    symbol=selection_row.symbol,
                    selection_state=selection_row.selection_state,
                    decision_state=decision.decision_state,
                    execution_intent=decision.execution_intent,
                    decision_reason=decision.decision_reason,
                    execution_plan_id=execution_plan_id,
                    capital_reservation_id=capital_reservation_id,
                    planner_action=planner_action,
                )
            )

    if args.output == "json":
        _print_json(output_rows)
    else:
        _print_table(output_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
