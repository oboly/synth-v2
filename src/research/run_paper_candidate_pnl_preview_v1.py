from __future__ import annotations

"""
Synth v2 - Paper Candidate PnL Preview V1.

LAYER:
research / paper-candidate reporting

BOUNDARY:
Allowed:
- read staged research_paper_candidate_signal rows
- compute deterministic diagnostic paper PnL previews
- aggregate by candidate, symbol, and overall batch
- print table or JSON output

Forbidden:
- account balance writes
- portfolio position writes
- execution_plan writes
- decision_gate writes
- executor calls
- broker/exchange actions
- live trading permission

Purpose:
Provide a permanent read-only preview for staged paper candidates before building
a DB-backed paper simulation/reporting layer.
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_TABLE = "research_paper_candidate_signal"


@dataclass(frozen=True)
class CandidatePnlRow:
    candidate_id: int
    symbol: str
    asof_ts_utc: datetime
    priority_rank: int | None
    selection_score: Decimal | None
    simulated_net_return: Decimal
    sleeve_fit_code: str | None
    execution_regime_label: str | None
    source_table: str
    source_replay_id: int
    notional_eur: Decimal
    simulated_pnl_eur: Decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only PnL preview for staged paper candidate rows."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--policy-name", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--signal-status", default="PROMOTION_CANDIDATE")
    parser.add_argument("--account-equity-eur", default="1000.00")
    parser.add_argument("--target-fraction", default="0.03300000")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def decimal_or_zero(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def validate_table_name(table_name: str) -> str:
    if not table_name.replace("_", "").isalnum():
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def fetch_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    safe_table = validate_table_name(args.table)

    limit_clause = ""
    params: list[Any] = [
        args.policy_name,
        args.batch_id,
        args.signal_status,
    ]

    if args.limit and args.limit > 0:
        limit_clause = "LIMIT %s"
        params.append(args.limit)

    sql = f"""
    SELECT
        candidate_id,
        symbol,
        asof_ts_utc,
        priority_rank,
        selection_score,
        simulated_net_return,
        sleeve_fit_code,
        execution_regime_label,
        source_table,
        source_replay_id
    FROM {safe_table}
    WHERE policy_name = %s
      AND load_batch_id = %s
      AND signal_status = %s
      AND simulated_net_return IS NOT NULL
    ORDER BY asof_ts_utc ASC, candidate_id ASC
    {limit_clause}
    """

    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return list(rows)


def build_candidate_rows(args: argparse.Namespace) -> list[CandidatePnlRow]:
    raw_rows = fetch_rows(args)
    account_equity_eur = Decimal(str(args.account_equity_eur))
    target_fraction = Decimal(str(args.target_fraction))
    notional_eur = account_equity_eur * target_fraction

    out: list[CandidatePnlRow] = []

    for row in raw_rows:
        simulated_return = decimal_or_zero(row["simulated_net_return"])
        simulated_pnl_eur = notional_eur * simulated_return

        out.append(
            CandidatePnlRow(
                candidate_id=int(row["candidate_id"]),
                symbol=str(row["symbol"]),
                asof_ts_utc=row["asof_ts_utc"],
                priority_rank=None if row["priority_rank"] is None else int(row["priority_rank"]),
                selection_score=decimal_or_none(row["selection_score"]),
                simulated_net_return=simulated_return,
                sleeve_fit_code=None if row["sleeve_fit_code"] is None else str(row["sleeve_fit_code"]),
                execution_regime_label=None
                if row["execution_regime_label"] is None
                else str(row["execution_regime_label"]),
                source_table=str(row["source_table"]),
                source_replay_id=int(row["source_replay_id"]),
                notional_eur=notional_eur,
                simulated_pnl_eur=simulated_pnl_eur,
            )
        )

    return out


def summarize(rows: list[CandidatePnlRow]) -> dict[str, Any]:
    if not rows:
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
        }

    trades = Decimal(len(rows))
    wins = sum(1 for row in rows if row.simulated_net_return > 0)
    losses = sum(1 for row in rows if row.simulated_net_return < 0)
    total_pnl = sum((row.simulated_pnl_eur for row in rows), Decimal("0"))
    total_return = sum((row.simulated_net_return for row in rows), Decimal("0"))
    gross_notional = sum((row.notional_eur for row in rows), Decimal("0"))

    return {
        "trades": len(rows),
        "symbols": len({row.symbol for row in rows}),
        "wins": wins,
        "losses": losses,
        "winrate": str((Decimal(wins) / trades).quantize(Decimal("0.0001"))),
        "gross_notional_eur": str(gross_notional.quantize(Decimal("0.01"))),
        "total_sim_pnl_eur": str(total_pnl.quantize(Decimal("0.0001"))),
        "avg_sim_pnl_eur": str((total_pnl / trades).quantize(Decimal("0.0001"))),
        "avg_sim_return": str((total_return / trades).quantize(Decimal("0.00000001"))),
    }


def summarize_symbols(rows: list[CandidatePnlRow]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trades": 0,
            "return_sum": Decimal("0"),
            "pnl_sum": Decimal("0"),
            "wins": 0,
            "losses": 0,
        }
    )

    for row in rows:
        item = stats[row.symbol]
        item["trades"] += 1
        item["return_sum"] += row.simulated_net_return
        item["pnl_sum"] += row.simulated_pnl_eur

        if row.simulated_net_return > 0:
            item["wins"] += 1
        elif row.simulated_net_return < 0:
            item["losses"] += 1

    out: list[dict[str, Any]] = []
    for symbol, item in stats.items():
        trades = Decimal(item["trades"])
        out.append(
            {
                "symbol": symbol,
                "trades": item["trades"],
                "avg_return": str((item["return_sum"] / trades).quantize(Decimal("0.00000001"))),
                "winrate": str((Decimal(item["wins"]) / trades).quantize(Decimal("0.0001"))),
                "sim_pnl_eur": str(item["pnl_sum"].quantize(Decimal("0.0001"))),
            }
        )

    return sorted(out, key=lambda row: Decimal(row["sim_pnl_eur"]), reverse=True)


def row_to_json(row: CandidatePnlRow) -> dict[str, Any]:
    return {
        "candidate_id": row.candidate_id,
        "symbol": row.symbol,
        "asof_ts_utc": row.asof_ts_utc.isoformat(sep=" "),
        "priority_rank": row.priority_rank,
        "selection_score": None if row.selection_score is None else str(row.selection_score),
        "simulated_net_return": str(row.simulated_net_return),
        "sleeve_fit_code": row.sleeve_fit_code,
        "execution_regime_label": row.execution_regime_label,
        "source_table": row.source_table,
        "source_replay_id": row.source_replay_id,
        "notional_eur": str(row.notional_eur.quantize(Decimal("0.01"))),
        "simulated_pnl_eur": str(row.simulated_pnl_eur.quantize(Decimal("0.0001"))),
    }


def print_table(args: argparse.Namespace, rows: list[CandidatePnlRow]) -> None:
    summary = summarize(rows)
    symbols = summarize_symbols(rows)

    print("Paper candidate PnL preview")
    print(f"database: {args.database}")
    print(f"table: {args.table}")
    print(f"policy_name: {args.policy_name}")
    print(f"batch_id: {args.batch_id}")
    print(f"signal_status: {args.signal_status}")
    print(f"account_equity_eur: {Decimal(str(args.account_equity_eur))}")
    print(f"target_fraction: {Decimal(str(args.target_fraction))}")
    print("writes: none")
    print()

    print("--- aggregate preview ---")
    for key, value in summary.items():
        print(f"{key}: {value}")

    print()
    print("--- per candidate preview ---")
    print("candidate_id | ts | symbol | rank | score | sim_return | notional_eur | sim_pnl_eur")
    print("-" * 120)
    for row in rows:
        print(
            f"{row.candidate_id} | "
            f"{row.asof_ts_utc} | "
            f"{row.symbol} | "
            f"{row.priority_rank} | "
            f"{row.selection_score} | "
            f"{row.simulated_net_return.quantize(Decimal('0.00000001'))} | "
            f"{row.notional_eur.quantize(Decimal('0.01'))} | "
            f"{row.simulated_pnl_eur.quantize(Decimal('0.0001'))}"
        )

    print()
    print("--- symbol preview ---")
    print("symbol | trades | avg_return | winrate | sim_pnl_eur")
    print("-" * 80)
    for row in symbols:
        print(
            f"{row['symbol']} | "
            f"{row['trades']} | "
            f"{row['avg_return']} | "
            f"{row['winrate']} | "
            f"{row['sim_pnl_eur']}"
        )

    print()
    print("--- interpretation ---")
    print("READ_ONLY_PREVIEW: no DB writes, no execution plans, no orders.")
    print("LIVE_EXECUTION_PERMISSION: NOT_GRANTED")


def main() -> int:
    args = parse_args()
    rows = build_candidate_rows(args)

    if args.output == "json":
        payload = {
            "summary": summarize(rows),
            "symbols": summarize_symbols(rows),
            "rows": [row_to_json(row) for row in rows],
            "writes": "none",
            "live_execution_permission": "NOT_GRANTED",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print_table(args, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
