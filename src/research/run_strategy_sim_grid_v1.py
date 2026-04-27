from __future__ import annotations

"""
Synth v2 - Strategy Simulation Grid V1.

LAYER:
research/backtest simulation

BOUNDARY:
Allowed:
- run deterministic strategy simulations over predefined market-only policies
- compare train/test windows
- rank strategy parameter combinations
- optionally persist individual simulation runs into synth_bt

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions

Purpose:
Automate walk-forward strategy simulation grids for research candidates.
This runner wraps the parking rotation strategy simulation core and reports
which parameter combinations survive out-of-sample testing.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.research.run_parking_rotation_strategy_sim_v1 import (
    DEFAULT_EVAL_TABLE,
    fetch_candidates,
    persist_simulation,
    simulate_trades,
    summarize_trades,
    _resolve_policy,
)


DEFAULT_POLICIES = [
    "parking_rotation_recovery_v1",
    "parking_rotation_recovery_v2",
]

DEFAULT_HOLD_HOURS = [24]
DEFAULT_COOLDOWN_HOURS = [12, 24, 48]
DEFAULT_MAX_TRADES_PER_SNAPSHOT = [1, 2]


@dataclass(frozen=True)
class GridConfig:
    policy_name: str
    hold_hours: int
    cooldown_hours_per_symbol: int
    max_trades_per_snapshot: int
    dedupe_symbol_overlap: bool


@dataclass(frozen=True)
class WindowConfig:
    label: str
    from_ts: str
    to_ts: str


@dataclass(frozen=True)
class GridResult:
    config: GridConfig
    train_summary: dict[str, Any]
    test_summary: dict[str, Any]
    train_candidate_rows: int
    test_candidate_rows: int
    train_sim_run_id: int | None
    test_sim_run_id: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run automated strategy simulation grid walk-forward evaluation."
    )
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)

    parser.add_argument(
        "--train-from-ts",
        default="2026-04-08 00:00:00",
    )
    parser.add_argument(
        "--train-to-ts",
        default="2026-04-24 00:00:00",
    )
    parser.add_argument(
        "--test-from-ts",
        default="2026-04-24 00:00:00",
    )
    parser.add_argument(
        "--test-to-ts",
        default="2026-04-28 00:00:00",
    )

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
    parser.add_argument("--min-test-trades", type=int, default=4)
    parser.add_argument("--sim-name", default="strategy_sim_grid_v1")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


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


def _safe_ratio(numerator: Any, denominator: Any) -> Decimal | None:
    if numerator is None or denominator is None:
        return None

    numerator_decimal = numerator if isinstance(numerator, Decimal) else Decimal(str(numerator))
    denominator_decimal = denominator if isinstance(denominator, Decimal) else Decimal(str(denominator))

    if denominator_decimal == 0:
        return None

    return numerator_decimal / denominator_decimal


def _status_for_result(
    *,
    train_summary: dict[str, Any],
    test_summary: dict[str, Any],
    min_test_trades: int,
) -> str:
    train_avg = train_summary["avg_net_return"]
    test_avg = test_summary["avg_net_return"]
    test_compound = test_summary["compound_net_return_trade_sequence"]
    test_winrate = test_summary["winrate"]
    test_trades = int(test_summary["trades"])

    if test_trades < min_test_trades:
        return "INSUFFICIENT_TEST_TRADES"

    if train_avg is None or train_avg <= 0:
        return "TRAIN_NOT_POSITIVE"

    if test_avg is None or test_avg <= 0:
        return "FAIL_TEST_NEGATIVE_AVG"

    if test_compound is None or test_compound <= 0:
        return "FAIL_TEST_NEGATIVE_COMPOUND"

    if test_winrate is not None and test_winrate >= Decimal("0.50"):
        return "PASS_SIM_WALK_FORWARD"

    return "POSITIVE_BUT_LOW_WINRATE"


def _score_for_sort(result: GridResult) -> tuple[Decimal, Decimal, Decimal, int]:
    test_summary = result.test_summary

    test_compound = test_summary["compound_net_return_trade_sequence"] or Decimal("-999")
    test_avg = test_summary["avg_net_return"] or Decimal("-999")
    test_winrate = test_summary["winrate"] or Decimal("-999")
    test_trades = int(test_summary["trades"])

    return (
        Decimal(str(test_compound)),
        Decimal(str(test_avg)),
        Decimal(str(test_winrate)),
        test_trades,
    )


def _build_grid_configs(args: argparse.Namespace) -> list[GridConfig]:
    dedupe_symbol_overlap = not bool(args.allow_symbol_overlap)

    configs: list[GridConfig] = []

    for policy_name in args.policies:
        _resolve_policy(str(policy_name))

        for hold_hours in args.hold_hours:
            if int(hold_hours) not in (4, 24):
                raise ValueError(f"Unsupported hold_hours: {hold_hours}")

            for cooldown_hours in args.cooldown_hours:
                for max_trades in args.max_trades_per_snapshot:
                    configs.append(
                        GridConfig(
                            policy_name=str(policy_name),
                            hold_hours=int(hold_hours),
                            cooldown_hours_per_symbol=int(cooldown_hours),
                            max_trades_per_snapshot=int(max_trades),
                            dedupe_symbol_overlap=dedupe_symbol_overlap,
                        )
                    )

    return configs


def _run_single_window(
    *,
    eval_table: str,
    config: GridConfig,
    window: WindowConfig,
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    policy = _resolve_policy(config.policy_name)

    candidates = fetch_candidates(
        eval_table=eval_table,
        policy=policy,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        hold_hours=config.hold_hours,
    )

    trades = simulate_trades(
        candidates,
        hold_hours=config.hold_hours,
        max_trades_per_snapshot=config.max_trades_per_snapshot,
        cooldown_hours_per_symbol=config.cooldown_hours_per_symbol,
        dedupe_symbol_overlap=config.dedupe_symbol_overlap,
    )

    summary = summarize_trades(trades)

    return candidates, trades, summary


def _persist_window_result(
    *,
    sim_name: str,
    eval_table: str,
    config: GridConfig,
    window: WindowConfig,
    candidate_rows: int,
    trades: list[Any],
    summary: dict[str, Any],
) -> int:
    windowed_sim_name = f"{sim_name}_{window.label}"

    return persist_simulation(
        sim_name=windowed_sim_name,
        policy_name=config.policy_name,
        eval_table=eval_table,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        hold_hours=config.hold_hours,
        max_trades_per_snapshot=config.max_trades_per_snapshot,
        cooldown_hours_per_symbol=config.cooldown_hours_per_symbol,
        dedupe_symbol_overlap=config.dedupe_symbol_overlap,
        candidate_rows=candidate_rows,
        trades=trades,
        summary=summary,
    )


def run_grid(args: argparse.Namespace) -> list[GridResult]:
    train_window = WindowConfig(
        label="train",
        from_ts=str(args.train_from_ts),
        to_ts=str(args.train_to_ts),
    )
    test_window = WindowConfig(
        label="test",
        from_ts=str(args.test_from_ts),
        to_ts=str(args.test_to_ts),
    )

    results: list[GridResult] = []

    for config in _build_grid_configs(args):
        train_candidates, train_trades, train_summary = _run_single_window(
            eval_table=str(args.eval_table),
            config=config,
            window=train_window,
        )

        test_candidates, test_trades, test_summary = _run_single_window(
            eval_table=str(args.eval_table),
            config=config,
            window=test_window,
        )

        train_sim_run_id: int | None = None
        test_sim_run_id: int | None = None

        if args.write_db:
            train_sim_run_id = _persist_window_result(
                sim_name=str(args.sim_name),
                eval_table=str(args.eval_table),
                config=config,
                window=train_window,
                candidate_rows=len(train_candidates),
                trades=train_trades,
                summary=train_summary,
            )

            test_sim_run_id = _persist_window_result(
                sim_name=str(args.sim_name),
                eval_table=str(args.eval_table),
                config=config,
                window=test_window,
                candidate_rows=len(test_candidates),
                trades=test_trades,
                summary=test_summary,
            )

        results.append(
            GridResult(
                config=config,
                train_summary=train_summary,
                test_summary=test_summary,
                train_candidate_rows=len(train_candidates),
                test_candidate_rows=len(test_candidates),
                train_sim_run_id=train_sim_run_id,
                test_sim_run_id=test_sim_run_id,
            )
        )

    return results


def _result_to_row(result: GridResult, *, min_test_trades: int) -> dict[str, Any]:
    train_summary = result.train_summary
    test_summary = result.test_summary

    train_avg = train_summary["avg_net_return"]
    test_avg = test_summary["avg_net_return"]
    train_compound = train_summary["compound_net_return_trade_sequence"]
    test_compound = test_summary["compound_net_return_trade_sequence"]

    avg_retention = _safe_ratio(test_avg, train_avg)
    compound_retention = _safe_ratio(test_compound, train_compound)

    return {
        "status": _status_for_result(
            train_summary=train_summary,
            test_summary=test_summary,
            min_test_trades=min_test_trades,
        ),
        "policy": result.config.policy_name,
        "hold": result.config.hold_hours,
        "cooldown": result.config.cooldown_hours_per_symbol,
        "max_per_snap": result.config.max_trades_per_snapshot,
        "dedupe": int(result.config.dedupe_symbol_overlap),
        "train_candidates": result.train_candidate_rows,
        "train_trades": train_summary["trades"],
        "train_avg": _fmt_decimal(train_avg),
        "train_wr": _fmt_decimal(train_summary["winrate"], 4),
        "train_comp": _fmt_decimal(train_compound),
        "test_candidates": result.test_candidate_rows,
        "test_trades": test_summary["trades"],
        "test_avg": _fmt_decimal(test_avg),
        "test_wr": _fmt_decimal(test_summary["winrate"], 4),
        "test_comp": _fmt_decimal(test_compound),
        "avg_retention": _fmt_decimal(avg_retention, 4),
        "compound_retention": _fmt_decimal(compound_retention, 4),
        "test_worst": _fmt_decimal(test_summary["worst_net_return"]),
        "test_best": _fmt_decimal(test_summary["best_net_return"]),
        "train_run": "" if result.train_sim_run_id is None else result.train_sim_run_id,
        "test_run": "" if result.test_sim_run_id is None else result.test_sim_run_id,
    }


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

    results = run_grid(args)
    ranked = sorted(results, key=_score_for_sort, reverse=True)

    rows = [
        _result_to_row(result, min_test_trades=int(args.min_test_trades))
        for result in ranked
    ]

    payload = {
        "eval_table": str(args.eval_table),
        "train_window": {
            "from_ts": str(args.train_from_ts),
            "to_ts": str(args.train_to_ts),
        },
        "test_window": {
            "from_ts": str(args.test_from_ts),
            "to_ts": str(args.test_to_ts),
        },
        "write_db": bool(args.write_db),
        "results_total": len(rows),
        "rows": rows,
    }

    if args.output == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    print("Strategy simulation grid")
    print(f"eval_table={args.eval_table}")
    print(f"train=[{args.train_from_ts},{args.train_to_ts})")
    print(f"test=[{args.test_from_ts},{args.test_to_ts})")
    print(f"configs={len(rows)}")
    print(f"write_db={args.write_db}")

    _print_table("TOP STRATEGY SIM CONFIGS", rows[: int(args.top)])

    pass_rows = [
        row for row in rows
        if row["status"] == "PASS_SIM_WALK_FORWARD"
    ]
    _print_table("PASSING CONFIGS", pass_rows[: int(args.top)])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
