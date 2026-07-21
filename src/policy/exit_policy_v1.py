from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.execution_planner.execution_planner_v1 import build_exit_plan_from_position
from src.execution_planner.models import ExecutionPlannerConfig, OpenPositionForExit
from src.execution_planner.repository import ExecutionPlannerRepository


ACTIVE_EXIT_PLAN_STATES = {"IDLE", "PLANNED", "PLACED", "MONITOR_QUEUE", "REPRICE_PENDING", "ESCALATED"}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class ExitPolicyConfig:
    take_profit_pct: Decimal
    stop_loss_pct: Decimal
    price_interval_code: str = "1h"


@dataclass(frozen=True)
class ExitPolicyResult:
    symbol: str
    asset_id: int
    trigger_state: str
    trigger_reason: str
    current_price_eur: Decimal
    avg_entry_price_eur: Decimal
    pnl_pct: Decimal
    exit_plan_created: bool
    execution_plan_id: int | None


def fetch_open_positions_for_policy(
    *,
    account_id: int,
    sleeve_code: str,
    venue: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        pp.portfolio_position_id,
        pp.account_id,
        pp.sleeve_code,
        pp.asset_id,
        pp.venue,
        pp.qty,
        pp.avg_entry_price,
        pp.mark_price,
        pp.market_value_eur,
        pp.realized_pnl_eur,
        pp.unrealized_pnl_eur,
        pp.position_status,
        a.symbol
    FROM portfolio_position pp
    JOIN asset a
      ON a.asset_id = pp.asset_id
    WHERE pp.account_id = %s
      AND pp.sleeve_code = %s
      AND pp.venue = %s
      AND pp.position_status = 'OPEN'
      AND pp.qty > 0
    ORDER BY pp.portfolio_position_id ASC
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [account_id, sleeve_code, venue])
            rows = cur.fetchall() or []
            return rows
    finally:
        conn.close()


def has_active_exit_plan(
    *,
    account_id: int,
    sleeve_code: str,
    venue: str,
    asset_id: int,
) -> bool:
    states_sql = ",".join(["%s"] * len(ACTIVE_EXIT_PLAN_STATES))
    params: list[Any] = [
        account_id,
        sleeve_code,
        venue,
        asset_id,
        "CLOSE_POSITION_MARKET_PAPER",
        *sorted(ACTIVE_EXIT_PLAN_STATES),
    ]

    sql = f"""
    SELECT EXISTS(
        SELECT 1
        FROM execution_plan
        WHERE account_id = %s
          AND sleeve_code = %s
          AND venue = %s
          AND asset_id = %s
          AND desired_action = %s
          AND plan_state IN ({states_sql})
    ) AS has_active_exit_plan
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return False
            return bool(row["has_active_exit_plan"])
    finally:
        conn.close()


def evaluate_exit_trigger(
    *,
    current_price_eur: Decimal,
    avg_entry_price_eur: Decimal,
    config: ExitPolicyConfig,
) -> tuple[str | None, str | None, Decimal]:
    if avg_entry_price_eur <= Decimal("0"):
        return None, None, Decimal("0")

    pnl_pct = ((current_price_eur - avg_entry_price_eur) / avg_entry_price_eur).quantize(Decimal("0.000000"))

    if pnl_pct >= config.take_profit_pct:
        return "EXIT_TRIGGERED", "TAKE_PROFIT", pnl_pct

    if pnl_pct <= (Decimal("0") - config.stop_loss_pct):
        return "EXIT_TRIGGERED", "STOP_LOSS", pnl_pct

    return None, None, pnl_pct


def run_exit_policy_v1(
    *,
    account_id: int,
    trading_account_id: int,
    sleeve_code: str,
    venue: str,
    config: ExitPolicyConfig,
) -> list[ExitPolicyResult]:
    planner_repo = ExecutionPlannerRepository()
    planner_config = ExecutionPlannerConfig(
        execution_mode="PAPER",
        trading_account_id=trading_account_id,
        action_type="PLACE_ORDER",
        requested_side="SELL",
    )
    position_rows = fetch_open_positions_for_policy(
        account_id=account_id,
        sleeve_code=sleeve_code,
        venue=venue,
    )

    out: list[ExitPolicyResult] = []

    for row in position_rows:
        asset_id = int(row["asset_id"])
        symbol = str(row["symbol"])
        avg_entry_price = _to_decimal(row["avg_entry_price"])
        current_price = planner_repo.fetch_reference_price_eur(
            asset_id=asset_id,
            venue=venue,
            interval_code=config.price_interval_code,
        )

        if current_price is None:
            out.append(
                ExitPolicyResult(
                    symbol=symbol,
                    asset_id=asset_id,
                    trigger_state="NO_ACTION",
                    trigger_reason="NO_PRICE",
                    current_price_eur=Decimal("0"),
                    avg_entry_price_eur=avg_entry_price,
                    pnl_pct=Decimal("0"),
                    exit_plan_created=False,
                    execution_plan_id=None,
                )
            )
            continue

        trigger_state, trigger_reason, pnl_pct = evaluate_exit_trigger(
            current_price_eur=current_price,
            avg_entry_price_eur=avg_entry_price,
            config=config,
        )

        if trigger_state is None:
            out.append(
                ExitPolicyResult(
                    symbol=symbol,
                    asset_id=asset_id,
                    trigger_state="NO_ACTION",
                    trigger_reason="THRESHOLD_NOT_HIT",
                    current_price_eur=current_price,
                    avg_entry_price_eur=avg_entry_price,
                    pnl_pct=pnl_pct,
                    exit_plan_created=False,
                    execution_plan_id=None,
                )
            )
            continue

        if has_active_exit_plan(
            account_id=account_id,
            sleeve_code=sleeve_code,
            venue=venue,
            asset_id=asset_id,
        ):
            out.append(
                ExitPolicyResult(
                    symbol=symbol,
                    asset_id=asset_id,
                    trigger_state="BLOCKED_ACTIVE_EXIT_PLAN",
                    trigger_reason=trigger_reason,
                    current_price_eur=current_price,
                    avg_entry_price_eur=avg_entry_price,
                    pnl_pct=pnl_pct,
                    exit_plan_created=False,
                    execution_plan_id=None,
                )
            )
            continue

        position = planner_repo.fetch_open_position_for_exit(
            account_id=account_id,
            sleeve_code=sleeve_code,
            venue=venue,
            asset_id=asset_id,
            symbol=None,
        )
        if position is None:
            out.append(
                ExitPolicyResult(
                    symbol=symbol,
                    asset_id=asset_id,
                    trigger_state="NO_ACTION",
                    trigger_reason="POSITION_NOT_FOUND",
                    current_price_eur=current_price,
                    avg_entry_price_eur=avg_entry_price,
                    pnl_pct=pnl_pct,
                    exit_plan_created=False,
                    execution_plan_id=None,
                )
            )
            continue

        exit_plan = build_exit_plan_from_position(
            position=position,
            config=planner_config,
            reference_price_eur=current_price,
        )
        execution_plan_id = planner_repo.create_exit_plan_without_reservation(exit_plan)

        out.append(
            ExitPolicyResult(
                symbol=symbol,
                asset_id=asset_id,
                trigger_state="EXIT_TRIGGERED",
                trigger_reason=trigger_reason or "EXIT_POLICY",
                current_price_eur=current_price,
                avg_entry_price_eur=avg_entry_price,
                pnl_pct=pnl_pct,
                exit_plan_created=True,
                execution_plan_id=execution_plan_id,
            )
        )

    return out
