from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from src.common.db import get_connection
from src.research.run_sector_rotation_engine_v1 import compute_asof, parse_utc_hour
from src.research.sector_rotation_data_v1 import (
    MIGRATION_PATH,
    ReconciliationCounts,
    acquire_write_lock,
    build_reconciliation_counts,
    check_schema,
    fetch_existing_hashes,
    release_write_lock,
    write_snapshots,
)
from src.research.sector_rotation_engine_v1 import MODEL_VERSION, WINDOW_ORDER


RUNNER_NAME = "sector_rotation_replay_v1"
DEFAULT_VENUE = "bitvavo"


def iter_asof_timestamps(
    start_ts_utc: datetime,
    end_ts_utc: datetime,
    step_hours: int,
) -> tuple[datetime, ...]:
    if step_hours <= 0:
        raise ValueError("step-hours must be > 0")
    if end_ts_utc < start_ts_utc:
        raise ValueError("end-as-of must be >= start-as-of")
    result = []
    cursor = start_ts_utc
    while cursor <= end_ts_utc:
        result.append(cursor)
        cursor += timedelta(hours=step_hours)
    return tuple(result)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Point-in-time historical replay for Sector Rotation Engine v1"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-db", action="store_true")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--start-as-of", default=None)
    parser.add_argument("--end-as-of", default=None)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--window", action="append", choices=list(WINDOW_ORDER), default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "validate-only" if args.validate_only else ("dry-run" if args.dry_run else "write-db")
    started = time.perf_counter()
    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} scope=historical-sector-replay workers=1",
        flush=True,
    )
    print(
        "SAFETY broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        flush=True,
    )
    if args.validate_only:
        print(
            f"MODEL model_version={MODEL_VERSION} windows={','.join(args.window or WINDOW_ORDER)} "
            f"point_in_time_candles=required taxonomy_validity=required "
            f"persistence_source=persisted_snapshots_only migration={MIGRATION_PATH}"
        )
        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} db_connections=0 db_writes=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0

    if not args.start_as_of or not args.end_as_of:
        print(
            f"FAILED runner={RUNNER_NAME} mode={mode} "
            "reason=ValueError:start-as-of_and_end-as-of_are_required db_writes=0"
        )
        return 1

    conn = None
    lock_acquired = False
    try:
        timestamps = iter_asof_timestamps(
            parse_utc_hour(args.start_as_of),
            parse_utc_hour(args.end_as_of),
            args.step_hours,
        )
        windows = tuple(args.window or WINDOW_ORDER)
        conn = get_connection()
        missing_source, target_present = check_schema(conn)
        if missing_source:
            raise RuntimeError(f"SOURCE_SCHEMA_MISSING:{','.join(missing_source)}")
        if args.write_db and not target_present:
            raise RuntimeError(f"MIGRATION_REQUIRED:{MIGRATION_PATH}")
        if args.write_db:
            acquire_write_lock(conn)
            lock_acquired = True
        generated_ts = datetime.now(UTC).replace(tzinfo=None)
        totals = ReconciliationCounts()
        total_rows = 0
        print(
            f"PHASE_START name=replay timestamps={len(timestamps)} "
            f"start={timestamps[0].isoformat()}Z end={timestamps[-1].isoformat()}Z "
            f"step_hours={args.step_hours} windows={','.join(windows)} "
            f"target_table_present={int(target_present)}",
            flush=True,
        )
        for index, asof_ts_utc in enumerate(timestamps, start=1):
            result = compute_asof(
                conn,
                venue=args.venue,
                asof_ts_utc=asof_ts_utc,
                window_codes=windows,
                target_table_present=target_present,
            )
            existing = fetch_existing_hashes(
                conn, result.snapshots, target_table_present=target_present
            )
            counts = build_reconciliation_counts(result.snapshots, existing)
            if args.write_db:
                counts = write_snapshots(
                    conn,
                    result.snapshots,
                    existing,
                    generated_ts_utc=generated_ts,
                )
            totals += counts
            total_rows += len(result.snapshots)
            states = Counter(row.rotation_state for row in result.snapshots)
            print(
                f"REPLAY asof_ts_utc={asof_ts_utc.isoformat()}Z rows={len(result.snapshots)} "
                f"inserts={counts.inserts} updates={counts.updates} unchanged={counts.unchanged} "
                f"insufficient={states['INSUFFICIENT_PARTICIPATION']} "
                f"unavailable={states['DATA_UNAVAILABLE']}",
                flush=True,
            )
            if index % 10 == 0 or index == len(timestamps):
                print(
                    f"HEARTBEAT completed={index}/{len(timestamps)} rows={total_rows} "
                    f"elapsed_s={time.perf_counter() - started:.3f}",
                    flush=True,
                )
        if args.write_db:
            conn.commit()
            transaction = "committed"
        else:
            conn.rollback()
            transaction = "rolled_back"
        print(
            f"PHASE_END name=replay rows={total_rows} inserts={totals.inserts} "
            f"updates={totals.updates} unchanged={totals.unchanged} stale={totals.stale}"
        )
        if not target_present:
            print(f"TARGET_SCHEMA status=missing migration={MIGRATION_PATH}")
        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} transaction={transaction} "
            f"db_writes={int(args.write_db)} rows={total_rows} "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        print(
            f"FAILED runner={RUNNER_NAME} mode={mode} reason={type(exc).__name__}:{exc} "
            f"db_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            if lock_acquired:
                try:
                    release_write_lock(conn)
                except Exception as exc:
                    print(f"LOCK_RELEASE_WARNING reason={type(exc).__name__}:{exc}")
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
