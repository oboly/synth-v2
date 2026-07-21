from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Any

from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig
from src.decision_gate.repository import DecisionGateRepository
from src.execution_planner.execution_planner_v1 import build_execution_plan
from src.execution_planner.models import ExecutionPlannerConfig, PlannedExecution
from src.execution_planner.repository import ExecutionPlannerRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run execution_planner_v1 from latest selection + decision gate."
    )
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-available-equity-eur", default="25.00")
    parser.add_argument("--execution-mode", choices=("PAPER", "LIVE"), default="PAPER")
    parser.add_argument("--trading-account-id", type=int, default=None)
    parser.add_argument("--permission-evidence-id", type=int, default=None)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _build_output_row(
    *,
    symbol: str | None,
    selection_state: str | None,
    decision_state: str | None,
    execution_intent: str | None,
    planner_action: str,
    desired_action: str | None,
    plan_state: str | None,
    target_fraction: Decimal | None,
    execution_plan_id: int | None,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "selection_state": selection_state,
        "decision_state": decision_state,
        "execution_intent": execution_intent,
        "planner_action": planner_action,
        "desired_action": desired_action,
        "plan_state": plan_state,
        "target_fraction": target_fraction,
        "execution_plan_id": execution_plan_id,
        "reason": reason,
    }


def _row_from_plan(
    plan: PlannedExecution,
    *,
    symbol: str | None,
    selection_state: str | None,
    decision_state: str | None,
    execution_intent: str | None,
    planner_action: str,
    execution_plan_id: int | None,
    reason: str | None,
) -> dict[str, Any]:
    return _build_output_row(
        symbol=symbol,
        selection_state=selection_state,
        decision_state=decision_state,
        execution_intent=execution_intent,
        planner_action=planner_action,
        desired_action=plan.desired_action,
        plan_state=plan.plan_state,
        target_fraction=plan.target_fraction,
        execution_plan_id=execution_plan_id,
        reason=reason,
    )


def _is_stale_idle_preplan(existing_plan: dict[str, Any], decision: Any) -> bool:
    desired_action = str(existing_plan.get("desired_action", "")).upper()
    plan_state = str(existing_plan.get("plan_state", "")).upper()
    decision_state = str(getattr(decision, "decision_state", "")).upper()
    execution_intent = str(getattr(decision, "execution_intent", "")).upper()

    if desired_action != "PREPARE_PLAN":
        return False

    if plan_state != "IDLE":
        return False

    return decision_state == "NO_ACTION" or execution_intent == "NONE"


def _print_json(rows: list[dict[str, Any]]) -> None:
    print(
        json.dumps(
            [{k: _serialize_value(v) for k, v in row.items()} for row in rows],
            indent=2,
            ensure_ascii=False,
        )
    )


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
        "execution_plan_id",
        "reason",
    ]

    printable: list[list[str]] = []
    for row in rows:
        printable.append(
            [
                "" if row["symbol"] is None else str(row["symbol"]),
                "" if row["selection_state"] is None else str(row["selection_state"]),
                "" if row["decision_state"] is None else str(row["decision_state"]),
                "" if row["execution_intent"] is None else str(row["execution_intent"]),
                "" if row["planner_action"] is None else str(row["planner_action"]),
                "" if row["desired_action"] is None else str(row["desired_action"]),
                "" if row["plan_state"] is None else str(row["plan_state"]),
                "" if row["target_fraction"] is None else str(row["target_fraction"]),
                "" if row["execution_plan_id"] is None else str(row["execution_plan_id"]),
                "" if row["reason"] is None else str(row["reason"]),
            ]
        )

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    planner_repo = ExecutionPlannerRepository()
    gate_repo = DecisionGateRepository()

    if args.execution_mode == "LIVE" and (
        args.trading_account_id is None or args.permission_evidence_id is None
    ):
        raise SystemExit(
            "LIVE planning requires --trading-account-id and --permission-evidence-id"
        )
    planner_config = ExecutionPlannerConfig(
        execution_mode=args.execution_mode,
        trading_account_id=args.trading_account_id,
        decision_gate_permission_evidence_id=args.permission_evidence_id,
    )
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

    output_rows: list[dict[str, Any]] = []

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

        existing_plan = planner_repo.fetch_latest_active_plan(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=selection_row.asset_id,
            venue=selection_row.venue,
        )

        if existing_plan is not None:
            existing_plan_id = int(existing_plan["execution_plan_id"])

            if _is_stale_idle_preplan(existing_plan, decision):
                invalidation_reason = (
                    f"current_decision_state={decision.decision_state}; "
                    f"current_execution_intent={decision.execution_intent}; "
                    f"current_decision_reason={decision.decision_reason}"
                )

                cancelled_rows = 0
                if args.write_db:
                    cancelled_rows = planner_repo.cancel_stale_preplan(
                        execution_plan_id=existing_plan_id,
                        reason=invalidation_reason,
                    )

                output_rows.append(
                    _build_output_row(
                        symbol=selection_row.symbol,
                        selection_state=decision.selection_state,
                        decision_state=decision.decision_state,
                        execution_intent=decision.execution_intent,
                        planner_action=(
                            "CANCELLED_STALE_PREPLAN"
                            if args.write_db and cancelled_rows > 0
                            else "CANCEL_STALE_PREPLAN_PREVIEW"
                        ),
                        desired_action=str(existing_plan["desired_action"]),
                        plan_state="CANCELLED" if args.write_db and cancelled_rows > 0 else str(existing_plan["plan_state"]),
                        target_fraction=_serialize_value(existing_plan.get("target_fraction")),
                        execution_plan_id=existing_plan_id,
                        reason=decision.decision_reason,
                    )
                )
                continue

            if decision.decision_state == "PREPARE_ALLOWED":
                if args.write_db:
                    planner_repo.update_plan(
                        execution_plan_id=existing_plan_id,
                        plan=build_execution_plan(
                            decision,
                            planner_config,
                            reference_price_eur=planner_repo.fetch_reference_price_eur(
                                selection_row.asset_id, selection_row.venue
                            ),
                        ),
                    )

                output_rows.append(
                    _build_output_row(
                        symbol=selection_row.symbol,
                        selection_state=decision.selection_state,
                        decision_state=decision.decision_state,
                        execution_intent=decision.execution_intent,
                        planner_action="PROMOTED_PREPARE" if args.write_db else "PROMOTE_PREPARE_PREVIEW",
                        desired_action="PREPARE_PLAN",
                        plan_state=str(existing_plan["plan_state"]),
                        target_fraction=planner_config.prepare_target_fraction,
                        execution_plan_id=existing_plan_id,
                        reason="OK",
                    )
                )
                continue

            if decision.decision_state == "EXECUTION_ALLOWED":
                if args.write_db:
                    planner_repo.update_plan(
                        execution_plan_id=existing_plan_id,
                        plan=build_execution_plan(
                            decision,
                            planner_config,
                            reference_price_eur=planner_repo.fetch_reference_price_eur(
                                selection_row.asset_id, selection_row.venue
                            ),
                        ),
                    )

                output_rows.append(
                    _build_output_row(
                        symbol=selection_row.symbol,
                        selection_state=decision.selection_state,
                        decision_state=decision.decision_state,
                        execution_intent=decision.execution_intent,
                        planner_action="PROMOTED_EXECUTION" if args.write_db else "PROMOTE_EXECUTION_PREVIEW",
                        desired_action="SPREAD_CAPTURE_PASSIVE",
                        plan_state=str(existing_plan["plan_state"]),
                        target_fraction=planner_config.execute_target_fraction,
                        execution_plan_id=existing_plan_id,
                        reason="OK",
                    )
                )
                continue

            output_rows.append(
                _build_output_row(
                    symbol=selection_row.symbol,
                    selection_state=decision.selection_state,
                    decision_state=decision.decision_state,
                    execution_intent=decision.execution_intent,
                    planner_action="SKIPPED_EXISTING_PLAN",
                    desired_action=str(existing_plan["desired_action"]),
                    plan_state=str(existing_plan["plan_state"]),
                    target_fraction=_serialize_value(existing_plan.get("target_fraction")),
                    execution_plan_id=existing_plan_id,
                    reason="ACTIVE_PLAN_EXISTS",
                )
            )
            continue

        if decision.execution_intent not in {"PREPARE_PLAN", "PLACE_PASSIVE_LIMIT"}:
            output_rows.append(
                _build_output_row(
                    symbol=selection_row.symbol,
                    selection_state=decision.selection_state,
                    decision_state=decision.decision_state,
                    execution_intent=decision.execution_intent,
                    planner_action="NONE",
                    desired_action=None,
                    plan_state=None,
                    target_fraction=None,
                    execution_plan_id=None,
                    reason=decision.decision_reason,
                )
            )
            continue

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

        if plan is None:
            output_rows.append(
                _build_output_row(
                    symbol=selection_row.symbol,
                    selection_state=decision.selection_state,
                    decision_state=decision.decision_state,
                    execution_intent=decision.execution_intent,
                    planner_action="SKIPPED_POLICY_DISABLED",
                    desired_action=None,
                    plan_state=None,
                    target_fraction=None,
                    execution_plan_id=None,
                    reason="CONTEXT_POLICY_DISABLED",
                )
            )
            continue

        execution_plan_id = None
        planner_action = "PLAN_PREVIEW"

        if args.write_db:
            if decision.execution_intent == "PLACE_PASSIVE_LIMIT":
                execution_plan_id, _ = planner_repo.create_plan_with_reservation(plan)
                planner_action = "CREATED_EXECUTION_PLAN"
            else:
                execution_plan_id = planner_repo.create_plan_without_reservation(plan)
                planner_action = "CREATED_PREPLAN"

        output_rows.append(
            _row_from_plan(
                plan,
                symbol=selection_row.symbol,
                selection_state=decision.selection_state,
                decision_state=decision.decision_state,
                execution_intent=decision.execution_intent,
                planner_action=planner_action,
                execution_plan_id=execution_plan_id,
                reason=decision.decision_reason,
            )
        )

    if args.output == "json":
        _print_json(output_rows)
    else:
        _print_table(output_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
