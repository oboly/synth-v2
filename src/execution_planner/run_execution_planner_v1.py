from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig
from src.decision_gate.repository import DecisionGateRepository
from src.execution_planner.execution_planner_v1 import (
    build_execution_plan,
)
from src.execution_planner.models import ExecutionPlannerConfig, PlannedExecution
from src.execution_planner.repository import ExecutionPlannerRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args()


def _row(plan, symbol, decision, action, reason, plan_id=None):
    return {
        "symbol": symbol,
        "selection_state": decision.selection_state,
        "decision_state": decision.decision_state,
        "execution_intent": decision.execution_intent,
        "planner_action": action,
        "desired_action": None if not plan else plan.desired_action,
        "plan_state": None if not plan else plan.plan_state,
        "target_fraction": None if not plan else plan.target_fraction,
        "execution_plan_id": plan_id,
        "reason": reason,
    }


def main() -> int:
    args = parse_args()

    planner_repo = ExecutionPlannerRepository()
    gate_repo = DecisionGateRepository()

    planner_config = ExecutionPlannerConfig()
    gate_config = DecisionGateConfig()

    selection_rows = gate_repo.fetch_selection_rows(
        venue=args.venue,
        asset_id=args.asset_id,
        limit=args.limit,
    )

    sleeve_state = gate_repo.fetch_sleeve_state(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
    )

    rows = []

    for s in selection_rows:

        decision = evaluate_selection_for_account(
            row=s,
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            sleeve_state=sleeve_state,
            duplicate_state=gate_repo.fetch_duplicate_state(
                account_id=args.account_id,
                sleeve_code=args.sleeve_code,
                asset_id=s.asset_id,
                venue=s.venue,
            ),
            config=gate_config,
        )

        existing = planner_repo.fetch_latest_active_plan(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=s.asset_id,
            venue=s.venue,
        )

        # ---------------------------
        # PROMOTION LOGIC
        # ---------------------------
        if existing:

            if decision.decision_state == "PREPARE_ALLOWED":
                planner_repo.update_plan(
                    execution_plan_id=existing["execution_plan_id"],
                    target_fraction=planner_config.prepare_target_fraction,
                    desired_action="PREPARE_PLAN",
                    notes="PROMOTED_TO_PREPARE",
                )
                rows.append(_row(None, s.symbol, decision, "PROMOTED_PREPARE", "OK"))
                continue

            if decision.decision_state == "EXECUTION_ALLOWED":
                planner_repo.update_plan(
                    execution_plan_id=existing["execution_plan_id"],
                    target_fraction=planner_config.execute_target_fraction,
                    desired_action="SPREAD_CAPTURE_PASSIVE",
                    notes="PROMOTED_TO_EXECUTION",
                )
                rows.append(_row(None, s.symbol, decision, "PROMOTED_EXECUTION", "OK"))
                continue

            rows.append(_row(None, s.symbol, decision, "SKIPPED_EXISTING_PLAN", "ACTIVE_PLAN_EXISTS"))
            continue

        # ---------------------------
        # NEW PLAN CREATION
        # ---------------------------
        if decision.execution_intent in {"PREPARE_PLAN", "PLACE_PASSIVE_LIMIT"}:

            reference_price = planner_repo.fetch_reference_price_eur(
                asset_id=s.asset_id,
                venue=s.venue,
            )

            plan = build_execution_plan(
                decision=decision,
                config=planner_config,
                reference_price_eur=reference_price,
            )

            plan_id = None

            if plan and args.write_db:

                if decision.execution_intent == "PLACE_PASSIVE_LIMIT":
                    plan_id, _ = planner_repo.create_plan_with_reservation(plan)
                    action = "CREATED_EXECUTION_PLAN"

                else:
                    plan_id = planner_repo.create_plan_without_reservation(plan)
                    action = "CREATED_PREPLAN"

            else:
                action = "PLAN_PREVIEW"

            rows.append(_row(plan, s.symbol, decision, action, decision.decision_reason, plan_id))

    # print simple table
    for r in rows:
        print(r)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

