from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


ENGINE_NAME = "asset_interval_quality_snapshot"
ENGINE_VERSION = "1.0"


def _utc_now_naive_seconds() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def fetch_quality_rows(conn, *, venue: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            asset_id,
            venue,
            interval_code,
            quality_status,
            quality_score,
            gap_events,
            missing_candles_total,
            small_gap_events,
            large_gap_events,
            latest_open_ts_utc,
            latest_close_ts_utc,
            freshness_lag_hours,
            rows_observed,
            expected_rows,
            coverage_ratio,
            notes
        FROM v_asset_interval_quality_v3
        WHERE venue = %s
        ORDER BY asset_id, interval_code
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue,))
        return list(cur.fetchall())


def write_quality_rows(
    conn,
    *,
    rows: list[dict[str, Any]],
    snapshot_ts_utc: datetime,
) -> int:
    if not rows:
        return 0

    sql = """
        INSERT INTO asset_interval_quality (
            asset_id,
            venue,
            interval_code,
            asof_ts_utc,
            quality_status,
            quality_score,
            gap_events,
            missing_candles_total,
            small_gap_events,
            large_gap_events,
            latest_open_ts_utc,
            latest_close_ts_utc,
            freshness_lag_hours,
            rows_observed,
            expected_rows,
            coverage_ratio,
            notes
        )
        VALUES (
            %(asset_id)s,
            %(venue)s,
            %(interval_code)s,
            %(asof_ts_utc)s,
            %(quality_status)s,
            %(quality_score)s,
            %(gap_events)s,
            %(missing_candles_total)s,
            %(small_gap_events)s,
            %(large_gap_events)s,
            %(latest_open_ts_utc)s,
            %(latest_close_ts_utc)s,
            %(freshness_lag_hours)s,
            %(rows_observed)s,
            %(expected_rows)s,
            %(coverage_ratio)s,
            %(notes)s
        )
        ON DUPLICATE KEY UPDATE
            quality_status = VALUES(quality_status),
            quality_score = VALUES(quality_score),
            gap_events = VALUES(gap_events),
            missing_candles_total = VALUES(missing_candles_total),
            small_gap_events = VALUES(small_gap_events),
            large_gap_events = VALUES(large_gap_events),
            latest_open_ts_utc = VALUES(latest_open_ts_utc),
            latest_close_ts_utc = VALUES(latest_close_ts_utc),
            freshness_lag_hours = VALUES(freshness_lag_hours),
            rows_observed = VALUES(rows_observed),
            expected_rows = VALUES(expected_rows),
            coverage_ratio = VALUES(coverage_ratio),
            notes = VALUES(notes)
    """

    payload = []
    for row in rows:
        payload.append(
            {
                "asset_id": row["asset_id"],
                "venue": row["venue"],
                "interval_code": row["interval_code"],
                "asof_ts_utc": snapshot_ts_utc,
                "quality_status": row["quality_status"],
                "quality_score": row["quality_score"],
                "gap_events": row["gap_events"],
                "missing_candles_total": row["missing_candles_total"],
                "small_gap_events": row["small_gap_events"],
                "large_gap_events": row["large_gap_events"],
                "latest_open_ts_utc": row["latest_open_ts_utc"],
                "latest_close_ts_utc": row["latest_close_ts_utc"],
                "freshness_lag_hours": row["freshness_lag_hours"],
                "rows_observed": row["rows_observed"],
                "expected_rows": row["expected_rows"],
                "coverage_ratio": row["coverage_ratio"],
                "notes": row["notes"],
            }
        )

    with conn.cursor() as cur:
        cur.executemany(sql, payload)

    conn.commit()
    return len(payload)


def print_table(rows: list[dict[str, Any]], *, snapshot_ts_utc: datetime) -> None:
    headers = [
        "snapshot_ts_utc",
        "asset_id",
        "venue",
        "interval",
        "status",
        "score",
        "gaps",
        "missing",
        "small",
        "large",
        "coverage",
        "latest_open",
        "lag_h",
    ]

    table_rows = []
    for row in rows:
        table_rows.append(
            [
                _fmt(snapshot_ts_utc),
                _fmt(row.get("asset_id")),
                _fmt(row.get("venue")),
                _fmt(row.get("interval_code")),
                _fmt(row.get("quality_status")),
                _fmt(row.get("quality_score")),
                _fmt(row.get("gap_events")),
                _fmt(row.get("missing_candles_total")),
                _fmt(row.get("small_gap_events")),
                _fmt(row.get("large_gap_events")),
                _fmt(row.get("coverage_ratio")),
                _fmt(row.get("latest_open_ts_utc")),
                _fmt(row.get("freshness_lag_hours")),
            ]
        )

    widths = [
        max(len(str(header)), *(len(str(row[index])) for row in table_rows))
        if table_rows
        else len(str(header))
        for index, header in enumerate(headers)
    ]

    print(" | ".join(str(header).ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for row in table_rows:
        print(" | ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize latest asset interval quality into asset_interval_quality."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    args = parser.parse_args()

    snapshot_ts_utc = _utc_now_naive_seconds()

    conn = get_connection()
    try:
        rows = fetch_quality_rows(conn, venue=args.venue)

        if args.output == "table":
            print_table(rows, snapshot_ts_utc=snapshot_ts_utc)

        written = 0
        if args.write_db:
            written = write_quality_rows(
                conn,
                rows=rows,
                snapshot_ts_utc=snapshot_ts_utc,
            )

        print(
            "[DONE] "
            f"engine={ENGINE_NAME} "
            f"version={ENGINE_VERSION} "
            f"venue={args.venue} "
            f"snapshot_ts_utc={snapshot_ts_utc.isoformat(sep=' ')} "
            f"rows={len(rows)} "
            f"written={written} "
            f"write_db={args.write_db}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
