from __future__ import annotations

"""
Synth v2 - Swing Pullback Strategy Simulation V1.

LAYER:
research/backtest simulation

BOUNDARY:
Allowed:
- read synth_bt replay eval rows
- apply named market-only research policies
- simulate deterministic fixed-horizon research trades
- run rolling walk-forward validation

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions

Purpose:
Evaluate the repaired grid candidate family:

ROTATION_EARLY / PULLBACK_WATCH / SWING_STRUCTURAL

This runner is research-only. It must not be connected directly to
decision_gate, execution_planner, executor, or account-aware layers.
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BT_DB = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v1"

WEAK_SYMBOLS = ("HNT", "SOL", "XLM", "LTC", "ETH", "XRP", "CC", "NOT")


@dataclass(frozen=True)
class NamedPolicy:
    policy_name: str
    selection_states: tuple[str, ...]
    rank_min: int
    rank_max: int
    btc_prior_min: Decimal | None
    btc_prior_max: Decimal | None
    selection_score_min: Decimal | None
    selection_score_max_exclusive: Decimal | None
    exclude_weak_symbols: bool
    rotation_bucket: str
    classification_code: str
    sleeve_fit_code: str


@dataclass(frozen=True)
class CandidateRow:
    replay_id: int
    asset_id: int
    symbol: str
    replay_asof_ts_utc: datetime
    selection_state: str
    selection_score: Decimal | None
    priority_rank: int | None
    btc_prior_24h: Decimal | None
    rotation_bucket: str | None
    classification_code: str | None
    sleeve_fit_code: str | None
    net_return: Decimal


@dataclass(frozen=True)
class TradeRow:
    replay_id: int
    asset_id: int
    symbol: str
    entry_ts_utc: datetime
    exit_ts_utc: datetime
    selection_state: str
    selection_score: Decimal | None
    priority_rank: int | None
    net_return: Decimal


@dataclass(frozen=True)
class SimConfig:
    policy_name: str
    hold_hours: int
    cooldown_hours_per_symbol: int
    max_trades_per_snapshot: int
    dedupe_symbol_overlap: bool


@dataclass(frozen=True)
class WindowPair:
    split_id: int
    train_from_ts: datetime
    train_to_ts: datetime
    test_from_ts: datetime
    test_to_ts: datetime


POLICIES: dict[str, NamedPolicy] = {
    "swing_pullback_recovery_v1": NamedPolicy(
        policy_name="swing_pullback_recovery_v1",
        selection_states=("WATCHLIST", "PREPARE", "BUY_READY"),
        rank_min=1,
        rank_max=3,
        btc_prior_min=Decimal("-0.030"),
        btc_prior_max=Decimal("0.000"),
        selection_score_min=None,
        selection_score_max_exclusive=None,
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EARLY",
        classification_code="PULLBACK_WATCH",
        sleeve_fit_code="SWING_STRUCTURAL",
    ),
    "swing_pullback_recovery_v2": NamedPolicy(
        policy_name="swing_pullback_recovery_v2",
        selection_states=("WATCHLIST", "PREPARE", "BUY_READY"),
        rank_min=1,
        rank_max=3,
        btc_prior_min=Decimal("-0.030"),
        btc_prior_max=Decimal("0.000"),
        selection_score_min=Decimal("0.52000000"),
        selection_score_max_exclusive=None,
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EARLY",
        classification_code="PULLBACK_WATCH",
        sleeve_fit_code="SWING_STRUCTURAL",
    ),
    "swing_pullback_recovery_v3": NamedPolicy(
        policy_name="swing_pullback_recovery_v3",
        selection_states=("WATCHLIST", "PREPARE", "BUY_READY"),
        rank_min=1,
        rank_max=10,
        btc_prior_min=Decimal("-0.030"),
        btc_prior_max=Decimal("0.000"),
        selection_score_min=None,
        selection_score_max_exclusive=None,
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EARLY",
        classification_code="PULLBACK_WATCH",
        sleeve_fit_code="SWING_STRUCTURAL",
    ),

    "swing_pullback_recovery_v5": NamedPolicy(
        policy_name="swing_pullback_recovery_v5",
        selection_states=("WATCHLIST",),
        rank_min=1,
        rank_max=10,
        btc_prior_min=Decimal("-0.030"),
        btc_prior_max=Decimal("0.000"),
        selection_score_min=None,
        selection_score_max_exclusive=None,
        exclude_weak_symbols=False,
        rotation_bucket="ROTATION_EARLY",
        classification_code="PULLBACK_WATCH",
        sleeve_fit_code="SWING_STRUCTURAL",
    ),
    "swing_pullback_recovery_v6": NamedPolicy(
        policy_name="swing_pullback_recovery_v6",
        selection_states=("WATCHLIST",),
        rank_min=1,
        rank_max=10,
        btc_prior_min=Decimal("-0.030"),
        btc_prior_max=Decimal("0.000"),
        selection_score_min=None,
        selection_score_max_exclusive=None,
        exclude_weak_symbols=False,
        rotation_bucket="ROTATION_EARLY",
        classification_code="PULLBACK_WATCH",
        sleeve_fit_code="SWING_STRUCTURAL",
    ),
    "swing_pullback_recovery_v4": NamedPolicy(
        policy_name="swing_pullback_recovery_v4",
        selection_states=("WATCHLIST", "PREPARE", "BUY_READY"),
        rank_min=1,
        rank_max=10,
        btc_prior_min=Decimal("-0.030"),
        btc_prior_max=Decimal("0.000"),
        selection_score_min=Decimal("0.52000000"),
        selection_score_max_exclusive=None,
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EARLY",
        classification_code="PULLBACK_WATCH",
        sleeve_fit_code="SWING_STRUCTURAL",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run swing pullback recovery strategy simulation."
    )
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--train-days", type=int, default=14)
    parser.add_argument("--test-days", type=int, default=3)
    parser.add_argument("--step-days", type=int, default=3)
    parser.add_argument(
        "--policies",
        nargs="+",
        default=[
            "swing_pullback_recovery_v1",
            "swing_pullback_recovery_v2",
            "swing_pullback_recovery_v3",
            "swing_pullback_recovery_v4",
        ],
    )
    parser.add_argument("--hold-hours", nargs="+", type=int, default=[24])
    parser.add_argument("--cooldown-hours", nargs="+", type=int, default=[24])
    parser.add_argument("--max-trades-per-snapshot", nargs="+", type=int, default=[1, 2])
    parser.add_argument("--allow-symbol-overlap", action="store_true")
    parser.add_argument("--min-test-trades-per-split", type=int, default=2)
    parser.add_argument("--min-valid-test-splits", type=int, default=2)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--show-splits", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def fmt(value: Any, places: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.{places}f}"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return

    columns = list(rows[0].keys())
    rendered: list[dict[str, str]] = []

    for row in rows:
        rendered_row: dict[str, str] = {}
        for column in columns:
            value = row.get(column)
            if isinstance(value, Decimal):
                rendered_row[column] = fmt(value)
            elif isinstance(value, datetime):
                rendered_row[column] = fmt(value)
            else:
                rendered_row[column] = "" if value is None else str(value)
        rendered.append(rendered_row)

    widths = {
        column: max(len(column), max(len(row[column]) for row in rendered))
        for column in columns
    }

    print(" | ".join(column.ljust(widths[column]) for column in columns))
    print("-+-".join("-" * widths[column] for column in columns))

    for row in rendered:
        print(" | ".join(row[column].ljust(widths[column]) for column in columns))


def json_default(value: Any) -> str | int | float | None:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def resolve_policy(policy_name: str) -> NamedPolicy:
    if policy_name not in POLICIES:
        known = ", ".join(sorted(POLICIES))
        raise ValueError(f"Unknown policy={policy_name}. Known policies: {known}")
    return POLICIES[policy_name]


def build_policy_where(policy: NamedPolicy, hold_hours: int) -> tuple[str, list[Any]]:
    if hold_hours == 4:
        return_column = "net_return_4h"
    elif hold_hours == 24:
        return_column = "net_return_24h"
    else:
        raise ValueError("Only hold_hours 4 and 24 are supported by the eval horizon table")

    filters = [
        f"{return_column} IS NOT NULL",
        "selection_state IN (" + ",".join(["%s"] * len(policy.selection_states)) + ")",
        "priority_rank BETWEEN %s AND %s",
        "rotation_bucket = %s",
        "classification_code = %s",
        "sleeve_fit_code = %s",
    ]

    params: list[Any] = [
        *policy.selection_states,
        policy.rank_min,
        policy.rank_max,
        policy.rotation_bucket,
        policy.classification_code,
        policy.sleeve_fit_code,
    ]

    if policy.btc_prior_min is not None:
        filters.append("btc_prior_24h >= %s")
        params.append(str(policy.btc_prior_min))

    if policy.btc_prior_max is not None:
        filters.append("btc_prior_24h <= %s")
        params.append(str(policy.btc_prior_max))

    if policy.selection_score_min is not None:
        filters.append("selection_score >= %s")
        params.append(str(policy.selection_score_min))

    if policy.selection_score_max_exclusive is not None:
        filters.append("selection_score < %s")
        params.append(str(policy.selection_score_max_exclusive))

    if policy.exclude_weak_symbols:
        filters.append("symbol NOT IN (" + ",".join(["%s"] * len(WEAK_SYMBOLS)) + ")")
        params.extend(WEAK_SYMBOLS)

    return " AND ".join(filters), params


def fetch_candidates(
    *,
    eval_table: str,
    policy: NamedPolicy,
    hold_hours: int,
    from_ts: datetime,
    to_ts: datetime,
) -> list[CandidateRow]:
    if hold_hours == 4:
        return_column = "net_return_4h"
    elif hold_hours == 24:
        return_column = "net_return_24h"
    else:
        raise ValueError("Only hold_hours 4 and 24 are supported")

    where_sql, params = build_policy_where(policy, hold_hours)

    sql = f"""
    SELECT
        bt_selection_v2_replay_id,
        asset_id,
        symbol,
        replay_asof_ts_utc,
        selection_state,
        selection_score,
        priority_rank,
        btc_prior_24h,
        rotation_bucket,
        classification_code,
        sleeve_fit_code,
        {return_column} AS net_return
    FROM {eval_table}
    WHERE replay_asof_ts_utc >= %s
      AND replay_asof_ts_utc < %s
      AND {where_sql}
    ORDER BY replay_asof_ts_utc, priority_rank, symbol
    """

    full_params: list[Any] = [from_ts, to_ts, *params]

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, full_params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[CandidateRow] = []

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")

        net_return = to_decimal(row["net_return"])
        if net_return is None:
            continue

        out.append(
            CandidateRow(
                replay_id=int(row["bt_selection_v2_replay_id"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                replay_asof_ts_utc=row["replay_asof_ts_utc"],
                selection_state=str(row["selection_state"]),
                selection_score=to_decimal(row.get("selection_score")),
                priority_rank=None if row.get("priority_rank") is None else int(row["priority_rank"]),
                btc_prior_24h=to_decimal(row.get("btc_prior_24h")),
                rotation_bucket=row.get("rotation_bucket"),
                classification_code=row.get("classification_code"),
                sleeve_fit_code=row.get("sleeve_fit_code"),
                net_return=net_return,
            )
        )

    return out


def selection_state_priority(selection_state: str) -> int:
    priority = {
        "BUY_READY": 0,
        "PREPARE": 1,
        "WATCHLIST": 2,
    }
    return priority.get(selection_state, 9)


def simulate_trades(
    *,
    candidates: list[CandidateRow],
    hold_hours: int,
    cooldown_hours_per_symbol: int,
    max_trades_per_snapshot: int,
    dedupe_symbol_overlap: bool,
) -> list[TradeRow]:
    by_snapshot: dict[datetime, list[CandidateRow]] = defaultdict(list)

    for row in candidates:
        by_snapshot[row.replay_asof_ts_utc].append(row)

    next_allowed_by_symbol: dict[str, datetime] = {}
    trades: list[TradeRow] = []
    block_hours = max(hold_hours, cooldown_hours_per_symbol)

    for snapshot_ts in sorted(by_snapshot):
        rows = sorted(
            by_snapshot[snapshot_ts],
            key=lambda row: (
                row.priority_rank if row.priority_rank is not None else 999999,
                selection_state_priority(row.selection_state),
                Decimal("0") - (row.selection_score or Decimal("0")),
                row.symbol,
            ),
        )

        trades_this_snapshot = 0

        for row in rows:
            if trades_this_snapshot >= max_trades_per_snapshot:
                break

            if dedupe_symbol_overlap:
                next_allowed = next_allowed_by_symbol.get(row.symbol)
                if next_allowed is not None and snapshot_ts < next_allowed:
                    continue

            exit_ts = snapshot_ts + timedelta(hours=hold_hours)

            trades.append(
                TradeRow(
                    replay_id=row.replay_id,
                    asset_id=row.asset_id,
                    symbol=row.symbol,
                    entry_ts_utc=snapshot_ts,
                    exit_ts_utc=exit_ts,
                    selection_state=row.selection_state,
                    selection_score=row.selection_score,
                    priority_rank=row.priority_rank,
                    net_return=row.net_return,
                )
            )

            next_allowed_by_symbol[row.symbol] = snapshot_ts + timedelta(hours=block_hours)
            trades_this_snapshot += 1

    return trades


def summarize_trades(trades: list[TradeRow]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "symbols": 0,
            "days": 0,
            "avg_net": None,
            "winrate": None,
            "worst": None,
            "best": None,
            "sum_net_eq": Decimal("0"),
            "compound": Decimal("0"),
        }

    returns = [trade.net_return for trade in trades]
    avg_net = sum(returns, Decimal("0")) / Decimal(len(returns))
    wins = sum(1 for value in returns if value > 0)
    compound = Decimal("1")

    for value in returns:
        compound *= Decimal("1") + value

    compound -= Decimal("1")

    return {
        "trades": len(trades),
        "symbols": len({trade.symbol for trade in trades}),
        "days": len({trade.entry_ts_utc.date() for trade in trades}),
        "avg_net": avg_net,
        "winrate": Decimal(wins) / Decimal(len(returns)),
        "worst": min(returns),
        "best": max(returns),
        "sum_net_eq": sum(returns, Decimal("0")),
        "compound": compound,
    }


def filter_candidates(
    candidates: list[CandidateRow],
    *,
    from_ts: datetime,
    to_ts: datetime,
) -> list[CandidateRow]:
    return [
        row for row in candidates
        if row.replay_asof_ts_utc >= from_ts and row.replay_asof_ts_utc < to_ts
    ]


def build_windows(
    *,
    from_ts: datetime,
    to_ts: datetime,
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[WindowPair]:
    windows: list[WindowPair] = []
    split_id = 1
    cursor = from_ts

    while True:
        train_from = cursor
        train_to = train_from + timedelta(days=train_days)
        test_from = train_to
        test_to = test_from + timedelta(days=test_days)

        if test_to > to_ts:
            break

        windows.append(
            WindowPair(
                split_id=split_id,
                train_from_ts=train_from,
                train_to_ts=train_to,
                test_from_ts=test_from,
                test_to_ts=test_to,
            )
        )

        split_id += 1
        cursor += timedelta(days=step_days)

    return windows


def decimal_mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def product_compounds(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None

    out = Decimal("1")
    for value in values:
        out *= Decimal("1") + value

    return out - Decimal("1")


def classify_result(
    *,
    valid_test_splits: int,
    min_valid_test_splits: int,
    positive_test_splits: int,
    negative_test_splits: int,
    avg_test: Decimal | None,
    test_comp_product: Decimal | None,
) -> str:
    if valid_test_splits < min_valid_test_splits:
        return "INSUFFICIENT_VALID_TEST_SPLITS"

    if avg_test is None or test_comp_product is None:
        return "NO_VALID_TEST_METRICS"

    if avg_test <= 0 or test_comp_product <= 0:
        return "FAIL_TEST_NEGATIVE"

    if negative_test_splits == 0:
        return "PROMOTE_SWING_RESEARCH_CANDIDATE"

    if positive_test_splits >= max(1, valid_test_splits - 1):
        return "PASS_WITH_ONE_WEAK_SPLIT"

    return "POSITIVE_BUT_UNSTABLE"


def run_config(
    *,
    eval_table: str,
    config: SimConfig,
    windows: list[WindowPair],
    from_ts: datetime,
    to_ts: datetime,
    min_test_trades_per_split: int,
    min_valid_test_splits: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = resolve_policy(config.policy_name)

    all_candidates = fetch_candidates(
        eval_table=eval_table,
        policy=policy,
        hold_hours=config.hold_hours,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    split_rows: list[dict[str, Any]] = []
    train_avgs: list[Decimal] = []
    test_avgs: list[Decimal] = []
    train_compounds: list[Decimal] = []
    test_compounds: list[Decimal] = []

    valid_test_splits = 0
    positive_test_splits = 0
    negative_test_splits = 0
    zero_trade_test_splits = 0
    train_trades_total = 0
    test_trades_total = 0

    for window in windows:
        train_candidates = filter_candidates(
            all_candidates,
            from_ts=window.train_from_ts,
            to_ts=window.train_to_ts,
        )
        test_candidates = filter_candidates(
            all_candidates,
            from_ts=window.test_from_ts,
            to_ts=window.test_to_ts,
        )

        train_trades = simulate_trades(
            candidates=train_candidates,
            hold_hours=config.hold_hours,
            cooldown_hours_per_symbol=config.cooldown_hours_per_symbol,
            max_trades_per_snapshot=config.max_trades_per_snapshot,
            dedupe_symbol_overlap=config.dedupe_symbol_overlap,
        )
        test_trades = simulate_trades(
            candidates=test_candidates,
            hold_hours=config.hold_hours,
            cooldown_hours_per_symbol=config.cooldown_hours_per_symbol,
            max_trades_per_snapshot=config.max_trades_per_snapshot,
            dedupe_symbol_overlap=config.dedupe_symbol_overlap,
        )

        train_summary = summarize_trades(train_trades)
        test_summary = summarize_trades(test_trades)

        train_trades_total += int(train_summary["trades"])
        test_trades_total += int(test_summary["trades"])

        if train_summary["trades"] > 0 and train_summary["avg_net"] is not None:
            train_avgs.append(train_summary["avg_net"])
            train_compounds.append(train_summary["compound"])

        if test_summary["trades"] == 0:
            zero_trade_test_splits += 1

        if test_summary["trades"] >= min_test_trades_per_split and test_summary["avg_net"] is not None:
            valid_test_splits += 1
            test_avgs.append(test_summary["avg_net"])
            test_compounds.append(test_summary["compound"])

            if test_summary["avg_net"] > 0:
                positive_test_splits += 1
            else:
                negative_test_splits += 1

        split_rows.append(
            {
                "split": window.split_id,
                "policy": config.policy_name,
                "hold": config.hold_hours,
                "max_per_snap": config.max_trades_per_snapshot,
                "cooldown": config.cooldown_hours_per_symbol,
                "train": f"{fmt(window.train_from_ts)}->{fmt(window.train_to_ts)}",
                "test": f"{fmt(window.test_from_ts)}->{fmt(window.test_to_ts)}",
                "train_candidates": len(train_candidates),
                "train_trades": train_summary["trades"],
                "train_avg": fmt(train_summary["avg_net"]),
                "train_comp": fmt(train_summary["compound"]),
                "test_candidates": len(test_candidates),
                "test_trades": test_summary["trades"],
                "test_avg": fmt(test_summary["avg_net"]),
                "test_comp": fmt(test_summary["compound"]),
                "test_wr": fmt(test_summary["winrate"], 4),
            }
        )

    avg_train = decimal_mean(train_avgs)
    avg_test = decimal_mean(test_avgs)
    avg_train_comp = decimal_mean(train_compounds)
    avg_test_comp = decimal_mean(test_compounds)
    test_comp_product = product_compounds(test_compounds)

    avg_retention = None
    if avg_train is not None and avg_test is not None and avg_train > 0:
        avg_retention = avg_test / avg_train

    compound_retention = None
    if avg_train_comp is not None and avg_test_comp is not None and avg_train_comp > 0:
        compound_retention = avg_test_comp / avg_train_comp

    status = classify_result(
        valid_test_splits=valid_test_splits,
        min_valid_test_splits=min_valid_test_splits,
        positive_test_splits=positive_test_splits,
        negative_test_splits=negative_test_splits,
        avg_test=avg_test,
        test_comp_product=test_comp_product,
    )

    result = {
        "status": status,
        "policy": config.policy_name,
        "hold": config.hold_hours,
        "max_per_snap": config.max_trades_per_snapshot,
        "cooldown": config.cooldown_hours_per_symbol,
        "dedupe": int(config.dedupe_symbol_overlap),
        "splits": len(windows),
        "valid_test_splits": valid_test_splits,
        "positive_test_splits": positive_test_splits,
        "negative_test_splits": negative_test_splits,
        "zero_trade_test_splits": zero_trade_test_splits,
        "train_trades": train_trades_total,
        "test_trades": test_trades_total,
        "avg_train": avg_train,
        "avg_test": avg_test,
        "avg_retention": avg_retention,
        "avg_train_comp": avg_train_comp,
        "avg_test_comp": avg_test_comp,
        "compound_retention": compound_retention,
        "test_comp_product": test_comp_product,
    }

    return result, split_rows


def sort_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_rank = {
        "PROMOTE_SWING_RESEARCH_CANDIDATE": 0,
        "PASS_WITH_ONE_WEAK_SPLIT": 1,
        "POSITIVE_BUT_UNSTABLE": 2,
        "FAIL_TEST_NEGATIVE": 3,
        "NO_VALID_TEST_METRICS": 4,
        "INSUFFICIENT_VALID_TEST_SPLITS": 5,
    }

    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            status_rank.get(str(row["status"]), 99),
            -(row["test_comp_product"] or Decimal("-999999")),
            -(row["avg_test"] or Decimal("-999999")),
            -int(row["valid_test_splits"]),
            str(row["policy"]),
        )

    return sorted(rows, key=key)


def main() -> int:
    args = parse_args()

    from_ts = parse_ts(args.from_ts)
    to_ts = parse_ts(args.to_ts)

    windows = build_windows(
        from_ts=from_ts,
        to_ts=to_ts,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
    )

    configs: list[SimConfig] = []

    for policy_name in args.policies:
        resolve_policy(policy_name)
        for hold_hours in args.hold_hours:
            for cooldown_hours in args.cooldown_hours:
                for max_per_snapshot in args.max_trades_per_snapshot:
                    configs.append(
                        SimConfig(
                            policy_name=policy_name,
                            hold_hours=hold_hours,
                            cooldown_hours_per_symbol=cooldown_hours,
                            max_trades_per_snapshot=max_per_snapshot,
                            dedupe_symbol_overlap=not args.allow_symbol_overlap,
                        )
                    )

    results: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []

    for config in configs:
        result, splits = run_config(
            eval_table=args.eval_table,
            config=config,
            windows=windows,
            from_ts=from_ts,
            to_ts=to_ts,
            min_test_trades_per_split=args.min_test_trades_per_split,
            min_valid_test_splits=args.min_valid_test_splits,
        )
        results.append(result)
        split_rows.extend(splits)

    results = sort_results(results)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "eval_table": args.eval_table,
                    "from_ts": from_ts,
                    "to_ts": to_ts,
                    "train_days": args.train_days,
                    "test_days": args.test_days,
                    "step_days": args.step_days,
                    "splits": len(windows),
                    "configs": len(configs),
                    "results": results,
                    "split_rows": split_rows if args.show_splits else [],
                },
                indent=2,
                default=json_default,
            )
        )
        return 0

    print("Swing pullback strategy simulation")
    print(f"eval_table={args.eval_table}")
    print(f"window=[{fmt(from_ts)},{fmt(to_ts)})")
    print(f"train_days={args.train_days}")
    print(f"test_days={args.test_days}")
    print(f"step_days={args.step_days}")
    print(f"splits={len(windows)}")
    print(f"configs={len(configs)}")
    print()

    print("=== SWING PULLBACK WALK-FORWARD SCOREBOARD ===")
    table_rows: list[dict[str, Any]] = []
    for row in results[: args.top]:
        table_rows.append(
            {
                "status": row["status"],
                "policy": row["policy"],
                "hold": row["hold"],
                "max_per_snap": row["max_per_snap"],
                "cooldown": row["cooldown"],
                "dedupe": row["dedupe"],
                "splits": row["splits"],
                "valid": row["valid_test_splits"],
                "positive": row["positive_test_splits"],
                "negative": row["negative_test_splits"],
                "zero": row["zero_trade_test_splits"],
                "train_trades": row["train_trades"],
                "test_trades": row["test_trades"],
                "avg_train": fmt(row["avg_train"]),
                "avg_test": fmt(row["avg_test"]),
                "avg_retention": fmt(row["avg_retention"], 4),
                "avg_train_comp": fmt(row["avg_train_comp"]),
                "avg_test_comp": fmt(row["avg_test_comp"]),
                "compound_retention": fmt(row["compound_retention"], 4),
                "test_comp_product": fmt(row["test_comp_product"]),
            }
        )
    print_table(table_rows)

    print()
    print("=== PROMOTION CANDIDATES ===")
    candidate_rows = [
        row for row in table_rows
        if row["status"] in ("PROMOTE_SWING_RESEARCH_CANDIDATE", "PASS_WITH_ONE_WEAK_SPLIT")
    ]
    print_table(candidate_rows)

    if args.show_splits:
        print()
        print("=== SPLIT DETAILS ===")
        print_table(split_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
