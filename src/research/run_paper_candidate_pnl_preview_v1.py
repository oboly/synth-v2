from __future__ import annotations

# Synth v2 - Paper Candidate PnL Preview V1.
#
# LAYER:
# research / paper-candidate diagnostics
#
# BOUNDARY:
# Allowed:
# - read staged paper candidate rows
# - compute deterministic simulated PnL from stored simulated_net_return
# - aggregate by batch and symbol
# - print table or JSON output
#
# Forbidden:
# - account balance writes
# - portfolio writes
# - decision_state writes
# - execution_intent writes
# - execution_plan writes
# - executor calls
# - broker/exchange actions
# - order handling
#
# IMPORTANT:
# simulated_net_return is a research/backtest field.
# It must never be used by live decision, live execution, or runtime selection.

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_TABLE = "research_paper_candidate_signal"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5_24h_tactical"
DEFAULT_SIGNAL_STATUS = "PROMOTION_CANDIDATE"
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


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
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument("--account-equity-eur", default="1000.00")
    parser.add_argument("--target-fraction", default="0.03300000")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit only the displayed per-candidate rows. Aggregates always use all matched rows.",
    )
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def decimal_required(value: Any, field_name: str) -> Decimal:
    result = decimal_or_none(value)
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def q(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def fetch_rows(args: argparse.Namespace) -> list[CandidatePnlRow]:
    safe_table = validate_table_name(args.table)
    account_equity_eur = Decimal(str(args.account_equity_eur))
    target_fraction = Decimal(str(args.target_fraction))
    notional_eur = account_equity_eur * target_fraction

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
    """

    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [args.policy_name, args.batch_id, args.signal_status])
            raw_rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[CandidatePnlRow] = []
    for row in raw_rows:
        simulated_return = decimal_required(row["simulated_net_return"], "simulated_net_return")
        out.append(
            CandidatePnlRow(
                candidate_id=int(row["candidate_id"]),
                symbol=str(row["symbol"]),
                asof_ts_utc=row["asof_ts_utc"],
                priority_rank=None if row.get("priority_rank") is None else int(row["priority_rank"]),
                selection_score=decimal_or_none(row.get("selection_score")),
                simulated_net_return=simulated_return,
                sleeve_fit_code=None if row.get("sleeve_fit_code") is None else str(row["sleeve_fit_code"]),
                execution_regime_label=None
                if row.get("execution_regime_label") is None
                else str(row["execution_regime_label"]),
                source_table=str(row["source_table"]),
                source_replay_id=int(row["source_replay_id"]),
                notional_eur=notional_eur,
                simulated_pnl_eur=notional_eur * simulated_return,
            )
        )

    return out


def aggregate(rows: list[CandidatePnlRow]) -> dict[str, Any]:
    trades = len(rows)
    if trades == 0:
        return {
            "trades": 0,
            "symbols": 0,
            "wins": 0,
            "losses": 0,
            "winrate": "0.0000",
            "gross_notional_eur": "0.00",
            "total_sim_pnl_eur": "0.0000",
            "avg_sim_pnl_eur": "0.0000",
            "avg_sim_return": "0.00000000",
        }

    wins = sum(1 for row in rows if row.simulated_net_return > 0)
    losses = sum(1 for row in rows if row.simulated_net_return < 0)
    total_pnl = sum((row.simulated_pnl_eur for row in rows), Decimal("0"))
    total_return = sum((row.simulated_net_return for row in rows), Decimal("0"))
    gross_notional = sum((row.notional_eur for row in rows), Decimal("0"))

    return {
        "trades": trades,
        "symbols": len({row.symbol for row in rows}),
        "wins": wins,
        "losses": losses,
        "winrate": str(q(Decimal(wins) / Decimal(trades), "0.0001")),
        "gross_notional_eur": str(q(gross_notional, "0.01")),
        "total_sim_pnl_eur": str(q(total_pnl, "0.0001")),
        "avg_sim_pnl_eur": str(q(total_pnl / Decimal(trades), "0.0001")),
        "avg_sim_return": str(q(total_return / Decimal(trades), "0.00000001")),
    }


def aggregate_by_symbol(rows: list[CandidatePnlRow]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    for row in rows:
        bucket = buckets.setdefault(
            row.symbol,
            {
                "symbol": row.symbol,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "return_sum": Decimal("0"),
                "sim_pnl_eur": Decimal("0"),
            },
        )
        bucket["trades"] += 1
        bucket["return_sum"] += row.simulated_net_return
        bucket["sim_pnl_eur"] += row.simulated_pnl_eur
        if row.simulated_net_return > 0:
            bucket["wins"] += 1
        elif row.simulated_net_return < 0:
            bucket["losses"] += 1

    out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        trades = Decimal(bucket["trades"])
        out.append(
            {
                "symbol": bucket["symbol"],
                "trades": bucket["trades"],
                "avg_return": str(q(bucket["return_sum"] / trades, "0.00000001")),
                "winrate": str(q(Decimal(bucket["wins"]) / trades, "0.0001")),
                "sim_pnl_eur": str(q(bucket["sim_pnl_eur"], "0.0001")),
            }
        )

    out.sort(key=lambda row: Decimal(row["sim_pnl_eur"]), reverse=True)
    return out


def row_to_dict(row: CandidatePnlRow) -> dict[str, Any]:
    payload = asdict(row)
    payload["asof_ts_utc"] = row.asof_ts_utc.isoformat(sep=" ")
    payload["selection_score"] = decimal_str(row.selection_score)
    payload["simulated_net_return"] = str(row.simulated_net_return)
    payload["notional_eur"] = str(row.notional_eur)
    payload["simulated_pnl_eur"] = str(row.simulated_pnl_eur)
    return payload


def build_payload(args: argparse.Namespace, rows: list[CandidatePnlRow]) -> dict[str, Any]:
    display_rows = rows if args.limit is None else rows[: max(args.limit, 0)]
    return {
        "meta": {
            "database": args.database,
            "table": args.table,
            "policy_name": args.policy_name,
            "batch_id": args.batch_id,
            "signal_status": args.signal_status,
            "account_equity_eur": str(Decimal(str(args.account_equity_eur))),
            "target_fraction": str(Decimal(str(args.target_fraction))),
            "rows_matched": len(rows),
            "detail_limit": args.limit,
            "writes": "none",
            "live_execution_permission": "NOT_GRANTED",
        },
        "aggregate": aggregate(rows),
        "symbol_preview": aggregate_by_symbol(rows),
        "detail_rows": [row_to_dict(row) for row in display_rows],
    }


def print_table(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    meta = payload["meta"]
    aggregate_payload = payload["aggregate"]

    print("Paper candidate PnL preview")
    for key in [
        "database",
        "table",
        "policy_name",
        "batch_id",
        "signal_status",
        "account_equity_eur",
        "target_fraction",
        "rows_matched",
        "detail_limit",
        "writes",
    ]:
        print(f"{key}: {meta[key]}")

    print()
    print("--- aggregate preview ---")
    for key in [
        "trades",
        "symbols",
        "wins",
        "losses",
        "winrate",
        "gross_notional_eur",
        "total_sim_pnl_eur",
        "avg_sim_pnl_eur",
        "avg_sim_return",
    ]:
        print(f"{key}: {aggregate_payload[key]}")

    print()
    print("--- per candidate preview ---")
    if args.limit is not None:
        print(f"displayed_rows: {len(payload['detail_rows'])} / {meta['rows_matched']}")
    print("candidate_id | ts | symbol | rank | score | sim_return | notional_eur | sim_pnl_eur")
    print("-" * 120)

    for row in payload["detail_rows"]:
        print(
            f"{row['candidate_id']} | "
            f"{row['asof_ts_utc']} | "
            f"{row['symbol']} | "
            f"{row['priority_rank']} | "
            f"{row['selection_score']} | "
            f"{q(Decimal(row['simulated_net_return']), '0.00000001')} | "
            f"{q(Decimal(row['notional_eur']), '0.01')} | "
            f"{q(Decimal(row['simulated_pnl_eur']), '0.0001')}"
        )

    print()
    print("--- symbol preview ---")
    print("symbol | trades | avg_return | winrate | sim_pnl_eur")
    print("-" * 80)

    for row in payload["symbol_preview"]:
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
    validate_table_name(args.table)

    rows = fetch_rows(args)
    payload = build_payload(args, rows)

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(args, payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
