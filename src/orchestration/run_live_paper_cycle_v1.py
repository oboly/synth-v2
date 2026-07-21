from __future__ import annotations

"""
ENGINE: run_live_paper_cycle_v1
MODE: latest-only

INPUT:
- obs_market_candle
- selection_state
- execution_plan
- capital_reservation
- portfolio_position
- execution_event
- portfolio_sleeve
- synth_bt.config_set
- synth_bt.config_param

OUTPUT:
- selection_state
- execution_plan
- capital_reservation
- execution_event
- portfolio_position
- portfolio_sleeve

CLI:
python -m src.orchestration.run_live_paper_cycle_v1 \
  --account-id 1 \
  --sleeve-code SWING_STRUCTURAL \
  --venue bitvavo \
  --config-scope PAPER \
  --config-name paper_sw_baseline

HISTORICAL:
- not supported
- use backtest replay wrapper later

NOTES:
- single-shot runner
- no waiting loop
- reads strategy/policy/planner parameters from config registry
- selection rebuild can be skipped to use latest persisted selection only
- only PREPARE / BUY_READY rows may enter account-aware decision/planner checks
"""

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any

from src.common.db_env_v1 import load_database_environment


load_database_environment()


from src.common.db_core_v1 import db_cursor, get_connection  # noqa: E402
from src.config_registry.repository import ConfigRegistryRepository
from src.config_registry.loader import load_config_set
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


DEFAULT_SELECTION_CONFIG_PATH = "configs/selection_engine_v2.yaml"
ELIGIBLE_SELECTION_STATES = {"PREPARE", "BUY_READY"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one live paper cycle.")
    parser.add_argument("--selection-config", default=DEFAULT_SELECTION_CONFIG_PATH)
    parser.add_argument("--config-scope", default="PAPER")
    parser.add_argument("--config-name", required=True)

    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=40)

    parser.add_argument("--engine-name", default="selection_engine_v2")
    parser.add_argument("--engine-version", default="2.0")

    parser.add_argument("--skip-selection-rebuild", action="store_true")
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


def _ms_since(start_perf: float) -> int:
    return int((perf_counter() - start_perf) * 1000)


def _require_decimal(config_by_component: dict[str, dict[str, Any]], component: str, parameter_name: str) -> Decimal:
    value = config_by_component[component][parameter_name]
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _require_int(config_by_component: dict[str, dict[str, Any]], component: str, parameter_name: str) -> int:
    return int(config_by_component[component][parameter_name])


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
    cycle_start_perf = perf_counter()
    stage_timings_ms: dict[str, int] = {}

    stage_start = perf_counter()
    loaded_config = load_config_set(
        scope=args.config_scope,
        config_name=args.config_name,
        repository=ConfigRegistryRepository(connection_factory=get_connection),
    )
    cfg = loaded_config.config_by_component
    stage_timings_ms["config_load"] = _ms_since(stage_start)

    gate_repo = DecisionGateRepository(cursor_factory=db_cursor)
    planner_repo = ExecutionPlannerRepository(connection_factory=get_connection)
    executor_repo = ExecutorRepository(connection_factory=get_connection)
    lifecycle_repo = PlanLifecycleRepository(connection_factory=get_connection)

    cycle_stats = {
        "selection_written": 0,
        "exit_plans_created": 0,
        "entry_plans_created": 0,
        "entry_cooldown_blocked": 0,
        "executor_results": 0,
        "expired_count": 0,
        "lifecycle_results": 0,
        "selection_rows_total": 0,
        "selection_rows_eligible": 0,
        "config_set_id": loaded_config.config_set.config_set_id,
        "config_name": loaded_config.config_set.config_name,
        "selection_rebuilt": 0 if args.skip_selection_rebuild else 1,
    }

    stage_start = perf_counter()
    if not args.skip_selection_rebuild:
        selection_config = load_selection_config(args.selection_config)
        conn = get_connection()
        try:
            candidates = fetch_selection_candidates(
                conn,
                venue=args.venue,
                asset_id=args.asset_id,
                limit=args.limit,
            )
            rows = rank_candidates(candidates, selection_config)
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
    stage_timings_ms["selection"] = _ms_since(stage_start)

    stage_start = perf_counter()
    exit_results = run_exit_policy_v1(
        account_id=args.account_id,
        trading_account_id=args.trading_account_id,
        sleeve_code=args.sleeve_code,
        venue=args.venue,
        config=ExitPolicyConfig(
            take_profit_pct=_require_decimal(cfg, "exit_policy", "take_profit_pct"),
            stop_loss_pct=_require_decimal(cfg, "exit_policy", "stop_loss_pct"),
        ),
        connection_factory=get_connection,
    )
    cycle_stats["exit_plans_created"] = sum(1 for r in exit_results if r.exit_plan_created)
    stage_timings_ms["exit_policy"] = _ms_since(stage_start)

    stage_start = perf_counter()
    gate_config = DecisionGateConfig(
        min_available_equity_eur=_require_decimal(cfg, "planner", "max_notional_eur")
    )
    planner_config = ExecutionPlannerConfig(
        execution_mode="PAPER",
        trading_account_id=args.trading_account_id,
        action_type="PLACE_ORDER",
        requested_side="BUY",
        prepare_target_fraction=_require_decimal(cfg, "planner", "prepare_target_fraction"),
        execute_target_fraction=_require_decimal(cfg, "planner", "execute_target_fraction"),
        max_notional_eur=_require_decimal(cfg, "planner", "max_notional_eur"),
        max_reprices=_require_int(cfg, "planner", "max_reprices"),
        max_wait_seconds=_require_int(cfg, "planner", "max_wait_seconds"),
        max_chase_bps=_require_decimal(cfg, "planner", "max_chase_bps"),
        min_spread_bps_for_capture=_require_decimal(cfg, "planner", "min_spread_bps_for_capture"),
        escalation_to_urgent_limit=False,
        abort_if_signal_invalidates=True,
    )

    selection_rows = gate_repo.fetch_selection_rows(
        venue=args.venue,
        asset_id=args.asset_id,
        symbol=None,
        limit=args.limit,
    )
    cycle_stats["selection_rows_total"] = len(selection_rows)

    eligible_rows = [
        row for row in selection_rows
        if row.selection_state in ELIGIBLE_SELECTION_STATES
    ]
    cycle_stats["selection_rows_eligible"] = len(eligible_rows)

    if eligible_rows:
        sleeve_state = gate_repo.fetch_sleeve_state(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
        )

        for selection_row in eligible_rows:
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
                cooldown_candles_after_close=_require_int(cfg, "entry_cooldown", "cooldown_candles"),
                connection_factory=get_connection,
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

    stage_timings_ms["planner"] = _ms_since(stage_start)

    stage_start = perf_counter()
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
    stage_timings_ms["executor"] = _ms_since(stage_start)

    stage_start = perf_counter()
    if not args.dry_run:
        cycle_stats["expired_count"] = lifecycle_repo.expire_due_plans(
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
    stage_timings_ms["lifecycle"] = _ms_since(stage_start)

    stage_start = perf_counter()
    summary = fetch_live_summary(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
    )
    stage_timings_ms["summary"] = _ms_since(stage_start)

    stage_timings_ms["total_cycle"] = _ms_since(cycle_start_perf)

    return {
        "stats": cycle_stats,
        "summary": summary,
        "config_snapshot": loaded_config.snapshot_json_ready,
        "stage_timings_ms": stage_timings_ms,
    }


def main() -> int:
    args = parse_args()
    cycle_started = datetime.now(UTC).replace(tzinfo=None)
    latest_close_ts = fetch_latest_closed_candle_close_ts(
        venue=args.venue,
        interval_code="1h",
    )

    if latest_close_ts is None:
        print("cycle status=no_candle_data")
        return 0

    try:
        cycle_payload = run_single_cycle(args)
        stats = cycle_payload["stats"]
        summary = cycle_payload["summary"]
        timings = cycle_payload["stage_timings_ms"]

        print(
            f"cycle=1 "
            f"close_ts={latest_close_ts} "
            f"config_set_id={stats['config_set_id']} "
            f"config_name={stats['config_name']} "
            f"selection_rebuilt={stats['selection_rebuilt']} "
            f"selection={stats['selection_written']} "
            f"selection_rows_total={stats['selection_rows_total']} "
            f"selection_rows_eligible={stats['selection_rows_eligible']} "
            f"exit_plans={stats['exit_plans_created']} "
            f"entry_plans={stats['entry_plans_created']} "
            f"cooldown_blocked={stats['entry_cooldown_blocked']} "
            f"executor={stats['executor_results']} "
            f"expired={stats['expired_count']} "
            f"lifecycle={stats['lifecycle_results']} "
            f"active_plans={summary['active_plans']} "
            f"open_positions={summary['open_positions']} "
            f"reserved={_fmt_decimal(summary['reserved']) if summary['reserved'] is not None else ''} "
            f"deployed={_fmt_decimal(summary['deployed']) if summary['deployed'] is not None else ''} "
            f"available={_fmt_decimal(summary['available']) if summary['available'] is not None else ''} "
            f"last_event={summary['last_event_type'] or ''} "
            f"last_symbol={summary['last_event_symbol'] or ''} "
            f"timing_config_ms={timings['config_load']} "
            f"timing_selection_ms={timings['selection']} "
            f"timing_exit_ms={timings['exit_policy']} "
            f"timing_planner_ms={timings['planner']} "
            f"timing_executor_ms={timings['executor']} "
            f"timing_lifecycle_ms={timings['lifecycle']} "
            f"timing_summary_ms={timings['summary']} "
            f"timing_total_cycle_ms={timings['total_cycle']} "
            f"started={cycle_started}"
        )
        return 0

    except Exception as exc:
        print(
            f"cycle=1 close_ts={latest_close_ts} status=error "
            f"error={type(exc).__name__}:{exc}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
