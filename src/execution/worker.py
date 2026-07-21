from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import db_cursor
from src.execution.bitvavo_client import BitvavoClient, BitvavoOrderRequest
from src.execution.permission_gate_v1 import (
    ExecutionPermissionRepository,
    validate_live_execution_permission,
)


EXECUTION_MODE = os.getenv("SYNTH_EXECUTION_MODE", "paper").lower()
DEFAULT_EUR_NOTIONAL = Decimal(os.getenv("SYNTH_DEFAULT_EUR_NOTIONAL", "25"))

ORDER_ID_RE = re.compile(r"order_id=([A-Za-z0-9_-]+)")
PRICE_RE = re.compile(r"price=([0-9.]+)")

DECIMAL_ZERO = Decimal("0")
BPS = Decimal("10000")

EXECUTABLE_DESIRED_ACTIONS = {
    "SPREAD_CAPTURE_PASSIVE",
    "ENTER",
    "ENTER_LONG",
}


@dataclass(slots=True)
class PlanRuntime:
    execution_plan_id: int
    trading_account_id: int | None
    asset_id: int
    symbol: str
    sleeve_code: str
    venue: str | None
    side: str
    desired_action: str
    execution_intent: str | None
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


def _market_symbol(symbol: str) -> str:
    return f"{symbol}-EUR"


def _estimate_amount(reference_price_eur: Decimal, target_fraction: Decimal) -> Decimal:
    eur_notional = DEFAULT_EUR_NOTIONAL * max(target_fraction, Decimal("0.10"))
    amount = eur_notional / reference_price_eur
    return amount.quantize(Decimal("0.00000001"))


def _fetch_symbol_map() -> dict[int, str]:
    sql = "SELECT asset_id, symbol FROM asset"

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    return {int(r["asset_id"]): str(r["symbol"]) for r in rows}


def _fetch_actionable_plans(limit: int = 50) -> list[PlanRuntime]:
    sql = """
    SELECT
        execution_plan_id,
        account_id,
        asset_id,
        sleeve_code,
        venue,
        side,
        desired_action,
        execution_intent,
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
    WHERE plan_state IN ('IDLE', 'PLACED', 'MONITOR_QUEUE', 'REPRICE_PENDING')
      AND desired_action IN (
          'SPREAD_CAPTURE_PASSIVE',
          'ENTER',
          'ENTER_LONG'
      )
    ORDER BY plan_ts_utc ASC
    LIMIT %s
    """

    symbol_map = _fetch_symbol_map()

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (limit,))
        rows = cur.fetchall()

    out: list[PlanRuntime] = []
    for row in rows:
        asset_id = int(row["asset_id"])
        symbol = symbol_map.get(asset_id)
        if not symbol:
            continue

        out.append(
            PlanRuntime(
                execution_plan_id=int(row["execution_plan_id"]),
                trading_account_id=(
                    None if row.get("account_id") is None else int(row["account_id"])
                ),
                asset_id=asset_id,
                symbol=symbol,
                sleeve_code=str(row["sleeve_code"]),
                venue=str(row["venue"]) if row.get("venue") is not None else None,
                side=str(row["side"] or "buy").lower(),
                desired_action=str(row["desired_action"]),
                execution_intent=(
                    None
                    if row.get("execution_intent") is None
                    else str(row["execution_intent"])
                ),
                execution_mode=str(row["execution_mode"]),
                target_fraction=Decimal(str(row["target_fraction"])),
                reference_price_eur=Decimal(str(row["reference_price_eur"])),
                passive_price_eur=Decimal(str(row["passive_price_eur"])),
                urgent_limit_price_eur=Decimal(str(row["urgent_limit_price_eur"])),
                max_reprices=int(row["max_reprices"]),
                max_wait_seconds=int(row["max_wait_seconds"]),
                max_chase_bps=Decimal(str(row["max_chase_bps"])),
                min_spread_bps_for_capture=Decimal(str(row["min_spread_bps_for_capture"])),
                escalation_to_urgent_limit=bool(row["escalation_to_urgent_limit"]),
                abort_if_signal_invalidates=bool(row["abort_if_signal_invalidates"]),
                plan_state=str(row["plan_state"]),
                notes=str(row["notes"] or ""),
                plan_ts_utc=row["plan_ts_utc"],
                valid_until_ts_utc=row.get("valid_until_ts_utc"),
            )
        )
    return out


def _fetch_latest_events_for_plans(plan_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not plan_ids:
        return {}

    placeholders = ", ".join(["%s"] * len(plan_ids))
    sql = f"""
    SELECT
        e.execution_event_id,
        e.execution_plan_id,
        e.event_ts_utc,
        e.event_type,
        e.order_price_eur,
        e.event_note
    FROM execution_event e
    JOIN (
        SELECT
            execution_plan_id,
            MAX(execution_event_id) AS max_event_id
        FROM execution_event
        WHERE execution_plan_id IN ({placeholders})
        GROUP BY execution_plan_id
    ) x
        ON x.execution_plan_id = e.execution_plan_id
       AND x.max_event_id = e.execution_event_id
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, plan_ids)
        rows = cur.fetchall()

    return {int(r["execution_plan_id"]): r for r in rows}


def _count_reprices_for_plan(execution_plan_id: int) -> int:
    sql = """
    SELECT COUNT(*) AS cnt
    FROM execution_event
    WHERE execution_plan_id = %s
      AND event_type IN ('PAPER_REPRICE_PASSIVE', 'LIVE_REPRICE_PASSIVE')
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (execution_plan_id,))
        row = cur.fetchone()

    return int(row["cnt"])


def _write_event(
    execution_plan_id: int,
    event_type: str,
    note: str,
    order_price: Decimal | None = None,
) -> None:
    sql = """
    INSERT INTO execution_event (
        execution_plan_id,
        event_ts_utc,
        event_type,
        order_price_eur,
        order_qty,
        queue_position,
        event_note
    ) VALUES (
        %s,
        UTC_TIMESTAMP(),
        %s,
        %s,
        NULL,
        NULL,
        %s
    )
    """

    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(sql, (execution_plan_id, event_type, order_price, note))


def _update_plan_state(execution_plan_id: int, plan_state: str) -> None:
    sql = """
    UPDATE execution_plan
    SET plan_state = %s
    WHERE execution_plan_id = %s
    """

    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(sql, (plan_state, execution_plan_id))


def _update_plan_passive_price(execution_plan_id: int, passive_price_eur: Decimal) -> None:
    sql = """
    UPDATE execution_plan
    SET passive_price_eur = %s
    WHERE execution_plan_id = %s
    """

    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(sql, (passive_price_eur, execution_plan_id))


def _parse_order_id(note: str | None) -> str | None:
    if not note:
        return None
    match = ORDER_ID_RE.search(note)
    if not match:
        return match
    return match.group(1)


def _parse_price(note: str | None) -> Decimal | None:
    if not note:
        return None
    match = PRICE_RE.search(note)
    if not match:
        return None
    return Decimal(match.group(1))


def _best_bid_ask(book: dict[str, Any]) -> tuple[Decimal, Decimal]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    if not bids or not asks:
        raise RuntimeError("Orderbook missing bids or asks.")

    best_bid = Decimal(str(bids[0][0]))
    best_ask = Decimal(str(asks[0][0]))
    return best_bid, best_ask


def _compute_passive_price(best_bid: Decimal, best_ask: Decimal, side: str) -> Decimal:
    spread = best_ask - best_bid
    tick = max(spread / Decimal("100"), Decimal("0.00000001"))

    if side == "buy":
        return (best_bid + tick).quantize(Decimal("0.00000001"))
    return (best_ask - tick).quantize(Decimal("0.00000001"))


def _spread_bps(best_bid: Decimal, best_ask: Decimal) -> Decimal:
    mid = (best_bid + best_ask) / Decimal("2")
    if mid <= DECIMAL_ZERO:
        return Decimal("0")
    return ((best_ask - best_bid) / mid) * BPS


def _elapsed_seconds(plan_ts_utc: datetime) -> int:
    return int((_utc_now_naive() - plan_ts_utc).total_seconds())


def _resolve_current_price(
    plan: PlanRuntime,
    latest_event: dict[str, Any] | None,
) -> Decimal:
    current_price = (
        Decimal(str(latest_event["order_price_eur"]))
        if latest_event and latest_event.get("order_price_eur") is not None
        else _parse_price(latest_event["event_note"] if latest_event else None)
    )
    if current_price is None:
        return plan.passive_price_eur
    return current_price


def _decide_reprice(
    plan: PlanRuntime,
    current_price: Decimal,
    target_price: Decimal,
    reprices: int,
) -> tuple[bool, str | None, Decimal | None]:
    if target_price == current_price:
        return False, None, None

    if reprices >= plan.max_reprices:
        return False, None, None

    if target_price > current_price:
        chase_bps = _bps(target_price, plan.reference_price_eur)
        if chase_bps <= plan.max_chase_bps:
            return True, "up", chase_bps
        return False, None, chase_bps

    return True, "down", None


def _place_initial_order_paper(plan: PlanRuntime) -> None:
    amount = _estimate_amount(plan.reference_price_eur, plan.target_fraction)
    market = _market_symbol(plan.symbol)

    _write_event(
        plan.execution_plan_id,
        "PAPER_PLACE_PASSIVE",
        f"paper order market={market} amount={amount} price={plan.passive_price_eur}",
        plan.passive_price_eur,
    )
    _update_plan_state(plan.execution_plan_id, "MONITOR_QUEUE")


def _place_initial_order_live(plan: PlanRuntime, client: BitvavoClient) -> None:
    amount = _estimate_amount(plan.reference_price_eur, plan.target_fraction)
    market = _market_symbol(plan.symbol)

    response = client.place_order(
        BitvavoOrderRequest(
            market=market,
            side="buy",
            order_type="limit",
            amount=str(amount),
            price=str(plan.passive_price_eur),
            post_only=True,
        )
    )
    order_id = str(response.get("orderId", "UNKNOWN"))

    _write_event(
        plan.execution_plan_id,
        "LIVE_PLACE_PASSIVE",
        f"live order placed market={market} order_id={order_id} amount={amount} price={plan.passive_price_eur}",
        plan.passive_price_eur,
    )
    _update_plan_state(plan.execution_plan_id, "MONITOR_QUEUE")


def _handle_monitor_paper(
    plan: PlanRuntime,
    client: BitvavoClient,
    latest_event: dict[str, Any] | None,
) -> str:
    market = _market_symbol(plan.symbol)
    book = client.get_book(market, depth=5)
    best_bid, best_ask = _best_bid_ask(book)

    spread_bps = _spread_bps(best_bid, best_ask)
    if spread_bps < plan.min_spread_bps_for_capture:
        _write_event(
            plan.execution_plan_id,
            "PAPER_ABORT_SPREAD_TOO_NARROW",
            f"spread_bps={spread_bps} below min={plan.min_spread_bps_for_capture}",
        )
        _update_plan_state(plan.execution_plan_id, "ABORTED")
        return "aborted"

    target_price = _compute_passive_price(best_bid, best_ask, side="buy")
    current_price = _resolve_current_price(plan, latest_event)

    reprices = _count_reprices_for_plan(plan.execution_plan_id)
    elapsed = _elapsed_seconds(plan.plan_ts_utc)
    should_reprice, direction, chase_bps = _decide_reprice(
        plan=plan,
        current_price=current_price,
        target_price=target_price,
        reprices=reprices,
    )

    if should_reprice:
        chase_text = f" chase_bps={chase_bps}" if chase_bps is not None else ""
        _write_event(
            plan.execution_plan_id,
            "PAPER_REPRICE_PASSIVE",
            (
                f"market={market} direction={direction} old_price={current_price} "
                f"new_price={target_price} spread_bps={spread_bps}{chase_text}"
            ),
            target_price,
        )
        _update_plan_passive_price(plan.execution_plan_id, target_price)
        _update_plan_state(plan.execution_plan_id, "MONITOR_QUEUE")
        return "repriced"

    if elapsed >= plan.max_wait_seconds:
        if plan.escalation_to_urgent_limit:
            _write_event(
                plan.execution_plan_id,
                "PAPER_ESCALATE_URGENT_LIMIT",
                f"elapsed={elapsed}s urgent_price={plan.urgent_limit_price_eur}",
                plan.urgent_limit_price_eur,
            )
            _update_plan_state(plan.execution_plan_id, "ESCALATED")
            return "escalated"

        _write_event(
            plan.execution_plan_id,
            "PAPER_ABORT_TIMEOUT",
            f"elapsed={elapsed}s exceeded max_wait_seconds={plan.max_wait_seconds}",
        )
        _update_plan_state(plan.execution_plan_id, "ABORTED")
        return "aborted"

    _write_event(
        plan.execution_plan_id,
        "PAPER_MONITOR_OK",
        f"market={market} current_price={current_price} target_price={target_price} spread_bps={spread_bps}",
        current_price,
    )
    _update_plan_state(plan.execution_plan_id, "MONITOR_QUEUE")
    return "monitored"


def _handle_monitor_live(
    plan: PlanRuntime,
    client: BitvavoClient,
    latest_event: dict[str, Any] | None,
) -> str:
    market = _market_symbol(plan.symbol)
    book = client.get_book(market, depth=5)
    best_bid, best_ask = _best_bid_ask(book)

    spread_bps = _spread_bps(best_bid, best_ask)
    if spread_bps < plan.min_spread_bps_for_capture:
        _write_event(
            plan.execution_plan_id,
            "LIVE_ABORT_SPREAD_TOO_NARROW",
            f"spread_bps={spread_bps} below min={plan.min_spread_bps_for_capture}",
        )
        _update_plan_state(plan.execution_plan_id, "ABORTED")
        return "aborted"

    target_price = _compute_passive_price(best_bid, best_ask, side="buy")
    current_price = _resolve_current_price(plan, latest_event)

    reprices = _count_reprices_for_plan(plan.execution_plan_id)
    elapsed = _elapsed_seconds(plan.plan_ts_utc)
    should_reprice, direction, chase_bps = _decide_reprice(
        plan=plan,
        current_price=current_price,
        target_price=target_price,
        reprices=reprices,
    )

    if should_reprice:
        order_id = _parse_order_id(latest_event["event_note"] if latest_event else None)
        if order_id:
            client.cancel_order(market, order_id)

        amount = _estimate_amount(plan.reference_price_eur, plan.target_fraction)
        response = client.place_order(
            BitvavoOrderRequest(
                market=market,
                side="buy",
                order_type="limit",
                amount=str(amount),
                price=str(target_price),
                post_only=True,
            )
        )
        new_order_id = str(response.get("orderId", "UNKNOWN"))
        chase_text = f" chase_bps={chase_bps}" if chase_bps is not None else ""

        _write_event(
            plan.execution_plan_id,
            "LIVE_REPRICE_PASSIVE",
            (
                f"market={market} order_id={new_order_id} direction={direction} "
                f"old_price={current_price} new_price={target_price}{chase_text}"
            ),
            target_price,
        )
        _update_plan_passive_price(plan.execution_plan_id, target_price)
        _update_plan_state(plan.execution_plan_id, "MONITOR_QUEUE")
        return "repriced"

    if elapsed >= plan.max_wait_seconds:
        if plan.escalation_to_urgent_limit:
            amount = _estimate_amount(plan.reference_price_eur, plan.target_fraction)
            response = client.place_order(
                BitvavoOrderRequest(
                    market=market,
                    side="buy",
                    order_type="limit",
                    amount=str(amount),
                    price=str(plan.urgent_limit_price_eur),
                    post_only=False,
                )
            )
            order_id = str(response.get("orderId", "UNKNOWN"))

            _write_event(
                plan.execution_plan_id,
                "LIVE_ESCALATE_URGENT_LIMIT",
                f"market={market} order_id={order_id} urgent_price={plan.urgent_limit_price_eur}",
                plan.urgent_limit_price_eur,
            )
            _update_plan_state(plan.execution_plan_id, "ESCALATED")
            return "escalated"

        _write_event(
            plan.execution_plan_id,
            "LIVE_ABORT_TIMEOUT",
            f"elapsed={elapsed}s exceeded max_wait_seconds={plan.max_wait_seconds}",
        )
        _update_plan_state(plan.execution_plan_id, "ABORTED")
        return "aborted"

    _write_event(
        plan.execution_plan_id,
        "LIVE_MONITOR_OK",
        f"market={market} current_price={current_price} target_price={target_price} spread_bps={spread_bps}",
        current_price,
    )
    _update_plan_state(plan.execution_plan_id, "MONITOR_QUEUE")
    return "monitored"


def _runtime_mode(execution_mode: str | None = None) -> str:
    mode = (execution_mode or EXECUTION_MODE).lower()
    if mode not in {"paper", "live"}:
        raise ValueError(f"Unsupported SYNTH_EXECUTION_MODE={mode!r}; expected paper or live.")
    return mode


def _require_live_gate(
    *,
    plan: PlanRuntime,
    permission_repo: ExecutionPermissionRepository,
) -> None:
    validate_live_execution_permission(
        plan=plan,
        market=_market_symbol(plan.symbol),
        repo=permission_repo,
    )


def process_execution_plans(
    *,
    execution_mode: str | None = None,
    broker_client_factory: Any = BitvavoClient,
    market_data_client_factory: Any = BitvavoClient,
    permission_repo: ExecutionPermissionRepository | None = None,
) -> dict[str, int]:
    mode = _runtime_mode(execution_mode)
    plans = _fetch_actionable_plans()
    latest_events = _fetch_latest_events_for_plans([p.execution_plan_id for p in plans])
    permission_repo = permission_repo or ExecutionPermissionRepository()
    broker_client: BitvavoClient | None = None
    market_data_client: BitvavoClient | None = None

    processed = 0
    paper_placed = 0
    live_placed = 0
    repriced = 0
    escalated = 0
    aborted = 0
    monitored = 0
    failed = 0

    for plan in plans:
        latest_event = latest_events.get(plan.execution_plan_id)

        try:
            if plan.desired_action not in EXECUTABLE_DESIRED_ACTIONS:
                _write_event(
                    plan.execution_plan_id,
                    "EXECUTOR_SKIPPED_NON_EXECUTABLE_ACTION",
                    f"desired_action={plan.desired_action}",
                )
                continue

            if plan.plan_state == "IDLE":
                if mode == "paper":
                    _place_initial_order_paper(plan)
                    processed += 1
                    paper_placed += 1
                else:
                    _require_live_gate(plan=plan, permission_repo=permission_repo)
                    if broker_client is None:
                        broker_client = broker_client_factory()
                    _place_initial_order_live(plan, broker_client)
                    processed += 1
                    live_placed += 1
                continue

            if mode == "paper":
                if market_data_client is None:
                    market_data_client = market_data_client_factory()
                outcome = _handle_monitor_paper(plan, market_data_client, latest_event)
            else:
                _require_live_gate(plan=plan, permission_repo=permission_repo)
                if broker_client is None:
                    broker_client = broker_client_factory()
                outcome = _handle_monitor_live(plan, broker_client, latest_event)

            processed += 1
            if outcome == "repriced":
                repriced += 1
            elif outcome == "escalated":
                escalated += 1
            elif outcome == "aborted":
                aborted += 1
            else:
                monitored += 1

        except Exception as exc:
            _write_event(plan.execution_plan_id, "ERROR", f"execution worker failed: {exc}")
            _update_plan_state(plan.execution_plan_id, "FAILED")
            failed += 1

    return {
        "processed": processed,
        "paper_placed": paper_placed,
        "live_placed": live_placed,
        "repriced": repriced,
        "escalated": escalated,
        "aborted": aborted,
        "monitored": monitored,
        "failed": failed,
    }
