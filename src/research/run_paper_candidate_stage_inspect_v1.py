from __future__ import annotations

"""
Synth v2 - Paper Candidate Stage Inspector V1.

LAYER:
research / paper-candidate staging inspection

BOUNDARY:
Allowed:
- read validated paper-candidate staging rows
- summarize batch, policy, symbol, and status coverage
- inspect staged market-only research candidates
- verify staging table does not expose account/execution fields

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions
- decision_gate writes
- execution_intent writes
- execution_plan writes
- database writes

Purpose:
Provide a read-only kennel inspection for staged paper-candidate signals.
This runner is a preflight tool, not a decision adapter.
"""

import argparse
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_TABLE = "research_paper_candidate_signal"
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

FORBIDDEN_COLUMNS = frozenset(
    {
        "account_id",
        "balance",
        "cash_balance",
        "available_balance",
        "position_id",
        "position_qty",
        "open_order_id",
        "order_id",
        "execution_plan_id",
        "execution_intent_id",
        "broker_order_id",
    }
)



ALLOWED_EXECUTION_REGIME_LABELS = frozenset(
    {
        "TREND_UP",
        "RANGE",
        "TREND_DOWN",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect staged paper-candidate research rows without writes."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--signal-status", default="VALIDATED")
    parser.add_argument("--policy-name", default=None)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    return str(value)


def fetch_columns(*, database: str, table_name: str) -> list[str]:
    safe_table = validate_table_name(table_name)
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM {safe_table}")
            rows = cur.fetchall() or []
    finally:
        conn.close()
    return [str(row["Field"]) for row in rows]


def build_filters(args: argparse.Namespace) -> tuple[str, list[Any]]:
    filters = []
    params: list[Any] = []

    if args.signal_status:
        filters.append("signal_status = %s")
        params.append(args.signal_status)

    if args.policy_name:
        filters.append("policy_name = %s")
        params.append(args.policy_name)

    if args.batch_id:
        filters.append("load_batch_id = %s")
        params.append(args.batch_id)

    return (" AND " + " AND ".join(filters)) if filters else "", params


def fetch_summary(*, args: argparse.Namespace) -> dict[str, Any]:
    safe_table = validate_table_name(args.table)
    where_sql, params = build_filters(args)
    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT
                    COUNT(*) AS rows_total,
                    COUNT(DISTINCT symbol) AS symbols,
                    COUNT(DISTINCT policy_name) AS policies,
                    COUNT(DISTINCT load_batch_id) AS batches,
                    MIN(asof_ts_utc) AS first_ts,
                    MAX(asof_ts_utc) AS last_ts,
                    ROUND(AVG(simulated_net_return), 8) AS avg_simulated_net_return,
                    ROUND(AVG(simulated_net_return > 0), 4) AS winrate,
                    MIN(simulated_net_return) AS worst_simulated_net_return,
                    MAX(simulated_net_return) AS best_simulated_net_return
                FROM {safe_table}
                WHERE 1=1
                {where_sql}
                '''
                , params,
            )
            summary = cur.fetchone() or {}

            cur.execute(
                f'''
                SELECT load_batch_id, signal_status, policy_name, policy_version,
                       COUNT(*) AS rows_total, COUNT(DISTINCT symbol) AS symbols,
                       MIN(asof_ts_utc) AS first_ts, MAX(asof_ts_utc) AS last_ts
                FROM {safe_table}
                WHERE 1=1
                {where_sql}
                GROUP BY load_batch_id, signal_status, policy_name, policy_version
                ORDER BY MAX(created_ts_utc) DESC, rows_total DESC
                LIMIT 20
                '''
                , params,
            )
            batches = cur.fetchall() or []

            cur.execute(
                f'''
                SELECT symbol, COUNT(*) AS rows_total,
                       ROUND(AVG(simulated_net_return), 8) AS avg_simulated_net_return,
                       ROUND(AVG(simulated_net_return > 0), 4) AS winrate,
                       MIN(simulated_net_return) AS worst_simulated_net_return,
                       MAX(simulated_net_return) AS best_simulated_net_return
                FROM {safe_table}
                WHERE 1=1
                {where_sql}
                GROUP BY symbol
                ORDER BY rows_total DESC, avg_simulated_net_return DESC
                LIMIT 30
                '''
                , params,
            )
            symbols = cur.fetchall() or []

            cur.execute(
                f'''
                SELECT load_batch_id, signal_status, policy_name, policy_version,
                       candidate_state, asset_id, symbol, venue, asof_ts_utc,
                       selection_state, priority_rank, selection_score, btc_prior_24h,
                       rotation_bucket, classification_code, sleeve_fit_code,
                       simulated_horizon_hours, simulated_net_return,
                       source_table, source_replay_id
                FROM {safe_table}
                WHERE 1=1
                {where_sql}
                ORDER BY asof_ts_utc, priority_rank, symbol
                LIMIT %s
                '''
                , [*params, args.limit],
            )
            samples = cur.fetchall() or []

            cur.execute(
                f'''
                SELECT
                    COALESCE(execution_regime_label, '<NULL>') AS execution_regime_label,
                    COUNT(*) AS rows_total
                FROM {safe_table}
                WHERE 1=1
                {where_sql}
                GROUP BY COALESCE(execution_regime_label, '<NULL>')
                ORDER BY rows_total DESC, execution_regime_label
                '''
                , params,
            )
            execution_regime_counts = cur.fetchall() or []

            cur.execute(
                f'''
                SELECT
                    SUM(execution_regime_label IS NULL) AS execution_regime_null_rows,
                    SUM(
                        execution_regime_label IS NOT NULL
                        AND execution_regime_label NOT IN ('TREND_UP', 'RANGE', 'TREND_DOWN')
                    ) AS execution_regime_invalid_rows
                FROM {safe_table}
                WHERE 1=1
                {where_sql}
                '''
                , params,
            )
            execution_regime_quality = cur.fetchone() or {}
    finally:
        conn.close()

    columns = fetch_columns(database=args.database, table_name=args.table)
    forbidden_present = sorted(set(columns).intersection(FORBIDDEN_COLUMNS))

    return {
        "database": args.database,
        "table": args.table,
        "filters": {
            "signal_status": args.signal_status,
            "policy_name": args.policy_name,
            "batch_id": args.batch_id,
        },
        "schema_forbidden_columns_present": forbidden_present,
        "summary": summary,
        "batches": batches,
        "symbols": symbols,
        "execution_regime_quality": execution_regime_quality,
        "execution_regime_counts": execution_regime_counts,
        "samples": samples,
    }


def print_table(payload: dict[str, Any]) -> None:
    print("Paper candidate stage inspector")
    print(f"database: {payload['database']}")
    print(f"table: {payload['table']}")
    print(f"filters: {payload['filters']}")

    forbidden = payload['schema_forbidden_columns_present']
    if forbidden:
        print(f"schema_forbidden_columns_present: {forbidden}")
    else:
        print("schema_forbidden_columns_present: none")

    print()
    print("--- summary ---")
    for key, value in payload['summary'].items():
        print(f'{key}: {json_default(value)}')

    print()
    print("--- execution regime health ---")
    for key, value in payload['execution_regime_quality'].items():
        print(f'{key}: {json_default(value)}')

    print()
    print("--- execution regime counts ---")
    for row in payload['execution_regime_counts']:
        print(row)

    print()
    print("--- batches ---")
    for row in payload['batches']:
        print(row)

    print()
    print("--- symbols ---")
    for row in payload['symbols']:
        print(row)

    print()
    print("--- samples ---")
    for row in payload['samples']:
        print(row)


def main() -> int:
    args = parse_args()
    payload = fetch_summary(args=args)

    if payload['schema_forbidden_columns_present']:
        if args.output == 'json':
            print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
        else:
            print_table(payload)
        return 2

    if args.output == 'json':
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
