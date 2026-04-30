from __future__ import annotations

# Synth v2 - Paper Candidate Ledger Preview V1.
#
# LAYER:
# research / paper simulation ledger preview
#
# BOUNDARY:
# Allowed:
# - read staged paper candidate rows
# - read research/backtest evaluation rows
# - use point-in-time entry price
# - use simulated forward exit price and simulated net return
# - compute deterministic OPEN and CLOSE ledger preview events
# - print table or JSON output
#
# Forbidden:
# - decision_state writes
# - execution_plan writes
# - live orders
# - account balance mutation
# - future-return fields outside research/backtest namespace
#
# NOTE:
# This tool intentionally uses simulated future returns and forward prices.
# It must remain in the research/backtest namespace only.

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_STAGE_TABLE = "research_paper_candidate_signal"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v2"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5_24h_tactical"
DEFAULT_BATCH_ID = "arena_v2_24h_tactical_2026"
DEFAULT_SIGNAL_STATUS = "PROMOTION_CANDIDATE"

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
SUPPORTED_HORIZONS = {4, 24, 48, 72, 168}
RETURN_TOLERANCE = Decimal("0.00000001")
QTY_Q = Decimal("0.00000001")
RETURN_Q = Decimal("0.00000001")
PNL_Q = Decimal("0.0001")
EUR_Q = Decimal("0.01")


@dataclass(frozen=True)
class SimulatedTrade:
    candidate_id: int
    source_replay_id: int
    symbol: str
    asset_id: int
    sleeve_fit_code: str
    execution_regime_label: str | None
    entry_ts_utc: datetime
    exit_ts_utc: datetime
    priority_rank: int | None
    selection_score: Decimal | None
    entry_price_eur: Decimal
    exit_price_eur: Decimal
    qty: Decimal
    notional_eur: Decimal
    simulated_net_return: Decimal
    eval_net_return: Decimal
    pnl_eur: Decimal
    return_mismatch_abs: Decimal


@dataclass(frozen=True)
class LedgerEvent:
    candidate_id: int
    source_replay_id: int
    symbol: str
    asset_id: int
    event_type: str
    ts_utc: datetime
    price_eur: Decimal
    qty_delta: Decimal
    notional_delta_eur: Decimal
    cashflow_eur: Decimal
    realized_pnl_eur: Decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only paper candidate ledger preview for research candidates."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--stage-table", default=DEFAULT_STAGE_TABLE)
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--account-equity-eur", default="1000.00")
    parser.add_argument("--target-fraction", default="0.03300000")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(value: str) -> str:
    if not TABLE_NAME_PATTERN.match(value):
        raise ValueError(f"Unsafe table name: {value}")
    return value


def to_decimal(value: Any, *, field_name: str) -> Decimal:
    if value is None:
        raise ValueError(f"Missing decimal field: {field_name}")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def fetch_trades(args: argparse.Namespace) -> list[SimulatedTrade]:
    hold_hours = int(args.hold_hours)
    if hold_hours not in SUPPORTED_HORIZONS:
        raise ValueError(f"Unsupported hold horizon: {hold_hours}")

    stage_table = validate_table_name(args.stage_table)
    eval_table = validate_table_name(args.eval_table)
    return_col = f"net_return_{hold_hours}h"
    exit_price_col = f"forward_close_price_{hold_hours}h"
    fixed_notional = Decimal(str(args.account_equity_eur)) * Decimal(str(args.target_fraction))

    sql = f"""
    SELECT
        s.candidate_id,
        s.source_replay_id,
        s.symbol,
        s.asset_id,
        s.sleeve_fit_code,
        s.execution_regime_label,
        s.asof_ts_utc,
        s.priority_rank,
        s.selection_score,
        s.simulated_net_return,
        e.entry_close_price,
        e.{exit_price_col} AS exit_price_eur,
        e.{return_col} AS eval_net_return
    FROM {stage_table} s
    JOIN {eval_table} e
      ON e.bt_selection_v2_replay_id = s.source_replay_id
     AND e.asset_id = s.asset_id
     AND e.symbol = s.symbol
    WHERE s.policy_name = %s
      AND s.load_batch_id = %s
      AND s.signal_status = %s
      AND s.source_table = %s
      AND s.simulated_horizon_hours = %s
      AND s.simulated_net_return IS NOT NULL
      AND e.entry_close_price IS NOT NULL
      AND e.{exit_price_col} IS NOT NULL
      AND e.{return_col} IS NOT NULL
    ORDER BY s.asof_ts_utc ASC, s.candidate_id ASC
    """

    params: list[Any] = [
        args.policy_name,
        args.batch_id,
        args.signal_status,
        args.eval_table,
        hold_hours,
    ]

    if args.limit and int(args.limit) > 0:
        sql += "\n    LIMIT %s"
        params.append(int(args.limit))

    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    trades: list[SimulatedTrade] = []
    for row in rows:
        candidate_id = int(row["candidate_id"])
        entry_price = to_decimal(row["entry_close_price"], field_name="entry_close_price")
        exit_price = to_decimal(row["exit_price_eur"], field_name="exit_price_eur")
        simulated_return = to_decimal(row["simulated_net_return"], field_name="simulated_net_return")
        eval_return = to_decimal(row["eval_net_return"], field_name="eval_net_return")

        if entry_price <= 0:
            raise ValueError(f"Invalid entry price for candidate_id={candidate_id}")

        entry_ts = row["asof_ts_utc"]
        if not isinstance(entry_ts, datetime):
            entry_ts = datetime.fromisoformat(str(entry_ts))

        qty = fixed_notional / entry_price
        pnl = fixed_notional * simulated_return

        trades.append(
            SimulatedTrade(
                candidate_id=candidate_id,
                source_replay_id=int(row["source_replay_id"]),
                symbol=str(row["symbol"]),
                asset_id=int(row["asset_id"]),
                sleeve_fit_code=str(row["sleeve_fit_code"]),
                execution_regime_label=None if row.get("execution_regime_label") is None else str(row["execution_regime_label"]),
                entry_ts_utc=entry_ts,
                exit_ts_utc=entry_ts + timedelta(hours=hold_hours),
                priority_rank=None if row.get("priority_rank") is None else int(row["priority_rank"]),
                selection_score=to_decimal_or_none(row.get("selection_score")),
                entry_price_eur=entry_price,
                exit_price_eur=exit_price,
                qty=qty,
                notional_eur=fixed_notional,
                simulated_net_return=simulated_return,
                eval_net_return=eval_return,
                pnl_eur=pnl,
                return_mismatch_abs=abs(simulated_return - eval_return),
            )
        )

    return trades


def build_events(trades: list[SimulatedTrade]) -> list[LedgerEvent]:
    events: list[LedgerEvent] = []
    for trade in trades:
        events.append(
            LedgerEvent(
                candidate_id=trade.candidate_id,
                source_replay_id=trade.source_replay_id,
                symbol=trade.symbol,
                asset_id=trade.asset_id,
                event_type="OPEN",
                ts_utc=trade.entry_ts_utc,
                price_eur=trade.entry_price_eur,
                qty_delta=trade.qty,
                notional_delta_eur=trade.notional_eur,
                cashflow_eur=-trade.notional_eur,
                realized_pnl_eur=Decimal("0"),
            )
        )
        events.append(
            LedgerEvent(
                candidate_id=trade.candidate_id,
                source_replay_id=trade.source_replay_id,
                symbol=trade.symbol,
                asset_id=trade.asset_id,
                event_type="CLOSE",
                ts_utc=trade.exit_ts_utc,
                price_eur=trade.exit_price_eur,
                qty_delta=-trade.qty,
                notional_delta_eur=-trade.notional_eur,
                cashflow_eur=trade.notional_eur + trade.pnl_eur,
                realized_pnl_eur=trade.pnl_eur,
            )
        )

    return sorted(events, key=lambda event: (event.ts_utc, event.candidate_id, event.event_type))


def aggregate_trades(trades: list[SimulatedTrade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "symbols": 0,
            "wins": 0,
            "losses": 0,
            "winrate": None,
            "gross_notional_eur": "0.00",
            "total_sim_pnl_eur": "0.0000",
            "avg_sim_pnl_eur": None,
            "avg_sim_return": None,
            "return_mismatch_rows": 0,
        }

    total_pnl = sum((trade.pnl_eur for trade in trades), Decimal("0"))
    total_return = sum((trade.simulated_net_return for trade in trades), Decimal("0"))
    wins = sum(1 for trade in trades if trade.simulated_net_return > 0)
    losses = sum(1 for trade in trades if trade.simulated_net_return < 0)
    mismatch_rows = sum(1 for trade in trades if trade.return_mismatch_abs > RETURN_TOLERANCE)
    count = Decimal(len(trades))

    return {
        "trades": len(trades),
        "symbols": len({trade.symbol for trade in trades}),
        "wins": wins,
        "losses": losses,
        "winrate": str((Decimal(wins) / count).quantize(Decimal("0.0001"))),
        "gross_notional_eur": str(sum((trade.notional_eur for trade in trades), Decimal("0")).quantize(EUR_Q)),
        "total_sim_pnl_eur": str(total_pnl.quantize(PNL_Q)),
        "avg_sim_pnl_eur": str((total_pnl / count).quantize(PNL_Q)),
        "avg_sim_return": str((total_return / count).quantize(RETURN_Q)),
        "return_mismatch_rows": mismatch_rows,
    }


def symbol_summary(trades: list[SimulatedTrade]) -> list[dict[str, Any]]:
    grouped: dict[str, list[SimulatedTrade]] = {}
    for trade in trades:
        grouped.setdefault(trade.symbol, []).append(trade)

    out: list[dict[str, Any]] = []
    for symbol, rows in grouped.items():
        count = Decimal(len(rows))
        wins = sum(1 for row in rows if row.simulated_net_return > 0)
        total_return = sum((row.simulated_net_return for row in rows), Decimal("0"))
        total_pnl = sum((row.pnl_eur for row in rows), Decimal("0"))
        out.append(
            {
                "symbol": symbol,
                "trades": len(rows),
                "avg_return": (total_return / count).quantize(RETURN_Q),
                "winrate": (Decimal(wins) / count).quantize(Decimal("0.0001")),
                "sim_pnl_eur": total_pnl.quantize(PNL_Q),
            }
        )

    return sorted(out, key=lambda item: item["sim_pnl_eur"], reverse=True)


def print_table(args: argparse.Namespace, trades: list[SimulatedTrade], events: list[LedgerEvent]) -> None:
    aggregate = aggregate_trades(trades)
    print("Paper candidate ledger preview")
    print(f"database: {args.database}")
    print(f"stage_table: {args.stage_table}")
    print(f"eval_table: {args.eval_table}")
    print(f"policy_name: {args.policy_name}")
    print(f"batch_id: {args.batch_id}")
    print(f"signal_status: {args.signal_status}")
    print(f"hold_hours: {args.hold_hours}")
    print(f"account_equity_eur: {args.account_equity_eur}")
    print(f"target_fraction: {args.target_fraction}")
    print("writes: none")
    print()

    print("--- aggregate preview ---")
    for key, value in aggregate.items():
        print(f"{key}: {value}")
    print()

    print("--- simulated trades ---")
    print("candidate_id | entry_ts | exit_ts | symbol | qty | entry | exit | return | pnl")
    print("-" * 130)
    for trade in trades:
        print(
            f"{trade.candidate_id} | "
            f"{trade.entry_ts_utc} | "
            f"{trade.exit_ts_utc} | "
            f"{trade.symbol} | "
            f"{trade.qty.quantize(QTY_Q)} | "
            f"{trade.entry_price_eur} | "
            f"{trade.exit_price_eur} | "
            f"{trade.simulated_net_return.quantize(RETURN_Q)} | "
            f"{trade.pnl_eur.quantize(PNL_Q)}"
        )
    print()

    print("--- ledger events ---")
    print("ts | candidate_id | symbol | event | qty_delta | price | cashflow | realized_pnl")
    print("-" * 130)
    for event in events:
        print(
            f"{event.ts_utc} | "
            f"{event.candidate_id} | "
            f"{event.symbol} | "
            f"{event.event_type} | "
            f"{event.qty_delta.quantize(QTY_Q)} | "
            f"{event.price_eur} | "
            f"{event.cashflow_eur.quantize(PNL_Q)} | "
            f"{event.realized_pnl_eur.quantize(PNL_Q)}"
        )
    print()

    print("--- symbol preview ---")
    print("symbol | trades | avg_return | winrate | sim_pnl_eur")
    print("-" * 80)
    for row in symbol_summary(trades):
        symbol = row["symbol"]
        trade_count = row["trades"]
        avg_return = row["avg_return"]
        winrate = row["winrate"]
        sim_pnl = row["sim_pnl_eur"]
        print(f"{symbol} | {trade_count} | {avg_return} | {winrate} | {sim_pnl}")
    print()

    print("--- interpretation ---")
    print("READ_ONLY_PREVIEW: no DB writes, no execution plans, no orders.")
    print("RESEARCH_LEDGER_ONLY: uses simulated future exit prices and returns.")
    print("LIVE_EXECUTION_PERMISSION: NOT_GRANTED")


def main() -> int:
    args = parse_args()
    trades = fetch_trades(args)
    events = build_events(trades)
    payload = {
        "summary": aggregate_trades(trades),
        "trades": [asdict(trade) for trade in trades],
        "events": [asdict(event) for event in events],
        "symbols": symbol_summary(trades),
    }

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(args, trades, events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
