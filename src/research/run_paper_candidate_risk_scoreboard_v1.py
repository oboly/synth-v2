from __future__ import annotations

# Synth v2 - Paper Candidate Risk Scoreboard V1.
#
# LAYER:
# research / paper-candidate benchmark diagnostics
#
# BOUNDARY:
# Allowed:
# - read staged paper candidate batches
# - reuse read-only curve risk metrics
# - compare batches on return, drawdown, exposure, and benchmark excess return
# - print table or JSON output
#
# Forbidden:
# - database writes
# - decision_state writes
# - execution_plan writes
# - live orders
# - account balance mutation
#
# NOTE:
# This tool intentionally consumes research/backtest paper-candidate outputs.
# It must remain in the research/backtest namespace only.

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.research.run_paper_candidate_curve_risk_metrics_v1 import build_payload


DEFAULT_DATABASE = "synth_bt"
DEFAULT_STAGE_TABLE = "research_paper_candidate_signal"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v2"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5_24h_tactical"
DEFAULT_SIGNAL_STATUS = "PROMOTION_CANDIDATE"

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class BatchRef:
    batch_id: str
    staged_rows: int
    first_ts_utc: datetime | None
    last_ts_utc: datetime | None


@dataclass(frozen=True)
class ScoreboardRow:
    batch_id: str
    trades: int
    symbols: int
    strategy_return_pct: Decimal
    strategy_max_drawdown_pct: Decimal
    benchmark_symbols: str
    benchmark_count: int
    benchmark_beaten_count: int
    best_benchmark_symbol: str | None
    best_benchmark_return_pct: Decimal | None
    avg_benchmark_return_pct: Decimal | None
    excess_return_vs_best_benchmark_pct: Decimal | None
    time_in_market_fraction: Decimal
    max_active_positions: int
    max_active_notional_eur: Decimal
    gross_notional_eur: Decimal
    return_per_max_active_notional_pct: Decimal
    return_per_gross_notional_pct: Decimal
    first_ts_utc: datetime | None
    last_ts_utc: datetime | None
    risk_state: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare staged paper-candidate batches using risk/exposure metrics."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--stage-table", default=DEFAULT_STAGE_TABLE)
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument(
        "--batch-id-values",
        default=None,
        help="Comma-separated batch ids. If omitted, all matching staged batches are scored.",
    )
    parser.add_argument("--account-equity-eur", default="1000.00")
    parser.add_argument("--target-fraction", default="0.03300000")
    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--benchmark-symbols", default="BTC,ETH")
    parser.add_argument("--limit-batches", type=int, default=None)
    parser.add_argument("--min-return-pct", default="0.00")
    parser.add_argument("--max-strategy-drawdown-pct", default="-5.00")
    parser.add_argument("--min-return-per-max-active-notional-pct", default="10.00")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def dec(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def dec0(value: Any) -> Decimal:
    parsed = dec(value, Decimal("0"))
    if parsed is None:
        return Decimal("0")
    return parsed


def fmt_dec(value: Decimal | None, places: str = "0.0000") -> str:
    if value is None:
        return "None"
    return str(value.quantize(Decimal(places)))


def parse_batch_id_values(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def fetch_batch_refs(args: argparse.Namespace) -> list[BatchRef]:
    safe_table = validate_table_name(args.stage_table)
    requested = parse_batch_id_values(args.batch_id_values)

    params: list[Any] = [args.policy_name, args.signal_status]
    filters = [
        "policy_name = %s",
        "signal_status = %s",
    ]

    if requested:
        placeholders = ", ".join(["%s"] * len(requested))
        filters.append(f"load_batch_id IN ({placeholders})")
        params.extend(requested)

    limit_sql = ""
    if args.limit_batches is not None:
        limit_sql = f"LIMIT {int(args.limit_batches)}"

    sql = f"""
    SELECT
        load_batch_id,
        COUNT(*) AS staged_rows,
        MIN(asof_ts_utc) AS first_ts_utc,
        MAX(asof_ts_utc) AS last_ts_utc
    FROM {safe_table}
    WHERE {" AND ".join(filters)}
    GROUP BY load_batch_id
    ORDER BY MIN(asof_ts_utc), load_batch_id
    {limit_sql}
    """

    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        BatchRef(
            batch_id=str(row["load_batch_id"]),
            staged_rows=int(row["staged_rows"]),
            first_ts_utc=row.get("first_ts_utc"),
            last_ts_utc=row.get("last_ts_utc"),
        )
        for row in rows
    ]


def classify_row(
    *,
    strategy_return_pct: Decimal,
    strategy_max_drawdown_pct: Decimal,
    return_per_max_active_notional_pct: Decimal,
    benchmark_count: int,
    benchmark_beaten_count: int,
    args: argparse.Namespace,
) -> str:
    min_return_pct = dec0(args.min_return_pct)
    max_strategy_drawdown_pct = dec0(args.max_strategy_drawdown_pct)
    min_efficiency_pct = dec0(args.min_return_per_max_active_notional_pct)

    if strategy_return_pct < min_return_pct:
        return "REJECT_RETURN"

    if strategy_max_drawdown_pct < max_strategy_drawdown_pct:
        return "REJECT_DRAWDOWN"

    if return_per_max_active_notional_pct < min_efficiency_pct:
        return "WATCH_LOW_EFFICIENCY"

    if benchmark_count > 0 and benchmark_beaten_count == benchmark_count:
        return "STRONG_BEATS_BENCHMARKS"

    return "LOW_EXPOSURE_ALPHA_CANDIDATE"


def build_risk_args(args: argparse.Namespace, batch_id: str) -> argparse.Namespace:
    return argparse.Namespace(
        database=args.database,
        stage_table=args.stage_table,
        eval_table=args.eval_table,
        policy_name=args.policy_name,
        batch_id=batch_id,
        signal_status=args.signal_status,
        account_equity_eur=args.account_equity_eur,
        target_fraction=args.target_fraction,
        hold_hours=args.hold_hours,
        benchmark_symbols=args.benchmark_symbols,
        limit=None,
        output="json",
    )


def build_scoreboard_row(args: argparse.Namespace, batch: BatchRef) -> ScoreboardRow:
    payload = build_payload(build_risk_args(args, batch.batch_id))

    summary = payload["summary"]
    strategy = payload["strategy"]
    exposure = payload["exposure"]
    comparisons = payload["comparisons"]

    strategy_return_pct = dec0(strategy["return_pct"])
    strategy_max_drawdown_pct = dec0(strategy["max_drawdown_pct"])
    return_per_max_active = dec0(comparisons["return_per_max_active_notional_pct"])
    return_per_gross = dec0(comparisons["return_per_gross_notional_pct"])
    benchmark_symbols = comparisons.get("benchmark_symbols", [])
    benchmark_count = int(comparisons.get("benchmark_count", 0))
    benchmark_beaten_count = int(comparisons.get("benchmark_beaten_count", 0))

    risk_state = classify_row(
        strategy_return_pct=strategy_return_pct,
        strategy_max_drawdown_pct=strategy_max_drawdown_pct,
        return_per_max_active_notional_pct=return_per_max_active,
        benchmark_count=benchmark_count,
        benchmark_beaten_count=benchmark_beaten_count,
        args=args,
    )

    return ScoreboardRow(
        batch_id=batch.batch_id,
        trades=int(summary["trades"]),
        symbols=int(summary["symbols"]),
        strategy_return_pct=strategy_return_pct,
        strategy_max_drawdown_pct=strategy_max_drawdown_pct,
        benchmark_symbols=",".join(str(item) for item in benchmark_symbols),
        benchmark_count=benchmark_count,
        benchmark_beaten_count=benchmark_beaten_count,
        best_benchmark_symbol=comparisons.get("best_benchmark_symbol"),
        best_benchmark_return_pct=dec(comparisons.get("best_benchmark_return_pct")),
        avg_benchmark_return_pct=dec(comparisons.get("avg_benchmark_return_pct")),
        excess_return_vs_best_benchmark_pct=dec(comparisons.get("excess_return_vs_best_benchmark_pct")),
        time_in_market_fraction=dec0(exposure["time_in_market_fraction"]),
        max_active_positions=int(exposure["max_active_positions"]),
        max_active_notional_eur=dec0(exposure["max_active_notional_eur"]),
        gross_notional_eur=dec0(exposure["gross_notional_eur"]),
        return_per_max_active_notional_pct=return_per_max_active,
        return_per_gross_notional_pct=return_per_gross,
        first_ts_utc=exposure.get("active_window_start_ts_utc") or batch.first_ts_utc,
        last_ts_utc=exposure.get("active_window_end_ts_utc") or batch.last_ts_utc,
        risk_state=risk_state,
    )


def build_payload_for_scoreboard(args: argparse.Namespace) -> dict[str, Any]:
    batches = fetch_batch_refs(args)
    rows = [build_scoreboard_row(args, batch) for batch in batches]

    return {
        "summary": {
            "scoreboard_version": "paper_candidate_risk_scoreboard_v1",
            "database": args.database,
            "stage_table": args.stage_table,
            "eval_table": args.eval_table,
            "policy_name": args.policy_name,
            "signal_status": args.signal_status,
            "batch_count": len(rows),
            "account_equity_eur": args.account_equity_eur,
            "target_fraction": args.target_fraction,
            "hold_hours": args.hold_hours,
            "benchmark_symbols": args.benchmark_symbols,
            "writes": "none",
            "live_execution_permission": "NOT_GRANTED",
        },
        "rows": [asdict(row) for row in rows],
    }


def print_table(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    rows = payload["rows"]

    print("Paper candidate risk scoreboard")
    for key in [
        "database",
        "stage_table",
        "eval_table",
        "policy_name",
        "signal_status",
        "batch_count",
        "account_equity_eur",
        "target_fraction",
        "hold_hours",
        "benchmark_symbols",
        "writes",
        "live_execution_permission",
    ]:
        print(f"{key}: {summary[key]}")

    print()
    print("--- risk scoreboard ---")
    print(
        "batch_id | trades | symbols | strat_ret | strat_dd | bench | beaten | "
        "best_bench | best_ret | avg_bench_ret | excess_best | tim | max_notional | "
        "ret/max_active | ret/gross | risk_state"
    )
    print("-" * 240)

    for row in rows:
        print(
            f"{row['batch_id']} | "
            f"{row['trades']} | "
            f"{row['symbols']} | "
            f"{fmt_dec(dec0(row['strategy_return_pct']))} | "
            f"{fmt_dec(dec0(row['strategy_max_drawdown_pct']))} | "
            f"{row['benchmark_symbols']} | "
            f"{row['benchmark_beaten_count']}/{row['benchmark_count']} | "
            f"{row['best_benchmark_symbol']} | "
            f"{fmt_dec(dec(row['best_benchmark_return_pct']))} | "
            f"{fmt_dec(dec(row['avg_benchmark_return_pct']))} | "
            f"{fmt_dec(dec(row['excess_return_vs_best_benchmark_pct']))} | "
            f"{fmt_dec(dec0(row['time_in_market_fraction']))} | "
            f"{fmt_dec(dec0(row['max_active_notional_eur']), '0.01')} | "
            f"{fmt_dec(dec0(row['return_per_max_active_notional_pct']))} | "
            f"{fmt_dec(dec0(row['return_per_gross_notional_pct']))} | "
            f"{row['risk_state']}"
        )

    print()
    print("--- interpretation ---")
    print("READ_ONLY_PREVIEW: no DB writes, no execution plans, no orders.")
    print("RESEARCH_SCOREBOARD_ONLY: uses research/backtest paper-candidate outputs.")
    print("LIVE_EXECUTION_PERMISSION: NOT_GRANTED")


def main() -> int:
    args = parse_args()
    payload = build_payload_for_scoreboard(args)

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
