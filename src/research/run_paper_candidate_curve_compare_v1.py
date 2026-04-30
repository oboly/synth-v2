from __future__ import annotations

# Synth v2 - Paper Candidate Curve Compare V1.
#
# LAYER:
# research / paper-candidate benchmark visualization
#
# BOUNDARY:
# Allowed:
# - read staged paper candidate rows
# - read research/backtest eval rows
# - compute simulated strategy equity curve
# - compute passive benchmark curves
# - write PNG/JSON files to requested output paths
#
# Forbidden:
# - database writes
# - decision_state writes
# - execution_plan writes
# - live orders
# - account balance mutation
#
# NOTE:
# This tool intentionally uses simulated future returns and forward prices.
# It must remain in the research/backtest namespace only.

import argparse
import bisect
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_STAGE_TABLE = "research_paper_candidate_signal"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v2"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5_24h_tactical"
DEFAULT_SIGNAL_STATUS = "PROMOTION_CANDIDATE"

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
SUPPORTED_HORIZONS = {4, 24, 48, 72, 168}


@dataclass(frozen=True)
class SimulatedTrade:
    candidate_id: int
    source_replay_id: int
    symbol: str
    asset_id: int
    entry_ts_utc: datetime
    exit_ts_utc: datetime
    priority_rank: int | None
    selection_score: Decimal | None
    entry_price_eur: Decimal
    exit_price_eur: Decimal
    simulated_net_return: Decimal
    notional_eur: Decimal
    simulated_pnl_eur: Decimal


@dataclass(frozen=True)
class EquityPoint:
    ts_utc: datetime
    equity_eur: Decimal


@dataclass(frozen=True)
class BenchmarkPoint:
    ts_utc: datetime
    price_eur: Decimal


@dataclass(frozen=True)
class BenchmarkCurve:
    symbol: str
    status: str
    start_ts_utc: datetime | None
    end_ts_utc: datetime | None
    start_price_eur: Decimal | None
    end_price_eur: Decimal | None
    start_equity_eur: Decimal | None
    end_equity_eur: Decimal | None
    return_pct: Decimal | None
    points: list[EquityPoint]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare staged paper-candidate simulated equity against passive benchmarks."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--stage-table", default=DEFAULT_STAGE_TABLE)
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument("--account-equity-eur", default="1000.00")
    parser.add_argument("--target-fraction", default="0.03300000")
    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--benchmark-symbols", default="BTC,ETH")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--json-output-file", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def validate_horizon(hold_hours: int) -> int:
    if hold_hours not in SUPPORTED_HORIZONS:
        raise ValueError(
            f"Unsupported hold horizon: {hold_hours}; supported={sorted(SUPPORTED_HORIZONS)}"
        )
    return hold_hours


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def decimal_or_raise(value: Any, field_name: str) -> Decimal:
    parsed = decimal_or_none(value)
    if parsed is None:
        raise ValueError(f"{field_name} is required")
    return parsed


def parse_benchmark_symbols(value: str) -> list[str]:
    symbols = []
    for raw in value.split(","):
        symbol = raw.strip().upper()
        if symbol:
            symbols.append(symbol)
    if not symbols:
        raise ValueError("At least one benchmark symbol is required.")
    return symbols


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if hasattr(value, "__dict__"):
        return asdict(value)
    return str(value)


def fetch_trades(args: argparse.Namespace) -> list[SimulatedTrade]:
    stage_table = validate_table_name(args.stage_table)
    eval_table = validate_table_name(args.eval_table)
    hold_hours = validate_horizon(args.hold_hours)

    return_col = f"net_return_{hold_hours}h"
    forward_price_col = f"forward_close_price_{hold_hours}h"
    notional_eur = Decimal(str(args.account_equity_eur)) * Decimal(str(args.target_fraction))

    limit_sql = ""
    params: list[Any] = [
        args.policy_name,
        args.batch_id,
        args.signal_status,
        args.eval_table,
    ]

    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive when provided.")
        limit_sql = "LIMIT %s"
        params.append(args.limit)

    sql = f"""
    SELECT
        s.candidate_id,
        s.source_replay_id,
        s.symbol,
        s.asset_id,
        s.asof_ts_utc AS entry_ts_utc,
        s.priority_rank,
        s.selection_score,
        s.simulated_net_return,
        e.entry_close_price,
        e.{forward_price_col} AS exit_price_eur,
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
      AND s.simulated_net_return IS NOT NULL
      AND e.entry_close_price IS NOT NULL
      AND e.{forward_price_col} IS NOT NULL
      AND e.{return_col} IS NOT NULL
    ORDER BY s.asof_ts_utc ASC, s.candidate_id ASC
    {limit_sql}
    """

    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    trades: list[SimulatedTrade] = []

    for row in rows:
        entry_ts = row["entry_ts_utc"]
        simulated_return = decimal_or_raise(row["simulated_net_return"], "simulated_net_return")
        entry_price = decimal_or_raise(row["entry_close_price"], "entry_close_price")
        exit_price = decimal_or_raise(row["exit_price_eur"], "exit_price_eur")
        simulated_pnl = notional_eur * simulated_return

        trades.append(
            SimulatedTrade(
                candidate_id=int(row["candidate_id"]),
                source_replay_id=int(row["source_replay_id"]),
                symbol=str(row["symbol"]),
                asset_id=int(row["asset_id"]),
                entry_ts_utc=entry_ts,
                exit_ts_utc=entry_ts + timedelta(hours=hold_hours),
                priority_rank=None if row["priority_rank"] is None else int(row["priority_rank"]),
                selection_score=decimal_or_none(row["selection_score"]),
                entry_price_eur=entry_price,
                exit_price_eur=exit_price,
                simulated_net_return=simulated_return,
                notional_eur=notional_eur,
                simulated_pnl_eur=simulated_pnl,
            )
        )

    return trades


def build_strategy_curve(
    *,
    trades: list[SimulatedTrade],
    start_equity: Decimal,
) -> list[EquityPoint]:
    if not trades:
        return []

    start_ts = min(row.entry_ts_utc for row in trades)
    equity = start_equity
    points = [EquityPoint(ts_utc=start_ts, equity_eur=equity)]

    for trade in sorted(trades, key=lambda row: (row.exit_ts_utc, row.candidate_id)):
        equity += trade.simulated_pnl_eur
        points.append(EquityPoint(ts_utc=trade.exit_ts_utc, equity_eur=equity))

    return points


def fetch_benchmark_points(
    *,
    database: str,
    eval_table: str,
    symbol: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[BenchmarkPoint]:
    safe_eval_table = validate_table_name(eval_table)

    sql = f"""
    SELECT
        replay_asof_ts_utc,
        AVG(entry_close_price) AS price_eur
    FROM {safe_eval_table}
    WHERE symbol = %s
      AND entry_close_price IS NOT NULL
      AND replay_asof_ts_utc >= %s
      AND replay_asof_ts_utc <= %s
    GROUP BY replay_asof_ts_utc
    ORDER BY replay_asof_ts_utc ASC
    """

    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [symbol, start_ts, end_ts])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        BenchmarkPoint(
            ts_utc=row["replay_asof_ts_utc"],
            price_eur=decimal_or_raise(row["price_eur"], "price_eur"),
        )
        for row in rows
    ]


def build_benchmark_curve(
    *,
    symbol: str,
    benchmark_points: list[BenchmarkPoint],
    timeline: list[datetime],
    start_equity: Decimal,
) -> BenchmarkCurve:
    if not benchmark_points or not timeline:
        return BenchmarkCurve(
            symbol=symbol,
            status="MISSING_PRICE_DATA",
            start_ts_utc=None,
            end_ts_utc=None,
            start_price_eur=None,
            end_price_eur=None,
            start_equity_eur=None,
            end_equity_eur=None,
            return_pct=None,
            points=[],
        )

    ts_values = [row.ts_utc for row in benchmark_points]
    prices = [row.price_eur for row in benchmark_points]

    start_price = prices[0]
    output_points: list[EquityPoint] = []

    for ts in timeline:
        idx = bisect.bisect_right(ts_values, ts) - 1
        if idx < 0:
            idx = 0
        price = prices[idx]
        equity = start_equity * (price / start_price)
        output_points.append(EquityPoint(ts_utc=ts, equity_eur=equity))

    end_price = prices[bisect.bisect_right(ts_values, timeline[-1]) - 1]
    end_equity = output_points[-1].equity_eur
    return_pct = ((end_equity / start_equity) - Decimal("1")) * Decimal("100")

    return BenchmarkCurve(
        symbol=symbol,
        status="OK",
        start_ts_utc=benchmark_points[0].ts_utc,
        end_ts_utc=ts_values[bisect.bisect_right(ts_values, timeline[-1]) - 1],
        start_price_eur=start_price,
        end_price_eur=end_price,
        start_equity_eur=start_equity,
        end_equity_eur=end_equity,
        return_pct=return_pct,
        points=output_points,
    )


def summarize(
    *,
    args: argparse.Namespace,
    trades: list[SimulatedTrade],
    strategy_curve: list[EquityPoint],
    benchmarks: list[BenchmarkCurve],
    output_file: str,
) -> dict[str, Any]:
    if not trades or not strategy_curve:
        return {
            "curve_compare_version": "paper_candidate_curve_compare_v1",
            "status": "NO_TRADES",
            "batch_id": args.batch_id,
            "trades": 0,
            "output_file": output_file,
            "writes": "png only, no DB writes, no execution writes, no orders",
        }

    start_equity = Decimal(str(args.account_equity_eur))
    end_equity = strategy_curve[-1].equity_eur
    strategy_return_pct = ((end_equity / start_equity) - Decimal("1")) * Decimal("100")

    return {
        "curve_compare_version": "paper_candidate_curve_compare_v1",
        "status": "OK",
        "database": args.database,
        "stage_table": args.stage_table,
        "eval_table": args.eval_table,
        "policy_name": args.policy_name,
        "batch_id": args.batch_id,
        "signal_status": args.signal_status,
        "hold_hours": args.hold_hours,
        "trades": len(trades),
        "symbols": len({row.symbol for row in trades}),
        "start_ts": min(row.entry_ts_utc for row in trades),
        "end_ts": max(row.exit_ts_utc for row in trades),
        "strategy_start_equity": start_equity,
        "strategy_end_equity": end_equity,
        "strategy_return_pct": strategy_return_pct,
        "benchmarks": [
            {
                "symbol": curve.symbol,
                "status": curve.status,
                "start_ts": curve.start_ts_utc,
                "end_ts": curve.end_ts_utc,
                "start_price_eur": curve.start_price_eur,
                "end_price_eur": curve.end_price_eur,
                "start_equity_eur": curve.start_equity_eur,
                "end_equity_eur": curve.end_equity_eur,
                "return_pct": curve.return_pct,
            }
            for curve in benchmarks
        ],
        "output_file": output_file,
        "writes": "png only, no DB writes, no execution writes, no orders",
    }


def plot_curves(
    *,
    args: argparse.Namespace,
    strategy_curve: list[EquityPoint],
    benchmarks: list[BenchmarkCurve],
    output_file: str,
) -> None:
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 6))

    strategy_times = [row.ts_utc for row in strategy_curve]
    strategy_equity = [float(row.equity_eur) for row in strategy_curve]
    ax.step(strategy_times, strategy_equity, where="post", label="strategy simulated equity")

    for curve in benchmarks:
        if curve.status != "OK" or not curve.points:
            continue
        times = [row.ts_utc for row in curve.points]
        equity = [float(row.equity_eur) for row in curve.points]
        ax.plot(times, equity, label=f"{curve.symbol} buy-and-hold")

    ax.set_title(f"Paper candidate curve compare - {args.batch_id}")
    ax.set_xlabel("UTC")
    ax.set_ylabel("Indexed equity EUR")
    ax.grid(True)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def print_table(summary: dict[str, Any]) -> None:
    print("--- curve compare ---")
    for key in [
        "batch_id",
        "trades",
        "symbols",
        "start_ts",
        "end_ts",
        "strategy_start_equity",
        "strategy_end_equity",
        "strategy_return_pct",
    ]:
        print(f"{key}: {summary.get(key)}")

    print()
    print("--- benchmarks ---")
    print("symbol | status | start_equity | end_equity | return_pct | start_price | end_price")
    print("-" * 110)

    for row in summary.get("benchmarks", []):
        print(
            f"{row['symbol']} | "
            f"{row['status']} | "
            f"{row['start_equity_eur']} | "
            f"{row['end_equity_eur']} | "
            f"{row['return_pct']} | "
            f"{row['start_price_eur']} | "
            f"{row['end_price_eur']}"
        )

    print()
    print(f"output_file: {summary.get('output_file')}")
    print(f"writes: {summary.get('writes')}")


def main() -> int:
    args = parse_args()
    validate_table_name(args.stage_table)
    validate_table_name(args.eval_table)
    validate_horizon(args.hold_hours)

    benchmark_symbols = parse_benchmark_symbols(args.benchmark_symbols)
    start_equity = Decimal(str(args.account_equity_eur))

    trades = fetch_trades(args)
    strategy_curve = build_strategy_curve(trades=trades, start_equity=start_equity)

    benchmarks: list[BenchmarkCurve] = []
    if trades and strategy_curve:
        start_ts = min(row.entry_ts_utc for row in trades)
        end_ts = max(row.exit_ts_utc for row in trades)
        timeline = [row.ts_utc for row in strategy_curve]

        for symbol in benchmark_symbols:
            benchmark_points = fetch_benchmark_points(
                database=args.database,
                eval_table=args.eval_table,
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            benchmarks.append(
                build_benchmark_curve(
                    symbol=symbol,
                    benchmark_points=benchmark_points,
                    timeline=timeline,
                    start_equity=start_equity,
                )
            )

        plot_curves(
            args=args,
            strategy_curve=strategy_curve,
            benchmarks=benchmarks,
            output_file=args.output_file,
        )

    summary = summarize(
        args=args,
        trades=trades,
        strategy_curve=strategy_curve,
        benchmarks=benchmarks,
        output_file=args.output_file,
    )

    payload = {
        "summary": summary,
        "strategy_curve": [asdict(row) for row in strategy_curve],
        "benchmarks": [
            {
                "summary": {
                    "symbol": curve.symbol,
                    "status": curve.status,
                    "start_ts_utc": curve.start_ts_utc,
                    "end_ts_utc": curve.end_ts_utc,
                    "start_price_eur": curve.start_price_eur,
                    "end_price_eur": curve.end_price_eur,
                    "start_equity_eur": curve.start_equity_eur,
                    "end_equity_eur": curve.end_equity_eur,
                    "return_pct": curve.return_pct,
                },
                "points": [asdict(row) for row in curve.points],
            }
            for curve in benchmarks
        ],
    }

    if args.json_output_file:
        json_path = Path(args.json_output_file)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, default=json_default, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
