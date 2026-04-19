from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
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
from src.policy.entry_cooldown_v1 import evaluate_entry_cooldown
from src.policy.exit_policy_v1 import ExitPolicyConfig, run_exit_policy_v1
from src.selection.run_selection_engine_v2 import (
    fetch_selection_candidates,
    write_selection_state_rows,
)
from src.selection.selection_engine_v2 import load_selection_config, rank_candidates


DEFAULT_CONFIG_PATH = "configs/selection_engine_v2.yaml"
RUNNER_NAME = "live_paper_loop_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live paper loop v1 on new closed 1h candles.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=40)

    parser.add_argument("--engine-name", default="selection_engine_v2")
    parser.add_argument("--engine-version", default="2.0")

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

    parser.add_argument("--take-profit-pct", default="0.020000")
    parser.add_argument("--stop-loss-pct", default="0.010000")
    parser.add_argument("--entry-cooldown-candles", type=int, default=2)

    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--waiting-log-every-polls", type=int, default=12)
    parser.add_argument("--max-cycles", type=int, default=0, help="0 = infinite")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _fmt_decimal(value: Any, places: int = 6) -> str:
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except Exception:
            return str(value)
    q = Decimal("1." + ("0" * places))
    return format(value.quantize(q), "f")


def _scope_key(args: argparse.Namespace) -> str:
    return f"account={args.account_id}|sleeve={args.sleeve_code}|venue={args.venue}"


def load_last_processed_close_ts(*, scope_key: str) -> datetime | None:
    sql = """
    SELECT last_processed_close_ts_utc
    FROM runtime_state
    WHERE runner_name = %s
      AND scope_key = %s
    LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [RUNNER_NAME, scope_key])
            row = cur.fetchone()
            if not row:
                return None
            return row["last_processed_close_ts_utc"]
    finally:
        conn.close()


def save_last_processed_close_ts(
    *,
    scope_key: str,
    last_processed_close_ts_utc: datetime,
    state_json: dict[str, Any] | None = None,
) -> None:
    sql = """
    INSERT INTO runtime_state (
        runner_name,
        scope_key,
        last_processed_close_ts_utc,
        state_json
    ) VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        last_processed_close_ts_utc = VALUES(last_processed_close_ts_utc),
        state_json = VALUES(state_json),
        updated_ts_utc = CURRENT_TIMESTAMP(6)
    """
    payload = None if state_json is None else json.dumps(state_json, ensure_ascii=False)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [RUNNER_NAME, scope_key, last_processed_close_ts_utc, payload])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_latest_closed_candle_close_ts(*, venue: str, interval_code: str = "1h") -> datetime | None:
    sql = """
    SELECT MAX(close_ts_utc) AS max_close_ts_utc
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [venue, interval_code])
            row = cur.fetchone()
            if not row:
                return None
            return row["max_close_ts_utc"]
    finally:
        conn.close()


def fetch_live_summary(*, account_id: int, sleeve_code: str) -> dict[str, Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    reserved_equity_eur,
                    deployed_equity_eur,
                    available_equity_eur
                FROM portfolio_sleeve
                WHERE account_id = %s
                  AND sleeve_code = %s
                LIMIT 1
                """,
                [account_id, sleeve_code],
            )
            sleeve = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM execution_plan
                WHERE account_id = %s
                  AND sleeve_code = %s
                  AND plan_state IN ('IDLE','PLANNED')
                """,
                [account_id, sleeve_code],
            )
            active_plans = int(cur.fetchone()["n"])

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM portfolio_position
                WHERE account_id = %s
                  AND sleeve_code = %s
                  AND position_status = 'OPEN'
                  AND qty > 0
                """,
                [account_id, sleeve_code],
            )
            open_positions = int(cur.fetchone()["n"])

            cur.execute(
                """
                SELECT
                    ee.event_type,
                    a.symbol
                FROM execution_event ee
                JOIN asset a
                  ON a.asset_id = ee.asset_id
                WHERE ee.account_id = %s
                  AND ee.sleeve_code = %s
                ORDER BY ee.execution_event_id DESC
                LIMIT 1
                """,
                [account_id, sleeve_code],
            )
            last_event = cur.fetchone()

        return {
            "reserved": None if not sleeve else sleeve["reserved_equity_eur"],
            "deployed": None if not sleeve else sleeve["deployed_equity_eur"],
            "available": None if not sleeve else sleeve["available_equity_eur"],
            "active_plans": active_plans,
            "open_positions": open_positions,
            "last_event_type": None if not last_event else last_event["event_type"],
            "last_event_symbol": None if not last_event else last_event["symbol"],
        }
    finally:
        conn.close()


def run_single_cycle(args: argparse.Namespace) -> dict[str, Any]:
    gate_repo = DecisionGateRepository()
    planner_repo = ExecutionPlannerRepository()
    executor_repo = ExecutorRepository()
    lifecycle_repo = PlanLifecycleRepository()

    cycle_stats = {
        "selection_written": 0,
        "exit_plans_created": 0,
        "entry_plans_created": 0,
        "entry_cooldown_blocked": 0,
        "executor_results": 0,
        "lifecycle_results": 0,
        "eligible_count": 0,
    }

    # 1. selection write
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
        if not args.dry_run:
            cycle_stats["selection_written"] = write_selection_state_rows(
                conn,
                rows=rows,
                run_asof_ts_utc=run_asof_ts_utc,
                engine_name=str(args.engine_name),
                engine_version=str(args.engine_version),
            )
        else:
            cycle_stats["selection_written"] = len(rows)
    finally:
        conn.close()

    # 2. exit policy
    exit_results = run_exit_policy_v1(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
        venue=args.venue,
        config=ExitPolicyConfig(
            take_profit_pct=Decimal(str(args.take_profit_pct)),
            stop_loss_pct=Decimal(str(args.stop_loss_pct)),
        ),
    )
    cycle_stats["exit_plans_created"] = sum(1 for r in exit_results if r.exit_plan_created)

    # 3. entry planner
    gate_config = DecisionGateConfig(
        min_available_equity_eur=Decimal(str(args.min_available_equity_eur))
    )
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
        if selection_row.selection_state in {"PREPARE", "BUY_READY"}:
            cycle_stats["eligible_count"] += 1

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

        if decision.execution_intent not in {"PREPARE_PLAN", "PLACE_PASSIVE_LIMIT"}:
            continue
        if decision.decision_state not in {"PREPARE_ALLOWED", "EXECUTION_ALLOWED"}:
            continue

        cooldown = evaluate_entry_cooldown(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            venue=selection_row.venue,
            asset_id=selection_row.asset_id,
            symbol=selection_row.symbol,
            cooldown_candles_after_close=args.entry_cooldown_candles,
        )
        if cooldown.cooldown_blocked:
            cycle_stats["entry_cooldown_blocked"] += 1
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
            continue

        if not args.dry_run:
            planner_repo.create_plan_with_reservation(plan)
        cycle_stats["entry_plans_created"] += 1

    # 4. executor
    plans = executor_repo.fetch_open_plans(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
        venue=args.venue,
        limit=args.limit,
    )
    for plan in plans:
        if not args.dry_run:
            execute_plan_paper(plan, executor_repo)
        cycle_stats["executor_results"] += 1

    # 5. lifecycle
    if not args.dry_run:
        invalidatable_plans = lifecycle_repo.fetch_invalidatable_active_plans(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            venue=args.venue,
            limit=args.limit,
        )
        for plan in invalidatable_plans:
            lifecycle_repo.invalidate_plan_for_selection_drop(plan)

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
            process_releasable_plan(plan, lifecycle_repo)
            cycle_stats["lifecycle_results"] += 1

    return cycle_stats


def main() -> int:
    args = parse_args()
    scope_key = _scope_key(args)

    last_processed_close_ts = load_last_processed_close_ts(scope_key=scope_key)
    cycle_no = 0

    wait_poll_counter = 0
    last_wait_key: tuple[datetime | None, datetime | None] | None = None

    while True:
        latest_close_ts = fetch_latest_closed_candle_close_ts(
            venue=args.venue,
            interval_code="1h",
        )

        if latest_close_ts is None:
            print("live_loop status=no_candle_data")
            time.sleep(args.poll_seconds)
            continue

        if last_processed_close_ts is not None and latest_close_ts <= last_processed_close_ts:
            wait_poll_counter += 1
            wait_key = (latest_close_ts, last_processed_close_ts)
            should_log_wait = (
                last_wait_key != wait_key
                or wait_poll_counter == 1
                or wait_poll_counter % max(1, args.waiting_log_every_polls) == 0
            )
            if should_log_wait:
                print(
                    f"live_loop status=waiting latest_close_ts={latest_close_ts} "
                    f"last_processed_close_ts={last_processed_close_ts} "
                    f"polls_waited={wait_poll_counter}"
                )
            last_wait_key = wait_key
            time.sleep(args.poll_seconds)
            continue

        wait_poll_counter = 0
        last_wait_key = None

        cycle_no += 1
        cycle_started = datetime.now(UTC).replace(tzinfo=None)

        try:
            stats = run_single_cycle(args)
            summary = fetch_live_summary(
                account_id=args.account_id,
                sleeve_code=args.sleeve_code,
            )
            print(
                f"cycle={cycle_no} "
                f"close_ts={latest_close_ts} "
                f"selection={stats['selection_written']} "
                f"eligible={stats['eligible_count']} "
                f"exit_plans={stats['exit_plans_created']} "
                f"entry_plans={stats['entry_plans_created']} "
                f"cooldown_blocked={stats['entry_cooldown_blocked']} "
                f"executor={stats['executor_results']} "
                f"lifecycle={stats['lifecycle_results']} "
                f"active_plans={summary['active_plans']} "
                f"open_positions={summary['open_positions']} "
                f"reserved={_fmt_decimal(summary['reserved']) if summary['reserved'] is not None else ''} "
                f"deployed={_fmt_decimal(summary['deployed']) if summary['deployed'] is not None else ''} "
                f"available={_fmt_decimal(summary['available']) if summary['available'] is not None else ''} "
                f"last_event={summary['last_event_type'] or ''} "
                f"last_symbol={summary['last_event_symbol'] or ''} "
                f"started={cycle_started}"
            )
            if not args.dry_run:
                save_last_processed_close_ts(
                    scope_key=scope_key,
                    last_processed_close_ts_utc=latest_close_ts,
                    state_json={
                        "cycle_no": cycle_no,
                        "latest_close_ts": latest_close_ts.isoformat(sep=" "),
                        "stats": stats,
                    },
                )
            last_processed_close_ts = latest_close_ts
        except Exception as exc:
            print(
                f"cycle={cycle_no} close_ts={latest_close_ts} status=error "
                f"error={type(exc).__name__}:{exc}"
            )

        if args.max_cycles > 0 and cycle_no >= args.max_cycles:
            break

        time.sleep(args.poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
