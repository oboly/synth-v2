from __future__ import annotations

"""
Synth v2 - Paper Candidate Execution Planner Preview V1.

LAYER:
research / paper-candidate planner preview

BOUNDARY:
Allowed:
- read validated paper-candidate staging rows
- run the existing decision_gate as a read-only preview
- call build_execution_plan for preview only
- fetch point-in-time entry reference price from the staged source replay table
- print deterministic preview output

Forbidden:
- decision_state writes
- execution_intent writes
- execution_plan writes
- capital reservation writes
- executor calls
- broker/exchange actions
- order handling
- database writes

Purpose:
Preview how validated staged paper candidates would flow through decision_gate
and execution_planner without creating plans or touching execution.
"""

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime
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
from src.research.run_paper_candidate_decision_gate_preview_v1 import (
    DEFAULT_DATABASE,
    DEFAULT_POLICY_NAME,
    DEFAULT_SIGNAL_STATUS,
    DEFAULT_TABLE,
    fetch_staged_candidates,
    staged_candidate_to_selection_input,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview execution_planner outcomes for staged paper candidates without writes."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--min-available-equity-eur", default="25.00")
    parser.add_argument(
        "--reference-interval",
        default="1h",
        help="Compatibility only. Paper-candidate previews use source replay entry_close_price.",
    )
    parser.add_argument(
        "--execution-regime-override",
        choices=("TREND_UP", "RANGE", "TREND_DOWN"),
        default=None,
        help="Diagnostic only: override decision.regime_label_4h for planner-context testing.",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def plan_to_dict(plan: Any) -> dict[str, Any] | None:
    if plan is None:
        return None
    return asdict(plan)


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        out[value] = out.get(value, 0) + 1
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows_total": len(rows),
        "symbols": len({row["symbol"] for row in rows}),
        "decision_counts": count_by(rows, "decision_state"),
        "execution_intent_counts": count_by(rows, "execution_intent"),
        "planner_action_counts": count_by(rows, "planner_action"),
        "desired_action_counts": count_by(rows, "desired_action"),
        "plan_state_counts": count_by(rows, "plan_state"),
    }


ALLOWED_REFERENCE_SOURCE_TABLES = frozenset(
    {
        "bt_selection_v2_replay_eval_horizon_v1",
        "bt_selection_v2_replay_eval_horizon_v2",
    }
)


def validate_reference_source_table(source_table: str) -> str:
    if source_table not in ALLOWED_REFERENCE_SOURCE_TABLES:
        allowed = ", ".join(sorted(ALLOWED_REFERENCE_SOURCE_TABLES))
        raise ValueError(f"Unsupported reference source table: {source_table}. Allowed: {allowed}")
    return source_table


def fetch_staged_reference_price_eur(
    *,
    database: str,
    source_table: str,
    source_replay_id: int | None,
) -> Decimal | None:
    if source_replay_id is None:
        return None

    safe_table = validate_reference_source_table(source_table)
    sql = f"""
    SELECT entry_close_price
    FROM {safe_table}
    WHERE bt_selection_v2_replay_id = %s
    LIMIT 1
    """

    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [source_replay_id])
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return None

    value = row["entry_close_price"] if isinstance(row, dict) else row[0]
    if value is None:
        return None

    return Decimal(str(value))


def preview_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    gate_repo = DecisionGateRepository(cursor_factory=db_cursor)

    staged_rows = fetch_staged_candidates(args)
    sleeve_state = gate_repo.fetch_sleeve_state(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
    )

    gate_config = DecisionGateConfig(
        min_available_equity_eur=Decimal(str(args.min_available_equity_eur))
    )
    planner_config = ExecutionPlannerConfig(
        execution_mode="PAPER",
        trading_account_id=args.trading_account_id,
        action_type="PLACE_ORDER",
        requested_side="BUY",
    )

    out: list[dict[str, Any]] = []

    for staged in staged_rows:
        selection_row = staged_candidate_to_selection_input(staged)
        if args.execution_regime_override is not None:
            selection_row = replace(
                selection_row,
                regime_label_4h=args.execution_regime_override,
            )

        duplicate_state = gate_repo.fetch_duplicate_state(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=staged.asset_id,
            venue=staged.venue,
        )
        has_open_order = gate_repo.fetch_open_order_flag(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=staged.asset_id,
            venue=staged.venue,
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

        reference_price_eur = None
        plan = None
        planner_action = "DECISION_GATE_BLOCKED"

        if decision.execution_intent in {"PREPARE_PLAN", "PLACE_PASSIVE_LIMIT"}:
            reference_price_eur = fetch_staged_reference_price_eur(
                database=args.database,
                source_table=staged.source_table,
                source_replay_id=staged.source_replay_id,
            )
            plan = build_execution_plan(
                decision=decision,
                config=planner_config,
                reference_price_eur=reference_price_eur,
            )
            planner_action = "PLAN_PREVIEW" if plan is not None else "SKIPPED_POLICY_DISABLED"

        out.append(
            {
                "candidate_id": staged.candidate_id,
                "load_batch_id": staged.load_batch_id,
                "source_replay_id": staged.source_replay_id,
                "symbol": staged.symbol,
                "asset_id": staged.asset_id,
                "venue": staged.venue,
                "asof_ts_utc": staged.asof_ts_utc,
                "policy_name": staged.policy_name,
                "policy_version": staged.policy_version,
                "signal_status": staged.signal_status,
                "selection_state": staged.selection_state,
                "priority_rank": staged.priority_rank,
                "selection_score": staged.selection_score,
                "simulated_net_return": staged.simulated_net_return,
                "account_id": args.account_id,
                "sleeve_code": args.sleeve_code,
                "decision_state": decision.decision_state,
                "decision_reason": decision.decision_reason,
                "execution_intent": decision.execution_intent,
                "available_equity_eur": decision.available_equity_eur,
                "has_active_plan": decision.has_active_plan,
                "has_open_position": decision.has_open_position,
                "has_open_order": has_open_order,
                "reference_price_eur": reference_price_eur,
                "execution_regime_override": args.execution_regime_override,
                "effective_regime_label_4h": selection_row.regime_label_4h,
                "planner_action": planner_action,
                "desired_action": None if plan is None else plan.desired_action,
                "plan_state": None if plan is None else plan.plan_state,
                "target_fraction": None if plan is None else plan.target_fraction,
                "max_notional_eur": None if plan is None else plan.max_notional_eur,
                "max_reprices": None if plan is None else plan.max_reprices,
                "max_wait_seconds": None if plan is None else plan.max_wait_seconds,
                "max_chase_bps": None if plan is None else plan.max_chase_bps,
                "notes": None if plan is None else plan.notes,
                "plan_preview": plan_to_dict(plan),
            }
        )

    return out


def print_table(rows: list[dict[str, Any]]) -> None:
    print("Paper candidate execution-planner preview")
    summary = summarize(rows)
    for key, value in summary.items():
        print(f"{key}: {value}")

    print()
    print(
        "candidate_id | ts | symbol | decision_state | execution_intent | "
        "planner_action | desired_action | plan_state | target_fraction | ref_price | reason"
    )
    print("-" * 170)

    for row in rows:
        print(
            f"{row['candidate_id']} | "
            f"{row['asof_ts_utc']} | "
            f"{row['symbol']} | "
            f"{row['decision_state']} | "
            f"{row['execution_intent']} | "
            f"{row['planner_action']} | "
            f"{row['desired_action']} | "
            f"{row['plan_state']} | "
            f"{row['target_fraction']} | "
            f"{row['reference_price_eur']} | "
            f"{row['decision_reason']}"
        )


def main() -> int:
    args = parse_args()
    rows = preview_rows(args)
    payload = {
        "summary": summarize(rows),
        "rows": rows,
    }

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
