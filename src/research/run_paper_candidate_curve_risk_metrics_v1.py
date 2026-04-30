from __future__ import annotations

# Synth v2 - Paper Candidate Curve Risk Metrics V1.
#
# LAYER:
# research / paper-candidate benchmark diagnostics
#
# BOUNDARY:
# Allowed:
# - read staged paper candidate rows through curve compare helper
# - read research/backtest eval rows through curve compare helper
# - compute strategy-vs-benchmark risk metrics
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
# This tool intentionally uses simulated future returns and forward prices.
# It must remain in the research/backtest namespace only.

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.research.run_paper_candidate_curve_compare_v1 import (
    BenchmarkCurve,
    EquityPoint,
    build_benchmark_curve,
    build_strategy_curve,
    fetch_benchmark_points,
    fetch_trades,
    json_default,
    parse_benchmark_symbols,
)


DEFAULT_DATABASE = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v2"
DEFAULT_BATCH_ID = "arena_v2_24h_tactical_2026"


@dataclass(frozen=True)
class RiskMetrics:
    name: str
    start_equity_eur: Decimal
    end_equity_eur: Decimal
    return_pct: Decimal
    max_drawdown_pct: Decimal
    max_drawdown_eur: Decimal
    points: int


@dataclass(frozen=True)
class ExposureMetrics:
    active_window_start_ts_utc: datetime | None
    active_window_end_ts_utc: datetime | None
    active_window_hours: Decimal
    time_in_market_hours: Decimal
    time_in_market_fraction: Decimal
    max_active_positions: int
    max_active_notional_eur: Decimal
    gross_notional_eur: Decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute paper-candidate curve risk metrics versus passive benchmarks."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--stage-table", default="research_paper_candidate_signal")
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--policy-name", default="swing_pullback_recovery_v5_24h_tactical")
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--signal-status", default="PROMOTION_CANDIDATE")
    parser.add_argument("--account-equity-eur", default="1000.00")
    parser.add_argument("--target-fraction", default="0.03300000")
    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--benchmark-symbols", default="BTC,ETH")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def pct(value: Decimal) -> Decimal:
    return value * Decimal("100")


def quant(value: Decimal, places: str = "0.0001") -> Decimal:
    return value.quantize(Decimal(places))


def fmt_optional_decimal(value: Decimal | None, places: str = "0.0000") -> str:
    if value is None:
        return "None"
    return str(value.quantize(Decimal(places)))


def build_curve_metrics(name: str, points: list[EquityPoint]) -> RiskMetrics:
    if not points:
        return RiskMetrics(
            name=name,
            start_equity_eur=Decimal("0"),
            end_equity_eur=Decimal("0"),
            return_pct=Decimal("0"),
            max_drawdown_pct=Decimal("0"),
            max_drawdown_eur=Decimal("0"),
            points=0,
        )

    start_equity = points[0].equity_eur
    end_equity = points[-1].equity_eur
    total_return_pct = pct((end_equity / start_equity) - Decimal("1"))

    peak = points[0].equity_eur
    worst_drawdown_pct = Decimal("0")
    worst_drawdown_eur = Decimal("0")

    for point in points:
        if point.equity_eur > peak:
            peak = point.equity_eur

        drawdown_eur = point.equity_eur - peak
        drawdown_pct = pct((point.equity_eur / peak) - Decimal("1"))

        if drawdown_pct < worst_drawdown_pct:
            worst_drawdown_pct = drawdown_pct
            worst_drawdown_eur = drawdown_eur

    return RiskMetrics(
        name=name,
        start_equity_eur=start_equity,
        end_equity_eur=end_equity,
        return_pct=total_return_pct,
        max_drawdown_pct=worst_drawdown_pct,
        max_drawdown_eur=worst_drawdown_eur,
        points=len(points),
    )


def merged_active_hours(intervals: list[tuple[datetime, datetime]]) -> Decimal:
    if not intervals:
        return Decimal("0")

    ordered = sorted(intervals, key=lambda row: row[0])
    merged: list[tuple[datetime, datetime]] = []

    cur_start, cur_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= cur_end:
            if end > cur_end:
                cur_end = end
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end

    merged.append((cur_start, cur_end))

    seconds = sum(
        Decimal(str((end - start).total_seconds()))
        for start, end in merged
    )
    return seconds / Decimal("3600")


def build_exposure_metrics(trades: list[Any]) -> ExposureMetrics:
    if not trades:
        return ExposureMetrics(
            active_window_start_ts_utc=None,
            active_window_end_ts_utc=None,
            active_window_hours=Decimal("0"),
            time_in_market_hours=Decimal("0"),
            time_in_market_fraction=Decimal("0"),
            max_active_positions=0,
            max_active_notional_eur=Decimal("0"),
            gross_notional_eur=Decimal("0"),
        )

    intervals = [(trade.entry_ts_utc, trade.exit_ts_utc) for trade in trades]
    start_ts = min(start for start, _ in intervals)
    end_ts = max(end for _, end in intervals)

    active_window_hours = Decimal(str((end_ts - start_ts).total_seconds())) / Decimal("3600")
    time_in_market_hours = merged_active_hours(intervals)
    time_in_market_fraction = (
        time_in_market_hours / active_window_hours
        if active_window_hours > 0
        else Decimal("0")
    )

    events: list[tuple[datetime, int, Decimal]] = []
    for trade in trades:
        events.append((trade.entry_ts_utc, 1, trade.notional_eur))
        events.append((trade.exit_ts_utc, -1, -trade.notional_eur))

    events.sort(key=lambda row: (row[0], row[1]))

    active_positions = 0
    active_notional = Decimal("0")
    max_active_positions = 0
    max_active_notional = Decimal("0")

    for _, delta_pos, delta_notional in events:
        active_positions += delta_pos
        active_notional += delta_notional

        if active_positions > max_active_positions:
            max_active_positions = active_positions
        if active_notional > max_active_notional:
            max_active_notional = active_notional

    gross_notional = sum((trade.notional_eur for trade in trades), Decimal("0"))

    return ExposureMetrics(
        active_window_start_ts_utc=start_ts,
        active_window_end_ts_utc=end_ts,
        active_window_hours=active_window_hours,
        time_in_market_hours=time_in_market_hours,
        time_in_market_fraction=time_in_market_fraction,
        max_active_positions=max_active_positions,
        max_active_notional_eur=max_active_notional,
        gross_notional_eur=gross_notional,
    )


def return_per_notional(return_pct_value: Decimal, notional: Decimal, account_equity: Decimal) -> Decimal:
    if notional <= 0:
        return Decimal("0")
    return return_pct_value / (notional / account_equity)


def build_generic_comparisons(
    *,
    strategy_metrics: RiskMetrics,
    benchmark_metrics: list[RiskMetrics],
    exposure: ExposureMetrics,
    account_equity: Decimal,
) -> dict[str, Any]:
    benchmark_symbols = [row.name for row in benchmark_metrics]
    benchmark_returns = [row.return_pct for row in benchmark_metrics]

    best_benchmark = max(benchmark_metrics, key=lambda row: row.return_pct) if benchmark_metrics else None
    worst_benchmark = min(benchmark_metrics, key=lambda row: row.return_pct) if benchmark_metrics else None

    avg_benchmark_return = (
        sum(benchmark_returns, Decimal("0")) / Decimal(len(benchmark_returns))
        if benchmark_returns
        else None
    )

    excess_by_symbol = {
        row.name: strategy_metrics.return_pct - row.return_pct
        for row in benchmark_metrics
    }

    beaten_symbols = [
        row.name
        for row in benchmark_metrics
        if strategy_metrics.return_pct > row.return_pct
    ]

    rank_values = sorted(
        [("strategy", strategy_metrics.return_pct)]
        + [(row.name, row.return_pct) for row in benchmark_metrics],
        key=lambda row: row[1],
        reverse=True,
    )
    strategy_rank = next(
        index + 1
        for index, row in enumerate(rank_values)
        if row[0] == "strategy"
    )

    out: dict[str, Any] = {
        "benchmark_count": len(benchmark_metrics),
        "benchmark_symbols": benchmark_symbols,
        "benchmark_beaten_count": len(beaten_symbols),
        "benchmark_beaten_symbols": beaten_symbols,
        "strategy_rank_by_return": strategy_rank,
        "best_benchmark_symbol": None if best_benchmark is None else best_benchmark.name,
        "best_benchmark_return_pct": None if best_benchmark is None else best_benchmark.return_pct,
        "worst_benchmark_symbol": None if worst_benchmark is None else worst_benchmark.name,
        "worst_benchmark_return_pct": None if worst_benchmark is None else worst_benchmark.return_pct,
        "avg_benchmark_return_pct": avg_benchmark_return,
        "benchmark_excess_return_pct_by_symbol": excess_by_symbol,
        "excess_return_vs_best_benchmark_pct": (
            None
            if best_benchmark is None
            else strategy_metrics.return_pct - best_benchmark.return_pct
        ),
        "return_per_gross_notional_pct": return_per_notional(
            strategy_metrics.return_pct,
            exposure.gross_notional_eur,
            account_equity,
        ),
        "return_per_max_active_notional_pct": return_per_notional(
            strategy_metrics.return_pct,
            exposure.max_active_notional_eur,
            account_equity,
        ),
    }

    if "BTC" in excess_by_symbol:
        out["excess_return_vs_BTC_pct"] = excess_by_symbol["BTC"]
    if "ETH" in excess_by_symbol:
        out["excess_return_vs_ETH_pct"] = excess_by_symbol["ETH"]

    return out


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    trades = fetch_trades(args)
    account_equity = dec(args.account_equity_eur)

    strategy_curve = build_strategy_curve(
        trades=trades,
        start_equity=account_equity,
    )

    strategy_metrics = build_curve_metrics("strategy", strategy_curve)
    exposure = build_exposure_metrics(trades)

    benchmarks: list[BenchmarkCurve] = []
    benchmark_metrics: list[RiskMetrics] = []

    if trades and strategy_curve:
        start_ts = min(row.entry_ts_utc for row in trades)
        end_ts = max(row.exit_ts_utc for row in trades)
        timeline = [point.ts_utc for point in strategy_curve]

        for symbol in parse_benchmark_symbols(args.benchmark_symbols):
            benchmark_points = fetch_benchmark_points(
                database=args.database,
                eval_table=args.eval_table,
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            curve = build_benchmark_curve(
                symbol=symbol,
                benchmark_points=benchmark_points,
                timeline=timeline,
                start_equity=account_equity,
            )
            benchmarks.append(curve)
            benchmark_metrics.append(build_curve_metrics(symbol, curve.points))

    return {
        "summary": {
            "risk_metrics_version": "paper_candidate_curve_risk_metrics_v1",
            "database": args.database,
            "policy_name": args.policy_name,
            "batch_id": args.batch_id,
            "signal_status": args.signal_status,
            "hold_hours": args.hold_hours,
            "trades": len(trades),
            "symbols": len({trade.symbol for trade in trades}),
            "account_equity_eur": str(account_equity),
            "target_fraction": str(args.target_fraction),
            "benchmark_symbols": parse_benchmark_symbols(args.benchmark_symbols),
            "writes": "none",
            "live_execution_permission": "NOT_GRANTED",
        },
        "strategy": asdict(strategy_metrics),
        "benchmarks": [asdict(row) for row in benchmark_metrics],
        "exposure": asdict(exposure),
        "comparisons": build_generic_comparisons(
            strategy_metrics=strategy_metrics,
            benchmark_metrics=benchmark_metrics,
            exposure=exposure,
            account_equity=account_equity,
        ),
    }


def print_table(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    strategy = payload["strategy"]
    exposure = payload["exposure"]
    comparisons = payload["comparisons"]

    print("Paper candidate curve risk metrics")
    for key in [
        "database",
        "policy_name",
        "batch_id",
        "signal_status",
        "hold_hours",
        "trades",
        "symbols",
        "account_equity_eur",
        "target_fraction",
        "benchmark_symbols",
        "writes",
        "live_execution_permission",
    ]:
        print(f"{key}: {summary[key]}")

    print()
    print("--- return / drawdown ---")
    print("name | return_pct | max_drawdown_pct | max_drawdown_eur | start_equity | end_equity")
    print("-" * 120)

    rows = [strategy] + payload["benchmarks"]
    for row in rows:
        print(
            f"{row['name']} | "
            f"{quant(dec(row['return_pct']))} | "
            f"{quant(dec(row['max_drawdown_pct']))} | "
            f"{quant(dec(row['max_drawdown_eur']))} | "
            f"{quant(dec(row['start_equity_eur']), '0.01')} | "
            f"{quant(dec(row['end_equity_eur']), '0.01')}"
        )

    print()
    print("--- exposure efficiency ---")
    for key in [
        "active_window_hours",
        "time_in_market_hours",
        "time_in_market_fraction",
        "max_active_positions",
        "max_active_notional_eur",
        "gross_notional_eur",
    ]:
        print(f"{key}: {exposure[key]}")

    print()
    print("--- benchmark comparison ---")
    print(f"benchmark_count: {comparisons['benchmark_count']}")
    print(f"benchmark_symbols: {comparisons['benchmark_symbols']}")
    print(f"benchmark_beaten_count: {comparisons['benchmark_beaten_count']}")
    print(f"benchmark_beaten_symbols: {comparisons['benchmark_beaten_symbols']}")
    print(f"strategy_rank_by_return: {comparisons['strategy_rank_by_return']}")
    print(f"best_benchmark_symbol: {comparisons['best_benchmark_symbol']}")
    print(f"best_benchmark_return_pct: {fmt_optional_decimal(comparisons['best_benchmark_return_pct'])}")
    print(f"avg_benchmark_return_pct: {fmt_optional_decimal(comparisons['avg_benchmark_return_pct'])}")
    print(f"excess_return_vs_best_benchmark_pct: {fmt_optional_decimal(comparisons['excess_return_vs_best_benchmark_pct'])}")
    print(f"benchmark_excess_return_pct_by_symbol: {comparisons['benchmark_excess_return_pct_by_symbol']}")

    print()
    print("--- comparisons ---")
    print(f"return_per_gross_notional_pct: {comparisons['return_per_gross_notional_pct']}")
    print(f"return_per_max_active_notional_pct: {comparisons['return_per_max_active_notional_pct']}")

    print()
    print("--- interpretation ---")
    print("READ_ONLY_PREVIEW: no DB writes, no execution plans, no orders.")
    print("RESEARCH_RISK_ONLY: uses simulated future exit prices and returns.")
    print("LIVE_EXECUTION_PERMISSION: NOT_GRANTED")


def main() -> int:
    args = parse_args()
    payload = build_payload(args)

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
