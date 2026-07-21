from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import db_cursor
from src.market_data.bitvavo_public_client_v1 import BitvavoPublicMarketDataClient


EXECUTION_MODE = os.getenv("SYNTH_EXECUTION_MODE", "paper").lower()
DEFAULT_EUR_NOTIONAL = Decimal(os.getenv("SYNTH_DEFAULT_EUR_NOTIONAL", "25"))
DECIMAL_ZERO = Decimal("0")
BPS = Decimal("10000")
PAPER_ACTIONABLE_STATES = frozenset({"IDLE", "MONITOR_QUEUE", "REPRICE_PENDING"})
LIVE_PREREQUISITE_CODES = (
    "CANONICAL_DECISION_GATE_PERMISSION_PRODUCER_REQUIRED",
    "ACCOUNT_BOUND_TRADE_CREDENTIAL_BINDING_REQUIRED",
    "LIVE_EXECUTOR_ACTIVATION_REQUIRED",
)


class LiveExecutionPrerequisitesUnavailable(RuntimeError):
    code = "LIVE_EXECUTION_PREREQUISITES_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(f"{self.code}:" + ",".join(LIVE_PREREQUISITE_CODES))


@dataclass(slots=True)
class PlanRuntime:
    execution_plan_id: int
    trading_account_id: int | None
    asset_id: int
    symbol: str
    sleeve_code: str
    venue: str | None
    market: str | None
    side: str | None
    desired_action: str
    execution_intent: str | None
    action_type: str | None
    requested_side: str | None
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
    plan_state: str
    notes: str
    plan_ts_utc: datetime
    valid_until_ts_utc: datetime | None


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _bps(a: Decimal, b: Decimal) -> Decimal:
    if b == DECIMAL_ZERO:
        return Decimal("999999")
    return abs(a - b) / b * BPS


def _estimate_amount(reference_price_eur: Decimal, target_fraction: Decimal) -> Decimal:
    eur_notional = DEFAULT_EUR_NOTIONAL * max(target_fraction, Decimal("0.10"))
    amount = eur_notional / reference_price_eur
    return amount.quantize(Decimal("0.00000001"))


def _fetch_symbol_map() -> dict[int, str]:
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT asset_id, symbol FROM asset")
        rows = cur.fetchall()
    return {int(row["asset_id"]): str(row["symbol"]) for row in rows}


def _decimal(row: dict[str, Any], key: str) -> Decimal:
    value = row.get(key)
    if value is None:
        raise ValueError(f"PLAN_{key.upper()}_MISSING")
    return Decimal(str(value))


def _fetch_actionable_plans(limit: int = 50) -> list[PlanRuntime]:
    sql = """
    SELECT
        execution_plan_id,
        trading_account_id,
        asset_id,
        sleeve_code,
        venue,
        market,
        side,
        desired_action,
        execution_intent,
        action_type,
        requested_side,
        plan_ts_utc,
        valid_until_ts_utc,
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
    FROM execution_plan
    WHERE plan_state IN ('IDLE', 'MONITOR_QUEUE', 'REPRICE_PENDING')
    ORDER BY plan_ts_utc ASC
    LIMIT %s
    """
    symbol_map = _fetch_symbol_map()
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (limit,))
        rows = cur.fetchall()

    plans: list[PlanRuntime] = []
    for row in rows:
        asset_id = int(row["asset_id"])
        symbol = symbol_map.get(asset_id)
        if symbol is None:
            continue
        plans.append(
            PlanRuntime(
                execution_plan_id=int(row["execution_plan_id"]),
                trading_account_id=(
                    None if row.get("trading_account_id") is None else int(row["trading_account_id"])
                ),
                asset_id=asset_id,
                symbol=symbol,
                sleeve_code=str(row["sleeve_code"]),
                venue=None if row.get("venue") is None else str(row["venue"]),
                market=None if row.get("market") is None else str(row["market"]),
                side=None if row.get("side") is None else str(row["side"]),
                desired_action=str(row["desired_action"]),
                execution_intent=(
                    None if row.get("execution_intent") is None else str(row["execution_intent"])
                ),
                action_type=None if row.get("action_type") is None else str(row["action_type"]),
                requested_side=(
                    None if row.get("requested_side") is None else str(row["requested_side"])
                ),
                execution_mode=str(row["execution_mode"]),
                target_fraction=_decimal(row, "target_fraction"),
                reference_price_eur=_decimal(row, "reference_price_eur"),
                passive_price_eur=_decimal(row, "passive_price_eur"),
                urgent_limit_price_eur=_decimal(row, "urgent_limit_price_eur"),
                max_reprices=int(row["max_reprices"]),
                max_wait_seconds=int(row["max_wait_seconds"]),
                max_chase_bps=_decimal(row, "max_chase_bps"),
                min_spread_bps_for_capture=_decimal(row, "min_spread_bps_for_capture"),
                escalation_to_urgent_limit=bool(row["escalation_to_urgent_limit"]),
                abort_if_signal_invalidates=bool(row["abort_if_signal_invalidates"]),
                plan_state=str(row["plan_state"]),
                notes=str(row.get("notes") or ""),
                plan_ts_utc=row["plan_ts_utc"],
                valid_until_ts_utc=row.get("valid_until_ts_utc"),
            )
        )
    return plans


def _fetch_latest_events_for_plans(plan_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not plan_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(plan_ids))
    sql = f"""
    SELECT e.*
    FROM execution_event e
    JOIN (
        SELECT execution_plan_id, MAX(execution_event_id) AS max_event_id
        FROM execution_event
        WHERE execution_plan_id IN ({placeholders})
        GROUP BY execution_plan_id
    ) latest ON latest.max_event_id = e.execution_event_id
    """
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, plan_ids)
        rows = cur.fetchall()
    return {int(row["execution_plan_id"]): row for row in rows}


def _count_reprices_for_plan(execution_plan_id: int) -> int:
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM execution_event
            WHERE execution_plan_id = %s AND event_type = 'PAPER_REPRICE_PASSIVE'
            """,
            (execution_plan_id,),
        )
        row = cur.fetchone()
    return int(row["cnt"])


def _write_event(
    execution_plan_id: int,
    event_type: str,
    note: str,
    order_price: Decimal | None = None,
) -> None:
    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            INSERT INTO execution_event (
                execution_plan_id, event_ts_utc, event_type,
                order_price_eur, order_qty, queue_position, event_note
            ) VALUES (%s, UTC_TIMESTAMP(), %s, %s, NULL, NULL, %s)
            """,
            (execution_plan_id, event_type, order_price, note),
        )


def _update_plan_state(execution_plan_id: int, plan_state: str) -> None:
    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE execution_plan SET plan_state = %s WHERE execution_plan_id = %s",
            (plan_state, execution_plan_id),
        )


def _update_plan_passive_price(execution_plan_id: int, passive_price_eur: Decimal) -> None:
    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE execution_plan SET passive_price_eur = %s WHERE execution_plan_id = %s",
            (passive_price_eur, execution_plan_id),
        )


def _best_bid_ask(book: dict[str, Any]) -> tuple[Decimal, Decimal]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        raise RuntimeError("ORDERBOOK_MISSING_BIDS_OR_ASKS")
    return Decimal(str(bids[0][0])), Decimal(str(asks[0][0]))


def _compute_passive_price(best_bid: Decimal, best_ask: Decimal, side: str) -> Decimal:
    spread = best_ask - best_bid
    tick = max(spread / Decimal("100"), Decimal("0.00000001"))
    if side == "BUY":
        return (best_bid + tick).quantize(Decimal("0.00000001"))
    if side == "SELL":
        return (best_ask - tick).quantize(Decimal("0.00000001"))
    raise ValueError("REQUESTED_SIDE_NOT_CANONICAL")


def _spread_bps(best_bid: Decimal, best_ask: Decimal) -> Decimal:
    mid = (best_bid + best_ask) / Decimal("2")
    if mid <= DECIMAL_ZERO:
        return DECIMAL_ZERO
    return ((best_ask - best_bid) / mid) * BPS


def _place_initial_order_paper(plan: PlanRuntime) -> None:
    amount = _estimate_amount(plan.reference_price_eur, plan.target_fraction)
    _write_event(
        plan.execution_plan_id,
        "PAPER_PLACE_PASSIVE",
        f"paper order market={plan.market} side={plan.requested_side} amount={amount} price={plan.passive_price_eur}",
        plan.passive_price_eur,
    )
    _update_plan_state(plan.execution_plan_id, "MONITOR_QUEUE")


def _validate_paper_plan(plan: PlanRuntime) -> None:
    if plan.trading_account_id is None or plan.trading_account_id <= 0:
        raise ValueError("TRADING_ACCOUNT_ID_REQUIRED")
    if plan.execution_intent is None or plan.execution_intent == "":
        raise ValueError("EXECUTION_INTENT_REQUIRED")
    if plan.action_type != "PLACE_ORDER":
        raise ValueError("PAPER_ACTION_NOT_SUPPORTED")
    if plan.requested_side not in {"BUY", "SELL"} or plan.side != plan.requested_side:
        raise ValueError("REQUESTED_SIDE_NOT_CANONICAL")
    if plan.market is None or plan.market == "":
        raise ValueError("PLAN_MARKET_MISSING")


def _handle_monitor_paper(
    plan: PlanRuntime,
    client: BitvavoPublicMarketDataClient,
    latest_event: dict[str, Any] | None,
) -> str:
    if plan.market is None:
        raise ValueError("PLAN_MARKET_MISSING")
    if plan.requested_side not in {"BUY", "SELL"}:
        raise ValueError("REQUESTED_SIDE_NOT_CANONICAL")
    book = client.get_book(plan.market, depth=5)
    best_bid, best_ask = _best_bid_ask(book)
    spread_bps = _spread_bps(best_bid, best_ask)
    if spread_bps < plan.min_spread_bps_for_capture:
        _write_event(plan.execution_plan_id, "PAPER_ABORT_SPREAD_TOO_NARROW", f"spread_bps={spread_bps}")
        _update_plan_state(plan.execution_plan_id, "ABORTED")
        return "aborted"

    target_price = _compute_passive_price(best_bid, best_ask, plan.requested_side)
    current_price = (
        Decimal(str(latest_event["order_price_eur"]))
        if latest_event and latest_event.get("order_price_eur") is not None
        else plan.passive_price_eur
    )
    elapsed = int((_utc_now_naive() - plan.plan_ts_utc).total_seconds())
    reprices = _count_reprices_for_plan(plan.execution_plan_id)
    if target_price != current_price and reprices < plan.max_reprices:
        if target_price < current_price or _bps(target_price, plan.reference_price_eur) <= plan.max_chase_bps:
            _write_event(
                plan.execution_plan_id,
                "PAPER_REPRICE_PASSIVE",
                f"market={plan.market} old_price={current_price} new_price={target_price}",
                target_price,
            )
            _update_plan_passive_price(plan.execution_plan_id, target_price)
            return "repriced"
    if elapsed >= plan.max_wait_seconds:
        state = "ESCALATED" if plan.escalation_to_urgent_limit else "ABORTED"
        event = "PAPER_ESCALATE_URGENT_LIMIT" if plan.escalation_to_urgent_limit else "PAPER_ABORT_TIMEOUT"
        _write_event(plan.execution_plan_id, event, f"elapsed={elapsed}s")
        _update_plan_state(plan.execution_plan_id, state)
        return "escalated" if plan.escalation_to_urgent_limit else "aborted"
    _write_event(plan.execution_plan_id, "PAPER_MONITOR_OK", f"market={plan.market} price={current_price}")
    return "monitored"


def _runtime_mode(execution_mode: str | None = None) -> str:
    mode = execution_mode or EXECUTION_MODE
    if mode not in {"paper", "live"}:
        raise ValueError("WORKER_MODE_NOT_CANONICAL")
    return mode


def process_execution_plans(
    *,
    execution_mode: str | None = None,
    market_data_client_factory: Any = BitvavoPublicMarketDataClient,
) -> dict[str, int]:
    _runtime_mode(execution_mode)
    plans = _fetch_actionable_plans()
    invalid_modes = [plan.execution_mode for plan in plans if plan.execution_mode not in {"PAPER", "LIVE"}]
    if invalid_modes:
        raise ValueError("PLAN_EXECUTION_MODE_NOT_CANONICAL")
    if any(plan.execution_mode == "LIVE" for plan in plans):
        raise LiveExecutionPrerequisitesUnavailable()

    latest_events = _fetch_latest_events_for_plans([plan.execution_plan_id for plan in plans])
    market_data_client: BitvavoPublicMarketDataClient | None = None
    counters = {
        "processed": 0,
        "paper_placed": 0,
        "live_placed": 0,
        "repriced": 0,
        "escalated": 0,
        "aborted": 0,
        "monitored": 0,
        "failed": 0,
    }

    for plan in plans:
        try:
            _validate_paper_plan(plan)
            if plan.plan_state not in PAPER_ACTIONABLE_STATES:
                raise ValueError("PAPER_PLAN_NOT_ACTIONABLE")
            if plan.plan_state == "IDLE":
                _place_initial_order_paper(plan)
                counters["paper_placed"] += 1
            else:
                if market_data_client is None:
                    market_data_client = market_data_client_factory()
                outcome = _handle_monitor_paper(
                    plan, market_data_client, latest_events.get(plan.execution_plan_id)
                )
                counters[outcome if outcome != "monitored" else "monitored"] += 1
            counters["processed"] += 1
        except Exception as exc:
            code = type(exc).__name__
            _write_event(plan.execution_plan_id, "EXECUTOR_REJECTED", f"code={code}")
            counters["failed"] += 1
    return counters
