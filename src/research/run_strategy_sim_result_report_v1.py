from __future__ import annotations

"""
Synth v2 - Strategy Simulation Result Report V1.

LAYER:
research/backtest reporting

BOUNDARY:
Allowed:
- read persisted strategy simulation runs from synth_bt
- compare train/test strategy simulation pairs
- report walk-forward retention and candidate status

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions

Purpose:
Turn persisted strategy simulation runs into a compact promotion scoreboard.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BT_DB = "synth_bt"
SIM_RUN_TABLE = "bt_strategy_sim_run_v1"


@dataclass(frozen=True)
class SimRunRow:
    strategy_sim_run_id: int
    sim_name: str
    policy_name: str
    from_ts_utc: datetime
    to_ts_utc: datetime
    hold_hours: int
    max_trades_per_snapshot: int
    cooldown_hours_per_symbol: int
    dedupe_symbol_overlap: int
    candidate_rows: int
    trades_total: int
    symbol_count: int
    day_count: int
    avg_net_return: Decimal | None
    winrate: Decimal | None
    worst_net_return: Decimal | None
    best_net_return: Decimal | None
    compound_net_return_trade_sequence: Decimal | None
    created_ts_utc: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report persisted strategy simulation walk-forward results."
    )
    parser.add_argument("--sim-name-prefix", default="strategy_sim_grid_v1")
    parser.add_argument("--min-test-trades", type=int, default=4)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _fmt_decimal(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return ""
    quant = Decimal("1").scaleb(-places)
    return str(value.quantize(quant))


def _safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def fetch_runs(*, sim_name_prefix: str) -> list[SimRunRow]:
    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    strategy_sim_run_id,
                    sim_name,
                    policy_name,
                    from_ts_utc,
                    to_ts_utc,
                    hold_hours,
                    max_trades_per_snapshot,
                    cooldown_hours_per_symbol,
                    dedupe_symbol_overlap,
                    candidate_rows,
                    trades_total,
                    symbol_count,
                    day_count,
                    avg_net_return,
                    winrate,
                    worst_net_return,
                    best_net_return,
                    compound_net_return_trade_sequence,
                    created_ts_utc
                FROM {SIM_RUN_TABLE}
                WHERE sim_name IN (%s, %s)
                ORDER BY
                    policy_name ASC,
                    hold_hours ASC,
                    max_trades_per_snapshot ASC,
                    cooldown_hours_per_symbol ASC,
                    dedupe_symbol_overlap ASC,
                    sim_name ASC,
                    strategy_sim_run_id ASC
                """,
                [
                    f"{sim_name_prefix}_train",
                    f"{sim_name_prefix}_test",
                ],
            )
            rows = cur.fetchall() or []
            if not all(isinstance(row, dict) for row in rows):
                raise TypeError("Expected dict rows from database cursor")
    finally:
        conn.close()

    return [
        SimRunRow(
            strategy_sim_run_id=int(row["strategy_sim_run_id"]),
            sim_name=str(row["sim_name"]),
            policy_name=str(row["policy_name"]),
            from_ts_utc=row["from_ts_utc"],
            to_ts_utc=row["to_ts_utc"],
            hold_hours=int(row["hold_hours"]),
            max_trades_per_snapshot=int(row["max_trades_per_snapshot"]),
            cooldown_hours_per_symbol=int(row["cooldown_hours_per_symbol"]),
            dedupe_symbol_overlap=int(row["dedupe_symbol_overlap"]),
            candidate_rows=int(row["candidate_rows"]),
            trades_total=int(row["trades_total"]),
            symbol_count=int(row["symbol_count"]),
            day_count=int(row["day_count"]),
            avg_net_return=_to_decimal(row["avg_net_return"]),
            winrate=_to_decimal(row["winrate"]),
            worst_net_return=_to_decimal(row["worst_net_return"]),
            best_net_return=_to_decimal(row["best_net_return"]),
            compound_net_return_trade_sequence=_to_decimal(
                row["compound_net_return_trade_sequence"]
            ),
            created_ts_utc=row["created_ts_utc"],
        )
        for row in rows
    ]


def _pair_key(row: SimRunRow) -> tuple[Any, ...]:
    return (
        row.policy_name,
        row.hold_hours,
        row.max_trades_per_snapshot,
        row.cooldown_hours_per_symbol,
        row.dedupe_symbol_overlap,
    )


def _latest_by_key_and_side(rows: list[SimRunRow]) -> dict[tuple[Any, ...], dict[str, SimRunRow]]:
    grouped: dict[tuple[Any, ...], dict[str, SimRunRow]] = {}

    for row in rows:
        key = _pair_key(row)
        side = "train" if row.sim_name.endswith("_train") else "test"

        grouped.setdefault(key, {})
        existing = grouped[key].get(side)

        if existing is None or row.strategy_sim_run_id > existing.strategy_sim_run_id:
            grouped[key][side] = row

    return grouped


def _status_for_pair(
    *,
    train: SimRunRow,
    test: SimRunRow,
    min_test_trades: int,
) -> str:
    if test.trades_total < min_test_trades:
        return "INSUFFICIENT_TEST_TRADES"

    if train.avg_net_return is None or train.avg_net_return <= 0:
        return "TRAIN_NOT_POSITIVE"

    if test.avg_net_return is None or test.avg_net_return <= 0:
        return "FAIL_TEST_NEGATIVE_AVG"

    if (
        test.compound_net_return_trade_sequence is None
        or test.compound_net_return_trade_sequence <= 0
    ):
        return "FAIL_TEST_NEGATIVE_COMPOUND"

    if test.winrate is not None and test.winrate >= Decimal("0.55"):
        return "PROMOTE_RESEARCH_CANDIDATE"

    if test.winrate is not None and test.winrate >= Decimal("0.50"):
        return "PASS_WATCHLIST_CANDIDATE"

    return "POSITIVE_BUT_LOW_WINRATE"


def build_report_rows(
    *,
    rows: list[SimRunRow],
    min_test_trades: int,
) -> list[dict[str, Any]]:
    pairs = _latest_by_key_and_side(rows)
    report_rows: list[dict[str, Any]] = []

    for key, pair in pairs.items():
        train = pair.get("train")
        test = pair.get("test")

        if train is None or test is None:
            continue

        avg_retention = _safe_ratio(test.avg_net_return, train.avg_net_return)
        compound_retention = _safe_ratio(
            test.compound_net_return_trade_sequence,
            train.compound_net_return_trade_sequence,
        )

        report_rows.append(
            {
                "status": _status_for_pair(
                    train=train,
                    test=test,
                    min_test_trades=min_test_trades,
                ),
                "policy": train.policy_name,
                "hold": train.hold_hours,
                "max_per_snap": train.max_trades_per_snapshot,
                "cooldown": train.cooldown_hours_per_symbol,
                "dedupe": train.dedupe_symbol_overlap,
                "train_run": train.strategy_sim_run_id,
                "test_run": test.strategy_sim_run_id,
                "train_trades": train.trades_total,
                "train_avg": _fmt_decimal(train.avg_net_return),
                "train_wr": _fmt_decimal(train.winrate, 4),
                "train_comp": _fmt_decimal(train.compound_net_return_trade_sequence),
                "test_trades": test.trades_total,
                "test_avg": _fmt_decimal(test.avg_net_return),
                "test_wr": _fmt_decimal(test.winrate, 4),
                "test_comp": _fmt_decimal(test.compound_net_return_trade_sequence),
                "avg_retention": _fmt_decimal(avg_retention, 4),
                "compound_retention": _fmt_decimal(compound_retention, 4),
                "test_worst": _fmt_decimal(test.worst_net_return),
                "test_best": _fmt_decimal(test.best_net_return),
            }
        )

    return sorted(
        report_rows,
        key=lambda row: (
            Decimal(str(row["test_comp"] or "-999")),
            Decimal(str(row["test_avg"] or "-999")),
            Decimal(str(row["test_wr"] or "-999")),
            int(row["test_trades"]),
        ),
        reverse=True,
    )


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

    runs = fetch_runs(sim_name_prefix=str(args.sim_name_prefix))
    rows = build_report_rows(
        rows=runs,
        min_test_trades=int(args.min_test_trades),
    )

    payload = {
        "sim_name_prefix": str(args.sim_name_prefix),
        "runs_loaded": len(runs),
        "pairs": len(rows),
        "rows": rows,
    }

    if args.output == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    print("Strategy simulation result report")
    print(f"sim_name_prefix={args.sim_name_prefix}")
    print(f"runs_loaded={len(runs)}")
    print(f"pairs={len(rows)}")

    _print_table("WALK-FORWARD STRATEGY SIM SCOREBOARD", rows[: int(args.top)])

    promoted = [
        row
        for row in rows
        if row["status"] == "PROMOTE_RESEARCH_CANDIDATE"
    ]
    _print_table("PROMOTION CANDIDATES", promoted[: int(args.top)])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
