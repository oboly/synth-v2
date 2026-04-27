from __future__ import annotations

"""
Synth v2 - Named Replay Policy V1.

LAYER:
research/backtest evaluation

BOUNDARY:
Allowed:
- read synth_bt replay eval table
- evaluate named market-only research policies
- persist policy-level research evaluation summaries into synth_bt

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
RESULT_TABLE = "bt_named_policy_eval_result_v1"

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
    parser.add_argument("--result-set-name", default="manual")
    parser.add_argument("--write-db", action="store_true")
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


def ensure_result_table() -> None:
    sql = f"""
    CREATE TABLE IF NOT EXISTS {RESULT_TABLE} (
        named_policy_eval_result_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

        result_set_name VARCHAR(100) NOT NULL,
        policy_name VARCHAR(100) NOT NULL,
        eval_table VARCHAR(128) NOT NULL,

        from_ts_utc DATETIME(6) DEFAULT NULL,
        to_ts_utc DATETIME(6) DEFAULT NULL,

        rank_min INT NOT NULL,
        rank_max INT NOT NULL,
        btc_prior_min DECIMAL(18,8) NOT NULL,
        btc_prior_max DECIMAL(18,8) NOT NULL,
        selection_score_lt DECIMAL(18,8) NOT NULL,
        exclude_weak_symbols TINYINT(1) NOT NULL,

        rotation_bucket VARCHAR(64) NOT NULL,
        classification_code VARCHAR(64) NOT NULL,
        sleeve_fit_code VARCHAR(64) NOT NULL,

        rows_total INT NOT NULL,
        symbol_count INT NOT NULL,
        day_count INT NOT NULL,

        rows_4h INT NOT NULL,
        avg_net_4h DECIMAL(28,12) DEFAULT NULL,
        avg_gross_4h DECIMAL(28,12) DEFAULT NULL,
        winrate_4h DECIMAL(18,8) DEFAULT NULL,
        worst_net_4h DECIMAL(28,12) DEFAULT NULL,
        best_net_4h DECIMAL(28,12) DEFAULT NULL,

        rows_24h INT NOT NULL,
        avg_net_24h DECIMAL(28,12) DEFAULT NULL,
        avg_gross_24h DECIMAL(28,12) DEFAULT NULL,
        winrate_24h DECIMAL(18,8) DEFAULT NULL,
        worst_net_24h DECIMAL(28,12) DEFAULT NULL,
        best_net_24h DECIMAL(28,12) DEFAULT NULL,

        created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

        PRIMARY KEY (named_policy_eval_result_id),
        KEY ix_named_policy_eval_policy_window (
            policy_name,
            from_ts_utc,
            to_ts_utc,
            created_ts_utc
        ),
        KEY ix_named_policy_eval_result_set (
            result_set_name,
            created_ts_utc
        ),
        KEY ix_named_policy_eval_24h (
            avg_net_24h,
            winrate_24h,
            rows_24h
        )
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_result_summary(
    *,
    result_set_name: str,
    eval_table: str,
    policy: NamedPolicy,
    from_ts: str | None,
    to_ts: str | None,
    summary_row: dict[str, Any],
) -> int:
    ensure_result_table()

    sql = f"""
    INSERT INTO {RESULT_TABLE} (
        result_set_name,
        policy_name,
        eval_table,
        from_ts_utc,
        to_ts_utc,
        rank_min,
        rank_max,
        btc_prior_min,
        btc_prior_max,
        selection_score_lt,
        exclude_weak_symbols,
        rotation_bucket,
        classification_code,
        sleeve_fit_code,
        rows_total,
        symbol_count,
        day_count,
        rows_4h,
        avg_net_4h,
        avg_gross_4h,
        winrate_4h,
        worst_net_4h,
        best_net_4h,
        rows_24h,
        avg_net_24h,
        avg_gross_24h,
        winrate_24h,
        worst_net_24h,
        best_net_24h
    ) VALUES (
        %(result_set_name)s,
        %(policy_name)s,
        %(eval_table)s,
        %(from_ts_utc)s,
        %(to_ts_utc)s,
        %(rank_min)s,
        %(rank_max)s,
        %(btc_prior_min)s,
        %(btc_prior_max)s,
        %(selection_score_lt)s,
        %(exclude_weak_symbols)s,
        %(rotation_bucket)s,
        %(classification_code)s,
        %(sleeve_fit_code)s,
        %(rows_total)s,
        %(symbol_count)s,
        %(day_count)s,
        %(rows_4h)s,
        %(avg_net_4h)s,
        %(avg_gross_4h)s,
        %(winrate_4h)s,
        %(worst_net_4h)s,
        %(best_net_4h)s,
        %(rows_24h)s,
        %(avg_net_24h)s,
        %(avg_gross_24h)s,
        %(winrate_24h)s,
        %(worst_net_24h)s,
        %(best_net_24h)s
    )
    """

    params = {
        "result_set_name": result_set_name,
        "policy_name": policy.policy_name,
        "eval_table": eval_table,
        "from_ts_utc": from_ts,
        "to_ts_utc": to_ts,
        "rank_min": policy.rank_min,
        "rank_max": policy.rank_max,
        "btc_prior_min": policy.btc_prior_min,
        "btc_prior_max": policy.btc_prior_max,
        "selection_score_lt": policy.max_selection_score_exclusive,
        "exclude_weak_symbols": int(policy.exclude_weak_symbols),
        "rotation_bucket": policy.rotation_bucket,
        "classification_code": policy.classification_code,
        "sleeve_fit_code": policy.sleeve_fit_code,
        "rows_total": summary_row["rows_total"],
        "symbol_count": summary_row["symbol_count"],
        "day_count": summary_row["day_count"],
        "rows_4h": summary_row["rows_4h"],
        "avg_net_4h": summary_row["avg_net_4h"],
        "avg_gross_4h": summary_row["avg_gross_4h"],
        "winrate_4h": summary_row["winrate_4h"],
        "worst_net_4h": summary_row["worst_net_4h"],
        "best_net_4h": summary_row["best_net_4h"],
        "rows_24h": summary_row["rows_24h"],
        "avg_net_24h": summary_row["avg_net_24h"],
        "avg_gross_24h": summary_row["avg_gross_24h"],
        "winrate_24h": summary_row["winrate_24h"],
        "worst_net_24h": summary_row["worst_net_24h"],
        "best_net_24h": summary_row["best_net_24h"],
    }

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result_id = int(cur.lastrowid)
        conn.commit()
        return result_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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

    eval_table = _validate_table_name(str(args.eval_table))
    policy_name = str(args.policy)
    from_ts = None if args.from_ts is None else str(args.from_ts)
    to_ts = None if args.to_ts is None else str(args.to_ts)

    result = evaluate_policy(
        eval_table=eval_table,
        policy_name=policy_name,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    written_result_id: int | None = None

    if args.write_db:
        if not result["summary"]:
            raise RuntimeError("No summary row produced; refusing to write empty result")

        policy = _resolve_policy(policy_name)
        written_result_id = write_result_summary(
            result_set_name=str(args.result_set_name),
            eval_table=eval_table,
            policy=policy,
            from_ts=from_ts,
            to_ts=to_ts,
            summary_row=result["summary"][0],
        )

        result["db_write"] = [
            {
                "named_policy_eval_result_id": written_result_id,
                "result_set_name": str(args.result_set_name),
                "policy_name": policy.policy_name,
            }
        ]

    if args.output == "json":
        if not args.show_trades:
            result = {k: v for k, v in result.items() if k != "trades"}
        print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    _print_table("SUMMARY", result["summary"])
    _print_table("BY DAY", result["by_day"])
    _print_table("BY SYMBOL", result["by_symbol"])

    if written_result_id is not None:
        _print_table("DB WRITE", result["db_write"])

    if args.show_trades:
        _print_table("TRADES", result["trades"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
