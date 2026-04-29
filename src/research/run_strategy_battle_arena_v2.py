from __future__ import annotations

# Synth v2.5 - Strategy Battle Arena V2.
#
# LAYER:
# research / strategy optimization arena
#
# BOUNDARY:
# Allowed:
# - read replay/evaluation data
# - compare market-only strategy parameter variants
# - compare multiple forward-return horizons
# - report global and per-symbol strategy preferences
# - classify variants as REJECTED / WATCH / PROMOTION_CANDIDATE
#
# Forbidden:
# - account balances
# - positions
# - open orders
# - decision_gate writes
# - execution_intent writes
# - execution_plan writes
# - broker/order actions
#
# Purpose:
# Let strategy variants prove themselves in a controlled research arena before
# they become paper candidates. V2 supports multi-horizon judging so a swing
# strategy cannot win on a cute 24h bounce and faceplant over a week.

import argparse
import itertools
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v2"
DEFAULT_STRATEGY_FAMILY = "swing_pullback_recovery_v5"

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

SUPPORTED_HORIZONS = frozenset({4, 24, 48, 72, 168})

PROMOTION_STATE_ORDER = (
    "PROMOTION_CANDIDATE",
    "WATCH",
    "REJECTED",
)


@dataclass(frozen=True)
class EvalRow:
    replay_id: int
    asset_id: int
    symbol: str
    venue: str
    replay_asof_ts_utc: datetime
    selection_state: str
    selection_score: Decimal | None
    priority_rank: int | None
    btc_prior_24h: Decimal | None
    rotation_bucket: str | None
    classification_code: str | None
    sleeve_fit_code: str | None
    returns_by_horizon: dict[int, Decimal | None]


@dataclass(frozen=True)
class ArenaParams:
    strategy_family: str
    hold_hours: int
    max_per_snapshot: int
    cooldown_hours: int
    rank_max: int
    btc_min: Decimal
    btc_max: Decimal
    min_selection_score: Decimal
    exclude_score_notch: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only multi-horizon strategy battle arena for Synth v2.5."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--venue", default="bitvavo")

    parser.add_argument("--hold-hours-values", default="72,168")
    parser.add_argument("--max-per-snapshot-values", default="1,2,3")
    parser.add_argument("--cooldown-hours-values", default="12,24,48")
    parser.add_argument("--rank-max-values", default="5,10")
    parser.add_argument("--btc-min-values", default="-0.05,-0.03,-0.02")
    parser.add_argument("--btc-max-values", default="0.00,0.02")
    parser.add_argument("--min-score-values", default="0.00,0.45,0.52")
    parser.add_argument(
        "--score-notch-mode",
        choices=("exclude", "include", "both"),
        default="exclude",
        help="Canonical v5 excludes score 0.50-0.52 with ranks 4-6.",
    )

    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--min-valid-months", type=int, default=2)
    parser.add_argument("--min-winrate", default="0.55")
    parser.add_argument("--min-avg-return", default="0.005")
    parser.add_argument("--max-symbol-trade-share", default="0.35")
    parser.add_argument("--max-worst-month-avg-loss", default="-0.05")
    parser.add_argument("--min-symbol-trades", type=int, default=2)
    parser.add_argument(
        "--min-positive-month-ratio",
        default="0.60",
        help="Minimum ratio of positive monthly splits required for PROMOTION_CANDIDATE.",
    )
    parser.add_argument("--min-promotion-hold-hours", type=int, default=72)

    parser.add_argument("--limit-rows", type=int, default=None)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--symbol-top", type=int, default=30)
    parser.add_argument("--output", choices=("table", "json", "jsonl"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("T", " "))


def parse_int_list(value: str) -> list[int]:
    out = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not out:
        raise ValueError("Expected at least one integer value.")
    return out


def parse_decimal_list(value: str) -> list[Decimal]:
    out = [Decimal(item.strip()) for item in value.split(",") if item.strip()]
    if not out:
        raise ValueError("Expected at least one decimal value.")
    return out


def validate_horizons(values: list[int]) -> list[int]:
    invalid = sorted(set(values).difference(SUPPORTED_HORIZONS))
    if invalid:
        raise ValueError(f"Unsupported hold horizons: {invalid}; supported={sorted(SUPPORTED_HORIZONS)}")
    return values


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return parse_ts(str(value))


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def score_notch_values(mode: str) -> list[bool]:
    if mode == "exclude":
        return [True]
    if mode == "include":
        return [False]
    return [True, False]


def build_param_grid(args: argparse.Namespace) -> list[ArenaParams]:
    hold_values = validate_horizons(parse_int_list(args.hold_hours_values))
    max_per_values = parse_int_list(args.max_per_snapshot_values)
    cooldown_values = parse_int_list(args.cooldown_hours_values)
    rank_values = parse_int_list(args.rank_max_values)
    btc_min_values = parse_decimal_list(args.btc_min_values)
    btc_max_values = parse_decimal_list(args.btc_max_values)
    min_score_values = parse_decimal_list(args.min_score_values)
    notch_values = score_notch_values(args.score_notch_mode)

    out: list[ArenaParams] = []

    for (
        hold_hours,
        max_per_snapshot,
        cooldown_hours,
        rank_max,
        btc_min,
        btc_max,
        min_selection_score,
        exclude_score_notch,
    ) in itertools.product(
        hold_values,
        max_per_values,
        cooldown_values,
        rank_values,
        btc_min_values,
        btc_max_values,
        min_score_values,
        notch_values,
    ):
        if btc_min > btc_max:
            continue

        out.append(
            ArenaParams(
                strategy_family=DEFAULT_STRATEGY_FAMILY,
                hold_hours=hold_hours,
                max_per_snapshot=max_per_snapshot,
                cooldown_hours=cooldown_hours,
                rank_max=rank_max,
                btc_min=btc_min,
                btc_max=btc_max,
                min_selection_score=min_selection_score,
                exclude_score_notch=exclude_score_notch,
            )
        )

    return out


def build_return_select_sql(horizons: list[int]) -> str:
    return ",\n        ".join(f"net_return_{horizon}h" for horizon in sorted(set(horizons)))


def build_return_not_null_sql(horizons: list[int]) -> str:
    parts = [f"net_return_{horizon}h IS NOT NULL" for horizon in sorted(set(horizons))]
    return "(" + " OR ".join(parts) + ")"


def fetch_eval_rows(
    *,
    database: str,
    eval_table: str,
    from_ts: datetime,
    to_ts: datetime,
    venue: str,
    param_grid: list[ArenaParams],
    limit_rows: int | None,
) -> list[EvalRow]:
    if not param_grid:
        return []

    safe_table = validate_table_name(eval_table)
    horizons = sorted({params.hold_hours for params in param_grid})
    return_select_sql = build_return_select_sql(horizons)
    return_not_null_sql = build_return_not_null_sql(horizons)

    max_rank = max(item.rank_max for item in param_grid)
    btc_min = min(item.btc_min for item in param_grid)
    btc_max = max(item.btc_max for item in param_grid)

    sql = (
        "SELECT "
        "bt_selection_v2_replay_id, asset_id, symbol, venue, replay_asof_ts_utc, "
        "selection_state, selection_score, priority_rank, btc_prior_24h, "
        "rotation_bucket, classification_code, sleeve_fit_code, "
        f"{return_select_sql} "
        f"FROM {safe_table} "
        "WHERE replay_asof_ts_utc >= %(from_ts)s "
        "AND replay_asof_ts_utc < %(to_ts)s "
        "AND venue = %(venue)s "
        "AND selection_state = 'WATCHLIST' "
        "AND priority_rank IS NOT NULL "
        "AND priority_rank <= %(max_rank)s "
        "AND btc_prior_24h IS NOT NULL "
        "AND btc_prior_24h >= %(btc_min)s "
        "AND btc_prior_24h <= %(btc_max)s "
        "AND rotation_bucket = 'ROTATION_EARLY' "
        "AND classification_code = 'PULLBACK_WATCH' "
        "AND sleeve_fit_code = 'SWING_STRUCTURAL' "
        f"AND {return_not_null_sql} "
        "ORDER BY replay_asof_ts_utc, priority_rank, selection_score DESC, symbol"
    )

    params: dict[str, Any] = {
        "from_ts": from_ts,
        "to_ts": to_ts,
        "venue": venue,
        "max_rank": max_rank,
        "btc_min": btc_min,
        "btc_max": btc_max,
    }

    if limit_rows is not None:
        sql = f"{sql} LIMIT %(limit_rows)s"
        params["limit_rows"] = int(limit_rows)

    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[EvalRow] = []
    for row in rows:
        returns_by_horizon = {
            horizon: to_decimal(row.get(f"net_return_{horizon}h"))
            for horizon in horizons
        }

        out.append(
            EvalRow(
                replay_id=int(row["bt_selection_v2_replay_id"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                replay_asof_ts_utc=to_datetime(row["replay_asof_ts_utc"]),
                selection_state=str(row["selection_state"]),
                selection_score=to_decimal(row.get("selection_score")),
                priority_rank=None if row.get("priority_rank") is None else int(row["priority_rank"]),
                btc_prior_24h=to_decimal(row.get("btc_prior_24h")),
                rotation_bucket=None if row.get("rotation_bucket") is None else str(row["rotation_bucket"]),
                classification_code=None if row.get("classification_code") is None else str(row["classification_code"]),
                sleeve_fit_code=None if row.get("sleeve_fit_code") is None else str(row["sleeve_fit_code"]),
                returns_by_horizon=returns_by_horizon,
            )
        )

    return out


def row_return(row: EvalRow, hold_hours: int) -> Decimal | None:
    return row.returns_by_horizon.get(hold_hours)


def row_passes_params(row: EvalRow, params: ArenaParams) -> bool:
    if row_return(row, params.hold_hours) is None:
        return False

    if row.priority_rank is None or row.priority_rank > params.rank_max:
        return False

    if row.btc_prior_24h is None:
        return False

    if row.btc_prior_24h < params.btc_min or row.btc_prior_24h > params.btc_max:
        return False

    if row.selection_score is not None and row.selection_score < params.min_selection_score:
        return False

    if params.exclude_score_notch:
        score = row.selection_score
        rank = row.priority_rank
        if score is not None and score >= Decimal("0.50000000") and score < Decimal("0.52000000"):
            if rank >= 4 and rank <= 6:
                return False

    return True


def apply_throttle(rows: list[EvalRow], params: ArenaParams) -> list[EvalRow]:
    accepted: list[EvalRow] = []
    accepted_count_by_ts: dict[datetime, int] = defaultdict(int)
    accepted_symbols_by_ts: dict[datetime, set[str]] = defaultdict(set)
    last_symbol_accept_ts: dict[str, datetime] = {}
    cooldown = timedelta(hours=params.cooldown_hours)

    for row in rows:
        if not row_passes_params(row, params):
            continue

        ts = row.replay_asof_ts_utc

        if accepted_count_by_ts[ts] >= params.max_per_snapshot:
            continue

        if row.symbol in accepted_symbols_by_ts[ts]:
            continue

        previous_ts = last_symbol_accept_ts.get(row.symbol)
        if previous_ts is not None and ts - previous_ts < cooldown:
            continue

        accepted.append(row)
        accepted_count_by_ts[ts] += 1
        accepted_symbols_by_ts[ts].add(row.symbol)
        last_symbol_accept_ts[row.symbol] = ts

    return accepted


def get_float_returns(rows: list[EvalRow], hold_hours: int) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = row_return(row, hold_hours)
        if value is not None:
            out.append(float(value))
    return out


def group_returns_by_month(rows: list[EvalRow], hold_hours: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row_return(row, hold_hours)
        if value is not None:
            grouped[row.replay_asof_ts_utc.strftime("%Y-%m")].append(float(value))

    out: list[dict[str, Any]] = []
    for month in sorted(grouped):
        values = grouped[month]
        wins = sum(1 for value in values if value > 0)
        out.append(
            {
                "month": month,
                "trades": len(values),
                "avg_return": round(sum(values) / len(values), 8),
                "winrate": round(wins / len(values), 4),
                "worst_return": round(min(values), 8),
                "best_return": round(max(values), 8),
            }
        )
    return out


def group_returns_by_symbol(rows: list[EvalRow], hold_hours: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row_return(row, hold_hours)
        if value is not None:
            grouped[row.symbol].append(float(value))

    out: list[dict[str, Any]] = []
    for symbol in sorted(grouped):
        values = grouped[symbol]
        wins = sum(1 for value in values if value > 0)
        out.append(
            {
                "symbol": symbol,
                "trades": len(values),
                "avg_return": round(sum(values) / len(values), 8),
                "median_return": round(median(values), 8),
                "winrate": round(wins / len(values), 4),
                "worst_return": round(min(values), 8),
                "best_return": round(max(values), 8),
            }
        )

    return sorted(out, key=lambda item: (-item["trades"], -item["avg_return"], item["symbol"]))


def calc_profit_factor(values: list[float]) -> float:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))

    if losses == 0:
        if gains > 0:
            return 999.0
        return 0.0

    return gains / losses


def classify_promotion(
    *,
    hold_hours: int,
    trades: int,
    avg_return: float,
    winrate: float,
    valid_months: int,
    worst_month_avg: float | None,
    max_symbol_trade_share: float,
    positive_month_ratio: float,
    args: argparse.Namespace,
) -> tuple[str, list[str]]:
    min_trades = int(args.min_trades)
    min_valid_months = int(args.min_valid_months)
    min_winrate = float(Decimal(str(args.min_winrate)))
    min_avg_return = float(Decimal(str(args.min_avg_return)))
    max_symbol_trade_share_allowed = float(Decimal(str(args.max_symbol_trade_share)))
    max_worst_month_avg_loss = float(Decimal(str(args.max_worst_month_avg_loss)))
    min_positive_month_ratio = float(Decimal(str(args.min_positive_month_ratio)))

    reasons: list[str] = []

    if trades < min_trades:
        reasons.append("MIN_TRADES_NOT_MET")
    if valid_months < min_valid_months:
        reasons.append("MIN_VALID_MONTHS_NOT_MET")
    if avg_return < min_avg_return:
        reasons.append("MIN_AVG_RETURN_NOT_MET")
    if winrate < min_winrate:
        reasons.append("MIN_WINRATE_NOT_MET")
    if max_symbol_trade_share > max_symbol_trade_share_allowed:
        reasons.append("MAX_SYMBOL_TRADE_SHARE_EXCEEDED")
    if positive_month_ratio < min_positive_month_ratio:
        reasons.append("MIN_POSITIVE_MONTH_RATIO_NOT_MET")
    if worst_month_avg is None:
        reasons.append("NO_MONTHLY_SPLITS")
    elif worst_month_avg < max_worst_month_avg_loss:
        reasons.append("WORST_MONTH_AVG_LOSS_EXCEEDED")

    if not reasons:
        min_promotion_hold_hours = int(args.min_promotion_hold_hours)
        if hold_hours < min_promotion_hold_hours:
            return "WATCH", ["HOLD_BELOW_PROMOTION_MIN"]
        return "PROMOTION_CANDIDATE", []

    watch_floor = max(5, min_trades // 2)
    if trades >= watch_floor and avg_return > 0 and winrate >= 0.50:
        return "WATCH", reasons

    return "REJECTED", reasons


def promotion_state_rank(value: str) -> int:
    try:
        return PROMOTION_STATE_ORDER.index(value)
    except ValueError:
        return len(PROMOTION_STATE_ORDER)


def calc_promotion_score(
    *,
    trades: int,
    avg_return: float,
    winrate: float,
    profit_factor: float,
    positive_month_ratio: float,
    worst_month_avg: float,
    max_symbol_trade_share: float,
) -> float:
    trade_term = min(math.log(max(trades, 1), 10), 2.0)
    avg_term = avg_return * 100.0
    winrate_term = (winrate - 0.50) * 20.0
    pf_term = min(profit_factor, 5.0)
    month_term = positive_month_ratio * 10.0
    worst_month_penalty = abs(min(worst_month_avg, 0.0)) * 50.0
    concentration_penalty = max(max_symbol_trade_share - 0.35, 0.0) * 20.0

    return round(
        trade_term
        + avg_term
        + winrate_term
        + pf_term
        + month_term
        - worst_month_penalty
        - concentration_penalty,
        6,
    )


def params_to_dict(params: ArenaParams) -> dict[str, Any]:
    return {
        "strategy_family": params.strategy_family,
        "hold_hours": params.hold_hours,
        "max_per_snapshot": params.max_per_snapshot,
        "cooldown_hours": params.cooldown_hours,
        "rank_max": params.rank_max,
        "btc_min": str(params.btc_min),
        "btc_max": str(params.btc_max),
        "min_selection_score": str(params.min_selection_score),
        "exclude_score_notch": params.exclude_score_notch,
    }


def evaluate_variant(rows: list[EvalRow], params: ArenaParams, args: argparse.Namespace) -> dict[str, Any]:
    accepted = apply_throttle(rows, params)
    values = get_float_returns(accepted, params.hold_hours)
    trades = len(values)

    if trades == 0:
        return {
            "params": params_to_dict(params),
            "promotion_state": "REJECTED",
            "promotion_score": -999.0,
            "failure_reasons": ["NO_TRADES"],
            "metrics": {
                "trades": 0,
                "symbols": 0,
                "avg_return": None,
                "median_return": None,
                "winrate": None,
                "profit_factor": None,
                "worst_return": None,
                "best_return": None,
                "valid_months": 0,
                "positive_months": 0,
                "positive_month_ratio": 0,
                "worst_month_avg": None,
                "max_symbol_trade_share": None,
            },
            "monthly_breakdown": [],
            "symbol_breakdown": [],
        }

    wins = sum(1 for value in values if value > 0)
    symbols = sorted({row.symbol for row in accepted})
    monthly = group_returns_by_month(accepted, params.hold_hours)
    symbol_breakdown = group_returns_by_symbol(accepted, params.hold_hours)

    valid_months = len(monthly)
    positive_months = sum(1 for row in monthly if row["avg_return"] > 0)
    positive_month_ratio = positive_months / valid_months if valid_months else 0.0
    worst_month_avg = min(row["avg_return"] for row in monthly) if monthly else 0.0
    max_symbol_trade_share = max(row["trades"] for row in symbol_breakdown) / trades if symbol_breakdown else 0.0

    avg_return = sum(values) / trades
    median_return = median(values)
    winrate = wins / trades
    profit_factor = calc_profit_factor(values)

    promotion_state, failure_reasons = classify_promotion(
        hold_hours=params.hold_hours,
        trades=trades,
        avg_return=avg_return,
        winrate=winrate,
        valid_months=valid_months,
        worst_month_avg=worst_month_avg,
        max_symbol_trade_share=max_symbol_trade_share,
        positive_month_ratio=positive_month_ratio,
        args=args,
    )

    promotion_score = calc_promotion_score(
        trades=trades,
        avg_return=avg_return,
        winrate=winrate,
        profit_factor=profit_factor,
        positive_month_ratio=positive_month_ratio,
        worst_month_avg=worst_month_avg,
        max_symbol_trade_share=max_symbol_trade_share,
    )

    return {
        "params": params_to_dict(params),
        "promotion_state": promotion_state,
        "promotion_score": promotion_score,
        "failure_reasons": failure_reasons,
        "metrics": {
            "trades": trades,
            "symbols": len(symbols),
            "avg_return": round(avg_return, 8),
            "median_return": round(median_return, 8),
            "winrate": round(winrate, 4),
            "profit_factor": round(profit_factor, 4),
            "worst_return": round(min(values), 8),
            "best_return": round(max(values), 8),
            "valid_months": valid_months,
            "positive_months": positive_months,
            "positive_month_ratio": round(positive_month_ratio, 4),
            "worst_month_avg": round(worst_month_avg, 8),
            "max_symbol_trade_share": round(max_symbol_trade_share, 4),
        },
        "monthly_breakdown": monthly,
        "symbol_breakdown": symbol_breakdown,
    }


def build_symbol_leaders(
    *,
    results: list[dict[str, Any]],
    min_symbol_trades: int,
    top: int,
) -> list[dict[str, Any]]:
    best_by_symbol: dict[str, dict[str, Any]] = {}

    for result in results:
        params = result["params"]
        parent_state = result["promotion_state"]

        for symbol_row in result["symbol_breakdown"]:
            trades = int(symbol_row["trades"])
            if trades < min_symbol_trades:
                continue

            avg_return = float(symbol_row["avg_return"])
            winrate = float(symbol_row["winrate"])
            symbol_score = round(
                avg_return * 100.0
                + (winrate - 0.50) * 10.0
                + min(trades, 10) * 0.10,
                6,
            )

            avg_return = float(symbol_row["avg_return"])
            symbol_winrate = float(symbol_row["winrate"])

            if avg_return >= 0.015 and symbol_winrate >= 0.60:
                symbol_state = "SYMBOL_STRONG"
            elif avg_return > 0 and symbol_winrate >= 0.50:
                symbol_state = "SYMBOL_WATCH"
            else:
                symbol_state = "SYMBOL_REJECTED"

            candidate = {
                "symbol": symbol_row["symbol"],
                "symbol_score": symbol_score,
                "parent_variant_state": parent_state,
                "symbol_state": symbol_state,
                "symbol_metrics": symbol_row,
                "params": params,
            }

            current = best_by_symbol.get(symbol_row["symbol"])
            if current is None or candidate["symbol_score"] > current["symbol_score"]:
                best_by_symbol[symbol_row["symbol"]] = candidate

    return sorted(
        best_by_symbol.values(),
        key=lambda item: (-item["symbol_score"], item["symbol"]),
    )[:top]


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        out[value] = out.get(value, 0) + 1
    return out


def run_arena(args: argparse.Namespace) -> dict[str, Any]:
    from_ts = parse_ts(args.from_ts)
    to_ts = parse_ts(args.to_ts)
    param_grid = build_param_grid(args)

    rows = fetch_eval_rows(
        database=args.database,
        eval_table=args.eval_table,
        from_ts=from_ts,
        to_ts=to_ts,
        venue=args.venue,
        param_grid=param_grid,
        limit_rows=args.limit_rows,
    )

    results = [evaluate_variant(rows, params, args) for params in param_grid]
    results = sorted(
        results,
        key=lambda item: (
            promotion_state_rank(item["promotion_state"]),
            -float(item["promotion_score"]),
            -int(item["metrics"]["trades"]),
        ),
    )

    symbol_leaders = build_symbol_leaders(
        results=results,
        min_symbol_trades=int(args.min_symbol_trades),
        top=int(args.symbol_top),
    )

    return {
        "arena": {
            "arena_version": "strategy_battle_arena_v2",
            "strategy_family": DEFAULT_STRATEGY_FAMILY,
            "database": args.database,
            "eval_table": args.eval_table,
            "venue": args.venue,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "base_rows": len(rows),
            "variant_count": len(param_grid),
            "promotion_state_counts": count_by(results, "promotion_state"),
            "writes": "none",
        },
        "results": results[: int(args.top)],
        "symbol_leaders": symbol_leaders,
    }


def print_table(payload: dict[str, Any]) -> None:
    arena = payload["arena"]

    print("Strategy Battle Arena V2")
    print(f"strategy_family: {arena['strategy_family']}")
    print(f"database: {arena['database']}")
    print(f"eval_table: {arena['eval_table']}")
    print(f"venue: {arena['venue']}")
    print(f"from_ts: {json_default(arena['from_ts'])}")
    print(f"to_ts: {json_default(arena['to_ts'])}")
    print(f"base_rows: {arena['base_rows']}")
    print(f"variant_count: {arena['variant_count']}")
    print(f"promotion_state_counts: {arena['promotion_state_counts']}")
    print(f"writes: {arena['writes']}")

    print()
    print("--- top variants ---")
    header = (
        "state | score | hold | trades | symbols | avg | med | winrate | pf | months | "
        "worst_month | sym_share | max/snap | cooldown | rank<= | btc | min_score | notch | fail"
    )
    print(header)
    print("-" * len(header))

    for result in payload["results"]:
        metrics = result["metrics"]
        params = result["params"]
        fail = ",".join(result["failure_reasons"]) if result["failure_reasons"] else "-"
        print(
            f"{result['promotion_state']} | "
            f"{result['promotion_score']} | "
            f"{params['hold_hours']}h | "
            f"{metrics['trades']} | "
            f"{metrics['symbols']} | "
            f"{metrics['avg_return']} | "
            f"{metrics['median_return']} | "
            f"{metrics['winrate']} | "
            f"{metrics['profit_factor']} | "
            f"{metrics['valid_months']}/{metrics['positive_months']} | "
            f"{metrics['worst_month_avg']} | "
            f"{metrics['max_symbol_trade_share']} | "
            f"{params['max_per_snapshot']} | "
            f"{params['cooldown_hours']} | "
            f"{params['rank_max']} | "
            f"{params['btc_min']}..{params['btc_max']} | "
            f"{params['min_selection_score']} | "
            f"{'exclude' if params['exclude_score_notch'] else 'include'} | "
            f"{fail}"
        )

    print()
    print("--- per-symbol leaders ---")
    symbol_header = (
        "symbol | score | hold | symbol_state | parent_variant_state | trades | avg | med | winrate | worst | best | "
        "max/snap | cooldown | rank<= | btc | min_score"
    )
    print(symbol_header)
    print("-" * len(symbol_header))

    for item in payload["symbol_leaders"]:
        metrics = item["symbol_metrics"]
        params = item["params"]
        print(
            f"{item['symbol']} | "
            f"{item['symbol_score']} | "
            f"{params['hold_hours']}h | "
            f"{item['symbol_state']} | "
            f"{item['parent_variant_state']} | "
            f"{metrics['trades']} | "
            f"{metrics['avg_return']} | "
            f"{metrics['median_return']} | "
            f"{metrics['winrate']} | "
            f"{metrics['worst_return']} | "
            f"{metrics['best_return']} | "
            f"{params['max_per_snapshot']} | "
            f"{params['cooldown_hours']} | "
            f"{params['rank_max']} | "
            f"{params['btc_min']}..{params['btc_max']} | "
            f"{params['min_selection_score']}"
        )


def main() -> int:
    args = parse_args()
    payload = run_arena(args)

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
        return 0

    if args.output == "jsonl":
        for row in payload["results"]:
            print(json.dumps(row, default=json_default, sort_keys=True))
        return 0

    print_table(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
