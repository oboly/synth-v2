from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run compact paper dashboard v1.")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--selection-limit", type=int, default=10)
    parser.add_argument("--plan-limit", type=int, default=10)
    parser.add_argument("--event-limit", type=int, default=10)
    return parser.parse_args()


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


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return _fmt_decimal(value)
    return str(value)


def _print_section(title: str) -> None:
    print()
    print(f"=== {title} ===")


def _print_table(headers: list[str], rows: list[list[Any]]) -> None:
    if not rows:
        print("(empty)")
        return

    printable = [[_fmt(v) for v in row] for row in rows]
    widths = [len(h) for h in headers]

    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt_row(values: list[str]) -> str:
        return " | ".join(values[i].ljust(widths[i]) for i in range(len(values)))

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in widths))
    for row in printable:
        print(fmt_row(row))


def fetch_rows(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            if rows is None:
                return []
            return rows
    finally:
        conn.close()


def main() -> int:
    args = parse_args()

    selection_rows = fetch_rows(
        """
        SELECT
            a.symbol,
            s.selection_state,
            s.selection_bias,
            s.selection_score,
            s.priority_rank
        FROM selection_state s
        JOIN asset a ON a.asset_id = s.asset_id
        WHERE s.venue = %s
          AND s.asof_ts_utc = (
              SELECT MAX(s2.asof_ts_utc)
              FROM selection_state s2
              WHERE s2.venue = %s
          )
        ORDER BY
            s.priority_rank IS NULL,
            s.priority_rank ASC,
            s.selection_score DESC,
            a.symbol ASC
        LIMIT %s
        """,
        [args.venue, args.venue, args.selection_limit],
    )

    sleeve_rows = fetch_rows(
        """
        SELECT
            account_id,
            sleeve_code,
            sleeve_status,
            target_weight,
            allocated_equity_eur,
            reserved_equity_eur,
            deployed_equity_eur,
            available_equity_eur,
            updated_ts_utc
        FROM portfolio_sleeve
        WHERE account_id = %s
          AND sleeve_code = %s
        """,
        [args.account_id, args.sleeve_code],
    )

    plan_rows = fetch_rows(
        """
        SELECT
            p.execution_plan_id,
            a.symbol,
            p.side,
            p.desired_action,
            p.plan_state,
            p.execution_mode,
            p.max_notional_eur,
            p.plan_ts_utc
        FROM execution_plan p
        JOIN asset a ON a.asset_id = p.asset_id
        WHERE p.account_id = %s
          AND p.sleeve_code = %s
          AND p.venue = %s
        ORDER BY p.execution_plan_id DESC
        LIMIT %s
        """,
        [args.account_id, args.sleeve_code, args.venue, args.plan_limit],
    )

    reservation_rows = fetch_rows(
        """
        SELECT
            cr.capital_reservation_id,
            cr.execution_plan_id,
            a.symbol,
            cr.reserved_amount_eur,
            cr.reservation_state
        FROM capital_reservation cr
        JOIN asset a ON a.asset_id = cr.asset_id
        WHERE cr.account_id = %s
          AND cr.sleeve_code = %s
        ORDER BY cr.capital_reservation_id DESC
        LIMIT %s
        """,
        [args.account_id, args.sleeve_code, args.plan_limit],
    )

    open_position_rows = fetch_rows(
        """
        SELECT
            pp.portfolio_position_id,
            a.symbol,
            pp.qty,
            pp.avg_entry_price,
            pp.mark_price,
            pp.market_value_eur,
            pp.realized_pnl_eur,
            pp.unrealized_pnl_eur,
            pp.position_status
        FROM portfolio_position pp
        JOIN asset a ON a.asset_id = pp.asset_id
        WHERE pp.account_id = %s
          AND pp.sleeve_code = %s
          AND pp.venue = %s
          AND pp.position_status = 'OPEN'
        ORDER BY pp.portfolio_position_id DESC
        """,
        [args.account_id, args.sleeve_code, args.venue],
    )

    closed_position_rows = fetch_rows(
        """
        SELECT
            pp.portfolio_position_id,
            a.symbol,
            pp.qty,
            pp.avg_entry_price,
            pp.mark_price,
            pp.market_value_eur,
            pp.realized_pnl_eur,
            pp.position_status,
            pp.updated_ts_utc
        FROM portfolio_position pp
        JOIN asset a ON a.asset_id = pp.asset_id
        WHERE pp.account_id = %s
          AND pp.sleeve_code = %s
          AND pp.venue = %s
          AND pp.position_status = 'CLOSED'
        ORDER BY pp.portfolio_position_id DESC
        LIMIT 10
        """,
        [args.account_id, args.sleeve_code, args.venue],
    )

    event_rows = fetch_rows(
        """
        SELECT
            ee.execution_event_id,
            ee.execution_plan_id,
            a.symbol,
            ee.event_type,
            ee.fill_price,
            ee.fill_qty
        FROM execution_event ee
        JOIN asset a ON a.asset_id = ee.asset_id
        WHERE ee.account_id = %s
          AND ee.sleeve_code = %s
        ORDER BY ee.execution_event_id DESC
        LIMIT %s
        """,
        [args.account_id, args.sleeve_code, args.event_limit],
    )

    eligible = sum(1 for r in selection_rows if r["selection_state"] in ("BUY_READY", "PREPARE"))
    active_plans = sum(1 for r in plan_rows if r["plan_state"] in ("IDLE", "PLANNED"))
    open_positions = len(open_position_rows)
    realized_pnl_total = sum(Decimal(str(r["realized_pnl_eur"])) for r in closed_position_rows) if closed_position_rows else Decimal("0")

    last_event_type = event_rows[0]["event_type"] if event_rows else None
    last_event_symbol = event_rows[0]["symbol"] if event_rows else None

    if sleeve_rows:
        s = sleeve_rows[0]
        reserved = s["reserved_equity_eur"]
        deployed = s["deployed_equity_eur"]
        available = s["available_equity_eur"]
    else:
        reserved = deployed = available = None

    print("=== SUMMARY ===")
    print(
        f"eligible={eligible} | active_plans={active_plans} | open_positions={open_positions} | "
        f"reserved={_fmt(reserved)} | deployed={_fmt(deployed)} | available={_fmt(available)} | "
        f"realized_pnl_total={_fmt(realized_pnl_total)} | last_event={_fmt(last_event_type)} | "
        f"last_symbol={_fmt(last_event_symbol)}"
    )

    _print_section("SELECTION")
    _print_table(
        ["symbol", "state", "bias", "score", "rank"],
        [[r["symbol"], r["selection_state"], r["selection_bias"], r["selection_score"], r["priority_rank"]] for r in selection_rows],
    )

    _print_section("PLANS")
    _print_table(
        ["id", "symbol", "side", "action", "state", "notional"],
        [[r["execution_plan_id"], r["symbol"], r["side"], r["desired_action"], r["plan_state"], r["max_notional_eur"]] for r in plan_rows],
    )

    _print_section("OPEN POSITIONS")
    _print_table(
        ["id", "symbol", "qty", "entry", "mark", "value", "realized", "unrealized", "status"],
        [[r["portfolio_position_id"], r["symbol"], r["qty"], r["avg_entry_price"], r["mark_price"], r["market_value_eur"], r["realized_pnl_eur"], r["unrealized_pnl_eur"], r["position_status"]] for r in open_position_rows],
    )

    _print_section("CLOSED POSITIONS")
    _print_table(
        ["id", "symbol", "qty", "entry", "mark", "value", "realized", "status", "updated"],
        [[r["portfolio_position_id"], r["symbol"], r["qty"], r["avg_entry_price"], r["mark_price"], r["market_value_eur"], r["realized_pnl_eur"], r["position_status"], r["updated_ts_utc"]] for r in closed_position_rows],
    )

    _print_section("EVENTS")
    _print_table(
        ["id", "plan", "symbol", "type", "price", "qty"],
        [[r["execution_event_id"], r["execution_plan_id"], r["symbol"], r["event_type"], r["fill_price"], r["fill_qty"]] for r in event_rows],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
