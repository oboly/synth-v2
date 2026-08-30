from __future__ import annotations

"""Read-only, whole-universe public candle coverage health check (Issue #606).

Answers a question the per-symbol freshness check in
``persisted_market_candle_freshness_v1.py`` cannot: is a gap isolated to a
handful of symbols/markets, or is it systemic across the whole enabled
Bitvavo universe (a stalled/failed writer)? The 2026-08-29/30 incident
(ICP-EUR 1h/4h reported stale) turned out to be the latter -- every enabled
market on every interval stalled at the same boundary because the canonical
writer checkout failed its authorization guard, not an ICP-specific or
aggregation-specific bug. This runner makes that distinction visible without
requiring anyone to eyeball hundreds of per-symbol rows.

Read-only: one SELECT-only transaction against the local database. No
network/exchange calls, no writes, no broker/account access.

database_writes=0 public_exchange_calls=0 broker_private_calls=0
broker_writes=0 order_submission=0 live_orders=0 decision_gate=none
execution_planner=none executor=none
"""

import argparse
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection
from src.common.utc import utc_now
from src.etl.bitvavo.etl_bitvavo_candles import floor_to_interval
from src.operations.persisted_market_candle_freshness_v1 import (
    CURRENT,
    SOURCE_UNAVAILABLE,
    UniverseCandleCoverage,
    classify_universe_candle_coverage,
    fetch_universe_latest_close_by_symbol,
)

RUNNER_NAME = "run_public_candle_coverage_health_check_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVALS = ["1h", "4h"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "SELECT-only whole-universe candle coverage check: distinguishes "
            "CURRENT / PARTIAL_COVERAGE / STALE / MISSING / WRITER_FAILED / "
            "SOURCE_UNAVAILABLE for the enabled asset universe."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--interval",
        action="append",
        dest="intervals",
        default=None,
        help="Repeatable. Defaults to 1h and 4h.",
    )
    return parser.parse_args(argv)


def fetch_enabled_symbols(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM asset WHERE is_enabled = 1 ORDER BY symbol")
        rows = cur.fetchall()
    return [str(row["symbol"]).upper() for row in rows]


def _format_utc_z(value: datetime | None) -> str:
    if value is None:
        return "not_available"
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_coverage(coverage: UniverseCandleCoverage) -> None:
    print(
        f"interval={coverage.interval_code} overall_state={coverage.overall_state} "
        f"reason={coverage.reason} "
        f"expected_close_ts_utc={_format_utc_z(coverage.expected_close_ts_utc)} "
        f"universe_size={coverage.universe_size} "
        f"current_count={coverage.current_count} "
        f"stale_count={coverage.stale_count} "
        f"missing_count={coverage.missing_count} "
        f"dominant_lag_close_ts_utc={_format_utc_z(coverage.dominant_lag_close_ts_utc)} "
        f"dominant_lag_symbol_count={coverage.dominant_lag_symbol_count}"
    )


def emit_source_unavailable(interval_code: str, reason: str) -> None:
    print(
        f"interval={interval_code} overall_state={SOURCE_UNAVAILABLE} reason={reason} "
        "expected_close_ts_utc=not_available universe_size=0 current_count=0 "
        "stale_count=0 missing_count=0 dominant_lag_close_ts_utc=not_available "
        "dominant_lag_symbol_count=0"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    intervals = args.intervals or DEFAULT_INTERVALS
    now = utc_now().astimezone(UTC)

    print(
        f"runner={RUNNER_NAME} version={RUNNER_VERSION} mode=select_only "
        f"venue={args.venue} intervals={','.join(intervals)} now_utc={_format_utc_z(now)}"
    )

    conn = None
    overall_states: list[str] = []
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION READ ONLY")
        symbols = fetch_enabled_symbols(conn)
        if not symbols:
            emit_source_unavailable("ALL", "NO_ENABLED_ASSETS")
            print("database_writes=0 public_exchange_calls=0 broker_private_calls=0 broker_writes=0")
            return 1

        for interval_code in intervals:
            expected_close_ts_utc = floor_to_interval(now, interval_code)
            symbol_latest_close = fetch_universe_latest_close_by_symbol(
                conn,
                venue=args.venue,
                interval_code=interval_code,
                symbols=symbols,
            )
            coverage = classify_universe_candle_coverage(
                interval_code=interval_code,
                expected_close_ts_utc=expected_close_ts_utc,
                symbol_latest_close=symbol_latest_close,
            )
            emit_coverage(coverage)
            overall_states.append(coverage.overall_state)
    except Exception as exc:
        for interval_code in intervals:
            emit_source_unavailable(interval_code, f"{exc.__class__.__name__}:{exc}")
        overall_states = [SOURCE_UNAVAILABLE]
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()

    print("database_writes=0 public_exchange_calls=0 broker_private_calls=0 broker_writes=0")
    return 0 if overall_states and all(state in (CURRENT,) for state in overall_states) else 1


if __name__ == "__main__":
    raise SystemExit(main())
