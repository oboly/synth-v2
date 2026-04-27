from __future__ import annotations

"""
Synth v2 - Named Replay Policy V1.

LAYER:
research/backtest evaluation

BOUNDARY:
Allowed:
- read synth_bt replay eval table
- evaluate named market-only research policies
- print policy summary, day breakdown, symbol breakdown, and trade rows

Forbidden:
- account state
- balances
- positions
- orders
- execution plans
- broker actions

Named policies:
- parking_rotation_recovery_v1
- parking_rotation_recovery_v2
"""

import argparse
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BT_DB = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v1"
DEFAULT_POLICY = "parking_rotation_recovery_v1"

WEAK_SYMBOLS = ("HNT", "SOL", "XLM", "LTC", "ETH", "XRP", "CC", "NOT")
WEAK_SYMBOLS_SQL = ",".join(f"'{symbol}'" for symbol in WEAK_SYMBOLS)


@dataclass(frozen=True)
class NamedPolicy:
    policy_name: str
    rank_min: int
    rank_max: int
    btc_prior_min: Decimal
    btc_prior_max: Decimal
    max_selection_score_exclusive: Decimal
    exclude_weak_symbols: bool
    rotation_bucket: str
    classification_code: str
    sleeve_fit_code: str


POLICIES: dict[str, NamedPolicy] = {
    "parking_rotation_recovery_v1": NamedPolicy(
        policy_name="parking_rotation_recovery_v1",
        rank_min=4,
        rank_max=10,
        btc_prior_min=Decimal("-0.010"),
        btc_prior_max=Decimal("0.010"),
        max_selection_score_exclusive=Decimal("0.50000000"),
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EXIT",
        classification_code="NO_TRADE",
        sleeve_fit_code="EXPERIMENTAL",
    ),
    "parking_rotation_recovery_v2": NamedPolicy(
        policy_name="parking_rotation_recovery_v2",
        rank_min=6,
        rank_max=15,
        btc_prior_min=Decimal("-0.005"),
        btc_prior_max=Decimal("0.015"),
        max_selection_score_exclusive=Decimal("0.50000000"),
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EXIT",
        classification_code="NO_TRADE",
        sleeve_fit_code="EXPERIMENTAL",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate named replay research policy."
    )
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    parser.add_argument("--show-trades", action="store_true")
    return parser.parse_args()


def _validate_table_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"Unsafe eval table name: {value}")
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


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


def _resolve_policy(policy_name: str) -> NamedPolicy:
    if policy_name not in POLICIES:
        allowed = ", ".join(sorted(POLICIES))
        raise ValueError(f"Unsupported policy: {policy_name}. Allowed: {allowed}")
    return POLICIES[policy_name]


def _policy_where(policy: NamedPolicy) -> str:
    weak_filter_sql = ""
    if policy.exclude_weak_symbols:
        weak_filter_sql = f"AND symbol NOT IN ({WEAK_SYMBOLS_SQL})"

    return f"""
        selection_state = 'WATCHLIST'
        AND priority_rank BETWEEN {policy.rank_min} AND {policy.rank_max}
        AND btc_prior_24h >= {policy.btc_prior_min}
        AND btc_prior_24h <= {policy.btc_prior_max}
        AND selection_score < {policy.max_selection_score_exclusive}
        {weak_filter_sql}
        AND rotation_bucket = '{policy.rotation_bucket}'
        AND classification_code = '{policy.classification_code}'
        AND sleeve_fit_code = '{policy.sleeve_fit_code}'
    """


def fetch_rows(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            rows = cur.fetchall() or []
            if not all(isinstance(row, dict) for row in rows):
                raise TypeError("Expected dict rows from database cursor")
            return list(rows)
    finally:
        conn.close()


def _time_filter_sql(*, from_ts: str | None, to_ts: str | None) -> tuple[str, list[Any]]:
    filters: list[str] = []
    params: list[Any] = []

    if from_ts is not None:
        filters.append("replay_asof_ts_utc >= %s")
        params.append(from_ts)

    if to_ts is not None:
        filters.append("replay_asof_ts_utc < %s")
        params.append(to_ts)

    if not filters:
        return "", []

    return " AND " + " AND ".join(filters), params


def evaluate_policy(
    *,
    eval_table: str,
    policy_name: str,
    from_ts: str | None,
    to_ts: str | None,
) -> dict[str, list[dict[str, Any]]]:
    safe_eval_table = _validate_table_name(eval_table)
    policy = _resolve_policy(policy_name)

    where_sql = _policy_where(policy)
    time_filter_sql, time_params = _time_filter_sql(from_ts=from_ts, to_ts=to_ts)
    full_where_sql = f"{where_sql} {time_filter_sql}"

    summary = fetch_rows(
        f"""
        SELECT
            '{policy.policy_name}' AS policy_name,
            {policy.rank_min} AS rank_min,
            {policy.rank_max} AS rank_max,
            {policy.btc_prior_min} AS btc_prior_min,
            {policy.btc_prior_max} AS btc_prior_max,
            {policy.max_selection_score_exclusive} AS selection_score_lt,
            COUNT(*) AS rows_total,
            COUNT(DISTINCT symbol) AS symbol_count,
            COUNT(DISTINCT DATE(replay_asof_ts_utc)) AS day_count,

            COUNT(net_return_4h) AS rows_4h,
            AVG(net_return_4h) AS avg_net_4h,
            AVG(gross_return_4h) AS avg_gross_4h,
            AVG(net_return_4h > 0) AS winrate_4h,
            MIN(net_return_4h) AS worst_net_4h,
            MAX(net_return_4h) AS best_net_4h,

            COUNT(net_return_24h) AS rows_24h,
            AVG(net_return_24h) AS avg_net_24h,
            AVG(gross_return_24h) AS avg_gross_24h,
            AVG(net_return_24h > 0) AS winrate_24h,
            MIN(net_return_24h) AS worst_net_24h,
            MAX(net_return_24h) AS best_net_24h
        FROM {safe_eval_table}
        WHERE {full_where_sql}
        """,
        time_params,
    )

    by_day = fetch_rows(
        f"""
        SELECT
            DATE(replay_asof_ts_utc) AS replay_day,
            COUNT(*) AS rows_total,

            COUNT(net_return_4h) AS rows_4h,
            AVG(net_return_4h) AS avg_net_4h,
            AVG(net_return_4h > 0) AS winrate_4h,

            COUNT(net_return_24h) AS rows_24h,
            AVG(net_return_24h) AS avg_net_24h,
            AVG(net_return_24h > 0) AS winrate_24h,
            MIN(net_return_24h) AS worst_net_24h,
            MAX(net_return_24h) AS best_net_24h
        FROM {safe_eval_table}
        WHERE {full_where_sql}
        GROUP BY
            DATE(replay_asof_ts_utc)
        ORDER BY
            replay_day
        """,
        time_params,
    )

    by_symbol = fetch_rows(
        f"""
        SELECT
            symbol,
            COUNT(*) AS rows_total,

            COUNT(net_return_4h) AS rows_4h,
            AVG(net_return_4h) AS avg_net_4h,
            AVG(net_return_4h > 0) AS winrate_4h,

            COUNT(net_return_24h) AS rows_24h,
            AVG(net_return_24h) AS avg_net_24h,
            AVG(net_return_24h > 0) AS winrate_24h,
            MIN(net_return_24h) AS worst_net_24h,
            MAX(net_return_24h) AS best_net_24h
        FROM {safe_eval_table}
        WHERE {full_where_sql}
        GROUP BY
            symbol
        ORDER BY
            rows_24h DESC,
            avg_net_24h DESC
        """,
        time_params,
    )

    trades = fetch_rows(
        f"""
        SELECT
            replay_asof_ts_utc,
            symbol,
            selection_state,
            selection_bias,
            selection_score,
            priority_rank,
            btc_prior_24h,
            rotation_bucket,
            classification_code,
            sleeve_fit_code,
            net_return_4h,
            net_return_24h
        FROM {safe_eval_table}
        WHERE {full_where_sql}
        ORDER BY
            replay_asof_ts_utc,
            symbol
        """,
        time_params,
    )

    return {
        "summary": summary,
        "by_day": by_day,
        "by_symbol": by_symbol,
        "trades": trades,
    }


def main() -> int:
    args = parse_args()

    result = evaluate_policy(
        eval_table=str(args.eval_table),
        policy_name=str(args.policy),
        from_ts=None if args.from_ts is None else str(args.from_ts),
        to_ts=None if args.to_ts is None else str(args.to_ts),
    )

    if args.output == "json":
        if not args.show_trades:
            result = {k: v for k, v in result.items() if k != "trades"}
        print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    _print_table("SUMMARY", result["summary"])
    _print_table("BY DAY", result["by_day"])
    _print_table("BY SYMBOL", result["by_symbol"])

    if args.show_trades:
        _print_table("TRADES", result["trades"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
