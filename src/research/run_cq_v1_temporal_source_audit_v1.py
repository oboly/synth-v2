from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.cq_v1_temporal_source_audit_v1 import (
    SOURCE_SPECS,
    bind_params,
    overall_state,
    source_result,
)

RUNNER_NAME = "cq_v1_temporal_source_audit_v1"
DEFAULT_LOOKBACK_DAYS = 45


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded read-only audit of CQ v1 temporal source history")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _fetch_history_summary(
    cursor: Any,
    *,
    from_sql: str,
    ts_col: str,
    where_sql: str,
    params: tuple[Any, ...],
    lookback_days: int,
) -> dict[str, Any]:
    sql = f"""
        SELECT COUNT(*) AS row_count,
               COUNT(DISTINCT {ts_col}) AS distinct_ts_count,
               MIN({ts_col}) AS first_ts,
               MAX({ts_col}) AS last_ts
        FROM {from_sql}
        WHERE {where_sql}
          AND {ts_col} >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
    """
    cursor.execute(sql, params + (lookback_days,))
    row = cursor.fetchone()
    if not isinstance(row, dict):
        raise TypeError("expected dict cursor row")
    return row


def _fetch_indexes(cursor: Any, table: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT index_name, non_unique, seq_in_index, column_name
        FROM information_schema.statistics
        WHERE table_schema=DATABASE() AND table_name=%s
        ORDER BY index_name, seq_in_index
        """,
        (table,),
    )
    rows = cursor.fetchall()
    if any(not isinstance(row, dict) for row in rows):
        raise TypeError("expected dict cursor index rows")
    return [dict(row) for row in rows]


def run(args: argparse.Namespace) -> int:
    if args.lookback_days < 1 or args.lookback_days > 366:
        raise SystemExit("--lookback-days must be within 1..366")
    output_path = Path(args.output_json)
    if output_path.exists():
        raise SystemExit("output artifact already exists; use a new immutable path")

    print(
        f"STARTED runner={RUNNER_NAME} venue={args.venue} lookback_days={args.lookback_days}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 db_reads=1 db_writes=0 outcomes_read=0 "
        "model_retuning=0 production_ranking_changes=0 broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 runtime_activation=0",
        flush=True,
    )

    conn = get_db_connection()
    try:
        results: list[dict[str, Any]] = []
        with conn.cursor() as cursor:
            for spec in SOURCE_SPECS:
                params = bind_params(spec, venue=args.venue)
                summary = _fetch_history_summary(
                    cursor,
                    from_sql=spec.history_from_sql or spec.table_name,
                    ts_col=spec.timestamp_column,
                    where_sql=spec.where_sql,
                    params=params,
                    lookback_days=args.lookback_days,
                )
                indexes = _fetch_indexes(cursor, spec.table_name)
                result = source_result(
                    spec,
                    row_count=int(summary.get("row_count") or 0),
                    distinct_ts_count=int(summary.get("distinct_ts_count") or 0),
                    first_ts=summary.get("first_ts"),
                    last_ts=summary.get("last_ts"),
                    indexes=indexes,
                )
                results.append(result)
                print(
                    f"SOURCE source_id={spec.source_id} state={result['history_state']} "
                    f"rows={result['row_count']} distinct_ts={result['distinct_timestamp_count']}",
                    flush=True,
                )

        state, blockers = overall_state(results)
        payload = {
            "runner": RUNNER_NAME,
            "venue": args.venue,
            "lookback_days": args.lookback_days,
            "state": state,
            "blockers": blockers,
            "sources": results,
            "bounded_shadow_runner_historical_reuse": "DENY_CURRENT_MAX_WITHOUT_ASOF_CUTOFF",
            "ppp_history": "UNAVAILABLE_UNLESS_CANONICAL_HISTORICAL_ARTIFACT_IS_SUPPLIED",
            "outcomes_read": 0,
            "model_retuning": 0,
            "db_writes": 0,
            "production_ranking_changed": 0,
        }
        _write_json(output_path, payload)
        print(f"FINISHED runner={RUNNER_NAME} state={state} blockers={','.join(blockers) or 'none'}", flush=True)
        return 0
    finally:
        conn.close()


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
