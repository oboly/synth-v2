"""
run_held_market_coverage_health_check_v1 -- Read-only invariant check
(Issue #238 follow-up):

    every resolvable positive wallet holding (across every linked trading
    account) must have either fresh canonical 4h context, or one precise
    non-resolvable/non-publishable reason.

Never mutates any table. Never invokes the canonical Fib writer or the
enrollment script. Exits non-zero (fail-closed) when any resolvable held
symbol has a coverage gap, so this can be wired into a scheduled check
without silently going green.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from src.common.db import get_connection
from src.market_data.canonical_fib_zone_map_v1 import (
    AVAILABLE_STATES,
    DEFAULT_LOOKBACK_CANDLES,
    DEFAULT_STALE_AFTER,
)
from src.market_data.held_market_coverage_v1 import (
    SAFETY_MARKERS,
    classify_held_coverage,
    coverage_check_passes,
    resolve_held_markets,
    summarize_coverage,
)
from src.market_data.run_held_market_enrollment_v1 import (
    DEFAULT_QUOTE_CURRENCY,
    DEFAULT_VENUE,
    fetch_asset_registry,
    fetch_latest_positive_balances,
)

RUNNER_NAME = "held_market_coverage_health_check_v1"
RUNNER_VERSION = "0.1"
MIN_REQUIRED_CANDLES = 60


def emit(message: str) -> None:
    print(message, flush=True)


def fetch_candle_counts_by_symbol(conn: Any, *, venue: str, interval_code: str, symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT a.symbol, COUNT(*) AS n
    FROM obs_market_candle c
    JOIN asset a ON a.asset_id = c.asset_id
    WHERE c.venue = %s AND c.interval_code = %s AND a.symbol IN ({placeholders})
    GROUP BY a.symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, *symbols))
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): int(row["n"]) for row in rows}


def fetch_canonical_rows_by_symbol(conn: Any, *, venue: str, quote_currency: str, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT *
    FROM canonical_fib_zone_map_latest_v1
    WHERE venue = %s AND quote_currency = %s AND symbol IN ({placeholders})
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, quote_currency, *symbols))
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): dict(row) for row in rows}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote-currency", default=DEFAULT_QUOTE_CURRENCY)
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--min-candles", type=int, default=MIN_REQUIRED_CANDLES)
    parser.add_argument("--stale-after-hours", type=float, default=DEFAULT_STALE_AFTER.total_seconds() / 3600)
    parser.add_argument(
        "--check",
        choices=("enrollment", "publication", "all"),
        default="all",
        help=(
            "Which invariant gates the exit code. 'enrollment' passes once every "
            "resolvable held asset has asset.is_portfolio/is_core_sensor set, "
            "even if its canonical 4h context is not yet published (e.g. still "
            "waiting for the next chain-4h cycle). 'publication' (and the "
            "default 'all') additionally requires fresh canonical 4h context to "
            "actually exist -- a known gap such as SOL/VET map-status-"
            "unavailable keeps failing this check and must never be treated as "
            "acceptable just because enrollment succeeded."
        ),
    )
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now_utc = datetime.now(UTC)
    stale_after = timedelta(hours=args.stale_after_hours)
    emit(f"STARTED {RUNNER_NAME} v{RUNNER_VERSION} venue={args.venue} ts={now_utc.isoformat()}")

    conn = get_connection()
    try:
        balances = fetch_latest_positive_balances(conn, venue=args.venue)
        asset_registry_by_symbol = fetch_asset_registry(conn)
        resolutions = resolve_held_markets(
            held_balances=balances,
            quote_currency=args.quote_currency,
            asset_registry_by_symbol=asset_registry_by_symbol,
        )
        resolvable_symbols = sorted({r.symbol for r in resolutions if r.resolvable and r.symbol})
        candle_count_by_symbol = fetch_candle_counts_by_symbol(
            conn, venue=args.venue, interval_code=args.interval, symbols=resolvable_symbols
        )
        canonical_row_by_symbol = fetch_canonical_rows_by_symbol(
            conn, venue=args.venue, quote_currency=args.quote_currency, symbols=resolvable_symbols
        )
    finally:
        conn.close()

    statuses = [
        classify_held_coverage(
            resolution,
            candle_count_by_symbol=candle_count_by_symbol,
            canonical_row_by_symbol=canonical_row_by_symbol,
            min_required_candles=args.min_candles,
            available_map_statuses=AVAILABLE_STATES,
            now_utc=now_utc,
            stale_after=stale_after,
        )
        for resolution in resolutions
    ]
    def _row(s: Any) -> dict[str, Any]:
        return {
            "currency_code": s.currency_code,
            "symbol": s.symbol,
            "market": s.market,
            "reason": s.reason,
            "candle_count": s.candle_count,
            "map_status": s.map_status,
            "held_by": list(s.held_by_account_codes),
        }

    coverage = summarize_coverage(statuses)
    publication_gaps = list(coverage.publication_gaps)
    publication_pass = coverage.publication_pass
    enrollment_gaps = list(coverage.enrollment_gaps)
    enrollment_pass = coverage.enrollment_pass

    summary = {
        "report": RUNNER_NAME,
        "version": RUNNER_VERSION,
        "generated_ts_utc": now_utc.isoformat(),
        "held_symbol_count": len(statuses),
        "ok_count": len(statuses) - len(publication_gaps),
        "gap_count": len(publication_gaps),
        "gaps": [_row(s) for s in publication_gaps],
        "enrollment": {
            "status": "PASS" if enrollment_pass else "FAIL",
            "gap_count": len(enrollment_gaps),
            "gaps": [_row(s) for s in enrollment_gaps],
        },
        "publication": {
            "status": "PASS" if publication_pass else "FAIL",
            "gap_count": len(publication_gaps),
            "gaps": [_row(s) for s in publication_gaps],
        },
        "check": args.check,
        **SAFETY_MARKERS,
    }

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        emit(f"held_symbol_count={summary['held_symbol_count']} ok={summary['ok_count']} gap={summary['gap_count']}")
        emit(f"enrollment_status={summary['enrollment']['status']} enrollment_gap_count={summary['enrollment']['gap_count']}")
        emit(f"publication_status={summary['publication']['status']} publication_gap_count={summary['publication']['gap_count']}")
        for row in summary["gaps"]:
            emit(f"  GAP {row['currency_code']} reason={row['reason']} held_by={row['held_by']}")

    failed = not coverage_check_passes(coverage, check=args.check)

    status_word = "FAILED" if failed else "FINISHED"
    emit(f"{status_word} {RUNNER_NAME} check={args.check} ts={datetime.now(UTC).isoformat()}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
