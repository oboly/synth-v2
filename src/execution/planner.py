from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from decimal import Decimal
from typing import Iterable

from src.common.db import db_cursor


@dataclass(slots=True)
class PlannedExecution:
    asset_id: int
    symbol: str
    sleeve_code: str
    desired_action: str
    execution_mode: str
    target_fraction: Decimal
    reference_price_eur: Decimal
    passive_price_eur: Decimal
    urgent_limit_price_eur: Decimal
    max_reprices: int
    max_wait_seconds: int
    max_chase_bps: Decimal
    min_spread_bps_for_capture: Decimal
    escalation_to_urgent_limit: bool
    abort_if_signal_invalidates: bool
    notes: str


ACTIVE_PLAN_STATES = (
    "IDLE",
    "PLACED",
    "MONITOR_QUEUE",
    "REPRICE_PENDING",
    "ESCALATED",
)


def _fetch_candidates() -> list[dict]:
    sql = """
    SELECT
        asset_id,
        symbol,
        interval_code,
        selection_state,
        selection_score,
        zone_state,
        fib_state,
        context_score,
        core_action,
        core_target_fraction,
        swing_action,
        swing_target_fraction
    FROM v_synth_context_master
    WHERE interval_code IN ('1d', '4h')
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        return cur.fetchall()


def _fetch_latest_price_map() -> dict[int, Decimal]:
    sql = """
    SELECT
        x.asset_id,
        x.close_price
    FROM (
        SELECT
            c.asset_id,
            c.close_price,
            ROW_NUMBER() OVER (
                PARTITION BY c.asset_id, c.interval_code
                ORDER BY c.close_ts_utc DESC
            ) AS rn
        FROM obs_market_candle c
        WHERE c.interval_code = '4h'
    ) x
    WHERE x.rn = 1
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    return {int(r["asset_id"]): Decimal(str(r["close_price"])) for r in rows}


def _fetch_active_plan_keys() -> set[tuple[int, str]]:
    placeholders = ", ".join(["%s"] * len(ACTIVE_PLAN_STATES))
    sql = f"""
    SELECT DISTINCT
        asset_id,
        sleeve_code
    FROM execution_plan
    WHERE plan_state IN ({placeholders})
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, ACTIVE_PLAN_STATES)
        rows = cur.fetchall()

    return {(int(r["asset_id"]), str(r["sleeve_code"])) for r in rows}


def _choose_execution_mode(sleeve_code: str) -> str:
    if sleeve_code == "CORE":
        return "SPREAD_CAPTURE_PASSIVE"
    if sleeve_code == "SWING":
        return "PASSIVE_SMART_REPRICE"
    if sleeve_code == "TACTICAL":
        return "URGENT_LIMIT"
    return "CONFIGURABLE"


def _planner_controls(sleeve_code: str) -> tuple[int, int, Decimal, Decimal]:
    if sleeve_code == "CORE":
        return 25, 3600, Decimal("10"), Decimal("3")
    if sleeve_code == "SWING":
        return 18, 1800, Decimal("12"), Decimal("3")
    if sleeve_code == "TACTICAL":
        return 10, 600, Decimal("18"), Decimal("2")
    return 8, 600, Decimal("15"), Decimal("2")


def _compute_prices(reference_price: Decimal, desired_action: str) -> tuple[Decimal, Decimal]:
    tick = reference_price * Decimal("0.0001")

    if desired_action == "ENTER_LONG":
        passive_price = reference_price - tick
        urgent_price = reference_price + (reference_price * Decimal("0.0008"))
        return passive_price.quantize(Decimal("0.00000001")), urgent_price.quantize(Decimal("0.00000001"))

    passive_price = reference_price + tick
    urgent_price = reference_price - (reference_price * Decimal("0.0008"))
    return passive_price.quantize(Decimal("0.00000001")), urgent_price.quantize(Decimal("0.00000001"))


def build_execution_plans() -> list[PlannedExecution]:
    rows = _fetch_candidates()
    latest_price_map = _fetch_latest_price_map()
    active_plan_keys = _fetch_active_plan_keys()

    plans: list[PlannedExecution] = []

    for row in rows:
        asset_id = int(row["asset_id"])
        symbol = str(row["symbol"])
        interval_code = str(row["interval_code"])
        context_score = Decimal(str(row["context_score"]))

        price = latest_price_map.get(asset_id)
        if price is None or price <= Decimal("0"):
            continue

        sleeve_code: str | None = None
        desired_action: str | None = None
        target_fraction = Decimal("0")

        if interval_code == "1d" and row.get("core_action") in ("ENTER_LONG", "PREPARE"):
            sleeve_code = "CORE"
            desired_action = str(row["core_action"])
            target_fraction = Decimal(str(row["core_target_fraction"] or "0"))

        elif interval_code == "4h" and row.get("swing_action") in ("ENTER_LONG", "PREPARE"):
            sleeve_code = "SWING"
            desired_action = str(row["swing_action"])
            target_fraction = Decimal(str(row["swing_target_fraction"] or "0"))

        if sleeve_code is None or desired_action is None:
            continue

        if (asset_id, sleeve_code) in active_plan_keys:
            continue

        if target_fraction <= Decimal("0"):
            continue

        if desired_action not in ("ENTER_LONG", "PREPARE"):
            continue

        if context_score < Decimal("0.45"):
            continue

        execution_mode = _choose_execution_mode(sleeve_code)
        max_reprices, max_wait_seconds, max_chase_bps, min_spread_bps = _planner_controls(sleeve_code)
        passive_price, urgent_price = _compute_prices(price, "ENTER_LONG")

        plans.append(
            PlannedExecution(
                asset_id=asset_id,
                symbol=symbol,
                sleeve_code=sleeve_code,
                desired_action=desired_action,
                execution_mode=execution_mode,
                target_fraction=target_fraction,
                reference_price_eur=price,
                passive_price_eur=passive_price,
                urgent_limit_price_eur=urgent_price,
                max_reprices=max_reprices,
                max_wait_seconds=max_wait_seconds,
                max_chase_bps=max_chase_bps,
                min_spread_bps_for_capture=min_spread_bps,
                escalation_to_urgent_limit=True,
                abort_if_signal_invalidates=True,
                notes=f"context_score={context_score} interval={interval_code}",
            )
        )

    return plans


def write_execution_plans(plans: Iterable[PlannedExecution]) -> int:
    plans = list(plans)
    if not plans:
        return 0

    sql = """
    INSERT INTO execution_plan (
        asset_id,
        sleeve_code,
        desired_action,
        plan_ts_utc,
        execution_mode,
        target_fraction,
        reference_price_eur,
        passive_price_eur,
        urgent_limit_price_eur,
        max_reprices,
        max_wait_seconds,
        max_chase_bps,
        min_spread_bps_for_capture,
        escalation_to_urgent_limit,
        abort_if_signal_invalidates,
        plan_state,
        notes
    ) VALUES (
        %(asset_id)s,
        %(sleeve_code)s,
        %(desired_action)s,
        %(plan_ts_utc)s,
        %(execution_mode)s,
        %(target_fraction)s,
        %(reference_price_eur)s,
        %(passive_price_eur)s,
        %(urgent_limit_price_eur)s,
        %(max_reprices)s,
        %(max_wait_seconds)s,
        %(max_chase_bps)s,
        %(min_spread_bps_for_capture)s,
        %(escalation_to_urgent_limit)s,
        %(abort_if_signal_invalidates)s,
        %(plan_state)s,
        %(notes)s
    )
    """

    now = datetime.now(UTC).replace(tzinfo=None)

    payload = []
    for plan in plans:
        payload.append(
            {
                "asset_id": plan.asset_id,
                "sleeve_code": plan.sleeve_code,
                "desired_action": plan.desired_action,
                "plan_ts_utc": now,
                "execution_mode": plan.execution_mode,
                "target_fraction": plan.target_fraction,
                "reference_price_eur": plan.reference_price_eur,
                "passive_price_eur": plan.passive_price_eur,
                "urgent_limit_price_eur": plan.urgent_limit_price_eur,
                "max_reprices": plan.max_reprices,
                "max_wait_seconds": plan.max_wait_seconds,
                "max_chase_bps": plan.max_chase_bps,
                "min_spread_bps_for_capture": plan.min_spread_bps_for_capture,
                "escalation_to_urgent_limit": int(plan.escalation_to_urgent_limit),
                "abort_if_signal_invalidates": int(plan.abort_if_signal_invalidates),
                "plan_state": "IDLE",
                "notes": plan.notes,
            }
        )

    with db_cursor(commit=True) as (_conn, cur):
        cur.executemany(sql, payload)

    return len(payload)
