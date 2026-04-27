from __future__ import annotations

"""
Synth v2 - Strategy Simulation Rolling Walk-Forward V1.

LAYER:
research/backtest simulation

BOUNDARY:
Allowed:
- read synth_bt replay eval rows
- run deterministic strategy simulations over rolling train/test windows
- compare market-only research policies and simulation parameters
- report aggregate out-of-sample robustness

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions

Purpose:
Replace single split validation with rolling walk-forward validation.
This prevents over-trusting one lucky train/test window.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.research.run_parking_rotation_strategy_sim_v1 import (
    DEFAULT_EVAL_TABLE,
    fetch_candidates,
    simulate_trades,
    summarize_trades,
    _resolve_policy,
)


DEFAULT_POLICIES = [
    "parking_rotation_recovery_v1",
    "parking_rotation_recovery_v2",
]

DEFAULT_HOLD_HOURS = [24]
DEFAULT_COOLDOWN_HOURS = [24]
DEFAULT_MAX_TRADES_PER_SNAPSHOT = [1, 2]


@dataclass(frozen=True)
class WindowPair:
    split_id: int
    train_from_ts: str
    train_to_ts: str
    test_from_ts: str
    test_to_ts: str


@dataclass(frozen=True)
class SimConfig:
    policy_name: str
    hold_hours: int
    cooldown_hours_per_symbol: int
    max_trades_per_snapshot: int
    dedupe_symbol_overlap: bool


@dataclass(frozen=True)
class SplitResult:
    split_id: int
    config: SimConfig
    train_candidate_rows: int
    train_summary: dict[str, Any]
    test_candidate_rows: int
    test_summary: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run rolling walk-forward strategy simulation validation."
    )
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)

    parser.add_argument("--from-ts", default="2026-04-08 00:00:00")
    parser.add_argument("--to-ts", default="2026-04-28 00:00:00")
    parser.add_argument("--train-days", type=int, default=10)
    parser.add_argument("--test-days", type=int, default=3)
    parser.add_argument("--step-days", type=int, default=1)

    parser.add_argument("--policies", nargs="+", default=DEFAULT_POLICIES)
    parser.add_argument("--hold-hours", nargs="+", type=int, default=DEFAULT_HOLD_HOURS)
    parser.add_argument(
        "--cooldown-hours",
        nargs="+",
        type=int,
        default=DEFAULT_COOLDOWN_HOURS,
    )
    parser.add_argument(
        "--max-trades-per-snapshot",
        nargs="+",
        type=int,
        default=DEFAULT_MAX_TRADES_PER_SNAPSHOT,
    )
    parser.add_argument(
        "--allow-symbol-overlap",
        action="store_true",
        help="Disable symbol overlap dedupe. Default is dedupe enabled.",
    )

    parser.add_argument("--min-test-trades-per-split", type=int, default=2)
    parser.add_argument("--min-valid-test-splits", type=int, default=2)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--show-splits", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _format_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _fmt_decimal(value: Any, places: int = 6) -> str:
    if value is None:
        return ""

    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    quant = Decimal("1").scaleb(-places)
    return str(decimal_value.quantize(quant))


def _safe_decimal(value: Any, fallback: str = "0") -> Decimal:
    if value is None:
        return Decimal(fallback)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _safe_ratio(numerator: Any, denominator: Any) -> Decimal | None:
    if numerator is None or denominator is None:
        return None

    numerator_decimal = _safe_decimal(numerator)
    denominator_decimal = _safe_decimal(denominator)

    if denominator_decimal == 0:
        return None

    return numerator_decimal / denominator_decimal


def build_windows(
    *,
    from_ts: str,
    to_ts: str,
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[WindowPair]:
    start = _parse_ts(from_ts)
    end = _parse_ts(to_ts)

    if train_days <= 0:
        raise ValueError("train_days must be positive")
    if test_days <= 0:
        raise ValueError("test_days must be positive")
    if step_days <= 0:
        raise ValueError("step_days must be positive")

    windows: list[WindowPair] = []
    cursor = start
    split_id = 1

    while True:
        train_from = cursor
        train_to = train_from + timedelta(days=train_days)
        test_from = train_to
        test_to = test_from + timedelta(days=test_days)

        if test_to > end:
            break

        windows.append(
            WindowPair(
                split_id=split_id,
                train_from_ts=_format_ts(train_from),
                train_to_ts=_format_ts(train_to),
                test_from_ts=_format_ts(test_from),
                test_to_ts=_format_ts(test_to),
            )
        )

        split_id += 1
        cursor += timedelta(days=step_days)

    return windows


def build_configs(args: argparse.Namespace) -> list[SimConfig]:
    dedupe_symbol_overlap = not bool(args.allow_symbol_overlap)

    configs: list[SimConfig] = []

    for policy_name in args.policies:
        _resolve_policy(str(policy_name))

        for hold_hours in args.hold_hours:
            if int(hold_hours) not in (4, 24):
                raise ValueError(f"Unsupported hold_hours: {hold_hours}")

            for cooldown_hours in args.cooldown_hours:
                for max_trades in args.max_trades_per_snapshot:
                    configs.append(
                        SimConfig(
                            policy_name=str(policy_name),
                            hold_hours=int(hold_hours),
                            cooldown_hours_per_symbol=int(cooldown_hours),
                            max_trades_per_snapshot=int(max_trades),
                            dedupe_symbol_overlap=dedupe_symbol_overlap,
                        )
                    )

    return configs


def run_single_window(
    *,
    eval_table: str,
    config: SimConfig,
    from_ts: str,
    to_ts: str,
) -> tuple[int, dict[str, Any]]:
    policy = _resolve_policy(config.policy_name)

    candidates = fetch_candidates(
        eval_table=eval_table,
        policy=policy,
        from_ts=from_ts,
        to_ts=to_ts,
        hold_hours=config.hold_hours,
    )

    trades = simulate_trades(
        candidates,
        hold_hours=config.hold_hours,
        max_trades_per_snapshot=config.max_trades_per_snapshot,
        cooldown_hours_per_symbol=config.cooldown_hours_per_symbol,
        dedupe_symbol_overlap=config.dedupe_symbol_overlap,
    )

    return len(candidates), summarize_trades(trades)


def run_walk_forward(
    *,
    eval_table: str,
    windows: list[WindowPair],
    configs: list[SimConfig],
) -> list[SplitResult]:
    results: list[SplitResult] = []

    for window in windows:
        for config in configs:
            train_candidate_rows, train_summary = run_single_window(
                eval_table=eval_table,
                config=config,
                from_ts=window.train_from_ts,
                to_ts=window.train_to_ts,
            )
            test_candidate_rows, test_summary = run_single_window(
                eval_table=eval_table,
                config=config,
                from_ts=window.test_from_ts,
                to_ts=window.test_to_ts,
            )

            results.append(
                SplitResult(
                    split_id=window.split_id,
                    config=config,
                    train_candidate_rows=train_candidate_rows,
                    train_summary=train_summary,
                    test_candidate_rows=test_candidate_rows,
                    test_summary=test_summary,
                )
            )

    return results


def _config_key(config: SimConfig) -> tuple[Any, ...]:
    return (
        config.policy_name,
        config.hold_hours,
        config.cooldown_hours_per_symbol,
        config.max_trades_per_snapshot,
        int(config.dedupe_symbol_overlap),
    )


def _status_for_aggregate(
    *,
    valid_test_splits: int,
    total_splits: int,
    positive_test_splits: int,
    avg_test_return: Decimal | None,
    compound_test_product: Decimal | None,
    min_valid_test_splits: int,
) -> str:
    if valid_test_splits < min_valid_test_splits:
        return "INSUFFICIENT_VALID_TEST_SPLITS"

    if valid_test_splits < total_splits:
        return "PARTIAL_TEST_COVERAGE"

    if avg_test_return is None or avg_test_return <= 0:
        return "FAIL_NEGATIVE_AVG_TEST"

    if compound_test_product is None or compound_test_product <= 0:
        return "FAIL_NEGATIVE_COMPOUND_TEST"

    if positive_test_splits == valid_test_splits:
        return "PROMOTE_ROLLING_CANDIDATE"

    if positive_test_splits >= max(1, valid_test_splits - 1):
        return "PASS_WITH_ONE_WEAK_SPLIT"

    return "UNSTABLE_TEST_SPLITS"


def aggregate_results(
    *,
    split_results: list[SplitResult],
    total_splits: int,
    min_test_trades_per_split: int,
    min_valid_test_splits: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[SplitResult]] = {}

    for result in split_results:
        grouped.setdefault(_config_key(result.config), []).append(result)

    rows: list[dict[str, Any]] = []

    for key, results in grouped.items():
        sample = results[0].config

        train_returns: list[Decimal] = []
        test_returns: list[Decimal] = []
        train_compounds: list[Decimal] = []
        test_compounds: list[Decimal] = []

        total_train_trades = 0
        total_test_trades = 0
        valid_test_splits = 0
        positive_test_splits = 0
        negative_test_splits = 0
        zero_trade_test_splits = 0

        worst_test_return: Decimal | None = None
        best_test_return: Decimal | None = None

        for result in results:
            train_summary = result.train_summary
            test_summary = result.test_summary

            train_trades = int(train_summary["trades"])
            test_trades = int(test_summary["trades"])

            total_train_trades += train_trades
            total_test_trades += test_trades

            train_avg = train_summary["avg_net_return"]
            test_avg = test_summary["avg_net_return"]
            train_compound = train_summary["compound_net_return_trade_sequence"]
            test_compound = test_summary["compound_net_return_trade_sequence"]

            if train_avg is not None:
                train_returns.append(_safe_decimal(train_avg))
            if train_compound is not None:
                train_compounds.append(_safe_decimal(train_compound))

            if test_trades == 0:
                zero_trade_test_splits += 1

            if test_trades >= min_test_trades_per_split and test_avg is not None:
                valid_test_splits += 1
                test_return = _safe_decimal(test_avg)
                test_returns.append(test_return)

                if test_return > 0:
                    positive_test_splits += 1
                elif test_return < 0:
                    negative_test_splits += 1

                if worst_test_return is None or test_return < worst_test_return:
                    worst_test_return = test_return
                if best_test_return is None or test_return > best_test_return:
                    best_test_return = test_return

                if test_compound is not None:
                    test_compounds.append(_safe_decimal(test_compound))

        avg_train_return = None
        if train_returns:
            avg_train_return = sum(train_returns, Decimal("0")) / Decimal(str(len(train_returns)))

        avg_test_return = None
        if test_returns:
            avg_test_return = sum(test_returns, Decimal("0")) / Decimal(str(len(test_returns)))

        avg_train_compound = None
        if train_compounds:
            avg_train_compound = sum(train_compounds, Decimal("0")) / Decimal(str(len(train_compounds)))

        avg_test_compound = None
        if test_compounds:
            avg_test_compound = sum(test_compounds, Decimal("0")) / Decimal(str(len(test_compounds)))

        compound_test_product = None
        if test_compounds:
            compound = Decimal("1")
            for value in test_compounds:
                compound *= Decimal("1") + value
            compound_test_product = compound - Decimal("1")

        avg_retention = _safe_ratio(avg_test_return, avg_train_return)
        compound_retention = _safe_ratio(avg_test_compound, avg_train_compound)

        status = _status_for_aggregate(
            valid_test_splits=valid_test_splits,
            total_splits=total_splits,
            positive_test_splits=positive_test_splits,
            avg_test_return=avg_test_return,
            compound_test_product=compound_test_product,
            min_valid_test_splits=min_valid_test_splits,
        )

        rows.append(
            {
                "status": status,
                "policy": sample.policy_name,
                "hold": sample.hold_hours,
                "cooldown": sample.cooldown_hours_per_symbol,
                "max_per_snap": sample.max_trades_per_snapshot,
                "dedupe": int(sample.dedupe_symbol_overlap),
                "splits": total_splits,
                "valid_test_splits": valid_test_splits,
                "positive_test_splits": positive_test_splits,
                "negative_test_splits": negative_test_splits,
                "zero_trade_test_splits": zero_trade_test_splits,
                "train_trades": total_train_trades,
                "test_trades": total_test_trades,
                "avg_train": _fmt_decimal(avg_train_return),
                "avg_test": _fmt_decimal(avg_test_return),
                "avg_retention": _fmt_decimal(avg_retention, 4),
                "avg_train_comp": _fmt_decimal(avg_train_compound),
                "avg_test_comp": _fmt_decimal(avg_test_compound),
                "compound_retention": _fmt_decimal(compound_retention, 4),
                "test_comp_product": _fmt_decimal(compound_test_product),
                "worst_test_avg": _fmt_decimal(worst_test_return),
                "best_test_avg": _fmt_decimal(best_test_return),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            Decimal(str(row["test_comp_product"] or "-999")),
            Decimal(str(row["avg_test"] or "-999")),
            Decimal(str(row["positive_test_splits"])),
            Decimal(str(row["test_trades"])),
        ),
        reverse=True,
    )


def split_detail_rows(
    *,
    windows: list[WindowPair],
    split_results: list[SplitResult],
) -> list[dict[str, Any]]:
    window_by_id = {window.split_id: window for window in windows}
    rows: list[dict[str, Any]] = []

    for result in split_results:
        window = window_by_id[result.split_id]
        rows.append(
            {
                "split": result.split_id,
                "train": f"{window.train_from_ts}->{window.train_to_ts}",
                "test": f"{window.test_from_ts}->{window.test_to_ts}",
                "policy": result.config.policy_name,
                "hold": result.config.hold_hours,
                "max_per_snap": result.config.max_trades_per_snapshot,
                "cooldown": result.config.cooldown_hours_per_symbol,
                "train_trades": result.train_summary["trades"],
                "train_avg": _fmt_decimal(result.train_summary["avg_net_return"]),
                "test_trades": result.test_summary["trades"],
                "test_avg": _fmt_decimal(result.test_summary["avg_net_return"]),
                "test_comp": _fmt_decimal(
                    result.test_summary["compound_net_return_trade_sequence"]
                ),
                "test_wr": _fmt_decimal(result.test_summary["winrate"], 4),
            }
        )

    return rows


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(f"=== {title} ===")

    if not rows:
        print("(no rows)")
        return

    headers = list(rows[0].keys())
    printable = [[str(row.get(header, "")) for header in headers] for row in rows]

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))

    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    windows = build_windows(
        from_ts=str(args.from_ts),
        to_ts=str(args.to_ts),
        train_days=int(args.train_days),
        test_days=int(args.test_days),
        step_days=int(args.step_days),
    )

    if not windows:
        raise ValueError("No walk-forward windows generated. Widen date range or reduce train/test days.")

    configs = build_configs(args)

    split_results = run_walk_forward(
        eval_table=str(args.eval_table),
        windows=windows,
        configs=configs,
    )

    aggregate_rows = aggregate_results(
        split_results=split_results,
        total_splits=len(windows),
        min_test_trades_per_split=int(args.min_test_trades_per_split),
        min_valid_test_splits=int(args.min_valid_test_splits),
    )

    detail_rows = split_detail_rows(
        windows=windows,
        split_results=split_results,
    )

    payload = {
        "eval_table": str(args.eval_table),
        "from_ts": str(args.from_ts),
        "to_ts": str(args.to_ts),
        "train_days": int(args.train_days),
        "test_days": int(args.test_days),
        "step_days": int(args.step_days),
        "windows": [window.__dict__ for window in windows],
        "configs": len(configs),
        "aggregate": aggregate_rows,
        "splits": detail_rows,
    }

    if args.output == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    print("Strategy simulation rolling walk-forward")
    print(f"eval_table={args.eval_table}")
    print(f"window=[{args.from_ts},{args.to_ts})")
    print(f"train_days={args.train_days}")
    print(f"test_days={args.test_days}")
    print(f"step_days={args.step_days}")
    print(f"splits={len(windows)}")
    print(f"configs={len(configs)}")

    _print_table("ROLLING WALK-FORWARD SCOREBOARD", aggregate_rows[: int(args.top)])

    passing = [
        row
        for row in aggregate_rows
        if row["status"] in (
            "PROMOTE_ROLLING_CANDIDATE",
            "PASS_WITH_ONE_WEAK_SPLIT",
        )
    ]
    _print_table("ROLLING CANDIDATES", passing[: int(args.top)])

    if args.show_splits:
        _print_table("SPLIT DETAILS", detail_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
