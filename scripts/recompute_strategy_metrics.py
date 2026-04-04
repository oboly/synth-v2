"""
SYNTH v2
Script: recompute_strategy_metrics
Purpose:
    Recompute daily sleeve/strategy metrics from trade_lot and state_transition_daily.
Usage:
    python -m scripts.recompute_strategy_metrics --date 2026-04-01
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from src.synth_sleeves.metrics import build_strategy_metrics_daily
from src.synth_sleeves.db_repository import SleeveRepository


def make_conn_params() -> dict[str, Any]:
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
    }


def fetch_rows(conn_params: dict[str, Any], sql: str, params: tuple[Any, ...]) -> list[dict]:
    with pymysql.connect(cursorclass=DictCursor, autocommit=True, charset="utf8mb4", **conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="UTC date in YYYY-MM-DD")
    args = parser.parse_args()

    metric_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    conn_params = make_conn_params()
    repo = SleeveRepository(conn_params)

    trade_sql = """
    SELECT
        DATE(close_ts_utc) AS metric_date_utc,
        sleeve_code,
        strategy_name,
        strategy_version_id,
        realized_pnl_eur,
        realized_pnl_pct,
        holding_minutes
    FROM trade_lot
    WHERE DATE(close_ts_utc) = %s
    """

    transition_sql = """
    SELECT
        metric_date_utc,
        sleeve_code,
        strategy_name,
        NULL AS strategy_version_id,
        from_state,
        to_state,
        transition_count
    FROM state_transition_daily
    WHERE metric_date_utc = %s
      AND from_state = 'PREPARE'
    """

    trade_rows = fetch_rows(conn_params, trade_sql, (metric_date,))
    transition_rows = fetch_rows(conn_params, transition_sql, (metric_date,))

    metrics = build_strategy_metrics_daily(trade_rows, transition_rows)
    for row in metrics:
        repo.insert_or_update_strategy_metrics_daily(row)

    print(f"[DONE] recomputed strategy metrics for {metric_date.isoformat()} rows={len(metrics)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
