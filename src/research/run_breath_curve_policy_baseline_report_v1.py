from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "breath_curve_policy_baseline_report_v1"
VERSION = "0.1"


def fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return ""

    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal("1").scaleb(-places)
    text = format(dec.quantize(q), "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(no rows)")
        return

    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def fetch_latest_run_ids(conn: Any, limit_runs: int) -> list[int]:
    sql = """
    SELECT research_breath_curve_policy_run_id
    FROM research_breath_curve_policy_run
    ORDER BY research_breath_curve_policy_run_id DESC
    LIMIT %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (limit_runs,))
        return [int(row["research_breath_curve_policy_run_id"]) for row in cur.fetchall()]


def in_clause(values: list[int]) -> tuple[str, list[int]]:
    if not values:
        return "(NULL)", []
    return "(" + ",".join(["%s"] * len(values)) + ")", values


def fetch_policy_vs_baselines(conn: Any, run_ids: list[int]) -> list[dict[str, Any]]:
    clause, params = in_clause(run_ids)

    sql = f"""
    SELECT
        r.policy_name,
        r.checkpoint_set,
        r.require_offset_match,
        COUNT(*) AS rows_n,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_policy_return_pct,
        ROUND(AVG(x.return_to_1000_pct), 4) AS avg_hold_to_1000_pct,
        ROUND(AVG(x.return_to_1272_pct), 4) AS avg_hold_to_1272_pct,
        ROUND(AVG(x.policy_return_pct - x.return_to_1000_pct), 4) AS avg_policy_minus_1000_pct,
        ROUND(AVG(x.policy_return_pct - x.return_to_1272_pct), 4) AS avg_policy_minus_1272_pct,
        ROUND(SUM(CASE WHEN x.policy_return_pct > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS policy_positive_rate_pct,
        ROUND(
            SUM(CASE WHEN x.return_to_1000_pct > 0 THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN x.return_to_1000_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
            * 100,
            2
        ) AS hold_1000_positive_rate_pct,
        ROUND(
            SUM(CASE WHEN x.return_to_1272_pct > 0 THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN x.return_to_1272_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
            * 100,
            2
        ) AS hold_1272_positive_rate_pct,
        ROUND(MAX(x.policy_return_pct), 4) AS best_policy_return_pct,
        ROUND(MIN(x.policy_return_pct), 4) AS worst_policy_return_pct
    FROM research_breath_curve_policy_run r
    JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    WHERE r.research_breath_curve_policy_run_id IN {clause}
    GROUP BY
        r.policy_name,
        r.checkpoint_set,
        r.require_offset_match
    ORDER BY
        avg_policy_return_pct DESC,
        r.policy_name,
        r.checkpoint_set
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_checkpoint_baseline(conn: Any, run_ids: list[int]) -> list[dict[str, Any]]:
    clause, params = in_clause(run_ids)

    sql = f"""
    SELECT
        x.checkpoint_ratio,
        COUNT(*) AS rows_n,
        ROUND(AVG(x.selected_partial_score), 4) AS avg_partial_score,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_policy_return_pct,
        ROUND(AVG(x.return_to_1000_pct), 4) AS avg_hold_to_1000_pct,
        ROUND(AVG(x.return_to_1272_pct), 4) AS avg_hold_to_1272_pct,
        ROUND(AVG(x.policy_return_pct - x.return_to_1000_pct), 4) AS avg_policy_minus_1000_pct,
        ROUND(AVG(x.policy_return_pct - x.return_to_1272_pct), 4) AS avg_policy_minus_1272_pct,
        ROUND(SUM(CASE WHEN x.policy_return_pct > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS policy_positive_rate_pct
    FROM research_breath_curve_policy_result x
    WHERE x.research_breath_curve_policy_run_id IN {clause}
    GROUP BY x.checkpoint_ratio
    ORDER BY x.checkpoint_ratio
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_offset_match_baseline(conn: Any, run_ids: list[int]) -> list[dict[str, Any]]:
    clause, params = in_clause(run_ids)

    sql = f"""
    SELECT
        x.offset_matches_best_full,
        COUNT(*) AS rows_n,
        ROUND(AVG(x.selected_partial_score), 4) AS avg_partial_score,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_policy_return_pct,
        ROUND(AVG(x.return_to_1000_pct), 4) AS avg_hold_to_1000_pct,
        ROUND(AVG(x.return_to_1272_pct), 4) AS avg_hold_to_1272_pct,
        ROUND(SUM(CASE WHEN x.policy_return_pct > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS policy_positive_rate_pct,
        ROUND(MAX(x.policy_return_pct), 4) AS best_policy_return_pct,
        ROUND(MIN(x.policy_return_pct), 4) AS worst_policy_return_pct
    FROM research_breath_curve_policy_result x
    WHERE x.research_breath_curve_policy_run_id IN {clause}
    GROUP BY x.offset_matches_best_full
    ORDER BY x.offset_matches_best_full DESC
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_symbol_baseline(conn: Any, run_ids: list[int]) -> list[dict[str, Any]]:
    clause, params = in_clause(run_ids)

    sql = f"""
    SELECT
        x.symbol,
        COUNT(*) AS rows_n,
        ROUND(AVG(x.selected_partial_score), 4) AS avg_partial_score,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_policy_return_pct,
        ROUND(AVG(x.return_to_1000_pct), 4) AS avg_hold_to_1000_pct,
        ROUND(AVG(x.return_to_1272_pct), 4) AS avg_hold_to_1272_pct,
        ROUND(AVG(x.policy_return_pct - x.return_to_1000_pct), 4) AS avg_policy_minus_1000_pct,
        ROUND(AVG(x.policy_return_pct - x.return_to_1272_pct), 4) AS avg_policy_minus_1272_pct,
        ROUND(SUM(CASE WHEN x.policy_return_pct > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS policy_positive_rate_pct
    FROM research_breath_curve_policy_result x
    WHERE x.research_breath_curve_policy_run_id IN {clause}
    GROUP BY x.symbol
    ORDER BY avg_policy_return_pct DESC, x.symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_run_health(conn: Any, run_ids: list[int]) -> list[dict[str, Any]]:
    clause, params = in_clause(run_ids)

    sql = f"""
    SELECT
        r.research_breath_curve_policy_run_id AS run_id,
        r.policy_name,
        r.checkpoint_set,
        r.require_offset_match,
        r.rows_input,
        r.rows_written,
        COUNT(x.research_breath_curve_policy_result_id) AS actual_rows,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_policy_return_pct
    FROM research_breath_curve_policy_run r
    LEFT JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    WHERE r.research_breath_curve_policy_run_id IN {clause}
    GROUP BY
        r.research_breath_curve_policy_run_id,
        r.policy_name,
        r.checkpoint_set,
        r.require_offset_match,
        r.rows_input,
        r.rows_written
    ORDER BY r.research_breath_curve_policy_run_id DESC
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()

    try:
        run_ids = fetch_latest_run_ids(conn, args.limit_runs)
        run_health = fetch_run_health(conn, run_ids)
        policy_baselines = fetch_policy_vs_baselines(conn, run_ids)
        checkpoint_baselines = fetch_checkpoint_baseline(conn, run_ids)
        offset_baselines = fetch_offset_match_baseline(conn, run_ids)
        symbol_baselines = fetch_symbol_baseline(conn, run_ids)
    finally:
        conn.close()

    print(f"report={REPORT_NAME} version={VERSION}")
    print("scope=research-only market-only account-agnostic")
    print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
    print("selection_engine=none decision_gate=none execution_planner=none executor=none")
    print(f"latest_run_count={len(run_ids)}")
    print(f"run_ids={','.join(str(x) for x in run_ids)}")

    print()
    print("--- run health ---")
    print_table(
        ["run_id", "policy", "checkpoint", "offset_req", "input", "written", "actual", "avg_policy"],
        [
            [
                str(row["run_id"]),
                str(row["policy_name"]),
                str(row["checkpoint_set"]),
                str(int(row["require_offset_match"])),
                str(row["rows_input"]),
                str(row["rows_written"]),
                str(row["actual_rows"]),
                fmt(row["avg_policy_return_pct"]),
            ]
            for row in run_health
        ],
    )

    print()
    print("--- policy vs same-window baselines ---")
    print_table(
        [
            "policy",
            "checkpoint",
            "offset_req",
            "rows",
            "policy_avg",
            "hold_1000",
            "hold_1272",
            "pol-1000",
            "pol-1272",
            "pol_pos",
            "1000_pos",
            "1272_pos",
            "best",
            "worst",
        ],
        [
            [
                str(row["policy_name"]),
                str(row["checkpoint_set"]),
                str(int(row["require_offset_match"])),
                str(row["rows_n"]),
                fmt(row["avg_policy_return_pct"]),
                fmt(row["avg_hold_to_1000_pct"]),
                fmt(row["avg_hold_to_1272_pct"]),
                fmt(row["avg_policy_minus_1000_pct"]),
                fmt(row["avg_policy_minus_1272_pct"]),
                fmt(row["policy_positive_rate_pct"], 2),
                fmt(row["hold_1000_positive_rate_pct"], 2),
                fmt(row["hold_1272_positive_rate_pct"], 2),
                fmt(row["best_policy_return_pct"]),
                fmt(row["worst_policy_return_pct"]),
            ]
            for row in policy_baselines
        ],
    )

    print()
    print("--- checkpoint baseline: 0.618 vs 0.786 etc ---")
    print_table(
        [
            "checkpoint",
            "rows",
            "partial",
            "policy_avg",
            "hold_1000",
            "hold_1272",
            "pol-1000",
            "pol-1272",
            "pol_pos",
        ],
        [
            [
                fmt(row["checkpoint_ratio"], 3),
                str(row["rows_n"]),
                fmt(row["avg_partial_score"]),
                fmt(row["avg_policy_return_pct"]),
                fmt(row["avg_hold_to_1000_pct"]),
                fmt(row["avg_hold_to_1272_pct"]),
                fmt(row["avg_policy_minus_1000_pct"]),
                fmt(row["avg_policy_minus_1272_pct"]),
                fmt(row["policy_positive_rate_pct"], 2),
            ]
            for row in checkpoint_baselines
        ],
    )

    print()
    print("--- offset-match baseline ---")
    print_table(
        [
            "offset_match",
            "rows",
            "partial",
            "policy_avg",
            "hold_1000",
            "hold_1272",
            "pol_pos",
            "best",
            "worst",
        ],
        [
            [
                str(int(row["offset_matches_best_full"])),
                str(row["rows_n"]),
                fmt(row["avg_partial_score"]),
                fmt(row["avg_policy_return_pct"]),
                fmt(row["avg_hold_to_1000_pct"]),
                fmt(row["avg_hold_to_1272_pct"]),
                fmt(row["policy_positive_rate_pct"], 2),
                fmt(row["best_policy_return_pct"]),
                fmt(row["worst_policy_return_pct"]),
            ]
            for row in offset_baselines
        ],
    )

    print()
    print("--- symbol baseline buckets ---")
    print_table(
        [
            "symbol",
            "rows",
            "partial",
            "policy_avg",
            "hold_1000",
            "hold_1272",
            "pol-1000",
            "pol-1272",
            "pol_pos",
        ],
        [
            [
                str(row["symbol"]),
                str(row["rows_n"]),
                fmt(row["avg_partial_score"]),
                fmt(row["avg_policy_return_pct"]),
                fmt(row["avg_hold_to_1000_pct"]),
                fmt(row["avg_hold_to_1272_pct"]),
                fmt(row["avg_policy_minus_1000_pct"]),
                fmt(row["avg_policy_minus_1272_pct"]),
                fmt(row["policy_positive_rate_pct"], 2),
            ]
            for row in symbol_baselines
        ],
    )

    print()
    print("random_anchor_baseline=NOT_IMPLEMENTED_IN_V1_REQUIRES_CANDLE_RESAMPLING")
    print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Breath Curve policy baseline comparison report."
    )
    parser.add_argument("--limit-runs", type=int, default=20)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
