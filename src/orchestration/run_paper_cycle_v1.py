from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db_env_v1 import load_database_environment


load_database_environment()


from src.common.db_core_v1 import db_cursor, get_connection  # noqa: E402
from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig
from src.decision_gate.repository import DecisionGateRepository
from src.execution_planner.execution_planner_v1 import build_execution_plan
from src.execution_planner.models import ExecutionPlannerConfig
from src.execution_planner.repository import ExecutionPlannerRepository
from src.executor.executor_v1 import execute_plan_paper
from src.executor.repository import ExecutorRepository
from src.plan_lifecycle.plan_lifecycle_v1 import process_releasable_plan
from src.plan_lifecycle.repository import PlanLifecycleRepository
from src.selection.run_selection_engine_v2 import (
    fetch_selection_candidates,
    write_selection_state_rows,
)
from src.selection.selection_engine_v2 import load_selection_config, rank_candidates


DEFAULT_CONFIG_PATH = "configs/selection_engine_v2.yaml"


def _fmt_decimal(value: Any, places: int = 10) -> str:
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except Exception:
            return str(value)
    q = Decimal("1." + ("0" * places))
    return format(value.quantize(q), "f")


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _fmt_decimal(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full paper cycle v1.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=40)

    parser.add_argument("--engine-name", default="selection_engine_v2")
    parser.add_argument("--engine-version", default="2.0")

    parser.add_argument("--min-available-equity-eur", default="25.00")
    parser.add_argument("--execution-mode", choices=("PAPER", "LIVE"), default="PAPER")
    parser.add_argument("--requested-side", choices=("BUY",), default="BUY")
    parser.add_argument("--prepare-target-fraction", default="0.06600000")
    parser.add_argument("--execute-target-fraction", default="0.06600000")
    parser.add_argument("--max-notional-eur", default="25.0000000000")
    parser.add_argument("--max-reprices", type=int, default=5)
    parser.add_argument("--max-wait-seconds", type=int, default=1800)
    parser.add_argument("--max-chase-bps", default="15.00000000")
    parser.add_argument("--min-spread-bps-for-capture", default="3.00000000")
    parser.add_argument("--escalation-to-urgent-limit", action="store_true")
    parser.add_argument("--no-abort-if-signal-invalidates", action="store_true")

    parser.add_argument("--skip-selection-write", action="store_true")
    parser.add_argument("--skip-planner", action="store_true")
    parser.add_argument("--skip-executor", action="store_true")
    parser.add_argument("--skip-lifecycle", action="store_true")

    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _print_json(payload: dict[str, Any]) -> None:
    def convert(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(v) for v in obj]
        return _serialize_value(obj)

    print(json.dumps(convert(payload), indent=2, ensure_ascii=False))


def _print_table(payload: dict[str, Any]) -> None:
    print("=== PAPER CYCLE SUMMARY ===")
    print(f"selection_written={payload['summary']['selection_written']}")
    print(f"plans_created={payload['summary']['plans_created']}")
    print(f"executor_results={payload['summary']['executor_results']}")
    print(f"lifecycle_results={payload['summary']['lifecycle_results']}")
    print()

    print("=== PLANNER RESULTS ===")
    headers = [
        "symbol",
        "selection_state",
        "selection_bias",
        "selection_score",
        "decision_state",
        "execution_intent",
        "planner_action",
        "desired_action",
        "plan_state",
        "execution_plan_id",
        "reason",
    ]
    rows = payload["planner_results"]

    widths = [len(h) for h in headers]
    printable: list[list[str]] = []
    for row in rows:
        vals = [
            "" if row.get("symbol") is None else str(row.get("symbol")),
            "" if row.get("selection_state") is None else str(row.get("selection_state")),
            "" if row.get("selection_bias") is None else str(row.get("selection_bias")),
            "" if row.get("selection_score") is None else _fmt_decimal(row.get("selection_score"), 6),
            "" if row.get("decision_state") is None else str(row.get("decision_state")),
            "" if row.get("execution_intent") is None else str(row.get("execution_intent")),
            "" if row.get("planner_action") is None else str(row.get("planner_action")),
            "" if row.get("desired_action") is None else str(row.get("desired_action")),
            "" if row.get("plan_state") is None else str(row.get("plan_state")),
            "" if row.get("execution_plan_id") is None else str(row.get("execution_plan_id")),
            "" if row.get("reason") is None else str(row.get("reason")),
        ]
        printable.append(vals)
        for idx, value in enumerate(vals):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str], w: list[int]) -> str:
        return " | ".join(v.ljust(w[i]) for i, v in enumerate(values))

    print(fmt(headers, widths))
    print("-+-".join("-" * x for x in widths))
    for row in printable:
        print(fmt(row, widths))
    print()

    print("=== EXECUTOR RESULTS ===")
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
    rows = payload["executor_results"]
    widths = [len(h) for h in headers]
    printable = []
    for row in rows:
        vals = [
            "" if row.get("execution_plan_id") is None else str(row.get("execution_plan_id")),
            "" if row.get("symbol") is None else str(row.get("symbol")),
            "" if row.get("desired_action") is None else str(row.get("desired_action")),
            "" if row.get("old_plan_state") is None else str(row.get("old_plan_state")),
            "" if row.get("new_plan_state") is None else str(row.get("new_plan_state")),
            "" if row.get("event_type") is None else str(row.get("event_type")),
            "" if row.get("fill_price_eur") is None else _fmt_decimal(row.get("fill_price_eur")),
            "" if row.get("fill_qty") is None else _fmt_decimal(row.get("fill_qty"), 10),
            "" if row.get("reservation_released") is None else str(row.get("reservation_released")),
            "" if row.get("position_opened") is None else str(row.get("position_opened")),
        ]
        printable.append(vals)
        for idx, value in enumerate(vals):
            widths[idx] = max(widths[idx], len(value))

    print(fmt(headers, widths))
    print("-+-".join("-" * x for x in widths))
    for row in printable:
        print(fmt(row, widths))
    print()

    print("=== LIFECYCLE RESULTS ===")
    headers = [
        "execution_plan_id",
        "symbol",
        "old_plan_state",
        "reservation_released",
        "released_amount_eur",
        "reason",
    ]
    rows = payload["lifecycle_results"]
    widths = [len(h) for h in headers]
    printable = []
    for row in rows:
        vals = [
            "" if row.get("execution_plan_id") is None else str(row.get("execution_plan_id")),
            "" if row.get("symbol") is None else str(row.get("symbol")),
            "" if row.get("old_plan_state") is None else str(row.get("old_plan_state")),
            "" if row.get("reservation_released") is None else str(row.get("reservation_released")),
            "" if row.get("released_amount_eur") is None else _fmt_decimal(row.get("released_amount_eur")),
            "" if row.get("reason") is None else str(row.get("reason")),
        ]
        printable.append(vals)
        for idx, value in enumerate(vals):
            widths[idx] = max(widths[idx], len(value))

    print(fmt(headers, widths))
    print("-+-".join("-" * x for x in widths))
    for row in printable:
        print(fmt(row, widths))


def main() -> int:
    args = parse_args()
    if args.requested_side == "SELL":
        print(
            "[BLOCKED] Generic PAPER cycle is BUY-only. "
            "Route manual SELL through manual_execution_service_v1.process()."
        )
        return 2

    gate_repo = DecisionGateRepository(cursor_factory=db_cursor)
    planner_repo = ExecutionPlannerRepository(connection_factory=get_connection)
    executor_repo = ExecutorRepository(connection_factory=get_connection)
    lifecycle_repo = PlanLifecycleRepository(connection_factory=get_connection)

    summary = {
        "selection_written": 0,
        "plans_created": 0,
        "executor_results": 0,
        "lifecycle_results": 0,
    }

    planner_results: list[dict[str, Any]] = []
    executor_results: list[dict[str, Any]] = []
    lifecycle_results: list[dict[str, Any]] = []

    if not args.skip_selection_write:
        config = load_selection_config(args.config)
        conn = get_connection()
        try:
            candidates = fetch_selection_candidates(
                conn,
                venue=args.venue,
                asset_id=args.asset_id,
                limit=args.limit,
            )
            rows = rank_candidates(candidates, config)
            run_asof_ts_utc = datetime.now(UTC).replace(tzinfo=None)
            summary["selection_written"] = write_selection_state_rows(
                conn,
                rows=rows,
                run_asof_ts_utc=run_asof_ts_utc,
                engine_name=str(args.engine_name),
                engine_version=str(args.engine_version),
            )
        finally:
            conn.close()

    if not args.skip_planner:
        gate_config = DecisionGateConfig(
            min_available_equity_eur=Decimal(str(args.min_available_equity_eur))
        )
        planner_config = ExecutionPlannerConfig(
            execution_mode=str(args.execution_mode),
            trading_account_id=args.trading_account_id,
            action_type="PLACE_ORDER",
            requested_side=args.requested_side,
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

        selection_rows = gate_repo.fetch_selection_rows(
            venue=args.venue,
            asset_id=args.asset_id,
            symbol=None,
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
                if plan is not None:
                    execution_plan_id, capital_reservation_id = planner_repo.create_plan_with_reservation(plan)
                    planner_action = "PLAN_AND_RESERVATION_CREATED"
                    summary["plans_created"] += 1

            planner_results.append(
                {
                    "symbol": selection_row.symbol,
                    "selection_state": selection_row.selection_state,
                    "selection_bias": selection_row.selection_bias,
                    "selection_score": selection_row.effective_selection_score,
                    "decision_state": decision.decision_state,
                    "execution_intent": decision.execution_intent,
                    "planner_action": planner_action,
                    "desired_action": None if plan is None else plan.desired_action,
                    "plan_state": None if plan is None else plan.plan_state,
                    "execution_plan_id": execution_plan_id,
                    "capital_reservation_id": capital_reservation_id,
                    "reason": decision.decision_reason,
                }
            )

    if not args.skip_executor:
        plans = executor_repo.fetch_open_plans(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            venue=args.venue,
            limit=args.limit,
        )
        for plan in plans:
            result = execute_plan_paper(plan, executor_repo)
            executor_results.append(asdict(result))
        summary["executor_results"] = len(executor_results)

    if not args.skip_lifecycle:
        lifecycle_repo.expire_due_plans(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            venue=args.venue,
        )
        releasable_plans = lifecycle_repo.fetch_releasable_plans(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            venue=args.venue,
            limit=args.limit,
        )
        for plan in releasable_plans:
            result = process_releasable_plan(plan, lifecycle_repo)
            lifecycle_results.append(asdict(result))
        summary["lifecycle_results"] = len(lifecycle_results)

    payload = {
        "summary": summary,
        "planner_results": planner_results,
        "executor_results": executor_results,
        "lifecycle_results": lifecycle_results,
    }

    if args.output == "json":
        _print_json(payload)
    else:
        _print_table(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
