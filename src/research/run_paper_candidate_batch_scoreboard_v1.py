from __future__ import annotations

# Synth v2 - Paper Candidate Batch Scoreboard V1.
#
# LAYER:
# research / paper-candidate batch comparison
#
# BOUNDARY:
# Allowed:
# - read staged paper candidate rows
# - compute deterministic batch-level preview metrics
# - compare PnL and fixed-window capacity across batches
#
# Forbidden:
# - database writes
# - decision_state writes
# - execution_plan writes
# - live orders
# - account balance mutation
#
# NOTE:
# This tool intentionally reads simulated future returns.
# It must remain in the research/backtest namespace only.

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_TABLE = "research_paper_candidate_signal"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5_24h_tactical"
DEFAULT_SIGNAL_STATUS = "PROMOTION_CANDIDATE"
DEFAULT_ACCOUNT_EQUITY_EUR = "1000.00"
DEFAULT_TARGET_FRACTION = "0.03300000"
DEFAULT_HOLD_HOURS = 24
DEFAULT_MAX_SLEEVE_FRACTION = "0.25"

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class BatchSummary:
    batch_id: str
    policy_name: str
    signal_status: str
    trades: int
    symbols: int
    wins: int
    losses: int
    winrate: Decimal
    avg_sim_return: Decimal
    total_sim_pnl_eur: Decimal
    gross_notional_eur: Decimal
    per_trade_notional_eur: Decimal
    max_active_positions: int
    max_active_notional_eur: Decimal
    max_active_fraction_of_equity: Decimal
    max_active_fraction_of_sleeve: Decimal
    sleeve_cap_eur: Decimal
    capacity_state: str
    first_ts_utc: datetime | None
    last_ts_utc: datetime | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare read-only paper candidate batch preview metrics."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument("--batch-ids", default=None)
    parser.add_argument("--account-equity-eur", default=DEFAULT_ACCOUNT_EQUITY_EUR)
    parser.add_argument("--target-fraction", default=DEFAULT_TARGET_FRACTION)
    parser.add_argument("--hold-hours", type=int, default=DEFAULT_HOLD_HOURS)
    parser.add_argument("--max-sleeve-fraction", default=DEFAULT_MAX_SLEEVE_FRACTION)
    parser.add_argument("--limit-batches", type=int, default=20)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def parse_batch_ids(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    out = [part.strip() for part in value.split(",") if part.strip()]
    return out or None


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def fetch_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    safe_table = validate_table_name(args.table)
    batch_ids = parse_batch_ids(args.batch_ids)

    filters = [
        "policy_name = %s",
        "signal_status = %s",
        "simulated_net_return IS NOT NULL",
    ]
    params: list[Any] = [args.policy_name, args.signal_status]

    if batch_ids is not None:
        placeholders = ", ".join(["%s"] * len(batch_ids))
        filters.append(f"load_batch_id IN ({placeholders})")
        params.extend(batch_ids)

    where_sql = " AND ".join(filters)
    sql = f"""
    SELECT
        candidate_id,
        load_batch_id,
        policy_name,
        signal_status,
        symbol,
        asset_id,
        asof_ts_utc,
        priority_rank,
        selection_score,
        simulated_net_return,
        sleeve_fit_code,
        execution_regime_label
    FROM {safe_table}
    WHERE {where_sql}
    ORDER BY load_batch_id ASC, asof_ts_utc ASC, candidate_id ASC
    """

    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return list(rows)


def build_exposure(rows: list[dict[str, Any]], *, notional: Decimal, hold_hours: int) -> tuple[int, Decimal]:
    events: list[tuple[datetime, int, int, Decimal]] = []
    for row in rows:
        entry_ts = row["asof_ts_utc"]
        exit_ts = entry_ts + timedelta(hours=hold_hours)
        events.append((exit_ts, 0, -1, -notional))
        events.append((entry_ts, 1, 1, notional))

    active_positions = 0
    active_notional = Decimal("0")
    max_active_positions = 0
    max_active_notional = Decimal("0")

    for _ts, _priority, position_delta, notional_delta in sorted(events):
        active_positions += position_delta
        active_notional += notional_delta
        if active_positions > max_active_positions:
            max_active_positions = active_positions
        if active_notional > max_active_notional:
            max_active_notional = active_notional

    return max_active_positions, max_active_notional


def summarize_batch(
    *,
    batch_id: str,
    rows: list[dict[str, Any]],
    account_equity_eur: Decimal,
    target_fraction: Decimal,
    hold_hours: int,
    max_sleeve_fraction: Decimal,
) -> BatchSummary:
    notional = account_equity_eur * target_fraction
    sleeve_cap_eur = account_equity_eur * max_sleeve_fraction

    returns = [dec(row["simulated_net_return"]) for row in rows]
    wins = sum(1 for value in returns if value > 0)
    losses = sum(1 for value in returns if value < 0)
    trades = len(rows)
    symbols = len({str(row["symbol"]) for row in rows})
    total_return = sum(returns, Decimal("0"))
    total_pnl = sum((notional * value for value in returns), Decimal("0"))
    gross_notional = notional * Decimal(trades)
    winrate = Decimal(wins) / Decimal(trades) if trades else Decimal("0")
    avg_return = total_return / Decimal(trades) if trades else Decimal("0")

    max_positions, max_notional = build_exposure(
        rows,
        notional=notional,
        hold_hours=hold_hours,
    )

    capacity_state = "PASS" if max_notional <= sleeve_cap_eur else "WATCH_CAPACITY"
    first_ts = min((row["asof_ts_utc"] for row in rows), default=None)
    last_ts = max((row["asof_ts_utc"] for row in rows), default=None)

    return BatchSummary(
        batch_id=batch_id,
        policy_name=str(rows[0]["policy_name"]) if rows else "",
        signal_status=str(rows[0]["signal_status"]) if rows else "",
        trades=trades,
        symbols=symbols,
        wins=wins,
        losses=losses,
        winrate=winrate,
        avg_sim_return=avg_return,
        total_sim_pnl_eur=total_pnl,
        gross_notional_eur=gross_notional,
        per_trade_notional_eur=notional,
        max_active_positions=max_positions,
        max_active_notional_eur=max_notional,
        max_active_fraction_of_equity=max_notional / account_equity_eur if account_equity_eur else Decimal("0"),
        max_active_fraction_of_sleeve=max_notional / sleeve_cap_eur if sleeve_cap_eur else Decimal("0"),
        sleeve_cap_eur=sleeve_cap_eur,
        capacity_state=capacity_state,
        first_ts_utc=first_ts,
        last_ts_utc=last_ts,
    )


def build_scoreboard(args: argparse.Namespace) -> list[BatchSummary]:
    rows = fetch_rows(args)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["load_batch_id"])].append(row)

    summaries = [
        summarize_batch(
            batch_id=batch_id,
            rows=batch_rows,
            account_equity_eur=dec(args.account_equity_eur),
            target_fraction=dec(args.target_fraction),
            hold_hours=int(args.hold_hours),
            max_sleeve_fraction=dec(args.max_sleeve_fraction),
        )
        for batch_id, batch_rows in grouped.items()
    ]

    summaries.sort(
        key=lambda item: (
            item.capacity_state != "PASS",
            -item.total_sim_pnl_eur,
            -item.trades,
            item.batch_id,
        )
    )

    return summaries[: int(args.limit_batches)]


def summary_to_dict(row: BatchSummary) -> dict[str, Any]:
    return asdict(row)


def fmt_dec(value: Decimal, places: str) -> str:
    return str(value.quantize(Decimal(places)))


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "None"
    return value.isoformat(sep=" ")


def print_table(args: argparse.Namespace, rows: list[BatchSummary]) -> None:
    print("Paper candidate batch scoreboard")
    print(f"database: {args.database}")
    print(f"table: {args.table}")
    print(f"policy_name: {args.policy_name}")
    print(f"signal_status: {args.signal_status}")
    print(f"account_equity_eur: {args.account_equity_eur}")
    print(f"target_fraction: {args.target_fraction}")
    print(f"hold_hours: {args.hold_hours}")
    print(f"max_sleeve_fraction: {args.max_sleeve_fraction}")
    print("writes: none")
    print()
    print("--- scoreboard ---")
    print("batch_id | trades | symbols | winrate | avg_return | total_pnl | max_pos | max_notional | sleeve_used | capacity | first_ts | last_ts")
    print("-" * 190)
    for row in rows:
        print(
            f"{row.batch_id} | "
            f"{row.trades} | "
            f"{row.symbols} | "
            f"{fmt_dec(row.winrate, "0.0001")} | "
            f"{fmt_dec(row.avg_sim_return, "0.00000001")} | "
            f"{fmt_dec(row.total_sim_pnl_eur, "0.0001")} | "
            f"{row.max_active_positions} | "
            f"{fmt_dec(row.max_active_notional_eur, "0.01")} | "
            f"{fmt_dec(row.max_active_fraction_of_sleeve, "0.0001")} | "
            f"{row.capacity_state} | "
            f"{fmt_ts(row.first_ts_utc)} | "
            f"{fmt_ts(row.last_ts_utc)}"
        )
    print()
    print("--- interpretation ---")
    print("READ_ONLY_PREVIEW: no DB writes, no execution plans, no orders.")
    print("RESEARCH_SCOREBOARD_ONLY: uses simulated future returns.")
    print("LIVE_EXECUTION_PERMISSION: NOT_GRANTED")


def main() -> int:
    args = parse_args()
    rows = build_scoreboard(args)
    payload = {
        "scoreboard_version": "paper_candidate_batch_scoreboard_v1",
        "inputs": {
            "database": args.database,
            "table": args.table,
            "policy_name": args.policy_name,
            "signal_status": args.signal_status,
            "batch_ids": args.batch_ids,
            "account_equity_eur": args.account_equity_eur,
            "target_fraction": args.target_fraction,
            "hold_hours": args.hold_hours,
            "max_sleeve_fraction": args.max_sleeve_fraction,
        },
        "rows": [summary_to_dict(row) for row in rows],
    }

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(args, rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
