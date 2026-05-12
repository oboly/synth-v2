from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "breath_curve_research_policy_report_v1"
VERSION = "0.1"


def fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return ""

    if isinstance(value, Decimal):
        dec = value
    else:
        dec = Decimal(str(value))

    q = Decimal("1").scaleb(-places)
    text = format(dec.quantize(q), "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def fetch_run_summary(conn: Any, limit: int) -> list[dict[str, Any]]:
    sql = """
    SELECT
        r.research_breath_curve_policy_run_id AS run_id,
        r.run_ts_utc,
        r.policy_name,
        r.policy_version,
        r.checkpoint_set,
        r.min_partial_score,
        r.tp1_weight,
        r.tp2_weight,
        r.cost_bps,
        r.require_offset_match,
        r.rows_input,
        r.rows_written,
        COUNT(x.research_breath_curve_policy_result_id) AS result_rows,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_return_pct,
        ROUND(
            SUM(CASE WHEN x.policy_return_pct > 0 THEN 1 ELSE 0 END)
            / NULLIF(COUNT(x.research_breath_curve_policy_result_id), 0)
            * 100,
            2
        ) AS positive_rate_pct,
        ROUND(MAX(x.policy_return_pct), 4) AS best_return_pct,
        ROUND(MIN(x.policy_return_pct), 4) AS worst_return_pct
    FROM research_breath_curve_policy_run r
    LEFT JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    GROUP BY
        r.research_breath_curve_policy_run_id,
        r.run_ts_utc,
        r.policy_name,
        r.policy_version,
        r.checkpoint_set,
        r.min_partial_score,
        r.tp1_weight,
        r.tp2_weight,
        r.cost_bps,
        r.require_offset_match,
        r.rows_input,
        r.rows_written
    ORDER BY r.research_breath_curve_policy_run_id DESC
    LIMIT %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def fetch_orphan_runs(conn: Any) -> list[dict[str, Any]]:
    sql = """
    SELECT
        r.research_breath_curve_policy_run_id AS run_id,
        r.run_ts_utc,
        r.policy_name,
        r.checkpoint_set,
        r.rows_input,
        r.rows_written
    FROM research_breath_curve_policy_run r
    LEFT JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    GROUP BY
        r.research_breath_curve_policy_run_id,
        r.run_ts_utc,
        r.policy_name,
        r.checkpoint_set,
        r.rows_input,
        r.rows_written
    HAVING COUNT(x.research_breath_curve_policy_result_id) = 0
    ORDER BY r.research_breath_curve_policy_run_id DESC
    LIMIT 20
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def fetch_latest_symbol_summary(conn: Any) -> list[dict[str, Any]]:
    sql = """
    SELECT
        r.research_breath_curve_policy_run_id AS run_id,
        r.policy_name,
        r.checkpoint_set,
        x.symbol,
        COUNT(*) AS result_rows,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_return_pct,
        ROUND(
            SUM(CASE WHEN x.policy_return_pct > 0 THEN 1 ELSE 0 END)
            / COUNT(*)
            * 100,
            2
        ) AS positive_rate_pct,
        ROUND(MAX(x.policy_return_pct), 4) AS best_return_pct,
        ROUND(MIN(x.policy_return_pct), 4) AS worst_return_pct
    FROM research_breath_curve_policy_run r
    JOIN (
        SELECT
            policy_name,
            MAX(research_breath_curve_policy_run_id) AS latest_run_id
        FROM research_breath_curve_policy_run
        GROUP BY policy_name
    ) latest
      ON latest.latest_run_id = r.research_breath_curve_policy_run_id
    JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    GROUP BY
        r.research_breath_curve_policy_run_id,
        r.policy_name,
        r.checkpoint_set,
        x.symbol
    ORDER BY
        r.policy_name,
        avg_return_pct DESC,
        x.symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def fetch_checkpoint_summary(conn: Any) -> list[dict[str, Any]]:
    sql = """
    SELECT
        r.policy_name,
        r.checkpoint_set,
        COUNT(*) AS result_rows,
        ROUND(AVG(x.policy_return_pct), 4) AS avg_return_pct,
        ROUND(
            SUM(CASE WHEN x.policy_return_pct > 0 THEN 1 ELSE 0 END)
            / COUNT(*)
            * 100,
            2
        ) AS positive_rate_pct,
        ROUND(MAX(x.policy_return_pct), 4) AS best_return_pct,
        ROUND(MIN(x.policy_return_pct), 4) AS worst_return_pct
    FROM research_breath_curve_policy_run r
    JOIN (
        SELECT
            policy_name,
            MAX(research_breath_curve_policy_run_id) AS latest_run_id
        FROM research_breath_curve_policy_run
        GROUP BY policy_name
    ) latest
      ON latest.latest_run_id = r.research_breath_curve_policy_run_id
    JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    GROUP BY
        r.policy_name,
        r.checkpoint_set
    ORDER BY
        avg_return_pct DESC,
        r.policy_name
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()

    try:
        run_rows = fetch_run_summary(conn, args.limit)
        orphan_rows = fetch_orphan_runs(conn)
        checkpoint_rows = fetch_checkpoint_summary(conn)
        symbol_rows = fetch_latest_symbol_summary(conn)
    finally:
        conn.close()

    print(f"report={REPORT_NAME} version={VERSION}")
    print("scope=research-only market-only account-agnostic")
    print("broker_calls=0 broker_writes=0 order_submission=0 decision_gate=none execution_planner=none executor=none")

    print()
    print("--- policy runs ---")
    if run_rows:
        print_table(
            [
                "run_id",
                "policy_name",
                "checkpoint",
                "rows",
                "avg",
                "positive",
                "best",
                "worst",
                "cost_bps",
                "offset_match",
            ],
            [
                [
                    str(row["run_id"]),
                    str(row["policy_name"]),
                    str(row["checkpoint_set"]),
                    str(row["result_rows"]),
                    fmt(row["avg_return_pct"]),
                    fmt(row["positive_rate_pct"], 2),
                    fmt(row["best_return_pct"]),
                    fmt(row["worst_return_pct"]),
                    fmt(row["cost_bps"], 2),
                    str(int(row["require_offset_match"])),
                ]
                for row in run_rows
            ],
        )
    else:
        print("(no policy runs)")

    print()
    print("--- orphan run check ---")
    if orphan_rows:
        print_table(
            ["run_id", "policy_name", "checkpoint", "rows_input", "rows_written"],
            [
                [
                    str(row["run_id"]),
                    str(row["policy_name"]),
                    str(row["checkpoint_set"]),
                    str(row["rows_input"]),
                    str(row["rows_written"]),
                ]
                for row in orphan_rows
            ],
        )
    else:
        print("OK: no orphan runs")

    print()
    print("--- latest checkpoint comparison ---")
    if checkpoint_rows:
        print_table(
            ["policy_name", "checkpoint", "rows", "avg", "positive", "best", "worst"],
            [
                [
                    str(row["policy_name"]),
                    str(row["checkpoint_set"]),
                    str(row["result_rows"]),
                    fmt(row["avg_return_pct"]),
                    fmt(row["positive_rate_pct"], 2),
                    fmt(row["best_return_pct"]),
                    fmt(row["worst_return_pct"]),
                ]
                for row in checkpoint_rows
            ],
        )
    else:
        print("(no checkpoint rows)")

    print()
    print("--- latest by-symbol summary ---")
    if symbol_rows:
        print_table(
            ["policy_name", "symbol", "rows", "avg", "positive", "best", "worst"],
            [
                [
                    str(row["policy_name"]),
                    str(row["symbol"]),
                    str(row["result_rows"]),
                    fmt(row["avg_return_pct"]),
                    fmt(row["positive_rate_pct"], 2),
                    fmt(row["best_return_pct"]),
                    fmt(row["worst_return_pct"]),
                ]
                for row in symbol_rows
            ],
        )
    else:
        print("(no symbol rows)")

    print()
    print(
        f"[DONE] runs={len(run_rows)} orphan_runs={len(orphan_rows)} "
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0"
    )

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only report for breath curve research policy DB backtests."
    )
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
