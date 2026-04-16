from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.common.db import get_db_connection


PIPELINE_NAME = "refresh_pipeline"
DEFAULT_INTERVALS = ("1h", "4h", "1d")
DEFAULT_VENUE = "bitvavo"


@dataclass(frozen=True)
class IntervalPlan:
    interval_code: str
    enabled: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="State-aware refresh pipeline for closed-candle processing."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", action="append", default=None)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if no new closed candle is detected.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without executing subprocess steps.",
    )
    return parser.parse_args()


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def get_latest_closed_candle_ts(
    conn,
    *,
    venue: str,
    interval_code: str,
    asset_id: int | None,
) -> datetime | None:
    where = [
        "venue = %s",
        "interval_code = %s",
    ]
    params: list[Any] = [venue, interval_code]

    if asset_id is not None:
        where.append("asset_id = %s")
        params.append(asset_id)

    where_sql = " AND ".join(where)

    sql = f"""
    SELECT MAX(close_ts_utc) AS max_close_ts_utc
    FROM obs_market_candle
    WHERE {where_sql}
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    if not row:
        return None

    value = row["max_close_ts_utc"] if isinstance(row, dict) else None
    return _ensure_utc(value)


def get_last_processed_ts(
    conn,
    *,
    pipeline_name: str,
    interval_code: str,
) -> datetime | None:
    sql = """
    SELECT last_processed_ts_utc
    FROM pipeline_state
    WHERE pipeline_name = %s
      AND interval_code = %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, [pipeline_name, interval_code])
        row = cur.fetchone()

    if not row:
        return None

    value = row["last_processed_ts_utc"] if isinstance(row, dict) else None
    return _ensure_utc(value)


def upsert_last_processed_ts(
    conn,
    *,
    pipeline_name: str,
    interval_code: str,
    last_processed_ts_utc: datetime,
) -> None:
    sql = """
    INSERT INTO pipeline_state (
        pipeline_name,
        interval_code,
        last_processed_ts_utc
    ) VALUES (
        %s,
        %s,
        %s
    )
    ON DUPLICATE KEY UPDATE
        last_processed_ts_utc = VALUES(last_processed_ts_utc)
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            [
                pipeline_name,
                interval_code,
                last_processed_ts_utc.replace(tzinfo=None),
            ],
        )

    conn.commit()


def run_subprocess(cmd: list[str], *, dry_run: bool) -> None:
    print(f"[STEP] {' '.join(cmd)}")

    if dry_run:
        return

    subprocess.run(cmd, check=True)


def maybe_run_interval(
    *,
    venue: str,
    interval_code: str,
    asset_id: int | None,
    force: bool,
    dry_run: bool,
) -> bool:
    conn = get_db_connection()

    try:
        latest_closed = get_latest_closed_candle_ts(
            conn,
            venue=venue,
            interval_code=interval_code,
            asset_id=asset_id,
        )
        last_processed = get_last_processed_ts(
            conn,
            pipeline_name=PIPELINE_NAME,
            interval_code=interval_code,
        )

        print(
            f"[CHECK] interval={interval_code} "
            f"latest_closed={latest_closed} "
            f"last_processed={last_processed}"
        )

        should_run = force

        if latest_closed is None:
            print(f"[SKIP] interval={interval_code} reason=no_candle_data")
            return False

        if not should_run:
            if last_processed is None:
                should_run = True
            elif latest_closed > last_processed:
                should_run = True

        if not should_run:
            print(f"[SKIP] interval={interval_code} reason=up_to_date")
            return False

        run_subprocess(
            [
                sys.executable,
                "-m",
                "src.features.run_feat_candle",
                "--interval",
                interval_code,
                *([] if asset_id is None else ["--asset", str(asset_id)]),
            ],
            dry_run=dry_run,
        )

        run_subprocess(
            [
                sys.executable,
                "-m",
                "src.measurement.run_structure_state_engine",
                "--venue",
                venue,
                "--interval",
                interval_code,
                *([] if asset_id is None else ["--asset-id", str(asset_id)]),
            ],
            dry_run=dry_run,
        )

        run_subprocess(
            [
                sys.executable,
                "-m",
                "src.engine.run_signal_engine",
                "--venue",
                venue,
                "--interval",
                interval_code,
                *([] if asset_id is None else ["--asset-id", str(asset_id)]),
            ],
            dry_run=dry_run,
        )

        run_subprocess(
            [
                sys.executable,
                "-m",
                "src.advice.run_advice_engine",
                "--venue",
                venue,
                "--interval",
                interval_code,
                *([] if asset_id is None else ["--asset-id", str(asset_id)]),
            ],
            dry_run=dry_run,
        )

        run_subprocess(
            [
                sys.executable,
                "-m",
                "src.ranking.run_ranking_engine",
                "--venue",
                venue,
                "--interval",
                interval_code,
                *([] if asset_id is None else ["--asset-id", str(asset_id)]),
            ],
            dry_run=dry_run,
        )

        run_subprocess(
            [
                sys.executable,
                "-m",
                "src.selection.run_selection_engine",
                "--venue",
                venue,
                *([] if asset_id is None else ["--asset-id", str(asset_id)]),
            ],
            dry_run=dry_run,
        )

        if not dry_run:
            upsert_last_processed_ts(
                conn,
                pipeline_name=PIPELINE_NAME,
                interval_code=interval_code,
                last_processed_ts_utc=latest_closed,
            )

        print(
            f"[DONE] interval={interval_code} "
            f"processed_ts={latest_closed}"
        )
        return True

    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    intervals = tuple(args.interval) if args.interval else DEFAULT_INTERVALS

    ran_any = False

    for interval_code in intervals:
        did_run = maybe_run_interval(
            venue=args.venue,
            interval_code=interval_code,
            asset_id=args.asset_id,
            force=args.force,
            dry_run=args.dry_run,
        )
        ran_any = ran_any or did_run

    print(f"[SUMMARY] ran_any={ran_any}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
